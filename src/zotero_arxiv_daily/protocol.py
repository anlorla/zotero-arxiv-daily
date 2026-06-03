from dataclasses import dataclass
from typing import Optional, TypeVar
from datetime import datetime
import re
import tiktoken
from openai import OpenAI
from loguru import logger
import json
RawPaperItem = TypeVar('RawPaperItem')


def _format_tldr_html(tldr: Optional[str]) -> str:
    """Make the model output safe to drop straight into the HTML email.

    The model is asked to use <strong> labels and <br> separators, but models
    sometimes fall back to markdown (**label**) or plain newlines. Normalize
    both so the structured layout always renders.
    """
    if not tldr:
        return tldr or ""
    text = tldr.strip()
    # markdown bold -> <strong>
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # if the model used newlines instead of <br>, convert the remaining ones
    text = re.sub(r"\n+", "<br>", text)
    return text


@dataclass
class Paper:
    source: str
    title: str
    authors: list[str]
    abstract: str
    url: str
    pdf_url: Optional[str] = None
    full_text: Optional[str] = None
    tldr: Optional[str] = None
    affiliations: Optional[list[str]] = None
    score: Optional[float] = None

    def _generate_tldr_with_llm(self, openai_client:OpenAI,llm_params:dict) -> str:
        lang = llm_params.get('language', 'English')

        prompt = "Here is the information of a paper.\n\n"
        if self.title:
            prompt += f"Title:\n{self.title}\n\n"
        if self.abstract:
            prompt += f"Abstract:\n{self.abstract}\n\n"
        if self.full_text:
            prompt += f"Main content (may be truncated):\n{self.full_text}\n\n"

        if not self.full_text and not self.abstract:
            logger.warning(f"Neither full text nor abstract is provided for {self.url}")
            return "Failed to generate TLDR. Neither full text nor abstract is provided"

        # use gpt-4o tokenizer for estimation. We now feed far fewer papers, so we can
        # afford a much larger context and produce a substantive, structured summary.
        enc = tiktoken.encoding_for_model("gpt-4o")
        prompt_tokens = enc.encode(prompt)
        prompt_tokens = prompt_tokens[:12000]  # truncate to 12000 tokens
        prompt = enc.decode(prompt_tokens)

        system_prompt = (
            f"你是一位帮研究者做论文速读的助手，回答必须用{lang}。"
            "请基于论文内容输出一段结构化速读摘要，严格按下面的格式：每个要点之间用 <br> 分隔，"
            "标签用 <strong> 包裹，不要使用 markdown 的 ** 号，也不要任何开场白或结尾。\n\n"
            "<strong>一句话</strong>：用一句话说清这篇论文最核心的贡献。<br>"
            "<strong>问题</strong>：它针对什么问题、为什么以前的做法不够好（1-2 句）。<br>"
            "<strong>做法</strong>：关键方法或核心想法，点出真正新颖之处，别堆术语（2-3 句）。<br>"
            "<strong>结果</strong>：主要实验结论或关键数字，有对比基线就写清楚（1-2 句）。<br>"
            "<strong>亮点</strong>：为什么值得读，新意或反直觉的点在哪，或有什么局限（1-2 句）。\n\n"
            "用平实的中文，讲清楚胜过堆砌名词。如果某个要点信息确实缺失，就如实写“原文未明确”。"
        )

        response = openai_client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            **llm_params.get('generation_kwargs', {})
        )
        tldr = response.choices[0].message.content
        return _format_tldr_html(tldr)
    
    def generate_tldr(self, openai_client:OpenAI,llm_params:dict) -> str:
        try:
            tldr = self._generate_tldr_with_llm(openai_client,llm_params)
            self.tldr = tldr
            return tldr
        except Exception as e:
            logger.warning(f"Failed to generate tldr of {self.url}: {e}")
            tldr = self.abstract
            self.tldr = tldr
            return tldr

    def _generate_affiliations_with_llm(self, openai_client:OpenAI,llm_params:dict) -> Optional[list[str]]:
        if self.full_text is not None:
            prompt = f"Given the beginning of a paper, extract the affiliations of the authors in a python list format, which is sorted by the author order. If there is no affiliation found, return an empty list '[]':\n\n{self.full_text}"
            # use gpt-4o tokenizer for estimation
            enc = tiktoken.encoding_for_model("gpt-4o")
            prompt_tokens = enc.encode(prompt)
            prompt_tokens = prompt_tokens[:2000]  # truncate to 2000 tokens
            prompt = enc.decode(prompt_tokens)
            affiliations = openai_client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": "You are an assistant who perfectly extracts affiliations of authors from a paper. You should return a python list of affiliations sorted by the author order, like [\"TsingHua University\",\"Peking University\"]. If an affiliation is consisted of multi-level affiliations, like 'Department of Computer Science, TsingHua University', you should return the top-level affiliation 'TsingHua University' only. Do not contain duplicated affiliations. If there is no affiliation found, you should return an empty list [ ]. You should only return the final list of affiliations, and do not return any intermediate results.",
                    },
                    {"role": "user", "content": prompt},
                ],
                **llm_params.get('generation_kwargs', {})
            )
            affiliations = affiliations.choices[0].message.content

            affiliations = re.search(r'\[.*?\]', affiliations, flags=re.DOTALL).group(0)
            affiliations = json.loads(affiliations)
            affiliations = list(set(affiliations))
            affiliations = [str(a) for a in affiliations]

            return affiliations
    
    def generate_affiliations(self, openai_client:OpenAI,llm_params:dict) -> Optional[list[str]]:
        try:
            affiliations = self._generate_affiliations_with_llm(openai_client,llm_params)
            self.affiliations = affiliations
            return affiliations
        except Exception as e:
            logger.warning(f"Failed to generate affiliations of {self.url}: {e}")
            self.affiliations = None
            return None
@dataclass
class CorpusPaper:
    title: str
    abstract: str
    added_date: datetime
    paths: list[str]