# 第十章 · 把性能第二刀切到上传那一侧

> **状态**：草稿 · 作者未定稿 · 2026-05-19 起头
> **代际**：r2-agent-protocol（Sprint 7 删 r1 之后单形态）
> **覆盖时段**：2026-05-15 到 2026-05-19 五日
> **关联 ADR**：ADR-008（三层缓存）
> **关联 sprint**：Sprint 6 全程 + Sprint 8 三层缓存
> **关联章节**：chapter-06（性能第一刀 · loop 层）/ chapter-09（兜底链补齐那三天）

---

## 序：第二刀落在用户上传的那一刻

chapter-06 讲的是性能第一刀——Sprint 5 把 tool 并行、题型路由、fast_path 三件事塞进 loop 层，单题 90-180 秒被压到 30-60 秒，通识题直接掉到 3-12 秒。那一刀切的全是"用户问题进来之后到答案出去"这条路径。

但用户用 BookScope 的第一感受不是问问题，是上传。一本几十万字的书丢进来，进度条转个 3 分钟，用户还没问第一个问题就要等。chapter-09 第十节那条通用兜底链做完后，KG 抽取这条路径上的错误处理矩阵齐了，但耗时这件事还没碰——anshi 整本 ingest 走老路要七八十秒、mingchao 卷一要两分多钟，都是把全书丢给 LLM 切 batch 抽人物的 LLM call 累加耗时。

第二刀就切在这里。5/15 下午一句"全部签字！"之后，Sprint 6 全程提前两个月启动，BE 一条工作链 5 commit 把 chunk batch 并发、batch 级 SQLite 缓存、book-level 缓存、SSE streaming 全推完。同一天作者亲签 ADR-008，三层缓存 31 分钟内落完。三天后 timing probe 跑出 664x 和 1271x 两个加速数——不是预估，是实测。

但 quality probe 跑齐那一天撞了墙。reviewer 评分这条调用路径在 minimax 上稳定拒答，4 组 × 5 题 = 20 次调用全部返空，原实验设计里"5 维度 std ≤ 0.5 分"的撤回判定走不通了。这是 chapter-04 v3.3 q5 std 翻车、chapter-09 第十节兜底链补齐之后，本套案例研究第三次把"失败比成功更值得写"那条 RE 行规写到具体一章——不是 cache 写错了字段，是实验设计预设错了前提。

本章十节按时间序串这五天的事。

---

## 一、chunk batch 调度从串行到并发

第一笔是 commit `d888be9`（5/15 16:16）。`MinimalKGExtractor.extract()` 原本是串行 for 循环——一本书按每 60 chunk 一 batch 切片，挨个调 LLM 抽人物。anshi 整本 267 chunks ≈ 5 个 batch，串行跑 LLM 时间累加；mingchao 卷一 1069 chunks ≈ 18 个 batch，累加更夸张。

改造照搬 Sprint 5 `loop.py:_dispatch_tools_parallel` 那条保序并发模板——ThreadPoolExecutor + dict[future, idx] + future.result() 按 idx 写回 results 严格保序。保序硬约束来自 `_merge_and_build_profiles` 的"同 canonical 取首次出现写法"语义，乱序会让 description 指针随机化。

几条具体判断点：

- n==1 或 max_workers==1 走 inline 分支不浪费线程池
- 单 batch 异常不做 partial 兜底，直接透传——KG 残缺让下游 r0 backend 读到错错角色清单比直接失败更危险
- max_workers 默认 5，跟 TOOL_PARALLEL_MAX_WORKERS 同上限（DeepSeek 默认 60 RPM 留余地），env `BOOKSCOPE_KG_EXTRACT_MAX_WORKERS` 可调
- 三级优先级 _resolve_max_workers——构造参数 > env > 默认；非整数 env 打 warning 走默认；< 1 全部 clamp 到 1

commit message 里的预估写得很克制：

> N=3 batch 5 路并发理论 3x 加速；N=10 batch 5 路并发理论 2x 加速。pilot 端到端 109 秒里 LLM 派发部分占大头，预估单本可压到 35-60 秒之间。

实测后来比预估更乐观——但 commit 那一刻 BE 不知道，写文档时按理论值给。这是 BookScope 数据点引用纪律的一种保守表达：没真跑就不写"实测多少"。

这条并发改造模板跟 Sprint 5 `loop.py` 那条的关系值得讲一句。Sprint 5 并发改造的对象是 tool 调用——一个 search_chunks 调多次、查不同章节范围。Sprint 6 这条改造的对象是 batch 抽取——一本书切成 N 段，每段独立调 LLM 抽人物。两边形态不同（前者是 tool 派发、后者是数据切片），但模板共用：抽辅助方法让主循环线性可读、ThreadPoolExecutor + dict[future, idx] 保序、单 batch 异常不做 partial、env override + 三级优先级、max_workers 默认值跟全局上限保持一致。**一处工程模板在两条不同性质的工作上各用一次**——这是 chapter-09 第六节"L1 抽的 LRUCache 底座给 L2 / L3 共用"那条复用思路在工作流层的同模式。

12 条新测试覆盖保序 / 并发实质（peak_inflight 3 + wall-time < 0.6s vs 串行 ≥ 0.9s）/ max_workers=1 退化串行 / 单 batch 不起池 / 异常透传 / env 控制。baseline 664 → 676。

---

## 二、KG r2 兼容 bug 静默潜伏 28 小时

