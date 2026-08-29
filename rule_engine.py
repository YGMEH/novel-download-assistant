# -*- coding: utf-8 -*-
"""书源规则引擎（兼容 Legado 风格书源 JSON 的常用子集）。

支持的规则语法：
  css:选择器@属性        例：css:.result li@text
  xpath://div[@id='x']   例：xpath://div[@class='chapter']//a/@href
  json:$.data.list       例：json:$.data.list[*].name
  regex:正则             例：regex:<title>(.*?)</title>
  默认规则（Legado 风格） 例：class.book-list@tag.li  /  tag.a@href
  || 多规则回退，取第一个非空结果
  ## 正则处理，rule##pattern 表示删除匹配，rule##pattern##replace 表示替换

不支持（会被跳过并在结果里提示）：
  @js: / <js> 内嵌 JavaScript、WebView 渲染、登录态、验证码、加密签名类书源。
"""
from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any

import requests
from lxml import etree, html as lhtml

try:
    from jsonpath_ng.ext import parse as jsonpath_parse
except Exception:  # pragma: no cover
    jsonpath_parse = None

_JPATH_CACHE: dict[str, Any] = {}


def _jsonpath_compiled(expr: str) -> Any:
    compiled = _JPATH_CACHE.get(expr)
    if compiled is None:
        compiled = jsonpath_parse(expr)
        _JPATH_CACHE[expr] = compiled
    return compiled

DEFAULT_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 6) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)
TEXT_ATTRS = {"text", "textnodes", "owntext", "html", "innerhtml", "outerhtml", "all"}
JS_MARKERS = ("@js:", "<js>", "{{java.", "@Header", "webView")


class RuleError(Exception):
    """规则解析或抓取失败。"""


class UnsupportedRule(RuleError):
    """规则用到了本引擎不支持的能力。"""


def _encode(value: str, charset: str | None) -> str:
    if not value:
        return ""
    if charset and charset.lower() not in ("utf-8", "utf8"):
        try:
            return urllib.parse.quote(value.encode(charset))
        except Exception:
            pass
    return urllib.parse.quote(value)


def _replace_vars(text: str, key: str | None, page: int, charset: str | None) -> str:
    if not text:
        return text
    key = key or ""
    mapping = {"{{key}}": _encode(key, charset), "{{page}}": str(page), "searchKey": _encode(key, charset), "searchPage": str(page)}
    out = text
    for token, value in mapping.items():
        out = out.replace(token, value)

    def _calc(match: re.Match) -> str:
        expr = match.group(1)
        try:
            return str(int(eval(expr, {"__builtins__": {}}, {"page": page})))  # noqa: S307
        except Exception:
            return match.group(0)

    return re.sub(r"\{\{\s*(page\s*[-+*/]\s*\d+)\s*\}\}", _calc, out)


def parse_url_spec(spec: str, key: str | None = None, page: int = 1) -> dict:
    if not spec or not str(spec).strip():
        raise RuleError("URL 规则为空")
    spec = str(spec).strip()
    if any(marker in spec for marker in JS_MARKERS):
        raise UnsupportedRule("该书源的 URL 规则使用了 JS/脚本，本引擎不支持")
    options: dict[str, Any] = {}
    url_part = spec
    match = re.search(r",\s*(\{.*\})\s*$", spec, re.S)
    if match:
        try:
            options = json.loads(match.group(1))
            url_part = spec[: match.start()].strip()
        except Exception:
            options = {}
    charset = options.get("charset")
    method = str(options.get("method", "GET")).upper()
    body = options.get("body")
    if isinstance(body, (dict, list)):
        body = json.dumps(body, ensure_ascii=False)
    url = _replace_vars(url_part, key, page, charset)
    if body:
        body = _replace_vars(str(body), key, page, charset)
    headers = options.get("headers") or {}
    if isinstance(headers, str):
        try:
            headers = json.loads(headers)
        except Exception:
            headers = {}
    return {"url": url, "method": method, "body": body, "charset": charset, "headers": headers, "webView": bool(options.get("webView"))}


