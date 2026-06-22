"""r1 FastAPI 入口的请求 / 响应 Pydantic schema。

本模块只负责 API 层的 I/O 契约，不持有任何业务逻辑。所有模型都是
Pydantic v2 BaseModel，FastAPI 会自动用它们做序列化与 OpenAPI 生成。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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
            "deepseek -> deepseek-v4-flash；anthropic -> claude-sonnet-4-6。"
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
    """POST /api/agent/narrative-curve 响应体。

    ``chapters`` 是逐章多维结构，给前端在节奏曲线之上叠维画整本书的"形状"：
    每章一条 ``{chapter, tension(0-10), sentiment(-5..5), pov, mainline, evidence,
    verified, match_score}``——``evidence`` 过原文核验，``verified=false`` 的章前端
    标低置信/淡化（evidence-first：核不过的维度不当确定结论画）。
    """

    chapters: list[dict] = Field(
        default_factory=list,
        description=(
            "逐章多维结构，按章号排序。每条 {chapter:int, tension:0-10, "
            "sentiment:-5..5, pov:str, mainline:bool, evidence:str, verified:bool, "
            "match_score:float}；evidence 过原文核验，verified=false 的标低置信。"
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
            "fortune:-5..5, evidence:str, verified:bool, match_score:float}]}；"
            "point 的 evidence 过原文核验，verified=false 的标低置信。"
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


class RelationshipTimelineResponse(BaseModel):
    """POST /api/agent/relationship-timeline 响应体。

    ``relations`` 是每对主要关系的逐章强度 + 关键转折，给前端在关系图上加时间维：
    每条 ``{a, b, relation, points, turning_points}``——``points`` 是逐章强度
    ``[{chapter, strength(0-10)}]``（连成强度曲线 / 拖时间轴时定连线粗细），
    ``turning_points`` 是关键转折 ``[{chapter, change, evidence, verified, match_score}]``，
    每个转折的 ``evidence`` 过原文核验，``verified=false`` 的前端标低置信/不画
    （evidence-first：挂不上原文的转折不当确定结论画）。
    """

    relations: list[dict] = Field(
        default_factory=list,
        description=(
            "逐对关系的演变。每条 {a:str, b:str, relation:str, "
            "points:[{chapter:int, strength:0-10}], "
            "turning_points:[{chapter:int, change:str, evidence:str, verified:bool, "
            "match_score:float}]}；转折的 evidence 过原文核验，verified=false 的标低置信。"
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
    book_session_id: str = Field(..., description="回显请求里的 book_session_id。")
    trace: dict = Field(
        default_factory=dict,
        description="运行用量 trace：input_tokens/output_tokens/chars/duration_ms。",
    )


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


__all__ = [
    "AgentAskRequest",
    "AgentAskResponse",
    "AnnotationsRequest",
    "AnnotationsResponse",
    "BookTocResponse",
    "BookUploadResponse",
    "ChapterTextResponse",
    "CharacterArcRequest",
    "CharacterArcResponse",
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
    "NarrativeCurveRequest",
    "NarrativeCurveResponse",
    "OrchestrateRequest",
    "PacingCurveRequest",
    "PacingCurveResponse",
    "PreviousReviewHint",
    "RelationshipTimelineRequest",
    "RelationshipTimelineResponse",
    "Review",
    "ReviewDimensionScore",
    "SessionListResponse",
    "SessionMetadata",
    "SubplotWeaveRequest",
    "SubplotWeaveResponse",
    "SuggestQuestionsRequest",
    "SuggestQuestionsResponse",
    "TimelineRequest",
    "TimelineResponse",
    "TocChapter",
]
