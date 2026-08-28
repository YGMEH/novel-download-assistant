// v2 聚合器端到端测试：模拟 Netlify 调用 default export
import agg from '../netlify/functions/aggregator.mjs';

const BASE = 'https://site.local/api/aggregator';
const log = (...a) => console.log(...a);

async function call(qs) {
  const res = await agg(new Request(`${BASE}?${qs}`));
  const j = await res.json();
  return { status: res.status, j };
}

// 1) ping
{
  const { j } = await call('action=ping');
  log('【ping】', JSON.stringify(j));
}

// 2) 四源并行搜索
const kw = '剑来';
const { j: s1 } = await call(`action=search&key=${encodeURIComponent(kw)}`);
log(`\n【搜索「${kw}」】`);
let ddBook = null, hmBook = null;
for (const s of (s1.sources || [])) {
  log(`  ${s.source}(${s.label || ''}): ok=${s.ok} 数量=${(s.books || []).length}${s.error ? ' 错误=' + s.error : ''}`);
  if (s.source === 'dingding' && s.books?.length && !ddBook) ddBook = s.books[0];
  if (s.source === 'huanmeng' && s.books?.length && !hmBook) hmBook = s.books[0];
}

// 3) 丁丁全链路：详情 → 目录(1305章) → 正文(带 path 透传)
if (ddBook) {
  const { j: d } = await call(`action=detail&source=dingding&id=${encodeURIComponent(ddBook.id)}`);
  log(`\n【丁丁详情】${d.book?.name} / ${d.book?.author} / ${d.book?.category}`);
  const { j: t } = await call(`action=toc&source=dingding&id=${encodeURIComponent(ddBook.id)}`);
  const chs = t.chapters || [];
  log(`【丁丁目录】共 ${chs.length} 章 | 首章: ${chs[0]?.title} | 附带path=${Boolean(chs[0]?.path)} w=${chs[0]?.w}`);
  const first = chs[0];
  const qs = `action=content&source=dingding&bid=${encodeURIComponent(ddBook.id)}&cid=${encodeURIComponent(first.cid)}&w=${first.w}&path=${encodeURIComponent(first.path)}`;
  const { j: c } = await call(qs);
  log(`【丁丁正文】长度=${(c.content || '').length} 首行: ${(c.content || '').split('\n')[0].slice(0, 40)}`);
} else {
  log('\n【丁丁】搜索无结果，跳过全链路');
}

// 4) 无限小说网全链路（换关键词更准）
{
  const { j: s2 } = await call(`action=search&key=${encodeURIComponent('斗破苍穹')}`);
  const wx = (s2.sources || []).find(s => s.source === 'wuxian');
  const hit = (wx?.books || [])[0];
  if (hit) {
    log(`\n【无限搜索「斗破苍穹」】${(wx.books || []).length} 本 | 首本: ${hit.name}（id=${hit.id}）`);
    const { j: d } = await call(`action=detail&source=wuxian&id=${encodeURIComponent(hit.id)}`);
    log(`【无限详情】${d.book?.name} / ${d.book?.author} / bookId=${d.book?.bookId} | 简介前30: ${(d.book?.intro || '').slice(0, 30)}`);
    const { j: t } = await call(`action=toc&source=wuxian&id=${encodeURIComponent(hit.id)}`);
    log(`【无限目录】共 ${(t.chapters || []).length} 章 | 首章: ${t.chapters?.[0]?.title}`);
    const { j: c } = await call(`action=content&source=wuxian&bid=${encodeURIComponent(hit.id)}&cid=${encodeURIComponent(t.chapters[0].cid)}`);
    log(`【无限正文】长度=${(c.content || '').length} 首行: ${(c.content || '').split('\n')[0].slice(0, 40)}`);
  } else {
    log('\n【无限】搜索无结果', wx?.error || '');
  }
}

// 5) 幻梦回归（v1 链路未被破坏）
if (hmBook) {
  const { j: t } = await call(`action=toc&source=huanmeng&id=${encodeURIComponent(hmBook.id)}`);
  log(`\n【幻梦回归】《${hmBook.name}》目录 ${(t.chapters || []).length} 章`);
}

log('\n测试结束');
