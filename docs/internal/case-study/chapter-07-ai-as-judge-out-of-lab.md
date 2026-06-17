# 第 7 章 · AI-as-judge 走出实验室：评分卡的产品化

> **状态**：草稿 · 作者未定稿
> **时段**：2026-05-01（Sprint 5.5 同日落地）
> **覆盖 commit**：`3d2ef8b`（BE · reviewer 接 user-facing）/ `9ea18af`（FE · ReviewCard 评分卡 + 历史回灌带分 + 5 维 schema 对齐）/ `d1138f6`（评论体 citation 厚度 + reviewer 中文像人话 + ReviewCard 顶部说明）/ `4f3e22a`（评分卡再迭代 · 删顶部说明 + 砍 suggest_redo 长文 + 禁 citation 英文 + 修第 4 轮卡住）
> **与前 6 章的关系**：第 3-4 章里 reviewer 是研究者评 batch 的工具——分数只给副管理看；第 7 章是 reviewer 第一次直接出现在用户屏幕上的工程过程

---

## 一、序：reviewer 一直在跑，但只有副管理看得到

第 3 章讲 reviewer agent 的鼓捣过程，第 4 章讲 reviewer 怎么从 v1 收敛到 v2、25 分制怎么定下来。两章里 reviewer 都是研究者的工具——副管理跑 batch 拿到一组 5 题答案，扔给 reviewer，reviewer 回 25 分制 5 维度的 JSON，副管理写进 batch run 报告，再写进 STATE。一个月里 reviewer 跑了几百次，每一次的输出都进了 `bookscope-benchmark/v2` 数据集，再没人看过。

普通用户从来不知道有这个 agent。前端 UI 里没有它，API 响应里没有它，文档里只在 case-study 内部提一笔。

Sprint 5.5 那天作者第一次完整 dogfood 一遍——拿自己稿子的一个章节段跑 BookScope，问了三道题，看了 BookScope 的答复，然后说了那句让 reviewer 走出实验室的话：

> "没有设置专业的 agent 团来评分吗？"

副管理愣了一下。reviewer 当然在——但它在 batch 里跑、在副管理的研究链路上跑、在 v2 benchmark 数据里跑，**就是不在用户面前跑**。BookScope 内部跑了一个月的"AI 评审团"对作者本人是隐形的。

那一刻 framing 翻转得很干脆——reviewer 不是研究工具，是**作者的第二视角**。作者写完一段，BookScope 给一个答复，reviewer 立刻在旁边给个分。25 分制是给作者本人看的——告诉他"BookScope 自己也觉得这次答得不太够"或者"这次答得不错你可以信"。

Sprint 5.5 那天 4 个 commit 就在干这件事——把 reviewer 从 dev-side 搬到 user-facing。下面按时间顺序串。

---

## 二、reviewer 接进 user-facing 的设计选择

`3d2ef8b` 是把 reviewer agent 接进 user-facing ask 流程的主 commit——schemas 加 review 字段、routes/agent.py 加四个 helper、events.py 加 ReviewEvent、6 单测。

### Review schema：5 维 × 5 分 = 25

`bookscope/api/schemas.py` 加两个新 Pydantic 模型：

```python
class ReviewDimensionScore(BaseModel):
    score: int  # 0-5
    comment: str

class Review(BaseModel):
    overall_score: int  # 0-25
    dimensions: dict[str, ReviewDimensionScore]  # 5 维
    overall_comment: str
    top_issues: list[str]
    suggest_redo: bool
```

`AgentAskResponse.review` 加 Optional 字段——同步 ask 直接挂在响应体里；streaming ask 走 ReviewEvent SSE 帧。

为什么是 25 分制不是 100 分制？5 维 × 5 分是 reviewer rubric_v1 一直在用的——25 是给作者一个**有粒度但不需要小数位**的直观刻度。100 分制下"79 vs 81"作者读不出区别；25 分制下"19 vs 21"是清晰段位（18 算"够用"，21 算"答得扎实"）。

### suggest_redo 阈值 < 18

