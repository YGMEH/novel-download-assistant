// 番茄目录 502 最小复现
async function fanqieToc(id) {
  const r = await fetch(`https://fq.taijiwang.top/api/directory?book_id=${encodeURIComponent(id)}`, {
    headers: { 'user-agent': 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36' },
  });
  const text = await r.text();
  console.log('status:', r.status);
  console.log('body[0..200]:', text.slice(0, 200));
  const j = JSON.parse(text);
  console.log('code:', j.code, '| lists:', j?.data?.lists?.length);
  return (j?.data?.lists || []).map(c => ({ cid: String(c.item_id), title: c.title }));
}
try {
  const t = await fanqieToc('7077516958534470656');
  console.log('章节数:', t.length, '| 首章:', t[0]);
} catch (e) {
  console.log('ERROR:', e.message);
  console.log(e.stack?.split('\n').slice(0, 4).join('\n'));
}