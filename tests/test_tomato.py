#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tomato_source 功能自测：详情 / 目录 / 正文 / 下载器兼容"""
import sys
sys.path.insert(0, "/root/novel-src")
import tomato_source as T

src = T.tomato_source

print("== 1. ID 提取 ==")
assert T.extract_book_id("7143038691944959011") == "7143038691944959011"
assert T.extract_book_id("https://fanqienovel.com/page/7143038691944959011") == "7143038691944959011"
assert T.extract_book_id("https://fanqienovel.com/page/7143038691944959011?utm=x") == "7143038691944959011"
assert T.extract_book_id("hello world") == ""
assert T.extract_item_id("/reader/7173216089122439711") == "7173216089122439711"
assert T.extract_item_id("7173216089122439711") == "7173216089122439711"
print("ID 提取 OK")

print("== 2. 详情（真实网络） ==")
d = src.detail(f"{T.BASE}/page/7143038691944959011")
print("  name:", d["name"], "| author:", d["author"],
      "| words:", d["word_count"], "| cover:", (d["cover"] or "")[:50])
assert d["name"] == "十日终焉"

print("== 3. 目录（真实网络） ==")
chs = src.toc(d["toc_url"])
print("  chapters:", len(chs), "| first:", chs[0]["title"], "| last:", chs[-1]["title"])
assert len(chs) > 100

print("== 4. 正文（真实网络，PUA 解码） ==")
body = src.content(chs[0]["url"])
n_pua = sum(1 for c in body if 0xE000 <= ord(c) <= 0xF8FF)
print("  chars:", len(body), "| residual PUA:", n_pua)
print("  head:", body[:60].replace("\n", " / "))
assert len(body) > 1500 and n_pua == 0

print("== 5. 下载器契约兼容 ==")
import downloader
import inspect
sig = inspect.signature(downloader.Task.__init__)
print("  Task(source, book, chapters, out_dir, ...) —— content(url) 契约由 run() 调用")
assert callable(src.content)
print("  OK")

print()
print("ALL PASSED")