`d888be9` 主线动作做完，BE 在 commit message 末尾报了一个旁注：

> MinimalKGExtractor 当前 `_extract_text_from_response` 按 Anthropic content blocks 读响应，Sprint 7 删 r1 后所有 adapter 默认走 r2 OpenAI plain dict，原 helper 读 `response.get("content")` 恒为 None → 抛 LLMFormatError —— 整条 upload → KG → r0 backend 链路在生产路径上 100% 静默挂。

这条 bug 是 5/14 中午切默认那一刻就埋下的。从切默认到 BE 在 5/15 下午写并发改造时撞出来——28 小时静默期。没人发现的原因是 BookScope 长期没人真上传过新书做 KG——书已经在 store 里就跳过此路径，KG 抽取层之前是冷数据。

chapter-09 第七节已经讲过同性质的两条 bug——fast_path r2 形态在 commit `a454f36` 被 QA 写测试时撞出、KG 在 `d888be9` 被 BE 写并发时撞出——都不是用户报告的，是相邻工作 exercise 到的。

修法是 commit `e33c37a`（5/15 16:28），跟 fast_path r2 修复（commit `0f36fb2`）同模式 + 复用 Backlog B-1（commit `038e11a`）做完的 adapter Protocol 契约：

```python
# 修前
text = _extract_text_from_response(response)  # 按 Anthropic content blocks 读
# 修后
text = self._client.extract_final_text(response)  # 形态差异由各自 adapter 兜底
```

extractor 构造签名不动——B-1 已经把 `extract_final_text` 方法挂在 LLMClient Protocol 里，传 client 就传到了。**一处协议改造解锁多处 bug 收口**——chapter-09 第七节那句话在这里第二次得到验证。

新建 `tests/agent/r2/test_minimal_kg_extractor_r2.py` 6 条 r2 形态守护测：fake R2 client 镜像 DeepSeekAdapter 在 r2 下的对外契约（messages_create 吐 OpenAI plain dict），断言 happy path / 围栏剥离 / 多 batch 合并 / 缺 choices / 缺 message / null content 全路径正确。两个老 fake client（`_FakeClient` / `_ConcurrencyFakeClient`）补 Protocol 要求的 `extract_final_text` / `extract_usage_tokens` 两个方法，让 fake 真符合 LLMClient。

baseline 676 → 683。修了这条 bug 之后 KG 抽取在 r2 默认下才真能跑通——之前 28 小时里生产路径 100% 抛 LLMFormatError 但没人报。

---

## 三、KG batch 缓存按 chunks 内容 hash

第二步是 commit `bdd9a20`（5/15 16:36）—— `_extract_from_batch` 这一层加 SQLite 持久化缓存。原因写在 commit message 里：

> anshi 量级单本 KG 抽取要几十秒到几分钟（最贵的一段），公开书 + 用户重启进程 + 用户切回同本时都是纯浪费。

cache key 算法是 sha256({chunks=[{index, text}], system_prompt, model}) 取前 24 字符。两个判断点：

- chunk 顺序敏感（merge 时影响"首次出现写法"）所以**不**做集合归一化
- chunk 序列化只取 {index, text} 两个字段——后续 chunk 对象加新字段（比如 metadata）不会让老缓存失效

后端 `SQLiteCache(table_name="kg_extractions", schema_version="v1")`，跟后面 book-level 缓存同库不同表，OPS 清缓存只 rm 一个文件就清两层。序列化走 `json.dumps`——`_extract_from_batch` 返 list[dict[str, Any]] 全 JSON 友好（name / canonical_name 是 str，key_chapter_indices 是 list[int]），不需要 pickle 兜底。

缓存层任何异常（DB 锁 / 序列化失败）都包死异常，转去直调 extract_func；写缓存失败也吞掉，不影响本次返值。这是 chapter-09 第七节那条 callback 三原则在缓存层的同模式应用——异常包死是 BookScope 全局基础设施的硬规则。

跟 L2 LLM 缓存的关系在 commit message 里写明了：

> 粒度不同（KG 缓存解析后 entries / L2 缓存原 LLM response），两层都命中是冗余不冲突——KG 层先返、L2 不被调；只在 KG miss 时走 LLM 调用路径再过 L2。

20 条新测试 / baseline 683 → 703。测试覆盖按职责分桶——key 算法 7 条（hex 格式 / 同 input 同 key / chunk text 改 / chunk 顺序改 / chunk index 改 / system_prompt 改 / model 改）/ 序列化 2 条 / extract_batch_cached 行为 7 条（首次 miss 写入 / 二次命中 / 不同 chunks / 不同 prompt / 不同 model / env disabled / clear_kg_cache）/ schema_version 失效 2 条 / MinimalKGExtractor 集成 2 条。

`tests/conftest.py` 加一条 `_isolate_kg_cache_db` autouse fixture——每个测试用 tmp_path 独立 KG 缓存 DB，避免跨测试污染。这条 fixture 是 BookScope 缓存层测试基础设施的标配——L1 / L2 / KG batch / KG book / book warmup 五层每一层都加一条同形态 autouse fixture。这是 chapter-09 第六节那条"缓存层基础设施共用"在测试层的具体形态——不只代码层共用 LRUCache + SQLiteCache 底座，测试隔离也共用 autouse fixture 模板。

---

## 四、KG 增量被 cache key 算法天然涵盖

