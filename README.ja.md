# BookScope 📖

**🌐 Language / 语言 / 言語:** [English](README.md) · [中文](README.zh.md) · [日本語](README.ja.md)

---

**多次元書籍テキスト分析・可視化プラットフォーム。**

[![CI](https://github.com/moyu-good/BookScope/actions/workflows/ci.yml/badge.svg)](https://github.com/moyu-good/BookScope/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## BookScope とは？

BookScope は、あらゆる長文テキストをインタラクティブな感情・文体分析ダッシュボードに変換します。
`.txt`・`.epub`・`.pdf` ファイルをアップロードするか、URLを入力するだけで以下が確認できます：

| タブ | 内容 |
|------|------|
| **Overview（概要）** | 主要感情・平均スコア・語数・検出言語 |
| **Heatmap（ヒートマップ）** | 8感情 × チャンク強度グリッド |
| **Emotion Timeline（感情タイムライン）** | 全チャンクにわたる感情弧グラフ |
| **Style（文体）** | レーダーチャート指紋 + 各指標推移グラフ |
| **Arc Pattern（感情弧パターン）** | ヴォネガット感情弧の自動分類 |
| **Export（エクスポート）** | CSV スコアまたは JSON 分析結果のダウンロード |
| **Chunks（チャンク）** | 各チャンクとスコアの閲覧 |

---

## クイックスタート

```bash
# 1. クローンしてインストール（editable モード — bookscope パッケージの認識に必要）
git clone https://github.com/moyu-good/BookScope.git
cd BookScope
pip install -e ".[dev]"

# 2. NLTK コーパスのダウンロード（初回のみ）
python -m textblob.download_corpora

# 3. 起動
streamlit run app/main.py
```

ブラウザで `http://localhost:8501` を開き、ファイルをアップロードするか URL を入力してください。

> **ヒント：** `ModuleNotFoundError: No module named 'bookscope'` が表示された場合は、プロジェクトルートで `pip install -e .` を実行してください。

---

## 対応入力形式

| 形式 | 説明 |
|------|------|
| `.txt` | UTF-8 / latin-1 / cp1252、自動エンコード検出 |
| `.epub` | ebooklib で HTML ドキュメントを抽出 |
| `.pdf` | PyMuPDF でページごとにテキスト抽出 |
| URL | HTML またはプレーンテキストを取得；trafilatura で本文抽出 |

---

## 多言語サポート

BookScope は書籍の言語を自動検出し、対応する分析バックエンドに切り替えます：

| 言語 | 検出 | トークン化 | 感情辞書 |
|------|------|-----------|---------|
| 🇬🇧 英語 | langdetect | NLTK | NRC 英語 |
| 🇨🇳 中国語 | langdetect | jieba | NRC 中国語（同梱） |
| 🇯🇵 日本語 | langdetect | janome | NRC 日本語（同梱） |

中日文の語数カウントは、スペースがないため非空白文字数をプロキシとして使用します。

---

## 処理の流れ

```
.txt / .epub / .pdf / URL
    │
    ├─ ingest/loader.py      形式別ディスパッチ → プレーンテキスト
    ├─ ingest/cleaner.py     Unicode NFC 正規化 + 空白処理
    ├─ ingest/chunker.py     段落分割または固定ウィンドウ（50% オーバーラップ）
    │
    ├─ nlp/multilingual.py   言語検出・CJK トークン化
    ├─ nlp/lexicon_analyzer.py   NRC 感情辞書 → 8次元 Plutchik スコア [0,1]
    ├─ nlp/style_analyzer.py     NLTK 品詞タグ付け → TTR・文長・品詞比率
    ├─ nlp/arc_classifier.py     多項式フィットで感情弧パターンを分類
    │
    └─ viz/
        ├─ emotion_timeline.py   塗りつぶしエリアチャート
        ├─ heatmap.py            Plotly ヒートマップ
        └─ style_radar.py        レーダー（スパイダー）チャート
```

### 感情モデル — プルチックの感情の輪

BookScope は [Robert Plutchik のモデル](https://en.wikipedia.org/wiki/Robert_Plutchik) に基づき、各テキストチャンクを 8 次元の基本感情でスコアリングします：

`怒り(anger)` · `期待(anticipation)` · `嫌悪(disgust)` · `恐怖(fear)` · `喜び(joy)` · `悲しみ(sadness)` · `驚き(surprise)` · `信頼(trust)`

各スコアは `[0, 1]` に正規化されます（NRC 感情辞書、Mohammad & Turney 2013）。

### 感情弧パターン — ヴォネガットの「物語の形」

BookScope は [Reagan ら（2016）](https://epjdatascience.springeropen.com/articles/10.1140/epjds/s13688-016-0093-1) が発見した 6 種類の感情弧パターンを検出します：

| パターン | 形状 | 代表例 |
|---------|------|--------|
| どん底からの成功（Rags to Riches） | ↗ 持続的上昇 | *大いなる遺産* |
| 栄光からの転落（Riches to Rags） | ↘ 持続的下降 | *ハムレット* |
| 穴に落ちた男（Man in a Hole） | ↘↗ 下降後上昇 | *ホビット* |
| イカロス（Icarus） | ↗↘ 上昇後転落 | *マクベス* |
| シンデレラ（Cinderella） | ↗↘↗ 上昇-下降-上昇 | *シンデレラ* |
| オイディプス（Oedipus） | ↘↗↘ 下降-上昇-下降 | *オイディプス王* |

---

## プロジェクト構成

```
bookscope/
├── ingest/          テキスト読み込み（.txt/.epub/.pdf/URL）・クリーニング・チャンキング
├── models/          Pydantic データモデル
├── nlp/             感情分析・文体指標・感情弧分類・多言語対応
├── store/           JSON 永続化ストレージ
├── utils/           NLTK 初期化ユーティリティ
└── viz/             Plotly レンダラー + ChartDataAdapter

app/
└── main.py          Streamlit エントリーポイント（7 タブ）

tests/               pytest ユニットテスト + hypothesis プロパティテスト（192 件）
```

---

## 技術スタック

| レイヤー | 技術 |
|---------|------|
| 言語 | Python 3.11+ |
| UI | Streamlit |
| チャート | Plotly |
| データモデル | Pydantic v2 |
| 感情分析 | nrclex（NRC 感情辞書）|
| 文体分析 | NLTK averaged_perceptron_tagger |
| 感情弧検出 | numpy 多項式フィッティング |
| 言語検出 | langdetect |
| 中国語トークン化 | jieba |
| 日本語トークン化 | janome |
| PDF 抽出 | PyMuPDF |
| URL 取得 | requests + trafilatura |
| テスト | pytest + hypothesis |
| リント | ruff |
| CI | GitHub Actions |

---

## 開発

```bash
# 開発依存関係のインストール
pip install -e ".[dev]"

# テスト実行
pytest

# リントチェック
ruff check bookscope tests

# 自動修正
ruff check bookscope tests --fix
```

---

## コントリビューション

1. リポジトリをフォーク
2. ブランチを作成：`git checkout -b feature/your-feature`
3. 開発依存関係をインストール：`pip install -e ".[dev]"`
4. 変更に対するテストを作成
5. `pytest && ruff check bookscope tests` を実行
6. プルリクエストを開く

---

## ライセンス

MIT — [LICENSE](LICENSE) を参照。

---

## 参考文献

- Mohammad, S. M., & Turney, P. D. (2013). *Crowdsourcing a word-emotion association lexicon*. Computational Intelligence.
- Plutchik, R. (1980). *Emotion: A psychoevolutionary synthesis*. Harper & Row.
- Reagan, A. J., et al. (2016). *The emotional arcs of stories are dominated by six basic shapes*. EPJ Data Science.
- Vonnegut, K. (1981). *Palm Sunday: An Autobiographical Collage*. Delacorte Press.
