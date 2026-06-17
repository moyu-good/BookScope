# BookScope 项目状态

**最后更新**：2026-06-16（第十八波 · 作者定 1.0、转公开文档整理）

---

**第十八波（2026-06-16）· 作者定 1.0 成功、准备 push 公开库,要求把对外文档/教学整理好(暂停开发)**：作者验收三个大改后拍板"这作为 1.0 是成功的",要"对啥也不知道的人把 readme 等各方面说明、教学都整理好",并问 GitHub 上有没有类似项目。
- **竞品调研**：搜了三类邻近工具——chat-with-PDF 的 RAG(pdfGPT/AnythingLLM,引用检索块但不核验引文)、NotebookLM 开源替代(Khoj/SurfSense,通用文档问答)、给小说家的 AI(NovelCrafter/Neural Novelist,多闭源偏"帮写")。结论:完整重合的没有,BookScope 位置 = 「证据优先 + 查询时代理 + 引用核验」用在「单本长书结构化深读」,开源 + BYOK + 不要 GPU + 国内优先。写进了 README 的"相关项目"段。
- **文档大修**(`d426533`)：作者拍板"中文为主 + 精简英文"。重写 README.md 成产品门面(一句话/为什么不用 ChatGPT/5 张实拍截图/13 功能表/正确上手/8 家预设面板/简版架构/技术栈/限制/竞品对比);新建 README.en.md;USER_GUIDE 补「12 个整本书功能怎么用」整节 + 改写 provider 节 + 章节重编号 1-10;ARCHITECTURE 补「主链路三:结构化功能」+ 长上下文默认 + 中性化 KG 内部措辞;Playwright 走 Edge 实拍 5 张截图存 docs/images/;git rm 冗余的 README.zh/ja。修掉过时事实(deepseek-chat→deepseek-v4-flash、minimax 删除、7→13 功能、1083 测试)。匿名化扫描干净。
- **状态**：1.0 文档就绪、可 push 公开库。功能开发暂停(作者明示"暂时不要开发")。
- **临时文件待清**(sandbox 拦删)：scripts/_tmp_*.py、_shot_*.png——未跟踪、不进库,作者手删。
- **下一步候选**(等作者放话恢复开发)：作者用过新版后的反馈微调;case-study 续写;RAG search 收口。

---

**第十七波（2026-06-16）· 作者用过 13 项功能后提的三个大改，按他排的顺序全做完才回报**：作者验收界面，先给三个 polish（功能页太简陋→善本题解卡、左栏书名从内容提取不是文件名、模型默认 flash，已先交付），再提三个大改：
- **① 关系图升级**（`e6851ea`）：从一次性静态布局重写成实时力导向动画——rAF 每帧算向心+斥力+弹簧，弹簧静止长度按"亲疏"强度（越亲拉越近），节点可拖（getScreenCTM 反矩阵换坐标，拖时钉住松手回弹）。后端 GraphEdge 加 strength(1-5)，两份 prompt 让模型只据原文判亲疏。anshi live：33 人物/30 关系/全核验，strength 分布 {1:3,2:3,3:10,4:12,5:2}（安禄山-安庆绪父子=5）。纯手写无图库、不破 GPU 红线。
- **② 运行过程可视化**（`e4e606b`）：作者要"点功能能看运行过程、用了多少 token、读了多少字"。后端 _UsageRecorder 把 client 包一层旁路记 token，13 个结构化端点统一回 trace（input/output tokens + chars + duration_ms，缓存命中记 0 是对的）。前端 runProcess.tsx 两块共享件：RunningProcess（跑时四段流水线 取全书→喂模型→梳理→核验 + 不确定进度扫光 + 计时器，不伪造百分比）、RunStats（跑完一行：通读 X 万字·输入/输出 N tokens·用时·几条）。12 个功能组件全接上。live：关系图 RunStats 实测"通读 39.5 万字·输入 265,114、输出 5,984 tokens·用时 2.0s·30 条关系"。
- **③ Provider/模型官方预设面板**（`a7688f3`）：作者要 model 设官方几个、各家 AI 公司"都安排上"。前端 PROVIDER_PRESETS 8 家（DeepSeek 默认/智谱/通义/Kimi/Anthropic/OpenAI/Gemini/Grok，国内优先），每家带 backend + 官方 base_url + 官方模型下拉 + "自定义"口子。后端零改动——deepseek adapter 本就是 OpenAI 兼容，除 Anthropic 外各家都 backend=deepseek + 自家 base_url。live：切 OpenAI → base_url 自动填、模型变 gpt-4o；切 Anthropic → base_url 字段隐藏。BYOK 不变、默认仍 flash。
- 后端 826 测试零回归、前端 build（51 模块）通过、ruff 干净。runtime backend(:8000) 已重起加载 trace；dev(:5180) 服新前端（本机另有项目占 :5173，没串）。
- **临时文件待清**（sandbox 拦删）：scripts/_tmp_*.py、_shot_*.png——未跟踪、不进库，作者手删。
- **下一步候选**：作者用新版关系图/运行过程/预设面板后的反馈微调；RAG search 收口（大书省钱）；case-study 续写（本程素材：力导向自写 + 旁路 token 观测 + 预设面板解耦后端 Literal）。

