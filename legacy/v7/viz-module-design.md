# BookScope — viz/ モジュール詳細設計書

## 1. 設計方針

可視化モジュールは「分析結果を受け取り、インタラクティブなチャートを返す」という単一の責務を持つ。各コンポーネントは独立してテスト可能であり、Streamlitに依存しない純粋なデータ変換層と、Streamlit固有の描画層を明確に分離する。

---

## 2. クラス設計

### 2.1 全体クラス構成

```
viz/
├── __init__.py
├── base.py              # BaseRenderer, ChartDataAdapter
├── emotion_timeline.py  # EmotionTimelineRenderer
├── emotion_heatmap.py   # EmotionHeatmapRenderer
├── style_radar.py       # StyleRadarRenderer
├── compare_view.py      # CompareViewRenderer
├── theme.py             # BookScopeTheme (配色・フォント定義)
└── export.py            # ExportManager (PNG/CSV/Markdown)
```

### 2.2 基底クラス

```python
# viz/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

@dataclass
class ChartConfig:
    """チャートの表示設定"""
    width: int = 800
    height: int = 500
    theme: str = "bookscope"
    locale: str = "ja"        # 軸ラベル等の言語
    interactive: bool = True   # ホバー・ズーム有効化

class ChartDataAdapter:
    """
    分析結果のスキーマ (Pydantic) → 
    各チャートライブラリが要求するデータ構造への変換を担う。
    
    役割: Renderer から Plotly/D3 の詳細を隠蔽し、
          分析スキーマが変わっても Renderer 側の改修を最小化する。
    """
    
    @staticmethod
    def to_timeline_series(
        emotions: list["ChapterEmotion"],
        channels: list[str] | None = None
    ) -> dict:
        """
        ChapterEmotion[] → Plotly用 dict
        
        出力例:
        {
            "x": [1, 2, 3, ...],              # 章番号
            "traces": {
                "joy":     [0.72, 0.65, ...],
                "sadness": [0.15, 0.30, ...],
                ...
            },
            "labels": ["上 先生と私", "上 先生と私", ...]
        }
        """
        ...
    
    @staticmethod
    def to_radar_data(
        fingerprint: "StyleFingerprint"
    ) -> dict:
        """
        StyleFingerprint → Plotly scatterpolar 用 dict
        
        出力例:
        {
            "categories": ["平均文長", "語彙多様性", "名詞比率", ...],
            "values": [0.65, 0.82, 0.45, ...],
            "range": [0, 1]   # 正規化済み
        }
        """
        ...
    
    @staticmethod
    def to_heatmap_matrix(
        emotions: list["ChapterEmotion"],
        channels: list[str] | None = None
    ) -> dict:
        """
        ChapterEmotion[] → D3 heatmap 用 matrix
        
        出力例:
        {
            "x_labels": ["Ch.1", "Ch.2", ...],
            "y_labels": ["joy", "trust", "fear", ...],
            "matrix": [[0.72, 0.65, ...], [0.15, 0.30, ...], ...],
            "text_previews": [["先生は...", "私は..."], ...]
        }
        """
        ...
    
    @staticmethod
    def to_compare_pair(
        book_a: "AnalysisResult",
        book_b: "AnalysisResult"
    ) -> dict:
        """2冊の分析結果を並列比較用の構造に変換"""
        ...


class BaseRenderer(ABC):
    """
    全Rendererの基底クラス。
    Streamlit への描画プロトコルを統一する。
    """
    
    def __init__(self, config: ChartConfig | None = None):
        self.config = config or ChartConfig()
        self.theme = BookScopeTheme()
    
    @abstractmethod
    def prepare_data(self, raw_data: Any) -> dict:
        """生データ → チャート用データ構造への変換"""
        ...
    
    @abstractmethod
    def build_figure(self, chart_data: dict) -> Any:
        """チャート用データ → Plotly Figure / D3 HTML"""
        ...
    
    def render(self, raw_data: Any, container=None) -> None:
        """
        Streamlit上に描画する統一エントリーポイント。
        
        1. prepare_data() でデータ変換
        2. build_figure() でチャート生成
        3. container (st / st.columns[]) に配置
        """
        chart_data = self.prepare_data(raw_data)
        figure = self.build_figure(chart_data)
        target = container or st
        
        if isinstance(figure, go.Figure):
            target.plotly_chart(figure, use_container_width=True)
        elif isinstance(figure, str):  # HTML string (D3)
            target.components.v1.html(figure, height=self.config.height)
    
    def export_png(self, raw_data: Any, path: str) -> None:
        """チャートをPNG画像として保存"""
        ...
    
    def export_data(self, raw_data: Any, path: str) -> None:
        """チャートの元データをCSVとして保存"""
        ...
```