第三步本来排的是"KG 增量"——用户追加章节后避免整本 KG 抽取重跑。commit `b12df12`（5/15 16:55）做出来时一行算法代码都没写。

audit 阶段发现三件事叠加自动解决了增量：

- `chunk_book` 是纯函数（regex 章切 + 段落合并 + 字符计数），同输入同输出
- `_split_into_batches` 按固定 60 切片（`chunks[start : start + 60]`），跟 chunks 内容无关
- `_compute_kg_cache_key` 按 chunks 的 {index, text} 序列 hash

三者叠加 → 用户追加章节后前 K // 60 个完整 batch 的 chunks 内容跟旧版完全一致 → cache key 一致 → 自动命中。只有"半满 batch"会因新 chunk 拼进来变 key，这是预期的少量重抽成本。

第三步落成的是一条 audit + 三条回归测试钉死这条性质：

- `test_chunker_is_deterministic_same_input_same_chunks`——chunker 决定性
- `test_batch_split_is_content_independent`——batch 边界稳定
- `test_appended_chapter_reuses_old_batch_caches`——端到端追加章节场景下旧 batch LLM 调用次数 = 0、新增 chunks 数 = 新 LLM 调用数

未来若有人改 `_split_into_batches` 或 `_compute_kg_cache_key` 算法会立刻失败提示。

这条经验进了 chapter-09 第八节末尾的续记：**缓存层 key 算法选得早，下游"增量"经常被免费解决**。

baseline 703 → 706 / 0 行算法代码 / 3 条回归门。

---

## 五、book-level 缓存让整本 KG 重读直接跳过

第四步是 commit `2419176`（5/15 17:05）—— `MinimalKGExtractor.extract` 出口再叠一层 book-level 缓存。

第三步 batch 级缓存命中条件是 `(chunks, system_prompt, model)` 三元组。但 `extract` 出口的 `BookKnowledgeGraph` 是 batch 抽取完之后 merge 出来的——任何重读同本书都得重切 batch、重查 batch 级缓存、重跑 merge。batch 级缓存命中再快，merge 那一步还是要走。用户上传过的书在 session 重启后想再问，这条路径每次都要走 18 个 batch SQLite 查询 + 一次 merge。

第四步在出口再叠一层——命中时整本 KG 直接走 JSON 反序列化跳过所有 batch 操作。新模块 `bookscope/agent/_internal/kg_book_cache.py`，cache key 用 `(all_chunks_text_concat, system_prompt, model)` 三元组 sha256 取前 24 字符。跟 batch 级 key **故意**不一样：本层 key **不绑 chunk.index**，整书重 ingest 时 index 由 text 顺序决定，text 一致就该命中。

跟 Sprint 8 L3 book 预热缓存的关系在 commit message 里讲清楚了——L3 缓存的是 `WarmedBook`（含 assembler 本体 + content_hash + ingested_at），pickle 持久化，键是 session_id；book-level KG 缓存缓存的是 `BookKnowledgeGraph`，JSON 持久化，键是 chunks + prompt + model 的 sha256。两层不是同一个对象、不是同一种 key 语义、不是同一种序列化方式，不在同一个文件——`.bookscope_cache/book_warmup/<sid>.pkl` vs `.bookscope_cache/kg_cache.db`。

**L3 是 session 级（"这本书在内存里 ready 了"），book-level KG 是内容级（"这堆 chunks + 这个 prompt + 这个 model 已经抽过 KG 了"）**。两层叠加的意义：L3 命中只表明 assembler 不用重新 ingest，KG 那一层还是要走；L3 miss + book-level KG hit 时（比如换 session 上传同样的 epub）依然能跳过整本 KG 抽取。

测试 24 条 / 5 个 TestClass。最关键的硬约束是**双层叠加验证**：book-level 命中后 batch 级 SQLite 必须 `size` 不变——验证完全跳过，不只是"快"。pytest 全套 730 零回归。

---

## 六、SSE streaming 让用户看见后端真进度

第五步是 commit `d066445`（5/15 17:33）—— FE 接 SSE 把 BE 攒下的加速能力转成用户可见的进度。

之前用户上传期间看的是 `useUploadProgress` 的三段经验曲线——按本地时间 t 估算"15% → 60% → 95%"的假进度条。后端真实 batch 进度、缓存命中状态全部对用户不可见。BE 的并发 + 两级缓存把 ingest 时间从分钟级压到秒级，但用户在浏览器看到的是同一根假曲线匀速跑完。chapter-08 那条"用户视角"主线在这里再次成立——工程层的优化如果不让用户感受到，等于没做。

技术形态：

- `bookscope/agent/events.py` 加 `IngestEvent` frozen dataclass + `IngestEventType` 6 类字面量（`ingest_started` / `kg_batch_started` / `kg_batch_completed` / `kg_cache_hit` / `ingest_done` / `ingest_error`）
- 独立 union 不并进 LoopEvent——ingest 流跟 ask 流是两条不同 SSE 端点，强行 union 会让 FE 类型膨胀
- `MinimalKGExtractor.__init__` 加 keyword-only `on_ingest_event` + `book_session_id`，跟 Sprint 1 AgentLoop callback 同三原则（默认 None / 异常包死 / trace 写完再 emit）
- 新端点 `POST /api/books/upload/stream` 跟 `/api/agent/ask/stream` 同模板——asyncio.Queue + thread bridge + StreamingResponse
- setup-time 错误（文件格式 / 空文件）仍走 HTTP 4xx；ingest 期错误 emit `ingest_error` + `upload_error` 帧，HTTP 仍 200

