# -*- coding: utf-8 -*-
"""本地 HTTP 服务：书源管理 + 搜索 + 目录 + 下载。

安全说明：默认只监听 127.0.0.1，不做鉴权，仅供本机使用。
若要监听 0.0.0.0（局域网可访问），请自行加上鉴权，否则同网段任何人都能调用你的下载接口。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
import threading
import webbrowser

from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, jsonify, request, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import downloader  # noqa: E402
import rule_engine as R  # noqa: E402
import tomato_source as builtin_tomato  # noqa: E402
from source_manager import SourceStore  # noqa: E402

app = Flask(__name__, static_folder=None)
store = SourceStore()
tasks = downloader.TaskManager()
_DETAIL_CACHE: dict[tuple[str, str], dict] = {}
_TOC_CACHE: dict[tuple[str, str], list[dict]] = {}
_CACHE_LOCK = threading.Lock()
_SEARCH_POOL = ThreadPoolExecutor(max_workers=32)
_SEARCH_JOBS: dict[str, dict] = {}
_SEARCH_LOCK = threading.Lock()


@app.after_request
def _cors(resp):
    """允许 file:// 或局域网设备打开的前端页面访问本机接口。"""
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = (
        "Content-Type, Access-Control-Request-Private-Network"
    )
    resp.headers["Access-Control-Allow-Private-Network"] = "true"
    return resp


@app.route("/api/<path:_any>", methods=["OPTIONS"])
def api_options(_any):
    return ("", 204)

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DEFAULT_CONFIG = {
    "download_dir": downloader.DOWNLOAD_DIR,
    "workers": 4,
    "retry": 2,
    "delay": 0.0,
    "timeout": 20,
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f) or {})
        except Exception:
            pass
    return cfg


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def ok(data=None, **extra):
    payload = {"success": True}
    if data is not None:
        payload["data"] = data
    payload.update(extra)
    return jsonify(payload)


def fail(message: str, code: int = 400):
    return jsonify({"success": False, "message": str(message)}), code


def _get_source(source_id: str):
    """按 ID 取书源：先查导入书源库，再落到内置源（当前为番茄内置）。"""
    try:
        return store.get(source_id)
    except KeyError:
        if source_id == builtin_tomato.SOURCE_ID:
            return builtin_tomato.tomato_source
        raise


# --------------------------------------------------------------------------
# 静态页面
# --------------------------------------------------------------------------

@app.get("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/static/<path:name>")
def static_file(name: str):
    return send_from_directory(os.path.join(BASE_DIR, "static"), name)


# --------------------------------------------------------------------------
# 书源管理
# --------------------------------------------------------------------------

@app.get("/api/sources")
def api_sources():
    keyword = (request.args.get("q") or "").strip().lower()
    brief = str(request.args.get("brief") or "").lower() in ("1", "true", "yes")
    items = [s.to_dict() for s in store.all()]
    items.append(builtin_tomato.tomato_source.to_dict())
    if keyword:
        items = [i for i in items
                 if keyword in i["name"].lower() or keyword in i["url"].lower()
                 or keyword in i["group"].lower()]
    items.sort(key=lambda i: (not i["enabled"], not i["downloadable"], i["name"]))
    files = sorted({i["file"] for i in items if i["file"]})
    payload = {
        "sources": [] if brief else items,
        "files": files,
        "total": len(items),
        "usable": sum(1 for i in items if i["enabled"] and i["searchable"] and i["downloadable"]),
    }
    return ok(payload)


@app.post("/api/sources/import")
def api_sources_import():
    body = request.get_json(silent=True) or {}
    try:
        if body.get("url"):
            result = store.import_from_url(body["url"].strip())
        elif body.get("text"):
            result = store.import_payload(body["text"], body.get("file_name"))
        else:
            return fail("请提供 url 或 text")
    except Exception as exc:
        return fail(f"导入失败：{exc}")
    return ok(result, message=f"已导入 {result['count']} 个书源")


@app.post("/api/sources/delete")
def api_sources_delete():
    body = request.get_json(silent=True) or {}
    file_name = (body.get("file") or "").strip()
    if not file_name:
        return fail("缺少 file")
    try:
        store.delete_file(file_name)
    except Exception as exc:
        return fail(str(exc))
    return ok(message=f"已删除 {file_name}")


@app.post("/api/sources/toggle")
def api_sources_toggle():
    body = request.get_json(silent=True) or {}
    try:
        store.set_enabled(body.get("id", ""), bool(body.get("enabled", True)))
    except Exception as exc:
        return fail(str(exc))
    return ok()


@app.post("/api/sources/reload")
def api_sources_reload():
    store.reload()
    return ok(message=f"已重新加载 {len(store.all())} 个书源")


# --------------------------------------------------------------------------
# 搜索 / 详情 / 目录
# --------------------------------------------------------------------------