### 2.3 各Rendererの設計

#### EmotionTimelineRenderer

```python
# viz/emotion_timeline.py

class EmotionTimelineRenderer(BaseRenderer):
    """
    感情推移の折れ線グラフ + 面グラフ。
    X軸: 章の進行、Y軸: 感情スコア (0-1)
    
    機能:
    - 8感情チャネルの個別表示/重ね合わせ切替
    - ポジティブ/ネガティブの面グラフ表示
    - 感情アーク（全体傾向線）のオーバーレイ
    - ホバーで該当章の冒頭テキストをプレビュー
    - 章クリックで詳細パネルへジャンプ
    
    使用ライブラリ: Plotly (go.Scatter + go.Figure)
    
    入力: list[ChapterEmotion]
    出力: plotly.graph_objects.Figure
    """
    
    DEFAULT_CHANNELS = [
        "joy", "trust", "fear", "surprise",
        "sadness", "disgust", "anger", "anticipation"
    ]
    
    CHANNEL_COLORS = {
        "joy":          "#EF9F27",  # amber
        "trust":        "#5DCAA5",  # teal
        "fear":         "#7F77DD",  # purple
        "surprise":     "#ED93B1",  # pink
        "sadness":      "#378ADD",  # blue
        "disgust":      "#97C459",  # green
        "anger":        "#E24B4A",  # red
        "anticipation": "#D85A30",  # coral
    }
    
    def prepare_data(self, raw_data):
        return ChartDataAdapter.to_timeline_series(
            raw_data, channels=self.DEFAULT_CHANNELS
        )
    
    def build_figure(self, chart_data):
        fig = go.Figure()
        for channel, values in chart_data["traces"].items():
            fig.add_trace(go.Scatter(
                x=chart_data["x"],
                y=values,
                name=self._localize(channel),
                line=dict(color=self.CHANNEL_COLORS[channel], width=2),
                hovertemplate="%{customdata}<br>%{y:.2f}",
                customdata=chart_data["labels"],
            ))
        fig.update_layout(**self.theme.timeline_layout())
        return fig
```

#### EmotionHeatmapRenderer

```python
# viz/emotion_heatmap.py

class EmotionHeatmapRenderer(BaseRenderer):
    """
    感情×章のヒートマップ。
    X軸: 章の進行、Y軸: 8感情チャネル、色: 感情強度
    
    機能:
    - セルホバーでテキストプレビュー表示
    - 行（感情チャネル）クリックでその感情の詳細推移へ
    - カラースケール切替（sequential / diverging）
    - 章の粒度切替（章 / 段落 / 固定ウィンドウ）
    
    使用ライブラリ: D3.js (Streamlit Component経由)
    
    理由: Plotly の heatmap はホバー時のリッチなテキスト
          プレビュー表示に制約がある。D3 であれば
          tooltip 内に該当テキストの冒頭を自由に配置可能。
    
    入力: list[ChapterEmotion]
    出力: str (HTML string, D3.js inline)
    """
    
    def prepare_data(self, raw_data):
        return ChartDataAdapter.to_heatmap_matrix(raw_data)
    
    def build_figure(self, chart_data):
        # D3.js のテンプレートHTMLにデータを埋め込んで返す
        return self._render_d3_template(
            template="heatmap.html",
            data=chart_data,
            config=self.config,
            theme=self.theme,
        )
```

#### StyleRadarRenderer

```python
# viz/style_radar.py

class StyleRadarRenderer(BaseRenderer):
    """
    文体指紋のレーダーチャート。
    各軸: 文体指標（10軸）、値: 0-1正規化スコア
    
    機能:
    - 章ごとの指紋を重ねて表示（半透明）
    - 全体平均と特定章の比較
    - 比較モード: 2冊の指紋を同一チャートに重畳
    - 各軸クリックで指標の説明パネル表示
    
    使用ライブラリ: Plotly (go.Scatterpolar)
    
    入力: StyleFingerprint | list[StyleFingerprint]
    出力: plotly.graph_objects.Figure
    """
    
    AXIS_LABELS_JA = {
        "avg_sentence_length": "平均文長",
        "ttr": "語彙多様性",
        "noun_ratio": "名詞比率",
        "verb_ratio": "動詞比率",
        "adj_ratio": "形容詞比率",
        "adv_ratio": "副詞比率",
        "passive_ratio": "受動態比率",
        "clause_depth": "文の複雑度",
        "readability_score": "可読性",
        "hapax_legomena_ratio": "一回出現語比率",
    }
    
    def prepare_data(self, raw_data):
        if isinstance(raw_data, list):
            return [ChartDataAdapter.to_radar_data(fp) for fp in raw_data]
        return ChartDataAdapter.to_radar_data(raw_data)
    
    def build_figure(self, chart_data):
        fig = go.Figure()
        datasets = chart_data if isinstance(chart_data, list) else [chart_data]
        for i, data in enumerate(datasets):
            fig.add_trace(go.Scatterpolar(
                r=data["values"] + [data["values"][0]],
                theta=data["categories"] + [data["categories"][0]],
                fill="toself",
                opacity=0.6 if len(datasets) > 1 else 0.8,
                name=data.get("label", f"Book {i+1}"),
            ))
        fig.update_layout(**self.theme.radar_layout())
        return fig
```