---

**第十六波（2026-06-16）· 功能队列 8 个一口气全交付**：作者"继续，而且 loop，把所有的功能都开发好再告诉我"——进连续自主开发模式，逐个走 design-first → probe → build → live → 记一笔，全做完才回报。
- **8 个功能全交付**（每个：设计稿过闸 + 可行性 probe + BE 模块 + 端点 + FE 组件 + 左栏接入 + 单测 + 实测）：① 实体回溯（`f217f51`）② 论点结构（`argument`）③ 文体体检（`style`）④ 前情回顾（`recap`）⑤ 概念演进（`concept`）⑥ 母题追踪（`motif`）⑦ 写作手法（`technique`）⑧ 知识卡片（`cards`）。左栏导航现 13 项。
- **三个功能家族**：input-recall（实体/概念演进/母题，输一个单位回溯 + verify-filter + empty→[]）；one-click extract（论点/文体/写作手法/知识卡片，一键 + verify-filter）；partial-context（前情回顾，只喂 ≤X 章=结构性无剧透）。全照搬 [[project_wholebook_feature_pattern]] 三守卫。
- **命根子全过**：8 个 probe 的命根子假阳性**全 0%**（不存在的实体/概念/母题返空、书反对的论点不编、没用的手法不编、没教的知识点不编、后文不剧透）。evidence-first 在 8 类新功能上一致成立。
- **队列首个 NO-GO→调整**：概念演进 probe 先 NO-GO（抽象概念"国家"引用真实性 82.9%<90%）→ 回设计层加 verify-filter 守卫（核验不过的丢）后建。probe gate 起了作用，诚实记录。
- **scope 两处诚实划界**：母题的"典故外部注释"（靠书外知识违 evidence-first）+ 知识卡片的"完整多轮互动苏格拉底对话"（状态/UI 重）都 v1 不做、留后续。
- **端到端 live 抽查**（重起后端 :8000 后 7 个新端点全过 anshi）：argument 19/19、style 0（自洽不爆报）、recap 18/18（≤15 章）、motif 13/13、concept 4/4、technique 5/5、cards 10/10——全 scanned=true、全 100% 核验。
- 后端 826（agent+api）全过、前端 build（50 模块）、ruff 干净、零回归。运行 backend 已加载全部新端点、:5173 左栏 13 项可用。
- **临时文件待清**（sandbox 拦删）：scripts/_tmp_*.py、_shot_*.png、_tmp_mockup_scholar.html——未跟踪、不进库，作者手删。
- **下一步候选**：作者点试 13 项后的反馈微调；RAG 那支 search 收口（大书省钱）；时间线/出题补归档数据；诗→意象等新题材 probe；case-study 续写（本程素材极厚：缓存攻坚 + UI 重搭 + 8 功能 design-first 全流程 + 首个 NO-GO 案例）。

---

