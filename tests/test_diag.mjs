// 分辨 terminated 根因：undici fetch(不同头) vs node:https，各测3次
const URL_ = 'https://fq.taijiwang.top/api/directory?book_id=7077516958534470656';
const UA = 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36';

async function viaFetch(label, headers) {
  try {
    const r = await fetch(URL_, { headers });
    const t = await r.text();
    console.log(`${label}: status=${r.status} len=${t.length} code=${JSON.parse(t).code}`);
  } catch (e) {
    console.log(`${label}: FAIL ${e.message}`);
  }
}

async function viaHttps(label) {
  const https = await import('node:https');
  return new Promise(resolve => {
    const req = https.get(URL_, { headers: { 'user-agent': UA } }, res => {
      const chunks = [];
      res.on('data', c => chunks.push(c));
      res.on('end', () => {
        const t = Buffer.concat(chunks).toString('utf8');
        try { console.log(`${label}: status=${res.statusCode} len=${t.length} code=${JSON.parse(t).code}`); }
        catch { console.log(`${label}: status=${res.statusCode} len=${t.length} (非JSON)`); }
        resolve();
      });
    });
    req.on('error', e => { console.log(`${label}: FAIL ${e.message}`); resolve(); });
    req.setTimeout(15000, () => { req.destroy(new Error('timeout')); });
  });
}

for (let i = 1; i <= 3; i++) {
  await viaFetch(`fetch#${i} (默认头)`, {});
  await viaFetch(`fetch#${i} (identity)`, { 'user-agent': UA, 'accept-encoding': 'identity' });
  await viaHttps(`https#${i}`);
}
