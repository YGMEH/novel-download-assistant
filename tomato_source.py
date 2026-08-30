# -*- coding: utf-8 -*-
"""内置番茄小说源（fanqienovel.com 官方网页接口）。

本模块是独立 provider，与 Legado 书源池并列，接口契约与 BookSource 一致
（search/detail/toc/content、id/name/enabled/capability/to_dict），
server.py 与 downloader.py 可直接调用，无需感知差异。
能力边界（2026-08 实测）：
  - 搜索：番茄搜索接口被风控（返回空），本源不支持关键词搜索；
    支持「纯数字书 ID / fanqienovel.com 链接」直达建卡。
  - 详情：/page/{book_id}，正则字段解析（bookName/author/abstract/wordNumber），
    兼容页面 __NEXT_DATA__ / __INITIAL_STATE__ 两种承载形态。
  - 目录：/api/reader/directory/detail?bookId=，需 Referer + 浏览器 UA，
    返回按卷分组的嵌套列表，展开后与 allItemIds 顺序一致。
  - 正文：/reader/{chapter_id}，正文内约一成字符被 PUA 私有区字体反爬混淆，
    用下方静态映射表（经字体 cmap + OCR 校对，哈希 dc027189e0ba4cd，
    实测跨请求稳定）还原，无需 fonttools 依赖。
"""
from __future__ import annotations

import json
import re
import threading
import time
from html import unescape
from urllib.parse import urlparse

import requests

UA_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
BASE = "https://fanqienovel.com"
SOURCE_ID = "tomato_builtin"
SOURCE_NAME = "番茄小说·内置源"

