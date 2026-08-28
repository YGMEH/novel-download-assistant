// 小说聚合后端（Netlify Functions v2，零依赖）
// 聚合四路：番茄聚合(fq.taijiwang.top) + 幻梦轻小说(huanmengacg.com)
//        + 无限小说网(wuxianbook.com) + 丁丁精选(曦灵系，猫眼同库备源)
// 仅做接口转发与格式统一：搜索 / 详情 / 目录 / 正文
// 说明：个人学习用途，不对任何上游内容负责。

import { wuxianSearch, wuxianDetail, wuxianToc, wuxianContent, xilingSearch, xilingDetail, xilingToc, xilingContent } from './sources_extra.mjs';
import { zonghengSearch, zonghengDetail, zonghengToc, zonghengContent, aixiaSearch, aixiaDetail, aixiaToc, aixiaContent, shaonianSearch, shaonianDetail, shaonianToc, shaonianContent } from './sources_more.mjs';

const UA = 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36';
const UPSTREAM_TIMEOUT_MS = 12000;
const CACHE_TTL_S = 300;

// ---------- 基础工具 ----------
function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'access-control-allow-origin': '*',
      'access-control-allow-headers': '*',
      'cache-control': `public, max-age=${CACHE_TTL_S}`,
    },
  });
}

function errorJson(msg, status = 502) {
  return json({ ok: false, error: msg }, status);
}

async function fetchUpstream(url, opts = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), UPSTREAM_TIMEOUT_MS);
  try {
    const r = await fetch(url, {
      ...opts,
      signal: ctrl.signal,
      headers: { 'user-agent': UA, ...(opts.headers || {}) },
    });
    if (!r.ok) throw new Error(`upstream ${r.status}`);
    return r;
  } finally {
    clearTimeout(timer);
  }
}