#### CompareViewRenderer

```python
# viz/compare_view.py

class CompareViewRenderer(BaseRenderer):
    """
    2冊の書籍を並列比較するコンポジットビュー。
    
    構成:
    ┌─────────────────────┬─────────────────────┐
    │   Book A 概要カード  │   Book B 概要カード  │
    ├─────────────────────┴─────────────────────┤
    │   感情アーク重ね合わせ (EmotionTimeline)    │
    ├─────────────────────┬─────────────────────┤
    │  Style Radar (A)    │  Style Radar (B)    │
    ├─────────────────────┴─────────────────────┤
    │   差分サマリー（数値テーブル）              │
    └───────────────────────────────────────────┘
    
    このRendererは他のRendererを内部で組み合わせる
    コンポジットパターンで実装する。
    
    入力: tuple[AnalysisResult, AnalysisResult]
    出力: None (Streamlit上に直接描画)
    """
    
    def __init__(self, config=None):
        super().__init__(config)
        self.timeline = EmotionTimelineRenderer(config)
        self.radar = StyleRadarRenderer(config)
    
    def render(self, raw_data, container=None):
        book_a, book_b = raw_data
        target = container or st
        
        # 概要カード (2列)
        col1, col2 = target.columns(2)
        self._render_summary_card(book_a.metadata, col1)
        self._render_summary_card(book_b.metadata, col2)
        
        # 感情アーク重ね合わせ (全幅)
        compare_data = ChartDataAdapter.to_compare_pair(book_a, book_b)
        self.timeline.render(compare_data["emotions"], target)
        
        # レーダー比較 (2列)
        col1, col2 = target.columns(2)
        self.radar.render(book_a.style, col1)
        self.radar.render(book_b.style, col2)
        
        # 差分テーブル
        self._render_diff_table(compare_data["diff"], target)
```

### 2.4 テーマ管理

```python
# viz/theme.py

class BookScopeTheme:
    """
    全チャート共通の配色・フォント・レイアウトを一元管理。
    Plotly の layout dict を生成するファクトリ。
    """
    
    FONT_FAMILY = "Noto Sans JP, Noto Sans SC, sans-serif"
    
    BG_COLOR = "rgba(0,0,0,0)"  # 透明（Streamlitのテーマに合わせる）
    GRID_COLOR = "rgba(128,128,128,0.15)"
    
    def base_layout(self) -> dict:
        return dict(
            font=dict(family=self.FONT_FAMILY, size=13),
            paper_bgcolor=self.BG_COLOR,
            plot_bgcolor=self.BG_COLOR,
            margin=dict(l=40, r=20, t=40, b=40),
            hoverlabel=dict(font_size=12),
        )
    
    def timeline_layout(self) -> dict:
        base = self.base_layout()
        base.update(
            xaxis=dict(title="章", gridcolor=self.GRID_COLOR),
            yaxis=dict(title="感情スコア", range=[0, 1], gridcolor=self.GRID_COLOR),
            legend=dict(orientation="h", y=-0.15),
            hovermode="x unified",
        )
        return base
    
    def radar_layout(self) -> dict:
        base = self.base_layout()
        base.update(
            polar=dict(
                radialaxis=dict(visible=True, range=[0, 1], gridcolor=self.GRID_COLOR),
            ),
        )
        return base
    
    def heatmap_colorscale(self) -> str:
        return "YlOrRd"  # 0=薄黄 → 1=濃赤
```

---

## 3. 技術選定比較表

### 3.1 ダッシュボードフレームワーク