# PUA 码位 -> 真实字符（映射稳定版；生成脚本与来源见 docs/tomato_builtin.md）
PUA_CHAR_MAP: dict[int, str] = {
    0xE3E8: 'd', 0xE3E9: '在', 0xE3EA: '主', 0xE3EB: '特',
    0xE3EC: '家', 0xE3ED: '军', 0xE3EE: '然', 0xE3EF: '表',
    0xE3F0: '场', 0xE3F1: '4', 0xE3F2: '要', 0xE3F3: '只',
    0xE3F4: 'v', 0xE3F5: '和', 0xE3F7: '6', 0xE3F8: '别',
    0xE3F9: '还', 0xE3FA: 'g', 0xE3FB: '现', 0xE3FC: '儿',
    0xE3FD: '岁', 0xE400: '此', 0xE401: '象', 0xE402: '月',
    0xE403: '3', 0xE404: '出', 0xE405: '战', 0xE406: '工',
    0xE407: '相', 0xE408: 'o', 0xE409: '男', 0xE40A: '直',
    0xE40B: '失', 0xE40C: '世', 0xE40D: 'F', 0xE40E: '都',
    0xE40F: '平', 0xE410: '文', 0xE411: '什', 0xE412: 'v',
    0xE413: 'o', 0xE414: '将', 0xE415: '真', 0xE416: 't',
    0xE417: '那', 0xE418: '当', 0xE41A: '会', 0xE41B: '立',
    0xE41C: '些', 0xE41D: 'u', 0xE41E: '是', 0xE41F: '十',
    0xE420: '张', 0xE421: '学', 0xE422: '气', 0xE423: '大',
    0xE424: '爱', 0xE425: '两', 0xE426: '命', 0xE427: '全',
    0xE428: '后', 0xE429: '东', 0xE42A: '性', 0xE42B: '通',
    0xE42C: '被', 0xE42D: '1', 0xE42E: '它', 0xE42F: '乐',
    0xE430: '接', 0xE431: '而', 0xE432: '感', 0xE433: '车',
    0xE434: '山', 0xE435: '公', 0xE436: '了', 0xE437: '常',
    0xE438: '以', 0xE439: '何', 0xE43A: '可', 0xE43B: '话',
    0xE43C: '先', 0xE43D: 'p', 0xE43E: 'i', 0xE43F: '叫',
    0xE440: '轻', 0xE441: 'm', 0xE442: '土', 0xE443: 'w',
    0xE444: '着', 0xE445: '变', 0xE446: '尔', 0xE447: '快',
    0xE448: 'l', 0xE449: '个', 0xE44A: '说', 0xE44B: '少',
    0xE44C: '色', 0xE44D: '里', 0xE44E: '安', 0xE44F: '花',
    0xE450: '远', 0xE451: '7', 0xE452: '难', 0xE453: '师',
    0xE454: '放', 0xE455: 't', 0xE456: '报', 0xE457: '认',
    0xE458: '面', 0xE459: '道', 0xE45A: 's', 0xE45C: '克',
    0xE45D: '地', 0xE45E: '度', 0xE45F: 'l', 0xE460: '好',
    0xE461: '机', 0xE462: 'U', 0xE463: '民', 0xE464: '写',
    0xE465: '把', 0xE466: '万', 0xE467: '同', 0xE468: '水',
    0xE469: '新', 0xE46A: '没', 0xE46B: '书', 0xE46C: '电',
    0xE46D: '吃', 0xE46E: '像', 0xE46F: '斯', 0xE470: '5',
    0xE471: '为', 0xE472: 'y', 0xE473: '自', 0xE474: '几',
    0xE475: '日', 0xE476: '教', 0xE477: '看', 0xE478: '但',
    0xE479: '第', 0xE47A: '加', 0xE47B: '候', 0xE47C: '作',
    0xE47D: '上', 0xE47E: '拉', 0xE47F: '住', 0xE480: '有',
    0xE481: '法', 0xE482: 'r', 0xE483: '事', 0xE484: '应',
    0xE485: '位', 0xE486: '利', 0xE487: '你', 0xE488: '声',
    0xE489: '身', 0xE48A: '国', 0xE48B: '问', 0xE48C: '马',
    0xE48D: '女', 0xE48E: '他', 0xE48F: 'y', 0xE490: '比',
    0xE491: '父', 0xE492: 'x', 0xE493: 'a', 0xE494: 'H',
    0xE495: 'N', 0xE496: 's', 0xE497: 'x', 0xE498: '边',
    0xE499: '美', 0xE49A: '对', 0xE49B: '所', 0xE49C: '金',
    0xE49D: '活', 0xE49E: '回', 0xE49F: '意', 0xE4A0: '到',
    0xE4A1: 'z', 0xE4A2: '从', 0xE4A3: 'j', 0xE4A4: '知',
    0xE4A5: '又', 0xE4A6: '内', 0xE4A7: '因', 0xE4A8: '点',
    0xE4A9: 'Q', 0xE4AA: '三', 0xE4AB: '定', 0xE4AC: '8',
    0xE4AD: 'r', 0xE4AE: 'b', 0xE4AF: '正', 0xE4B0: '或',
    0xE4B1: '夫', 0xE4B2: '向', 0xE4B3: '德', 0xE4B4: '听',
    0xE4B5: '更', 0xE4B7: '得', 0xE4B8: '告', 0xE4B9: '并',
    0xE4BA: '本', 0xE4BB: 'q', 0xE4BC: '过', 0xE4BD: '记',
    0xE4BE: 'L', 0xE4BF: '让', 0xE4C0: '打', 0xE4C1: 'f',
    0xE4C2: '人', 0xE4C3: '就', 0xE4C4: '者', 0xE4C5: '去',
    0xE4C6: '原', 0xE4C7: '满', 0xE4C8: '体', 0xE4C9: '做',
    0xE4CA: '经', 0xE4CB: 'k', 0xE4CC: '走', 0xE4CD: '如',
    0xE4CE: '孩', 0xE4CF: 'c', 0xE4D0: 'g', 0xE4D1: '给',
    0xE4D2: '使', 0xE4D3: '物', 0xE4D5: '最', 0xE4D6: '笑',
    0xE4D7: '部', 0xE4D9: '员', 0xE4DA: '等', 0xE4DB: '受',
    0xE4DC: 'k', 0xE4DD: '行', 0xE4DE: '一', 0xE4DF: '条',
    0xE4E0: '果', 0xE4E1: '动', 0xE4E2: '光', 0xE4E3: '门',
    0xE4E4: '头', 0xE4E5: '见', 0xE4E6: '往', 0xE4E7: '自',
    0xE4E8: '解', 0xE4E9: '成', 0xE4EA: '处', 0xE4EB: '天',
    0xE4EC: '能', 0xE4ED: '于', 0xE4EE: '名', 0xE4EF: '其',
    0xE4F0: '发', 0xE4F1: '总', 0xE4F2: '母', 0xE4F3: '的',
    0xE4F4: '死', 0xE4F5: '手', 0xE4F6: '入', 0xE4F7: '路',
    0xE4F8: '进', 0xE4F9: '心', 0xE4FA: '来', 0xE4FB: 'h',
    0xE4FC: '时', 0xE4FD: '力', 0xE4FE: '多', 0xE4FF: '开',
    0xE500: '已', 0xE501: '许', 0xE502: 'd', 0xE503: '至',
    0xE504: '由', 0xE505: '很', 0xE506: '界', 0xE507: 'n',
    0xE508: '小', 0xE509: '与', 0xE50A: 'z', 0xE50B: '想',
    0xE50C: '代', 0xE50D: '么', 0xE50E: '分', 0xE50F: '生',
    0xE510: '口', 0xE511: '再', 0xE512: '妈', 0xE513: '望',
    0xE514: '次', 0xE515: '西', 0xE516: '风', 0xE517: '种',
    0xE518: '带', 0xE519: 'J', 0xE51B: '实', 0xE51C: '情',
    0xE51D: '才', 0xE51E: '这', 0xE520: 'e', 0xE521: '我',
    0xE522: '神', 0xE523: '格', 0xE524: '长', 0xE525: '觉',
    0xE526: '间', 0xE527: '年', 0xE528: '眼', 0xE529: '无',
    0xE52A: '不', 0xE52B: '亲', 0xE52C: '关', 0xE52D: '结',
    0xE52E: '0', 0xE52F: '友', 0xE530: '信', 0xE531: '下',
    0xE532: '却', 0xE533: '重', 0xE534: '己', 0xE535: '老',
    0xE536: '2', 0xE537: '音', 0xE538: '字', 0xE539: 'm',
    0xE53A: '呢', 0xE53B: '明', 0xE53C: '之', 0xE53D: '前',
    0xE53E: '高', 0xE53F: 'p', 0xE540: 'b', 0xE541: '目',
    0xE542: '太', 0xE543: 'e', 0xE544: '9', 0xE545: '起',
    0xE546: '棱', 0xE547: '她', 0xE548: '也', 0xE549: 'w',
    0xE54A: '用', 0xE54B: '方', 0xE54C: '子', 0xE54D: '英',
    0xE54E: '每', 0xE54F: '理', 0xE550: '便', 0xE551: '四',
    0xE552: '数', 0xE553: '期', 0xE554: '中', 0xE555: 'c',
    0xE556: '外', 0xE557: '样', 0xE558: 'a', 0xE559: '海',
    0xE55A: '们', 0xE55B: '任',
}
_PUA_TABLE = dict(PUA_CHAR_MAP)


