<p align="center">
  <img src="docs/images/logo.svg" width="120" alt="书鉴 BookScope">
</p>

<h1 align="center">书鉴 · BookScope</h1>

<p align="center">
  <b>把几百万字的大部头，变成一本可核验、可交互、可追问的「书鉴」。</b><br>
  问书、画关系、理时间线、追伏笔、读公文、跨文本对照——每条结论都翻回原文核对，对得上才盖「鉴」印。
</p>

<p align="center">
  <a href="https://github.com/moyu-good/BookScope/actions"><img src="https://github.com/moyu-good/BookScope/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.12%2B-blue.svg" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/react-19-61dafb.svg" alt="React 19">
  <img src="https://img.shields.io/badge/AI--Native-DeepSeek%20Ready-4D6BFE.svg" alt="AI Native / DeepSeek Ready">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT">
</p>

<p align="center">
  中文 · <a href="README.en.md">English</a> · <a href="https://moyu-good.github.io/BookScope/">在线 Demo</a>
</p>

---

## 为什么会有 BookScope

现在的 AI 聊天工具读长文时，最让人不敢信的是：它随口说「原文写了 XX」，你没法逐字回去查。书鉴从一开始就把「核验」当成立身之本——每一条引文都翻回原文逐字比对，对得上才显示并盖「鉴」印，对不上的直接不给你看；需要推断的地方明确标「研判」，不冒充事实。

它也不是一个「阅读器」，而是一个**工具**：把复杂的长文本分析拆成一个个点一下就能用的动作，让几百万字的书也能渐进式地跑起来——先秒出结构版，后台继续构建深度版，随时能看到进度，不用干等几十分钟。

<p align="center">
  <img src="docs/images/hero-bookshelf.png" width="820" alt="书柜：每本书成一卷书脊，按题材上色">
  <br>
  <sub>书柜。传进来的每本书立成一卷书脊，按题材上色：朱砂是公文，暖琥珀是小说与历史，墨青是理论与论文。</sub>
</p>

---

## ✨ 核心能力

### 1. 可核验的问答
问书、问公文、跨书追问，答案都挂原文出处。逐字核对过的盖「鉴」印，核不上的不会冒出来。

<p align="center">
  <img src="docs/images/hero-ask.png" width="760" alt="问书：答案挂原文出处，逐字核对过的盖「鉴」印">
</p>

### 2. 读书人的可视化
不是冷冰冰的仪表盘，而是有书卷气的图：叙事曲线画成水墨山峦，人物关系铺成星图，角色弧线长成工笔花鸟。每一笔背后都钉着原文。

<p align="center">
  <img src="docs/images/narrative.png" width="48%" alt="山水叙事曲线">
  <img src="docs/images/arc.png" width="48%" alt="花鸟人物弧线">
  <br>
  <sub>左：叙事曲线画成山水长卷。右：人物弧线画成工笔花鸟。</sub>
</p>

<p align="center">
  <img src="docs/images/relationship.png" width="48%" alt="关系演变小多图时间线">
  <img src="docs/images/foreshadow.png" width="48%" alt="伏笔回收弧线">
  <br>
  <sub>左：关系演变。右：伏笔回收。</sub>
</p>

### 3. 长文档渐进式分析
几百万字也不怕：先出零 LLM 的结构版报告（秒出），后台按章预建深度版，进度实时可见；改哪章只重算哪章，重复操作全部走缓存。

### 4. 跨文本对照与簇关系发现
把多本书/多份文档摆在一起，自动发现谁继承谁、谁反驳谁、谁补充谁，还能一键生成可交互的 HTML 报告或进入结构化「对照工作台」继续追问。

### 5. 公文/红头文件专门适配
自动识别公文，换一套读公文的工具：官话翻人话、挑相关条款、算时限门槛、多文件依据链分析。

---

## 🚀 快速开始

需要 **Python 3.12+** 和 **Node.js 18+**。

