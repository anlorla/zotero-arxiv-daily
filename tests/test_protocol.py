"""Tests for zotero_arxiv_daily.protocol: Paper.generate_tldr, Paper.generate_affiliations,
clean_tldr_text, looks_garbled, resolve_generation_kwargs."""

from types import SimpleNamespace

import pytest

from tests.canned_responses import SAMPLE_TLDR_6P, make_sample_paper, make_stub_openai_client
from zotero_arxiv_daily.protocol import clean_tldr_text, looks_garbled, resolve_generation_kwargs


@pytest.fixture()
def llm_params():
    return {
        "language": "English",
        "generation_kwargs": {"model": "gpt-4o-mini", "max_tokens": 16384},
    }


# ---------------------------------------------------------------------------
# generate_tldr
# ---------------------------------------------------------------------------


def test_tldr_returns_response(llm_params):
    client = make_stub_openai_client()
    paper = make_sample_paper()
    result = paper.generate_tldr(client, llm_params)
    assert result == SAMPLE_TLDR_6P
    assert paper.tldr == result


def test_tldr_without_abstract_or_fulltext(llm_params):
    client = make_stub_openai_client()
    paper = make_sample_paper(abstract="", full_text=None)
    result = paper.generate_tldr(client, llm_params)
    assert "Failed to generate TLDR" in result


def test_tldr_falls_back_to_abstract_on_error(llm_params):
    paper = make_sample_paper()

    # Client whose create() raises
    from types import SimpleNamespace

    broken_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(RuntimeError("API down")))
        )
    )
    result = paper.generate_tldr(broken_client, llm_params)
    assert result == paper.abstract


def test_tldr_truncates_long_prompt(llm_params):
    client = make_stub_openai_client()
    paper = make_sample_paper(full_text="word " * 10000)
    result = paper.generate_tldr(client, llm_params)
    assert result is not None


def test_tldr_garbled_output_retries_then_falls_back(llm_params):
    """A model that keeps emitting corrupted text: retry once, then fall back
    to the raw abstract instead of mailing garbage."""
    calls = []

    def create_garbled(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content="Problem：实现细粒度的空间和和和语言因果推理。"
            ))]
        )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_garbled))
    )
    paper = make_sample_paper()
    result = paper.generate_tldr(client, llm_params)
    assert len(calls) == 2  # one retry
    assert result == paper.abstract


def test_tldr_strips_markup_from_model_output(llm_params):
    """Leaked HTML/markdown markup is cleaned before rendering."""
    dirty = (
        "<!--<strong>Problem</strong>>：现有方法太慢。<br>\n"
        "**Premise**：假设分布平稳。\n"
        "Perturbation：换成线性注意力，改动在\\textbf{架构}层。\n"
        "Principle：复杂度从 $O(n^2)$ 降到线性。\n"
        "Proof：三个基准上快 2 倍。\n"
        "Push：扩展到多模态。"
    )

    def create_dirty(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=dirty))]
        )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_dirty))
    )
    paper = make_sample_paper()
    result = paper.generate_tldr(client, llm_params)
    assert "<" not in result and ">" not in result
    assert "**" not in result and "\\" not in result and "$" not in result
    assert "架构" in result  # \textbf{架构} keeps its content
    assert "Problem" in result and "Push" in result


# ---------------------------------------------------------------------------
# clean_tldr_text / looks_garbled / resolve_generation_kwargs
# ---------------------------------------------------------------------------


def test_clean_tldr_text_handles_none_and_empty():
    assert clean_tldr_text(None) == ""
    assert clean_tldr_text("") == ""


def test_clean_tldr_text_collapses_whitespace():
    assert clean_tldr_text("a   b　c\n\n\nd") == "a b c\nd"


def test_looks_garbled_accepts_clean_6p():
    assert not looks_garbled(SAMPLE_TLDR_6P)


def test_looks_garbled_rejects_corruption():
    # 真实事故样本的特征：叠字、replacement char、缺标签
    assert looks_garbled("Problem：在LIBERO和和和CALVIN基准上提升。")
    assert looks_garbled(SAMPLE_TLDR_6P + "�")
    assert looks_garbled("一句话：这是旧格式的摘要，没有 6P 标签。")
    assert looks_garbled("")


def test_resolve_generation_kwargs_overrides_win():
    params = {
        "generation_kwargs": {"model": "gpt-4o-mini", "max_tokens": 16384},
        "generation_overrides": {"model": "deepseek-ai/DeepSeek-V4-Flash", "temperature": 0.3},
    }
    kwargs = resolve_generation_kwargs(params)
    assert kwargs["model"] == "deepseek-ai/DeepSeek-V4-Flash"
    assert kwargs["temperature"] == 0.3
    assert kwargs["max_tokens"] == 16384


def test_resolve_generation_kwargs_without_overrides():
    params = {"generation_kwargs": {"model": "gpt-4o-mini"}}
    assert resolve_generation_kwargs(params) == {"model": "gpt-4o-mini"}


# ---------------------------------------------------------------------------
# generate_affiliations
# ---------------------------------------------------------------------------


def test_affiliations_returns_parsed_list(llm_params):
    client = make_stub_openai_client()
    paper = make_sample_paper()
    result = paper.generate_affiliations(client, llm_params)
    assert isinstance(result, list)
    assert "TsingHua University" in result
    assert "Peking University" in result


def test_affiliations_none_without_fulltext(llm_params):
    client = make_stub_openai_client()
    paper = make_sample_paper(full_text=None)
    result = paper.generate_affiliations(client, llm_params)
    assert result is None


def test_affiliations_deduplicates(llm_params):
    """The stub returns two distinct affiliations, so no dedup needed.
    But confirm the set() dedup in the code doesn't break anything.
    """
    client = make_stub_openai_client()
    paper = make_sample_paper()
    result = paper.generate_affiliations(client, llm_params)
    assert len(result) == len(set(result))


def test_affiliations_malformed_llm_output(llm_params):
    """LLM returns affiliations without JSON brackets. Should fall back gracefully."""
    from types import SimpleNamespace

    def create_no_brackets(**kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="TsingHua University, Peking University"),
                )
            ]
        )

    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create_no_brackets)
        )
    )
    paper = make_sample_paper()
    result = paper.generate_affiliations(client, llm_params)
    # re.search for [...] will fail -> AttributeError -> caught -> returns None
    assert result is None


def test_affiliations_error_returns_none(llm_params):
    from types import SimpleNamespace

    broken_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
        )
    )
    paper = make_sample_paper()
    result = paper.generate_affiliations(broken_client, llm_params)
    assert result is None
    assert paper.affiliations is None
