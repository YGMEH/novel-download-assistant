// 猫眼正文验证（AES 解密 + 拉取）
import crypto from 'node:crypto';
import fs from 'node:fs';

function aesDecrypt(b64, key, iv) {
  const d = crypto.createDecipheriv('aes-128-cbc', Buffer.from(key), Buffer.from(iv));
  return Buffer.concat([d.update(Buffer.from(b64, 'base64')), d.final()]).toString('utf8');
}

const toc = JSON.parse(fs.readFileSync('/tmp/mj_toc.json', 'utf8'));
const first = toc.data.list[0];
const url = aesDecrypt(first.path, 'f041c49714d39908', '0123456789abcdef');
console.log('猫眼首章:', first.chapterName, '->', url);

const jwt = fs.readFileSync('/tmp/mj_jwt.txt', 'utf8').trim();
const headers = {
  'client-device': '0cdeb38dd0f2a381b06c0a02926ee317',
  'client-brand': 'vivo',
  'client-version': '2.3.0',
  'client-name': 'app.maoyankanshu.novel',
  'client-source': 'android',
  'user-agent': 'okhttp/4.9.2',
  'Authorization': jwt,
};
const r = await fetch(url, { headers });
const text = await r.text();
console.log('正文HTTP:', r.status, '长度:', text.length);
try {
  const j = JSON.parse(text);
  console.log('content前80:', (j.content || '').slice(0, 80).replace(/\n/g, ' '));
} catch { console.log('非JSON:', text.slice(0, 150)); }