**第十五波（2026-06-16）· 界面收口 + 转性能/缓存**：接十四波，作者验收界面后定下一步方向。
- **界面收口**：作者两轮反馈——① 钤印评点版"还差一口气、跟展示图差一点" → 从 transcript 抠出他认可的 mockup 精确代码逐项对照，补回"案头摊开一本善本册页"的物件感（desk 底色 + folio 圆角描边厚影）、藏书票式左栏（居中竖排藏书印 + 图标导航 + 函套色）、❡ 鱼尾 + 干净引证卡（`3aec619`/`f23cc6c`/`ca2a85c`）；② "余白太多、缩在一个窗口里" → 册页去 max-width 铺满屏幕只留窄桌沿、正文走版心、能力网格大屏 3 列（`74ab5f0`）。Playwright 走系统 Edge 截图核对（preview 截图工具本机卡死，换 Edge 绕过）。作者认可收口。
- **方向定**：作者拍板——主攻**缓存命中率 36%→≥90%（性能总开关）**，同时给时间线+每书出题补归档数据；key 有余额、体裁采书作者自己来。
- **质量验证总表**（`1c9d3ba`）：作者点破"早有大量 logs 别重跑"。把散在 exp004–015 的真实数据汇成 [quality-validation-summary.md](experiments/quality-validation-summary.md)——所有发明区功能在 flash+bm25、4 本不同体裁书上全 GO，**命根子假阳性一律 0%**（evidence-first 真实数据验证）。14 个散落根目录的 raw log 归位到 docs/internal/experiments/logs/。
- **缓存 Phase 1 instrumentation**（`7246271`）：按 WP-agent-token-budget（戴明：先量再砍）给 loop 加 per-tool 体量计量——measure_output_size + 每条 tool 结果落 result_chars/result_tokens_est 进 trace.tool_calls，能按 tool 归因 miss 构成（头号嫌疑=get_chapter_range 整章 full_text）。新测 4 条 + tests/agent 624 过（唯一 fail 是 KG 并发计时 flaky，无关）。
- **缓存攻坚已完成（≥90% 硬目标达成）**：Phase 1 profile 出 miss 肥源=search_chunks 74%（推翻 WP 预判的 get_chapter_range；`2bb0365`）；长上下文钉稳定路实测稳态命中 **100%**（`f5e0ba7`）；硬化解析 lenient+重试把回退 **33%→0%**（`3f9f2b5`）；引用真实性 A/B **长上下文 100% = RAG 100%**（`854eb95`）；据此**转默认**——塞得下的书默认走长上下文（`56e0f6f`），全量 1024 测试过。运行 backend 已重起加载新默认（:8000）。
- **功能队列第 1 个「实体回溯快查」已交付**（`f217f51`）：design-first 过闸 → probe GO（假阳性 0%、引用真实性 91.9%）→ 建成（entity_recall.py + EntityRecall.tsx + 左栏「实体回溯」）→ anshi live 验过（安禄山 60/60、杨国忠 salvage 救回截断、朱元璋命根子返空）。复用整本书结构化模式 + 三守卫。后端 776 过、前端 build 过、零回归。模式跑通：design-first → probe → build → live → 记一笔。
- **未完成 / 交接**：① 功能队列剩 7 个（下一个=论点结构梳理/学习者，按 design-first 逐个）；② RAG 那支 search_chunks 收口（大书省钱，非紧急）；③ 时间线 / 每书出题补归档数据。probe/profile 探针在 scripts/（运行时设 BOOKSCOPE_SMOKE_EPUB + key，书名带 z-library/真名严禁进提交）。临时文件 scripts/_tmp_* 待手删（sandbox 拦删）。
- **临时文件待清**（删除被 sandbox 规则拦）：scripts/_tmp_shot.py、_tmp_keytest.py、_tmp_mockup_scholar.html、_shot_*.png——未跟踪、不会进提交，作者方便时手删。

---

**第十四波（2026-06-15）· 界面重搭**：作者连着两轮锤现有界面——"功能挤在窄单列里没高级感""LLM 设置占太大版面""书柜全是同一本书的历史""没有功能说明""动画少、薄、文案奇奇怪怪"。会话里出了两版草图，作者认可"数字善本案头 · 评点钤印"方向，让我先存设计语言再照着搭。
- **设计语言存档**（`c5fee5e` 后那次 docs commit）：`docs/internal/design/WP-ui-design-language.md` + memory `project_ui_design_language.md`。定位=数字善本/评点本不是通用 SaaS；骨架=app-shell；四个不撞脸的 primitive（钤印核验 / 评点排版 / 函套书脊侧栏 / 古籍细节克制）。
- **单列 → app-shell**：左栏常驻（藏书印「鑒」+ 案上当前书 + 模式导航 问书/关系图/时间线/节奏/一致性 + 底部书库/设置），宽主画布一次只显示一件事。手机端左栏收成抽屉（汉堡 + 遮罩）。原来"壹/贰/叁"往下滚的结构整个换掉；WholeBookTabs 的 tab 升成左栏导航。
- **LLM 设置降级**：从头版大块降进左栏底部的"设置"，点开才是抽屉。头版不再被配置占着。
- **钤印核验落地**（抽成 `web/src/SealMark.tsx`）：核验过的原文角上盖朱砂「鉴」小印（方、1.5px 边、淡底、转 -7deg），盖章=证据核验的视觉语言。问书答案的引证卡（quote/paraphrase 盖、none 不盖）+ 时间线事件 + 一致性两处对照，三处都用同一枚印。
- **评点排版**：答案区改成"朱批（评点）+ 原文为证（引证卡）"，正文换宋体，引证卡带朱砂左线 + 钤印。
- **每件事加了版心标题**：CanvasHeader（宋体大标题 + 版心式朱砂短线 54px + 一句说明），补上作者要的"功能说明"。
- **书架去重**：同一本书上传多次只在书架留最近用过的那个，不再堆 5 条 anshi。
- **验证**：`npm run build` 绿（tsc + vite 都过）；dev server :5173 已服新源码（curl 验过 App.tsx/SealMark.tsx 都是新的）。只动前端，后端没碰、不需要跑 pytest。
- **下一步候选**：作者看完真实界面后的反馈微调；古籍细节再克制收一遍；论点结构/实体回溯/无剧透三个读者学习者功能（已在 ROADMAP）。

