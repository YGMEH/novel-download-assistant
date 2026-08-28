// 扩展源模块 B：纵横中文网 | 爱下小说 | 少年梦阅读
// 均为公开书源仓库样本的接口复刻，个人学习用途。

import crypto from 'node:crypto';

const UA_PC = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36';
const UA_DALVIK = 'Dalvik/2.1.0 (Linux; U; Android 10; MIX Build/PKQ1.190118.001)';
const UA_OK = 'okhttp/4.9.1';
const TMO = 12000;

async function f(url, opts = {}, ms = TMO) {
  const c = new AbortController();
  const t = setTimeout(() => c.abort(), ms);
  try {
    const r = await fetch(url, { ...opts, signal: c.signal });
    if (!r.ok) throw new Error(`upstream ${r.status}`);
    return r;
  } finally { clearTimeout(t); }
}

const unesc = (s) => String(s || '')
  .split('&' + 'nbsp;').join(' ')
  .split('&' + 'lt;').join('<')
  .split('&' + 'gt;').join('>')
  .split('&' + 'quot;').join('"')
  .split('&#39;').join("'")
  .split('&' + 'amp;').join('&');

const clean = (s) => unesc(String(s || '').replace(/<[^>]+>/g, '')).replace(/\s+/g, ' ').trim();

// ---------- 纵横中文网 ----------
export async function zonghengSearch(kw) {
  const r = await f(`https://search.zongheng.com/search/book?keyword=${encodeURIComponent(kw)}&sort=null&pageNo=1&pageNum=20&isFromHuayu=0`, {
    headers: { 'user-agent': UA_PC },
  });
  const j = await r.json();
  const list = (j && j.data && j.data.datas && j.data.datas.list) || [];
  return list.map(b => ({
    source: 'zongheng',
    id: String(b.bookId),
    name: clean(b.name),
    author: b.authorName || '佚名',
    intro: clean(b.description || ''),
    cover: b.coverUrl ? `https://static.zongheng.com/upload${b.coverUrl}` : '',
    category: b.cateFineName || b.catePName || '',
  }));
}

