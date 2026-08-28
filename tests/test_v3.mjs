// v3 聚合器端到端测试：7 源全链路
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

// 2) 搜索（多关键词覆盖各源）
const kws = ['剑来', '斗破苍穹', '火影'];
let samples = {};
for (const kw of kws) {
  const { j } = await call(`action=search&key=${encodeURIComponent(kw)}`);
  log(`\n【搜索「${kw}」】`);
  for (const s of (j.sources || [])) {
    const n = (s.books || []).length;
    log(`  ${s.source}(${s.label || ''}): ok=${s.ok} 数量=${n}${s.error ? ' 错误=' + s.error.slice(0, 60) : ''}`);
    if (!samples[s.source] && n > 0) samples[s.source] = s.books[0];
  }
}

// 3) 逐个源全链路（详情→目录→正文）
for (const [src, name] of [['zongheng', '纵横'], ['aixia', '爱下'], ['shaonian', '少年梦'], ['dingding', '丁丁'], ['wuxian', '无限'], ['fanqie', '番茄'], ['huanmeng', '幻梦']]) {
  const b = samples[src];
  if (!b) { log(`\n【${name}】无样本，跳过`); continue; }
  try {
    const { j: d } = await call(`action=detail&source=${src}&id=${encodeURIComponent(b.id)}`);
    log(`\n【${name}详情】${d.book?.name} / ${d.book?.author} / ${(d.book?.category || '').slice(0, 30)}`);
    const { j: t } = await call(`action=toc&source=${src}&id=${encodeURIComponent(b.id)}`);
    const chs = t.chapters || [];
    log(`【${name}目录】共 ${chs.length} 章 | 首章: ${chs[0]?.title}`);
    if (chs.length) {
      const { j: c } = await call(`action=content&source=${src}&bid=${encodeURIComponent(b.id)}&cid=${encodeURIComponent(chs[0].cid)}`);
      log(`【${name}正文】长度=${(c.content || '').length} 首行: ${(c.content || '').split('\n')[0].slice(0, 40)}`);
    }
  } catch (e) {
    log(`【${name}】链路失败: ${e.message}`);
  }
}

log('\n测试结束');