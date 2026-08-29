# 小说下载助手（书源壳子）

一个本地运行的「书源解析 + 搜索 + 整本 TXT 下载」工具。
本地会自动加载 `sources/builtin/` 里的内置书源；个人另行导入的书源放在 `sources/` 顶层。

**🌐 在线网页版（免翻墙、免安装，打开即用）**：
**https://ygmeh.github.io/novel-download-assistant/**

**📚 过滤后的多源一键导入（已移除 18+ / 成人 / 漫画 / 有声 / 登录 / 脚本 / 加密源，共 356 条安全书源）：**
https://raw.githubusercontent.com/YGMEH/novel-download-assistant/main/sources/builtin/reading_sources_safe.json

在“阅读”App 中选择“网络导入”，粘贴上面的链接即可导入。
纯静态单页（`docs/` 目录），浏览器直连番茄聚合源接口，支持搜索、在线阅读、整本 TXT 下载、夜间模式。
完整多源功能（332 源聚合、并发下载、断点续传）请用下方本地部署方式。

## 在线聚合版（可选部署，一键七源）
`docs/index.html` 支持两种运行模式，自动检测无需配置：
- **聚合模式**：检测到 `/api/aggregator` 后端时启用，同时聚合 7 个书源：番茄、幻梦轻小说、无限小说网、丁丁阅读、纵横中文网、爱下小说、少年梦阅读。搜索结果分组展示、单源失败自动降级不影响其他源；
- **直连模式**：静态托管（GitHub Pages 等）自动回退，仅番茄源，行为与旧版一致。