export async function zonghengDetail(id) {
  const r = await f(`https://book.zongheng.com/book/${encodeURIComponent(id)}.html`, {
    headers: { 'user-agent': UA_PC },
  });
  const html = await r.text();
  const title = clean((html.match(/<title>([^<]*)</) || [])[1] || '');
  const m = title.match(/^(.*?)\(([^)]+)\)/);
  const name = m ? m[1] : title;
  const author = m ? m[2] : '';
  const category = (html.match(/og:novel:category" content="([^"]*)"/) || [])[1] || '';
  // 真简介内嵌在页面 JS 里（description:"..."\u003Cbr\u003E 转义）
  let intro = '';
  const im = html.match(/description:"((?:[^"\\]|\\.)*)"/);
  if (im) intro = im[1].replace(/\\u003Cbr\\u003E/gi, '\n').replace(/\\u003C\/?[\s\S]*?\\u003E/gi, '').replace(/\\n/g, '\n').trim();
  if (!intro) intro = clean((html.match(/og:novel:description" content="([^"]*)"/) || [])[1] || '');
  const cover = (html.match(/og:image" content="([^"]*)"/) || [])[1] || '';
  if (!name) throw new Error('详情解析失败');
  return { source: 'zongheng', id: String(id), name, author: author || '佚名', intro, cover, category };
}

export async function zonghengToc(id) {
  const r = await f('https://bookapi.zongheng.com/api/chapter/getChapterList', {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded', 'user-agent': UA_PC },
    body: `bookId=${encodeURIComponent(id)}`,
  });
  const j = await r.json();
  if (j.code !== 0) throw new Error(j.message || `code ${j.code}`);
  const out = [];
  for (const tome of ((j.result && j.result.chapterList) || [])) {
    for (const c of (tome.chapterViewList || [])) {
      out.push({ cid: String(c.chapterId), title: c.chapterName });
    }
  }
  return out;
}

export async function zonghengContent(bid, cid) {
  const r = await f(`https://read.zongheng.com/chapter/${encodeURIComponent(bid)}/${encodeURIComponent(cid)}.html`, {
    headers: { 'user-agent': UA_PC },
  });
  const html = await r.text();
  const i = html.indexOf('class="content"');
  if (i < 0) throw new Error('正文解析失败');
  const seg = html.slice(i);
  const end = seg.indexOf('</div>');
  const ps = (end > 0 ? seg.slice(0, end) : seg).match(/<p[^>]*>([\s\S]*?)<\/p>/g) || [];
  const text = ps.map(p => clean(p)).filter(Boolean).join('\n');
  if (!text) throw new Error('正文为空');
  return text;
}

// ---------- 爱下小说 ----------
const AX = 'https://apiv2hans.aixdzs.com';
const AX_SALT = '2c6689f91ee4d4e87d798397d47310ebbe1dad79ixdzs';

async function axPost(path, bodyObj, withSign = false) {
  const headers = {
    'content-type': 'application/json',
    'user-agent': UA_DALVIK,
  };
  if (withSign) {
    // 签名：SHA1(盐 + nonce + curtime + nonce)，与公开书源算法一致
    const abc = 'abcdefghijklmnopqrstuvwxyz0123456789';
    let nonce = '';
    for (let i = 0; i < 8; i++) nonce += abc[Math.floor(Math.random() * abc.length)];
    const curtime = String(Math.floor(Date.now() / 1000));
    const checksum = crypto.createHash('sha1').update(AX_SALT + nonce + curtime + nonce).digest('hex');
    headers.checkSumDTO = JSON.stringify({ appid: 'ixdzs', checksum, curtime, nonce });
  }
  const r = await f(`${AX}${path}`, { method: 'POST', headers, body: JSON.stringify(bodyObj) });
  return r.json();
}

export async function aixiaSearch(kw) {
  const j = await axPost('/search', { searchTerms: kw, pageSize: '20', pageNum: '1' });
  const hits = ((j.hits || {}).hits) || [];
  return hits.map(h => {
    const s = h._source || {};
    return {
      source: 'aixia',
      id: String(s.id || s._id || ''),
      name: s.name || '未知书名',
      author: s.author || '佚名',
      intro: s.shortIntro || '',
      cover: s.cover ? `https://img22.aixdzs.com/${s.cover}` : '',
      category: s.tag || s.cat || '',
    };
  }).filter(b => b.id);
}

export async function aixiaDetail(id) {
  const j = await axPost('/book/detail', { bookId: String(id) });
  const d = (j.data || {}).book || {};
  return {
    source: 'aixia',
    id: String(id),
    name: d.title || '未知书名',
    author: d.author || '佚名',
    intro: d.longIntro || '',
    cover: d.cover ? `https://img22.aixdzs.com/${d.cover}` : '',
    category: [d.cat, d.zt].filter(Boolean).join(','),
  };
}

export async function aixiaToc(id) {
  const j = await axPost('/catalog', { bookId: String(id) });
  const cl = ((j.data || {}).chapterList) || [];
  return cl.map(c => ({ cid: String(c.chapterId), title: c.chapterName }));
}

export async function aixiaContent(bid, cid) {
  // body 中 chapterId 为数字、bookId 为字符串（与官方 App 一致）
  const body = `{"chapterId": ${Number(cid)},"bookId":"${String(bid)}"}`;
  const abc = 'abcdefghijklmnopqrstuvwxyz0123456789';
  let nonce = '';
  for (let i = 0; i < 8; i++) nonce += abc[Math.floor(Math.random() * abc.length)];
  const curtime = String(Math.floor(Date.now() / 1000));
  const checksum = crypto.createHash('sha1').update(AX_SALT + nonce + curtime + nonce).digest('hex');
  const r = await f(`${AX}/chapter/content`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'user-agent': UA_DALVIK,
      checkSumDTO: JSON.stringify({ appid: 'ixdzs', checksum, curtime, nonce }),
    },
    body,
  });
  const j = await r.json();
  const content = String((((j.data || {}).chapter || {}).chapterContent) || '').trim();
  if (!content) throw new Error('正文为空');
  return content;
}

// ---------- 少年梦阅读 ----------
const SN = 'https://api.shaoniandream.com';
const SN_K = '87ac02d392a8d3566fe7748c8de00af3';
const SN_S = '57dcuidu8aa8062bfe8042ea65310669';

function snSign(raw) {
  return crypto.createHash('md5').update(`${raw}&key=${SN_K}&secrect=${SN_S}`).digest('hex').toUpperCase();
}

async function snPost(path, body) {
  const r = await f(`${SN}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'user-agent': UA_OK, version: 'v3' },
    body: JSON.stringify(body),
  });
  return r.json();
}

export async function shaonianSearch(kw) {
  const raw = `count=10&isDevice=Android&keywords=${kw}&page=1&regDevice=2`;
  const j = await snPost('/Booklibrary/index', {
    count: 10, isDevice: 'Android', keywords: kw, page: 1, regDevice: '2', sign: snSign(raw),
  });
  if (j.status !== 1) throw new Error(j.msg || `status ${j.status}`);
  return (j.data || []).map(b => ({
    source: 'shaonian',
    id: String(b.BooksID),
    name: b.title || '未知书名',
    author: b.penName || '佚名',
    intro: b.jianjie || '',
    cover: b.picture ? `${SN}${b.picture}` : '',
    category: '',
  }));
}

export async function shaonianDetail(id) {
  const raw = `BookID=${id}&UserID=-1&isDevice=Android&regDevice=2`;
  const j = await snPost('/Booklibrary/bookdetail', {
    BookID: Number(id), UserID: '-1', isDevice: 'Android', regDevice: '2', sign: snSign(raw),
  });
  if (j.status !== 1) throw new Error(j.msg || `status ${j.status}`);
  const d = j.data || {};
  const au = d.AuthorObj || {};
  const labels = Array.isArray(d.booklabel) ? d.booklabel.map(x => (x && (x.label || x.name)) || x).join(',') : String(d.booklabel || '');
  return {
    source: 'shaonian',
    id: String(id),
    name: d.title || '未知书名',
    author: au.penName || '佚名',
    intro: d.jianjie || '',
    cover: d.picture ? `${SN}${d.picture}` : '',
    category: labels,
  };
}

export async function shaonianToc(id) {
  const raw = `BookID=${id}&UserID=-1&isDevice=Android&regDevice=2`;
  const j = await snPost('/Booklibrary/readdir', {
    BookID: Number(id), UserID: '-1', isDevice: 'Android', regDevice: '2', sign: snSign(raw),
  });
  if (j.status !== 1) throw new Error(j.msg || `status ${j.status}`);
  const out = [];
  for (const vol of (((j.data || {}).chapterList) || [])) {
    for (const c of (vol.chapterList || [])) {
      out.push({ cid: String(c.id), title: c.title });
    }
  }
  return out;
}

export async function shaonianContent(bid, cid) {
  const raw = `BookID=${bid}&UserID=-1&chapter_id=${cid}&isDevice=Android&isMarket=true&regDevice=2`;
  const j = await snPost('/Booklibrary/readchapter', {
    BookID: Number(bid), UserID: '-1', chapter_id: Number(cid),
    isDevice: 'Android', isMarket: 'true', regDevice: '2', sign: snSign(raw),
  });
  if (j.status !== 1) throw new Error(j.msg || `status ${j.status}`);
  const d = j.data || {};
  const parts = (d.show_content || []).map(x => Buffer.from(x.content || '', 'base64').toString('utf8'));
  const content = parts.join('\n').trim();
  if (!content) throw new Error('正文为空（可能为付费/锁章）');
  return content;
}