FE `streamUploadBook` async generator + `IngestProgressState` reducer，进度条 SSE 帧迟到时回退到三段曲线作 fallback。stepLabel 文案从"AI 正在分析角色，请稍候"切到"AI 正在分析角色 · 3 / 5 批次完成 · 已命中缓存 2 段"。

这一笔顺手修了一个 race condition——`test_extract_merges_duplicates_across_batches` 在 ThreadPoolExecutor 并发下 FakeClient.pop 顺序与 batch idx 随机错配。原来 `d888be9` 并发改造之后这条测试已经在 race 上了，CI 偶发挂——FakeClient 顺序消费是测试自己的脆弱设计，不是 BE 改造的问题。`max_workers=1` 强制串行钉死断言稳定，单测覆盖力不损失。

baseline 730 → 744（+8 KG streaming + 6 SSE 端点）。npm build 全绿（241.88 KB / gzip 75.93 KB，相比上一次 commit 增量约 +3 KB）。

这一笔在 chapter-08 那条用户视角主线里的位置——chapter-08 讲 dogfood 那一天作者真用 BookScope 上传新书撞了一连串"工程对但用户感受不对"的坑，FE 错误兜底全覆盖 / timeout 90 → 180 / partial_evidence 进 BookScope 这几件事都是那一天的产出（见 memory `feedback_fe_error_coverage.md`）。本节 SSE streaming 是同条线的延续——**工程层把 ingest 从 109 秒压到 35-60 秒不算完整交付，FE 让用户看见这件事在哪段省了时间才算完整交付**。stepLabel "AI 正在分析角色 · 3 / 5 批次完成 · 已命中缓存 2 段"这句文案不是装饰，是 BookScope 团队对"工程价值必须穿透到用户感受"那条规则的具体做法——用户看到这一句，下次再上传同本书时心理预期就锚到"缓存会命中"上，不会再问"为什么这次跑得比上次快"。

---

## 七、ADR-008 三层缓存一日签字 + 31 分钟做完

跟 Sprint 6 BE 工作链并行的是 Sprint 8 三层缓存。

ADR-008 原编排是 2026-08-07 启动，作者 5/15 下午一句"全部签字！"提前两个月。commit `ce4aae3` Status 段改成"已批准 · 2026-05-15 作者明示签字 · Sprint 8 启动"。L1 / L2 / L3 在签字前后 31 分钟内全部做完——这段 chapter-09 第六节已经讲过，本节只摘要并标出跟 ingest 层的差异。

**L1 search_chunks 缓存**（commit `2c2428e` · 15:05）—— 进程内 LRU + 5 元组 key + session_id 前缀清。`bookscope/agent/_internal/cache.py` 通用 LRUCache 底座 140 行 + `search_cache.py` wrapper 155 行。session 销毁挂钩自动清。38 条新测试 / baseline 496 → 534 / demo 同 session 同题 5 次调用，backend.retrieve 只跑 1 次。

**L2 LLM 调用缓存**（commit `b24f93c` · 15:24）—— SQLite 持久化层。`_internal/sqlite_cache.py`（212 行）作通用 key→bytes 抽象 + `_internal/llm_cache.py`（389 行）作 wrapper。按 ADR-008 D-3 算法 c 实施 cache key——assistant.tool_calls[].id 按出现顺序归一化为 call_0/call_1 抹掉 provider 端 random id 抖动；tools 列表按 function.name 排序去顺序敏感性；payload 整体 sort_keys JSON dump 后 sha256 取前 24 字符。

reviewer 路径**不接缓存**——reviewer.py 直接调 client.messages_create 不走 invoke_client helper，天然不被 wrapper 覆盖。test_llm_cache.py 加专项硬规则 grep 源码确认。36 条新测试 / baseline 534 → 570。

**L3 book 预热缓存**（commit `8271e6b` · 15:36）—— LRU + 磁盘 pickle 双层。`book_cache.py` 407 行。`WarmedBook` dataclass 含 assembler 本体、content_hash、ingested_at。L3a 进程内 `LRUCache(max_size=5)` + L3b 磁盘 `.bookscope_cache/book_warmup/<session_id>.pkl`。pickle 用临时文件 + atomic replace 避免半写。pickle 选用而非 JSON——vector_store 内部含 numpy array / BM25Okapi pickle 不可 JSON 序列化。26 条新测试 / baseline 570 → 596。

三层 + book-level KG 缓存 + batch 级 KG 缓存合计在 BookScope 工程层形成了一个分工清楚的缓存矩阵：

| 层 | 缓存对象 | 后端 | key 维度 | 命中场景 |
|---|---|---|---|---|
| L1 search | search_chunks 结果 | 进程内 LRU | (session, query, scope, filter, k) | 同 session 同题反复问 |
| L2 LLM | LLM 调用 response | SQLite | messages 归一化 sha256 | 同 prompt 同 messages 重发 |
| L3 book | WarmedBook | LRU + pickle | session_id | session 切回 |
| KG batch | 单 batch entries | SQLite | (chunks, prompt, model) | 同 chunks 重抽 |
| KG book | 整本 KG | SQLite | (all_chunks_text, prompt, model) | 同 epub 重 ingest |

