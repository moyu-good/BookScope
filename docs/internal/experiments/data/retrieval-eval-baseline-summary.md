# 检索 golden set · BM25-only 基线汇总

**日期**：2026-06-10 · **环境**：无 SILICONFLOW_API_KEY，SessionVectorStore 自然退到 `bm25_only`
**脚本**：`scripts/eval_retrieval.py` · **golden set**：`docs/internal/experiments/data/golden-retrieval-{book}.json`（人工通读 chunk 标注，commit `9a9778d`）
**指标**：recall@k = expected 集合在 top-k 的命中率（按 query 平均）；MRR = 首个命中的 1/rank。

## 基线数字（top_k=10）

| book | chunks | 标注条数（语义/位置/角色） | recall@5 | recall@10 | MRR | 最差类型 |
|------|--------|---------------------------|----------|-----------|-----|----------|
| anshi | 267 | 19（11/4/4） | 0.662 | 0.785 | 0.693 | positional（MRR 0.50） |
| mingchao | 1069 | 20（12/4/4） | 0.667 | 0.808 | 0.564 | positional（r@10 0.75，MRR 0.50） |
| zhinei | 319 | 17（11/3/3） | 0.637 | 0.745 | 0.541 | positional（r@5 0.33，MRR 0.38） |
| kuicheng | 4315 | 18（10/4/4） | 0.380 | 0.426 | 0.397 | positional（**r@5 = 0.000**） |

逐题明细在 `retrieval-eval-{book}-bm25_only-2026-06-10.json`。

## 三句观察

1. **位置找（positional）是 BM25 的系统性短板，四本书全中，书越大越惨。** 根因：contextual header 给每个 chunk 都注入了"第N章"，章号 token 在 BM25 里同时命中全书几千个 chunk，"第 1 章开头"这类 query 在 kuicheng（4315 chunks）上 recall@5 直接归零。位置找本就不该走全文检索——应该走 chapter 字段过滤 + 章内取段，这给 WP3（章节鲁棒性）补了一条定量证据。
2. **语料越大 BM25 越糊。** kuicheng 整体 recall@5（0.380）只有其他三本（0.64-0.67）的六成：主角名"裴谦"出现在几千个 chunk 里，角色找 query（如"乔老湿是个什么样的 UP 主"）的关键词在全书反复出现，真正的"人物首次登场/定义性段落"沉底。角色找在小书上反而是最强项（zhinei 角色找三题全部 MRR=1.0）。
3. **改述型语义 query 是另一类失败。** query 用"盐铁会议""4 万亿刺激计划"这种通行说法，原文写的是"《盐铁论》记载的辩论""4万亿元的刺激计划"，BM25 词面对不上就空手而归（zhinei 两题 recall 0）。这正是 embedding 该补的位置——等有 key 后跑同一套 golden set 的 hybrid 对照，就能定量回答"向量检索值多少分"。

## 标注过程中发现的意外（按严重度排）

1. **同一 epub 两次 ingest 切块结果不同（未定位根因，已绕开）。** zhinei 首次 ingest 产出 398 chunks/159 章，之后 5+ 个独立进程（含固定 PYTHONHASHSEED 实验）稳定产出 319/25，首次结果再也复现不出来；kuicheng 同日同现象（4319/1681 → 稳定 4315/1676）。两版 raw_text 总字符数相同但换行结构不同——脚注行在首跑版本里是短行（被章节正则误判成 159 个"章"），稳定版里是长行。mingchao/anshi 未受影响。golden set 已用文本探针整体重映射到稳定版并人工核对；eval 脚本带 n_chunks 守卫，对不上拒跑。首跑版本的完整 chunk dump 留在 `.tmp_golden/{zhinei,kuicheng}_chunks.cache.json` 作证据。**这个问题值得 BE 接手查 epub 抽取层（loader 的 `_HTMLTextExtractor` / ebooklib 路径）**——同一本书索引不可复现，会让缓存键、持久化 index、跨 session 引用全部失去锚点。
2. **zhinei 章节检测被两类噪声污染。** 目录页每行"第N章"各自成"章"（chapter 1-8 是单 chunk 存根）；各章尾注区复用"第N章"标题，chapter 字段无法区分正文第八章（ch16）和尾注第八章（ch24）。导论正文挂在目录存根的"第八章"下。
3. **kuicheng 文内章号与 chunker 章号漂移。** 原文"第999章"对应 chunk.chapter=1001（网文有缺章/重章），位置类检索按文内章号找会错位——WP3 Phase B（真章号）的直接素材。
4. **zhinei 的 epub 元数据书名带 60 字营销副标题**，被 contextual header 注入每个 chunk，"2020年""百万亿元"等词全书污染 BM25 词频。书名清洗只处理了标点，没处理副标题。
5. **mingchao 是七卷合订**：原文章号每卷重置，chunker 顺序重编 1-158；另有每卷目录 chunk（如 idx 0、254、283），任何含章名关键词的 query 都会先撞上目录 chunk。

## 下一步建议

- 有 SILICONFLOW_API_KEY 的环境重跑四本，拿 hybrid 对照基线（脚本零改动，模式自动切换并写进文件名）。
- baseline 方差：BM25 是确定性检索，单次即可；hybrid 受 embedding 服务影响，跑前先确认同 query 多次结果是否一致，不一致则按 `feedback_baseline_variance_first` 跑 3 次求 std。
- 位置找的修复方向不在检索调参，在工具层路由（chapter 过滤），建议归入 WP3 验收范围。