`suggest_redo` 是个布尔标记——reviewer 觉得这次答得太薄、建议作者按"带更厚原文证据"重答一遍。阈值定在 < 18。

为什么是 18？25 分制下 5 维平均 3.6 是边界——rubric 把 3 分定义为"判断模糊 / 证据不强 / 语气保留 / 方向不具体"。平均刚过 3 算可用，跌破 3.6（即总分 < 18）说明这份答复对作家"不够顶用"。这不是统计意义上的 threshold，是 reviewer rubric 内部刻度自己决定的——平均勉强过 3 分还能看，平均掉到 3.5 就该重答。

### `_try_review_or_none`：reviewer 异常吞掉

routes/agent.py 加了四个 helper，最关键的是 `_try_review_or_none`：

```python
def _try_review_or_none(...) -> Review | None:
    try:
        raw = review_answer(client=..., model=..., question=..., ...)
        return _review_from_raw_dict(raw)
    except (ProviderError, LLMFormatError, KeyError, TypeError,
            ValueError, AttributeError):
        return None
```

reviewer 跑挂了——不管是 ProviderError（minimax 422 content filter）、LLMFormatError（JSON 自己救不回来）、还是 schema 字段不对——一律返 None，主 ask 流程不受影响。

这是一条设计原则：**reviewer 是"加分项"不是"阻塞项"**。BookScope 的核心承诺是"回答用户问的关于这本书的问题"；reviewer 给评分卡是锦上添花。reviewer 挂了主答案该出还得出。

异常清单写死六个（ProviderError / LLMFormatError / KeyError / TypeError / ValueError / AttributeError）是因为副管理一边写一边踩——比如 reviewer 返了一个 dict 缺 `dimensions` 字段抛 KeyError、比如 `_review_from_raw_dict` 把 `score` 当 int 转结果拿到 None 抛 TypeError。一条一条加进 except 直到 6 单测全跑过。

### 同步 ask 串 reviewer · streaming ask 流后 emit

同步 ask endpoint 直接在 `_run_loop_or_raise` 后面串 `_try_review_or_none`——多花 5-15 秒但拿到 review 一起返。

streaming ask 复杂一点——`final_answer` 已经 emit 出去了，reviewer 跑那 5-15 秒里前端怎么办？两条路：

- 路 A：reviewer 跑完再 emit `done` 帧——前端在 final_answer 后等 5-15 秒空白
- 路 B：emit `final_answer` 立即 `done`，开新一帧 ReviewEvent 异步追加

走的路 A——final_answer 已 emit、ReviewEvent 在它后面、然后 done。前端在 final_answer 出来后已经能看完答案，5-15 秒延迟里 ReviewCard 区域是空的，等评分回来就出现。

这条选择背后的考虑：用户看完 final_answer 大概需要 10-20 秒（一段答复加几段 citation），reviewer 那 5-15 秒大概率被吸进读答案的时间里——评分卡冒出来时用户刚好读完答案，自然往下看分。

不过这条选择留了一个细节坑——progress timeline 在 reviewer 跑期间会一直显示"第 N 轮 思考中"，让用户误以为 BookScope 还在跑主答案。这个坑 `4f3e22a` 才修——见第五节。

### 6 单测覆盖

测试文件 `tests/api/test_routes_agent.py` +298 行、`tests/api/test_agent_ask.py` +98 行。autouse fixture `_disable_reviewer_by_default` 让既有 `_FakeAdapter` 序列固定的测试默认 reviewer 抛错走 None 路径——不破坏既有 526 单测 case；要测 review 帧的用例自己 monkeypatch 回去。

`pytest 526 全绿（baseline 520 + 6 新用例零回归）`。

---

## 三、5 维 schema 对齐的踩坑

`9ea18af` 是 FE 配套——236 行的 ReviewCard.tsx 新组件、App.tsx review state 接入、historyStorage 加 Review 字段。

本来计划 BE / FE 同 sprint 平行干——BE 派 `bookscope-prompt-engineer` agent 起草 rubric → FE 派一个 typescript-reviewer wrapper 起草 ReviewCard。两个 agent 几乎同时开工。

