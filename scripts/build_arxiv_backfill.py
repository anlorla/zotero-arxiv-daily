"""Build a backfill JSON of arXiv papers announced on given days (run locally, not on CI).

IDs come from the arxiv.org/list pastweek pages (so only the last 5 announcement days are
reachable); metadata comes from OAI-PMH (export.arxiv.org/api now answers 406/429).
The JSON is committed and the "Backfill" workflow reranks and mails it.

    uv run scripts/build_arxiv_backfill.py --categories cs.CV cs.RO cs.LG cs.AI cs.CL \
        --dates "Tue, 22 Sep 2026" "Fri, 25 Sep 2026" --out backfill/2026-09-22_25.json
"""
import argparse
import json
import re
from datetime import datetime, timedelta
from time import sleep

import xml.etree.ElementTree as ET

import requests

UA = {"User-Agent": "zotero-arxiv-daily backfill"}


def listing_ids(category: str, days: set[str]) -> list[str]:
    ids, skip = [], 0
    while True:
        url = f"https://arxiv.org/list/{category}/pastweek?skip={skip}&show=2000"
        html = requests.get(url, headers=UA, timeout=60).text
        sections = re.split(r"<h3>", html)[1:]
        page_ids = []
        for sec in sections:
            day = sec.split("(")[0].strip()
            found = re.findall(r'href\s*=\s*"/abs/(\d{4}\.\d{4,5})"', sec)
            page_ids += found
            if day in days:
                ids += found
        if len(page_ids) < 2000:
            return ids
        skip += 2000
        sleep(3)


def day_range(start: str, end: str) -> set[str]:
    fmt = "%a, %d %b %Y"
    d, e = datetime.strptime(start, fmt), datetime.strptime(end, fmt)
    out = set()
    while d <= e:
        out.add(d.strftime(fmt))
        d += timedelta(days=1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--categories", nargs="+", required=True)
    ap.add_argument("--dates", nargs=2, required=True, metavar=("FIRST", "LAST"),
                    help='listing headings, e.g. "Tue, 22 Sep 2026" "Fri, 25 Sep 2026"')
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    days = day_range(*args.dates)
    ids = []
    for cat in args.categories:
        cat_ids = listing_ids(cat, days)
        print(f"{cat}: {len(cat_ids)} papers")
        ids += cat_ids
        sleep(3)
    ids = list(dict.fromkeys(ids))
    print(f"unique: {len(ids)}")

    wanted = set(ids)
    first = datetime.strptime(args.dates[0], "%a, %d %b %Y") - timedelta(days=2)
    params = {"verb": "ListRecords", "metadataPrefix": "arXiv", "set": "cs",
              "from": first.strftime("%Y-%m-%d")}
    ns = {"o": "http://www.openarchives.org/OAI/2.0/", "a": "http://arxiv.org/OAI/arXiv/"}
    found = {}
    while True:
        resp = requests.get("https://oaipmh.arxiv.org/oai", params=params, headers=UA, timeout=120)
        if resp.status_code == 503:
            sleep(int(resp.headers.get("Retry-After", 30)))
            continue
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        for meta in root.iterfind(".//o:metadata/a:arXiv", ns):
            pid = meta.findtext("a:id", namespaces=ns)
            if pid not in wanted:
                continue
            authors = [
                " ".join(filter(None, [a.findtext("a:forenames", "", ns), a.findtext("a:keyname", "", ns)]))
                for a in meta.iterfind("a:authors/a:author", ns)
            ]
            found[pid] = {
                "id": pid,
                "title": " ".join(meta.findtext("a:title", "", ns).split()),
                "authors": authors,
                "abstract": " ".join(meta.findtext("a:abstract", "", ns).split()),
                "categories": meta.findtext("a:categories", "", ns).split(),
            }
        token = root.findtext(".//o:resumptionToken", namespaces=ns)
        print(f"metadata {len(found)}/{len(wanted)}")
        if not token:
            break
        params = {"verb": "ListRecords", "resumptionToken": token}
        sleep(3)
    missing = wanted - set(found)
    if missing:
        print(f"missing metadata for {len(missing)}: {sorted(missing)[:10]} ...")
    records = [found[i] for i in ids if i in found]
    with open(args.out, "w") as f:
        json.dump(records, f, ensure_ascii=False, indent=0)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
