// 丁丁章节路径 AES 解密 + 正文拉取验证
import crypto from 'node:crypto';
import fs from 'node:fs';

const toc = JSON.parse(fs.readFileSync('/tmp/dd_toc3.json', 'utf8'));
const first = toc.data.list[0];
console.log('首章:', first.chapterName, '| path(密文):', first.path.slice(0, 50) + '...');

function aesDecrypt(b64, key, iv) {
  const d = crypto.createDecipheriv('aes-128-cbc', Buffer.from(key), Buffer.from(iv));
  return Buffer.concat([d.update(Buffer.from(b64, 'base64')), d.final()]).toString('utf8');
}

const url = aesDecrypt(first.path, '4395daa50ad6baf7', '0123456789abcdef');
console.log('解密后 URL:', url);

// 带 App 头拉正文
const jwt = fs.readFileSync('/tmp/dd_jwt.txt', 'utf8').trim();
const headers = {
  'client-device': '429497b3cc84a9f1333c793cc6e9110a',
  'client-brand': 'XIAOMI',
  'client-version': '1.1.0',
  'client-channel': 'android',
  'client-name': 'app.maoyankanshu.novel',
  'alias-name': 'dingdianapp',
  'client-source': 'android',
  'user-agent': 'okhttp/4.9.2',
  'Authorization': jwt,
};
const r = await fetch(url, { headers });
const text = await r.text();
console.log('正文HTTP:', r.status, '长度:', text.length);
try {
  const j = JSON.parse(text);
  console.log('字段:', Object.keys(j), '| content前80:', (j.content || '').slice(0, 80).replace(/\n/g, ' '));
} catch { console.log('非JSON:', text.slice(0, 150)); }