然后撞了一个 cross-stack 同步问题。

### FE 起草时假设 4 维

FE agent 起草 ReviewCard 时它看的是早期讨论稿——那一稿子里 reviewer 的维度是 4 个：`honesty / actionability / citation_depth / writer_relevance`。这是副管理跟 PE 在早期讨论时的草案，没进最终 rubric_v1。

FE agent 按 4 维写 `DIMENSION_LABELS`，写了 5 格 bar，写了 truncate 评语，写了 top_issues 列表。

BE 那一头实际跑出来的 reviewer rubric_v1 是 **5 维**——

1. `structural_judgment`（判断 vs 复述）
2. `evidence_density`（证据密度与精度）
3. `honesty`（诚实度）
4. `actionability`（可操作性）
5. `cross_chapter_coherence`（跨章节视野）

FE 起草完一接 BE 响应——`dimensions` dict 里有 5 个 key，FE 的 `DIMENSION_LABELS` 只配了 4 个，第 5 个维度 fallback 渲染成原始英文 key `cross_chapter_coherence`，丑、暴露 schema 细节给用户。

### 同 commit 修对齐

合并到 9ea18af 一起改——`DIMENSION_LABELS` 改 5 维：

```typescript
const DIMENSION_LABELS: Record<string, string> = {
  structural_judgment: '判断而非复述',
  evidence_density: '证据厚度',
  honesty: '诚实度',
  actionability: '可操作',
  cross_chapter_coherence: '跨章节视野',
}

const PRIMARY_DIMS = [
  'structural_judgment',
  'evidence_density',
  'honesty',
  'actionability',
  'cross_chapter_coherence',
] as const
```

漏的维度还留了 fallback——以后 BE 加新维度时 FE 旧版本也不会挂，只会显示原始 key 名（不好看但不挂）。

### 翻译过的 5 维标签

维度名翻译这件事副管理来回试了三轮——

- `structural_judgment` 直译"结构判断"——读起来像编程概念
- 试过"判断力" / "下判断"——还是抽象
- 最后定"判断而非复述"——明确说出这一维是在评 BookScope 有没有给判断，不是在评什么模糊的"判断力"

`evidence_density` 也是——

- 直译"证据密度"——技术词，作者读着别扭
- 改"证据厚度"——一个作家熟悉的口语词（"这段写得厚"）

reviewer rubric 内部用英文 key 名（机器侧）、UI 标签用中文（人侧）。这条分层后面 `d1138f6` 还会再加强——reviewer 评语本身也禁用任何英文 key 名。

### 切书 / 新提问 / 历史回灌

App.tsx 加 review state，几个清空和回灌的点要扣紧：

- 切书 → 清空 review（旧书的评分不能挂在新书答复上）
- 新提问 → 清空 review（新题等评分回来再填）
- ErrorBanner 重置 → 清空 review
- 历史记录回灌 → `entry.review` 直接塞进 state（让历史看也带分）

historyStorage.ts `QAEntry` 加可选 `review?: Review` 字段——老历史没这个字段就 null，新历史有就回灌。`HistoryPanel` 组件本身一行没改——回灌走 entry.review 自然进 ReviewCard 不需要新 prop。

### review + final_answer 顺序不定

streaming SSE 帧里 `final_answer` 和 `review` 出现顺序看实际 timing——绝大多数情况是 final_answer 先 review 后，但 reviewer 万一某次特别快也可能反过来。runAsk 里不假设顺序——用局部 `finalAnswer` 和 `finalReview` 变量收齐两个事件后**一起** appendEntry，保证历史记录里答案和评分对得上。

`npm run build` 1.60s 绿、gzip 73.37 KB 在 300 KB 预算内。Sprint 5.5 三块的 reviewer user-facing 路径打通。

---

## 四、第一次给作者看评分卡的反馈

`3d2ef8b` + `9ea18af` 上线、BE 重启、作者打开 web 问了第二轮题。然后副管理收到一段反馈——三件事一起来：