部署聚合版（免费）：把本仓库接入 [Netlify](https://app.netlify.com)（Import from Git），其余全自动；`netlify.toml` 已配置静态目录与函数。其中「丁丁阅读」与「猫眼」两个源需要鉴权：请在 Netlify 后台（Site settings → Environment variables）配置环境变量 `DD_JWT` 与 `MJ_JWT`（值取各自 JWT 去掉 `bearer` 前缀后的内容）；未配置时这两个源会自动跳过，不影响其余五源。


## 它是什么

- 一个 HTML 前端页面（单文件，无需构建）
- 一个 Python 本地服务（Flask）
- 一个兼容 Legado 书源 JSON 常用规则子集的解析引擎

流程：导入书源 → 输入书名搜索 → 选书 → 获取目录 → 下载整本 TXT。

## 快速开始

```bash
pip install -r requirements.txt
python server.py --open
```

默认地址 `http://127.0.0.1:8765`。

首次打开会自动加载 `sources/builtin/` 里的内置书源，也可再去「书源管理」导入更多。

### 命令行参数

| 参数 | 说明 | 默认 |
|---|---|---|
| `--host` | 监听地址 | `127.0.0.1` |
| `--port` | 端口 | `8765` |
| `--open` | 启动后自动打开浏览器 | 关 |

> 服务**没有鉴权**，默认只监听本机。若改成 `--host 0.0.0.0`，同网段任何人都能调用你的下载接口，请自行加访问控制或防火墙规则。

## 目录结构

```
小说下载助手/
├── index.html          前端页面（搜索 / 任务 / 书源 / 文件 / 设置）
├── server.py           本地 HTTP 服务与 API
├── rule_engine.py      规则解析引擎（CSS / XPath / JSONPath / 正则 / 默认规则）
├── source_manager.py   书源加载、能力自检、搜索详情目录正文
├── downloader.py       并发下载、进度、失败记录、断点续传、合并落盘
├── selftest.py         自测脚本（起本地假书站验证全链路，不访问外网）
├── requirements.txt
├── sources/
│   ├── builtin/            内置书源（开箱即用）
│   │   ├── fanqie_api.json     番茄聚合 API（随仓库内置分发）
│   │   ├── yckceo_1226.json    yckceo 1226 聚合源（303 条原始规则）
│   │   ├── yckceo_1245.json    yckceo 1245 聚合源（39 条原始规则）
│   │   ├── gutenberg.json      Project Gutenberg（公版英文书，默认停用）
│   │   └── wikisource.json     中文维基文库（公版古籍，默认停用）
│   └── example.json.sample   规则写法示例（不会被加载）
├── downloads/          下载好的 TXT
└── .cache/             断点续传缓存
```

## 内置书源

本地内置三份常用书源，放在 `sources/builtin/`，启动即加载：

| 书源 | 文件 | 内容 | 说明 |
|---|---|---|---|
| 番茄聚合 API | `fanqie_api.json` | 番茄小说聚合接口 | 聚合镜像源，默认启用，随仓库内置 |
| yckceo 1226 | `yckceo_1226.json` | 第三方站点聚合（原文件 303 条，去重后约 291 条） | 默认启用；部分含 JS/登录规则，界面会标能力 |
| yckceo 1245 | `yckceo_1245.json` | 第三方站点聚合（原文件 39 条，去重后约 38 条） | 默认启用；与 1226 少量重名同源会按 name+url 去重 |

另外还有两个公版源（默认停用，可在书源页打开）：

| 书源 | 语言 | 说明 |
|---|---|---|
| Project Gutenberg | 英文 | 公有领域作品，整本单章下载全文 |
| 中文维基文库 | 中文 | 公版古籍，搜索走维基文库公开 API |

个人另行导入的书源放在 `sources/` 顶层（被 `.gitignore` 排除）。

两个内置源的限制：

- Gutenberg 的搜索结果是英文书，中文书很少。
- 维基文库的目录规则针对"按回/按节分页"的书籍（如《紅樓夢》《三國演義》）。不分页的长文（单页面）可能只有很少的章节，属于正常情况。
- 维基文库正文带繁简体按页面原始版本，诗词段落会保留。

## 导入书源

「书源」页支持两种方式：

- **从链接导入**：填一个书源 JSON 的 URL
- **粘贴文本导入**：直接贴 JSON，支持单个对象或数组

也可以手动把 `.json` 文件丢进 `sources/` 目录，然后点「重新加载」。

仓库里有一份 `sources/example.json.sample`，指向本地假站、`enabled: false`，只用来演示各字段该怎么写。想参考的话复制一份改名成 `.json` 再改成你自己的站点规则。

导入后每个书源会显示自检结果：

- `可下载` — 目录规则和正文规则都有，能走完整流程
- `不可下载` — 缺关键规则，只能搜索或完全不可用
- 黄色标签 — 具体问题，例如 `含 JS/java 脚本规则`、`需要 WebView 渲染`、`需要登录`

## 支持的规则语法

| 写法 | 示例 |
|---|---|
| CSS | `css:.result li@text`、`css:a.title@href` |
| XPath | `xpath://div[@id='content']`、`//a/@href` |
| JSONPath | `json:$.data.books[*].name` |
| 正则 | `regex:<title>(.*?)</title>` |
| Legado 默认规则 | `class.book-list@tag.li`、`id.content@html` |
| 多规则回退 | `ruleA||ruleB`（取第一个非空） |
| 正则处理 | `rule##要删除的`、`rule##查找##替换` |

属性名支持 `text` `textNodes` `ownText` `html` 以及任意 HTML 属性（`href`、`src`、`data-src` 等）。

搜索地址支持 `{{key}}`、`{{page}}` 变量，以及 Legado 的 `url,{"method":"POST","body":"...","charset":"gbk"}` 写法。

### 不支持

规则里带内嵌 JavaScript（`@js:`、`<js>`、`{{java.xxx}}`）、需要 WebView 渲染、需要登录态或加密签名的书源无法使用。这类源会在列表里被明确标出，不会假装能用。

原因是本引擎只做静态 HTTP 请求 + 规则解析，没有内置 JS 运行时。

## 书源字段对照

同时兼容新旧两种字段命名：

| 用途 | 新版 | 旧版 |
|---|---|---|
| 书源名 | `bookSourceName` | `sourceName` |
| 书源地址 | `bookSourceUrl` | `sourceUrl` |
| 搜索地址 | `searchUrl` | `ruleSearchUrl` |
| 搜索列表 | `ruleSearch.bookList` | `ruleSearchList` |
| 书名 | `ruleSearch.name` | `ruleSearchName` |
| 详情链接 | `ruleSearch.bookUrl` | `ruleSearchNoteUrl` |
| 目录地址 | `ruleBookInfo.tocUrl` | `ruleChapterUrl` |
| 章节列表 | `ruleToc.chapterList` | `ruleChapterList` |
| 章节链接 | `ruleToc.chapterUrl` | `ruleContentUrl` |
| 正文 | `ruleContent.content` | `ruleBookContent` |

## 下载行为

- 并发抓取（默认 4 线程，上限 8），可在「设置」页调整
- 失败自动重试，仍失败的章节会记录标题、链接和错误原因
- 每 20 章写一次缓存；中断或取消后再次下载会自动续传
- 章节顺序严格按目录顺序合并，不依赖抓取完成顺序
- 输出文件带书籍头信息（书名、作者、来源、章节数、下载时间、简介）
- 章节分隔格式：`== 章节标题 ==`
- 抓取失败的章节会留占位文字，不会静默丢内容

「设置」页可调整：下载目录、并发数、重试次数、每章请求间隔（防封）、请求超时。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/sources` | 书源列表，支持 `?q=` 筛选 |
| POST | `/api/sources/import` | 导入书源，body 为 `{url}` 或 `{text, file_name}` |
| POST | `/api/sources/toggle` | 启用/停用某书源 |
| POST | `/api/sources/delete` | 删除书源文件 |
| POST | `/api/sources/reload` | 重新扫描 `sources/` |
| GET | `/api/search` | `?key=书名&source_id=xxx&page=1` |
| GET | `/api/detail` | `?source_id=xxx&book_url=...` |
| GET | `/api/toc` | `?source_id=xxx&toc_url=...` |
| GET | `/api/content` | `?source_id=xxx&url=...` 单章预览，用于验证规则 |
| POST | `/api/download` | body 含 `source_id`、`book`、`chapters` |
| GET | `/api/tasks` / `/api/task/<id>` | 任务列表 / 单个任务进度 |
| POST | `/api/task/<id>/cancel` | 取消任务 |
| GET | `/api/files` | 已下载文件列表 |
| GET/POST | `/api/config` | 读取 / 保存设置 |

## 自测

```bash
python selftest.py
```

会在本机起一个临时假书站，用一份内置的测试规则跑完整链路，校验：书源自检、搜索、详情、目录顺序、正文清洗、整本下载、章节完整性、断点续传、不支持规则的识别。全程不访问外部网站。

## 在 Android 上运行

需要一个能跑 Python 的环境（Termux 等）：

```bash
pkg install python libxml2 libxslt
pip install -r requirements.txt
python server.py --port 8765
```

然后用手机浏览器打开 `http://127.0.0.1:8765`。下载目录建议在「设置」页改成 `/sdcard/Download/小说/` 之类的共享目录，方便其他 App 读取（Termux 需先执行 `termux-setup-storage` 授权）。

## 使用须知

这个项目主要提供解析和下载框架。本地会自动加载 `sources/builtin/` 里的书源快照。

- 请仅导入你**有权访问**的来源
- 遵守目标站点的 robots.txt、服务条款和当地法律
- 不要用它抓取或传播侵权内容
- 建议设置请求间隔，不要给目标站点造成压力

使用者对自己导入的书源和下载的内容负责。

## 云端部署（Render 免费层）

本项目已适配云平台：检测到 `PORT` 环境变量时自动监听 `0.0.0.0`，无需改代码。

1. Fork 本仓库到你的 GitHub，或直接用已有仓库
2. 在 [render.com](https://render.com) 注册 → New → Web Service → 连接该仓库（会自动读取 `render.yaml` 蓝图）
3. 选免费套餐，点部署，完成后得到 `https://<服务名>.onrender.com` 链接

打开链接即可使用，无需安装 Python。

注意：
- 免费实例 15 分钟无访问会休眠，首次打开需等约 1 分钟唤醒
- 免费层磁盘是临时的：服务重启后已下载的 TXT 会丢失（搜索/目录/正文解析不受影响）
- 公网部署后接口无鉴权，任何拿到链接的人都能调用，请自行评估

## License

MIT