@app.get("/api/search")
def api_search():
    key = (request.args.get("key") or "").strip()
    source_id = (request.args.get("source_id") or "").strip()
    page = int(request.args.get("page") or 1)
    if not key:
        return fail("请输入书名")
    if not source_id:
        return fail("请选择书源")
    try:
        src = _get_source(source_id)
    except KeyError as exc:
        return fail(str(exc), 404)

    cfg = load_config()
    try:
        results = src.search(key, page=page, timeout=int(cfg["timeout"]))
    except R.UnsupportedRule as exc:
        return fail(f"该书源不被支持：{exc}")
    except Exception as exc:
        return fail(f"搜索失败：{exc}")
    return ok({"results": results, "source": src.to_dict()})


def _normalize_author(value):
    value = str(value or "").strip().lower()
    for prefix in ("作者：", "作者:", "作者", "作家：", "作家:", "作家"):
        if value.startswith(prefix):
            value = value[len(prefix):].strip()
            break
    return "".join(value.split())


def _search_one(job_id, src, key, limit, timeout, page=1, precision=False,
                author_pages=1):
    with _SEARCH_LOCK:
        job = _SEARCH_JOBS.get(job_id)
        if job is None or job.get("cancelled"):
            return  # 已取消/已过期：未开始的任务直接退出，不占线程池继续请求
    try:
        rows = src.search(key, page=page, limit=limit, timeout=timeout)
        key_norm = _normalize_author(key)
        author_match = any(
            _normalize_author(r.get("author")) == key_norm
            for r in rows
        )
        if author_match and author_pages > 1:
            seen = {(r.get("book_url"), r.get("source_id")) for r in rows}
            for next_page in range(page + 1, page + author_pages):
                more = src.search(key, page=next_page, limit=limit, timeout=timeout)
                added = 0
                for row in more:
                    marker = (row.get("book_url"), row.get("source_id"))
                    if marker not in seen:
                        seen.add(marker)
                        rows.append(row)
                        added += 1
                if not more or not added:
                    break
        if precision:
            low = key.lower()
            rows = [
                r for r in rows
                if low in (r.get("name") or "").lower()
                or low in (r.get("author") or "").lower()
                or low in (r.get("kind") or "").lower()
            ]
        with _SEARCH_LOCK:
            job = _SEARCH_JOBS.get(job_id)
            if job is None or job.get("cancelled"):
                return
            job["results"].extend(rows)
            job["done"] += 1
    except Exception as exc:
        with _SEARCH_LOCK:
            job = _SEARCH_JOBS.get(job_id)
            if job is not None and not job.get("cancelled"):
                job["fails"].append(f"{src.name}：{exc}")
                job["done"] += 1


def _prune_search_jobs():
    """清理早已结束的搜索任务，避免 _SEARCH_JOBS 无限增长。"""
    now = time.time()
    dead = [
        k for k, j in _SEARCH_JOBS.items()
        if (j.get("cancelled") and now - j["created"] > 60)
        or (j["done"] >= j["total"] and now - j["created"] > 600)
    ]
    for k in dead:
        _SEARCH_JOBS.pop(k, None)


@app.post("/api/search_start")
def api_search_start():
    body = request.get_json(silent=True) or {}
    key = (body.get("key") or "").strip()
    if not key:
        return fail("请输入书名")
    cfg = load_config()
    timeout = min(int(cfg.get("timeout", 20)), 6)
    limit = max(1, min(int(body.get("limit") or 6), 20))
    page = max(1, int(body.get("page") or 1))
    precision = bool(body.get("precision", False))
    sources = [s for s in store.all() if s.enabled and s.capability()["searchable"]]
    job_id = uuid.uuid4().hex
    with _SEARCH_LOCK:
        _prune_search_jobs()
        _SEARCH_JOBS[job_id] = {
            "results": [], "fails": [], "total": len(sources), "done": 0,
            "created": time.time(), "cancelled": False, "page": page, "key": key,
        }
    for src in sources:
        _SEARCH_POOL.submit(_search_one, job_id, src, key, limit, timeout, page, precision)
    return ok({"job_id": job_id, "total": len(sources), "page": page})


@app.get("/api/search_poll")
def api_search_poll():
    job_id = (request.args.get("job_id") or "").strip()
    with _SEARCH_LOCK:
        job = _SEARCH_JOBS.get(job_id)
        if job is None:
            return fail("搜索任务不存在或已过期", 404)
        finished = job.get("cancelled") or job["done"] >= job["total"]
        data = {
            "results": list(job["results"]), "fails": list(job["fails"]),
            "total": job["total"], "done": job["done"], "finished": finished,
            "cancelled": bool(job.get("cancelled")), "page": job.get("page", 1),
        }
    return ok(data)