| 評価軸 | Streamlit | Dash (Plotly) | Panel (HoloViz) | Gradio |
|-------|-----------|---------------|-----------------|--------|
| **学習コスト** | 低い。Pythonスクリプトを書く感覚で構築可能 | 中程度。Flask的なコールバック設計の理解が必要 | 中程度。HoloVizエコシステムへの理解が必要 | 低い。ML デモ向けに最適化 |
| **カスタマイズ性** | 中程度。Components APIで拡張可能だが制約あり | 高い。HTML/CSS/JSを自由に組み込める | 高い。Bokehベースで柔軟 | 低い。UIパターンが限定的 |
| **インタラクション** | 基本的。セレクトボックス・スライダー中心 | 高度。任意のコールバックチェーンが可能 | 高度。Paramベースのリアクティブ更新 | 基本的。入出力のペア構造 |
| **デプロイ容易性** | Streamlit Cloudで無料デプロイ可能 | Heroku/Render等が必要 | 同左 | Hugging Face Spacesで無料 |
| **OSSとの親和性** | 高い。`streamlit run`で即起動 | 中程度。依存が多め | 中程度 | 高い |
| **日本語フォント** | 対応可能（カスタムCSS） | 対応可能 | 対応可能 | 制約あり |
| **GitHub Stars** | ~37k | ~22k | ~4k | ~35k |

**結論: Streamlit を採用**

最大の理由は「`pip install bookscope && streamlit run app/main.py` で即座にダッシュボードが立ち上がる」という体験が、OSSプロジェクトの導入障壁を最も低くするため。カスタマイズ性の不足はStreamlit Components (D3.js) で補完する。Dashは機能的には優れるが、コールバック設計の複雑さがコントリビュータの参入障壁になる。

---

### 3.2 チャートライブラリ

| 評価軸 | Plotly | D3.js | Matplotlib | ECharts | Altair |
|-------|--------|-------|------------|---------|--------|
| **インタラクティブ性** | 高い（ホバー・ズーム・パン標準装備） | 最高（完全カスタム可能） | なし（静的画像） | 高い | 中程度 |
| **Streamlit統合** | ネイティブ対応 (`st.plotly_chart`) | Components経由（HTML埋め込み） | ネイティブ (`st.pyplot`) | Components経由 | ネイティブ (`st.altair_chart`) |
| **レーダーチャート** | `Scatterpolar`で対応 | 自作必要 | patches で可能だが煩雑 | 対応 | 非対応 |
| **ヒートマップ** | 基本的（tooltip制約あり） | 完全カスタム可能 | `imshow`で対応 | 対応 | 対応 |
| **日本語ラベル** | 対応 | フォント指定で対応 | フォント設定が煩雑 | 対応 | 対応 |
| **PNGエクスポート** | `kaleido`で対応 | `html2canvas`等が必要 | ネイティブ | ライブラリ必要 | ネイティブ |
| **学習コスト** | 低〜中 | 高い | 低い | 低〜中 | 低い |

**結論: Plotly をメイン + D3.js をサブで採用**

標準的なチャート（折れ線、レーダー、棒グラフ）は Plotly で十分にカバーできる。Streamlitとのネイティブ統合により、追加の設定なしでインタラクティブなチャートが描画可能。ヒートマップのようにリッチなtooltip（テキストプレビュー表示）が必要な場面に限り、D3.js を Streamlit Component として組み込む。Matplotlibは静的画像のため、本プロジェクトの「インタラクティブ」要件に合わない。

---

### 3.3 D3.js Streamlit Component の実装方針

Streamlitのカスタムコンポーネントとして D3.js を組み込む方式は2つある。

| 方式 | `st.components.v1.html()` | カスタムComponent (npm) |
|------|--------------------------|----------------------|
| **実装コスト** | 低い。HTML文字列を渡すだけ | 高い。React + npm ビルドが必要 |
| **双方向通信** | Python→JS のみ（一方向） | 双方向（JS→Pythonのコールバック可能） |
| **パフォーマンス** | iframe内で毎回再レンダリング | 差分更新可能 |
| **適用場面** | 表示専用のチャート | クリックイベントでPython側の状態を更新したい場合 |

**結論: Phase 1-2 は `st.components.v1.html()` で十分。**

ヒートマップのセルクリックでPython側の状態を更新する必要が出てきた Phase 3 で、カスタムComponent への移行を検討する。初期段階で npm ビルド環境を要求すると、コントリビュータの参入障壁が上がるため。

---

## 4. ページ構成とレイアウト

### 4.1 Overview ページ

