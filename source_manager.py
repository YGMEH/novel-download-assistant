# -*- coding: utf-8 -*-
"""书源管理与解析：把 Legado 风格书源 JSON 变成可执行的搜索/详情/目录/正文操作。

书源完全由用户自行导入，本项目不内置任何书源。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from html import unescape
from typing import Any

import requests

import rule_engine as R

SOURCES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources")
_LOCK = threading.Lock()


# --------------------------------------------------------------------------
# 字段兼容：新版 ruleSearch{} 与旧版 ruleSearchName 两种写法都能读
# --------------------------------------------------------------------------

def _pick(src: dict, *paths: str) -> Any:
    for path in paths:
        cur: Any = src
        ok = True
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and cur not in (None, ""):
            return cur
    return None


class BookSource:
    """一个书源。"""

    def __init__(self, raw: dict, file_name: str = "", index: int = 0):
        self.raw = raw
        self.file_name = file_name
        self.index = index
        self.name = str(_pick(raw, "bookSourceName", "sourceName", "name") or "未命名书源")
        self.url = str(_pick(raw, "bookSourceUrl", "sourceUrl", "url") or "").rstrip("/")
        self.group = str(_pick(raw, "bookSourceGroup", "sourceGroup") or "")
        self.comment = str(_pick(raw, "bookSourceComment") or "")
        self.enabled = bool(raw.get("enabled", True))
        self.id = hashlib.md5(f"{self.name}|{self.url}".encode()).hexdigest()[:12]

        header = _pick(raw, "header", "httpHeaders")
        if isinstance(header, str):
            try:
                header = json.loads(header)
            except Exception:
                header = {}
        self.header: dict = header if isinstance(header, dict) else {}

        self.search_url = _pick(raw, "searchUrl", "ruleSearchUrl")
        self.explore_url = _pick(raw, "exploreUrl", "ruleFindUrl")

        self.r_search = {
            "list": _pick(raw, "ruleSearch.bookList", "ruleSearchList"),
            "name": _pick(raw, "ruleSearch.name", "ruleSearchName"),
            "author": _pick(raw, "ruleSearch.author", "ruleSearchAuthor"),
            "kind": _pick(raw, "ruleSearch.kind", "ruleSearchKind"),
            "intro": _pick(raw, "ruleSearch.intro", "ruleSearchIntroduce"),
            "cover": _pick(raw, "ruleSearch.coverUrl", "ruleSearchCoverUrl"),
            "last": _pick(raw, "ruleSearch.lastChapter", "ruleSearchLastChapter"),
            "words": _pick(raw, "ruleSearch.wordCount"),
            "book_url": _pick(raw, "ruleSearch.bookUrl", "ruleSearchNoteUrl"),
        }
        self.r_info = {
            "name": _pick(raw, "ruleBookInfo.name", "ruleBookName"),
            "author": _pick(raw, "ruleBookInfo.author", "ruleBookAuthor"),
            "kind": _pick(raw, "ruleBookInfo.kind", "ruleBookKind"),
            "intro": _pick(raw, "ruleBookInfo.intro", "ruleIntroduce"),
            "cover": _pick(raw, "ruleBookInfo.coverUrl", "ruleCoverUrl"),
            "last": _pick(raw, "ruleBookInfo.lastChapter", "ruleBookLastChapter"),
            "words": _pick(raw, "ruleBookInfo.wordCount"),
            "toc_url": _pick(raw, "ruleBookInfo.tocUrl", "ruleChapterUrl"),
            "init": _pick(raw, "ruleBookInfo.init"),
        }
        self.r_toc = {
            "list": _pick(raw, "ruleToc.chapterList", "ruleChapterList"),
            "name": _pick(raw, "ruleToc.chapterName", "ruleChapterName"),
            "url": _pick(raw, "ruleToc.chapterUrl", "ruleContentUrl"),
            "next": _pick(raw, "ruleToc.nextTocUrl", "ruleChapterUrlNext"),
        }
        self.r_content = {
            "content": _pick(raw, "ruleContent.content", "ruleBookContent"),
            "next": _pick(raw, "ruleContent.nextContentUrl", "ruleContentUrlNext"),
            "replace": _pick(raw, "ruleContent.replaceRegex"),
        }

    # ---------------- 能力自检 ----------------

    def capability(self) -> dict:
        """判断这个书源在本引擎里能用到什么程度。"""
        problems: list[str] = []
        blob = json.dumps(self.raw, ensure_ascii=False)
        if "@js:" in blob or "<js>" in blob or "{{java." in blob:
            problems.append("含 JS/java 脚本规则")
        if '"webView":true' in blob.replace(" ", ""):
            problems.append("需要 WebView 渲染")
        if _pick(self.raw, "loginUrl", "loginUi"):
            problems.append("需要登录")
        if not self.search_url:
            problems.append("缺少搜索地址")
        if not self.r_toc["list"]:
            problems.append("缺少目录规则")
        if not self.r_content["content"]:
            problems.append("缺少正文规则")
        return {
            "searchable": bool(self.search_url) and "含 JS/java 脚本规则" not in problems,
            "downloadable": bool(self.r_toc["list"] and self.r_content["content"]),
            "quality": (40 if bool(self.r_toc["list"] and self.r_content["content"]) else 0)
                       + (30 if bool(self.search_url) else 0)
                       + (10 if not problems else 0)
                       - (10 if "需要登录" in problems else 0),
            "problems": problems,
        }

    def to_dict(self) -> dict:
        cap = self.capability()
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "group": self.group,
            "comment": self.comment,
            "enabled": self.enabled,
            "file": self.file_name,
            "searchable": cap["searchable"],
            "downloadable": cap["downloadable"],
            "quality": cap["quality"],
            "problems": cap["problems"],
        }

    # ---------------- 抓取动作 ----------------

    def _session(self) -> requests.Session:
        s = requests.Session()
        s.trust_env = False
        return s

    def search(self, key: str, page: int = 1, limit: int = 20, timeout: int = 20) -> list[dict]:
        if not self.search_url:
            raise R.RuleError("该书源没有搜索规则")
        spec = str(self.search_url)
        if not re.match(r"^https?://", spec.split(",")[0].strip()):
            spec = self.url + "/" + spec.lstrip("/")
        session = self._session()
        text, final_url = R.http_fetch(session, spec, self.header, key=key, page=page,
                                       timeout=timeout, referer=self.url or None)
        ctx = R.build_context(text)
        nodes = R.get_list(ctx, self.r_search["list"])
        if not nodes and self.r_search["list"]:
            return []
        if not nodes:
            nodes = [ctx]

        out: list[dict] = []
        for node in nodes[:limit]:
            try:
                book_url = R.get_string(node, self.r_search["book_url"], final_url)
                item = {
                    "source_id": self.id,
                    "source_name": self.name,
                    "source_quality": self.capability()["quality"],
                    "name": R.get_string(node, self.r_search["name"], final_url),
                    "author": R.get_string(node, self.r_search["author"], final_url),
                    "kind": R.get_string(node, self.r_search["kind"], final_url, join=" / "),
                    "intro": R.get_string(node, self.r_search["intro"], final_url)[:300],
                    "cover": R.absolute(R.get_string(node, self.r_search["cover"], final_url), final_url),
                    "last_chapter": R.get_string(node, self.r_search["last"], final_url),
                    "word_count": R.get_string(node, self.r_search["words"], final_url),
                    "book_url": R.absolute(book_url, final_url),
                }
            except R.RuleError:
                continue
            if item["name"] and item["book_url"]:
                out.append(item)
        return out

    def detail(self, book_url: str, timeout: int = 20) -> dict:
        session = self._session()
        text, final_url = R.http_fetch(session, book_url, self.header,
                                       timeout=timeout, referer=self.url or None)
        ctx = R.build_context(text)
        if self.r_info["init"]:
            sub = R.get_list(ctx, self.r_info["init"])
            if sub:
                ctx = sub[0]
        toc_url = R.get_string(ctx, self.r_info["toc_url"], final_url) or final_url
        return {
            "source_id": self.id,
            "source_name": self.name,
            "name": R.get_string(ctx, self.r_info["name"], final_url),
            "author": R.get_string(ctx, self.r_info["author"], final_url),
            "kind": R.get_string(ctx, self.r_info["kind"], final_url, join=" / "),
            "intro": R.get_string(ctx, self.r_info["intro"], final_url),
            "cover": R.absolute(R.get_string(ctx, self.r_info["cover"], final_url), final_url),
            "last_chapter": R.get_string(ctx, self.r_info["last"], final_url),
            "word_count": R.get_string(ctx, self.r_info["words"], final_url),
            "book_url": final_url,
            "toc_url": R.absolute(toc_url, final_url),
        }

    def toc(self, toc_url: str, timeout: int = 20, max_pages: int = 60) -> list[dict]:
        session = self._session()
        chapters: list[dict] = []
        seen_pages: set[str] = set()
        url = toc_url
        for _ in range(max_pages):
            if not url or url in seen_pages:
                break
            seen_pages.add(url)
            text, final_url = R.http_fetch(session, url, self.header,
                                           timeout=timeout, referer=self.url or None)
            ctx = R.build_context(text)
            nodes = R.get_list(ctx, self.r_toc["list"])
            for node in nodes:
                title = R.get_string(node, self.r_toc["name"], final_url)
                chap_url = R.absolute(R.get_string(node, self.r_toc["url"], final_url), final_url)
                if title and chap_url:
                    chapters.append({"title": title, "url": chap_url})
            next_url = ""
            if self.r_toc["next"]:
                try:
                    next_url = R.absolute(R.get_string(ctx, self.r_toc["next"], final_url), final_url)
                except R.RuleError:
                    next_url = ""
            if not next_url or next_url == final_url:
                break
            url = next_url

        # 去重但保留顺序
        uniq: list[dict] = []
        seen: set[str] = set()
        for c in chapters:
            if c["url"] in seen:
                continue
            seen.add(c["url"])
            uniq.append(c)
        return uniq

    def content(self, chapter_url: str, timeout: int = 20, max_pages: int = 20) -> str:
        session = self._session()
        parts: list[str] = []
        url = chapter_url
        seen: set[str] = set()
        for _ in range(max_pages):
            if not url or url in seen:
                break
            seen.add(url)
            text, final_url = R.http_fetch(session, url, self.header,
                                           timeout=timeout, referer=self.url or None)
            ctx = R.build_context(text)
            body = R.get_string(ctx, self.r_content["content"], final_url, join="\n")
            if body:
                parts.append(body)
            next_url = ""
            if self.r_content["next"]:
                try:
                    next_url = R.absolute(R.get_string(ctx, self.r_content["next"], final_url), final_url)
                except R.RuleError:
                    next_url = ""
            if not next_url or next_url in seen:
                break
            url = next_url

        body = "\n".join(parts)
        return self._clean(body)

    def _clean(self, body: str) -> str:
        """把抓到的正文整理成纯文本段落。"""
        if not body:
            return ""

        # 书源自带的 replaceRegex 先执行
        replace = self.r_content.get("replace")
        if replace:
            for line in str(replace).split("\n"):
                if not line.strip():
                    continue
                pattern, _, repl = line.partition("##")
                try:
                    body = re.sub(pattern, repl, body)
                except Exception:
                    continue

        # script/style 整块丢掉，避免正文里混进代码
        body = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", body)
        # 换行类标签统一转成 \n
        body = re.sub(r"(?i)<br\s*/?>", "\n", body)
        body = re.sub(r"(?i)</(p|div|li|h[1-6]|tr)\s*>", "\n", body)
        body = re.sub(r"(?i)<(p|div|li|h[1-6]|tr)\b[^>]*>", "\n", body)
        # 其余标签直接剥掉（@html 规则会带上外层标签）
        body = re.sub(r"<[^>]+>", "", body)
        # HTML 实体还原
        body = unescape(body)

        body = body.replace("\u3000", " ").replace("\xa0", " ")
        lines = [ln.strip() for ln in body.split("\n")]
        lines = [ln for ln in lines if ln]
        return "\n".join(lines)


# --------------------------------------------------------------------------
# 书源仓库：加载 / 导入 / 删除
# --------------------------------------------------------------------------

class SourceStore:
    def __init__(self, directory: str = SOURCES_DIR):
        self.dir = directory
        os.makedirs(self.dir, exist_ok=True)
        self._cache: dict[str, BookSource] = {}
        self.reload()

    def reload(self) -> None:
        """扫描书源目录；默认只加载已审核安全包，保留其他文件供回滚。"""
        safe_only = os.environ.get("NOVEL_SAFE_SOURCES", "1").lower() not in ("0", "false", "no")
        with _LOCK:
            self._cache = {}
            for root, _dirs, files in os.walk(self.dir):
                if safe_only and os.path.relpath(root, self.dir).replace("\\", "/") == "builtin":
                    files = [fn for fn in files if fn == "reading_sources_safe.json"]
                for fn in sorted(files):
                    if not fn.lower().endswith(".json"):
                        continue
                    rel = os.path.relpath(os.path.join(root, fn), self.dir)
                    path = os.path.join(root, fn)
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                    except Exception:
                        continue
                    items = data if isinstance(data, list) else [data]
                    for i, raw in enumerate(items):
                        if not isinstance(raw, dict):
                            continue
                        src = BookSource(raw, rel, i)
                        self._cache[src.id] = src

    def all(self) -> list[BookSource]:
        return list(self._cache.values())

    def get(self, source_id: str) -> BookSource:
        src = self._cache.get(source_id)
        if not src:
            raise KeyError(f"书源不存在：{source_id}")
        return src

    def import_payload(self, payload: Any, file_name: str | None = None) -> dict:
        """导入书源。payload 可为 dict / list / JSON 字符串。"""
        if isinstance(payload, str):
            payload = json.loads(payload)
        items = payload if isinstance(payload, list) else [payload]
        items = [i for i in items if isinstance(i, dict)]
        if not items:
            raise ValueError("没有解析出任何书源")

        name = file_name or f"import_{len(os.listdir(self.dir)) + 1}.json"
        if not name.lower().endswith(".json"):
            name += ".json"
        name = re.sub(r"[^\w\-.\u4e00-\u9fff]", "_", name)
        path = os.path.join(self.dir, name)
        base, ext = os.path.splitext(path)
        n = 1
        while os.path.exists(path):
            path = f"{base}_{n}{ext}"
            n += 1
        with open(path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=1)
        self.reload()
        return {"file": os.path.basename(path), "count": len(items)}

    def import_from_url(self, url: str, timeout: int = 30) -> dict:
        session = requests.Session()
        session.trust_env = False
        resp = session.get(url, timeout=timeout, headers={"User-Agent": R.DEFAULT_UA})
        resp.raise_for_status()
        resp.encoding = resp.encoding or "utf-8"
        file_name = os.path.basename(url.split("?")[0]) or "remote.json"
        return self.import_payload(resp.text, file_name)

    def delete_file(self, file_name: str) -> None:
        rel = str(file_name or "").replace("\\", "/").lstrip("/")
        if not rel or ".." in rel.split("/"):
            raise ValueError("非法路径")
        root = os.path.abspath(self.dir)
        path = os.path.abspath(os.path.join(self.dir, rel))
        if path != root and not path.startswith(root + os.sep):
            raise ValueError("非法路径")
        if os.path.isfile(path):
            os.remove(path)
        self.reload()

    def set_enabled(self, source_id: str, enabled: bool) -> None:
        src = self.get(source_id)
        path = os.path.join(self.dir, src.file_name)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data if isinstance(data, list) else [data]
        if 0 <= src.index < len(items):
            items[src.index]["enabled"] = bool(enabled)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=1)
        self.reload()