> "原文跟分析的内容是有点不相干的。"
> "这个评分非常的莫名其妙不知道是拿来干什么的。"
> "中文也不像是中文。"

`d1138f6` 一次修这三件。

### (1) 评论体 citation 厚度——"原文跟分析不相干"

作者点开了一道评论体题——"明朝的财政、军事、外交三条线索"。BookScope 答了一段比较完整的评论，三条线各自有论点。但 citation 只挂了 1 条原文（第 20 章纳税人口的一个数字）。

reviewer 本身已经标出问题了——`evidence_density` 给了 1 分，评语写"证据严重不足"。但作者抓得更狠：

> "原文跟分析是不相干的。"

意思是：那 1 条 citation 撑财政部分还撑得住，但是军事、外交两条根本没原文撑——LLM 在"装作看到了原文证据"，实际上只有第三方知识打底的论述。这就是 BookScope 最不能犯的错——**没原文撑的论点不该写，写出来的论点必须有原文撑**。

修在 `bookscope/agent/prompts/fast_path/fast_path_review_v1.md`——

- 把"citations 至少 1 条"硬约束改成"citations 至少 3 条最好 4-5 条 + 每个论点都要有 citation 撑"
- 新加"宁可砍论点不砍 citation"原则——拿到的原文撑不住的论点不写，缩窄到原文真能撑的范围
- 加正反对比例（一条 citation 撑三条线索 vs 缩窄到只讲财政部分）

这一条不是评分卡本身的问题，是**评分卡暴露出 BookScope 答复有诚信问题**——评分卡上了之后第一次让作者直接看到"评论这么厚但 citation 这么薄"的 mismatch。reviewer 在干自己的事，让 BookScope 该露的短露出来。

### (2) ReviewCard 顶部加说明——"莫名其妙"

第二件反馈是评分卡本身——作者看不懂这是什么。25 分制头条印章红印章 + 5 个 bar——它评的是什么、是 BookScope 自己评自己吗、为什么是 25 分？

ReviewCard.tsx 顶部加一行小字：

> "另一个 AI 在按编辑视角给上面这次回答打分（参考用，不是 BookScope 自夸）。分低的时候点底下"重答"让 BookScope 带更厚原文证据再答一遍。"

中性灰小字 + leading-relaxed，不抢评分本身的视觉。

这段文案副管理写的时候自己觉得已经够简——但事实证明对"另一个 AI"、"编辑视角"、"不是 BookScope 自夸"几个概念是堆了 8 个东西，下一 commit 又被作者锤一遍——见第五节。

### (3) reviewer 中文像人话——"中文不像中文"

第三件反馈最深——reviewer 的中文评语本身是机器味的。作者贴出几句样本：

> "thesis-driven 不足"
> "以论带述效果欠佳"
> "教科书式安全输出"
> "actionability 在此维度本就不适用"

四句里三句是翻译腔加英文 key，第四句是名词化堆叠。CLAUDE.md 第三条"中文写作硬规则"对 BookScope 所有中文产出都生效——commit、文档、case-study、prompt——**reviewer 输出的评语也是中文产出**，也得遵守。

这件事副管理之前没意识到——reviewer rubric prompt 里没有"中文写作硬规则"段。reviewer 用着同一个 minimax 同一个模型，但它继承了 LLM 自然倾向出来的写作惯性——thesis-driven、actionability 一类的英文术语混着名词化堆叠就出来了。

`reviewer_rubric_v1.md` 加一整段"中文写作硬规则"——CLAUDE.md 第三条的项目级强制对 reviewer 同样生效：

- 禁用词清单：thesis-driven / 以论带述 / 教科书式 / 安全输出 / 安全赞美 / 论证脉络 / decoration / actionability / evidence_density / citation 厚度 / 名词化堆叠
- 报告体口吻："对于 X 场景而言" / "在该维度本就不适用"
- 装腔修饰："严重不足" / "完全缺席" / "模式"
- 必须项：像真编辑面对面说 / 直接给判断不绕弯 / 短句 / 用具体数字胜抽象