@app.post("/api/search_cancel")
def api_search_cancel():
    body = request.get_json(silent=True) or {}
    job_id = (body.get("job_id") or "").strip()
    with _SEARCH_LOCK:
        job = _SEARCH_JOBS.get(job_id)
        if job is None:
            return fail("搜索任务不存在或已过期", 404)
        job["cancelled"] = True
    return ok()


@app.get("/api/search_all")
def api_search_all():
    """服务端并发搜索全部启用且可搜索的书源。

    浏览器对同一 origin 的并发连接数有限制（HTTP/1.1 一般 6 条），
    前端 8 路并发打 130+ 个源会被连接队列卡死；这里用服务端线程池并发，
    绕开浏览器限制，整体速度快很多。
    """
    key = (request.args.get("key") or "").strip()
    if not key:
        return fail("请输入书名")
    cfg = load_config()
    per_timeout = min(int(cfg.get("timeout", 20)), 6)   # 单源限时 6 秒
    limit = int(request.args.get("limit") or 6)         # 每源最多取 6 条
    sources = [s for s in store.all() if s.enabled and s.capability()["searchable"]]

    def run(src):
        try:
            return src, src.search(key, page=1, limit=limit, timeout=per_timeout)
        except Exception as exc:
            return src, exc

    results: list[dict] = []
    fails: list[str] = []
    with ThreadPoolExecutor(max_workers=32) as ex:
        futs = [ex.submit(run, s) for s in sources]
        for f in as_completed(futs):
            src, res = f.result()
            if isinstance(res, Exception):
                fails.append(f"{src.name}：{res}")
            else:
                for item in res:
                    results.append(item)
    return ok({"results": results, "fails": fails, "total": len(sources)})


@app.post("/api/split_text")
def api_split_text():
    """把上传的文本按份数均衡分割，保存到下载目录。"""
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "split.txt").strip()
    text = body.get("text") or ""
    try:
        parts = int(body.get("parts") or 2)
    except (TypeError, ValueError):
        return fail("份数需为数字")
    if not text:
        return fail("文本为空")
    if not (1 <= parts <= 50):
        return fail("份数需在 1-50 之间")

    lines = text.split("\n")
    total_len = sum(len(ln) + 1 for ln in lines)
    target = total_len / parts
    chunks: list[list[str]] = []
    cur: list[str] = []
    cur_len = 0
    for ln in lines:
        cur.append(ln)
        cur_len += len(ln) + 1
        if cur_len >= target and len(chunks) < parts - 1:
            chunks.append(cur)
            cur, cur_len = [], 0
    if cur or not chunks:
        chunks.append(cur)
    # 均分后份数不足 parts（空行很多时），用空行补齐语义上的份数
    while len(chunks) < parts:
        chunks.append([])

    cfg = load_config()
    d = cfg["download_dir"]
    base = os.path.splitext(os.path.basename(name))[0] or "split"
    saved: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        fn = f"{base}_part{i}.txt"
        path = os.path.join(d, fn)
        n = 1
        while os.path.exists(path):
            fn = f"{base}_part{i}_{n}.txt"
            path = os.path.join(d, fn)
            n += 1
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(chunk))
        saved.append(fn)
    return ok({"files": saved}, message=f"已分割为 {len(saved)} 份")


@app.get("/api/detail")
def api_detail():
    source_id = (request.args.get("source_id") or "").strip()
    book_url = (request.args.get("book_url") or "").strip()
    if not source_id or not book_url:
        return fail("缺少 source_id 或 book_url")
    try:
        src = _get_source(source_id)
    except KeyError as exc:
        return fail(str(exc), 404)
    cache_key = (source_id, book_url)
    with _CACHE_LOCK:
        cached = _DETAIL_CACHE.get(cache_key)
    if cached is not None:
        return ok(cached)
    cfg = load_config()
    try:
        detail = src.detail(book_url, timeout=int(cfg["timeout"]))
    except Exception as exc:
        return fail(f"获取详情失败：{exc}")
    with _CACHE_LOCK:
        _DETAIL_CACHE[cache_key] = detail
    return ok(detail)


@app.get("/api/toc")
def api_toc():
    source_id = (request.args.get("source_id") or "").strip()
    toc_url = (request.args.get("toc_url") or "").strip()
    if not source_id or not toc_url:
        return fail("缺少 source_id 或 toc_url")
    try:
        src = _get_source(source_id)
    except KeyError as exc:
        return fail(str(exc), 404)
    cache_key = (source_id, toc_url)
    with _CACHE_LOCK:
        cached = _TOC_CACHE.get(cache_key)
    if cached is not None:
        return ok({"count": len(cached), "chapters": cached, "cached": True})
    cfg = load_config()
    try:
        chapters = src.toc(toc_url, timeout=int(cfg["timeout"]))
    except Exception as exc:
        return fail(f"获取目录失败：{exc}")
    with _CACHE_LOCK:
        _TOC_CACHE[cache_key] = chapters
    return ok({"count": len(chapters), "chapters": chapters, "cached": False})