---

**第十三波（2026-06-15）· productize + citation 精度 + 修 ship 后的 bug**：作者试用关系图后反馈 UX，连续推进 productize 与 citation 精度，中途修了两个 ship 后的可靠性 bug。
- **关系图入口 UX 改版**（`c03844c`）：作者"区分不明显/不突出，我都以为这是个啥按钮"。素按钮→朱砂红顶边"关系图谱"面板 + 两张图标卡片（人物图/概念图各带描述 + 适用书型）。
- **关系图 502 修复**（`464a8b7`）：作者实测点崩了。根因=reasoning model 吃 token 致大图（anshi 18-47 边浮动）截断→解析失败→502。修=prompt 限规模约30边 + 抢救截断的边。**操作坑**：uvicorn --reload 没加载改动 + L2 缓存了坏响应，清进程树重起干净后端才生效。live 验过人物图/概念图都 200。
- **citation 精度两半**：① 分两类（`43623a4`）match_type 三态徽标（逐字/转述/未核验）；② claim precision（exp-015 GO `b5b2016` + entailment 层 `60ef17a`）——答完自动核非逐字引用撑不撑得起论断、弱支撑标⚠（"只核转述"形态，作者选的成本档）。live 验过。
- **每书自动出诊断题**（`9c12087`+`3b23f7f`）：据整本书出书内专属诊断题（点名书内元素），按需 fetch 省成本。可靠性修同 502 一脉（4000token+关缓存防poison+重试）。live 验过出李归仁/封常清/灵宝之战等书内专属题。
- **本地服务器管理教训**：待机会挂后端；--reload 不可靠（不加载改动）→ 改代码后要清进程树（含 reloader 子 worker 继承 socket）重起无 reload 后端；L2 缓存会 poison（缓存坏响应）→ 结构化输出功能关缓存。
- **教训沉淀**：reasoning model 长输出/结构化输出功能（图、出题）通病——给够 token + 解析兜底/重试 + 别靠缓存，已并进 [[reference_reasoning_model_token_budget]]。
- **节奏曲线可视化建成**（`8e35566`）：逐章张力柱状图（BE 结构化每章张力 + FE 自写 SVG 柱状图、点柱看依据），三教训焊进去、按需 fetch 省 token。live 验过 30 章铺垫章低/战斗章高。**productize 三项全收**（每书出题 + citation 精度 + 节奏曲线）。
- **case-study chapter-12 草稿**（`881727c`）："把验过的能力搬上货架"——本程素材结构化沉淀（chapter-11 测量层母题在输出端的续篇），定稿留作者。
- **设定一致性扫描功能建成**（exp-011 GO → 功能）：主动扫全书找矛盾，双命根子守卫（prompt 滤号称/实有/史料/视角 + 两处证据都核验才留），anshi 自洽书 live 扫 0 条不瞎编。**差异化 A 作家诊断四道全有功能/入口** + 顺手解决 CP2 过敏。
- **差异化全建成**：A 作家诊断（伏笔/弧线/一致性/节奏）+ B 读者关系图 + C 学习者概念图全落地 + live 验过。
- **UI 重构**（ui-ux-pro-max skill 诊断）：整本书分析收进「肆·全书透视」区，朱砂红横线堆叠→分层+点睛、删 emoji。作者反馈待机致浏览器热更断开，杀两 vite 重起一个干净的在 :5173。
- **时间线/事件梳理功能建成**（读者发明区，进肆区）：anshi live 30 事件 29 核验、按时序。长输出截断同关系图 502、8000+抢救修。
- **注意**：「肆 全书透视」现 5 个工具（人物图/概念图/节奏/一致性/时间线），再加（论点结构/实体回溯/无剧透）会重新拥挤——加之前要先定 肆 区的子组织（tab/折叠）。下一程候选：肆 区子组织 + 论点结构/实体回溯/无剧透 / 诗→意象 probe / 百万字 / case-study 续写。所有改动测试零回归（KG 并发计时 flaky 复跑即过）。

---