class TomatoError(Exception):
    """内置番茄源错误。"""


def _decode_pua(text: str) -> str:
    return text.translate(_PUA_TABLE)


def extract_book_id(text: str) -> str:
    """从纯数字、/page/{id}、book_id= 参数或任意番茄链接中提取书 ID。"""
    text = (text or "").strip()
    if re.fullmatch(r"\d{10,20}", text):
        return text
    m = (re.search(r"/page/(\d{10,20})", text)
         or re.search(r"book_id[=:](\d{10,20})", text)
         or re.search(r"bookId[=:](\d{10,20})", text))
    if m:
        return m.group(1)
    if "fanqienovel.com" in text:
        m = re.search(r"(\d{10,20})", text)
        if m:
            return m.group(1)
    return ""


def extract_item_id(url: str) -> str:
    """从 /reader/{id} 或纯数字中提取章节 ID。"""
    text = (url or "").strip()
    if re.fullmatch(r"\d{10,20}", text):
        return text
    m = re.search(r"/reader/(\d{10,20})", text)
    return m.group(1) if m else ""


class TomatoSource:
    """内置番茄源。线程安全：内部复用 requests.Session（连接池线程安全）。"""

    def __init__(self):
        self.id = SOURCE_ID
        self.name = SOURCE_NAME
        self.url = BASE
        self.group = "内置"
        self.enabled = True
        self._session = requests.Session()
        self._session.trust_env = False
        self._session.headers.update({"User-Agent": UA_DESKTOP})
        self._lock = threading.Lock()
        self._last_hit = 0.0

    # ---------------- 基础 ----------------

    def capability(self) -> dict:
        return {
            "searchable": False,      # 关键词搜索被风控；书 ID 直达走单源自搜
            "downloadable": True,
            "quality": 80,
            "problems": ["不支持关键词搜索（官方风控），支持书 ID/链接直达"],
        }

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "group": self.group,
            "comment": "官方网页接口：详情/目录/正文全可用，正文含字体反爬自动还原；"
                       "搜索仅支持书 ID 或番茄链接直达。",
            "enabled": self.enabled,
            "file": "builtin:tomato",
            "searchable": False,
            "downloadable": True,
            "quality": 80,
            "problems": ["不支持关键词搜索（官方风控），支持书 ID/链接直达"],
        }

    def _throttle(self, min_gap: float = 0.5) -> None:
        with self._lock:
            gap = time.time() - self._last_hit
            if gap < min_gap:
                time.sleep(min_gap - gap)
            self._last_hit = time.time()

    def _get(self, url: str, referer: str | None = None,
             timeout: int = 20, retries: int = 2) -> str:
        headers = {"Referer": referer} if referer else {}
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            self._throttle()
            try:
                resp = self._session.get(url, headers=headers, timeout=timeout)
                if resp.status_code == 403:
                    # 预热：访问一次详情页拿 Cookie 再重试
                    book_hint = extract_book_id(referer or "") or extract_book_id(url)
                    if book_hint:
                        self._session.get(f"{BASE}/page/{book_hint}",
                                          headers={"User-Agent": UA_DESKTOP}, timeout=timeout)
                    last_exc = TomatoError(f"HTTP 403（{url}）")
                    continue
                resp.raise_for_status()
                if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
                    resp.encoding = "utf-8"
                return resp.text
            except TomatoError:
                last_exc = last_exc or TomatoError(f"HTTP 403（{url}）")
            except Exception as exc:
                last_exc = exc
            time.sleep(0.8 * (attempt + 1))
        raise TomatoError(f"请求失败：{url}（{last_exc}）")

    # ---------------- 搜索（书 ID / 链接直达） ----------------

    def search(self, key: str, page: int = 1, limit: int = 20,
               timeout: int = 20) -> list[dict]:
        book_id = extract_book_id(key)
        if not book_id:
            raise TomatoError(
                "番茄内置源不支持关键词搜索（官方风控）。"
                "请输入番茄书 ID（纯数字）或 fanqienovel.com 书籍链接。")
        detail = self.detail(f"{BASE}/page/{book_id}", timeout=timeout)
        return [{
            "source_id": self.id,
            "source_name": self.name,
            "source_quality": 80,
            "name": detail.get("name", ""),
            "author": detail.get("author", ""),
            "kind": detail.get("kind", ""),
            "intro": (detail.get("intro", "") or "")[:300],
            "cover": detail.get("cover", ""),
            "last_chapter": detail.get("last_chapter", ""),
            "word_count": detail.get("word_count", ""),
            "book_url": detail.get("book_url", ""),
        }]

    # ---------------- 详情 ----------------

    @staticmethod
    def _json_slice(raw: str, marker: str) -> str | None:
        """取 marker= 后的平衡 JSON 串（考虑字符串转义）。"""
        m = re.search(re.escape(marker) + r"\s*=\s*", raw)
        if not m:
            return None
        start = m.end()
        i, depth, instr, esc = start, 0, False, False
        while i < len(raw):
            c = raw[i]
            if instr:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    instr = False
            else:
                if c == '"':
                    instr = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        return raw[start:i + 1]
            i += 1
        return None

    @staticmethod
    def _rx1(raw: str, pattern: str) -> str:
        m = re.search(pattern, raw)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _ld_image(raw: str) -> str:
        """从 ld+json 结构化数据块提取封面。

        番茄详情页有两个 JSON-LD 块：
        - NewsArticle：image 为 URL 数组；
        - 百度 cambrian：images 为 URL 数组。
        两者通常指向同一张封面图，取第一个 http 开头的 URL 即可。
        """
        for block in re.findall(r"application/ld[+]json[^>]*>(.*?)</script>",
                                raw, re.S):
            try:
                data = json.loads(block.strip())
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            for key in ("image", "images"):
                val = data.get(key)
                if isinstance(val, str) and val.startswith("http"):
                    return val
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, str) and item.startswith("http"):
                            return item
        return ""

    def detail(self, book_url: str, timeout: int = 20) -> dict:
        book_id = extract_book_id(book_url) or extract_book_id(
            urlparse(book_url).query)
        if not book_id:
            raise TomatoError(f"无法从地址提取书 ID：{book_url}")
        page_url = f"{BASE}/page/{book_id}"
        raw = self._get(page_url, referer=BASE, timeout=timeout)

        name = self._rx1(raw, r'"bookName"\s*:\s*"([^"]+)"')
        author = self._rx1(raw, r'"author"\s*:\s*"([^"]+)"')
        intro = self._rx1(raw, r'"abstract"\s*:\s*"([^"]+)"')
        word_count = self._rx1(raw, r'"wordNumber"\s*:\s*(\d+)')
        cover = (self._rx1(raw, r'<meta property="og:image" content="([^"]+)"')
                 or self._rx1(raw, r'"thumb_url"\s*:\s*"([^"]+)"')
                 or self._ld_image(raw))
        if cover.startswith("//"):
            cover = "https:" + cover
        kind = self._rx1(raw, r'"category"\s*:\s*"([^"]+)"')

        if not name:
            raise TomatoError("详情解析失败：未找到书名（页面可能改版或被风控）")

        return {
            "source_id": self.id,
            "source_name": self.name,
            "name": unescape(name),
            "author": unescape(author),
            "kind": unescape(kind),
            "intro": unescape(intro),
            "cover": cover,
            "last_chapter": "",
            "word_count": word_count,
            "book_url": page_url,
            "toc_url": page_url,
        }

    # ---------------- 目录 ----------------

    def toc(self, toc_url: str, timeout: int = 20,
            max_pages: int = 1) -> list[dict]:
        book_id = extract_book_id(toc_url)
        if not book_id:
            raise TomatoError(f"无法从地址提取书 ID：{toc_url}")
        api = f"{BASE}/api/reader/directory/detail?bookId={book_id}"
        raw = self._get(api, referer=f"{BASE}/page/{book_id}", timeout=timeout)
        try:
            data = json.loads(raw).get("data") or {}
        except Exception as exc:
            raise TomatoError(f"目录接口返回异常：{exc}")

        chapters: list[dict] = []
        seen: set[str] = set()
        # chapterListWithVolume 形如 [[章...], [章...]]，外层按卷、内层按序
        for vol in data.get("chapterListWithVolume") or []:
            if isinstance(vol, dict):
                vol = vol.get("chapters") or []
            for ch in vol:
                item_id = str(ch.get("itemId") or "").strip()
                title = unescape(str(ch.get("title") or "")).strip()
                if not item_id or not title or item_id in seen:
                    continue
                seen.add(item_id)
                chapters.append({
                    "title": title,
                    "url": f"{BASE}/reader/{item_id}",
                    "volume": unescape(str(ch.get("volume_name") or "")),
                })
        if not chapters:
            raise TomatoError("目录为空（可能需要登录或已被风控）")
        return chapters

    # ---------------- 正文 ----------------

    def content(self, chapter_url: str, timeout: int = 20,
                max_pages: int = 1) -> str:
        item_id = extract_item_id(chapter_url)
        if not item_id:
            raise TomatoError(f"无法从地址提取章节 ID：{chapter_url}")
        url = f"{BASE}/reader/{item_id}"
        raw = self._get(url, timeout=timeout)
        raw = unescape(raw)

        m = re.search(
            r'<div class="muye-reader-content[^"]*"[^>]*>(.*?)</div>\s*</div>',
            raw, re.S)
        scope = m.group(1) if m else raw
        paras: list[str] = []
        for p in re.findall(r"<p[^>]*>(.*?)</p>", scope, re.S):
            t = re.sub(r"<[^>]+>", "", p)
            t = _decode_pua(t).strip()
            if t:
                paras.append(t)
        if not paras:
            raise TomatoError("正文解析为空（页面可能改版、需要登录或被风控）")
        return "\n".join(paras)


# 模块级单例：server.py 直接 import 使用
tomato_source = TomatoSource()