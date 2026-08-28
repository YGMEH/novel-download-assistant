// 扩展源模块：无限小说网（HTML 解析） + 曦灵系丁丁/猫眼（AES + 固定头，同库互备）
// 被 aggregator.mjs import。个人学习用途，仅做接口转发与格式统一。

import crypto from 'node:crypto';

const UA = 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36';
const TMO = 12000;

// JWT 从环境变量读取（Netlify 环境变量 DD_JWT / MJ_JWT，本地测试 export 注入）
const DD_JWT = process.env.DD_JWT || '';
const MJ_JWT = process.env.MJ_JWT || '';

const XL = {
  dd: {
    base: 'http://api.xingliangglobal.com',
    headers: {
      'client-device': '429497b3cc84a9f1333c793cc6e9110a',
      'client-brand': 'XIAOMI',
      'client-version': '1.1.0',
      'client-channel': 'android',
      'client-name': 'app.maoyankanshu.novel',
      'alias-name': 'dingdianapp',
      'client-source': 'android',
      'user-agent': 'okhttp/4.9.2',
      'Authorization': 'bearer' + DD_JWT,
    },
    aes: '4395daa50ad6baf7',
  },
  mj: {
    base: 'http://api.jmlldsc.com',
    headers: {
      'client-device': '0cdeb38dd0f2a381b06c0a02926ee317',
      'client-brand': 'vivo',
      'client-version': '2.3.0',
      'client-name': 'app.maoyankanshu.novel',
      'client-source': 'android',
      'user-agent': 'okhttp/4.9.2',
      'Authorization': 'bearer' + MJ_JWT,
    },
    aes: 'f041c49714d39908',
  },
};

function aesDec(b64, key, iv = '0123456789abcdef') {
  const d = crypto.createDecipheriv('aes-128-cbc', Buffer.from(key), Buffer.from(iv));
  return Buffer.concat([d.update(Buffer.from(b64, 'base64')), d.final()]).toString('utf8');
}

async function f(url, opts = {}, ms = TMO) {
  const c = new AbortController();
  const t = setTimeout(() => c.abort(), ms);
  try {
    const r = await fetch(url, { ...opts, signal: c.signal });
    if (!r.ok) throw new Error(`upstream ${r.status}`);
    return r;
  } finally { clearTimeout(t); }
}

async function pool(jobs, size = 20) {
  const out = [];
  for (let i = 0; i < jobs.length; i += size) {
    out.push(...await Promise.allSettled(jobs.slice(i, i + size).map(fn => fn())));
  }
  return out;
}

const unesc = (s) => String(s || '')
  .split('&' + 'nbsp;').join(' ')
  .split('&' + 'lt;').join('<')
  .split('&' + 'gt;').join('>')
  .split('&' + 'quot;').join('"')
  .split('&#39;').join("'")
  .split('&' + 'amp;').join('&')
  .replace(/&#x([0-9a-f]+);/gi, (_, h) => String.fromCodePoint(parseInt(h, 16)))
  .replace(/&#(\d+);/g, (_, d) => String.fromCodePoint(Number(d)));

const stripTags = (s) => unesc(String(s || '').replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]+>/g, '')).trim();

// ---------- 无限小说网（书籍 id = 详情页 slug 路径） ----------
const WX = 'https://wuxianbook.com';

async function wxGet(path, opts = {}) {
  const r = await f(`${WX}${path}`, {
    ...opts,
    headers: { 'user-agent': UA, referer: WX + '/', ...(opts.headers || {}) },
  });
  return r.text();
}

