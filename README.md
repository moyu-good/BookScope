# 书鉴 · BookScope

[![CI](https://github.com/moyu-good/BookScope/actions/workflows/ci.yml/badge.svg)](https://github.com/moyu-good/BookScope/actions)
[![Python 3.14+](https://img.shields.io/badge/python-3.14+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

中文 · [English](README.en.md)

> 上传一本大部头,随便问它。凡是它说“书里写了……”,都回原文一个字一个字对过,对得上才显示给你。

🔗 **在线 Demo**:[moyu-good.github.io/BookScope](https://moyu-good.github.io/BookScope/) —— 点开就能玩,预置了一本《三国演义》的真实分析(不用装、不用 key)。想分析自己的书,克隆下来本地跑。

![书鉴 · BookScope 概览](docs/images/overview.png)

书鉴帮你读厚书。把书(epub / txt / pdf)拖进去,你可以像聊天一样问它,也能一键画人物关系图、理时间线、找伏笔、扫一遍全书前后有没有写矛盾。

为什么要它?现在的 AI 答你的时候,经常顺嘴编一句“原文写了 XX”,听着挺像真的,你又没法一句句回去查。书鉴就专门管这件事:AI 每给一句引文,它都翻回原书核对——对得上,才显示,旁边盖个「鉴」字小印,意思是“这句查过了,是真的”;对不上,直接不给你看。书鉴的“鉴”,就是核查的意思。

你的书也不用担心。书鉴跑在你自己电脑上,用你自己的 AI 账号(设置里填个 key)。书的内容直接发给你选的那家 AI(默认 DeepSeek),书鉴这边没有服务器,碰不到你的书,也碰不到你的 key。

## 几张截图

问书:答案底下挂着原文出处,查过的盖了「鉴」印。

![问书:带核验引用的答案](docs/images/qa-citation.png)

人物关系图:能拖,线越粗俩人关系越近,每条线点开都看得到原文。

![人物关系图](docs/images/graph.png)

不管点哪个功能,你都看得见它读了多少字、花了多少 token、跑了几秒。

![运行过程](docs/images/running.png)

## 它能干十三件事

左边一栏切换,一次干一件。除了“问书”是随便聊,其余的点一下(或者填个词)就开跑:

| 功能 | 干啥用 |
|------|--------|
| 问书 | 随便问,答案都带原文出处,每条都查过 |
| 关系图 | 画人物 / 概念的关系网,能拖、按亲疏调远近,每条线点开看原文 |
| 时间线 | 把全书的事按真实先后理顺,多条线、倒叙也能还原 |
| 节奏曲线 | 一章一章看张力,哪几章平、哪几章是高潮 |
| 一致性 | 翻全书找前后打架的地方(第 5 章写左撇子、第 80 章又用右手),两处摆一起 |
| 实体回溯 | 给个人名 / 物件 / 地名,看它全书每次出现在哪 |
| 前情回顾 | 告诉它你读到第几章,它只回顾到这,后面的根本看不到,不剧透 |
| 母题追踪 | 盯一个主题 / 意象,看它在全书反复出现在哪 |
| 论点结构 | 把一本讲道理的书拆开:它主张啥、拿啥撑着 |
| 概念演进 | 给个概念,看它在书里怎么一步步铺开 |
| 写作手法 | 列出作者用了哪些手法,配上原文例子 |
| 知识卡片 | 做成知识点卡片 + 几道反问自测题 |
| 文体体检 | 扫用词重复、视角穿帮、支线写着写着没了 |

凡是要它下判断的(矛盾、伏笔、手法这些),都守一条死规矩:证据回原文查不实的,这条就不说了——宁可少给你几条,也不瞎编。

## 上手

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

打开 `http://localhost:5173` → 左下角设置里填你的 AI key → 拖一本 epub / txt / pdf 进去 → 开问。默认用 DeepSeek 的 `deepseek-v4-flash`,国内能直连,也最便宜。

## 填你自己的 key（BYOK）

书鉴不带任何厂商的 key,你用自己的。设置里预置了八家:DeepSeek(默认)、智谱 GLM、通义千问、Kimi、Anthropic、OpenAI、Gemini、Grok——选哪家,接口地址自动给你填好。除了 Anthropic,其余都走 OpenAI 那套通用接口,所以你自己搭的代理、别的兼容服务也都接得上。

你的 key 只待在浏览器里,跟着请求直接发给你选的那家,不经过任何服务器,也不会传给我们。没有任何埋点统计。

## 它怎么干活的

它不在你传书的时候就把整本拆碎、提前算好一堆结果摆着;而是只建一个轻索引。等你真问了,才让 agent 现场翻原文、一条条核对:

```
传书（一次）              提问（每次）
  解析 epub/txt/pdf       route：判断走快路径还是 agent 循环
  按章切块 + 建索引        agent 现场查原文、给答案 + 引用
                          verify_citations：每条引用回原文逐字比对
                            → 对不上的标记 verified=false，盖不了「鉴」印
```

书不太大、能整本塞进 AI 的,就整本塞,再配一层固定缓存,你反复问同一本能省不少 token;书特别大塞不下的,就退一步,用 BM25 加向量混合检索去捞相关段落。想看细节看 [架构总图](docs/ARCHITECTURE.md),每个功能怎么用看 [用户手册](docs/USER_GUIDE.md)。

## 技术栈

Python 3.14 · FastAPI · Pydantic v2 · React 19 + Vite + TypeScript + Tailwind v4 · 多厂商 LLM(BYOK,默认 DeepSeek)· FAISS + BM25 · 1083 个 pytest 用例。

## 文档

- [用户手册](docs/USER_GUIDE.md) —— 十三个功能逐个怎么用、怎么配 key、怎么读答案
- [架构总图](docs/ARCHITECTURE.md) —— 传书 / 提问两条链路、引用核验、缓存
- [架构决策记录](docs/architecture-decisions/) —— 每个关键技术决策怎么拍的
- [贡献指南](CONTRIBUTING.md)

## License

[MIT](LICENSE)