最关键的是给了**反例 vs 正例**——

- 反例："evidence_density 严重不足，其余主张均为无引用的断言"
- 正例："3 条线索（财政 / 军事 / 外交）只挂了 1 条原文（第 20 章纳税人口数），其余两条没有原文撑"

让 reviewer 自己学怎么写——具体数字胜抽象判定，编辑面对面口吻胜技术报告口吻。

### 给作者看的语境 vs 给副管理看的语境

这一 commit 暴露一件被忽略的事——reviewer 的**输出语境**变了。

在第 3-4 章里 reviewer 给副管理看——副管理是 AI 系统的工程方，看得懂"evidence_density 1 分 actionability 3 分"。reviewer 用半中半英、用技术术语、用 rubric 字段名都没问题——副管理对着 rubric 读懂分数和评语。

现在 reviewer 给作者看——作者是文学创作者，对编程概念无感、对英文 key 名抗拒。reviewer 必须切换写作姿态——从"AI 系统内部报告体"切到"编辑面对面说"。

这不是 prompt 改一个 paragraph 的事——是 reviewer **角色定位本身**的迁移：从"自动化评估器（machine-readable）"切到"作者的第二视角（human-facing）"。

`d1138f6` 给 reviewer 的"中文写作硬规则"段就是在做这个迁移——告诉 reviewer："你说的话现在是给作家本人读的，不是写给后端日志的"。

`pytest 526 全绿、npm build 1.06s 绿（gzip 73.49 KB 在预算内）`。

---

## 五、评分卡再迭代：第三次 dogfood

`d1138f6` 上线后作者第三次 dogfood——四件细节反馈：

1. 顶部说明文案绕——8 个概念读起来更困惑
2. suggest_redo 长文案多余——"reviewer 觉得这道题答得不太够" 那句机器味提示读着尴尬
3. 评语里还有英文 key 漏网——"三条 citation"、"actionability 低分"
4. 答案出完后 progress timeline 一直显示"第 4 轮 思考中"误导

`4f3e22a` 四件一起修。

### 顶部说明文案删

上一 commit 加的那段：

> "另一个 AI 在按编辑视角给上面这次回答打分（参考用，不是 BookScope 自夸）。分低的时候点底下"重答"让 BookScope 带更厚原文证据再答一遍。"

副管理写的时候觉得已经够简，作者读完说"这是个啥莫名其妙"——堆了"另一个 AI"、"编辑视角"、"参考用"、"BookScope 自夸"、"分低的时候"、"重答"、"更厚原文证据"、"再答一遍"8 个概念。每个单独都不难，叠一起 = 一段需要解码的字。

`ReviewCard.tsx` -20 行——顶部 4 行说明文案删掉，评分卡下面 5 维度 + 总评 + top_issues 已经够清楚，顶部不需要再绕一段。

这条小事背后的判断：**UI 解释性文案的边际效用是负的**。一个看得懂的界面不需要文字解释——加解释只会暴露这个界面没看懂。评分卡的 5 维度 bar + 总分头条 + top_issues 列表已经在视觉上自我解释——25 分头条、5 个 bar、几条问题——加文字描述反而让用户先读完文字再看图，多一步。

删掉之后作者没再说"莫名其妙"。

### suggest_redo 长文案砍

原本 suggest_redo 区块是"提示文案 + 重答按钮"双列：

```
reviewer 觉得这道题答得不太够。
要不要 BookScope 带更厚原文证据再答一遍？
[重答]
```

作者那句："这个放在这里的目的是什么"——他懂这是低分提示，但是"reviewer 觉得这道题答得不太够"这种第三方拟人化太机器。

简化成只保留按钮：

```
[重答这道题]
```

按钮文案从"重答"改"重答这道题"——自带含义（用户能猜到重答的是哪道）。不需要前面一句提示。

### 禁用英文 key 名加强

`d1138f6` 已经禁了 thesis-driven、actionability 等英文术语，但 `reviewer_rubric_v1.md` 没明示"任何英文 key 名都不许出现"。reviewer 还是会写出"三条 citation"、"actionability 这一维"——它觉得自己在"引用字段名"是合理的。