@app.get("/api/content")
def api_content():
    """章节正文。默认返回前 2000 字预览；full=1 返回完整正文，供在线阅读使用。"""
    source_id = (request.args.get("source_id") or "").strip()
    url = (request.args.get("url") or "").strip()
    full = (request.args.get("full") or "").strip() in ("1", "true", "yes")
    if not source_id or not url:
        return fail("缺少 source_id 或 url")
    try:
        src = _get_source(source_id)
    except KeyError as exc:
        return fail(str(exc), 404)
    try:
        body = src.content(url, timeout=int(load_config()["timeout"]))
    except Exception as exc:
        return fail(f"获取正文失败：{exc}")
    data = {"length": len(body), "preview": body[:2000]}
    if full:
        data["content"] = body
    return ok(data)


# --------------------------------------------------------------------------
# 下载任务
# --------------------------------------------------------------------------

@app.post("/api/download")
def api_download():
    body = request.get_json(silent=True) or {}
    source_id = (body.get("source_id") or "").strip()
    book = body.get("book") or {}
    toc_url = (body.get("toc_url") or book.get("toc_url") or "").strip()
    chapters = body.get("chapters")

    if not source_id:
        return fail("缺少 source_id")
    try:
        src = _get_source(source_id)
    except KeyError as exc:
        return fail(str(exc), 404)

    cfg = load_config()
    if not chapters:
        if not toc_url:
            return fail("缺少 toc_url 或 chapters")
        try:
            chapters = src.toc(toc_url, timeout=int(cfg["timeout"]))
        except Exception as exc:
            return fail(f"获取目录失败：{exc}")
    if not chapters:
        return fail("目录为空，无法下载")

    out_dir = body.get("download_dir") or cfg["download_dir"]
    task = tasks.submit(
        src, book, chapters, out_dir,
        workers=body.get("workers", cfg["workers"]),
        retry=body.get("retry", cfg["retry"]),
        delay=body.get("delay", cfg["delay"]),
    )
    return ok(task.snapshot(), message="已开始下载")


@app.get("/api/tasks")
def api_tasks():
    return ok({"tasks": tasks.list()})


@app.get("/api/task/<task_id>")
def api_task(task_id: str):
    task = tasks.get(task_id)
    if not task:
        return fail("任务不存在", 404)
    return ok(task.snapshot())


@app.post("/api/task/<task_id>/cancel")
def api_task_cancel(task_id: str):
    task = tasks.get(task_id)
    if not task:
        return fail("任务不存在", 404)
    task.cancel()
    return ok(message="已请求取消")


# --------------------------------------------------------------------------
# 配置 / 已下载文件
# --------------------------------------------------------------------------

@app.get("/api/config")
def api_get_config():
    return ok(load_config())


@app.post("/api/config")
def api_set_config():
    body = request.get_json(silent=True) or {}
    cfg = load_config()
    for field in ("download_dir", "workers", "retry", "delay", "timeout"):
        if field in body:
            cfg[field] = body[field]
    save_config(cfg)
    return ok(cfg, message="配置已保存")


@app.get("/api/files")
def api_files():
    cfg = load_config()
    directory = cfg["download_dir"]
    items = []
    if os.path.isdir(directory):
        for name in sorted(os.listdir(directory)):
            path = os.path.join(directory, name)
            if os.path.isfile(path):
                items.append({
                    "name": name,
                    "size_kb": round(os.path.getsize(path) / 1024, 1),
                    "path": path,
                })
    return ok({"dir": directory, "files": items})


@app.get("/api/files/<path:name>")
def api_file_download(name: str):
    cfg = load_config()
    return send_from_directory(cfg["download_dir"], os.path.basename(name), as_attachment=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="小说下载助手 · 本地服务")
    default_host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    parser.add_argument("--host", default=default_host,
                        help="监听地址，默认仅本机；检测到 PORT 环境变量（云平台部署）时自动改为 0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    parser.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    args = parser.parse_args()

    os.makedirs(load_config()["download_dir"], exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, "sources"), exist_ok=True)

    if args.host not in ("127.0.0.1", "localhost"):
        print("[警告] 你正在监听非本机地址，本服务没有鉴权，"
              "同网段任何人都能调用下载接口，请自行加访问控制。")

    url = f"http://{args.host}:{args.port}"
    print(f"小说下载助手已启动：{url}")
    print(f"书源目录：{os.path.join(BASE_DIR, 'sources')}（书源需自行导入）")
    print(f"下载目录：{load_config()['download_dir']}")
    if args.open:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()