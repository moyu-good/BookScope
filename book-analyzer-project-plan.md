# BookScope — 書籍テキスト分析・可視化プラットフォーム

## プロジェクト概要

汎用的な書籍テキスト分析ツールを構築し、感情推移と文体特徴をインタラクティブなWebダッシュボードで可視化する。多言語対応（日英中）を備え、GitHub上でOSSとして公開する。

---

## 技術スタック

| レイヤー | 採用技術 | 選定理由 |
|---------|---------|---------|
| 言語 | Python 3.11+ | NLPエコシステムの充実 |
| 形態素解析 | spaCy + GiNZA (ja), en_core_web_trf (en), zh_core_web_trf (zh) | 多言語を統一APIで処理可能 |
| 感情分析 | transformers (multilingual sentiment) + カスタム辞書 | VADERの二値分類を超える多次元分析 |
| 文体分析 | 自作モジュール (spaCy POS統計ベース) | 既存に汎用ライブラリが存在しないため |
| トピック分析 | BERTopic | 多言語対応かつ解釈性が高い |
| ダッシュボード | Streamlit + Plotly | Pythonのみで完結、デプロイ容易 |
| 高度な可視化 | D3.js (Streamlit components経由) | ヒートマップ等のカスタム描画 |
| データ格納 | JSON + SQLite | 軽量かつ依存なし |
| デプロイ | Streamlit Cloud / GitHub Pages (静的出力) | 無料枠で公開可能 |

---

## リポジトリ構成

```
bookscope/
├── README.md                  # プロジェクト説明（日英併記）
├── pyproject.toml             # 依存管理 (Poetry / uv)
├── bookscope/
│   ├── __init__.py
│   ├── ingest/                # 入力処理
│   │   ├── loader.py          # txt/epub/PDF/URL読み込み
│   │   ├── cleaner.py         # ノイズ除去・正規化
│   │   └── chunker.py         # 章・段落・文への分割
│   ├── nlp/                   # 分析パイプライン
│   │   ├── lang_detect.py     # 言語自動判定
│   │   ├── preprocessor.py    # トークン化・レンマ化
│   │   ├── sentiment.py       # 多次元感情分析
│   │   ├── stylometrics.py    # 文体指紋スコアリング
│   │   └── topics.py          # トピックモデリング
│   ├── models/                # データモデル
│   │   └── schemas.py         # Pydanticスキーマ定義
│   ├── store/                 # データ永続化
│   │   └── repository.py      # JSON/SQLite I/O
│   └── viz/                   # 可視化コンポーネント
│       ├── emotion_timeline.py
│       ├── style_radar.py
│       ├── heatmap.py
│       └── compare_view.py
├── app/                       # Streamlitアプリ
│   ├── main.py                # エントリーポイント
│   ├── pages/
│   │   ├── 01_upload.py       # 書籍アップロード
│   │   ├── 02_overview.py     # 概要ダッシュボード
│   │   ├── 03_sentiment.py    # 感情分析詳細
│   │   ├── 04_style.py        # 文体分析詳細
│   │   └── 05_compare.py      # 書籍比較
│   └── components/            # カスタムStreamlitコンポーネント
│       └── d3_heatmap/
├── tests/
│   ├── test_sentiment.py
│   ├── test_stylometrics.py
│   └── fixtures/              # テスト用テキストデータ
├── notebooks/                 # 実験・検証用
│   └── exploration.ipynb
├── docs/                      # ドキュメント
│   ├── architecture.md
│   └── api_reference.md
└── .github/
    └── workflows/
        └── ci.yml             # テスト・リント自動実行
```

---

## 開発フェーズ

### Phase 1: MVP — 単一書籍の基本分析（2〜3週間）

このフェーズのゴールは「1冊のテキストを投入したら、感情の推移グラフと基本的な文体指標が表示される」最小限の動作を実現すること。

**タスク一覧:**

1. **入力パイプライン構築** — `ingest/` モジュール
   - txt形式の読み込みと章分割ロジック
   - 文単位の分割（spaCyのsentencizer活用）
   - 青空文庫形式のルビ・注釈除去

2. **感情分析エンジン v1** — `nlp/sentiment.py`
   - Hugging Faceのmultilingual sentimentモデル導入
   - 文単位でスコアリング → 章単位で集計
   - 出力: `{chapter_id, sentence_id, positive, negative, neutral}`

3. **文体分析エンジン v1** — `nlp/stylometrics.py`
   - 5つの基本指標を実装:
     - 平均文長（単語数/文字数）
     - 語彙多様性（TTR: Type-Token Ratio）
     - 品詞比率（名詞/動詞/形容詞/副詞）
     - 受動態使用率
     - 文の複雑度（従属節の深さ）
   - 章ごとの推移データ生成

4. **ダッシュボード v1** — `app/`
   - Streamlit で単一ページ構成
   - Plotlyの折れ線グラフで感情推移を表示
   - レーダーチャートで文体指紋を表示

**Phase 1 完了基準:** 夏目漱石「こころ」(青空文庫)をアップロードし、感情推移グラフと文体レーダーが表示される。

---

### Phase 2: 分析の深化 + 多言語対応（2〜3週間）

**タスク一覧:**

