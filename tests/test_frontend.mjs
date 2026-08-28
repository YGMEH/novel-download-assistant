// 前端无头功能测试：DOM 桩 + 真实上游
import fs from 'node:fs';
import handler from '/root/novel-src/netlify/functions/aggregator.mjs';

// ---- DOM 桩 ----
function makeEl(){
  return {
    textContent:'', innerHTML:'', value:'刀剑神域', disabled:false, src:'',
    style:{}, classList:{ add(){}, remove(){}, toggle(){} },
    removeAttribute(){}, addEventListener(){}, onclick:null,
  };
}
const els = {};
globalThis.document = {
  querySelector(s){ return els[s] ||= makeEl(); },
  documentElement:{ classList:{ add(){}, toggle(){} } },
  createElement(){ return { href:'', download:'', click(){}, style:{} }; },
};
globalThis.window = { scrollTo(){} };
globalThis.localStorage = { night:'' };
URL.createObjectURL = () => 'blob:fake';
URL.revokeObjectURL = () => {};

// 相对路径 AGG 请求改道到真实聚合函数；其余走真 fetch
const realFetch = globalThis.fetch;
globalThis.fetch = async (url, opts) => {
  if (typeof url === 'string' && url.startsWith('/api/aggregator')){
    return handler(new Request('http://local.test' + url, { method:'GET' }));
  }
  return realFetch(url, opts);
};

const sleep = ms => new Promise(r => setTimeout(r, ms));
let js = fs.readFileSync('/tmp/extracted.js', 'utf8');
js += `
;(async () => {
  await sleep(600);
  console.log('--- 聚合模式 ---');
  console.log('MODE:', MODE);
  await doSearch();
  console.log('提示:', els['#listTip'].textContent);
  console.log('列表长度:', els['#list'].innerHTML.length, '字符');

  await openDetail('huanmeng', '8689');
  await sleep(1500);
  console.log('详情书名:', els['#dTitle'].textContent);
  console.log('详情meta:', els['#dMeta'].innerHTML.slice(0, 120));
  console.log('章节数:', chapters.length, '| 首章:', chapters[0]?.title);

  await openReader(0);
  await sleep(2000);
  console.log('阅读器标题:', els['#rH'].textContent);
  console.log('正文前60字:', els['#rCt'].textContent.slice(0, 60).replace(/\\n/g, ' '));

  await downloadBook();
  console.log('下载条文本:', els['#dlTxt'].textContent);

  console.log('--- 直连模式（模拟 github.io） ---');
  MODE = 'direct'; renderModeBadge();
  els['#kw'].value = '剑来';
  await doSearch();
  console.log('提示:', els['#listTip'].textContent);
  console.log('MODE徽章:', els['#modeBadge'].textContent);
  console.log('=== 前端测试结束 ===');
})();
`;
eval(js);