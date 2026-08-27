# -*- coding: utf-8 -*-
"""下载任务：并发抓章节、合并落盘、进度与断点续传。"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")


def safe_name(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", (name or "未命名").strip())
    return name[:80] or "未命名"


class Task:
    def __init__(self, source, book: dict, chapters: list[dict], out_dir: str,
                 workers: int = 4, retry: int = 2, delay: float = 0.0):
        self.id = uuid.uuid4().hex[:10]
        self.source = source
        self.book = book
        self.chapters = chapters
        self.out_dir = out_dir
        self.workers = max(1, min(int(workers), 8))
        self.retry = max(0, int(retry))
        self.delay = max(0.0, float(delay))

        self.total = len(chapters)
        self.done = 0
        self.status = "pending"      # pending / running / paused / done / error / cancelled
        self.message = ""
        self.file_path = ""
        self.failed: list[dict] = []
        self.started_at = time.time()
        self.finished_at: float | None = None

        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._texts: dict[int, str] = {}
        self._cache_file = os.path.join(
            CACHE_DIR, f"{safe_name(book.get('name', ''))}_{source.id}.json")

    # ---------------- 状态 ----------------

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "message": self.message,
            "book_name": self.book.get("name", ""),
            "author": self.book.get("author", ""),
            "source_name": getattr(self.source, "name", ""),
            "total": self.total,
            "done": self.done,
            "failed": len(self.failed),
            "failed_list": self.failed[:50],
            "percent": round(self.done / self.total * 100, 1) if self.total else 0.0,
            "file": self.file_path,
            "elapsed": round((self.finished_at or time.time()) - self.started_at, 1),
        }

    def cancel(self) -> None:
        self._cancel.set()

    # ---------------- 缓存（断点续传） ----------------

    def _load_cache(self) -> None:
        os.makedirs(CACHE_DIR, exist_ok=True)
        if not os.path.isfile(self._cache_file):
            return
        try:
            with open(self._cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in (data.get("texts") or {}).items():
                idx = int(k)
                if 0 <= idx < self.total and v:
                    self._texts[idx] = v
            self.done = len(self._texts)
        except Exception:
            self._texts = {}

    def _save_cache(self) -> None:
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump({"book": self.book.get("name", ""),
                           "texts": {str(k): v for k, v in self._texts.items()}},
                          f, ensure_ascii=False)
        except Exception:
            pass

    def _drop_cache(self) -> None:
        try:
            if os.path.isfile(self._cache_file):
                os.remove(self._cache_file)
        except Exception:
            pass

    # ---------------- 主流程 ----------------

    def run(self) -> None:
        self.status = "running"
        self._load_cache()
        if self._texts:
            self.message = f"检测到缓存，续传 {len(self._texts)}/{self.total} 章"

        todo = [i for i in range(self.total) if i not in self._texts]

        def fetch(idx: int) -> tuple[int, str, str]:
            chap = self.chapters[idx]
            last_err = ""
            for attempt in range(self.retry + 1):
                if self._cancel.is_set():
                    return idx, "", "已取消"
                try:
                    if self.delay:
                        time.sleep(self.delay)
                    body = self.source.content(chap["url"])
                    if body.strip():
                        return idx, body, ""
                    last_err = "正文为空"
                except Exception as exc:
                    last_err = str(exc)[:200]
                time.sleep(0.6 * (attempt + 1))
            return idx, "", last_err

        try:
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                futures = [pool.submit(fetch, i) for i in todo]
                for fut in as_completed(futures):
                    if self._cancel.is_set():
                        break
                    idx, body, err = fut.result()
                    with self._lock:
                        if body:
                            self._texts[idx] = body
                        elif err and err != "已取消":
                            self.failed.append({
                                "index": idx + 1,
                                "title": self.chapters[idx]["title"],
                                "url": self.chapters[idx]["url"],
                                "error": err,
                            })
                        self.done = len(self._texts)
                        if self.done % 20 == 0:
                            self._save_cache()

            if self._cancel.is_set():
                self.status = "cancelled"
                self.message = "已取消，进度已缓存，可再次下载续传"
                self._save_cache()
                self.finished_at = time.time()
                return

            self._write_file()
            if self.failed:
                self.status = "done"
                self.message = f"完成，但有 {len(self.failed)} 章抓取失败"
            else:
                self.status = "done"
                self.message = "全部章节下载完成"
                self._drop_cache()
        except Exception as exc:
            self.status = "error"
            self.message = f"下载出错：{exc}"
            self._save_cache()
        finally:
            self.finished_at = time.time()

    def _write_file(self) -> None:
        os.makedirs(self.out_dir, exist_ok=True)
        name = safe_name(self.book.get("name", "未命名"))
        author = safe_name(self.book.get("author", ""))
        file_name = f"{name}_{author}.txt" if author else f"{name}.txt"
        path = os.path.join(self.out_dir, file_name)

        header = [
            f"书名：{self.book.get('name', '')}",
            f"作者：{self.book.get('author', '')}",
            f"分类：{self.book.get('kind', '')}",
            f"来源：{getattr(self.source, 'name', '')}（{self.book.get('book_url', '')}）",
            f"章节数：{self.total}",
            f"下载时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "简介：",
            (self.book.get("intro") or "").strip(),
            "",
            "=" * 40,
            "",
        ]

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(header))
            for i, chap in enumerate(self.chapters):
                body = self._texts.get(i, "")
                f.write(f"\n\n== {chap['title']} ==\n\n")
                f.write(body if body else "（本章抓取失败，可重试后重新下载）")
            f.write("\n")
        self.file_path = path


class TaskManager:
    def __init__(self):
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()

    def submit(self, source, book: dict, chapters: list[dict], out_dir: str = DOWNLOAD_DIR,
               workers: int = 4, retry: int = 2, delay: float = 0.0) -> Task:
        task = Task(source, book, chapters, out_dir, workers, retry, delay)
        with self._lock:
            self._tasks[task.id] = task
        threading.Thread(target=task.run, daemon=True).start()
        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def list(self) -> list[dict]:
        items = sorted(self._tasks.values(), key=lambda t: t.started_at, reverse=True)
        return [t.snapshot() for t in items[:50]]