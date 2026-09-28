"""Tests for ArxivRetriever."""

import time
from types import SimpleNamespace

from zotero_arxiv_daily.retriever.arxiv_retriever import ArxivRetriever, _run_with_hard_timeout
import zotero_arxiv_daily.retriever.arxiv_retriever as arxiv_retriever


def _sleep_and_return(value: str, delay_seconds: float) -> str:
    time.sleep(delay_seconds)
    return value


def _raise_runtime_error() -> None:
    raise RuntimeError("boom")


def test_arxiv_retriever(config, mock_feedparser, monkeypatch):
    # Metadata comes straight from the RSS fixture; no arXiv API or downloads.
    def _no_network(*args, **kwargs):
        raise AssertionError("convert_to_paper must not touch the network")

    monkeypatch.setattr(arxiv_retriever, "extract_text_from_html", _no_network)
    monkeypatch.setattr(arxiv_retriever, "extract_text_from_pdf", _no_network)
    monkeypatch.setattr(arxiv_retriever, "extract_text_from_tar", _no_network)

    new_entries = [
        e for e in mock_feedparser.entries
        if e.get("arxiv_announce_type", "new") == "new"
    ]

    retriever = ArxivRetriever(config)
    papers = retriever.retrieve_papers()

    assert len(papers) == len(new_entries)
    assert set(p.title for p in papers) == set(" ".join(e.title.split()) for e in new_entries)
    for p in papers:
        assert p.abstract and not p.abstract.startswith("arXiv:")
        assert "Announce Type" not in p.abstract
        assert p.authors and all("," not in a for a in p.authors)
        pid = p.url.removeprefix("https://arxiv.org/abs/")
        assert p.pdf_url == f"https://arxiv.org/pdf/{pid}"
        assert p.full_text is None


def test_arxiv_fetch_full_text_falls_back(config, mock_feedparser, monkeypatch):
    calls = []
    monkeypatch.setattr(arxiv_retriever, "extract_text_from_tar", lambda r: calls.append("tar"))
    monkeypatch.setattr(arxiv_retriever, "extract_text_from_html", lambda r: calls.append("html") or "html text")
    monkeypatch.setattr(arxiv_retriever, "extract_text_from_pdf", lambda r: calls.append("pdf"))

    retriever = ArxivRetriever(config)
    paper = retriever.retrieve_papers()[0]
    retriever.fetch_full_text(paper)

    assert calls == ["tar", "html"]
    assert paper.full_text == "html text"


def test_arxiv_backfill_file(config, tmp_path, monkeypatch):
    import json
    from omegaconf import open_dict

    path = tmp_path / "backfill.json"
    path.write_text(json.dumps([
        {"id": "2609.00001v1", "title": "T1", "authors": ["A", "B"], "abstract": "abs 1", "categories": ["cs.RO"]},
        {"id": "2609.00002v2", "title": "T2", "authors": ["C"], "abstract": "abs 2"},
    ]))
    with open_dict(config):
        config.source.arxiv.backfill_file = str(path)

    def _no_rss(*args, **kwargs):
        raise AssertionError("backfill mode must not read RSS")

    monkeypatch.setattr(arxiv_retriever.feedparser, "parse", _no_rss)
    papers = ArxivRetriever(config).retrieve_papers()

    assert [p.title for p in papers] == ["T1", "T2"]
    assert papers[0].authors == ["A", "B"]
    assert papers[1].url == "https://arxiv.org/abs/2609.00002v2"
    assert papers[1].pdf_url == "https://arxiv.org/pdf/2609.00002v2"


def test_run_with_hard_timeout_returns_value():
    result = _run_with_hard_timeout(
        _sleep_and_return, ("done", 0.01), timeout=1, operation="test op", paper_title="paper"
    )
    assert result == "done"


def test_run_with_hard_timeout_returns_none_on_timeout(monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(arxiv_retriever, "logger", SimpleNamespace(warning=warnings.append))
    result = _run_with_hard_timeout(
        _sleep_and_return, ("done", 1.0), timeout=0.01, operation="test op", paper_title="paper"
    )
    assert result is None
    assert "timed out" in warnings[0]


def test_run_with_hard_timeout_returns_none_on_failure(monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(arxiv_retriever, "logger", SimpleNamespace(warning=warnings.append))
    result = _run_with_hard_timeout(
        _raise_runtime_error, (), timeout=1, operation="test op", paper_title="paper"
    )
    assert result is None
    assert "boom" in warnings[0]