```bash
# 1. 克隆
git clone https://github.com/moyu-good/BookScope.git
cd BookScope

# 2. 装后端（pip 或 uv 二选一）
pip install -e ".[dev]"
# 或
uv pip install --system -e ".[dev]"

# 3. 一次性下载 NLTK 资源
python -m textblob.download_corpora

# 4. 启动后端
uvicorn bookscope.api.app:create_app --factory --reload --port 8000

# 5. 另开终端启动前端
cd web && npm install && npm run dev
```

打开 <http://localhost:5173>，左下角设置里填你自己的 AI key，拖一本 epub / txt / pdf 进去就能开始。

### 不想开浏览器？直接命令行

```bash
# 一条命令把书变成可分享的结构版 HTML 报告（零 LLM、秒出）
bookscope report 书.epub --out 书鉴.html

# 启动本地服务
bookscope serve --port 8000

# 两个文件直接出跨文本对照 HTML 报告（需要 LLM key）
bookscope cross 书A.epub 书B.pdf --out 对照.html --api-key sk-...

# 对一本书直接提问，输出带原文引用的答案
bookscope ask 书.epub "这本书的核心主张是什么？" --api-key sk-...

# 先预建章脉缓存，后续 report/cross/ask 会更快
bookscope prewarm 书.epub --api-key sk-...
```

> 💡 默认使用 **DeepSeek `deepseek-v4-flash`**：国内可直连、便宜、适合长文本批量分析。也支持 OpenAI 兼容接口，自己搭的代理/网关都能接。

---

## 🧩 生态适配 & 快捷使用

BookScope 定位是**工具**，所以「接入简单、复杂功能一键可用」和功能本身一样重要。

| 场景 | 方式 |
| --- | --- |
| **本地 Web 工具** | 一条命令起前后端，浏览器里拖文件即用 |
| **BYOK 多厂商** | DeepSeek（默认）、智谱、通义、Kimi、Anthropic、OpenAI、Gemini、Grok，或任何 OpenAI 兼容服务 |
| **可分享交付物** | 报告生成独立 HTML，可下载、新窗口打开、打印/存 PDF |
| **IM 推送** | 支持 Feishu 文件推送（配置 `outbound.allowedFileDirs` 后直接把报告发到会话） |
| **结构化数据** | 跨文本对照/簇关系提供 JSON 数据端点，方便二次开发 |
| **在线 Demo** | [moyu-good.github.io/BookScope](https://moyu-good.github.io/BookScope/) 免安装体验 |

### AI-Native / DeepSeek Ready
- 默认 DeepSeek，针对长文本、JSON 结构化输出做了重试与容错；
- 所有分析端点统一 BYOK，key 只留在浏览器，不经过任何服务器；
- 支持 OpenAI 兼容协议，接代理、接国产模型、接自建网关都只需改 base_url。

---

## 🏗 它怎么干活

不在传书时把整本拆碎提前算完。传书只建轻索引；你真问了，才让 agent 现场翻原文、逐条核对。

```
传书（一次）                提问（每次）
  解析 epub/txt/pdf          route：判断走快路径还是 agent 循环
  按章切块 + 建索引           agent 现场查原文、给答案 + 引用
                            verify_citations：每条引用回原文逐字比对
                              → 对不上的盖不了「鉴」印
```

整本书的图（关系、曲线、伏笔）走另一条路：整本精读一次，出一份带原文证据的逐章结构，所有图都从这一份派生，不重复读全书。

---

## 🛠 技术栈

- **后端**：Python 3.12 · FastAPI · Pydantic v2 · SQLite 缓存
- **前端**：React 19 · Vite · TypeScript · Tailwind v4
- **AI**：多厂商 LLM（BYOK，默认 DeepSeek）· OpenAI 兼容协议
- **检索/分析**：FAISS · BM25 · NetworkX · 2000+ pytest 用例

---

## 📚 文档

- [用户手册](docs/USER_GUIDE.md)
- [架构总图](docs/ARCHITECTURE.md)
- [架构决策记录](docs/architecture-decisions/)
- [贡献指南](CONTRIBUTING.md)

---

## 🤝 贡献

欢迎提 Issue、PR、想法。请保持「核验优先」和「渐进交付」两条主线：任何新功能都要能锚回原文，任何长文档操作都不能让用户干等。

---

## License

[MIT](LICENSE)