**第十二波（2026-06-12）· 发明区验证收尾 + 转建设**：接第十一波连续推进，把发明区从验证推进到第一个落地功能。
- **节奏/张力曲线 probe → GO**（exp-012，软一档）：发明区第四炮、最难验的主观连续构念。方法论锚=构念效度（无二元 ground truth 靠收敛+复现+判别）。anshi 曲线方向对（制度章松/战役章紧）、跨 run 核心集稳、假阳性 0%。**差异化 A 作家诊断四炮至此全 GO**。
- **人物关系图 probe → GO**（exp-013）：发明区第五炮、首个读者受众。anshi 抽全面关系网、每边带证据、核心关系跨 run 稳、假阳性 0%。首轮 4000 token 截断暴露建设约束（图输出 ~5000-6000 token），8000 重跑干净——②类结构检索靠长上下文做成、KG 反向复活成立。
- **人物关系图功能 MVP 建成**（commit `9e56753`，走 design-first `WP-character-graph.md` 作者批"继续"过闸）：BE `character_graph.py`（结构化 JSON 抽取 + 边粒度 verify_citations + 章号纠偏）+ 端点 `POST /api/agent/character-graph`（塞得下才抽，大书 422）+ FE `CharacterGraph.tsx`（自写 Fruchterman-Reingold 力导向、点边看原文出处、不引重图库）。anshi 真跑 24 节点 22 边 **22/22 边核验**、章号纠偏生效、40s。18 单测 + 719 全绿零回归 + FE build 过。
- **方法论沉淀**：构念效度锚补登记 methodology-map（wiki）；probe playbook memory 更新五炮 + 主观构念变体。
- **概念图 probe → GO（exp-014，zhinei）+ 概念图功能建成**（commit `2709397`）：泛化关系图成"分析单位=人物|概念"（小改、机制共用）。zhinei 真跑 11/11 边核验、制内市场为中心。FE 双单位按钮（人物图/概念图共用一套力导向组件）。**跨题材图能力闭环**（人物 anshi 22/22 + 概念 zhinei 11/11 双单位端到端验通），兑现 NORTH_STAR 分析单位自适应。
- **前后端起到本地**（FastAPI :8000 + Vite :5174，proxy 通）给作者试人物/概念关系图。
- 剩两件（作者"其他都可以继续"）：① citation 分两类/claim precision（exp-011 CP2 过敏）；② 作家诊断 productize（每书自动出题/节奏曲线可视化）。

---

**第十一波（2026-06-12）· 发明区能力逐个验证 + 兑现到界面**：作者"直接开始，一直跑，design 技能一直用，能并行就并行"。一轮连续推进，3 发明区 probe 全 GO + 2 个 UX 功能 + 1 个地基修。
- **feature 1 诊断题一键化**（commit `39090ca`）：App.tsx 加"深度诊断（作家审稿）"按钮组，surface 伏笔回收/节奏/转变/支线/设定漂移五道发明区诊断题，降"不会问"门槛。
- **feature 3 分析产物导出**（commit `f3e7569`）：AnswerBlock 加"导出 Markdown"，question 存进 payload（实时+历史回放都带），客户端 Blob 下载问/答/原文引用，接"攒发现→改稿"回路。
- **exp-010 人物弧线/动机漂移 → GO**（设计 `08c8c36` + 结果 `9c81847`）：anshi 长上下文，准确率 100%（李隆基/安禄山判准渐变）+ 假阳性 0%（"一夜性情大变""杨贵妃致怠政"虚构突变框架全顶回去）+ 零方差。surfacing 已随 feature 1 ship。
- **exp-011 设定一致性/前后矛盾 → GO**（commit `1ac6a21`）：最硬的跨章对照类（embedding 碰不了）。控制注入 2 处矛盾（左/右手、兵力数字），找到率 100% + 假阳性 0%（自洽话题从不编矛盾还能解释为什么不是矛盾）。
- **citation 章号纠偏**（commit `d2cf156`）：长上下文模型自报章号系统性漂移（exp-009/010/011 都犯），修=snippet verify 命中 chunk 后用 chunk 真章号覆盖（`_long_context_inputs` 填真章号 + `long_context.py` verify 后覆盖）。exp-011 直接验证了这修的必要性。
- **并行实践**：exp-010/011 probe 后台跑、主 Claude 前台同时做 commit / citation 修（in-session Agent 有 bug 不用，走 background Bash）。memory 存 `project_invent_zone_probe_playbook`（probe 复用模式）。
- 测试 581（tests/agent）全绿、ruff 干净、npm build 通过、零回归。下一炮 probe = 节奏/张力曲线；剩 citation 分两类 / claim precision（exp-011 CP2 过敏暴露）。

