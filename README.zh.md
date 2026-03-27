# BookScope 📖

**🌐 Language / 语言 / 言語:** [English](README.md) · [中文](README.zh.md) · [日本語](README.ja.md)

---

**多维度书籍文本分析与可视化工具。**

[![CI](https://github.com/moyu-good/BookScope/actions/workflows/ci.yml/badge.svg)](https://github.com/moyu-good/BookScope/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## BookScope 是什么？

BookScope 能将任意长篇文本转化为交互式情感与文体分析仪表板。
上传 `.txt`、`.epub`、`.pdf` 文件，或粘贴一个 URL，即可获得：

| 标签页 | 内容 |
|--------|------|
| **Overview（概览）** | 主导情感、平均分数、字数、检测语言 |
| **Heatmap（热力图）** | 8维情感 × 分块强度网格 |
| **Emotion Timeline（情感时间线）** | 全章节情感弧线图 |
| **Style（文体）** | 雷达图指纹 + 各指标趋势线 |
| **Arc Pattern（情节弧）** | 冯内古特情节弧自动分类 |
| **Export（导出）** | 下载 CSV 分数或完整 JSON 分析结果 |
| **Chunks（分块）** | 浏览各分块及其分数 |

---

## 快速开始

```bash
# 1. 克隆并安装（editable 模式，确保 Python 能找到 bookscope 包）
git clone https://github.com/moyu-good/BookScope.git
cd BookScope
pip install -e ".[dev]"

# 2. 下载 NLTK 语料库（仅需一次）
python -m textblob.download_corpora

# 3. 启动
streamlit run app/main.py
```

打开 `http://localhost:8501`，上传文件或输入 URL 即可开始分析。

> **提示：** 如果出现 `ModuleNotFoundError: No module named 'bookscope'`，请在项目根目录运行 `pip install -e .`。

---

## 支持的输入格式

| 格式 | 说明 |
|------|------|
| `.txt` | UTF-8 / latin-1 / cp1252，自动检测编码 |
| `.epub` | 通过 ebooklib 提取 HTML 文档内容 |
| `.pdf` | 通过 PyMuPDF 逐页提取文本 |
| URL | 抓取 HTML 或纯文本；通过 trafilatura 提取正文 |

---

## 多语言支持

BookScope 自动检测书籍语言并切换相应分析后端：

| 语言 | 检测 | 分词 | 情感词典 |
|------|------|------|---------|
| 🇬🇧 英语 | langdetect | NLTK | NRC 英语 |
| 🇨🇳 中文 | langdetect | jieba | NRC 中文（内置） |
| 🇯🇵 日语 | langdetect | janome | NRC 日语（内置） |

中日文的字数统计使用非空白字符数作为词数代理（因为词语之间没有空格）。

---

## 工作原理

```
.txt / .epub / .pdf / URL
    │
    ├─ ingest/loader.py      格式分发 → 纯文本
    ├─ ingest/cleaner.py     Unicode NFC 规范化 + 空白处理
    ├─ ingest/chunker.py     段落分割或固定窗口（50% 重叠）
    │
    ├─ nlp/multilingual.py   语言检测、中日文分词
    ├─ nlp/lexicon_analyzer.py   NRC 情感词典 → 8 维 Plutchik 分数 [0,1]
    ├─ nlp/style_analyzer.py     NLTK 词性标注 → TTR、句长、词性比率
    ├─ nlp/arc_classifier.py     多项式拟合情感值 → 情节弧分类
    │
    └─ viz/
        ├─ emotion_timeline.py   填充面积图
        ├─ heatmap.py            Plotly 热力图
        └─ style_radar.py        雷达（蜘蛛）图
```

### 情感模型 — Plutchik 情感轮

BookScope 基于 [Robert Plutchik 的情感模型](https://en.wikipedia.org/wiki/Robert_Plutchik) 对每个文本分块进行 8 维情感评分：

`愤怒(anger)` · `期待(anticipation)` · `厌恶(disgust)` · `恐惧(fear)` · `喜悦(joy)` · `悲伤(sadness)` · `惊讶(surprise)` · `信任(trust)`

每种情感分数归一化至 `[0, 1]`（NRC 情感词典，Mohammad & Turney 2013）。

### 情节弧 — 冯内古特的故事形状

BookScope 能识别 [Reagan 等人（2016）](https://epjdatascience.springeropen.com/articles/10.1140/epjds/s13688-016-0093-1) 发现的六种情感弧模式：

| 模式 | 形状 | 代表作 |
|------|------|--------|
| 白手起家（Rags to Riches） | ↗ 持续上升 | 《远大前程》 |
| 盛极而衰（Riches to Rags） | ↘ 持续下降 | 《哈姆雷特》 |
| 跌入谷底（Man in a Hole） | ↘↗ 先降后升 | 《霍比特人》 |
| 乐极生悲（Icarus） | ↗↘ 先升后降 | 《麦克白》 |
| 好事多磨（Cinderella） | ↗↘↗ 升-降-升 | 《灰姑娘》 |
| 回光返照（Oedipus） | ↘↗↘ 降-升-降 | 《俄狄浦斯王》 |

---

## 项目结构

```
bookscope/
├── ingest/          文本加载（.txt/.epub/.pdf/URL）、清洗、分块
├── models/          Pydantic 数据模型
├── nlp/             情感分析、文体指标、情节弧分类、多语言支持
├── store/           JSON 持久化存储
├── utils/           NLTK 初始化工具
└── viz/             Plotly 渲染器 + ChartDataAdapter

app/
└── main.py          Streamlit 入口（7 个标签页）

tests/               pytest 单元测试 + hypothesis 属性测试（192 个）
```

---

## 技术栈

| 层 | 技术 |
|----|------|
| 语言 | Python 3.11+ |
| UI | Streamlit |
| 图表 | Plotly |
| 数据模型 | Pydantic v2 |
| 情感分析 | nrclex（NRC 情感词典）|
| 文体分析 | NLTK averaged_perceptron_tagger |
| 情节弧检测 | numpy 多项式拟合 |
| 语言检测 | langdetect |
| 中文分词 | jieba |
| 日文分词 | janome |
| PDF 提取 | PyMuPDF |
| URL 抓取 | requests + trafilatura |
| 测试 | pytest + hypothesis |
| 代码检查 | ruff |
| CI | GitHub Actions |

---

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest

# 代码检查
ruff check bookscope tests

# 自动修复
ruff check bookscope tests --fix
```

---

## 贡献

1. Fork 本仓库
2. 创建分支：`git checkout -b feature/your-feature`
3. 安装开发依赖：`pip install -e ".[dev]"`
4. 为你的改动编写测试
5. 运行 `pytest && ruff check bookscope tests`
6. 提交 Pull Request

---

## 许可证

MIT — 详见 [LICENSE](LICENSE)。

---

## 参考文献

- Mohammad, S. M., & Turney, P. D. (2013). *Crowdsourcing a word-emotion association lexicon*. Computational Intelligence.
- Plutchik, R. (1980). *Emotion: A psychoevolutionary synthesis*. Harper & Row.
- Reagan, A. J., et al. (2016). *The emotional arcs of stories are dominated by six basic shapes*. EPJ Data Science.
- Vonnegut, K. (1981). *Palm Sunday: An Autobiographical Collage*. Delacorte Press.
