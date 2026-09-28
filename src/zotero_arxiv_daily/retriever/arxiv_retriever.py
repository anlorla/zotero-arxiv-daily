from .base import BaseRetriever, register_retriever
import arxiv
from arxiv import Result as ArxivResult
from ..protocol import Paper
from ..utils import extract_markdown_from_pdf, extract_tex_code_from_tar
from tempfile import TemporaryDirectory
import feedparser
from tqdm import tqdm
import multiprocessing
import os
import json
from queue import Empty
from typing import Any, Callable, TypeVar
from loguru import logger
import requests

T = TypeVar("T")

DOWNLOAD_TIMEOUT = (10, 60)
PDF_EXTRACT_TIMEOUT = 180
TAR_EXTRACT_TIMEOUT = 180


def _download_file(url: str, path: str) -> None:
    with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT) as response:
        response.raise_for_status()
        with open(path, "wb") as file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    file.write(chunk)


def _run_in_subprocess(
    result_queue: Any,
    func: Callable[..., T | None],
    args: tuple[Any, ...],
) -> None:
    try:
        result_queue.put(("ok", func(*args)))
    except Exception as exc:
        result_queue.put(("error", f"{type(exc).__name__}: {exc}"))


def _run_with_hard_timeout(
    func: Callable[..., T | None],
    args: tuple[Any, ...],
    *,
    timeout: float,
    operation: str,
    paper_title: str,
) -> T | None:
    start_methods = multiprocessing.get_all_start_methods()
    context = multiprocessing.get_context("fork" if "fork" in start_methods else start_methods[0])
    result_queue = context.Queue()
    process = context.Process(target=_run_in_subprocess, args=(result_queue, func, args))
    process.start()

    try:
        status, payload = result_queue.get(timeout=timeout)
    except Empty:
        if process.is_alive():
            process.kill()
        process.join(5)
        result_queue.close()
        result_queue.join_thread()
        logger.warning(f"{operation} timed out for {paper_title} after {timeout} seconds")
        return None

    process.join(5)
    result_queue.close()
    result_queue.join_thread()

    if status == "ok":
        return payload

    logger.warning(f"{operation} failed for {paper_title}: {payload}")
    return None


def _extract_text_from_pdf_worker(pdf_url: str) -> str:
    with TemporaryDirectory() as temp_dir:
        path = os.path.join(temp_dir, "paper.pdf")
        _download_file(pdf_url, path)
        return extract_markdown_from_pdf(path)


def _extract_text_from_html_worker(html_url: str) -> str | None:
    import trafilatura

    downloaded = trafilatura.fetch_url(html_url)
    if downloaded is None:
        raise ValueError(f"Failed to download HTML from {html_url}")
    text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
    if not text:
        raise ValueError(f"No text extracted from {html_url}")
    return text


def _extract_text_from_tar_worker(source_url: str, paper_id: str, paper_title: str | None = None) -> str | None:
    with TemporaryDirectory() as temp_dir:
        path = os.path.join(temp_dir, "paper.tar.gz")
        _download_file(source_url, path)
        file_contents = extract_tex_code_from_tar(path, paper_id, paper_title=paper_title)
        if not file_contents or "all" not in file_contents:
            raise ValueError("Main tex file not found.")
        return file_contents["all"]


def _split_authors(creator: str) -> list[str]:
    # arXiv RSS packs all authors into one dc:creator string: "A, B, C" or "A, B and C".
    names = []
    for part in creator.split(","):
        names.extend(n.strip() for n in part.split(" and "))
    return [n for n in names if n]


def _rss_entry_to_result(entry: Any) -> ArxivResult:
    """Build an arxiv.Result straight from an RSS entry.

    export.arxiv.org/api answers GitHub Actions runners with HTTP 406 (since 2026-09-23),
    so metadata comes from the RSS feed; full text is downloaded later from arxiv.org.
    """
    paper_id = entry.id.removeprefix("oai:arXiv.org:")
    summary = entry.get("summary", "")
    if "Abstract:" in summary:
        summary = summary.split("Abstract:", 1)[1]
    authors = _split_authors(entry.get("author", ""))
    categories = [t["term"] for t in entry.get("tags", []) if t.get("term")]
    return ArxivResult(
        entry_id=f"https://arxiv.org/abs/{paper_id}",
        title=" ".join(entry.get("title", "").split()),
        authors=[ArxivResult.Author(n) for n in authors],
        summary=" ".join(summary.split()),
        primary_category=categories[0] if categories else "",
        categories=categories,
        links=[ArxivResult.Link(f"https://arxiv.org/pdf/{paper_id}", title="pdf", rel="related")],
    )