ADR-008 D-1 三层 + KG 两层 = 五层缓存矩阵。每层 key 算法、序列化方式、清理钩子都不同，但底座抽象（LRUCache + SQLiteCache）是共用的。这是 chapter-09 第六节那句话的具体形态——**L1 落不好 L2 / L3 没东西继承**，所以三层是串行而非并发推。

ADR-008 签字那一刻的工程节奏值得记一笔。15:05 L1 commit `2c2428e` 已落（副管理判断 L1 包装 search_chunks 外不动 r2 runtime 不触发"等 r2 稳定"边界）。15:07 作者签字 `ce4aae3`。15:24 L2 commit `b24f93c` 落。15:36 L3 commit `8271e6b` 落。**31 分钟三层全推完**——这是 chapter-09 第五节"签字粒度跟工程操作不可逆性挂钩"的具体形态：缓存层挂在 r2 runtime 外、对业务逻辑零侵入、撤回成本是 `git revert` 三个 commit——所以作者一句话四条工作齐批合理，副管理推动速度从分钟级降到秒级合理。

跟 ADR-008 D-3 cache key 算法的关系做一点实施层简化。D-3 文本描述"按 role 分桶哈希"，L2 实施时简化为整 payload sort_keys dump——分桶的复杂状态机带来的字段级 invalidate 收益当前用不上，但 id 归一化这层稳定性收益（D-3 算法 c 的核心）保留。这是一笔"实施跟 ADR 文本不严格一致但精神一致"的处理——副管理在 commit message 里明示这点，未来读 ADR-008 的人能知道哪部分被简化了。这条做法进 ADR 索引附录 A 的"ADR 写作约定与维护建议"那一段——**ADR 草稿写的是大方向，实施层简化在 commit message 里标清就行，不必反复回 ADR 文本动小字段**。

---

## 八、timing probe 跑出 664x 和 1271x

三层缓存 + KG 两层缓存落完之后，5/18 中午跑 timing probe。这两轮跑实在 chapter-09 第十节那条通用兜底链补完之后——KG 在 minimax 上 ContentFiltered 也兜得住、jieba 本地 NER 接得上、parser 也接了 3 层 autofix——probe 才能真跑完一本。

probe 工具是 commit `51c698e`（5/15 17:54）落的，命名 `scripts/probe_kg_cache_timing.py` 377 行。撤回判定函数 `evaluate_speedup` 提成纯函数——参数对应 exp006 设计第六节的 10x 阈值。撤回触发即 JSON 写入 `failure_reason="cache_speedup_below_10x"`。设计文档里写的阈值不能停在文字层，必须有可执行的判定函数——这是 chapter-09 第六节"设计文档写完后 12 分钟 QA probe 就开始写"那条节奏的具体形态。

5/18 跑出来的数据（数据见 `docs/internal/experiments/data/exp006-kg-cache-timing-anshi-empty-20260518-103523.json` 和 `exp006-kg-cache-timing-mingchao-empty-20260518-104756.json`）：

| 书 | 首次 ingest | 二次 ingest | 三次 ingest | speedup |
|---|---|---|---|---|
| anshi（267 chunks · 5 batch） | 79.74 s | 0.12 s | 0.13 s | **664x** |
| mingchao 卷一（1069 chunks · 18 batch） | 127.14 s | 0.10 s | 0.10 s | **1271x** |

验收阈值是 ≤ 1/10（10x speedup），实测在 1/600 量级。耗时红线远不命中。

二次 / 三次都是 0.1 秒级——book-level 缓存命中走纯 JSON 反序列化 + Pydantic 校验，**LLM call 数 = 0、batch_cache_hits = 0、book_cache_hits = 1**。验证了 commit `2419176` 第四步那条"book-level 命中后 batch 级 SQLite 必须 size 不变"的双层叠加硬约束在端到端真实跑下不破。

probe 跑这两轮中间还修了一个 bug——commit `0869c39`（5/16 早）`probe stats key 单复数对位`。probe 脚本读 sqlite_cache stats 时写的是 `hits` / `misses`（复数），实际返单数 `hit` / `miss`，第一次跑全是 0 显示"加速失败"。单测里全用 mock 数据喂，没人真去查过返的什么。commit message 标题写"首数据 anshi 664x speedup"——bug 修完才看到真数据。

跟着的另一笔是 commit `049caed`（5/16 中午）`KG parser 接 3 层 autofix · 修 mingchao probe LLMFormatError`——KG parser 长期独立长，没人想起来 loop 和 reviewer 第 31 轮加过的 3 层 autofix。chapter-09 第十节那句话在这里第二次重演——**切默认之后的冷门路径只能等相邻工作 exercise 才会暴露**。修完 mingchao probe 才跑得动。

值得记一下"std 在这种实测下不再是必要门"的判断。exp006 设计第三节那条规则——"三次跑求 std 这条不是装样子"——是 chapter-04 v3.3 q5 std 翻车留下的硬规则（memory `feedback_baseline_variance_first.md`）。但在 cache speedup 这种"理论上应该 ≥ 100x"的场景里，三次跑得到的 anshi summary 是 mean=26.66 s / std=45.97 s——std 比 mean 还大，单看 summary 数字毫无意义。真正读得到的信号在 runs 数组里：run 1 = 79.74 s / runs 2-3 = 0.12-0.13 s。**这是"std 作为统计指标在双峰分布上失效"的具体例子**——首次跑跟二次跑不是同一个总体的样本，是两条性质不同的路径（cold path vs warm path），不能合并求 std。下次 probe 设计时应该按 cache_state 分组分别求 std，而不是 3 次合在一起。这条经验进 exp006 第九节的"设计漏洞"那一节作单独一条——std 不是万能的，分布性质先于统计指标。

