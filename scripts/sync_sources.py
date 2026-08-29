# -*- coding: utf-8 -*-
"""同步 yckceo 书源合集，过滤成人/不兼容源并做搜索-详情-目录健康探测。

用法：python scripts/sync_sources.py [--dry-run] [--probe-key 蛊真人]
目标文件默认为 sources/builtin/reading_sources_safe.json。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from source_manager import BookSource  # noqa: E402

LIST_URL = "https://www.yckceo.com/yuedu/shuyuans/index.html"
JSON_URL = "https://www.yckceo.com/yuedu/shuyuans/json/id/{}.json"
EXTRA_SOURCE_URLS = (
    "https://legado.aoaostar.com/sources/b778fe6b.json",
)
OUT_FILE = ROOT / "sources" / "builtin" / "reading_sources_safe.json"
META_FILE = ROOT / "sources" / "builtin" / "reading_sources_safe.meta.json"
TARGET = 1000
MIN_TARGET = 800
MAX_PAGES = 3
PAGE_SIZE = 100
FETCH_TIMEOUT = 20
PROBE_TIMEOUT = 4
PROBE_WORKERS = 12
ADULT_RE = re.compile(
    r"18\s*\+|18禁|十八禁|成人|色情|情色|肉文|肉书|肉漫|韩漫|漫画|短剧|直播|"
    r"po18|污漫|污文|涩文|淫|禁漫|耽美|色情小说|成人小说|含黄|含18",
    re.I,
)


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href", "")
            self._text = []

    def handle_data(self, data):
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join(self._text).strip()))
            self._href = ""
            self._text = []


def get(url: str, timeout=FETCH_TIMEOUT) -> requests.Response:
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "NovelSourceSync/1.0"})
    r.raise_for_status()
    return r


def collect_bundle_ids() -> list[str]:
    ids: list[str] = []
    for page in range(1, MAX_PAGES + 1):
        url = LIST_URL if page == 1 else LIST_URL.replace("index.html", f"index_{page}.html")
        try:
            text = get(url).text
        except Exception as exc:
            print(f"WARN list page {page}: {exc}", file=sys.stderr)
            continue
        parser = LinkParser()
        parser.feed(text)
        for href, title in parser.links:
            m = re.search(r"/shuyuans/content/id/(\d+)\.html", href)
            if m and not ADULT_RE.search(title):
                ids.append(m.group(1))
    return list(dict.fromkeys(ids))


def bundle_url(bundle_id: str) -> str:
    return JSON_URL.format(bundle_id)


def load_bundles(ids: list[str]) -> list[dict]:
    all_sources: list[dict] = []
    for bundle_id in ids:
        try:
            data = get(bundle_url(bundle_id)).json()
        except Exception as exc:
            print(f"WARN bundle {bundle_id}: {exc}", file=sys.stderr)
            continue
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            continue
        all_sources.extend(x for x in data if isinstance(x, dict))
        if len(all_sources) >= TARGET * 3:
            break
    for url in EXTRA_SOURCE_URLS:
        try:
            data = get(url).json()
        except Exception as exc:
            print(f"WARN extra source {url}: {exc}", file=sys.stderr)
            continue
        if isinstance(data, dict):
            data = [data]
        if isinstance(data, list):
            all_sources.extend(x for x in data if isinstance(x, dict))
    return all_sources


def is_safe_shape(raw: dict) -> bool:
    identity = " ".join(str(raw.get(k, "")) for k in (
        "bookSourceName", "bookSourceGroup", "bookSourceComment", "bookSourceUrl"
    ))
    blob = json.dumps(raw, ensure_ascii=False)
    if ADULT_RE.search(identity):
        return False
    if raw.get("bookSourceType", 0) != 0:
        return False
    if raw.get("loginUrl") or raw.get("loginUi") or raw.get("loginCheckJs"):
        return False
    if raw.get("enabledCookieJar"):
        return False
    if re.search(r"(?i)@js:|<js>|\{\{java\.|javascript:|webview|内置浏览器|验证码|滑块", blob):
        return False
    src = BookSource(raw)
    cap = src.capability()
    return bool(cap["searchable"] and cap["downloadable"] and not cap["problems"])


def source_key(raw: dict) -> str:
    return re.sub(r"\s+", "", str(raw.get("bookSourceUrl", "")).rstrip("/").lower())


def probe(raw: dict, key: str) -> tuple[dict, str]:
    try:
        src = BookSource(raw)
        rows = src.search(key, limit=3, timeout=PROBE_TIMEOUT)
        if not rows:
            return raw, "search-empty"
        detail = src.detail(rows[0]["book_url"], timeout=PROBE_TIMEOUT)
        if not detail.get("toc_url"):
            return raw, "detail-no-toc"
        chapters = src.toc(detail["toc_url"], timeout=PROBE_TIMEOUT, max_pages=2)
        if not chapters:
            return raw, "toc-empty"
        return raw, "ok"
    except Exception as exc:
        return raw, type(exc).__name__


def atomic_write(items: list[dict], dry_run: bool) -> None:
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    if dry_run:
        return
    if OUT_FILE.exists():
        backup = OUT_FILE.with_suffix(OUT_FILE.suffix + ".bak")
        shutil.copy2(OUT_FILE, backup)
    fd, temp_name = tempfile.mkstemp(prefix="reading_sources_safe.", suffix=".json", dir=OUT_FILE.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=1)
            f.write("\n")
        os.replace(temp_name, OUT_FILE)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--probe-key", default="蛊真人")
    args = ap.parse_args()
    ids = collect_bundle_ids()
    if not ids:
        print("ERROR no bundle ids found", file=sys.stderr)
        return 2
    raw = load_bundles(ids)
    candidates: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        k = source_key(item)
        if not k or k in seen or not is_safe_shape(item):
            continue
        seen.add(k)
        candidates.append(item)
    print(f"bundles={len(ids)} raw={len(raw)} shape_safe={len(candidates)}")
    healthy: list[dict] = []
    failed: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=PROBE_WORKERS) as pool:
        futures = [pool.submit(probe, item, args.probe_key) for item in candidates]
        for future in as_completed(futures):
            item, status = future.result()
            if status == "ok":
                healthy.append(item)
            else:
                failed[status] = failed.get(status, 0) + 1
            if len(healthy) >= TARGET:
                break
    if len(healthy) < MIN_TARGET:
        print(f"ERROR healthy sources {len(healthy)} below minimum {MIN_TARGET}; old file kept", file=sys.stderr)
        print(json.dumps(failed, ensure_ascii=False, sort_keys=True))
        return 3
    healthy.sort(key=lambda item: (
        -int(BookSource(item).capability()["quality"]),
        str(item.get("bookSourceName", "")),
    ))
    healthy = healthy[:TARGET]
    digest = hashlib.sha256(json.dumps(healthy, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    atomic_write(healthy, args.dry_run)
    if not args.dry_run:
        META_FILE.write_text(json.dumps({"updated_at": datetime.now().isoformat(timespec="seconds"), "count": len(healthy), "sha256": digest, "bundles": ids}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"healthy={len(healthy)} failed={sum(failed.values())} sha256={digest} dry_run={args.dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