**第十波（2026-06-12）· 功能审计 → 设计 → 落地**：作者要求重看设计书，审"哪些功能不必要 / 缺什么 / 高星项目能借鉴"，再点破漏了"新功能开发与调研"维度，授权按建议推进、口头"开始/继续"即批。
- **功能审计三栏**（不重复 6/11 audit-conclusion 的 KG/检索/reviewer/citation 四结论）：砍（fast_rating 偏离"给作家深读"定位 / 用户侧 ReviewCard / fast_path 四子路由该瘦身）、补（reranker / 引用点击回跳原文 / 分析产物导出 / 每书自动出诊断题 / RSE 检索段拼接）、借鉴（reranker 提到检索线第一优先 / kotaemon 点击回跳 / RAGFlow 分块可视化）。
- **补的第四栏·发明区**：作者点破审计只做砍-补-抄、漏了项目命根子——没人做过要原创调研的功能（伏笔追踪 / 人物弧线 / 设定一致性 / 节奏曲线 / 跨题材分析单位）。立新功能流程（借鉴 vs 发明 + 发明区先做可行性 probe 两道闸，`docs/internal/design/2026-06-12-new-feature-research-pipeline.md`）。首炮选伏笔—回收配对追踪，probe 设计落 exp-008。memory 存 `feedback_invent_zone_feature_research`。
- **砍用户侧 ReviewCard**（commit `b7b6ef7`）：评分卡 + 重答交互整删，reviewer 回路保留只落后端日志（开发/案例研究仍用），USER_GUIDE 对账 8 处清评分卡 + minimax 残留。
- **reranker 代码**（commit `181d476`）：`reranker_provider.py` 接 SiliconFlow `/v1/rerank`、接进 `r0_search_chunks.py:173`、`retrieval_mode` 四档留痕、默认 `BOOKSCOPE_RERANK=off`、31 单测覆盖跑通/无 key 跳过/API 失败退回三路。golden set before/after 验证待 SiliconFlow key（要先补 hybrid 基线再比，别拿 bm25_only 当 before）。
- **.env 加载**（commit `f109793`）：`bookscope/__init__.py` guarded `load_dotenv`、`.env`/`.env.local` 进 `.gitignore`、`.env.example` 自文档两把 key。CLI 脚本/沙箱从此读得到 key。
- **硬拦路（等作者）**：`DEEPSEEK_API_KEY` / `SILICONFLOW_API_KEY` 两把都不在环境里、也无 `.env`。伏笔 probe（要 DeepSeek flash）和 reranker 验证 + hybrid 基线（要 SiliconFlow 免费档）都跑不起来——作者把 key 填进 `.env` 后即可跑。
- 测试 954 全绿（930 → 954，reranker 新增 31、ReviewCard 改写 1）；ruff 干净；npm build 通过。

**第九波（2026-06-11）· 充值后验证 + 缓存实锤 + flash + 连续追问 Phase 1a/1b**：作者充值 DeepSeek 后连续推进，多个产品级修正与新能力。
- **缓存适配实锤有效**（commit `d3c685d`/`ec4b15e`）：根因查实——固定 17KB 前缀被 citation_hint 错位（拼在变化的 user message 里）+ 问题分析污染。修：citation_hint 移进 system 固定段、user 只留纯问题。实测连发两题不同问题、相同 system，**命中 98%**（5632/5753 token，按 1/50 价）。observability 四处补齐（adapter 透出 cache 字段 / loop 累计 / fast_path 累计 / API model_dump）。深度题 agent loop 受益大；快路径 fast_path 命中率天然低（检索内容每题变，非 bug）
- **模型全切 flash**（commit `159895e`）：作者"全换 flash"。pro→flash 省约 3 倍 + 缓存命中价。**作者 reframe（memory `feedback_flash_mass_user_perspective`）**：flash 是最大众档，从大众视角调试才对，质量分低不是测试期该焦虑的——pro 刷分是自嗨
- **minimax 彻底删除**（commit `800144c`，-564 行）：作者明示弃用，代码层 provider 入口全删，历史文档保留
- **连续追问 Phase 1a**（commit `e6c6208`）：ADR-009 方案 C 第一步——conversation_id/turn_index 骨架 + conversation_store 持久化 + 上轮答案注入 system 可变段。执行代理自守住缓存约束（前情提要不进固定前缀）
- **连续追问 Phase 1b 指代消解**（commit `eb2090c`）：question_processor 加 rewrite_followup——带历史把"哪几章最稀"这种残句追问改写成独立问题，喂给检索/路由/持久化；v2 prompt 新建不动 v1。顺修 question_processor._extract_text 只认 Anthropic 形态的 r2 老 bug（和 reviewer 同根第二例——r2 切 DeepSeek 后拆题/改写一直空转）。**连续追问 Phase 1 完整**（骨架+注入+指代消解），Phase 2 登记表预热待排
- **Python 3.14 升级落定**（commit `bc0e301`/`c2c42a1`）：前序 session 半成品（CLAUDE.md/pyproject.toml/README×3/CI×2/CONTRIBUTING/USER_GUIDE/test_loader）经作者确认保留；repository.py 补 `from __future__ import annotations` 让去引号的前向引用在当前 3.13.4 环境也能跑，自洽收尾
- 测试 893 → 930；DeepSeek 余额已充；bundle 备份 `C:\project file\BookScope-backup-2026-06-11.bundle`（3.9MB）

