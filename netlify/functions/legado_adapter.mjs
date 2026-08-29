// Legado 书源适配器（安全子集）
// 支持：URL 模板、GET/POST、请求头、常见 CSS 选择器、属性/文本、四链路。
// 明确不执行：@js/java、WebView、登录、验证码、加密签名、任意脚本。

import sourceData from '../../sources/builtin/reading_sources_safe.json' with { type: 'json' };

const UA = 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/124 Mobile Safari/537.36';
const TIMEOUT = 8000;
const SOURCES = Array.isArray(sourceData) ? sourceData : [];

const blocked = (x) => {
  const s = JSON.stringify(x || '');
  return /@js:|<js>|\{\{java\.|webView|Authorization|Bearer |PHPSESSID|jieqiUser/i.test(s);
};
const sourceId = (s) => `${s.bookSourceName || 'source'}|${s.bookSourceUrl || ''}`;
const clean = (s) => String(s ?? '').replace(/<script[\s\S]*?<\/script>/gi, '').replace(/<style[\s\S]*?<\/style>/gi, '').replace(/<[^>]+>/g, '').replace(/&nbsp;/gi, ' ').replace(/&amp;/gi, '&').replace(/&lt;/gi, '<').replace(/&gt;/gi, '>').replace(/&#39;/g, "'").replace(/\s+/g, ' ').trim();
const abs = (u, base) => { try { return new URL(String(u || ''), base).href; } catch (_) { return ''; } };
function vars(spec, key = '', page = 1) {
  return String(spec || '')
    .replace(/\{\{key\}\}/g, encodeURIComponent(key))
    .replace(/\{\{page\}\}/g, String(page))
    .replace(/\{\{\s*page\s*([+-])\s*(\d+)\s*\}\}/g, (_, op, n) => String(page + (op === '+' ? 1 : -1) * Number(n)))
    .replace(/searchKey/g, encodeURIComponent(key)).replace(/searchPage/g, String(page));
}
function splitRule(rule) { return String(rule || '').split('##')[0].split('||')[0].trim(); }
function legadoTokenCss(token) {
  const t = String(token || '').trim();
  if (!t || /^(text|all|owntext|html|innerhtml|outerhtml|href|src|children)$/i.test(t)) return '';
  const m = t.match(/^class\.([\w-]+)/i);
  if (m) return `.${m[1]}`;
  const i = t.match(/^id\.([\w-]+)/i);
  if (i) return `#${i[1]}`;
  const g = t.match(/^tag\.([\w-]+)/i);
  if (g) return g[1];
  // Legado 的 tag.span[0:1] 是切片表达式；这里保留 span 选择器。
  const bare = t.match(/^([\w-]+)/);
  return bare ? bare[1] : t;
}
function normalizeSelector(r) {
  if (r.startsWith('css:')) return r.slice(4).trim();
  if (r.includes('@')) return r.split('@').map(legadoTokenCss).filter(Boolean).join(' ');
  return legadoTokenCss(r);
}
function parseRule(rule) {
  let r = splitRule(rule); let attr = 'text';
  const m = r.match(/^(.*)@([\w:-]+)$/);
  if (m) { r = m[1]; attr = m[2].toLowerCase(); }
  // 独立的末尾属性规则，如 ruleToc.chapterName = "text"。
  if (/^(text|all|owntext|html|innerhtml|outerhtml|href|src)$/i.test(r.trim())) {
    attr = r.trim().toLowerCase(); r = '*';
  }
  if (/^(xpath:|json:|\$\.|regex:|@js:|<js>)/i.test(r)) throw new Error('该规则需要 XPath/JSON/JS，当前在线适配器不支持');
  return { selector: normalizeSelector(r), attr };
}
function escRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
function elements(html, selector) {
  // 安全的常见 CSS 子集：tag、.class、#id、tag.class、后代选择器、:first-child。
  const parts = selector.replace(/:first-child/g, '').trim().split(/\s+/).filter(Boolean);
  let pool = [String(html || '')];
  for (const part of parts) {
    const tag = (part === '*' || !part.match(/[\w-]/)) ? '[\\w-]+' : ((part.match(/^([\w-]*)/) || [,''])[1] || '[\\w-]+');
    const id = (part.match(/#([\w-]+)/) || [,''])[1];
    const cls = (part.match(/\.([\w-]+)/g) || []).map(x => x.slice(1));
    const open = new RegExp(`<(${tag})(?:\\s[^>]*?)?>([\\s\\S]*?)<\\/\\1>`, 'gi');
    const next = [];
    for (const parent of pool) {
      let m;
      while ((m = open.exec(parent))) {
        const full = m[0], attrs = full.slice(0, full.indexOf('>') + 1);
        if (id && !new RegExp(`\\bid=["']${escRe(id)}["']`, 'i').test(attrs)) continue;
        if (cls.length && !cls.every(c => new RegExp(`\\bclass=["'][^"']*\\b${escRe(c)}\\b`, 'i').test(attrs))) continue;
        next.push(full);
      }
    }
    pool = next;
  }
  return pool;
}
function pick(html, rule, base = '') {
  if (!rule) return '';
  const { selector, attr } = parseRule(rule);
  if (selector === 'url:') return base;
  const found = elements(html, selector)[0] || '';
  if (!found) return '';
  if (attr === 'text' || attr === 'all' || attr === 'owntext' || attr === 'html') return attr === 'html' ? found : clean(found);
  const m = found.match(new RegExp(`\\b${escRe(attr)}=["']([^"']*)["']`, 'i'));
  return m ? (attr === 'href' || attr === 'src' ? abs(m[1], base) : m[1]) : '';
}
function list(html, rule) { const { selector } = parseRule(rule); return elements(html, selector); }
function rule(src, group, key) { return src?.[group]?.[key] || ''; }
function parseUrlSpec(spec, key = '', page = 1) {
  const raw = String(spec || '').trim();
  const match = raw.match(/,\s*(\{[\s\S]*\})\s*$/);
  const pos = match ? match.index : -1;
  let urlPart = pos >= 0 ? raw.slice(0, pos).trim() : raw;
  let options = {};
  if (pos >= 0) {
    const optionText = match[1];
    try { options = JSON.parse(optionText); }
    catch (_) {
      // 部分老书源使用单引号对象；仅做受限键值转换，不执行任意 JS。
      try {
        const normalized = optionText.replace(/([{,]\s*)'([^']+)'\s*:/g, '$1"$2":').replace(/:\s*'([^']*)'/g, ':"$1"');
        options = JSON.parse(normalized);
      } catch (_) { throw new Error('URL 规则后的 JSON 选项无效'); }
    }
  }
  const url = vars(urlPart, key, page);
  let body = options.body;
  if (body && typeof body === 'object') body = JSON.stringify(body);
  if (typeof body === 'string') body = vars(body, key, page);
  let headers = options.headers || {};
  if (typeof headers === 'string') {
    try { headers = JSON.parse(headers); } catch (_) { headers = {}; }
  }
  return { url, method: String(options.method || 'GET').toUpperCase(), body: body || undefined, headers, charset: options.charset || '' };
}
async function fetchText(spec, src, key = '', page = 1, referer = '') {
  if (!spec) throw new Error('URL 规则为空');
  if (blocked(spec) || blocked(src)) throw new Error('书源含脚本、登录凭据或特殊运行时，已阻止');
  const parsed = parseUrlSpec(spec, key, page);
  const url = parsed.url.startsWith('http') ? parsed.url : `${src.bookSourceUrl}/${parsed.url.replace(/^\//, '')}`;
  const headers = { 'user-agent': UA, ...(src.header && typeof src.header === 'object' ? src.header : {}), ...(parsed.headers || {}) };
  if (referer) headers.referer = referer;
  const init = { method: parsed.method, headers };
  if (parsed.body && parsed.method !== 'GET' && parsed.method !== 'HEAD') init.body = parsed.body;
  const ctrl = new AbortController(); const timer = setTimeout(() => ctrl.abort(), TIMEOUT);
  try {
    const r = await fetch(url, { ...init, signal: ctrl.signal });
    if (!r.ok) throw new Error(`上游 HTTP ${r.status}`);
    const bytes = new Uint8Array(await r.arrayBuffer());
    let text;
    if (parsed.charset) {
      try { text = new TextDecoder(parsed.charset).decode(bytes); }
      catch (_) { text = new TextDecoder().decode(bytes); }
    } else text = new TextDecoder().decode(bytes);
    return { text, url: r.url || url };
  } finally { clearTimeout(timer); }
}
function sourceById(id) { return SOURCES.find(s => sourceId(s) === id || s.bookSourceName === id); }
export function listLegadoSources() { return SOURCES.map(s => ({ id: sourceId(s), name: s.bookSourceName, group: s.bookSourceGroup || '', url: s.bookSourceUrl })); }
// 测试用导出：不暴露凭据，仅返回规范化后的请求参数。
export function inspectUrlSpec(spec, key = '', page = 1) { return parseUrlSpec(spec, key, page); }
export async function legadoSearch(id, key) {
  const s = sourceById(id); if (!s) throw new Error('书源不存在');
  const r = await fetchText(s.searchUrl, s, key); const nodes = list(r.text, rule(s, 'ruleSearch', 'bookList'));
  return nodes.slice(0, 10).map(n => ({ source: sourceId(s), source_name: s.bookSourceName, name: pick(n, rule(s, 'ruleSearch', 'name'), r.url), author: pick(n, rule(s, 'ruleSearch', 'author'), r.url), intro: pick(n, rule(s, 'ruleSearch', 'intro'), r.url), cover: pick(n, rule(s, 'ruleSearch', 'coverUrl'), r.url), book_url: pick(n, rule(s, 'ruleSearch', 'bookUrl'), r.url) })).filter(x => x.name && x.book_url);
}
export async function legadoDetail(id, bookUrl) {
  const s = sourceById(id); if (!s) throw new Error('书源不存在'); const r = await fetchText(bookUrl, s); const g = 'ruleBookInfo';
  return { source: sourceId(s), source_name: s.bookSourceName, name: pick(r.text, rule(s,g,'name'),r.url), author: pick(r.text,rule(s,g,'author'),r.url), intro: pick(r.text,rule(s,g,'intro'),r.url), cover: pick(r.text,rule(s,g,'coverUrl'),r.url), toc_url: pick(r.text,rule(s,g,'tocUrl'),r.url) || r.url };
}
export async function legadoToc(id, tocUrl) {
  const s = sourceById(id); if (!s) throw new Error('书源不存在'); const r = await fetchText(tocUrl, s); const nodes = list(r.text, rule(s,'ruleToc','chapterList'));
  return nodes.map(n => ({ title: pick(n,rule(s,'ruleToc','chapterName'),r.url), url: pick(n,rule(s,'ruleToc','chapterUrl'),r.url) })).filter(x => x.title && x.url);
}
export async function legadoContent(id, chapterUrl) {
  const s = sourceById(id); if (!s) throw new Error('书源不存在'); const r = await fetchText(chapterUrl, s); const body = pick(r.text,rule(s,'ruleContent','content'),r.url); if (!body) throw new Error('正文为空'); return clean(body);
}
