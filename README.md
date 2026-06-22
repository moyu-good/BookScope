<p align="center">
  <img src="docs/images/logo.svg" width="116" alt="书鉴 BookScope">
</p>

<h1 align="center">书鉴 · BookScope</h1>

<p align="center">
  读厚书的人用的工具。AI 答你的每一句「书里写了……」，都回原文一字一字对过，对得上才显示、盖一个「鉴」印。
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
  <img src="docs/images/hero.svg" width="720" alt="AI 引的原文回书里逐字核验，对得上才盖「鉴」印">
</p>

---

## 它是什么

把一本大部头（epub / txt / pdf）拖进去，像聊天一样问它，也能画人物关系图、理时间线、找伏笔、看一章一章的节奏，扫一遍全书前后有没有写矛盾。

跑在你自己电脑上，用你自己的 AI 账号。书的内容直接发给你选的那家 AI（默认 DeepSeek），书鉴这边没有服务器，碰不到你的书，也碰不到你的 key。

**在线 Demo**：[moyu-good.github.io/BookScope](https://moyu-good.github.io/BookScope/) —— 一本《三国演义》跑好的结果，不用装、不用填 key，打开就能点。想分析自己的书，克隆到本地。

## 为什么不一样

现在的 AI 答你的时候经常顺嘴编一句「原文写了 XX」，听着像真的，你又没法一句句回去查。

书鉴专门管这件事：AI 每给一句引文，它都翻回原书逐字核对，对得上才显示、旁边盖一个「鉴」印，对不上的直接不给你看。要它下判断的地方（矛盾、伏笔、手法这些）也守同一条死规矩 —— 查不实就不说，宁可少给几条也不瞎编。

「鉴」就是核查。这是书鉴的立身之本，不是一个附加功能。

## 能做什么

左边一栏切功能，一次跑一件。「问书」是随便聊，其余点一下（或填个词）就开跑。

| | |
|---|---|
| **问书** | 随便问，答案都带原文出处、每条都查过 |
| **前情回顾** | 说你读到第几章，只回顾到这、后面不剧透 |
| **关系图** | 人物 / 概念的关系网，能拖，线越粗越亲近，点开看原文 |
| **关系随时间** | 两个人一章章怎么升温降温，转折点配原文 |
| **叙事流 / 戏份弧线** | 谁和谁逐章同场、谁的戏份起落 |
| **声口一致** | 一个角色说话腔调稳不稳，标出「这句不像他说的」 |
| **时间线** | 全书的事按真实先后理顺，多线、倒叙也能还原 |
| **节奏 / 多维曲线** | 逐章的张力、情感、视角、主支线 |
| **伏笔回收 / 支线编织** | 哪个伏笔埋了没收、每条支线何时活跃交汇 |
| **实体 / 母题 / 概念** | 盯一个人 / 物 / 主题 / 概念，看它全书怎么铺开 |
| **一致性 / 文体体检** | 翻全书找前后打架、用词重复、视角穿帮 |
| **改稿清单** | 把诊断发现归成能勾选、能导出的修改单 |
| **论点结构 / 知识卡片** | 拆一本讲道理的书：它主张啥、拿啥撑着，做成自测卡 |
| **精读注释** | 边读原文边在行间看到伏笔、矛盾、母题的批注 |

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

## 几张截图

| | |
|---|---|
| ![问书：带核验引用的答案](docs/images/qa-citation.png) | ![人物关系图](docs/images/graph.png) |
| 问书：答案挂着原文出处，查过的盖了「鉴」印 | 关系图：线越粗越亲近，每条点开都看得到原文 |

每点一个功能，都看得见它读了多少字、花了多少 token、跑了几秒。

## 自带 key（BYOK）

书鉴不带任何厂商的 key，你用自己的。设置里预置了八家：DeepSeek（默认）、智谱 GLM、通义千问、Kimi、Anthropic、OpenAI、Gemini、Grok，选哪家接口地址就自动填好。除 Anthropic 外都走 OpenAI 那套通用接口，你自己搭的代理、别的兼容服务也接得上。

key 只待在浏览器里，跟着请求直接发给你选的那家，不经过任何服务器，也没有埋点统计。

## 它怎么干活

不在传书的时候就把整本拆碎、提前算好一堆结果摆着，而是只建一个轻索引。等你真问了，才让 agent 现场翻原文、一条条核对：

```
传书（一次）              提问（每次）
  解析 epub/txt/pdf        route：判断走快路径还是 agent 循环
  按章切块 + 建索引         agent 现场查原文、给答案 + 引用
                          verify_citations：每条引用回原文逐字比对
                            → 对不上的标 verified=false，盖不了「鉴」印
```

书不大、能整本塞进 AI 的，就整本塞 + 一层固定缓存，反复问同一本省 token；书特别大塞不下的，退一步用 BM25 加向量混合检索捞相关段落。

## 技术栈

Python 3.14 · FastAPI · Pydantic v2 · React 19 + Vite + TypeScript + Tailwind v4 · 多厂商 LLM（BYOK，默认 DeepSeek）· FAISS + BM25 · 1200+ 个 pytest 用例。

## 文档

- [用户手册](docs/USER_GUIDE.md)：各功能怎么用、怎么配 key、怎么读答案
- [架构总图](docs/ARCHITECTURE.md)：传书 / 提问两条链路、引用核验、缓存
- [架构决策记录](docs/architecture-decisions/)：每个关键技术决策怎么拍的
- [贡献指南](CONTRIBUTING.md)

## License

[MIT](LICENSE)