```
┌─ sidebar ──────────┐┌─ main ──────────────────────────────┐
│                    ││                                      │
│  [書籍選択]        ││  KPIカード (4列)                     │
│  ├ こころ          ││  ┌────┐┌────┐┌────┐┌────┐           │
│  └ 1984            ││  │総文数││語彙数││感情Arc││可読性│    │
│                    ││  └────┘└────┘└────┘└────┘           │
│  [言語]  自動検出  ││                                      │
│                    ││  感情アーク概要 (EmotionTimeline)     │
│  [分析設定]        ││  ┌──────────────────────────────┐    │
│  チャンクサイズ    ││  │  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~ │    │
│  [章|段落|固定窓]  ││  └──────────────────────────────┘    │
│                    ││                                      │
│  [エクスポート]    ││  文体サマリー (StyleRadar, 縮小版)    │
│  PNG | CSV | MD    ││  ┌──────────────────────────────┐    │
│                    ││  │       ◇ レーダー              │    │
└────────────────────┘│  └──────────────────────────────┘    │
                      └──────────────────────────────────────┘
```

### 4.2 Sentiment ページ

```
┌─ main ───────────────────────────────────────────────────┐
│                                                           │
│  [感情チャネル選択] ☑joy ☑sadness ☑fear □trust ...       │
│                                                           │
│  感情タイムライン (EmotionTimeline, フルサイズ)            │
│  ┌───────────────────────────────────────────────────┐    │
│  │  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~    │    │
│  │  ↑ クリックで下のヒートマップと連動                │    │
│  └───────────────────────────────────────────────────┘    │
│                                                           │
│  感情ヒートマップ (EmotionHeatmap)                        │
│  ┌───────────────────────────────────────────────────┐    │
│  │ joy      ▓▓░░▓▓▓░░▓▓▓▓░░▓▓░░░░▓▓▓▓▓▓░░░░▓▓   │    │
│  │ sadness  ░░▓▓░░░▓▓░░░░▓▓░░▓▓▓▓░░░░░░▓▓▓▓░░   │    │
│  │ fear     ░░░░░░░░░░░░░░▓▓▓▓░░░░░░░░░░░░▓▓▓▓   │    │
│  │ ...                                              │    │
│  └───────────────────────────────────────────────────┘    │
│                                                           │
│  感情アーク分類: "Man in a hole" パターン                  │
│  (書籍全体の感情曲線が6基本パターンのどれに近いか表示)     │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

### 4.3 Style ページ

```
┌─ main ───────────────────────────────────────────────────┐
│                                                           │
│  文体指紋レーダー (StyleRadar, フルサイズ)                 │
│  ┌───────────────────────────────────────────────────┐    │
│  │            ◇                                      │    │
│  │     全体平均 (実線) + 選択章 (点線)                │    │
│  └───────────────────────────────────────────────────┘    │
│                                                           │
│  ┌──────────────────────┐┌──────────────────────────┐    │
│  │ 語彙多様性の推移      ││ 平均文長の推移            │    │
│  │ (Plotly line chart)   ││ (Plotly line chart)       │    │
│  └──────────────────────┘└──────────────────────────┘    │
│                                                           │
│  文末表現分布 (です/ます vs だ/である)                     │
│  ┌───────────────────────────────────────────────────┐    │
│  │ (Plotly stacked bar chart)                        │    │
│  └───────────────────────────────────────────────────┘    │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

---

## 5. インタラクション設計

| 操作 | トリガー | 影響範囲 | 実装方式 |
|-----|---------|---------|---------|
| 書籍切替 | サイドバーのセレクトボックス | 全ページの全チャートが再描画 | `st.session_state["selected_book"]` |
| 章選択 | タイムラインの点クリック | ヒートマップのハイライト列、レーダーの重畳線 | Plotly `clickData` callback |
| 感情チャネルフィルタ | チェックボックス群 | タイムライン + ヒートマップの表示チャネル | `st.multiselect` → Adapter再変換 |
| チャンク粒度切替 | ラジオボタン (章/段落/窓) | 全感情・文体チャートのX軸粒度 | `st.radio` → 再分析トリガー |
| エクスポート | サイドバーのボタン | 指定フォーマットでダウンロード | `st.download_button` + ExportManager |
| 比較モード切替 | Compare ページへの遷移 | CompareViewRenderer が起動 | Streamlit multipage routing |

---

## 6. パフォーマンス考慮

| 懸念事項 | 対策 |
|---------|------|
| 大容量テキスト（10万文以上）のヒートマップ描画が重い | 章単位で集約したデータをデフォルト表示、段落粒度はオンデマンド展開 |
| Plotlyの大量トレース描画が遅い | 8感情チャネルの同時表示は最大3チャネルをデフォルトON、残りはチェックで追加 |
| D3 Component の iframe 再レンダリング | データ変更がない場合は `st.cache_data` で HTML 文字列をキャッシュ |
| 比較モードで2冊分のデータを同時保持 | `st.session_state` にキャッシュ済みの AnalysisResult を格納 |