**第八波（2026-06-11）· DeepSeek 切 v4-pro + 温度调教 + 接管 BE 半成品**：作者"继续，但先切模型"。
- **模型切换**（commit `2426993`）：烟测发现默认 deepseek-chat 别名实际是 v4-flash 非思维模式（该别名 7/24 弃用）。全生产默认切 deepseek-v4-pro（loop_shared / kg_extractor / question_processor / dependencies / schemas / 三脚本 / test 断言）；历史实验脚本 exp004/007 不动保留 flash 记录
- **温度调教**：查 DeepSeek 官方场景表（代码 0.0 / 分析 1.0 / 对话 1.3 / 创意 1.5）；deepseek adapter 补 temperature 参数（缺口，anthropic 早有）；KG 抽取 + 题型分类两条结构化路降 0.0 求确定性，主 loop / reviewer 走默认 1.0；reviewer 温度优化（exp-004 评分一致性问题）留后续实验不擅定
- **接管 BE 半成品**：BE 派去做 WP5 + WP8a 后失联，只搭了 WP5 脚手架（SPIN 常量 / _SearchRecord / 强制综合）但空转逻辑零接入零测试。主 Claude 补完空转检测接入 + 5 测试（commit `8481d9a`）；WP8a rubric 版本管线随后补完接 v2 进生产 + 题型感知解析（commit `716d0f6`）
- **lint 清零**（`c0c1492`）：backfill epub 文件名超长行加 noqa
- 测试 875 → **880 全绿**，全仓 ruff 绿；换模型致 L2 缓存自动失效重算，exp004 等历史数据是 flash 跑的与今后 pro 不可直接比
- **v3.6 对照判定不切**（commit `08b483c`）：v3.5 24.07 vs v3.6 22.68 超 noise 退步，生产维持 v3.5

---

**历史波次已归档**

第一波 ~ 第十六波详细记录在 `docs/internal/build-log/`；第十七 / 十八波及 6/10 当天各段在本节速查。详细提交记录见 `git log --oneline`，每波 commit hash 链见各章节案例研究文档。

主要里程碑速查：

- **Sprint 0（第 16-33 轮）**：工程基础、KG 抽取、API、UI、case-study chapter-01-04 草稿
- **Sprint 1/2/5.5（5/1-5/14）**：并发 batch / 错误兜底 / streaming 进度 / reviewer 接 UI / dogfood
- **Sprint 7（5/13-5/15）**：r2 OpenAI function calling 协议切换，r1 runtime 1693 行 git rm，ADR-007 三次签字
- **Sprint 8 / Sprint 6（5/15）**：三层缓存（L1 search LRU / L2 LLM SQLite / L3 book pickle）落地 ADR-008 签字；KG 全书抽取 + book-level 缓存 + 通用兜底链 5 层
- **Sprint 3（5/18 启动）**：zhinei + kuicheng 两本新书入仓，端到端答题跑通，通用兜底链定型
- **第十七波（5/19）**：quality probe 跑齐 4 组（anshi/mingchao × empty/warm）——reviewer 60 次调用全返空锤实 minimax 拒答（memory `reference_minimax_reviewer_limit.md`），改替代指标判定**不撤回 book-level cache**（commit `2419176`）；chapter-10 + article-12 草稿落地
- **第十八波（6/10）· 停摆 22 天后全面盘点**：作者回来要求梳理设计与目的留存。3 探查代理并发盘 docs/代码/测试（`docs/internal/audit/2026-06-10-project-inventory.md`）——代码测试健康、留存断点集中在"文档落后于现实"。落地：四件文档修正 + ADR-001/004/005 追认 + ROADMAP 重排 + NORTH_STAR 作者签字修订（commit `229958d`/`882c33c`）。**P0 发现**：`loop_shared.py:112` 硬编码 v3.1 自第 26 轮从未改，生产一直跑 v3.1、v3.2~v3.5 从未进产品（memory `project_prompt_v31_regression.md`）；override 机制 Sprint 7 删 r1 后已坏。设计缺口评审 13 条 + OSS 对标（`docs/internal/design/2026-06-10-design-gap-review.md` / `docs/internal/research-notes/002-oss-benchmark-survey.md`）
- **6/10 当天 WP 落地**（第四~七段，均 6/10）：WP0 prompt 版本链修复（生产 v3.1→v3.5、override 死路修复、`CURRENT_PROMPT_VERSION` 单一事实源，commit 链至 `af1a484`）；WP1 citation 可信链 + WP5a partial_evidence（`5f3b716`）；WP2a 检索降级可见（`c717f8e`）；WP3 章节鲁棒性 Phase A+B（`bb008d2`，揭开 mingchao/kuicheng/zhinei 三本章号疑团）；WP2 golden set 74 条标注（`05f0755`，BM25 位置找系统性短板）；**reviewer 翻案修复**（`f99f94a`，根因是 `reviewer.py:_extract_text` 只认 Anthropic 形态——r2 切换起对所有 provider 一律空，exp006"minimax 拒答"错误归因翻案）；**Sprint 3 验收完成**（12/12 batch · 总耗时 20 分钟 · 跨书 std=1.02 ≤ 1.5 过 · verified 率 0.82~1.0）；key 安全清理 + README/USER_GUIDE 刷新（`8c32fa9`/`532435e`）
- **6/11 芯片**：run_batch 元数据三处硬编码修正 + exp004 12 份 backfill（commit `6e6bf06`）——**`BookText.word_count` 口径分界 = 此 commit**（旧 `split()` 数中文字数把 anshi 38 万字记成 3134，改 CJK 按非空白字符计数，旧数据不可与新数据混比）；`getattr(obj, field, 兜底值)` 兜底值陷阱进 memory
- **测试基线演进**：第一波 ~400 → 第十七波 780（含 Sprint 7 r1 删除期 496 谷底后回升）→ 第九波 930