export async function wuxianSearch(kw) {
  const html = await wxGet('/e/search/index.php', {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: `tbname=bookname&show=title,writer&tempid=1&keyboard=${encodeURIComponent(kw)}`,
    redirect: 'follow',
  });
  if (html.includes('没有搜索到相关的内容')) return [];
  const out = [];
  const rx = /<li class="search-wrap-first">\s*<a href="([^"]+)"[\s\S]*?<span class="title">([\s\S]*?)<\/span>[\s\S]*?<h5 class="book-author">作者:\s*([^<]*)<\/h5>/g;
  let m;
  while ((m = rx.exec(html))) {
    let id = m[1];
    try { if (/^https?:\/\//.test(id)) id = new URL(id).pathname; } catch {}
    if (!id.startsWith('/')) id = '/' + id;
    out.push({ source: 'wuxian', id, name: stripTags(m[2]), author: stripTags(m[3]) || '佚名', intro: '', cover: '', category: '' });
  }
  return out;
}

export async function wuxianDetail(urlPath) {
  let path = urlPath;
  try { if (/^https?:\/\//.test(path)) path = new URL(path).pathname; } catch {}
  if (!path.startsWith('/')) path = '/' + path;
  const html = await wxGet(path);
  const bid = (html.match(/data-bookid="(\d+)"/) || [])[1];
  const name = stripTags((html.match(/<h2 class="detail-book-title">([\s\S]*?)<\//) || [])[1] || '');
  const author = stripTags((html.match(/detail-book-author[\s\S]*?<span><a[^>]*>([^<]*)</) || [])[1] || '');
  const intro = stripTags((html.match(/name="description" content="([^"]*)"/) || [])[1] || '')
    .replace(/^[\s\S]*?内容简介：/, '').replace(/txt下载[\s\S]*$/, '');
  let cover = (html.match(/detail-header-img"><img src="([^"]+)"/) || [])[1] || '';
  if (cover.startsWith('//')) cover = 'https:' + cover;
  if (!bid || !name) throw new Error('详情解析失败');
  return { source: 'wuxian', id: path, bookId: bid, name, author: author || '佚名', intro, cover, category: '' };
}

async function wxBookId(idOrPath) {
  if (/^\d+$/.test(idOrPath)) return idOrPath;
  const html = await wxGet(idOrPath);
  const bid = (html.match(/data-bookid="(\d+)"/) || [])[1];
  if (!bid) throw new Error('bookid 解析失败');
  return bid;
}

export async function wuxianToc(id) {
  const bid = await wxBookId(id);
  const first = JSON.parse(await wxGet(`/e/extend/bookpage/pages.php?id=${bid}&pageNum=0&dz=asc`));
  const totalPage = Math.min(Number(first.totalPage) || 1, 300);
  const list = [...(first.list || [])];
  if (totalPage > 1) {
    const jobs = Array.from({ length: totalPage - 1 }, (_, i) => () =>
      wxGet(`/e/extend/bookpage/pages.php?id=${bid}&pageNum=${i + 1}&dz=asc`).then(x => JSON.parse(x)));
    const rs = await pool(jobs, 20);
    for (const r of rs) if (r.status === 'fulfilled' && r.value && r.value.list) list.push(...r.value.list);
  }
  return list.map(c => ({ cid: String(c.id), title: c.title }));
}

export async function wuxianContent(path, cid) {
  if (!path) throw new Error('缺少书籍路径');
  if (!path.startsWith('/')) path = '/' + path;
  const html = await wxGet(`${path}${cid}.html`);
  const i = html.indexOf('id="text">');
  if (i < 0) throw new Error('正文解析失败');
  const seg = html.slice(i + 10);
  const end = seg.indexOf('</div>');
  const content = stripTags(end >= 0 ? seg.slice(0, end) : seg).replace(/\n{3,}/g, '\n\n').replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '').trim();
  if (!content) throw new Error('正文为空');
  return content;
}

// ---------- 曦灵系（丁丁主 / 猫眼备，同书库同 novelId） ----------
async function xlFetch(which, path) {
  const s = XL[which];
  const j = await (await f(`${s.base}${path}`, { headers: s.headers })).json();
  if (j.code !== 200 && j.code !== 4004) throw new Error(j.msg || `code ${j.code}`);
  return j;
}

export async function xilingSearch(kw) {
  let j;
  try { j = await xlFetch('dd', `/search?keyword=${encodeURIComponent(kw)}`); }
  catch { j = await xlFetch('mj', `/search?keyword=${encodeURIComponent(kw)}&page=1`); }
  return (j && j.data || []).map(b => ({
    source: 'dingding',
    id: String(b.novelId),
    name: b.novelName || '未知书名',
    author: b.authorName || '佚名',
    intro: b.summary || '',
    cover: b.cover || '',
    category: (b.categoryNames || []).map(c => (c && c.className) || c).join(',') || '',
  }));
}

export async function xilingDetail(id) {
  let j;
  try { j = await xlFetch('dd', `/novel/${encodeURIComponent(id)}?isSearch=0`); }
  catch { j = await xlFetch('mj', `/novel/${encodeURIComponent(id)}?isSearch=0`); }
  const d = j && j.data || {};
  return {
    source: 'dingding',
    id: String(id),
    name: d.novelName || '未知书名',
    author: d.authorName || '佚名',
    intro: d.summary || '',
    cover: d.cover || '',
    category: (d.categoryNames || []).map(c => (c && c.className) || c).join(',') || (String(d.status) === '1' ? '完结' : '连载'),
  };
}

// 目录带加密 path 与源标记（正文请求透传可免重拉目录，整本下载关键）
export async function xilingToc(id) {
  let j, which = 'dd';
  try { j = await xlFetch('dd', `/novel/${encodeURIComponent(id)}/chapters`); }
  catch { j = await xlFetch('mj', `/novel/${encodeURIComponent(id)}/chapters`); which = 'mj'; }
  return ((j && j.data && j.data.list) || []).map(c => ({
    cid: String(c.chapterId), title: c.chapterName, path: c.path || '', w: which,
  }));
}

export async function xilingContent(id, cid, which, pathEnc) {
  let path = pathEnc, w = which;
  if (!path || !w) {
    const toc = await xilingToc(id);
    const hit = toc.find(c => c.cid === String(cid));
    if (!hit || !hit.path) throw new Error('章节不在目录中');
    path = hit.path; w = hit.w;
  }
  const s = XL[w] || XL.dd;
  const url = aesDec(path, s.aes);
  const j = await (await f(url, { headers: s.headers })).json();
  const content = String((j && j.content) || '').trim();
  if (!content) throw new Error('正文为空');
  return content;
}