---

## 九、quality probe 跑齐撞到 reviewer 限制

5/19 跑 quality probe。这是本章的核心素材——不是 cache 写错了字段，是实验设计本身预设错了前提。

quality probe 工具同样在 commit `51c698e` 一并写出，`scripts/probe_kg_cache_quality.py` 416 行。撤回判定函数 `compare_quality_runs` 对应 exp006 设计第六节"5 维度子分单维度 std ≤ 0.5 分"的质量红线。

跑了 4 组 × 5 题 = 20 道作家诊断题，配 minimax + v3.4 prompt：

- 3a anshi empty（commit `589f522` 数据）
- 3b anshi warm（commit `589f522` 数据）
- 4a mingchao empty（commit `589f522` 数据）
- 4b mingchao warm（commit `23bdbce` 数据 · 第十六波先跑一组）

数据见 `docs/internal/experiments/data/exp006-kg-cache-quality-{anshi,mingchao}-{empty,warm}.json`。每组真实跑出来的画像：

| 组 | KG 角色数 | 失败题 | 平均 dur | 答案 ans_len 范围 | reviewer 拿分题数 |
|---|---|---|---|---|---|
| 3a anshi empty | 595（jieba 兜底） | q1 LoopTimeout | 150.6 s | 951-1568 字 | **0 / 5** |
| 3b anshi warm | 87（LLM 主路径） | q1 LoopTimeout | 148.7 s | 0-1612 字 | **0 / 5** |
| 4a mingchao empty | 286 | q4 LoopTimeout | 165.6 s | 0-1170 字 | **0 / 5** |
| 4b mingchao warm | 370 | q3 LoopTimeout | 161.0 s | 0-1348 字 | **0 / 5** |

reviewer 在四组数据上**全部 5 题返空**——错误是 `reviewer_format_error: reviewer returned empty text after 3 attempts`。即便已经接了 commit `0ee345d` 的 empty 重试 + 中性化提示（chapter-09 第十节那条对 reviewer 的兜底），minimax 对 reviewer 评分这种"作家诊断题 + 5 维度结构化打分"组合在三次重试内都拒答。

直接后果——`compare_quality_runs` 函数收到全 null 的 `review.scores`，`per_dim_std` 全部为 0.0，永远返 `validation_failed=False`，等于"reviewer 缺失被默判通过"。撤回判定**逻辑上无法走通**。

这不是 cache 层的问题，是 minimax 在 reviewer 这条调用路径上的稳定拒答（跟第 33 轮 q3 论点铺垫题被 422 间歇拦截是同一类）。要拿到 reviewer 评分必须换 provider（DeepSeek / Anthropic），但那是 Sprint 7 "多 provider 兜底"才解锁的事。

预设错的地方在哪里——回头看 exp006 设计第二节那一句"reviewer：minimax + reviewer_rubric_v1（5 维 25 分制）"。第 31 轮 ContentFiltered 兜底链做完后看到 anshi 5 题能从全挂到平均 18.0/25，就把 reviewer 默认能跑当作了实验前提；但 q3 那次拿到分是间歇性运气，不是稳态。本实验 5 题 × 4 组 = 20 次 reviewer 调用全部返空，才是稳态的 minimax 拒答画像。

跟 reviewer 拒答同步发生的另一件事是 LoopTimeout——q1（anshi 节奏评估）两组都挂、mingchao q3 / q4 各挂一次。dur 207 s 没收敛对照 BookScope 默认 timeout 180 s——agent 在迭代到第 5 / 第 8 轮 search_chunks 时仍在堆 token，到 180 s 触发 LoopTimeout 抛出。这跟 reviewer 拒答是两件事但同时压在同一组数据上：作家诊断题在节奏 / 论点 / 支线密度三种题型上对 LLM 算力的需求本身就高，agent 跑不完 + reviewer 评不动叠在一起，让 4 组数据里"既有完整答案又有 reviewer 评分"的题数为 0。

回头看完成题的 trace 反而有意思的细节——q2（anshi 支线密度）在 empty 跑了 101.2 s / 5 iterations / 4 次 search_chunks，answer 1568 字 / 6 citations，章节覆盖 6 / 7 / 11；q3（anshi 论点铺垫）在 empty 跑了 212.0 s / 8 iterations / 7 次 search_chunks 在 timeout 边沿险过，answer 4296 tokens / 8 citations 覆盖 1 / 6 / 10 / 18 / 29 五个章节。这种"题做出来了但 reviewer 评不了"的状态是案例研究里最值得记的——单看 answer 文本，agent 在 anshi 上的作家诊断答题质量是肉眼可读的厚度；但工程验证维度上拿不到分。**人眼能判断好坏不等于工程能自动判断好坏**——这是 chapter-07 reviewer 走出实验室之后第一次在新书新题型上被破坏。

举一个具体例子。q3 anshi 论点铺垫题答案里这一段：

> 全书论证链是闭环的：序章提出核心命题（历史叙事中混入宣传与神话），第 5—6 章以封常清、高仙芝案例破除"忠臣被冤杀"的君主—奸臣叙事，第 9 章以灵宝之战破除"昏君佞臣作梗"的简单归因，第 18 章以睢阳保卫战揭示过度宣传如何将真实英勇事迹扭曲为鬼故事，第 29 章则以元结语收束。