// 幻梦正文里夹的广告（推广文字/链接/分隔线），先按行过滤再剥标签
function cleanHuanmengContent(html) {
  const AD_PATTERNS = [
    /aifun\.ltd/i,
    /t\.me\//i,
    /huanmengnovel/i,
    /AI风月/,
    /幻梦\s*APP/,
    /更多轻小说阅读/,
    /角色扮演与美少女聊天/,
  ];
  const text = html
    .replace(/<a[^>]*>[\s\S]*?<\/a>/gi, '')
    .replace(/<br\s*\/?\s*>/gi, '\n')
    .replace(/<\/?(p|div|span|img)[^>]*>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(new RegExp('&' + 'nbsp;', 'g'), ' ')
    .replace(new RegExp('&' + 'amp;', 'g'), '&')
    .replace(new RegExp('&' + 'lt;', 'g'), '<')
    .replace(new RegExp('&' + 'gt;', 'g'), '>')
    .replace(new RegExp('&' + 'quot;', 'g'), '"');
  const lines = text.split('\n').map(l => l.trim()).filter(l => {
    if (!l) return true; // 保留空行，最后统一压缩
    if (/^[=\-*~·—―\s]+$/.test(l)) return false;   // 纯分隔线
    if (AD_PATTERNS.some(re => re.test(l))) return false; // 推广行
    return true;
  });
  return lines.join('\n').replace(/\n{3,}/g, '\n\n').trim();
}

// ---------- 各源实现 ----------
// 统一返回结构：
// search  -> { ok, sources:[{source:'fanqie'|'huanmeng', ok, books:[{source,id,name,author,intro,cover,category}] , error? }] }
// detail  -> { ok, book:{source,id,name,author,intro,cover,category} }
// toc     -> { ok, chapters:[{cid,title}] }
// content -> { ok, content:'...' }

async function fanqieSearch(kw) {
  const r = await fetchUpstream(`https://fq.taijiwang.top/api/search?key=${encodeURIComponent(kw)}`);
  const j = await r.json();
  if (j.code !== 200) throw new Error(j.message || '上游错误');
  const blocks = j?.data?.search_tabs?.[0]?.data || [];
  const books = [];
  for (const b of blocks) {
    for (const it of (b.book_data || [])) {
      if (it && it.book_id && it.book_name) {
        books.push({
          source: 'fanqie',
          id: String(it.book_id),
          name: it.book_name,
          author: it.author || '佚名',
          intro: it.abstract || '',
          cover: it.thumb_url || '',
          category: it.category || '',
        });
      }
    }
  }
  return books;
}

async function fanqieDetail(id) {
  const r = await fetchUpstream(`https://fq.taijiwang.top/api/detail?book_id=${encodeURIComponent(id)}`);
  const j = await r.json();
  if (j.code !== 200) throw new Error(j.message || '上游错误');
  const d = j?.data?.data || {};
  return {
    source: 'fanqie',
    id: String(id),
    name: d.book_name || '未知书名',
    author: d.author || '佚名',
    intro: d.abstract || '',
    cover: d.thumb_url || '',
    category: d.category || '',
  };
}

async function fanqieToc(id) {
  const r = await fetchUpstream(`https://fq.taijiwang.top/api/directory?book_id=${encodeURIComponent(id)}`);
  const j = await r.json();
  if (j.code !== 200) throw new Error(j.message || '上游错误');
  return (j?.data?.lists || []).map(c => ({ cid: String(c.item_id), title: c.title }));
}

async function fanqieContent(cid) {
  const r = await fetchUpstream(`https://fq.taijiwang.top/api/content?tab=%E5%B0%8F%E8%AF%B4&item_id=${encodeURIComponent(cid)}`);
  const j = await r.json();
  if (j.code !== 200) throw new Error(j.message || '上游错误');
  return j?.data?.content || '';
}

async function huanmengSearch(kw) {
  const url = `https://www.huanmengacg.com/index.php/bookapi/search?password=chiyu666&key=${encodeURIComponent(kw)}&page=1&size=20`;
  const r = await fetchUpstream(url);
  const j = await r.json();
  const list = j?.data?.list || [];
  return list.map(it => ({
    source: 'huanmeng',
    id: String(it.id),
    name: it.name || '未知书名',
    author: it.author || '佚名',
    intro: it.intro || '',
    cover: it.pic || '',
    category: it.kind || '',
  }));
}

async function huanmengDetail(id) {
  const r = await fetchUpstream(`https://www.huanmengacg.com/index.php/bookapi/detail?password=chiyu666&id=${encodeURIComponent(id)}`);
  const j = await r.json();
  const d = j?.data || {};
  return {
    source: 'huanmeng',
    id: String(id),
    name: d.name || '未知书名',
    author: d.author || '佚名',
    intro: d.intro || '',
    cover: d.pic || '',
    category: d.kind || '',
  };
}

async function huanmengToc(id) {
  const r = await fetchUpstream(`https://www.huanmengacg.com/index.php/bookapi/chapters?password=chiyu666&id=${encodeURIComponent(id)}&size=5000`);
  const j = await r.json();
  return (j?.data?.list || []).map(c => ({ cid: String(c.id), title: c.name }));
}

async function huanmengContent(bid, cid) {
  const r = await fetchUpstream(`https://www.huanmengacg.com/index.php/bookapi/content?password=chiyu666&bid=${encodeURIComponent(bid)}&cid=${encodeURIComponent(cid)}`);
  const j = await r.json();
  return cleanHuanmengContent(j?.data?.content || '');
}

// ---------- 路由处理 ----------
async function handle(action, params) {
  switch (action) {
    case 'search': {
      const kw = (params.get('key') || '').trim();
      if (!kw) return errorJson('缺少搜索关键词', 400);
      const sources = [
        { name: 'fanqie', fn: fanqieSearch },
        { name: 'huanmeng', fn: huanmengSearch },
        { name: 'wuxian', fn: wuxianSearch },
        { name: 'dingding', fn: xilingSearch },
        { name: 'zongheng', fn: zonghengSearch },
        { name: 'aixia', fn: aixiaSearch },
        { name: 'shaonian', fn: shaonianSearch },
      ];
      const results = await Promise.allSettled(sources.map(s => s.fn(kw)));
      return json({
        ok: true,
        sources: sources.map((s, i) => {
          const v = results[i];
          if (v.status === 'fulfilled') return { source: s.name, ok: true, books: v.value };
          return { source: s.name, ok: false, books: [], error: String(v.reason?.message || v.reason) };
        }),
      });
    }

    case 'detail': {
      const src = params.get('source');
      const id = (params.get('id') || '').trim();
      if (!src || !id) return errorJson('缺少 source 或 id', 400);
      const book = src === 'fanqie' ? await fanqieDetail(id)
                 : src === 'huanmeng' ? await huanmengDetail(id)
                 : src === 'wuxian' ? await wuxianDetail(id)
                 : src === 'dingding' ? await xilingDetail(id)
                 : src === 'zongheng' ? await zonghengDetail(id)
                 : src === 'aixia' ? await aixiaDetail(id)
                 : src === 'shaonian' ? await shaonianDetail(id)
                 : null;
      if (!book) return errorJson('未知来源', 400);
      return json({ ok: true, book });
    }

    case 'toc': {
      const src = params.get('source');
      const id = (params.get('id') || '').trim();
      if (!src || !id) return errorJson('缺少 source 或 id', 400);
      const chapters = src === 'fanqie' ? await fanqieToc(id)
                     : src === 'huanmeng' ? await huanmengToc(id)
                     : src === 'wuxian' ? await wuxianToc(id)
                     : src === 'dingding' ? await xilingToc(id)
                     : src === 'zongheng' ? await zonghengToc(id)
                     : src === 'aixia' ? await aixiaToc(id)
                     : src === 'shaonian' ? await shaonianToc(id)
                     : null;
      if (chapters === null) return errorJson('未知来源', 400);
      return json({ ok: true, chapters });
    }

    case 'content': {
      const src = params.get('source');
      const bid = (params.get('bid') || '').trim();
      const cid = (params.get('cid') || '').trim();
      if (!src || !cid) return errorJson('缺少 source 或 cid', 400);
      let content = '';
      if (src === 'fanqie') content = await fanqieContent(cid);
      else if (src === 'huanmeng') content = bid ? await huanmengContent(bid, cid) : '';
      else if (src === 'wuxian') content = bid ? await wuxianContent(bid, cid) : '';
      else if (src === 'zongheng') content = bid ? await zonghengContent(bid, cid) : '';
      else if (src === 'aixia') content = bid ? await aixiaContent(bid, cid) : '';
      else if (src === 'shaonian') content = bid ? await shaonianContent(bid, cid) : '';
      else if (src === 'dingding') {
        if (!bid) return errorJson('缺少 bid', 400);
        content = await xilingContent(bid, cid, (params.get('w') || '').trim(), (params.get('path') || '').trim());
      }
      else return errorJson('未知来源', 400);
      if (!content) return errorJson('正文为空', 404);
      return json({ ok: true, content });
    }

    case 'ping':
      return json({ ok: true, time: Date.now(), sources: ['fanqie', 'huanmeng', 'wuxian', 'dingding', 'zongheng', 'aixia', 'shaonian'] });

    default:
      return errorJson('未知 action，可用：search / detail / toc / content / ping', 400);
  }
}

export default async (req) => {
  const url = new URL(req.url);
  if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': 'GET,OPTIONS' } });
  if (req.method !== 'GET') return errorJson('仅支持 GET', 405);
  try {
    return await handle(url.searchParams.get('action'), url.searchParams);
  } catch (e) {
    return errorJson(String(e?.message || e));
  }
};

export const config = { path: '/api/aggregator' };
