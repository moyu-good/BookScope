"""r1 FastAPI 入口的请求 / 响应 Pydantic schema。

本模块只负责 API 层的 I/O 契约，不持有任何业务逻辑。所有模型都是
Pydantic v2 BaseModel，FastAPI 会自动用它们做序列化与 OpenAPI 生成。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class PreviousReviewHint(BaseModel):
    """重答时把上次 reviewer 给的批评摘要传回 generator。

    Review 模型的瘦身版——FE 不必把整份 Review 回传，只挑能注入到
    system prompt 的关键信息：总分 + 5 维评语 + top_issues。
    格式异常时 routes 层 fallback 跳过注入不崩。
    """

    total_score: int = Field(..., ge=0, le=25, description="上次 25 分制总分。")
    dimension_comments: dict[str, str] = Field(
        default_factory=dict,
        description="按 rubric 维度键索引的中文评语（structural_judgment 等）。",
    )
    top_issues: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="上次 reviewer 标出的最大问题列表；超 5 条直接 422。",
    )


class AgentAskRequest(BaseModel):
    """POST /api/agent/ask 请求体。

    BYOK 原则：``api_key`` 由调用方显式携带，服务端不落盘。
    ``provider`` 默认 DeepSeek（ADR-002 v2 选定的默认 provider）。
    """

    question: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="用户问题；空串与过长输入都会在 Pydantic 层直接 422。",
    )
    book_session_id: str = Field(
        ...,
        min_length=1,
        description="Book session 标识，由 load_book 或 smoke test 创建。",
    )
    provider: Literal["deepseek", "anthropic"] = Field(
        default="deepseek",
        description="LLM provider：'deepseek'（默认）/ 'anthropic'。",
    )
    api_key: str = Field(
        ...,
        min_length=8,
        description="BYOK API key；服务端不持久化。",
    )
    model: str | None = Field(
        default=None,
        description=(
            "覆盖默认 model（可选）。不传时由 provider 决定默认值："
            "deepseek -> deepseek-v4-flash；anthropic -> claude-opus-4-8。"
        ),
    )
    base_url: str | None = Field(
        default=None,
        description=(
            "OpenAI 兼容 endpoint 覆盖（可选）。deepseek 走代理 / 私有部署 / "
            "其他 OpenAI 兼容 endpoint 时可覆盖；anthropic 忽略此字段。"
        ),
    )
    previous_review: PreviousReviewHint | None = Field(
        default=None,
        description=(
            "上一次答这道题时 reviewer 给的批评摘要。重答按钮按下时由 FE 带回，"
            "routes 层会拼成 system prompt 追加段注入 generator，让它知道"
            "上次哪几维没答好——不再重复同样的失误。字段缺失 / 格式异常时"
            "routes 层 fallback 跳过注入不崩。"
        ),
    )
    conversation_id: str | None = Field(
        default=None,
        description=(
            "追问用的对话标识（ADR-009 Phase 1a）。不传 = 开一场新对话，"
            "服务端生成 id 并在响应里回显；传了 = 接着这场对话往下问，"
            "服务端读上一轮的答案和引用拼成前情提要注入这一轮。"
            "对话从属于书，``book_session_id`` 照旧必填。"
            "和 ``previous_review`` 语义不冲突：重答是同一问重跑，"
            "追问是接着问下一问，两者可以并存。"
        ),
    )


class ReviewDimensionScore(BaseModel):
    """单个评分维度的分数 + 一句话评语。

    分数取 0-5：5 分制对齐 ``reviewer_rubric_v1.md``（rubric 实际是 1-5，
    取 0 仅作 reviewer 失败兜底时的默认值占位，业务流程不会写入 0）。
    """

    score: int = Field(..., ge=0, le=5, description="0-5 整数分；rubric 实际 1-5。")
    comment: str = Field(default="", description="reviewer 给出的一句话评语。")


class Review(BaseModel):
    """user-facing reviewer 评分结果（Sprint 5.5 BE）。

    把 ``bookscope.agent.reviewer.review_answer`` 的原始 dict 映射成
    前端易消费的扁平结构：

    - ``overall_score``：5 维 × 5 分 = 25 分制总分。
    - ``dimensions``：键为 rubric 五个维度（``structural_judgment`` /
      ``evidence_density`` / ``honesty`` / ``actionability`` /
      ``cross_chapter_coherence``），值为 ``ReviewDimensionScore``。
    - ``suggest_redo``：``overall_score < 18`` 时为 ``True``——阈值取
      "5 维平均 3.6/5 以下"作"答复对作家不够顶用、值得带更厚证据重答"
      的提示线，让前端显示"要不要带更厚证据重答"按钮。
    """

    overall_score: int = Field(..., ge=0, le=25, description="25 分制总分。")
    dimensions: dict[str, ReviewDimensionScore] = Field(
        default_factory=dict,
        description="按维度名索引的 5 分制评分 + 评语。",
    )
    overall_comment: str = Field(
        default="",
        description="reviewer 给出的总评（``overall`` 字段，2-4 句话）。",
    )
    top_issues: list[str] = Field(
        default_factory=list,
        description="reviewer 标的最大问题列表。",
    )
    suggest_redo: bool = Field(
        default=False,
        description="overall_score < 18 时建议作家带更厚证据重答。",
    )


class AgentAskResponse(BaseModel):
    """POST /api/agent/ask 响应体。"""

    answer: str = Field(..., description="agent 综合作答。")
    citations: list[dict] = Field(
        default_factory=list,
        description=(
            "原文引用列表；每条至少含 chapter(int) + snippet(str)。"
            "由 AgentLoop 在 loop 层强制校验，缺失会在上游抛 LLMFormatError。"
        ),
    )
    trace: dict = Field(
        default_factory=dict,
        description="LoopTrace 的 dict 化产物；用于可观测性与前端调试。",
    )
    book_session_id: str = Field(
        ...,
        description="回显请求里的 book_session_id，便于前端关联会话。",
    )
    conversation_id: str = Field(
        ...,
        description=(
            "本轮所属对话的标识（ADR-009 Phase 1a）。请求传了就原样回显，"
            "没传（开新对话）就回服务端新生成的 id——FE 拿到后存下来，"
            "下一问带回来就能接着追问。"
        ),
    )
    turn_index: int = Field(
        ...,
        ge=1,
        description=(
            "本轮是这场对话的第几问，从 1 起（ADR-009 Phase 1a）。"
            "追问递增；重答（``previous_review``）是同一问重跑，turn_index 不增。"
        ),
    )
    review: Review | None = Field(
        default=None,
        description=(
            "reviewer agent 评分（Sprint 5.5 BE）。"
            "reviewer 调失败 / 解析失败时为 ``None``，不阻断主 ask 流程。"
        ),
    )
    protocol_version: Literal["r1", "r2"] = Field(
        default="r1",
        description=(
            "本次 ask 走的 AgentLoop 协议代际（ADR-007 D-4 / D-5）。"
            "``r1`` = Anthropic tool_use 主格式；``r2`` = OpenAI function "
            "calling 主格式。由 env ``BOOKSCOPE_AGENT_PROTOCOL`` 决定，"
            "默认 ``r1`` 保向后兼容。后续 batch 归档 + case-study 引文脚本"
            "按本字段分支处理。"
        ),
    )
    route_type: Literal[
        "fast_general",
        "fast_review",
        "fast_summary",
        "fast_rating",
        "agent_loop",
        "long_context",
    ] = Field(
        default="agent_loop",
        description=(
            "本次 ask 命中的路由类型——通识 / 评论 / 摘要 / 评分 / 深度。"
            "fast_path 兜底回 agent_loop 时落 ``agent_loop``。FE 拿到后做"
            "路由可视化提示（与 SSE ``RouteDecisionEvent`` 同语义，给同步"
            "调用方一份等价信息）。默认 ``agent_loop`` 保向后兼容。"
        ),
    )


class CharacterGraphRequest(BaseModel):
    """POST /api/agent/character-graph 请求体（WP-character-graph）。

    BYOK 同 AgentAskRequest——抽图也要调 LLM（长上下文整本进 context）。
    """

    book_session_id: str = Field(
        ..., min_length=1, description="Book session 标识。"
    )
    unit: Literal["person", "concept"] = Field(
        default="person",
        description=(
            "分析单位：'person' 抽人物关系图（小说/历史，默认）、"
            "'concept' 抽概念关系图（理论书，exp-014 GO 的跨题材投影）。"
        ),
    )
    provider: Literal["deepseek", "anthropic"] = Field(
        default="deepseek", description="LLM provider。"
    )
    api_key: str = Field(..., min_length=8, description="BYOK API key；服务端不持久化。")
    model: str | None = Field(default=None, description="覆盖默认 model（可选）。")
    base_url: str | None = Field(
        default=None, description="OpenAI 兼容 endpoint 覆盖（可选）。"
    )


class GraphEdge(BaseModel):
    """人物关系图的一条边。

    ``evidence`` 是证明这条关系的原文片段；``verified`` 由 ``verify_citations``
    比对全书 chunk 得到；``chapter`` 是命中 chunk 的真章号（章号纠偏，不信模型自报）。
    """

    source: str = Field(..., description="关系起点人物名。")
    target: str = Field(..., description="关系终点人物名。")
    relation: str = Field(..., description="关系类型（君臣/政敌/父子/同盟等）。")
    strength: int = Field(
        default=3,
        ge=1,
        le=5,
        description="关系亲疏强度 1-5（5=最紧密，如父子/生死同盟；1=最疏远）。布局据此调远近粗细。",
    )
    evidence: str = Field(default="", description="证明这条关系的原文逐字片段。")
    verified: bool = Field(
        default=False, description="evidence 是否在原文里比对命中。"
    )
    chapter: int = Field(
        default=0, ge=0, description="命中 chunk 的真章号；未命中/未知为 0。"
    )
    match_score: float = Field(default=0.0, description="证据匹配分（0-1）。")
    polarity: str | None = Field(
        default=None,
        description="关系极性 友 / 敌 / 中,后端据原文判(章脉 v2 每章 valence 聚合的综合敌友)。"
        "缺 = 旧数据(v1),前端回落 relationKind 正则(保守)。",
    )


class CharacterGraphResponse(BaseModel):
    """POST /api/agent/character-graph 响应体。"""

    nodes: list[str] = Field(
        default_factory=list, description="人物名列表（图节点）。"
    )
    edges: list[GraphEdge] = Field(
        default_factory=list, description="关系列表（图的边），每条带原文出处。"
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="抽取元信息：duration_ms / input_tokens / output_tokens / "
        "verified_edges / total_edges。",
    )


class CharacterFlowRequest(BaseModel):
    """POST /api/agent/character-flow 请求体（WP-character-narrative-flow）。

    BYOK 同 CharacterGraphRequest——抽逐章同场结构也要调 LLM（整本进 context）。
    """

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    provider: Literal["deepseek", "anthropic"] = Field(
        default="deepseek", description="LLM provider。"
    )
    api_key: str = Field(..., min_length=8, description="BYOK API key；服务端不持久化。")
    model: str | None = Field(default=None, description="覆盖默认 model（可选）。")
    base_url: str | None = Field(
        default=None, description="OpenAI 兼容 endpoint 覆盖（可选）。"
    )


class CharacterFlowResponse(BaseModel):
    """POST /api/agent/character-flow 响应体。

    ``chapters`` 是逐章同场结构，给前端画 storyline（横轴章节、每人一条横线、同场聚束）：
    每章一条 ``{chapter, present, pairs}``，``present`` 是这章登场的主要人物名，
    ``pairs`` 是这章同场互动的人物对，每对 ``{a, b, evidence, verified, match_score,
    chapter}``——``evidence`` 过原文核验，``verified=false`` 的同场对留着但前端标灰
    （evidence-first：核不过的不进束）。
    """

    chapters: list[dict] = Field(
        default_factory=list,
        description=(
            "逐章同场结构，按章号排序。每条 {chapter:int, present:[人名], "
            "pairs:[{a, b, evidence, verified, match_score, chapter}]}；"
            "pair 的 evidence 过原文核验，verified=false 的标灰。"
        ),
    )
    scanned: bool = Field(
        default=False,
        description="是否成功抽取。false=失败/书太大，前端提示重试；区别于扫过但空（scanned=true、空列表）。",
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class SubplotWeaveRequest(BaseModel):
    """POST /api/agent/subplot-weave 请求体（支线编织图，WP-subplot-weave，probe GO）。

    BYOK 同 CharacterFlowRequest——抽支线 + 逐章活跃 + 交汇也要调 LLM（整本进 context）。
    """

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    provider: Literal["deepseek", "anthropic"] = Field(
        default="deepseek", description="LLM provider。"
    )
    api_key: str = Field(..., min_length=8, description="BYOK API key；服务端不持久化。")
    model: str | None = Field(default=None, description="覆盖默认 model（可选）。")
    base_url: str | None = Field(
        default=None, description="OpenAI 兼容 endpoint 覆盖（可选）。"
    )


class SubplotWeaveResponse(BaseModel):
    """POST /api/agent/subplot-weave 响应体。

    给前端画 braided narrative：每条支线一条横向泳道（``active_chapters`` 决定哪几章亮
    实心点睛色、其余休眠灰断），两条支线同章交汇画一个连接节点。两组证据处理不同：

    - ``subplots``：保留全部，``verified=false`` 的整条泳道前端淡化（支线判定是主观构念，
      存在性描述留给读者自己核，不剔）。
    - ``intersections``：BE 已双端 verify-filter（两条 evidence 都核验命中才保留），列表里
      全是双端 verified——交汇是最易编的部分，一条腿站不住的不画（命根子，probe 守住的）。
    """

    subplots: list[dict] = Field(
        default_factory=list,
        description=(
            "情节支线列表（含主线）。每条 {name:str, active_chapters:[int], evidence:str, "
            "verified:bool, match_score:float}；active_chapters 是这条支线活跃的章号（升序），"
            "evidence 过原文核验，verified=false 的前端淡化（不剔）。"
        ),
    )
    intersections: list[dict] = Field(
        default_factory=list,
        description=(
            "支线交汇点，按章号排序。每条 {subplots:[name,name], chapter:int, "
            "a_evidence:str, b_evidence:str, a_verified:bool, b_verified:bool, "
            "a_match_score:float, b_match_score:float}；BE 已双端 verify-filter，"
            "全部 a_verified+b_verified（两端原文都核验命中才画交汇）。"
        ),
    )
    scanned: bool = Field(
        default=False,
        description="是否成功抽取。false=失败/书太大，前端提示重试；区别于扫过但空（scanned=true、空列表）。",
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class CheckCitationsRequest(BaseModel):
    """POST /api/agent/check-citations 请求体（claim precision，exp-015 GO）。

    答完后前端自动带回答案 + 引用，核每条引用撑不撑得起答案的论述。BYOK。
    """

    answer: str = Field(..., min_length=1, description="答案全文（当论断上下文）。")
    citations: list[dict] = Field(
        default_factory=list,
        description="引用列表，每条至少含 snippet + match_type。",
    )
    provider: Literal["deepseek", "anthropic"] = Field(default="deepseek")
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class CheckCitationsResponse(BaseModel):
    """POST /api/agent/check-citations 响应体。"""

    citations: list[dict] = Field(
        default_factory=list,
        description="每条引用附加 claim_support（supported / weak / unchecked）。",
    )


class SuggestQuestionsRequest(BaseModel):
    """POST /api/agent/suggest-questions 请求体（每书自动出诊断题）。

    据整本书内容出书内专属诊断题。BYOK。
    """

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    provider: Literal["deepseek", "anthropic"] = Field(default="deepseek")
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class SuggestQuestionsResponse(BaseModel):
    """POST /api/agent/suggest-questions 响应体。"""

    questions: list[dict] = Field(
        default_factory=list,
        description="书内专属诊断题，每条 {type, question}。type 为发明区诊断五类之一。",
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class GenreDetectRequest(BaseModel):
    """POST /api/agent/detect-genre 请求体（选书时主动测一次题材）。

    一次轻 LLM 调用判书的题材，结果缓存进 session metadata，前端据此决定 nav 显隐
    （小说藏"论点结构"、理论书藏"人物弧线"）。重复调用直接命中缓存不再花钱。BYOK。
    """

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    provider: Literal["deepseek", "anthropic"] = Field(default="deepseek")
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class GenreDetectResponse(BaseModel):
    """POST /api/agent/detect-genre 响应体。"""

    genre: str = Field(
        default="",
        description=(
            "封闭集 {小说/历史/理论/论文/公文/会议/诗歌/工具书/其他} 里的题材词；"
            "测不出退空串（前端按未分类全显）。"
        ),
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")


class BookModeRequest(BaseModel):
    """POST /api/agent/detect-mode 请求体（选书时判一次叙事型 / 论述型）。

    比题材细一维、按内容判（exp035）：分开叙事型历史（明朝→人物镜头）和论述型历史
    （安史 / 经济制裁→思想镜头），前端据此只上对应一套镜头、不再两套重叠。清晰题材直接映射、
    只含糊的（历史 / 传记）才真调 LLM。重复调命中缓存。BYOK。
    """

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    provider: Literal["deepseek", "anthropic"] = Field(default="deepseek")
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class BookModeResponse(BaseModel):
    """POST /api/agent/detect-mode 响应体。"""

    mode: str = Field(
        default="",
        description=(
            "narrative（叙事型：人物 / 情节推进）或 discursive（论述型：论点 / 概念推进）；"
            "判不出退空串（前端按未判、维持题材默认）。"
        ),
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")


class PacingCurveRequest(BaseModel):
    """POST /api/agent/pacing-curve 请求体（节奏曲线可视化，exp-012 GO）。

    据整本书逐章判张力，出可视化曲线。BYOK。
    """

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    provider: Literal["deepseek", "anthropic"] = Field(default="deepseek")
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class PacingCurveResponse(BaseModel):
    """POST /api/agent/pacing-curve 响应体。"""

    points: list[dict] = Field(
        default_factory=list,
        description="逐章张力点，每条 {chapter, tension(1-5), note}，按章号排序。",
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class NarrativeCurveRequest(BaseModel):
    """POST /api/agent/narrative-curve 请求体（多维叙事曲线，WP-multidim-narrative-curve）。

    据整本书逐章抽张力 + 情感方向 + 主导 POV + 主/支线，出多维曲线。BYOK。
    """

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    provider: Literal["deepseek", "anthropic"] = Field(
        default="deepseek", description="LLM provider。"
    )
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class NarrativeCurveResponse(BaseModel):
    """POST /api/agent/narrative-curve 响应体（1.5.x 重做：纵轴换成能数的事，非张力标量）。

    ``chapters`` 是逐章事件密度结构：每章高度 = ``event_count + turning_count``，都是从
    章脉 events / 伏笔回收数出来、每条能锚原文的；``is_turning`` 标转折章（朱砂点）。前端点
    一章列出 ``events`` / ``turning_points``（各条带 evidence + verified，evidence-first：核
    不过的标"待核"）。``tension`` 等四维仍带回，但只进选中章明细标"模型判读"，不当纵轴。
    """

    chapters: list[dict] = Field(
        default_factory=list,
        description=(
            "逐章事件密度结构，按章号排序。每条 {chapter:int, event_count:int, "
            "turning_count:int, height:int(=event+turning), is_turning:bool, "
            "events:[{text, evidence, verified}], "
            "turning_points:[{hook, kind, evidence, verified}], "
            "tension:0-10, sentiment:-5..5, pov:str, mainline:bool, "
            "evidence:str(章代表句兜底), verified:bool, match_score:float}。"
            "events/turning_points 每条 evidence 过原文核验，verified=false 的标待核。"
        ),
    )
    scanned: bool = Field(
        default=False,
        description="是否成功抽取。false=失败/书太大，前端提示重试；区别于扫过但空（scanned=true、空列表）。",
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class PrewarmSpineRequest(BaseModel):
    """POST /api/agent/prewarm-spine 请求体（性能 Lever B 后端：进分析台就后台预建章脉）。

    超长文第一次建章脉要整本 map-reduce（可能十几分钟）。一进分析台先打这个端点，
    后台线程里预建、立刻返回；建好后所有整本书功能命中缓存秒出。body 跟别的整本书端点
    一致（BYOK）。不带 genre——服务端固定用 fiction，跟叙事曲线/关系图/节奏/时间线等
    默认整本书功能同一条 spine 缓存键，预建的正好是它们要的那条。
    """

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    provider: Literal["deepseek", "anthropic"] = Field(
        default="deepseek", description="LLM provider。"
    )
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class PrewarmSpineResponse(BaseModel):
    """POST /api/agent/prewarm-spine 响应体：立刻返回，不等构建。

    ``status``：``cached`` 已缓存（不用建）；``building`` 已有一路在建（幂等，不重复起）；
    ``started`` 本次刚起后台建。前端据此决定是否轮询 status 端点。
    """

    status: Literal["cached", "building", "started"] = Field(
        ..., description="cached=已缓存无需建；building=已在建；started=本次刚起后台建。"
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")


class BookReportRequest(BaseModel):
    """POST /api/agent/book/report 请求体：出书鉴报告。

    只读章脉缓存，章脉没建过不主动建（返回 404 提示先跑分析 / 预建章脉）。
    body 与整本书端点一致（BYOK）；genre 服务端固定 fiction（与整本书功能同一条 spine 缓存键）。
    """

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    provider: Literal["deepseek", "anthropic"] = Field(
        default="deepseek", description="LLM provider。"
    )
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class CrossBookReportRequest(BaseModel):
    """POST /api/agent/cross-book/report 请求体：多本书 / 文档簇对照报告。

    每本从章脉提炼书级主张（轻 LLM），再做一次跨文本对照推理，出书鉴对照报告。
    章脉未全建的书返回 409 + 进度提示（先预建/等后台补建）。
    """

    book_session_ids: list[str] = Field(
        ..., min_length=2, description="至少两本书的 session_id（顺序即对照顺序）。"
    )
    provider: Literal["deepseek", "anthropic"] = Field(
        default="deepseek", description="LLM provider。"
    )
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class CrossBookAskRequest(BaseModel):
    """POST /api/agent/cross-book/ask 请求体：对照报告内追问。

    在多书观点骨架 + 已有对照结论上回答，不重读全文。
    """

    book_session_ids: list[str] = Field(
        ..., min_length=2, description="至少两本书的 session_id（与对照报告一致）。"
    )
    question: str = Field(..., min_length=1, max_length=2000, description="用户问题。")
    provider: Literal["deepseek", "anthropic"] = Field(
        default="deepseek", description="LLM provider。"
    )
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class CrossBookAskResponse(BaseModel):
    """POST /api/agent/cross-book/ask 响应体。"""

    answer: str = Field(..., description="跨文本对照回答。")
    sources: list[str] = Field(default_factory=list, description="来源（书名/章号）。")


class PrewarmSpineStatusResponse(BaseModel):
    """GET /api/agent/prewarm-spine/status 响应体：轮询后台预建进度。

    ``idle`` 没建过也不在建；``building`` 后台正在建；``done`` 建好（缓存已就绪，
    整本书功能会命中）；``error`` 后台建失败（``error`` 带原因）。``chapters`` 只在
    done 时给章数。
    """

    status: Literal["idle", "building", "done", "error"] = Field(
        ..., description="idle=未建/不在建；building=在建；done=建好缓存就绪；error=建失败。"
    )
    chapters: int | None = Field(
        default=None, description="done 时的章脉章数；其它状态为 null。"
    )
    built_chapters: int = Field(
        default=0, description="已建成的章数（渐进：building 中也实时可读）。"
    )
    total_chapters: int = Field(
        default=0, description="全书总章数（渐进：building 中也实时可读）。"
    )
    error: str | None = Field(
        default=None, description="error 时的失败原因（type: message）；其它状态为 null。"
    )


class SpineEvidenceRequest(BaseModel):
    """POST /api/agent/spine-evidence 请求体（章脉章级锚视图"点开现取"那一句，ADR-010 出路 B）。

    关系图边 / 时间线事件这类章级锚视图不带 upfront 逐字证据，用户点开某条时调本端点，从那一章
    原文里现找支撑句。纯检索、不调 LLM、不要 api_key——是数据端点不是分析端点。
    """

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    chapter: int = Field(..., ge=1, description="这条边/事件锚定的真章号。")
    kind: Literal["pair", "event"] = Field(
        ..., description="pair=关系边(传 a/b)；event=事件(传 event)。"
    )
    a: str | None = Field(default=None, description="kind=pair 时人物 A。")
    b: str | None = Field(default=None, description="kind=pair 时人物 B。")
    event: str | None = Field(default=None, description="kind=event 时事件描述。")


class SpineEvidenceResponse(BaseModel):
    """POST /api/agent/spine-evidence 响应体。"""

    chapter: int = Field(..., description="回显章号。")
    evidence: str = Field(default="", description="从该章原文找到的支撑句；没找到返空串。")
    found: bool = Field(
        default=False, description="是否在该章找到支撑原文（evidence-first：没找到不编）。"
    )


class ForeshadowArcsRequest(BaseModel):
    """POST /api/agent/foreshadow-arcs 请求体（伏笔→回收弧线图，WP-foreshadow-payoff-arcs）。

    据整本书抽每条伏笔的埋点章 + 回收点章 + 两端原文，给前端画跨章 arc diagram。BYOK。
    """

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    provider: Literal["deepseek", "anthropic"] = Field(
        default="deepseek", description="LLM provider。"
    )
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class ForeshadowArcsResponse(BaseModel):
    """POST /api/agent/foreshadow-arcs 响应体。

    ``arcs`` 是每条伏笔的埋点→回收配对，给前端画跨章弧线图：每条
    ``{description, setup_chapter, payoff_chapter|null, setup_evidence, payoff_evidence,
    status, setup_verified, payoff_verified, setup_match_score, payoff_match_score}``——
    ``status="resolved"`` = 已回收实弧（两端都挂上原文）；``status="dangling"`` = 断弧
    （埋了没回收，回收端 ``payoff_chapter`` 为 null、前端画灰虚线悬空）。埋点核不过的弧
    已在 BE 滤掉（evidence-first：挂不上原文的伏笔不画）。
    """

    arcs: list[dict] = Field(
        default_factory=list,
        description=(
            "逐条伏笔弧，按 setup_chapter 排序。每条 {description:str, "
            "setup_chapter:int, payoff_chapter:int|null, setup_evidence:str, "
            "payoff_evidence:str, status:'resolved'|'dangling', setup_verified:bool, "
            "payoff_verified:bool, setup_match_score:float, payoff_match_score:float}；"
            "两端 evidence 过原文核验，status=dangling 是断弧（埋了没回收）。"
        ),
    )
    scanned: bool = Field(
        default=False,
        description="是否成功抽取。false=失败/书太大，前端提示重试；区别于扫过但空（scanned=true、空列表）。",
    )
    confirmed_none: bool = Field(
        default=False,
        description=(
            "空值三态（task #29 根一）：是否**确证全书没有伏笔**——扫过全书（scanned=true）且"
            "没抽出挂得上原文的伏笔弧。true 时前端笃定显示「全书没埋伏笔」，区别于 "
            "scanned=false 的「扫失败 / 待核」。注意：单条弧的 status=dangling（埋了没回收）是"
            "另一层确证（这条伏笔确证未回收），由各弧自己带，不归这个列表级字段。"
        ),
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class CharacterArcRequest(BaseModel):
    """POST /api/agent/character-arc 请求体（戏份/人物弧线曲线，WP-character-arc-curves）。

    据整本书给主要角色逐章抽戏份密度 + 处境弧线，出可视化曲线。BYOK，同 NarrativeCurveRequest。
    """

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    provider: Literal["deepseek", "anthropic"] = Field(
        default="deepseek", description="LLM provider。"
    )
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class CharacterArcResponse(BaseModel):
    """POST /api/agent/character-arc 响应体。

    ``characters`` 是 per 角色的逐章弧线，给前端画"谁何时主导（戏份密度）+ 谁过得顺不顺
    （处境弧线）"两条曲线：每个角色一条 ``{name, points}``，``points`` 是逐章数值点
    ``[{chapter, presence(0-10), fortune(-5..5), evidence, verified, match_score}]``——
    ``evidence`` 过原文核验，``verified=false`` 的点前端标低置信/淡化（evidence-first：
    核不过的不当确定结论画）。把已验过的 exp-010 弧线分析画成可核验的曲线，不重造判定。
    """

    characters: list[dict] = Field(
        default_factory=list,
        description=(
            "per 角色逐章弧线。每条 {name:str, points:[{chapter:int, presence:0-10, "
            "fortune:-5..5, note:str（处境一句话·具体发生了什么·可空）, evidence:str, "
            "verified:bool, match_score:float}]}；point 的 evidence 过原文核验，"
            "verified=false 的标低置信。"
        ),
    )
    scanned: bool = Field(
        default=False,
        description="是否成功抽取。false=失败/书太大，前端提示重试；区别于扫过但空（scanned=true、空列表）。",
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class NarrativePhasesRequest(BaseModel):
    """POST /api/agent/narrative-phases 请求体（情节脉络·阶段划分，WP-narrative-phases）。"""

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    provider: Literal["deepseek", "anthropic"] = Field(
        default="deepseek", description="LLM provider。"
    )
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class NarrativePhasesResponse(BaseModel):
    """POST /api/agent/narrative-phases 响应体。

    ``book_type`` 叙事型 / 论述型;只有叙事型才切阶段(论述型 phases 为空、前端不显阶段)。
    每个 phase 的代表事件 evidence 过原文核验(verified=false 标灰,evidence-first)。
    """

    book_type: str = Field(default="", description="叙事型 / 论述型;论述型不切阶段。")
    phases: list[dict] = Field(
        default_factory=list,
        description="阶段 {name,start_ch,end_ch,gist,evidence,verified,match_score};论述型空。",
    )
    scanned: bool = Field(default=False, description="是否成功抽取；false=失败 / 书太大。")
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(default_factory=dict, description="运行用量 trace。")


class CharacterVoiceRequest(BaseModel):
    """POST /api/agent/character-voice 请求体（声口一致，WP-character-voice）。

    给一个角色，整本进 context 归拢其对白、刻画语言特征、标 voice drift。
    BYOK，同 CharacterArcRequest——多一个 ``character`` 入参指定分析哪个角色。
    """

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    character: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="要分析声口的角色名（可复用人物图抽出的节点）。",
    )
    provider: Literal["deepseek", "anthropic"] = Field(
        default="deepseek", description="LLM provider。"
    )
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class CharacterVoiceResponse(BaseModel):
    """POST /api/agent/character-voice 响应体。

    给前端画一张「X 的声口」面板：上半语言特征（每条挂代表对白），下半 voice drift
    提示（每条挂那句对白 + 章 + 一句为什么不像，点开看原文核验）。两部分证据处理不同：

    - ``features``：保留全部，``verified=false`` 的前端淡化（evidence-first：核不过的
      不当确定结论，但描述性特征留给读者自己核）。
    - ``drift_items``：BE 已 verify-filter（核不过的整条丢），列表里全是 verified——
      挂不上原文的 drift 是工具一面之词，不报，免得 cry wolf。
    - ``sample_too_small``：角色全书对白太少、不够刻画稳定腔调时为 true，前端明说
      样本不足、不硬下 drift 判定（命根子，probe 守住的）。
    """

    character: str = Field(..., description="回显请求里的角色名。")
    sample_too_small: bool = Field(
        default=False,
        description="该角色对白太少、不够刻画稳定声口时为 true，前端提示样本不足。",
    )
    features: list[dict] = Field(
        default_factory=list,
        description=(
            "语言特征，每条 {trait:str, evidence:str, verified:bool, match_score:float, "
            "chapter:int}；evidence 过原文核验，verified=false 的前端淡化（不剔）。"
        ),
    )
    drift_items: list[dict] = Field(
        default_factory=list,
        description=(
            "voice drift 提示，每条 {chapter:int, quote:str, reason:str, verified:bool, "
            "match_score:float}，按章号排序。BE 已 verify-filter，全部 verified——"
            "核不过的不报（这是提示不是定论，作家自己判断）。"
        ),
    )
    scanned: bool = Field(
        default=False,
        description=(
            "是否成功分析。false=失败/书太大，前端提示重试；"
            "区别于分析过但声口很稳（scanned=true、drift 空列表）。"
        ),
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class CharacterStanceRequest(BaseModel):
    """POST /api/agent/character-stance 请求体（立场判定 Toulmin，probe exp024 GO）。

    给一个角色 + 一条**可配的立场轴**（``pos_label`` ↔ ``neg_label``），整本进 context
    正反取证 + 综合倾向 + 争议度。轴由调用方按书给（三国 = 尊汉扶主 / 篡逆自立，
    安史 = 忠唐 / 附燕，别的书换别的）——此端点不认死某条轴。BYOK 同 CharacterVoiceRequest。
    """

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    character: str = Field(
        ..., min_length=1, max_length=100, description="要判立场的角色名（可复用人物图节点）。"
    )
    pos_label: str = Field(
        ..., min_length=1, max_length=40, description="立场轴正端（如 尊汉扶主）。"
    )
    neg_label: str = Field(
        ..., min_length=1, max_length=40, description="立场轴负端（如 篡逆自立）。"
    )
    provider: Literal["deepseek", "anthropic"] = Field(
        default="deepseek", description="LLM provider。"
    )
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class CharacterStanceResponse(BaseModel):
    """POST /api/agent/character-stance 响应体（Toulmin：正据 + 反据 + 倾向 + 争议度）。

    争议判断两方并陈、让读者自己看，不藏在一个确定分后头（evidence-first 机制层，
    对治"曹操是否尊汉压成 -4 + 单句"那种拍脑袋 + 假精确 + 单证据）。前端画争议象限时：
    ``dispute`` 高的不画笃定点（带不确定 + "争"标），点开看 ``pro`` / ``con`` 两栏。
    """

    character: str = Field(..., description="回显请求里的角色名。")
    pos: str = Field(default="", description="回显立场轴正端。")
    neg: str = Field(default="", description="回显立场轴负端。")
    pro: list[dict] = Field(
        default_factory=list,
        description="偏正端的证据，每条 {原文:str, 说明:str, verified:bool}；原文过核验。",
    )
    con: list[dict] = Field(
        default_factory=list, description="偏负端的证据，同 pro 结构。"
    )
    net: int = Field(default=0, description="综合倾向 -5（偏 neg）..0..+5（偏 pos）。")
    dispute: int = Field(
        default=0, description="争议度 0-5：正反两方都有硬证据、真两难时才高。"
    )
    dispute_reason: str = Field(default="", description="争议度的一句理由。")
    scanned: bool = Field(
        default=False, description="是否成功判定；false=失败/书太大，前端提示重试。"
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class SuggestStanceAxisRequest(BaseModel):
    """POST /api/agent/suggest-stance-axis 请求体（按书建议一对立场轴标签）。

    人物志立场象限的轴不写死三国的「尊汉扶主 / 篡逆自立」——拿书的节选让 LLM 判这本书
    围绕的核心立场 / 阵营对立，给一对默认标签（用户仍可改）。字段同 CharacterStanceRequest
    的 BYOK 部分，不带 character / pos_label / neg_label——轴正是这里要建议的。
    """

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    provider: Literal["deepseek", "anthropic"] = Field(
        default="deepseek", description="LLM provider。"
    )
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class SuggestStanceAxisResponse(BaseModel):
    """POST /api/agent/suggest-stance-axis 响应体（建议的一对立场轴标签）。

    ``scanned=False`` 或 pos/neg 空 = 这本书判不出明显立场对立（工具书 / 诗集 / 纯理论），
    前端保持空、让用户自己填（evidence-first：判不出不硬造）。
    """

    pos: str = Field(
        default="", description="建议的立场轴正端（如 尊汉扶主 / 忠唐）；判不出为空。"
    )
    neg: str = Field(
        default="", description="建议的立场轴负端（如 篡逆自立 / 附燕）；判不出为空。"
    )
    scanned: bool = Field(
        default=False, description="是否给出建议；false=判不出/失败，前端保持空让用户填。"
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")


class BatchStanceRequest(BaseModel):
    """POST /api/agent/batch-stance 请求体（立场格局批量粗定位，probe exp032 GO）。

    一次把多个角色同时定位到可配立场轴（``pos_label`` ↔ ``neg_label``）上，每人给 net +
    dispute + 一句依据。立场格局主视图靠它一口气铺开全员；点开某人才跑 character-stance 的
    单人 Toulmin 详证。轴由调用方按书给（不认死某条轴）。BYOK 同 CharacterStanceRequest。
    """

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    characters: list[str] = Field(
        ...,
        min_length=1,
        max_length=60,
        description="要一次定位的角色名（前端取人物图节点里戏份最重的前若干个）。",
    )
    pos_label: str = Field(
        ..., min_length=1, max_length=40, description="立场轴正端（如 尊汉扶主）。"
    )
    neg_label: str = Field(
        ..., min_length=1, max_length=40, description="立场轴负端（如 篡逆自立）。"
    )
    provider: Literal["deepseek", "anthropic"] = Field(
        default="deepseek", description="LLM provider。"
    )
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class BatchStancePosition(BaseModel):
    """立场格局里一个人的粗定位（批量一次判：net 方向可信、dispute 是浅判）。"""

    name: str = Field(..., description="角色名。")
    net: int = Field(default=0, description="综合倾向 -5（偏 neg）..0..+5（偏 pos）。")
    dispute: int = Field(
        default=0, description="争议度 0-5（批量粗判，别当权威，真争议点开看 Toulmin）。"
    )
    brief: str = Field(default="", description="一句话依据。")


class BatchStanceResponse(BaseModel):
    """POST /api/agent/batch-stance 响应体（一批角色的立场粗定位）。

    ``scanned=False`` = 判不出 / 失败（前端不画象限、退回按需点人）。粗定位诚实：net 方向可信、
    dispute 是浅判——真争议由前端点开某人跑单人 Toulmin 显（evidence-first 机制层，对治把
    "曹操是否尊汉"这种千年争议在批量里压成一个确定分）。
    """

    positions: list[BatchStancePosition] = Field(
        default_factory=list, description="每个角色一项 {name, net, dispute, brief}。"
    )
    scanned: bool = Field(
        default=False, description="是否成功批量定位；false=失败/书太大，前端不画象限。"
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")


class ScholarStanceRequest(BaseModel):
    """POST /api/agent/scholar-stance 请求体（学者立场谱，理论书镜头，probe exp033 GO）。

    理论书跟哪些思想家对话、各自站在本书核心争论的哪一极。轴由模型据本书原文自己定
    （不像 character-stance 由调用方给轴）——所以没有 character / pos_label / neg_label
    字段，只带 BYOK 部分（同 SuggestStanceAxisRequest）。
    """

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    provider: Literal["deepseek", "anthropic"] = Field(
        default="deepseek", description="LLM provider。"
    )
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class ScholarStanceAxis(BaseModel):
    """本书核心争论轴：两极 + 依据（全用本书的话）。"""

    pole_a: str = Field(default="", description="争论轴一极（如 国家能力 / 计划）。")
    pole_b: str = Field(default="", description="争论轴另一极（如 市场自发 / 产权）。")
    from_book: str = Field(default="", description="这条轴的依据，用本书原话概括。")


class ScholarStancePosition(BaseModel):
    """谱上一个学者：立场位置 + 原文原句（过片段核验）。"""

    name: str = Field(..., description="学者 / 思想家名。")
    stance_stated: bool = Field(
        default=False, description="本书有没有明说 / 刻画其立场；false=只提名，不摆位置。"
    )
    pole: str = Field(default="", description="偏哪一极：a / b / 中；只提名为空。")
    position: int = Field(
        default=0,
        description="立场位置 -5（紧贴 pole_a）..0（中/只提名）..+5（紧贴 pole_b）。",
    )
    quote: str = Field(default="", description="本书里刻画其立场的原文原句；只提名为空。")
    quote_verified: bool = Field(
        default=False,
        description="原句按片段核过原书（evidence-first）；false=没锚上，前端标待核。",
    )
    mentions: int = Field(
        default=0,
        description="被本书提及次数（名 / 姓取大者）；十字轴横轴＝被讨论分量（核心↔边缘），可数。",
    )
    brief: str = Field(default="", description="一句话说明。")


class ScholarStanceResponse(BaseModel):
    """POST /api/agent/scholar-stance 响应体（学者立场谱）。

    ``scanned=False`` = 抽不出核心争论轴 / 有立场的学者不足 2 个（工具书 / 无学术对话的书），
    前端不画谱、不硬造（evidence-first，同 suggest-stance-axis 判不出返空的精神）。
    """

    axis: ScholarStanceAxis | None = Field(
        default=None, description="核心争论轴；判不出为 None。"
    )
    scholars: list[ScholarStancePosition] = Field(
        default_factory=list,
        description=(
            "谱上每个学者一项 {name, stance_stated, pole, position, quote, "
            "quote_verified, brief}。"
        ),
    )
    scanned: bool = Field(
        default=False, description="是否成功成谱；false=判不出/失败，前端不画谱。"
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class ArgumentTreeRequest(BaseModel):
    """POST /api/agent/argument-tree 请求体（论点结构骨架树，理论书镜头，probe exp034 GO）。

    把论点结构从平铺 claim 清单升成 中心论点 + 论点（逻辑角色 + 支撑关系）的论证树。中心论点
    与关系由模型据本书原文自己拆（同 scholar-stance），只带 BYOK 部分。
    """

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    provider: Literal["deepseek", "anthropic"] = Field(
        default="deepseek", description="LLM provider。"
    )
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class ArgumentTreeThesis(BaseModel):
    """全书中心论点（主脉）：作者最核心那句主张 + 原文原句（过核验）。"""

    claim: str = Field(default="", description="中心论点，用本书话概括。")
    quote: str = Field(default="", description="刻画中心论点的原文原句。")
    quote_verified: bool = Field(default=False, description="原句核过原书；false=前端标待核。")
    chapter: int = Field(default=0, description="命中章号；0=没锚上。")
    from_book: str = Field(default="", description="依据（本书原话）。")


class ArgumentTreeClaim(BaseModel):
    """论证树上一条论点：逻辑角色 + 撑谁（supports）+ 原文原句（过核验）。"""

    id: str = Field(..., description="论点 id（c1/c2/…），供 supports 互指。")
    claim: str = Field(..., description="论点，用本书话概括。")
    role: str = Field(
        default="支撑", description="逻辑角色：中心/前提/支撑/递进/反驳/论据/结论。"
    )
    supports: str = Field(
        default="thesis", description="它撑/反哪条：另一论点 id 或 thesis（直接撑中心论点）。"
    )
    quote: str = Field(default="", description="刻画它的原文原句。")
    quote_verified: bool = Field(default=False, description="原句核过原书；false=前端标待核。")
    chapter: int = Field(default=0, description="命中章号；0=没锚上。")
    brief: str = Field(default="", description="一句话说明。")


class ArgumentTreeResponse(BaseModel):
    """POST /api/agent/argument-tree 响应体（论证骨架树）。

    ``scanned=False`` = 非论说题材 / 抽不出中心论点 / 有效论点不足 2 条，前端不画树、不硬造
    （evidence-first，同平铺 argument-structure 的题材门控精神）。
    """

    thesis: ArgumentTreeThesis | None = Field(
        default=None, description="中心论点；判不出为 None。"
    )
    claims: list[ArgumentTreeClaim] = Field(
        default_factory=list, description="论证树的论点（带逻辑角色 + supports 关系）。"
    )
    scanned: bool = Field(default=False, description="是否成功成树；false=判不出/失败。")
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(default_factory=dict, description="运行用量 trace。")


class RelationshipTimelineRequest(BaseModel):
    """POST /api/agent/relationship-timeline 请求体（关系随时间演变，WP-relationship-over-time）。

    据整本书逐对主要关系抽逐章强度 + 关键转折，给关系图加一根时间轴。BYOK。
    """

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    provider: Literal["deepseek", "anthropic"] = Field(
        default="deepseek", description="LLM provider。"
    )
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)
    pair_a: str | None = Field(
        default=None,
        description="下钻：这对人的一方（canonical 名）。与 pair_b 同给才算这对编年。",
    )
    pair_b: str | None = Field(
        default=None,
        description="下钻：另一方。都不给则返全员对清单（总览，不算编年）。",
    )


class RelationshipTimelineResponse(BaseModel):
    """POST /api/agent/relationship-timeline 响应体（1.5.1 关系编年）。

    两种返法（与关系图协同：关系图=全员索引，这里=任一对按需下钻）：
    - 给了 ``pair_a``/``pair_b`` → ``relations`` 是这一对的**关系编年**（一条）：
      ``{a, b, verdict, beats}``。``verdict`` 是整体判断
      ``{essence, arc, asymmetric, view_a_on_b, view_b_on_a, sharp_point, pivot_chapter}``；
      ``beats`` 是逐幕编年 ``[{chapter, scene, state, valence(-5友..5敌), change,
      evidence, verified, match_score}]``，每幕 evidence 按这对人 + 这件事在原文里捞、过核验，
      ``verified=false`` 的前端标低置信/标待核（evidence-first：挂不上原文的不当确定结论画）。
    - 没给 pair → ``relations`` 空、``pairs`` 是便宜的全员对清单（不调 LLM）：
      ``[{a, b, chapters, first, last, count}]``，给概览/选择器，点一对再来取编年。
    """

    relations: list[dict] = Field(
        default_factory=list,
        description=(
            "下钻时这对人的关系编年（一条）：{a, b, verdict:{essence, arc, asymmetric, "
            "view_a_on_b, view_b_on_a, sharp_point, pivot_chapter}, "
            "beats:[{chapter, scene, state, valence, change, evidence, verified, match_score}]}。"
            "没下钻时为空。"
        ),
    )
    pairs: list[dict] = Field(
        default_factory=list,
        description=(
            "全员对清单（总览，没下钻时返）：[{a, b, chapters:[int], first, last, count}]，"
            "按互动章数降序。给前端做选择器/概览，覆盖全书所有有关系的对，点一对再取编年。"
        ),
    )
    scanned: bool = Field(
        default=False,
        description="是否成功抽取。false=失败/书太大，前端提示重试；区别于扫过但空（scanned=true、空列表）。",
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class ConsistencyScanRequest(BaseModel):
    """POST /api/agent/consistency-scan 请求体（设定一致性扫描，exp-011 GO）。

    扫全书找设定/人物前后矛盾。BYOK。
    """

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    provider: Literal["deepseek", "anthropic"] = Field(default="deepseek")
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class ConsistencyScanResponse(BaseModel):
    """POST /api/agent/consistency-scan 响应体。"""

    contradictions: list[dict] = Field(
        default_factory=list,
        description="前后矛盾列表，每条 {topic, conflict, a:{snippet,chapter,verified}, "
        "b:{...}}；两处证据都过原文核验。空 + scanned=true = 书自洽没扫出矛盾。",
    )
    scanned: bool = Field(
        default=False,
        description="是否成功扫描。true+空=自洽无矛盾；false=扫描失败/书太大，前端提示重试。",
    )
    confirmed_clean: bool = Field(
        default=False,
        description=(
            "空值三态（task #29 根一）：是否**确证无矛盾**——扫过全书（scanned=true）且没扫出"
            "矛盾。true 时前端正面笃定显示「全书自洽」（好消息），区别于 scanned=false 的"
            "「扫失败 / 待核」。evidence-first：只在真扫过全书 + 确实没矛盾时为 true。"
        ),
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


# ── 1.6 红头文件垂直(Phase 1)：单文件解读 + 三个跨文件视图 ──────────────────


class RedheadDocStructureRequest(BaseModel):
    """POST /api/agent/redhead/doc-structure 请求体（单份公文文脉解读）。

    一份公文 = 一个已有的 book session（用户照现有 /books/upload 各传一份公文）；
    这里收单个 book_session_id，建这份的文脉。BYOK，同其它整本结构化功能。
    """

    book_session_id: str = Field(..., min_length=1, description="Book session 标识（一份公文）。")
    provider: Literal["deepseek", "anthropic"] = Field(default="deepseek")
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)
    head_only: bool = Field(
        default=False,
        description=(
            "只要头要素骨架（公文结构鸟瞰），跳过贵的条款维 map-reduce。True=公文结构视图"
            "（秒出骨架：先 peek 缓存、没有才只建 head）；False=办事清单等需逐条款的视图"
            "（照旧建/取完整文脉含条款）。默认 False 向后兼容。"
        ),
    )


class RedheadDocStructureResponse(BaseModel):
    """POST /api/agent/redhead/doc-structure 响应体（一份公文的文脉）。"""

    structure_read: dict | None = Field(
        default=None,
        description=(
            "看结构（结构即信号）研判，文种判不出时缺省。{authority:{level,rank,doc_type,issuer,"
            "agency_level,appraisal,verified_basis…}, signals:[{kind,element,note}]}。权威刻度据"
            "文种+发文机关行政层级（agency_level：最高/高/中低，task #29 根二）判效力——最高/高"
            "层级（国务院/国办/部委/省级）点出全国/本系统约束，绝不说'容易被覆盖'；结构信号读"
            "缺席/排序/篇幅。评估层（研判，前端不盖鉴印）。"
        ),
    )
    head: list[dict] = Field(
        default_factory=list,
        description=(
            "文件头要素，固定 8 条（发文字号/文种/发文机关/主送机关/抄送机关/标题事由/"
            "成文日期/签发人）。每条 {field, value, evidence, verified, match_score, status, "
            "reason[, not_applicable]}；status 是空值三态（task #29 根一）：present=抽到了 / "
            "absent_confirmed=确证为无（带 reason，如公开件无密级、下行文无签发人栏、平件未标"
            "紧急、法规本体无发文要素，前端显笃定的'公开/无/不适用'）/ unverified=真没抽到"
            "（前端才显'待核'）。absent_confirmed 同时带 not_applicable=true（不计分母）。"
        ),
    )
    clauses: list[dict] = Field(
        default_factory=list,
        description=(
            "逐条款结构，按条款序号排。每条 {chapter, matter, instruction_type, actor, "
            "deadline, basis_ref, evidence, verified, match_score}；instruction_type 是"
            "带原文撑的四标签之一（硬要求/软倡导/信息告知/依据陈述），不是打分。"
        ),
    )
    scanned: bool = Field(
        default=False,
        description="是否成功精读。false=失败，前端提示重试；true+空 clauses=读过但没抽到条款。",
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class RedheadCrossDocRequest(BaseModel):
    """跨文件视图（依据链网 / 政策演变 / 上下级一致性）共用的请求体。

    「卷宗」= 客户端传一组 book_session_ids（每个是一份已上传的公文）。端点逐个 resolve
    assembler、建文脉，凑成一摞文脉再跑视图。政策演变可另带 topic，见子类。BYOK。
    """

    book_session_ids: list[str] = Field(
        ...,
        min_length=1,
        description="一组 book session 标识（一卷宗的多份公文）。",
    )
    provider: Literal["deepseek", "anthropic"] = Field(default="deepseek")
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class RedheadDependencyGraphResponse(BaseModel):
    """POST /api/agent/redhead/dependency-graph 响应体（依据链关联网）。"""

    nodes: list[dict] = Field(
        default_factory=list,
        description=(
            "节点：文件（字号）+ 机关。每条 {id, kind:'文件'|'机关', label, 文种, 机关, "
            "成文日期}，前端按 kind 分色。"
        ),
    )
    edges: list[dict] = Field(
        default_factory=list,
        description=(
            "有向边：{source, target, kind, chapter_anchor, note}。kind 是关系类型"
            "（依据/落实/废止/修改/上下级/发文）；chapter_anchor 是来源条款序号（可空，"
            "点开按需取证据）。"
        ),
    )
    scanned: bool = Field(
        default=False,
        description="是否成功推出关系网。false=失败/不足两份相关文件/没推出任何关系（空态）。",
    )
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class RedheadPolicyEvolutionRequest(RedheadCrossDocRequest):
    """POST /api/agent/redhead/policy-evolution 请求体。可另带政策主题。"""

    topic: str | None = Field(
        default=None,
        description="政策主题（可选）。空时按这摞文件整体的政策线排演变。",
    )


class RedheadPolicyEvolutionResponse(BaseModel):
    """POST /api/agent/redhead/policy-evolution 响应体（政策演变时间线）。"""

    stages: list[dict] = Field(
        default_factory=list,
        description=(
            "按成文日期排的演变阶段，每条 {order, doc, change, snippet, verified}。"
            "doc 是真实发文字号；snippet 取那份文脉某条款已核 evidence（锚不到原文的阶段被丢）。"
            "空 + scanned=true = 主题不在这摞文件。"
        ),
    )
    wording_diffs: list[dict] = Field(
        default_factory=list,
        description=(
            "措辞 diff（逐字比）：每条 {topic_point, before, before_doc, after, after_doc, "
            "direction(升格/松绑/收紧/转向/新增/删除), basis, verified}。before/after 原文逐字"
            "（只认逐字命中、转述丢）；direction 是方向研判。新闻在 delta 里,不在新增的话里。"
        ),
    )
    scanned: bool = Field(
        default=False,
        description="是否成功排演变。false=失败/没有可锚的真实文件；true+空=主题不在这摞文件。",
    )
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class RedheadLevelConsistencyResponse(BaseModel):
    """POST /api/agent/redhead/level-consistency 响应体（上下级一致性核查）。"""

    conflicts: list[dict] = Field(
        default_factory=list,
        description=(
            "上下级对不上的地方，每条 {topic, detail, deviation, upper:{doc, clause, snippet, "
            "verified}, lower:{...}}。deviation 是 走样/加码/漏落实 之一；两侧 snippet 都取"
            "各自文脉已核 evidence（任一侧坐实不了的整条丢，不 cry wolf）。"
        ),
    )
    scanned: bool = Field(
        default=False,
        description=(
            "是否成功核查。false=失败/这摞文件全平级或单文件（没上下级落差，题材自适应该掉）；"
            "true+空=都一致没扫出走样。"
        ),
    )
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class RedheadPlainLanguageRequest(RedheadDocStructureRequest):
    """POST /api/agent/redhead/plain-language 请求体。比单份解读多一个翻译模式。"""

    mode: Literal["clauses", "fulltext"] = Field(
        default="clauses",
        description="clauses=逐条款摘译(默认);fulltext=整篇逐句翻译(#22,通篇官话→白话)。",
    )


class RedheadPlainLanguageResponse(BaseModel):
    """POST /api/agent/redhead/plain-language 响应体（大白话翻译）。"""

    mode: str = Field(
        default="clauses",
        description="clauses=逐条款摘译 / fulltext=整篇逐句。前端按它选 item 形态。",
    )
    items: list[dict] = Field(
        default_factory=list,
        description=(
            "白话条目。clauses 每条 {chapter, matter, plain, evidence, verified, match_score};"
            "fulltext 每条 {seq, original, plain, evidence, verified, match_score}。两模式都可带"
            "可选 nuance=[{marker, meaning}]（命中措辞刻度才点弦外之意）。核的是原文不是白话。"
        ),
    )
    scanned: bool = Field(default=False, description="false=失败，前端提示重试。")
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(default_factory=dict, description="运行用量 trace。")


class RedheadCloseReadingResponse(BaseModel):
    """POST /api/agent/redhead/close-reading 响应体（逐条精读）。

    公文整合 centerpiece（设计稿 WP-redhead-consolidation 整合 1+2）：一条公文的三个切面合到
    一张卡——大白话 + 结构标签 + 内联术语 + 对原文，一个富视图替原来大白话 / 名词解释 / 公文结构
    条款三趟。从同一份文脉后端合成（不走前端三端点对齐）。
    """

    items: list[dict] = Field(
        default_factory=list,
        description=(
            "逐条精读条目，按条款序号排。每条 {chapter, matter, plain(大白话，改写失败退回 "
            "matter), structure:{instruction_type(硬要求/软倡导/方针部署/信息告知/依据陈述), "
            "actor, deadline, basis_ref}, glossary:[{term, explanation, context_meaning, "
            "policy_intent}]（内联术语，可空）, evidence(逐字原文), verified, match_score}；"
            "可带可选 nuance=[{marker, meaning}]（命中措辞刻度才点弦外之意）。结构标签直接取文脉"
            "条款骨架不重抽；内联术语核不过的不挂；核的是原文不是白话。"
        ),
    )
    scanned: bool = Field(
        default=False,
        description=(
            "false=失败/没拆出可逐条精读的正文（前端优雅退场）；true+空 items=读过但没条款。"
        ),
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(default_factory=dict, description="运行用量 trace。")


class RedheadRelevanceRequest(RedheadDocStructureRequest):
    """POST /api/agent/redhead/relevance 请求体（跟我相关）。比单份解读多一个身份。

    **已退役（1.6 整合 3，设计稿 WP-redhead-consolidation）**：「跟我相关」并进「利害与风向」
    （/redhead/stakes 输出的 related_clauses 段）。前端入口 + 组件已撤；端点 + schema 暂留一个
    版本周期返兼容响应，不再单独对外亮出。
    """

    role: str = Field(
        ..., min_length=1, max_length=100,
        description="用户身份（个体户/某局/企业…），据此筛相关条款。",
    )


class RedheadRelevanceResponse(BaseModel):
    """POST /api/agent/redhead/relevance 响应体（已退役，见 Request 注释）。"""

    role: str = Field(default="", description="回显请求里的身份。")
    items: list[dict] = Field(
        default_factory=list,
        description=(
            "跟这个身份相关的条款，每条 {chapter, matter, relevance(高/中), "
            "bearing(义务/利好/条件), note(对你一句话), evidence, verified, "
            "match_score}。不相关的不返。"
        ),
    )
    scanned: bool = Field(default=False, description="false=失败；true+空=没冲你来的条款。")
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(default_factory=dict, description="运行用量 trace。")


class RedheadStakesRequest(RedheadDocStructureRequest):
    """POST /api/agent/redhead/stakes 请求体（利害与风向：相关条款 + 机会/风险/信号 + 含金量）。

    1.6 整合 3 吸收「跟我相关」：身份可选——填了先列跟你相关的条款再研判利害；**不填给通用版**
    （面向一般读者研判，作者拍板点 3）。
    """

    role: str = Field(
        default="", max_length=100,
        description=(
            "用户身份（个体户/投资人/某局/企业…）。填了据此筛相关条款 + 研判利害；空=通用版。"
        ),
    )


class RedheadStakesResponse(BaseModel):
    """POST /api/agent/redhead/stakes 响应体（利害与风向）。

    1.6 整合 3（设计稿 WP-redhead-consolidation）：吸收原「跟我相关」——输出先列 ``related_clauses``
    （跟这身份直接相关的条款，事实底座），再研判机会/风险/信号。原 /redhead/relevance 端点软退役。

    两种证据契约（1.6.1 evidence-first 升级）：相关条款 + 机会/风险=**证据层**（锚原文、过核验、
    可盖鉴印）；信号=**评估层**（标研判 + 引发它的原文基础 + 置信度，绝不盖鉴印冒充事实）。裸推断
    零容忍。含金量（substance）按钱学森开环/闭环判：闭环(指令+主体+时限+考核罚则)=真金白银，
    开环(纯号召)=空头。
    """

    role: str = Field(default="", description="回显用户身份（通用版为空串）。")
    related_clauses: list[dict] = Field(
        default_factory=list,
        description=(
            "跟这身份直接相关的条款（吸收自原跟我相关，作利害研判的事实底座）。每条 "
            "{chapter, matter, relevance(高/中), bearing(义务/利好/条件), note(对你一句话), "
            "evidence, verified, match_score}。证据层，按相关度排；核不过的不丢只标待核。"
            "通用版（没填身份）恒空。"
        ),
    )
    opportunities: list[dict] = Field(
        default_factory=list,
        description=(
            "机会（可争取的红利）。每条 {what, why（对这角色为何是机会）, action（可采取的动作）, "
            "substance（真金白银/有条件兑现/空头倡导）, "
            "substance_reason（凭哪些 marker 判，锚原文）, horizon（近/远/无期）, "
            "evidence, verified, match_score}。证据层，按 substance 排序。"
        ),
    )
    risks: list[dict] = Field(
        default_factory=list,
        description=(
            "风险（暴露面/代价）。每条 {what, cost（代价/后果）, substance, substance_reason, "
            "horizon, evidence, verified, match_score}。证据层，按 substance 排序。"
        ),
    )
    signals: list[dict] = Field(
        default_factory=list,
        description=(
            "信号（弦外之音/政策风向）。每条 {direction（研判出的方向）, "
            "basis（引发它的原文片段列表）, confidence（高/中/低）}。"
            "评估层——标研判、绝不盖鉴印；无原文基础的信号一条都不出。"
        ),
    )
    recommendation: str = Field(
        default="",
        description="系统一句话建议（带立场、轻重缓急）：哪些真金白银值得马上动、哪些空头别当真。",
    )
    scanned: bool = Field(
        default=False, description="false=失败/非公文退场；true+空=没研判出。"
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(default_factory=dict, description="运行用量 trace。")


class RedheadHardFactsResponse(BaseModel):
    """POST /api/agent/redhead/hard-facts 响应体（要点提取，原硬信息提取表）。

    1.6 整合 4（设计稿 WP-redhead-consolidation）：吸收「关键时间轴」——时间类硬事实（时限 /
    生效废止）就是原时间轴抽的东西，前端在表里加「时序视图」把这两类按时序排（保留时间轴那条线的
    形态）。原 /redhead/timeline 端点软退役。功能 label 改「要点提取」，端点 path 不变。
    """

    facts: list[dict] = Field(
        default_factory=list,
        description=(
            "散落全文的硬信息，每条 {kind(时限/数字指标/适用范围/生效废止/责任主体), value, "
            "context, evidence, verified, match_score, binding(硬指标/参考值,约束力层), "
            "binding_reason}。kind=时限/生效废止 是时间类，前端「时序视图」按时序排这两类。"
        ),
    )
    scanned: bool = Field(default=False, description="false=失败；true+空=没抽到硬信息。")
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(default_factory=dict, description="运行用量 trace。")


class MeetingActionLedgerRequest(RedheadDocStructureRequest):
    """POST /api/agent/meeting/action-ledger 请求体（1.7 会议·行动项台账 / 我的行动项）。

    一份会议记录 = 一个已有的 book session（用户照现有 /books/upload 各传一份会议记录 txt）；
    这里收单个 book_session_id，建这份的会脉、派生行动项台账。BYOK，同其它整本结构化功能。

    比单份解读多两个可选项：
    - ``form``：形态（逐字稿/纪要）。传了当门控、不再让模型判；不传则会脉抽取里让模型判
      （判不准默认纪要）。
    - ``owner``：传了就只返该 owner 的行动项（「我的行动项」，按身份筛）；不传则返全部
      （「行动项台账」）。
    """

    form: Literal["逐字稿", "纪要"] | None = Field(
        default=None,
        description="形态门控（逐字稿/纪要）。不传则自动判（判不准默认纪要）。",
    )
    owner: str | None = Field(
        default=None,
        max_length=100,
        description="只看某人的行动项（我的行动项）。不传=全部行动项（台账）。",
    )


class MeetingActionLedgerResponse(BaseModel):
    """POST /api/agent/meeting/action-ledger 响应体（会脉行动项台账）。

    一份会议记录精读一次出会脉（head + decisions + action_items），首炮两个功能都从它派生：
    行动项台账（全部行动项）+ 我的行动项（请求带 owner 时按身份筛）。
    """

    form: str = Field(
        default="纪要",
        description="判出的形态（逐字稿/纪要）。下游据此调期望：纪要里 owner 到组/会议级不算抽坏。",
    )
    head: list[dict] = Field(
        default_factory=list,
        description=(
            "会议头要素，固定 6 条（会议主题/会议时间/主持人/参会人/缺席列席/记录范围）。"
            "每条 {field, value, evidence, verified, match_score}；该形态天生没有的（如纪要的"
            "缺席列席、逐字稿的记录范围）空着时带 not_applicable=true（本形态无此项，非待核）。"
            "抽不到的留空 value + verified=false（待核，绝不编）。"
        ),
    )
    decisions: list[dict] = Field(
        default_factory=list,
        description=(
            "这场会真定下来的事，按序号排。每条 {chapter, decision, decided_by, background, "
            "substance(真金白银/有条件兑现/空头表态), substance_reason, evidence, verified, "
            "match_score}。substance 是开环/闭环判的含金量档，不是打分。"
        ),
    )
    action_items: list[dict] = Field(
        default_factory=list,
        description=(
            "行动项台账（传 owner 时只含该身份的）。每条 {chapter, task, owner, due, "
            "from_decision(落实哪条决议序号，可空), source, substance, substance_reason, "
            "loose_end(owner 空或 due 空=true，BE 纯计算), evidence, verified, match_score}。"
            "排序：loose_end 置顶（没人接/没时限的黑洞）→ 含金量 → 序号。"
            "owner/due 空是信号不是缺陷。"
        ),
    )
    open_issues: list[dict] = Field(
        default_factory=list,
        description="议而未决（首炮恒空 []，schema 占位，第二炮再填）。",
    )
    owner: str | None = Field(
        default=None, description="回显请求里的 owner（我的行动项时）；台账模式为 null。"
    )
    scanned: bool = Field(
        default=False,
        description=(
            "是否成功精读。false=失败，前端提示重试；"
            "true+空 action_items=读过但没抽到行动项。"
        ),
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(default_factory=dict, description="运行用量 trace。")


class MeetingStanceRequest(RedheadDocStructureRequest):
    """POST /api/agent/meeting/stance 请求体（1.7 会议·立场与弦外，第四炮）。

    一份会议记录 = 一个已有的 book session（照现有 /books/upload 传一份会议记录 txt）；这里收
    单个 book_session_id，读出这份会议各议题的真实立场与言下之意。BYOK，同其它整本结构化功能。

    比单份解读多一个可选项：
    - ``form``：形态（逐字稿/纪要）。**立场弦外靠口语细节，纪要是编辑过的概括稿读不出语气**——
      传了纪要直接优雅退场（返空 + 提示传逐字稿），绝不在概括句上硬编。不传则按会脉判出的形态
      （判不准默认纪要，会退场）。逐字稿才正常跑。
    """

    form: Literal["逐字稿", "纪要"] | None = Field(
        default=None,
        description="形态门控（逐字稿/纪要）。纪要退场（读不出语气），逐字稿才判立场弦外。",
    )


class MeetingStanceResponse(BaseModel):
    """POST /api/agent/meeting/stance 响应体（立场与弦外）。

    **整个是评估层**（同公文「利害与风向」的信号段）：没有一条是盖鉴印的事实，全是带原话基础的
    研判。死守 evidence-first：每条立场/弦外的 ``basis`` 必须过核验，一条都核不到就丢整条；
    **stance/subtext 都没有 verified 字段**（评估层、绝不盖鉴印，前端标「研判」不是钤印核验）。
    """

    form: str = Field(
        default="纪要",
        description="判出/传入的形态（逐字稿/纪要）。纪要时 topics 空 + form_note 给退场提示。",
    )
    form_note: str = Field(
        default="",
        description="纪要退场提示（建议传逐字稿）；逐字稿为空串。",
    )
    topics: list[dict] = Field(
        default_factory=list,
        description=(
            "按核心议题聚合的立场与弦外。每个议题 {topic, verdict, stances, subtexts}。"
            "verdict 三态：「有立场张力」（读出了立场/弦外）/「确证一致无弦外」（确证纯通报或真"
            "一致同意，stances/subtexts 空但 verdict 本身是答案，是笃定的「无」不是抽不到）/"
            "「读不出（纪要/待核）」。stance 每条 {person, topic, "
            "position(支持/反对/保留/摇摆/回避),"
            " reading(人话解读), substance(真金白银/有条件兑现/空头表态), substance_reason,"
            " basis(引发研判的原话列表), confidence(高/中/低)}。subtext 每条 {kind(表面同意实则"
            "保留/拖延搁置/甩锅推责/回避问题/留口子/口头答应没底), person, topic, subtext,"
            " basis(原话列表), confidence}。评估层：标研判、绝不盖鉴印；basis 核不到的整条不出。"
        ),
    )
    summary: str = Field(
        default="",
        description="系统一句话总览（带立场，谁在推谁在拖、谁嘴上答应实则没动）；没料返空串。",
    )
    scanned: bool = Field(
        default=False,
        description=(
            "是否成功读出。false=失败/纪要退场/非会议；true+空=读过但没立场张力。"
            "抽到任一立场/弦外、或任一议题 verdict 是「确证一致无弦外」（确证无也是扫过了）→ true。"
        ),
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(default_factory=dict, description="运行用量 trace。")


class MeetingCommitmentsRequest(RedheadCrossDocRequest):
    """POST /api/agent/meeting/commitments 请求体（1.7 会议·跨会承诺—兑现追踪，杀手价值）。

    「卷宗」复用法：客户端传一组 ``book_session_ids``（每个是一份已上传的会议记录 txt）。端点逐个
    建会脉、把承诺按会议时间串起来，跨会追每条承诺后来兑现没。BYOK，同跨文件视图。

    比跨文件视图多一个可选 owner：传了就只返该 owner 的承诺（「我的承诺」，按身份筛）；不传则返
    全部人的承诺台账。
    """

    owner: str | None = Field(
        default=None,
        max_length=100,
        description="只看某人的承诺（我的承诺）。不传=全部人的承诺台账。",
    )


class MeetingCommitmentsResponse(BaseModel):
    """POST /api/agent/meeting/commitments 响应体（跨会承诺—兑现台账）。

    多场会摆一起：每场出会脉、承诺=行动项，跨会沿时间线追每条承诺后来兑现没。状态死守
    evidence-first——「兑现」必须更晚的会里有原话坐实（过核验），判不出就标「进行中/未知」，
    绝不猜兑现；「逾期」由 BE 据 due 纯算（不让模型打这个标）。
    """

    commitments: list[dict] = Field(
        default_factory=list,
        description=(
            "跨会追下来的承诺台账，按「逾期/未兑现置顶→进行中→未知→兑现」排（要追的捞最前）。"
            "每条 {cid, from_mid, from_meeting(哪场会承诺的), from_date, owner, task, due, "
            "substance, status(兑现/未兑现/逾期/进行中/未知), status_note, evidence_mid, "
            "evidence_meeting(哪场更晚的会坐实的), evidence(那句原话), evidence_verified, "
            "from_evidence(承诺那句原话), from_verified}。owner/due 空是信号不是缺陷。"
            "传 owner 时只含该身份的。"
        ),
    )
    meetings: list[dict] = Field(
        default_factory=list,
        description="这组会按时间排的清单，每条 {mid, label(会议主题), date}。给前端按会标注。",
    )
    owners: list[str] = Field(
        default_factory=list,
        description="按承诺数多到少排的 owner 列表，给前端按人分组。",
    )
    owner: str | None = Field(
        default=None, description="回显请求里的 owner（我的承诺时）；台账模式为 null。"
    )
    scanned: bool = Field(
        default=False,
        description=(
            "是否成功跨会追踪。false=失败/不足 2 场会/一条承诺都没抽到（空态）；"
            "true+空 commitments=读过但没追出承诺。"
        ),
    )
    trace: dict = Field(default_factory=dict, description="运行用量 trace。")


class RedheadTimelineResponse(BaseModel):
    """POST /api/agent/redhead/timeline 响应体（关键时间轴）。

    **已退役（1.6 整合 4，设计稿 WP-redhead-consolidation）**：关键时间轴并进「要点提取」
    （/redhead/hard-facts 的时间类硬事实 + 前端「时序视图」切换）。前端入口 + 组件已撤；端点 +
    schema 暂留一个版本周期，不再单独对外亮出。
    """

    nodes: list[dict] = Field(
        default_factory=list,
        description=(
            "按时序排的时间节点，每条 {when(日期或相对期), what, chapter, evidence, verified, "
            "match_score}。"
        ),
    )
    scanned: bool = Field(default=False, description="false=失败；true+空=没带时间的要求。")
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(default_factory=dict, description="运行用量 trace。")


class RedheadGlossaryResponse(BaseModel):
    """POST /api/agent/redhead/glossary 响应体（名词解释）。"""

    terms: list[dict] = Field(
        default_factory=list,
        description=(
            "公文术语释义，每条 {term, explanation(人话), chapter, evidence(术语出现的原句), "
            "verified, match_score}。"
        ),
    )
    scanned: bool = Field(default=False, description="false=失败；true+空=没挑到难词。")
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(default_factory=dict, description="运行用量 trace。")


class RedheadFormatCheckResponse(BaseModel):
    """POST /api/agent/redhead/format-check 响应体（规范性自检，对照 GB/T 9704）。"""

    checks: list[dict] = Field(
        default_factory=list,
        description=(
            "逐要素核查，每条 {item, status(齐/缺/存疑), note, evidence, verified, rule_note}。"
        ),
    )
    summary: dict = Field(
        default_factory=dict,
        description="汇总 {ok, missing, unsure, total, text, extraction_trustworthy}。",
    )
    scanned: bool = Field(default=False, description="false=失败；true=核过。")
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(default_factory=dict, description="运行用量 trace。")


class TimelineRequest(BaseModel):
    """POST /api/agent/timeline 请求体（时间线/事件梳理）。BYOK。"""

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    provider: Literal["deepseek", "anthropic"] = Field(default="deepseek")
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class TimelineResponse(BaseModel):
    """POST /api/agent/timeline 响应体。"""

    events: list[dict] = Field(
        default_factory=list,
        description="按时序排的事件，每条 {order, time, event, chapter, evidence, verified}。",
    )
    scanned: bool = Field(
        default=False,
        description="是否成功梳理。false=失败/书太大，前端提示重试。",
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class EntityRecallRequest(BaseModel):
    """POST /api/agent/entity-recall 请求体（实体回溯快查）。BYOK。"""

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    entity: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="要回溯的实体名（人/物/地点/概念）。",
    )
    provider: Literal["deepseek", "anthropic"] = Field(default="deepseek")
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class EntityRecallResponse(BaseModel):
    """POST /api/agent/entity-recall 响应体。"""

    entity: str = Field(..., description="回显请求里的实体名。")
    appearances: list[dict] = Field(
        default_factory=list,
        description=(
            "按章节先后排的出现处，每条 {order, chapter, what, snippet, verified}。"
            "空列表 = 书里没找到这个实体（合法，不是失败）。"
        ),
    )
    scanned: bool = Field(
        default=False,
        description="是否成功回溯。false=失败/书太大；区别于扫过但没找到（scanned=true、空列表）。",
    )
    confirmed_absent: bool = Field(
        default=False,
        description=(
            "空值三态（task #29 根一）：是否**确证全书未出现**——扫过全书（scanned=true）且"
            "确实没找到这个实体。true 时前端笃定显示「全书没有这个实体」（这是答案，不是搜漏），"
            "区别于 scanned=false 的「扫失败 / 待核」。evidence-first：只在真扫过全书 + 确实"
            "没出现时为 true（probe 实测假阳性 0%）。"
        ),
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class ArgumentStructureRequest(BaseModel):
    """POST /api/agent/argument-structure 请求体（论点结构梳理）。BYOK。"""

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    provider: Literal["deepseek", "anthropic"] = Field(default="deepseek")
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class ArgumentStructureResponse(BaseModel):
    """POST /api/agent/argument-structure 响应体。"""

    claims: list[dict] = Field(
        default_factory=list,
        description="按论证推进排的论点，每条 {order, claim, chapter, evidence, verified}。",
    )
    scanned: bool = Field(
        default=False,
        description="是否成功梳理。false=失败/书太大，前端提示重试。",
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class StyleIssuesRequest(BaseModel):
    """POST /api/agent/style-issues 请求体（文体级毛病检测）。BYOK。"""

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    provider: Literal["deepseek", "anthropic"] = Field(default="deepseek")
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class StyleIssuesResponse(BaseModel):
    """POST /api/agent/style-issues 响应体。"""

    issues: list[dict] = Field(
        default_factory=list,
        description="文体毛病，每条 {type, what, chapter, snippet, verified}；全部原文核验过。"
        "空列表 = 没扫出核验得了的毛病（合法）。",
    )
    scanned: bool = Field(
        default=False,
        description="是否成功扫描。false=失败/书太大；区别于扫过但没毛病（scanned=true、空列表）。",
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class RecapRequest(BaseModel):
    """POST /api/agent/recap 请求体（无剧透情节回顾）。BYOK。"""

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    up_to_chapter: int = Field(
        ..., ge=1, description="读到第几章（只回顾 ≤ 此章，后文不喂、零剧透）。"
    )
    provider: Literal["deepseek", "anthropic"] = Field(default="deepseek")
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class RecapResponse(BaseModel):
    """POST /api/agent/recap 响应体。"""

    up_to_chapter: int = Field(..., description="回显请求里的 up_to_chapter。")
    points: list[dict] = Field(
        default_factory=list,
        description="按时序排的前情要点，每条 {order, point, chapter, snippet, verified}；"
        "chapter 全 ≤ up_to_chapter（结构性无剧透）。",
    )
    scanned: bool = Field(
        default=False,
        description="是否成功回顾。false=失败/书太大/该章号前无可识别原文。",
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class ChapterAskRequest(BaseModel):
    """POST /api/agent/chapter-ask 请求体（按章问答 / 本章导读）。BYOK。

    只把第 ``chapter`` 章的原文喂进 context——"贴着我在读这一章"。``question`` 留空 =
    本章导读（预设问"这章讲了什么 / 谁登场 / 几个要点"）。
    """

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    chapter: int = Field(..., ge=1, description="按哪一章问（只喂这一章原文）。")
    question: str = Field(
        default="",
        max_length=2000,
        description="问题；留空 = 本章导读（预设问）。",
    )
    provider: Literal["deepseek", "anthropic"] = Field(default="deepseek")
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class ChapterAskResponse(BaseModel):
    """POST /api/agent/chapter-ask 响应体。"""

    chapter: int = Field(..., description="回显请求里的 chapter。")
    answer: str = Field(default="", description="只依据本章原文的作答 / 导读。")
    citations: list[dict] = Field(
        default_factory=list,
        description="本章内的原文引用（{chapter, snippet, verified}）；都在本章 verify 过。",
    )
    scanned: bool = Field(
        default=False,
        description="是否答出。false=失败/该章无可识别原文/书太大。",
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class ConceptEvolutionRequest(BaseModel):
    """POST /api/agent/concept-evolution 请求体（跨章概念演进对照）。BYOK。"""

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    concept: str = Field(
        ..., min_length=1, max_length=100, description="要回溯演进的概念名。"
    )
    provider: Literal["deepseek", "anthropic"] = Field(default="deepseek")
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class ConceptEvolutionResponse(BaseModel):
    """POST /api/agent/concept-evolution 响应体。"""

    concept: str = Field(..., description="回显请求里的概念名。")
    stages: list[dict] = Field(
        default_factory=list,
        description=(
            "按章节先后排的演进阶段，每条 {order, chapter, development, snippet, "
            "verified}；全部原文核验过。空列表 = 概念不在书 / 没核验得了的阶段（合法）。"
        ),
    )
    scanned: bool = Field(
        default=False,
        description="是否成功回溯。false=失败/书太大；区别于扫过但没找到（scanned=true、空列表）。",
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class MotifTrackingRequest(BaseModel):
    """POST /api/agent/motif-tracking 请求体（主题母题追踪）。BYOK。"""

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    motif: str = Field(
        ..., min_length=1, max_length=100, description="要追踪的主题/母题名。"
    )
    provider: Literal["deepseek", "anthropic"] = Field(default="deepseek")
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class MotifTrackingResponse(BaseModel):
    """POST /api/agent/motif-tracking 响应体。"""

    motif: str = Field(..., description="回显请求里的母题名。")
    occurrences: list[dict] = Field(
        default_factory=list,
        description=(
            "按章节先后排的复现处，每条 {order, chapter, manifestation, snippet, "
            "verified}；全部原文核验过。空列表 = 母题不在书 / 没核验得了的复现（合法）。"
        ),
    )
    scanned: bool = Field(
        default=False,
        description="是否成功回溯。false=失败/书太大；区别于扫过但没找到（scanned=true、空列表）。",
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class WritingTechniqueRequest(BaseModel):
    """POST /api/agent/writing-technique 请求体（写作手法分析）。BYOK。"""

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    provider: Literal["deepseek", "anthropic"] = Field(default="deepseek")
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class WritingTechniqueResponse(BaseModel):
    """POST /api/agent/writing-technique 响应体。"""

    techniques: list[dict] = Field(
        default_factory=list,
        description=(
            "写作手法，每条 {order, technique, how, chapter, snippet, verified}；"
            "全部原文核验过。空列表 = 没核验得了的显著手法（合法）。"
        ),
    )
    scanned: bool = Field(
        default=False,
        description="是否成功分析。false=失败/书太大；区别于分析过但没显著手法（scanned=true、空列表）。",
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class StudyCardsRequest(BaseModel):
    """POST /api/agent/study-cards 请求体（知识点卡片）。BYOK。"""

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    provider: Literal["deepseek", "anthropic"] = Field(default="deepseek")
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class StudyCardsResponse(BaseModel):
    """POST /api/agent/study-cards 响应体。"""

    cards: list[dict] = Field(
        default_factory=list,
        description=(
            "知识点卡片，每张 {order, concept, point, question, chapter, snippet, "
            "verified}；全部原文核验过。空列表 = 没核验得了的知识点（合法）。"
        ),
    )
    scanned: bool = Field(
        default=False,
        description="是否成功出卡。false=失败/书太大；区别于出过但没核验得了的知识点（scanned=true、空列表）。",
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class AnnotationsRequest(BaseModel):
    """POST /api/agent/annotations 请求体（精读注释层，WP-annotated-reading）。

    按选中的 ``layers`` 编排已有整本书分析、把已核验结论摆成行间注释。BYOK。
    ``entity`` / ``motif`` 仅在对应图层选中时需要——没选那一层不必传。
    """

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    layers: list[str] = Field(
        default_factory=lambda: ["foreshadow", "contradiction"],
        description=(
            "想看的注释图层子集，取值 'foreshadow' / 'motif' / 'contradiction' / "
            "'entity'。默认只开伏笔 + 矛盾两层（治'糊一脸' + 控延迟）；未知名忽略。"
        ),
    )
    entity: str | None = Field(
        default=None,
        max_length=100,
        description="选 'entity' 图层时要回溯的实体名；没选那层可不传。",
    )
    motif: str | None = Field(
        default=None,
        max_length=100,
        description="选 'motif' 图层时要追踪的母题名；没选那层可不传。",
    )
    provider: Literal["deepseek", "anthropic"] = Field(default="deepseek")
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class AnnotationsResponse(BaseModel):
    """POST /api/agent/annotations 响应体。

    ``annotations`` 是贴回原文行间的注释，每条由某个已建分析的一条**已核验**结论生成——
    verified=false 的不进（evidence-first，阅读视图里直接不出现）。跨章类（伏笔回收、设定
    矛盾）带 ``target_chapter`` / ``target_snippet`` 指向它牵连的另一处。``chapters`` 只含
    有注释牵涉到的章（含跨章 target 章）的原文，给阅读视图连续滚动显示。
    """

    annotations: list[dict] = Field(
        default_factory=list,
        description=(
            "行间注释，按 (chapter, layer) 排序。每条 {layer:str, type:str, chapter:int, "
            "snippet:str, summary:str, target_chapter:int|null, target_snippet:str|null, "
            "anchor:str, target_anchor:str|null}；snippet 是该注释挂的原文片段（已核验），"
            "跨章类的 target_* 指向另一处。anchor='exact' 表示 snippet 是所属章原文的逐字"
            "子串、可挂精确行间记号；'approx' 表示转述类、退批注栏不进行间（WP §35）。"
            "target_anchor 对跨章 target_snippet 同理判，无 target 为 null。"
        ),
    )
    chapters: list[dict] = Field(
        default_factory=list,
        description=(
            "有注释牵涉到的章的原文，每条 {chapter:int, text:str}，按章号排序。"
            "只返有注释的章（含跨章 target 章），有界、demo 友好。"
        ),
    )
    scanned: list[str] = Field(
        default_factory=list,
        description="实际跑成功的图层名列表；某层数据源失败被跳过则不在其中。",
    )
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


class OrchestrateRequest(BaseModel):
    """POST /api/agent/orchestrate 请求体（agent 模式，WP-agent-mode §10）。

    用户说一个自然语言目标，编排器规划该跑哪几个已有分析、串起来跑、综合成带原文
    证据的回答。BYOK 同 AgentAskRequest。
    """

    book_session_id: str = Field(..., min_length=1, description="Book session 标识。")
    goal: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="自然语言分析目标（如「这本书伏笔铺得怎么样」「这书在论证什么、证据扎不扎实」）。",
    )
    provider: Literal["deepseek", "anthropic"] = Field(
        default="deepseek", description="LLM provider。"
    )
    api_key: str = Field(..., min_length=8, description="BYOK API key；服务端不持久化。")
    model: str | None = Field(default=None, description="覆盖默认 model（可选）。")
    base_url: str | None = Field(
        default=None, description="OpenAI 兼容 endpoint 覆盖（可选）。"
    )


class HealthResponse(BaseModel):
    """GET /api/health 响应体。"""

    status: Literal["ok", "degraded"] = Field(
        default="ok",
        description="健康状态；当前只有 ok，保留 degraded 以备后续扩展。",
    )
    version: str = Field(
        ...,
        description="项目版本号，取 bookscope.__version__（与发版三处版本号同源）。",
    )
    generation: str = Field(
        default="r1-agent-loop",
        description="代际标识；恒为 r1-agent-loop。",
    )
    deployment_mode: Literal["local", "hosted"] = Field(
        default="local",
        description=(
            "部署形态：local（本地克隆版,无账号）/ hosted（公网托管版,有账号）。"
            "前端据此决定是否显示登录 / 账号入口。"
        ),
    )


class BookUploadResponse(BaseModel):
    """POST /api/books/upload 响应体（ADR-004 方案 B）。

    upload 一次会走完整的 ingest → KG → 装配 → 持久化链路，响应里
    回传新生成的 session_id 与几项关键计数，供前端展示与后续 agent/ask
    使用。
    """

    session_id: str = Field(
        ...,
        description="新生成的 book session id；供后续 POST /api/agent/ask 使用。",
    )
    book_title: str = Field(..., description="书名；来自 upload 参数或文件名。")
    language: str = Field(..., description="书籍语种；默认 zh。")
    chunk_count: int = Field(..., ge=0, description="ingest 阶段产出的 chunk 总数。")
    character_count: int = Field(
        ..., ge=0, description="MinimalKGExtractor 抽取到的角色数。"
    )
    message: str = Field(
        default="upload succeeded",
        description="人类可读的状态文本；前端可选展示。",
    )
    chapter_detection: dict | None = Field(
        default=None,
        description=(
            "章节检测质量指标（WP3 Phase A）。"
            "ChapterDetectionStats 的 dict 形态：chapters_detected / "
            "parse_success_rate / avg_chapter_chars / max_chapter_chars / "
            "pattern_hits / warnings / volume_markers_found。"
            "warnings 非空说明检测可疑（如全书没切出章节）。"
            "向后兼容字段——老客户端不读不影响。"
        ),
    )


class ImportFolderRequest(BaseModel):
    """POST /api/books/import-folder 请求体：批量导入本地文件夹（仅 local 模式）。

    逐本走 ingest（解析+分章）注册为书库 session；跳过 KG 抽取（空 KG），
    书立即可报告/对照/渐进章脉。章脉等深度由现有 prewarm 后台补。
    """

    folder_path: str = Field(..., min_length=1, description="本地文件夹绝对路径。")
    provider: Literal["deepseek", "anthropic"] = Field(
        default="deepseek", description="LLM provider。"
    )
    api_key: str = Field(..., min_length=8, description="BYOK API key；不持久化。")
    model: str | None = Field(default=None)
    base_url: str | None = Field(default=None)


class ImportFolderResponse(BaseModel):
    """POST /api/books/import-folder 响应体：立即返回 job_id + 接受文件数。"""

    job_id: str = Field(..., description="导入任务 id，用于轮询 status。")
    total: int = Field(..., description="接受的候选文件数。")
    skipped: list[str] = Field(default_factory=list, description="跳过的文件（扩展名不支持/读取失败）。")


class ImportFolderStatusResponse(BaseModel):
    """GET /api/books/import-folder/status 响应体：轮询批量导入进度。"""

    status: Literal["idle", "running", "done", "error"] = Field(
        ..., description="idle=无此任务；running=导入中；done=完成；error=失败。"
    )
    done: int = Field(default=0, description="已完成本数。")
    total: int = Field(default=0, description="总本数。")
    current: str | None = Field(default=None, description="正在导入的文件名。")
    results: list[dict] = Field(default_factory=list, description="每本结果：file/session_id/book_title/error。")
    error: str | None = Field(default=None, description="任务级错误。")

class SessionMetadata(BaseModel):
    """单个 book session 的元数据（用于 GET /api/sessions[/{id}] 返回体）。

    字段语义对齐 :class:`bookscope.api.session_storage.JSONFileSessionStorage`
    在 ``metadata.json`` 里写入的内容。**不暴露内部细节**——chunk 数 /
    vector_index 路径 / 角色数等留给 ``/books/upload`` 与
    ``/agent/ask`` 自己的响应体。
    """

    session_id: str = Field(..., description="session 标识。")
    book_title: str = Field(..., description="书名。")
    language: str = Field(..., description="书籍语种。")
    genre: str = Field(
        default="",
        description=(
            "题材（封闭集：小说/历史/理论/论文/公文/会议/诗歌/工具书/其他）。"
            "懒检测——还没分过类时为空串，前端据此显隐题材专属功能（#7）。"
        ),
    )
    created_at: str = Field(
        ...,
        description="ISO-8601 UTC 时间戳；session 首次写入磁盘的时刻。",
    )
    last_accessed_at: str = Field(
        ...,
        description="ISO-8601 UTC 时间戳；最近一次访问 session 的时刻。",
    )


class SessionListResponse(BaseModel):
    """GET /api/sessions 响应体。

    永远 200——空 list 也是合法响应。
    """

    sessions: list[SessionMetadata] = Field(
        default_factory=list,
        description="所有已上传书的 session 元数据列表（按 session_id 升序）。",
    )


class TocChapter(BaseModel):
    """目录里的一章——只给章号 / 标题 / 字数，不带正文（目录要小、要秒回）。"""

    chapter: int = Field(..., ge=1, description="章节号（detect_chapters 标准化后，1 起）。")
    title: str = Field(default="", description="章节标题；原文无标题时为空串。")
    word_count: int = Field(..., ge=0, description="该章字数（中文按字符、英文按词）。")


class BookTocResponse(BaseModel):
    """GET /api/books/{session_id}/toc 响应体——精读阅读器的目录。

    纯数据、不调 LLM：章节由已修根的 ``detect_chapters`` 现场解析（脏书边界
    见 WP-robust-chapter-detection）。章号是序号、不保证等于真回数。
    """

    book_title: str = Field(..., description="书名。")
    total_chapters: int = Field(..., ge=0, description="章节总数；空书为 0。")
    chapters: list[TocChapter] = Field(
        default_factory=list, description="按章号升序的目录条目。"
    )


class ChapterTextResponse(BaseModel):
    """GET /api/books/{session_id}/chapters/{chapter} 响应体——单章正文。

    阅读器读到哪取哪；不调 LLM。越界 / 不存在 → 404（ChapterNotFound）。
    """

    chapter: int = Field(..., ge=1, description="回显章节号。")
    title: str = Field(default="", description="章节标题；无标题为空串。")
    text: str = Field(..., description="该章完整原文。")
    word_count: int = Field(..., ge=0, description="该章字数。")


class ErrorResponse(BaseModel):
    """通用错误响应。

    FastAPI 的 HTTPException.detail 可以直接塞入本对象的 dict 形态；
    前端按 error_type 做分支处理比按 HTTP 状态码粗匹配更稳。
    """

    error_type: str = Field(..., description="错误类型名，例如 BookSessionNotFound。")
    message: str = Field(..., description="人类可读的错误描述。")
    details: dict | None = Field(
        default=None,
        description="可选的附加结构化上下文；前端可选消费。",
    )
    partial_evidence: list[dict] = Field(
        default_factory=list,
        description=(
            "失败前已查到的原文证据（WP5a）。LoopTimeout / "
            "MaxIterationsExceeded 的 504 响应携带，每条 "
            "{chunk_id, chapter, snippet}；其他错误为空列表。"
            "FE ErrorBanner 显示「查到这些原文但没来得及综合」。"
        ),
    )


# ---- 托管版账号(1.6.2 · 只 hosted 路由用,纯 pydantic 不碰 argon2) ----


class RegisterRequest(BaseModel):
    """POST /api/auth/register 请求体(只 hosted)。"""

    email: str = Field(..., min_length=3, max_length=254, description="登录邮箱。")
    password: str = Field(
        ..., min_length=8, max_length=128, description="密码,至少 8 位。"
    )
    # 手机号 2026-06-29 撤掉(PIPL 最小必要:SMS 缓做、收了没用)。数据层 users.phone
    # 列 + UserPublic.phone 保留给将来 SMS,注册暂不收集。

    @field_validator("email")
    @classmethod
    def _email_shape(cls, v: str) -> str:
        v = v.strip()
        host = v.rsplit("@", 1)[-1] if "@" in v else ""
        if "@" not in v or "." not in host:
            raise ValueError("邮箱格式不对")
        return v


class LoginRequest(BaseModel):
    """POST /api/auth/login 请求体(只 hosted)。"""

    email: str = Field(..., min_length=3, max_length=254, description="登录邮箱。")
    password: str = Field(..., min_length=1, max_length=128, description="密码。")


class UserPublic(BaseModel):
    """账号对外视图——绝不含密码哈希。"""

    id: str
    email: str
    phone: str | None = None
    email_verified: bool = False
    created_at: str


class AuthResponse(BaseModel):
    """注册 / 登录成功返回:令牌 + 账号。令牌存浏览器,后续请求带 Bearer。"""

    token: str = Field(
        ..., description="带签名时限的鉴权令牌;只装 user_id,不含 API key。"
    )
    user: UserPublic


class ForgotPasswordRequest(BaseModel):
    """POST /api/auth/forgot-password 请求体(只 hosted)。"""

    email: str = Field(..., min_length=3, max_length=254, description="账号邮箱。")


class ResetPasswordRequest(BaseModel):
    """POST /api/auth/reset-password 请求体(只 hosted)。"""

    token: str = Field(..., min_length=1, description="找回密码令牌(邮件里的)。")
    new_password: str = Field(
        ..., min_length=8, max_length=128, description="新密码,至少 8 位。"
    )


class VerifyEmailRequest(BaseModel):
    """POST /api/auth/verify-email 请求体(只 hosted)。"""

    token: str = Field(..., min_length=1, description="邮箱验证令牌(邮件里的)。")


__all__ = [
    "AuthResponse",
    "ForgotPasswordRequest",
    "LoginRequest",
    "RegisterRequest",
    "ResetPasswordRequest",
    "UserPublic",
    "VerifyEmailRequest",
    "AgentAskRequest",
    "AgentAskResponse",
    "AnnotationsRequest",
    "AnnotationsResponse",
    "BookTocResponse",
    "BookUploadResponse",
    "ChapterAskRequest",
    "ChapterAskResponse",
    "ChapterTextResponse",
    "CharacterArcRequest",
    "CharacterArcResponse",
    "NarrativePhasesRequest",
    "NarrativePhasesResponse",
    "CharacterFlowRequest",
    "CharacterFlowResponse",
    "CharacterGraphRequest",
    "CharacterGraphResponse",
    "CharacterVoiceRequest",
    "CharacterVoiceResponse",
    "CheckCitationsRequest",
    "CheckCitationsResponse",
    "ConsistencyScanRequest",
    "ConsistencyScanResponse",
    "ErrorResponse",
    "ForeshadowArcsRequest",
    "ForeshadowArcsResponse",
    "GraphEdge",
    "HealthResponse",
    "MeetingActionLedgerRequest",
    "MeetingActionLedgerResponse",
    "MeetingCommitmentsRequest",
    "MeetingCommitmentsResponse",
    "NarrativeCurveRequest",
    "NarrativeCurveResponse",
    "OrchestrateRequest",
    "PacingCurveRequest",
    "PacingCurveResponse",
    "PreviousReviewHint",
    "PrewarmSpineRequest",
    "PrewarmSpineResponse",
    "PrewarmSpineStatusResponse",
    "RedheadCrossDocRequest",
    "RedheadDependencyGraphResponse",
    "RedheadDocStructureRequest",
    "RedheadDocStructureResponse",
    "RedheadLevelConsistencyResponse",
    "RedheadPolicyEvolutionRequest",
    "RedheadPolicyEvolutionResponse",
    "RedheadFormatCheckResponse",
    "RedheadGlossaryResponse",
    "RedheadHardFactsResponse",
    "RedheadPlainLanguageResponse",
    "RedheadRelevanceRequest",
    "RedheadRelevanceResponse",
    "RedheadTimelineResponse",
    "RelationshipTimelineRequest",
    "RelationshipTimelineResponse",
    "Review",
    "ReviewDimensionScore",
    "SessionListResponse",
    "SessionMetadata",
    "SpineEvidenceRequest",
    "SpineEvidenceResponse",
    "SubplotWeaveRequest",
    "SubplotWeaveResponse",
    "SuggestQuestionsRequest",
    "SuggestQuestionsResponse",
    "TimelineRequest",
    "TimelineResponse",
    "TocChapter",
]
