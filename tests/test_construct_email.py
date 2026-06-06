"""Tests for zotero_arxiv_daily.construct_email: render_email, get_relevance_pill, get_block_html, parse_tldr_sections."""

from zotero_arxiv_daily.construct_email import (
    render_email,
    get_relevance_pill,
    get_block_html,
    get_empty_html,
    get_tldr_html,
    parse_tldr_sections,
)
from tests.canned_responses import make_sample_paper, SAMPLE_TLDR_6P


def test_render_email_with_papers():
    papers = [make_sample_paper(score=7.5, tldr="A great paper.", affiliations=["MIT"])]
    html = render_email(papers)
    assert "Sample Paper Title" in html
    assert "A great paper." in html
    assert "MIT" in html


def test_render_email_empty_list():
    html = render_email([])
    assert "没有过线的新论文" in html


def test_render_email_author_truncation():
    authors = [f"Author {i}" for i in range(10)]
    paper = make_sample_paper(authors=authors, score=7.0, tldr="ok")
    html = render_email([paper])
    assert "Author 0" in html
    assert "Author 1" in html
    assert "Author 2" in html
    assert "..." in html
    assert "Author 8" in html
    assert "Author 9" in html
    # Middle authors should be truncated
    assert "Author 5" not in html


def test_render_email_affiliation_truncation():
    affiliations = [f"Uni {i}" for i in range(8)]
    paper = make_sample_paper(affiliations=affiliations, score=7.0, tldr="ok")
    html = render_email([paper])
    assert "Uni 0" in html
    assert "Uni 4" in html
    assert "..." in html
    assert "Uni 7" not in html


def test_render_email_no_affiliations_renders_nothing():
    paper = make_sample_paper(affiliations=None, score=7.0, tldr="ok")
    html = render_email([paper])
    # 提取失败时不再显示"机构未知"占位文案
    assert "机构未知" not in html


def test_render_email_shows_score():
    paper = make_sample_paper(score=5.8, tldr="ok")
    html = render_email([paper])
    assert "相关度 5.8" in html


def test_render_email_escapes_html_in_title():
    paper = make_sample_paper(title="Attention <Is> All & You Need", score=5.0, tldr="ok")
    html = render_email([paper])
    assert "Attention &lt;Is&gt; All &amp; You Need" in html


def test_get_relevance_pill_tiers():
    assert "#1a7f37" in get_relevance_pill(5.2)  # green tier
    assert "#1a56c4" in get_relevance_pill(4.7)  # blue tier
    assert "#9a6700" in get_relevance_pill(4.3)  # amber tier
    assert "相关度 4.3" in get_relevance_pill(4.3)


def test_get_relevance_pill_none():
    pill = get_relevance_pill(None)
    assert "未知" in pill


def test_parse_tldr_sections_full():
    sections = parse_tldr_sections(SAMPLE_TLDR_6P)
    labels = [label for label, _ in sections]
    assert labels == ["Problem", "Premise", "Perturbation", "Principle", "Proof", "Push"]
    assert all(content for _, content in sections)


def test_parse_tldr_sections_continuation_lines():
    text = "Problem：第一行\n续写的第二行\nProof：证据"
    sections = parse_tldr_sections(text)
    assert sections[0] == ("Problem", "第一行 续写的第二行")
    assert sections[1] == ("Proof", "证据")


def test_parse_tldr_sections_plain_text_returns_none():
    # 摘要回退（非 6P 格式）应返回 None，由调用方按普通段落渲染
    assert parse_tldr_sections("This is just a plain abstract about widgets.") is None
    assert parse_tldr_sections("") is None


def test_get_tldr_html_structured():
    html = get_tldr_html(SAMPLE_TLDR_6P)
    assert "Problem" in html
    assert "瓶颈" in html  # Chinese hint for the label
    assert "速读生成失败" not in html


def test_get_tldr_html_fallback_paragraph():
    html = get_tldr_html("Just an abstract.")
    assert "速读生成失败" in html
    assert "Just an abstract." in html


def test_get_tldr_html_escapes_content():
    html = get_tldr_html("Problem：a<b 且 x&y\nProof：ok")
    assert "a&lt;b" in html
    assert "x&amp;y" in html


def test_get_block_html_contains_all_fields():
    html = get_block_html(
        rank=1,
        title="Title",
        url="http://abs.url",
        authors="Auth",
        rate_html="PILL_MARKER",
        tldr="Summary",
        pdf_url="http://pdf.url",
        affiliations="MIT",
    )
    assert "Title" in html
    assert "Auth" in html
    assert "PILL_MARKER" in html
    assert "Summary" in html
    assert "http://pdf.url" in html
    assert "http://abs.url" in html
    assert "MIT" in html
    assert ">1<" in html  # rank badge


def test_get_block_html_without_pdf_url():
    html = get_block_html(
        rank=2,
        title="Title",
        url="http://abs.url",
        authors="Auth",
        rate_html="",
        tldr="Summary",
        pdf_url=None,
        affiliations=None,
    )
    assert "阅读 PDF" not in html
    assert "http://abs.url" in html


def test_get_empty_html():
    html = get_empty_html()
    assert "没有过线的新论文" in html