`4f3e22a` 加一段强调：

> **绝对禁用任何英文 key 名**（即便它们是 rubric 字段名）：不要写 'citation' → 写'引文'或'原文'；不要写 'actionability' → 写'可操作'或描述具体；不要写 'evidence_density' → 写'证据密度'或'原文够不够'；不要写 'honesty' → 写'诚实度'。**评语是给作者读的中文段落，不是字段标签**。

最后一句是关键——"评语是给作者读的中文段落，不是字段标签"。明确告诉 reviewer 它现在写的是面向人的散文，不是 JSON 字段值的注释。

同时把"严重缺陷"加进装腔修饰禁用词——上一 commit 漏了这一组。

### 第 4 轮卡住的 bug

最后一件不是文案是真 bug——作者反馈"第 4 轮的分析一直卡着"。

挖了一下——`final_answer` 已经 emit 出去（前端已经能看完答案），但 reviewer 跑那 5-15 秒期间，progress timeline 上最后一行 `iteration_start` 事件（第 4 轮）一直显示 "running"——前端不知道 final_answer 出完之后还在等 reviewer，就还按"第 4 轮 思考中"渲染。

用户体感：答案出来了，但进度条还在转——"卡住了"。

修在 App.tsx `runAsk` 流式分支收 `final_answer` 时立刻：

1. 把 progress 里所有 `status=running` 的 tool 标 ok
2. 加一行 `kind=meta` 的 progress 项："reviewer 评分中…"

收 `review` event 后把那行改成"reviewer 评分完成"。

视觉上变成——final_answer 出完后 progress timeline 不再"思考中"，而是清晰地切到"reviewer 评分中…"过渡到"reviewer 评分完成"。用户看得到"BookScope 主答案已出、现在在等评分"两阶段。

这条 fix 把第二节那个"流式 ask 选了 路 A 留下的细节坑"补上了——路 A（reviewer 跑完再 emit）的代价就是前端要清楚地告诉用户"主答案出完了、现在在等评分"。少了这个交互细节，用户以为 BookScope 还在主答案。

`pytest 526 全绿、npm build 1.64s 绿（gzip 73.40 KB）`。Sprint 5.5 收官。

---

## 六、AI-as-judge 走出实验室的元层观察

四个 commit 跑完，回头看几件事——

### reviewer 的输出语境决定它的写作姿态

第 3-4 章里 reviewer 是给副管理看的——评语半中半英、用 rubric 字段名、用技术术语都没问题。第 7 章里 reviewer 是给作者看的——必须用编辑面对面口吻、用具体数字、用中文短句。

prompt 一字没变的情况下把 reviewer 从 dev-side 搬到 user-facing，**评语就会显得机器**——LLM 的自然倾向 + rubric 字段名混杂会输出 thesis-driven / actionability 这种英文混搭。`d1138f6` 加"中文写作硬规则"段才让 reviewer 知道自己说话的对象变了。

这是一条比较普适的观察——**任何一个 AI agent 的输出语境从研究端切到用户端时，prompt 必须显式重新告诉它说话对象是谁**。LLM 没法自己猜——它只看 prompt 字面、不知道它的输出最终被谁读。`d1138f6` 那一段"中文写作硬规则 + 编辑面对面 + 评语给作家读"是一次显式语境转移。

### reviewer 是"作者的第二视角"不是"裁判"

评分卡顶部说明那段文案被删的根原因——副管理一开始想把 ReviewCard 解释成"另一个 AI 评审团给当前答案打分"。这是研究侧视角——把它当成一个独立的评估器、一个有权威的打分系统。

作者反馈"莫名其妙"之后副管理才意识到——对作者而言 ReviewCard 不是"裁判"，是**他自己的第二视角**。作者读完 BookScope 答复，会自然想知道"这答得够不够"——评分卡填的是这个空。25 分制不是权威分，是 BookScope 自己对这次答复的诚实评估——告诉作者"BookScope 自己也觉得这次薄了"。