---

**剩工作面（短期 / 长期推进点）**

- **连续追问 Phase 1 真实验收通过**（2026-06-11，flash 跑 anshi 3 轮追问链）：对话 id 串 3 轮、turn 递增 ✓；指代消解工作（"那唐玄宗在这件事里"→"唐玄宗在安史之乱中"）✓；第二三轮答案承接上文 ✓。真跑发现 rewrite max_tokens 300 偏小（flash reasoning 吃光预算偶发 fallback），调 800 修复。文档体系也已去黑话重整（北极星→项目定位 / ROADMAP→开发看板）。**可进 Phase 2**
- **question_processor flash 拆题修复**（2026-06-12，exp008 烟测发现）：拆题在 flash 上偶发 `response missing both 'choices' and 'content'` 然后 fallback——拆题/指代消解/章节推荐全被跳过。直接打 flash 复现查实根因**不是绕过 adapter 归一化**（response 形态正常，`choices` 一直在），是 flash 作为 reasoning model 把 reasoning_content 算进 max_tokens，拆题 reasoning 要 844~1075 token、旧 `DEFAULT_MAX_TOKENS=800` 必截断、`finish_reason=length`、content 返空。修两处：800→2048 给 reasoning 留够余地（复现验证 3/3 正常吐 JSON）；`_extract_text` 在 choices 在但 content 空时报准截断错因不再误报缺字段。补 3 条 flash 形态单测（TestFlashShapeResponse），processor 套 37 全绿、agent 套 570 绿（1 条 KG 并发计时 flake 单跑过，无关）。memory `reference_reasoning_model_token_budget`
- **本波待办接力**：连续追问 Phase 2 登记表预热（当前主线）；reviewer 温度优化（exp-004 评分一致性）留后续实验
- **任务芯片 ×1**：reviewer JSON autofix 两缺口（另一条工作流推进中，工作区曾有未提交改动）
- **case-study 主线**：chapter-00 / 01-10 草稿齐 + 12 篇 article 实质内容齐 · 定稿等里程碑点作者亲笔润色（草稿持续写不催定稿）
- **Backlog B-3** chunker 参数对齐重抽 KG · P1
- **数据口径提醒**：换模型（flash↔pro）致 L2 缓存失效重算，exp004 等历史数据是 flash 跑的；word_count 口径以 `6e6bf06` 为界——跨这两条线的实验数据不可直接混比

**等作者决策项**

- CLAUDE.md 规则文本自带真名字面量待批准脱敏（公开发布前）
- git bundle 打包 / 上传方案（公司不接受 token，走个人机推私有库；公开发布走脱敏树全新历史）
- WP1-8 中尚未排期的工作包方向认可（见设计评审第四节）
- 百万字测试书亲选还是授权 RE 采购（dogfood 当前搁置，作者明示书没写完无对象可测）