1. **多次元感情モデル** — `nlp/sentiment.py` 拡張
   - Plutchikの8基本感情への拡張
     (joy, trust, fear, surprise, sadness, disgust, anger, anticipation)
   - NRC Emotion Lexicon + transformerモデルのアンサンブル
   - 感情アーク（Emotional Arc）の自動分類
     - 6つの基本パターン検出（Rags to riches, Riches to rags, etc.）

2. **文体指標の追加** — `nlp/stylometrics.py` 拡張
   - 可読性スコア（Flesch-Kincaid相当、日本語は独自実装）
   - 文末表現の分布（です/ます vs だ/である）
   - 修辞技法の検出（反復、対比、比喩の頻度）
   - 語彙リッチネスの推移（窓付きTTR）

3. **多言語対応** — `nlp/lang_detect.py` + 各モジュール
   - langdetectで自動言語判定
   - 言語ごとのspaCyモデル切り替え
   - 日本語固有: GiNZAによる係り受け解析活用
   - 中国語固有: jieba分詞との連携

4. **入力形式の拡充** — `ingest/loader.py`
   - epub対応（ebooklib）
   - PDF対応（PyMuPDF）
   - URL指定（requests + BeautifulSoup）

**Phase 2 完了基準:** 英語・日本語・中国語の書籍各1冊で全分析が動作する。

---

### Phase 3: ダッシュボード強化 + 比較機能（2〜3週間）

**タスク一覧:**

1. **ヒートマップ型タイムライン** — `viz/heatmap.py`
   - X軸: 書籍の進行（章 or ページ比率）
   - Y軸: 感情チャネル（8次元）
   - セルの色: 感情強度
   - ホバーで該当テキストをプレビュー

2. **書籍比較モード** — `app/pages/05_compare.py`
   - 2冊の並列表示
   - 感情アークの重ね合わせ
   - 文体レーダーの差分表示
   - 語彙の共通度（Jaccard係数）の可視化

3. **ページ構成の整理** — `app/pages/`
   - マルチページ構成への移行
   - サイドバーでの書籍選択UI
   - 分析パラメータの調整パネル

4. **エクスポート機能**
   - 分析結果のJSON/CSVダウンロード
   - グラフ画像のPNGエクスポート
   - 分析レポートのMarkdown自動生成

**Phase 3 完了基準:** 2冊の書籍を並べて比較でき、分析結果をエクスポートできる。

---

### Phase 4: 公開準備 + 仕上げ（1〜2週間）

1. **README整備** — 日英併記、スクリーンショット付き
2. **GitHub Actions CI** — pytest + ruff による自動チェック
3. **デモデータ同梱** — 青空文庫/Project Gutenbergから著作権切れ作品3冊
4. **Streamlit Cloudデプロイ** — ワンクリックで試せるデモ環境
5. **ドキュメント** — アーキテクチャ説明、API仕様、コントリビューションガイド
6. **ライセンス** — MIT License

---

## 主要モジュールの設計メモ

### sentiment.py — 多次元感情分析

```python
# 基本インターフェース案
class SentimentAnalyzer:
    def __init__(self, lang: str = "auto"):
        self.lang = lang
        self.model = load_multilingual_model()
        self.lexicon = load_nrc_lexicon(lang)
    
    def analyze_sentence(self, text: str) -> EmotionScore:
        """文単位の8次元感情スコアを返す"""
        ...
    
    def analyze_chapter(self, sentences: list[str]) -> ChapterEmotion:
        """章単位の集計 + 感情アーク判定"""
        ...
    
    def detect_arc_pattern(self, scores: list[float]) -> ArcType:
        """感情推移の曲線フィッティングによるパターン分類"""
        ...
```

### stylometrics.py — 文体指紋

```python
class StyleAnalyzer:
    METRICS = [
        "avg_sentence_length",    # 平均文長
        "ttr",                    # 語彙多様性
        "noun_ratio",             # 名詞比率
        "verb_ratio",             # 動詞比率
        "adj_ratio",              # 形容詞比率
        "adv_ratio",              # 副詞比率
        "passive_ratio",          # 受動態比率
        "clause_depth",           # 文の複雑度
        "readability_score",      # 可読性スコア
        "hapax_legomena_ratio",   # 一回出現語比率
    ]
    
    def fingerprint(self, doc: spacy.Doc) -> StyleFingerprint:
        """テキスト全体の文体指紋を生成"""
        ...
    
    def track_over_chapters(self, chapters: list) -> list[StyleFingerprint]:
        """章ごとの文体推移を追跡"""
        ...
```

---

## リスクと対策

| リスク | 影響 | 対策 |
|-------|-----|------|
| 日本語感情辞書の精度不足 | 感情分析の品質低下 | NRC + WRIME辞書の併用、transformerモデルで補完 |
| 大容量テキストの処理速度 | UX悪化 | バッチ処理 + プログレスバー、結果キャッシュ |
| spaCyモデルのサイズ | デプロイ困難 | sm/mdモデルを基本、trf はオプション |
| Streamlit Cloudの制約 | メモリ不足 | テキスト長の上限設定、段階的処理 |

---

## 次のアクション

1. リポジトリ作成 + `pyproject.toml` でdependency定義
2. `ingest/loader.py` で青空文庫テキストの読み込み実装
3. `nlp/sentiment.py` のv1実装（Hugging Face multilingual）
4. Streamlitで最小限のグラフ表示を確認
