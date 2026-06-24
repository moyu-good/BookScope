<p align="center">
  <img src="docs/images/logo.svg" width="116" alt="书鉴 BookScope">
</p>

<h1 align="center">书鉴 · BookScope</h1>

<p align="center">
  读厚书的人用的工具。问它书里的事，每句引文都翻回原文一字一字对过，对得上才显示、盖一个「鉴」印；它还把整本书按读书人的眼光画出来。
</p>

<p align="center">
  <a href="https://github.com/moyu-good/BookScope/actions"><img src="https://github.com/moyu-good/BookScope/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.14+-blue.svg" alt="Python 3.14+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
</p>

<p align="center">
  中文 · <a href="README.en.md">English</a> · <a href="https://moyu-good.github.io/BookScope/">在线 Demo</a>
</p>

<p align="center">
  <img src="docs/images/graph.png" width="760" alt="星图人物关系：每个人是一颗星，连线是关系，点开看原文">
  <br>
  <sub>《三国演义》的人物关系——每个人一颗星，戏份越重越亮，敌红盟绿，点一条线看那一章的原文。</sub>
</p>

---

## 它是什么

把一本大部头（epub / txt / pdf）拖进去，像聊天一样问它。它也能画人物关系、看一章章的张力起落、理时间线、追伏笔、扫全书前后有没有写矛盾。

跑在你自己电脑上，用你自己的 AI 账号。书直接发给你选的那家 AI（默认 DeepSeek），书鉴这边没有服务器，碰不到你的书，也碰不到你的 key。

**在线 Demo**：[moyu-good.github.io/BookScope](https://moyu-good.github.io/BookScope/) —— 一本《三国演义》跑好的结果，不用装也不用填 key，打开就能点。想分析自己的书，克隆到本地。

## 凭什么不一样

**一是核验。** 现在的 AI 答你的时候经常顺嘴编一句「原文写了 XX」，听着像真的，你又没法一句句回去查。书鉴每给一句引文，都翻回原书逐字核对，对得上才显示、旁边盖一个「鉴」印，对不上的直接不给你看。要它下判断的地方（矛盾、伏笔、手法）也守同一条规矩：查不实就不说，宁可少给几条也不瞎编。这是立身之本，不是附加功能。

**二是它把整本书画出来，画法是读书人的，不是数据仪表盘。** 张力曲线画成一道水墨山峦，人物关系铺成一片夜空星图，角色弧线长成一枝工笔花鸟。每一笔背后都钉着原文：点关系图的一条线、或时间线的一件事，它现去那一章把支撑的原句捞出来给你看。

<p align="center">
  <img src="docs/images/narrative.png" width="48%" alt="山水叙事曲线">
  <img src="docs/images/arc.png" width="48%" alt="花鸟人物弧线">
  <br>
  <sub>左：叙事曲线画成山水长卷，一峰一谷是一章的张力，红点是高潮。右：人物弧线画成工笔花鸟，每个角色一枝，枝的起伏是他的处境、着花疏密是他的戏份。</sub>
</p>

<p align="center">
  <img src="docs/images/qa-citation.png" width="60%" alt="带核验的问答：答案挂原文出处，盖「鉴」印">
  <br>
  <sub>问书：答案挂着原文出处，逐字核对过的盖了「鉴」印；核不上的不会冒出来。</sub>
</p>

## 能做什么

左边一栏切功能，一次跑一件。「问书」是随便聊，其余点一下（或填个词）就开跑。按你想干的事分四拨：

- **问**：问书（带原文出处答深问题）· 前情回顾（说你读到第几章，只回顾到这、后面不剧透）
- **看人物**：关系网 + 关系怎么一章章升温降温 · 谁何时同场、谁的戏份起落 · 一个角色说话腔调稳不稳
- **看情节**：逐章的张力 / 情感 / 视角 / 主支线 · 伏笔埋了收没收 · 每条支线何时活跃交汇 · 多线倒叙也理清真实时序
- **查证学习**：盯一个人 / 物 / 母题 / 概念看它全书怎么铺开 · 扫前后矛盾、用词重复、视角穿帮 · 拆一本讲道理的书的论点结构、做成自测卡 · 把诊断聚成能勾选的改稿清单 · 边读边在行间看带证据的批注

每点一个功能，都看得见它读了多少字、花了多少 token、跑了几秒。

## 快速开始

需要 Python 3.14+ 和 Node.js。

```bash
git clone https://github.com/moyu-good/BookScope.git
cd BookScope
pip install -e ".[dev]"
python -m textblob.download_corpora       # 一次性 NLTK 资源

uvicorn bookscope.api.app:create_app --factory --reload --port 8000   # 后端

# 另开一个终端
cd web && npm install && npm run dev       # 前端，http://localhost:5173
```

打开 `http://localhost:5173`，左下角设置里填你的 AI key，拖一本 epub / txt / pdf 进去，开问。默认用 DeepSeek 的 `deepseek-v4-flash`，国内能直连，也最便宜。

## 自带 key（BYOK）

书鉴不带任何厂商的 key，你用自己的。设置里预置了八家：DeepSeek（默认）、智谱 GLM、通义千问、Kimi、Anthropic、OpenAI、Gemini、Grok，选哪家接口地址就自动填好。除 Anthropic 外都走 OpenAI 那套通用接口，你自己搭的代理、别的兼容服务也接得上。

key 只待在浏览器里，跟着请求直接发给你选的那家，不经过任何服务器，也没有埋点统计。

## 它怎么干活

不在传书的时候就把整本拆碎、提前算好一堆结论摆着。传书只建一个轻索引；等你真问了，才让 agent 现场翻原文、一条条核对：

```
传书（一次）              提问（每次）
  解析 epub/txt/pdf        route：判断走快路径还是 agent 循环
  按章切块 + 建索引         agent 现场查原文、给答案 + 引用
                          verify_citations：每条引用回原文逐字比对
                            → 对不上的盖不了「鉴」印
```

要画整本书的那些图（关系、曲线、伏笔），是另一条路：整本精读一次，出一份带原文证据的逐章结构，各种图都从这一份派生，不用每画一张就重读一遍全书。所以几百万字的网文也跑得动——点之前它会先告诉你这本有多大、大概要等多久。

## 技术栈

Python 3.14 · FastAPI · Pydantic v2 · React 19 + Vite + TypeScript + Tailwind v4 · 多厂商 LLM（BYOK，默认 DeepSeek）· FAISS + BM25 · 1300+ 个 pytest 用例。

## 文档

- [用户手册](docs/USER_GUIDE.md)：各功能怎么用、怎么配 key、怎么读答案
- [架构总图](docs/ARCHITECTURE.md)：传书 / 提问两条链路、引用核验、缓存
- [架构决策记录](docs/architecture-decisions/)：每个关键技术决策怎么拍的
- [贡献指南](CONTRIBUTING.md)

## License

[MIT](LICENSE)
