from dataclasses import dataclass
from typing import Optional, TypeVar
from datetime import datetime
import html
import re
import tiktoken
from openai import OpenAI
from loguru import logger
import json
RawPaperItem = TypeVar('RawPaperItem')


# The 6P speed-reading framework used for every TLDR. construct_email.py parses
# these labels back out of Paper.tldr to render the structured layout, so keep
# the two files in sync if you change them.
TLDR_LABELS = ("Problem", "Premise", "Perturbation", "Principle", "Proof", "Push")


def resolve_generation_kwargs(llm_params: dict) -> dict:
    """Merge llm.generation_kwargs with llm.generation_overrides.

    The GitHub Actions workflow overwrites config/custom.yaml wholesale with the
    CUSTOM_CONFIG repository variable, so keys set there (e.g. an outdated model
    name) cannot be fixed from the repo. base.yaml's generation_overrides wins
    over generation_kwargs, which lets the repo pin the actual model in code.
    """
    kwargs = dict(llm_params.get('generation_kwargs', None) or {})
    overrides = llm_params.get('generation_overrides', None)
    if overrides:
        kwargs.update(dict(overrides))
    return kwargs


def clean_tldr_text(text: Optional[str]) -> str:
    """Normalize raw model output to plain text.

    The model is instructed to return plain text, but unstable providers leak
    HTML tags, markdown markers or LaTeX commands. Strip all of it here so the
    email renderer only ever receives plain text (it does its own escaping).
    """
    if not text:
        return ""
    t = html.unescape(text)
    # code fences and markdown emphasis/heading markers
    t = re.sub(r"```[a-zA-Z]*", "", t)
    t = re.sub(r"\*\*|__|(?<![a-zA-Z0-9])[#`]+", "", t)
    # HTML tags, comment markers, and any leftover angle brackets — the
    # summaries are prose, so stray '<'/'>' are never legitimate content
    t = re.sub(r"<[^<>]{0,80}>", " ", t)
    t = t.replace("<!--", " ").replace("-->", " ")
    t = re.sub(r"[<>]", " ", t)
    # LaTeX: \command{content} -> content, then stray \command and '$'
    t = re.sub(r"\\[a-zA-Z]+\{([^{}]*)\}", r"\1", t)
    t = re.sub(r"\\[a-zA-Z]+", " ", t)
    t = t.replace("\\", " ").replace("$", "")
    # collapse whitespace per line, drop empty lines
    lines = [re.sub(r"[ \t 　]+", " ", line).strip() for line in t.splitlines()]
    return "\n".join(line for line in lines if line)


def looks_garbled(text: str) -> bool:
    """Heuristics for the broken-LLM failure mode seen in production:
    duplicated CJK characters (和和和), replacement chars, mangled markup, or
    output that lost the required 6P structure."""
    if not text:
        return True
    if "�" in text:
        return True
    # a CJK char repeated 3+ times in a row is essentially never legitimate
    if re.search(r"([一-鿿])\1{2}", text):
        return True
    # many distinct doubled CJK chars (legit words like 渐渐 exist, but several
    # in one short summary indicates token-level corruption)
    if len(re.findall(r"([一-鿿])\1", text)) >= 4:
        return True
    found_labels = sum(
        1 for label in TLDR_LABELS
        if re.search(rf"^{label}\s*[:：]", text, flags=re.MULTILINE)
    )
    return found_labels < 4


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
        lang = llm_params.get('language', '中文')

        prompt = "论文信息如下。\n\n"
        if self.title:
            prompt += f"标题：\n{self.title}\n\n"
        if self.abstract:
            prompt += f"摘要：\n{self.abstract}\n\n"
        if self.full_text:
            prompt += f"正文（可能被截断）：\n{self.full_text}\n\n"

        if not self.full_text and not self.abstract:
            logger.warning(f"Neither full text nor abstract is provided for {self.url}")
            return "Failed to generate TLDR. Neither full text nor abstract is provided"

        # use gpt-4o tokenizer for estimation; cap the (often messy LaTeX)
        # full text so a weak provider is not pushed past its usable context
        enc = tiktoken.encoding_for_model("gpt-4o")
        prompt_tokens = enc.encode(prompt)
        prompt_tokens = prompt_tokens[:8000]  # truncate to 8000 tokens
        prompt = enc.decode(prompt_tokens)

        system_prompt = (
            f"你是一位帮研究者做论文速读的助手。请按以下六个分析维度输出论文速读，"
            f"内容用{lang}，标签保持英文原样。只输出纯文本：每个维度一行，行首是标签后跟中文冒号，"
            "禁止任何 HTML 标签、Markdown 符号、LaTeX 命令、项目符号，也不要任何开场白或结尾。\n\n"
            "Problem：这篇工作要解决的真正瓶颈是什么？\n"
            "Premise：方法成立依赖哪些关键假设？\n"
            "Perturbation：相对已有工作改动了什么？最大的改动发生在哪一层（数据/表示/架构/目标/训练流程/评测）？\n"
            "Principle：为什么这个改动应该有效？背后的机理是什么？\n"
            "Proof：实验证据是否把效果归因到了这个改动上（消融/对照是否干净）？关键数字是什么？\n"
            "Push：下一步最自然的延伸是什么？\n\n"
            "每行 1-3 句，写实、具体，不要套话。如果某个维度论文没有给出信息，就写：原文未明确。"
        )

        gen_kwargs = resolve_generation_kwargs(llm_params)
        last_tldr = None
        for attempt in range(2):
            response = openai_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                **gen_kwargs
            )
            last_tldr = clean_tldr_text(response.choices[0].message.content)
            if not looks_garbled(last_tldr):
                return last_tldr
            logger.warning(
                f"TLDR of {self.url} looks garbled (attempt {attempt + 1}/2): {last_tldr[:80]!r}"
            )
        raise ValueError("model kept returning garbled TLDR output")

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
                **resolve_generation_kwargs(llm_params)
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