8 个 citations 覆盖第 1 / 6 / 10 / 18 / 29 五个章节，citation_coverage_ratio = 0.6667。这条答案的厚度在作家诊断题题型上是合格的——结构判断有依据、证据密度够、跨章节连贯性可读、可操作性具体到章节号。但 reviewer 拒答让这道题在 5 维度评分上写不出数字。

这种"答案够好但拿不到分"的状态在统计层面有个直接后果——本章 4 组 × 5 题 = 20 道题里有 16 道是 outcome="success"（answer 长度 951-1612 字 / citations 4-8 条 / dur 101-212 秒），但 average_total = null、min_total = null、max_total = null——summary 段里所有评分相关字段全部 null。这是 BookScope 历史上首次出现"答题成功率 80% 但平均分 N/A"的实验数据画像，跟以往任何一份 batch 数据都不同。下次设计实验前要把"用 ans_len + citation_count + dur + outcome 这种 reviewer 无关指标作为主判定、reviewer 评分作为辅判定"这条写进 probe 模板。

---

## 十、换用多证据链 + 不撤回 book-level cache

reviewer 评分跑不出来不等于 cache 验证不了。换用 4 组数据里能直接读到的替代证据：

**A. KG 角色数差异不来自 cache，来自 LLM 间歇行为**

anshi empty 595 vs warm 87（差 7 倍）——empty 跑那次 LLM batch 全失败，jieba 兜底吃下 538 个人名；warm 跑 warm-up 阶段 LLM 大部分成功，命中 cache 拿到 87 个真 KG 人名。**两条路径走的是不同的兜底层**，不是 cache 写错了字段。

mingchao empty 286 vs warm 370（差 22%）——都走 LLM 主路径，差异在 LLM 间歇拒答某些 batch 的 noise 范围。

**B. 失败题分布跟 cache state 无关**

anshi 两组都是 q1 LoopTimeout（dur 207s / 206s 没收敛）——节奏评估题在 anshi 上的固有不稳，跟第 31 / 32 轮观察的 max_iterations 现象同源。

mingchao empty q4 失败 / warm q3 失败——题目互换，说明 LoopTimeout 触发的是 LLM 单次跑的偶发不收敛，跟 cache 命中或不命中没有关系。

**C. 答案 ans_len 差异在 LLM 单次跑 noise 范围内**

anshi 4 道完成题平均 |Δans_len| = 180 字（占答案 13%）——单次 LLM 跑天然就有这个量级的方差。

mingchao 完成题平均 |Δans_len| = 728 字（占答案 60%）——表面看大，实际主因是 q3 / q4 互换 LoopTimeout 让两题各贡献约 1100 字差（一题完成对一题失败）；扣掉互换题，剩余 q1 / q2 / q5 |Δans_len| = (841 + 428 + 178) / 3 = 482 字，仍在 LLM noise 范围内。

**D. 平均 dur 在 4 组之间差异 ≤ 3%**

anshi 150.6s vs 148.7s（差 1.3%）；mingchao 165.6s vs 161.0s（差 2.9%）。这才是 cache 真正能影响到答题端到端路径的部分——dur 包含 KG 抽取时间，warm 路径 KG 命中省下抽取时间应该体现在 dur 上。但端到端答题里 KG 抽取占比已经很小（timing 实验已经验证 warm 路径 KG ≤ 0.12 s），剩下约 150 s 都是 agent loop 跑 search_chunks + LLM 答题，cache 影响不到这部分。

降级证据链汇总——cache 跟冷算在替代指标上数据一致：

| 维度 | 判定 |
|---|---|
| KG 角色数差异 | 来自 LLM 间歇行为（jieba 兜底触发 / batch 拒答），不是 cache key 漏字段 |
| 失败题分布 | 题不固定，跟 cache state 无关 |
| 答案 ans_len 差异 | 在 LLM 单次跑 noise 范围内 |
| 平均 dur 差异 | ≤ 3%，cache 影响到的部分（KG 抽取段）已被 timing 实验单独验证（664x / 1271x） |
| reviewer 评分对照 | 不可执行（minimax provider 限制），不构成判定证据 |

**结论：不撤回 commit `2419176` book-level cache 层**。Sprint 6 三层缓存 + KG 两层缓存全部保留。

撤回判定走 commit `0e50449` 落进 exp006 第九节正文。判定本身是 RE 在数据齐了之后写的，不是事先编排——这是 chapter-09 第六节那条"决策门控写在前面，不是事后补的免责声明"在 reviewer 限制场景下的反面教材：**门控写在前面是好规则，但门控可能失效；失效后的替代判定是临时立起来的，不是事先准备的**。本章把这个失效过程完整记下来，下次实验设计预设替代指标时有具体参照。

---

## 收尾：性能分层 + 失败实验沉淀的研究资产

性能优化在 BookScope 工程层是分层的。chapter-06 讲第一刀——loop 层 tool 并行、题型路由、fast_path。本章讲第二刀——ingest 层 chunk batch 并发、KG 两级缓存、book-level 持久化、SSE streaming。两刀加上 Sprint 8 三层缓存，五层缓存矩阵 + 两条并发路径，把"用户问题进来到答案出去"和"用户上传到 KG 抽完"两条主路径上能压的都压了。