def _safe_referer(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parts = urllib.parse.urlsplit(str(value))
        safe = urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
        safe.encode("latin-1")
        return safe
    except (UnicodeEncodeError, ValueError):
        return None


def http_fetch(session: requests.Session, spec: str, base_headers: dict | None = None, key: str | None = None, page: int = 1, timeout: int = 20, referer: str | None = None) -> tuple[str, str]:
    info = parse_url_spec(spec, key, page)
    if info["webView"]:
        raise UnsupportedRule("该书源需要 WebView 渲染，本引擎不支持")
    headers = {"User-Agent": DEFAULT_UA}
    if base_headers:
        headers.update({str(k): str(v) for k, v in base_headers.items()})
    headers.update({str(k): str(v) for k, v in info["headers"].items()})
    if referer:
        safe_referer = _safe_referer(referer)
        if safe_referer:
            headers["Referer"] = safe_referer
    resp = session.request(info["method"], info["url"], data=info["body"], headers=headers, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    if info["charset"]:
        resp.encoding = info["charset"]
    elif not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text, resp.url


def build_context(text: str) -> Any:
    stripped = (text or "").lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            return json.loads(stripped)
        except Exception:
            pass
    try:
        return lhtml.fromstring(text)
    except Exception as exc:
        raise RuleError(f"响应无法解析为 HTML/JSON：{exc}") from exc


def _node_text(node: Any, attr: str | None) -> str:
    attr = (attr or "text").lower()
    if isinstance(node, str): return node.strip()
    if isinstance(node, (int, float)): return str(node)
    if isinstance(node, (dict, list)): return json.dumps(node, ensure_ascii=False)
    if attr in ("text", "all"): return " ".join(t.strip() for t in node.itertext() if t.strip())
    if attr == "textnodes": return "\n".join(t.strip() for t in node.itertext() if t.strip())
    if attr == "owntext": return " ".join(p.strip() for p in [node.text or ""] + [c.tail or "" for c in node] if p.strip())
    if attr in ("html", "innerhtml", "outerhtml"): return etree.tostring(node, encoding="unicode", method="html").strip()
    value = node.get(attr)
    if value is None and attr == "href": value = node.get("data-href") or node.get("data-url")
    if value is None and attr == "src": value = node.get("data-src") or node.get("data-original")
    return (value or "").strip()


def _apply_replaces(value: str, tails: list[str]) -> str:
    if not value or not tails: return value
    if len(tails) == 1: return re.sub(tails[0], "", value)
    for i in range(0, len(tails) - 1, 2):
        try: value = re.sub(tails[i], tails[i + 1].replace("$", "\\"), value)
        except Exception: pass
    return value


def _default_tokens(rule: str) -> list[str]: return [t for t in rule.split("@") if t != ""]


def _step_default(nodes: list, token: str) -> list:
    low = token.lower()
    if low == "children":
        out = []
        for node in nodes: out.extend(list(node))
        return out
    kind, _, rest = token.partition(".")
    index: int | None = None
    name = rest
    parts = rest.rsplit(".", 1)
    if len(parts) == 2 and re.fullmatch(r"-?\d+", parts[1]): name, index = parts[0], int(parts[1])
    css = {"class": f".{name}", "id": f"#{name}", "tag": name, "text": f":contains('{name}')" if name else None}.get(kind.lower(), token)
    if not css: return nodes
    out: list = []
    for node in nodes:
        try: out.extend(node.cssselect(css))
        except Exception: continue
    if index is not None and out:
        try: out = [out[index]]
        except IndexError: out = []
    return out


def _select_nodes(ctx: Any, core: str) -> list:
    core = core.strip()
    if not core: return []
    if core.startswith("json:") or core.startswith("$."):
        expr = core[5:] if core.startswith("json:") else core
        if jsonpath_parse is None: raise RuleError("缺少 jsonpath-ng，无法解析 JSON 规则")
        if not isinstance(ctx, (dict, list)): raise RuleError("当前响应不是 JSON，无法使用 json 规则")
        return [m.value for m in _jsonpath_compiled(expr).find(ctx)]
    if isinstance(ctx, (dict, list)): raise RuleError("当前响应是 JSON，请使用 json:$.xxx 规则")
    if core.startswith(("xpath:", "//", "./")):
        expr = core[6:] if core.startswith("xpath:") else core
        try: return list(ctx.xpath(expr))
        except Exception as exc: raise RuleError(f"XPath 无效：{expr} ({exc})") from exc
    if core.startswith("regex:"):
        raw = etree.tostring(ctx, encoding="unicode", method="html")
        return [m.group(1) if m.groups() else m.group(0) for m in re.finditer(core[6:], raw, re.S)]
    if core.startswith("css:"):
        try: return list(ctx.cssselect(core[4:].strip()))
        except Exception as exc: raise RuleError(f"CSS 无效：{core[4:].strip()} ({exc})") from exc
    nodes = [ctx]
    for token in _default_tokens(core):
        if token.lower() in TEXT_ATTRS: break
        nodes = _step_default(nodes, token)
        if not nodes: break
    return nodes


def _split_attr(core: str) -> tuple[str, str | None]:
    if core.startswith(("xpath:", "//", "./", "json:", "$. ", "regex:")): return core, None
    head, sep, tail = core.rpartition("@")
    if not sep: return core, None
    tail_l = tail.strip().lower()
    if tail_l in TEXT_ATTRS or re.fullmatch(r"[A-Za-z_:][\w:.\-]*", tail.strip()):
        if "." in tail and tail_l not in TEXT_ATTRS and not tail.startswith("data-"): return core, None
        return head, tail.strip()
    return core, None


def get_list(ctx: Any, rule: str | None) -> list:
    if not rule: return []
    for alt in str(rule).split("||"):
        core, _tails = _split_core_tails(alt)
        if not core: continue
        try: nodes = _select_nodes(ctx, core)
        except RuleError: continue
        if nodes: return nodes
    return []


def _split_core_tails(rule: str) -> tuple[str, list[str]]:
    parts = str(rule).split("##")
    return parts[0].strip(), [p for p in parts[1:]]


def get_string(ctx: Any, rule: str | None, base_url: str = "", join: str = " ") -> str:
    if rule is None or str(rule).strip() == "": return ""
    rule = str(rule)
    if any(marker in rule for marker in JS_MARKERS): raise UnsupportedRule("规则内含 JS，本引擎不支持")
    for alt in rule.split("||"):
        core, tails = _split_core_tails(alt)
        if not core: continue
        if core.strip().lower().startswith("url:"):
            value = _apply_replaces(base_url or "", tails).strip()
            if value: return value
            continue
        core, attr = _split_attr(core)
        try: nodes = _select_nodes(ctx, core)
        except RuleError: continue
        values = [_node_text(n, attr) for n in nodes]
        values = [v for v in values if v]
        if not values: continue
        value = join.join(values) if len(values) > 1 else values[0]
        value = _apply_replaces(value, tails).strip()
        if value:
            if attr in ("href", "src") or (base_url and re.match(r"^(?!https?://)(/|\.{1,2}/|[\w\-./]+\.\w+)", value) and attr in ("href", "src")):
                value = urllib.parse.urljoin(base_url, value)
            return value
    return ""


def absolute(url: str, base_url: str) -> str:
    if not url:
        return ""
    # Some sources insert whitespace into relative URLs; remove it before joining.
    value = re.sub(r"\s+", "", str(url))
    if value.startswith(("http://", "https://")):
        return value
    return urllib.parse.urljoin(base_url, value)