`4f3e22a` 删顶部说明 + 砍 suggest_redo 长文案，方向就是把"裁判"语义彻底去掉，让评分卡变成一个低调的、附加的、给作者补一个看法的视角。

### 评分卡反过来逼答案诚信

第三节那条 reviewer 抓出"3 条线索只挂 1 条 citation"——是评分卡上线带来的副作用。在 dev-side batch 阶段 reviewer 早就标过 evidence_density 1 分，副管理看到了但只把它记进 STATE 留作改进点。

评分卡上线之后这条数据**直接出现在作者眼前**——作者立刻能看到"评论这么厚但 citation 这么薄"的 mismatch，立刻反馈"原文跟分析不相干"。fast_path_review_v1.md 那一条"宁可砍论点不砍 citation"硬约束就是这一刻定的——评分卡让 BookScope 的诚信问题没法藏。

这是 AI-as-judge 走出实验室的一个意想不到的好处——**当评分公开给最终用户后，BookScope 自己就不敢答得太水**。reviewer 看着、用户看着、低分会触发"重答"按钮，每一道题答得薄都有代价。这一条对 BookScope 答复质量的长期约束比单独修 generator prompt 更强。

### reviewer 自己也要遵守"中文像人话"

第 7 章一个最容易被忽略的点——reviewer 是项目内的 AI agent，**它也要遵守 CLAUDE.md 第三条中文写作硬规则**。

副管理之前下意识把"中文像人话"当成对自己（主 Claude）和文档产出的约束——commit message、case-study、STATE 这些都要中文像中文。但 reviewer 是个 LLM agent，prompt 里没明示就会出 thesis-driven / actionability 一类的输出。

`d1138f6` 把"中文写作硬规则"段加进 reviewer rubric——这条规则**变成项目级规则**，不是主 Claude 个人产出规则。任何项目内运行的 LLM agent（reviewer / generator / 后续可能加的 critic）都要遵守。

这条沉淀进 memory 是值得的——以后任何新的 AI agent prompt 起草都默认带"中文写作硬规则"段（如果输出面向用户）。少这一段 = LLM 默认就会出翻译腔。

---

## 七、Sprint 5.5 那一日的尾巴

Sprint 5.5 一日 7 commit 整收官——4 个评分卡相关（这一章覆盖的）+ 3 个其他（上传进度、Onboarding、suggested questions、第 6 章草稿）。

回头看这四个 commit 的密度——

- `3d2ef8b` BE +699 / -14 行（schemas + routes + events + tests）
- `9ea18af` FE +331 / -12 行（ReviewCard + App + historyStorage）
- `d1138f6` +54 / -4 行（fast_path prompt + reviewer rubric + ReviewCard 顶部一行）
- `4f3e22a` +32 / -26 行（ReviewCard 删 + App progress meta + rubric 禁英文 key 名）

第三第四 commit 加起来才 86 行 / 减 30 行，但是它们把 reviewer 从"机器评估器"调到"作者第二视角"——这是 framing 上的距离，不是代码量上的距离。

最容易被忽略的一件事——`d1138f6` 和 `4f3e22a` 都是**作者 dogfood 反馈触发的**。BookScope 这一个月跑了几百次 batch、reviewer 在 dev-side 出了几百次评语，副管理从没觉得评语机器。直到作者真用一遍——三次 dogfood 反馈三次迭代——才把 reviewer 调成给人读的样子。

这是这个项目最长期的资产——作者作为长篇网络小说创作者本人在用 BookScope，他每一次反馈都是 BookScope 唯一真实的产品验证回路。reviewer 走出实验室那一天是 Sprint 5.5——这一天 BookScope 第一次让作者**直接看到 AI 评审团的分数**，作者也第一次能告诉 BookScope"你这个分给得机器"。

reviewer 一直在跑——只是这一天起跑给作者看。

---

*本章草稿到此为止。Sprint 5.5 评分卡相关 4 commit 已覆盖、reviewer 角色迁移已写清、作者三次 dogfood 反馈各自展开。定稿由作者在里程碑点统一润色。*