timing probe 跑出 664x 和 1271x 不是预估，是实测——anshi 79.74 s → 0.12 s、mingchao 127.14 s → 0.10 s。Sprint 6 的工程目标在数据上做到了。

但 quality probe 那一天真正值得记的不是"cache 验证通过"——是"原撤回判定走不通之后副管理怎么处理"。reviewer 在 minimax 上稳定拒答让 5 维度 std ≤ 0.5 分判定逻辑失效，改用 KG 角色数 / 失败题分布 / ans_len / 平均 dur 四条替代证据链做多源判定，最终得出"cache 跟冷算数据一致"的结论，不撤回 book-level cache。

这一笔进 chapter-09 第十节末尾那条 memory `feedback_global_not_single_case.md`——任何 provider 任何错误任何书，不让分析停下。reviewer 路径上还差一层兜底没接——多 provider。这是 Sprint 7 的事。

下次实验设计前 RE 要先做两件事：

1. **probe reviewer 稳定性再决定要不要用 minimax 当 reviewer**——5 题 × 3 次重复跑看 reviewer 拿分覆盖率，覆盖率 < 80% 直接换 provider
2. **撤回判定预设替代指标**——reviewer 评分只是一种证据，本章里 ans_len 差异 + 失败题分布 + 平均 dur 在 reviewer 缺失下兜起了同样的"cache 稳定性"判定，下次设计直接把这两类指标写进撤回 / 验收阈值，跟 reviewer 评分并列作为多证据链，不靠单一指标

这两条已经在 exp006 第九节末尾写明，等 Sprint 7 多 provider 兜底接上 DeepSeek / Anthropic 之后回头补本实验的 reviewer 评分对照——那时第三组数据进来，本章末尾会有一段续记，跟 chapter-09 第十节那种续记同形态。

把"未来事件作为续记钩子"这条做法写明值得一提。chapter-09 第九节那段"起头本身参与到事件中"在本章的延续是——本章是 5/19 写出，但 Sprint 6 收口 + reviewer 限制 + 多证据链替代判定这三件事在 5/15 / 5/18 / 5/19 三个时间点分别发生，本章把这三段串起来写成一篇案例研究文章。Sprint 7 多 provider 接 reviewer 的事还没发生，但本章末尾已经留了钩子等它发生——案例研究的指针跑在事件之前。这是 chapter-09 第九节"案例研究边写边发生"那种节奏的另一种形态——不是事件中起头然后续记，而是事件未发生时就把续记的位置标好。

这条做法对未来代际级切换的副管理有具体参照价值——case-study 不必等所有事都收口才写一段，反而是"留钩子等事件来填"在 BookScope 团队节奏里是合理的产出形态。

Sprint 6 至此整体收口。本章覆盖的 commit 序列 `d888be9` → `e33c37a` → `bdd9a20` → `b12df12` → `2419176` → `d066445` → `6ce2b8f` → `4b53493` → `51c698e` → `0869c39` → `049caed` → `23bdbce` → `589f522` → `0e50449` → `ad6d381` → `333f744` 共 16 个 commit 跨 5/15 到 5/19 五天。

工程层数据点对照一下 chapter-06 第一刀时期的画像：

| 维度 | chapter-06（第一刀 · loop 层） | 本章（第二刀 · ingest 层） |
|---|---|---|
| 主战场 | 用户问题进来到答案出去 | 用户上传到 KG 抽完 |
| 起点耗时 | 90-180 秒单题 | 79-127 秒单本 |
| 终点耗时 | 30-60 秒（深题）/ 3-12 秒（通识） | 0.10-0.13 秒（重读）/ 35-60 秒（首次） |
| 加速倍数 | 通识 8-15x / 深题 2-3x | 重读 664x / 1271x |
| 工程手段 | tool 并行 / 题型路由 / fast_path | chunk batch 并发 / 五层缓存矩阵 / SSE streaming |
| 失败实验素材 | fast_path r2 形态 bug 静默挂 | reviewer 限制让原撤回判定走不通 |

两刀加起来——BookScope 整条用户路径（上传 → 问 → 答）上能压的耗时都压了，从分钟级降到秒级是常态。下一刀切在哪里目前还没看清——可能是 reviewer 路径接多 provider 兜底（Sprint 7）、可能是 chunker 参数归一让 mingchao chunks 不再是 anshi 的 4 倍（Backlog B-3）、可能是 FAISS 索引重建从 lazy build 改成上传时同步生成。这条路径留给 Sprint 7 / 8 / 9 接续。

reviewer 走出实验室是 chapter-07 那天；用户视角走进实验室是 chapter-08 那天；副管理姿态在跨多 sprint 一日内可重复执行是 chapter-09 那天；性能第二刀切到上传那一侧、撞到 reviewer 限制之后用多证据链兜起判定是本章这一周。

失败的实验比成功的实验更值得写——chapter-04 v3.3 q5 std 翻车是第一次、chapter-09 第十节通用兜底链补齐三天是第二次、本章 quality probe 撞到 reviewer 限制是第三次。三次接在一起，BookScope 案例研究的"研究"成分一次次比"工程交付"成分更厚。

---

*第十章草稿到此为止。16 commit 覆盖 Sprint 6 BE 五连 + Sprint 8 三层缓存 + timing probe 实测 + quality probe 撞墙 + 换用多证据链判定。Sprint 7 多 provider 兜底接 reviewer 的钩子留给后续续记。定稿由作者在里程碑点统一润色。*
