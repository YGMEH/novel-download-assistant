// 本地全链路实测：直接调用 aggregator.mjs 的默认导出
import handler from '/root/novel-src/netlify/functions/aggregator.mjs';

function mk(method, url) {
  return new Request(url, { method });
}

async function call(label, url) {
  const t0 = Date.now();
  try {
    const res = await handler(mk('GET', url));
    const j = await res.json();
    const ms = Date.now() - t0;
    console.log(`\n### ${label} -> HTTP ${res.status} (${ms}ms)`);
    return j;
  } catch (e) {
    console.log(`\n### ${label} -> 异常: ${e.message}`);
    return null;
  }
}

const BASE = 'http://localhost/api/aggregator';

// 1. ping
await call('ping', `${BASE}?action=ping`);

// 2. 聚合搜索：剑来（番茄有、幻梦无）
let j = await call('聚合搜索「剑来」', `${BASE}?action=search&key=${encodeURIComponent('剑来')}`);
if (j?.sources) {
  for (const s of j.sources) {
    console.log(`  ${s.source}: ok=${s.ok} 书目=${s.books.length}${s.error ? ' err=' + s.error : ''}`);
    if (s.books.length) console.log(`   首本: ${s.books[0].name} / ${s.books[0].author} / id=${s.books[0].id}`);
  }
  const fq = j.sources.find(s => s.source === 'fanqie' && s.ok && s.books.length);
  if (fq) {
    const id = fq.books[0].id;
    // 3. 番茄详情
    const d = await call('番茄详情 id=' + id, `${BASE}?action=detail&source=fanqie&id=${id}`);
    console.log('  书名:', d?.book?.name, '| 分类:', d?.book?.category);
    // 4. 番茄目录
    const t = await call('番茄目录 id=' + id, `${BASE}?action=toc&source=fanqie&id=${id}`);
    if (t?.chapters) {
      console.log(`  章节数: ${t.chapters.length} | 首章: ${t.chapters[0].title} cid=${t.chapters[0].cid}`);
      // 5. 番茄正文
      const c = await call('番茄正文 首章', `${BASE}?action=content&source=fanqie&cid=${t.chapters[0].cid}`);
      console.log('  正文前80字:', (c?.content || '(空)').slice(0, 80).replace(/\n/g, ' '));
    }
  }
}

// 6. 聚合搜索：刀剑神域（幻梦有）
j = await call('聚合搜索「刀剑神域」', `${BASE}?action=search&key=${encodeURIComponent('刀剑神域')}`);
if (j?.sources) {
  for (const s of j.sources) {
    console.log(`  ${s.source}: ok=${s.ok} 书目=${s.books.length}${s.error ? ' err=' + s.error : ''}`);
  }
  const hm = j.sources.find(s => s.source === 'huanmeng' && s.ok && s.books.length);
  if (hm) {
    const id = hm.books[0].id;
    console.log(`  幻梦首本: ${hm.books[0].name} / ${hm.books[0].author} / id=${id}`);
    // 7. 幻梦详情
    await call('幻梦详情 id=' + id, `${BASE}?action=detail&source=huanmeng&id=${id}`);
    // 8. 幻梦目录
    const t = await call('幻梦目录 id=' + id, `${BASE}?action=toc&source=huanmeng&id=${id}`);
    if (t?.chapters) {
      console.log(`  章节数: ${t.chapters.length} | 首章: ${t.chapters[0].title} cid=${t.chapters[0].cid}`);
      // 9. 幻梦正文
      const c = await call('幻梦正文 首章', `${BASE}?action=content&source=huanmeng&bid=${id}&cid=${t.chapters[0].cid}`);
      console.log('  正文前80字:', (c?.content || '(空)').slice(0, 80).replace(/\n/g, ' '));
    }
  }
}

// 10. 异常路径：未知来源 / 缺参数
await call('未知来源(应400)', `${BASE}?action=detail&source=xxx&id=1`);
await call('缺关键词(应400)', `${BASE}?action=search`);
console.log('\n=== 实测结束 ===');