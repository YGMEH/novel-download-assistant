# -*- coding: utf-8 -*-
"""自测：起一个本地假书站 + 一份书源规则，验证搜索/详情/目录/正文/下载全链路。

不访问任何外部网站，纯本机验证引擎是否正确。
用法：~/.novelshell/bin/python selftest.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import downloader  # noqa: E402
from source_manager import BookSource  # noqa: E402

PORT = 18771
CHAPTERS = [(i, f"第{i}章 测试章节{i}") for i in range(1, 13)]


class FakeSite(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _send(self, body: str, ctype="text/html; charset=utf-8"):
        raw = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)

        if u.path == "/search":
            key = (q.get("q") or [""])[0]
            self._send(f"""<html><body>
              <div class="result-list">
                <div class="book">
                  <a class="title" href="/book/1">{key or '测试书籍'}</a>
                  <span class="author">测试作者</span>
                  <span class="cat">测试分类</span>
                  <p class="desc">这是一本用于自测的虚构书籍，内容由本地脚本生成。</p>
                </div>
              </div></body></html>""")

        elif u.path == "/book/1":
            self._send("""<html><body>
              <div class="detail">
                <h1 class="bookname">自测书籍</h1>
                <span class="author">测试作者</span>
                <span class="cat">测试分类</span>
                <div class="intro">本地自测用虚构书籍，共 12 章。</div>
                <a class="toc-link" href="/toc/1">查看目录</a>
              </div></body></html>""")

        elif u.path == "/toc/1":
            items = "".join(
                f'<li><a href="/chapter/{i}">{t}</a></li>' for i, t in CHAPTERS)
            self._send(f"<html><body><ul class='chapter-list'>{items}</ul></body></html>")

        elif u.path.startswith("/chapter/"):
            n = u.path.rsplit("/", 1)[-1]
            para = "<br>".join(
                f"这是第 {n} 章的第 {k} 段正文，用于验证抓取与合并是否正确。"
                for k in range(1, 6))
            self._send(f"<html><body><div id='content'>{para}</div></body></html>")

        else:
            self._send("<html><body>not found</body></html>")


SOURCE_RULE = {
    "bookSourceName": "本地自测源",
    "bookSourceUrl": f"http://127.0.0.1:{PORT}",
    "bookSourceGroup": "自测",
    "searchUrl": f"http://127.0.0.1:{PORT}/search?q={{{{key}}}}",
    "ruleSearch": {
        "bookList": "css:.result-list .book",
        "name": "css:a.title@text",
        "author": "css:.author@text",
        "kind": "css:.cat@text",
        "intro": "css:.desc@text",
        "bookUrl": "css:a.title@href",
    },
    "ruleBookInfo": {
        "name": "css:.bookname@text",
        "author": "css:.author@text",
        "kind": "css:.cat@text",
        "intro": "css:.intro@text",
        "tocUrl": "css:a.toc-link@href",
    },
    "ruleToc": {
        "chapterList": "css:.chapter-list li",
        "chapterName": "css:a@text",
        "chapterUrl": "css:a@href",
    },
    "ruleContent": {"content": "css:#content@html"},
}


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), FakeSite)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.4)

    failures: list[str] = []

    def check(label: str, cond: bool, extra: str = "") -> None:
        print(("  [OK] " if cond else "  [FAIL] ") + label + (f" — {extra}" if extra else ""))
        if not cond:
            failures.append(label)

    try:
        src = BookSource(SOURCE_RULE, "selftest.json", 0)
        cap = src.capability()
        print("1) 书源能力自检")
        check("可搜索", cap["searchable"])
        check("可下载", cap["downloadable"])
        check("无阻断问题", not cap["problems"], str(cap["problems"]))

        print("2) 搜索")
        results = src.search("自测书籍")
        check("返回结果", len(results) == 1, f"{len(results)} 条")
        book = results[0] if results else {}
        check("书名解析", book.get("name") == "自测书籍", book.get("name", ""))
        check("作者解析", book.get("author") == "测试作者", book.get("author", ""))
        check("详情链接绝对化", str(book.get("book_url", "")).startswith("http"),
              book.get("book_url", ""))

        print("3) 详情")
        detail = src.detail(book["book_url"])
        check("详情书名", detail["name"] == "自测书籍", detail["name"])
        check("目录地址", detail["toc_url"].endswith("/toc/1"), detail["toc_url"])

        print("4) 目录")
        chapters = src.toc(detail["toc_url"])
        check("章节数=12", len(chapters) == 12, f"{len(chapters)} 章")
        check("首章标题", chapters and chapters[0]["title"] == "第1章 测试章节1",
              chapters[0]["title"] if chapters else "")
        check("末章标题", chapters and chapters[-1]["title"] == "第12章 测试章节12",
              chapters[-1]["title"] if chapters else "")
        check("章节顺序正确",
              [c["title"] for c in chapters] == [t for _, t in CHAPTERS])

        print("5) 正文")
        body = src.content(chapters[0]["url"])
        check("正文非空", len(body) > 50, f"{len(body)} 字")
        check("<br> 已转换为换行", "<br>" not in body and body.count("\n") >= 4)
        check("无 HTML 标签残留", "<div" not in body and "</div>" not in body)

        print("6) 下载整本")
        out_dir = os.path.join(BASE_DIR, ".selftest_out")
        shutil.rmtree(out_dir, ignore_errors=True)
        cache = os.path.join(BASE_DIR, ".cache")
        shutil.rmtree(cache, ignore_errors=True)

        mgr = downloader.TaskManager()
        task = mgr.submit(src, dict(detail), chapters, out_dir, workers=4, retry=1)
        for _ in range(120):
            if task.status in ("done", "error", "cancelled"):
                break
            time.sleep(0.25)
        check("任务完成", task.status == "done", f"{task.status} / {task.message}")
        check("全部章节抓到", task.done == 12, f"{task.done}/12")
        check("无失败章节", not task.failed, str(task.failed[:2]))
        check("文件已生成", bool(task.file_path) and os.path.isfile(task.file_path),
              task.file_path)

        if task.file_path and os.path.isfile(task.file_path):
            with open(task.file_path, "r", encoding="utf-8") as f:
                text = f.read()
            check("12 个章节标题齐全",
                  all(f"== {t} ==" in text for _, t in CHAPTERS))
            check("无失败占位", "本章抓取失败" not in text)
            check("章节顺序与目录一致",
                  [text.index(f"== {t} ==") for _, t in CHAPTERS] ==
                  sorted(text.index(f"== {t} ==") for _, t in CHAPTERS))
            check("含书籍头信息", "书名：" in text and "章节数：12" in text)
            print(f"  文件大小 {os.path.getsize(task.file_path)} 字节")

        print("7) 断点续传（删掉产物但保留缓存后重跑）")
        task2 = mgr.submit(src, dict(detail), chapters, out_dir, workers=4)
        for _ in range(120):
            if task2.status in ("done", "error", "cancelled"):
                break
            time.sleep(0.25)
        check("二次运行完成", task2.status == "done", task2.message)

        print("8) 不支持的书源应被识别")
        js_src = BookSource({
            "bookSourceName": "含JS的源",
            "bookSourceUrl": "http://example.invalid",
            "searchUrl": "http://example.invalid/s?k={{key}}",
            "ruleSearch": {"bookList": "@js:java.ajax('x')"},
            "ruleToc": {"chapterList": "css:li"},
            "ruleContent": {"content": "css:#c@text"},
        }, "x.json", 0)
        problems = js_src.capability()["problems"]
        check("识别出 JS 规则", any("JS" in p for p in problems), str(problems))

        shutil.rmtree(out_dir, ignore_errors=True)
        shutil.rmtree(cache, ignore_errors=True)
    finally:
        server.shutdown()

    print("\n" + ("全部通过 ✅" if not failures else f"失败 {len(failures)} 项：{failures}"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())