def _load_backfill_results(path: str) -> list[ArxivResult]:
    """Load papers from a JSON file (see scripts/build_arxiv_backfill.py) instead of today's RSS."""
    with open(path) as f:
        records = json.load(f)
    return [
        ArxivResult(
            entry_id=f"https://arxiv.org/abs/{r['id']}",
            title=r["title"],
            authors=[ArxivResult.Author(n) for n in r["authors"]],
            summary=r["abstract"],
            categories=r.get("categories", []),
            links=[ArxivResult.Link(f"https://arxiv.org/pdf/{r['id']}", title="pdf", rel="related")],
        )
        for r in records
    ]


@register_retriever("arxiv")
class ArxivRetriever(BaseRetriever):
    # convert_to_paper is offline now; full text is fetched only for kept papers.
    convert_sleep_seconds = 0

    def __init__(self, config):
        super().__init__(config)
        if self.config.source.arxiv.category is None:
            raise ValueError("category must be specified for arxiv.")
        self._raw_by_url: dict[str, ArxivResult] = {}

    def _retrieve_raw_papers(self) -> list[ArxivResult]:
        backfill_file = self.config.source.arxiv.get("backfill_file", None)
        if backfill_file:
            logger.info(f"Backfill mode: loading papers from {backfill_file}")
            raw_papers = _load_backfill_results(backfill_file)
            if self.config.executor.debug:
                raw_papers = raw_papers[:10]
            return raw_papers

        query = '+'.join(self.config.source.arxiv.category)
        include_cross_list = self.config.source.arxiv.get("include_cross_list", False)
        # Get the latest paper from arxiv rss feed
        feed = feedparser.parse(f"https://rss.arxiv.org/atom/{query}")
        if 'Feed error for query' in feed.feed.title:
            raise Exception(f"Invalid ARXIV_QUERY: {query}.")
        allowed_announce_types = {"new", "cross"} if include_cross_list else {"new"}
        entries = [
            i for i in feed.entries
            if i.get("arxiv_announce_type", "new") in allowed_announce_types
        ]
        if self.config.executor.debug:
            entries = entries[:10]

        raw_papers = []
        seen = set()
        for entry in entries:
            if entry.id in seen:
                continue
            seen.add(entry.id)
            raw_papers.append(_rss_entry_to_result(entry))
        return raw_papers

    def convert_to_paper(self, raw_paper: ArxivResult) -> Paper:
        self._raw_by_url[raw_paper.entry_id] = raw_paper
        return Paper(
            source=self.name,
            title=raw_paper.title,
            authors=[a.name for a in raw_paper.authors],
            abstract=raw_paper.summary,
            url=raw_paper.entry_id,
            pdf_url=raw_paper.pdf_url,
        )

    def fetch_full_text(self, paper: Paper) -> None:
        raw_paper = self._raw_by_url.get(paper.url)
        if raw_paper is None:
            return
        full_text = extract_text_from_tar(raw_paper)
        if full_text is None:
            full_text = extract_text_from_html(raw_paper)
        if full_text is None:
            full_text = extract_text_from_pdf(raw_paper)
        paper.full_text = full_text


def extract_text_from_html(paper: ArxivResult) -> str | None:
    html_url = paper.entry_id.replace("/abs/", "/html/")
    try:
        return _extract_text_from_html_worker(html_url)
    except Exception as exc:
        logger.warning(f"HTML extraction failed for {paper.title}: {exc}")
        return None


def extract_text_from_pdf(paper: ArxivResult) -> str | None:
    if paper.pdf_url is None:
        logger.warning(f"No PDF URL available for {paper.title}")
        return None
    return _run_with_hard_timeout(
        _extract_text_from_pdf_worker,
        (paper.pdf_url,),
        timeout=PDF_EXTRACT_TIMEOUT,
        operation="PDF extraction",
        paper_title=paper.title,
    )


def extract_text_from_tar(paper: ArxivResult) -> str | None:
    source_url = paper.source_url()
    if source_url is None:
        logger.warning(f"No source URL available for {paper.title}")
        return None
    return _run_with_hard_timeout(
        _extract_text_from_tar_worker,
        (source_url, paper.entry_id, paper.title),
        timeout=TAR_EXTRACT_TIMEOUT,
        operation="Tar extraction",
        paper_title=paper.title,
    )
