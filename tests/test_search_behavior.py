#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Search aggregation and author pagination regression tests."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import server  # noqa: E402


class FakeSource:
    name = "fake"

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def search(self, key, page=1, limit=20, timeout=6):
        self.calls.append(page)
        return [dict(row) for row in self.pages.get(page, [])]


class AuthorPaginationTests(unittest.TestCase):
    def setUp(self):
        self.job_id = "author-pagination-test"
        with server._SEARCH_LOCK:
            server._SEARCH_JOBS[self.job_id] = {
                "results": [], "fails": [], "total": 1, "done": 0,
                "created": 0, "cancelled": False,
            }

    def tearDown(self):
        with server._SEARCH_LOCK:
            server._SEARCH_JOBS.pop(self.job_id, None)

    def test_exact_author_match_collects_later_pages_and_deduplicates(self):
        src = FakeSource({
            1: [
                {"name": "Book A", "author": "作者：Alice", "book_url": "/a", "source_id": "s"},
                {"name": "Book B", "author": "Other", "book_url": "/b", "source_id": "s"},
            ],
            2: [
                {"name": "Book A", "author": "Alice", "book_url": "/a", "source_id": "s"},
                {"name": "Book C", "author": "Alice", "book_url": "/c", "source_id": "s"},
            ],
            3: [],
        })

        server._search_one(self.job_id, src, " Alice ", 20, 6, author_pages=3)

        job = server._SEARCH_JOBS[self.job_id]
        self.assertEqual(src.calls, [1, 2, 3])
        self.assertEqual([row["name"] for row in job["results"]], ["Book A", "Book B", "Book C"])
        self.assertEqual(job["done"], 1)
        self.assertEqual(job["fails"], [])

    def test_non_author_query_does_not_expand_pages(self):
        src = FakeSource({
            1: [{"name": "Alice in Town", "author": "Other", "book_url": "/a", "source_id": "s"}],
            2: [{"name": "Should Not Load", "author": "Other", "book_url": "/b", "source_id": "s"}],
        })

        server._search_one(self.job_id, src, "Alice", 20, 6, author_pages=3)

        self.assertEqual(src.calls, [1])
        self.assertEqual(len(server._SEARCH_JOBS[self.job_id]["results"]), 1)


class FrontendGroupingTests(unittest.TestCase):
    def test_same_title_merges_and_best_source_is_first(self):
        html_path = os.path.join(BASE_DIR, "index.html")
        with open(html_path, "r", encoding="utf-8") as handle:
            html = handle.read()
        match = re.search(
            r"(const norm = .*?\nfunction buildGroups\(.*?\n\})\n\nfunction renderList",
            html,
            re.S,
        )
        self.assertIsNotNone(match, "Could not extract grouping functions from index.html")
        rows = [
            {
                "name": "Same Book", "author": "Author One", "source_id": "low",
                "source_name": "Low", "book_url": "https://low/book", "source_quality": 1,
            },
            {
                "name": " Same  Book ", "author": "Different Author", "source_id": "high",
                "source_name": "High", "book_url": "https://high/book", "source_quality": 90,
                "cover": "cover.jpg", "intro": "complete metadata", "last_chapter": "Chapter 9",
            },
        ]
        script = "\n".join([
            "const $ = () => ({value: ''});",
            match.group(1),
            f"const groups = buildGroups({json.dumps(rows)}, 'Same Book');",
            "if (groups.length !== 1) throw new Error('same title was not merged');",
            "if (groups[0].sources.length !== 2) throw new Error('sources were lost');",
            "if (groups[0].sources[0].source_id !== 'high') throw new Error('best source was not first');",
            "if (groups[0].author !== 'Different Author') throw new Error('card metadata did not follow best source');",
        ])
        result = subprocess.run(
            ["node", "-e", script], cwd=BASE_DIR, text=True,
            capture_output=True, timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
