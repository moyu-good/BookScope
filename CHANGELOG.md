# Changelog

All notable changes to BookScope will be documented in this file.

## [1.8.1] - 2026-07-02 · 公文读得更清爽：方针分「有话」和「空话」、要点不注水、卷宗对齐书库

1.8.0 上线后读公文有几处不顺手：方针条款一律显一句「这是方针」、连着看像废话刷屏；要点提取抽不出硬数字时拿「适用范围」「责任主体」充数、显得没要点；办事清单同一句读两遍；卷宗跟书库对不上。这一版把这些理顺了。

### 公文读得更准

- **方针条款分三种看**：以前所有方针都显同一句「这是方向不是办事」，连着五条像废话。现在分开：**话里有话的**（「结合实际」「原则上」这类），点破它的弦外之音（给了自由裁量、留了口子、没时间表）；**有方向的**，一句简述；**纯口号的**，才淡化标一句、不刷屏。
- **逐条精读加筛子**：想只看有弦外之音的那几条、或只看硬要求，点一下就筛出来。
- **要点提取不注水**：一份公文要是以方针为主、抽不出办结时限 / 达标比例 / 金额门槛这类硬指标，就老实说「这份硬指标本就少，不是没抽到」，不拿适用范围、责任主体这类框架信息冒充要点。
- **办事清单不再读两遍**：标题跟下面的原文一模一样时只留一处；纯方向性的条款收进折叠区，不混进要办的事。

### 快了、顺了

- **公文结构秒出**：以前点它要等两分多钟才出一页骨架。现在别的分析跑过就秒出，没跑过也只出骨架、不再陪跑那两分钟。
- **卷宗跟书库对齐**：同一本书不再列一堆重复、每份标出是公文还是小说、还能直接去上传。
- **盖章按钮**：公文分析的「生成」按钮点下去像盖一枚朱砂印，落定再出结果。

## [1.8.0] - 2026-07-01 · 能在书里读了：划句做笔记、AI 批注浮章末 + 公文功能理清爽

这一版 BookScope 有了真正的阅读器。点开一本书就能读，读到哪句想法多就划下来记笔记，笔记跟着书留在书架上。想看深一层，开「AI批」，伏笔和前后矛盾就以朱批浮在当前章的章末，不用跳出去。公文那边把十来个功能理成清清爽爽的几组，抽取也修得更全（公报、意见这类以前抽不全的现在抽全了）。会议记录补上最后一块：读出每个议题背后的立场和没明说的弦外之音。

### 新功能 · 在书里读、划、批

- **阅读器**：点开书直接读，翻页、跳章、调字号。读到哪句有想法，划一下就能加书签 / 高亮 / 写笔记 / 标重点；笔记留在这本书上，回书架能看到哪本书记了几条。
- **AI 批注浮在章末**：读的时候开「AI批」，模型把这一章相关的伏笔、前后矛盾摘出来列在章末，每条能回原文核。想通读全书的分层批注，另有「精读」视图。
- **全书回溯合一**：追一个人物 / 一个概念 / 一个母题在全书怎么走，从前是三个入口，现在合成一个「全书回溯」，选谁追谁。

### 公文 · 功能理清爽 + 抽得更全

- **十来个功能理成几组**：把官话翻成人话、结构标签、术语解释合成一个「逐条精读」；「跟我相关」并进「利害与风向」；关键时间轴并进要点。选择少了，该看的都在。
- **公报、意见这类抽全了**：叙述体公文（如公报）从前逐条款抽不全，现在从个位数抽到上百条；层级式公文（意见 / 批复）按「一、（二）」的层级切开，不再整份糊成一团漏掉条款。
- **不再复读原文**：逐条精读、办事清单遇到"方针部署"这类只表态不办事的条款，从前几乎照抄原文；现在实质条款讲清谁做什么、什么标准时限，纯方向性的老实标「这条是方针、不是具体要办的事」。

### 会议 · 读出立场和弦外之音

- **立场与弦外**：一份会议记录，读出每个议题背后各方的立场，以及没明说但话里有话的地方（逐字稿读得最准，纪要信息少会如实说明）。会议这套工具至此五件到齐。

### 修了什么

- **上传顺手了**：一次能选多本、能拖进来，每本入库带进度；语种从填空改成下拉（中文 / English / 日本語）。
- **"确证为无"和"没扫到"分清**：设定一致性、伏笔、实体回溯里，模型确认书里没有，跟根本没扫到，现在是两回事，不再都显空。
- **叙事曲线不印假精确**：某章的张力从"7/10"改成粗档（偏紧 / 居中 / 偏松）。这个分本就只看相对高低，抠具体数字没意义——我们拿真实语料重复测过，同一章的绝对分会上下抖一档。
- **表单统一善本风**：勾选框、下拉、滑块换成跟整站一致的样式，不再是突兀的白底原生控件。

### 底层改进

- 为将来的托管版打了账号地基（标注按用户存），只在托管形态生效，本地版一字不变。
- 补了一份算法依托溯源的审计：每个分析功能的机制依托哪条国家标准 / 哪篇论文 / 哪次真实语料测试，逐个说清，配套可复现的 probe 脚本进仓。
- 案例研究、设计文档随这版更新。

## [1.7.0] - 2026-06-29 · 会议记录也能读深了 + 公文研判修两处

这一版 BookScope 学会读会议记录了——逐字稿、纪要都吃。上传一份会议记录，它认出这是会议，自动抽出谁拍了什么板、谁该做什么、还有哪些提了没定的事，还能把好几场会摆一起追"谁当初承诺了、到现在兑现没"。公文那边也修了两处研判：公开件不再误标"待核"、国务院这类高层级文件的分量不再被当成一般公文。

### 新功能 · 读懂一摞会议记录

- **行动项台账**：把一场会拆成决议 + 行动项。谁做什么、什么时限、负责人是谁，一目了然；没派到人或没定时限的单独标出来（会议最容易漏的就是这些）。还能按负责人筛「我的行动项」。
- **悬而未决**：把"提了但没拍板 / 没人接 / 还要再议"的议题捞出来——这些是会议纪要最容易漏掉的黑洞。
- **跨会议追承诺**：好几场会摆一起，追每个人的承诺兑现没。谁上次会说下周交、到现在还没影，一眼看到（兑现 / 逾期 / 还在做都分清）。
- **自动认出会议**：上传会议记录自动归类、自动亮出上面这套工具，不用手动选。

### 修了什么 · 公文研判

- **"待核"不再误报**：公开文件本就没有密级，以前显"待核"像没抽到；现在显"公开 / 无密级"——确实没有跟没抽到分开了。意见类公文本就没签发人栏、未标紧急就是平件，同理。
- **效力看发文机关层级**：国务院 / 国办这类顶层机关发的文，以前被笼统判成"一般公文、容易被覆盖"；现在按发文机关行政层级研判，顶层文件点出它的全国约束力，不再一刀切。

### 底层改进

- 为将来的托管版打了账号地基（登录 / 账号 / 按用户存文档），全部只在托管形态生效，本地版行为一字不变。
- 案例研究、设计文档随这版更新。

## [1.6.0] - 2026-06-26 · 看得懂红头文件：BookScope 学会读公文了

这一版 BookScope 不只读书了。上传一份党政公文 / 红头文件，它会认出这是公文，自动换上一套专门读公文的工具：把官话翻成人话、挑出跟你相关的条款、算清每条要求的时限和门槛，还能把好几份文件摆一起看谁依据谁。所有结论照样锚回原文、核得到才算数。

### 新功能 · 读懂一份公文

- **公文结构**：把一份文件拆开摆清楚。发文字号、发文机关、成文日期这些头要素先列出来对照国标看齐没齐；正文逐条排开，每条说清是硬要求还是软倡导、谁去办、什么期限、依据哪份上位文件。
- **大白话翻译**：把公文体官话逐句翻成人话。难的不是「应当于三十日内予以办结」这种文绉绉的话，是看着懂其实没懂的：「原则上同意」留了口子、「研究研究」约等于不办、「由相关部门认定」真规则在别人手里，碰到这类它会点破弦外之意。
- **利害与风向**：报上你的身份，它判这份文件对你藏着什么机会、什么风险，每条标含金量：有主体有时限有考核的是真金白银，只发号召没问责的是空头倡导；再加一段它透出的政策风向（标研判、不冒充事实）。
- **办事清单**：把文件拆成一张能勾的待办，谁去做、到几号、凭哪条，硬要求排最前。
- **跟我相关**：说一句你是谁，只把跟你直接相关的条款圈出来。
- **硬信息提取**：把散落全文的金额、比例、期限、门槛、起止日聚成一张速查表。
- **关键时间轴**：把文件里所有时间点排成一条线，什么时候施行、几号截止、分几个阶段。
- **名词解释**：把专有名词、简称、术语逐个用人话解释，依哪份上位文件定义的也标出来。
- **规范性自检**：对照公文格式国标，看发文字号、署名、成文日期、印章这些要素齐不齐、规不规范。

### 新功能 · 多份公文比对（卷宗）

把相关的几份文件归成一份「卷宗」，三个跨文件视图都跑这一组：

- **依据链网**：把好几份文件的关系画成一张网，谁依据谁、谁落实谁、新文件废了哪份旧的、机关之间谁管谁。
- **政策演变**：按成文日期排成一条线，看一项政策怎么一步步改到现在，每阶段钉一句原话。
- **上下级一致性**：把上位文件和下位文件并排勘对，挑出走样、加码、漏落实的地方，每处上下两栏对照。

选够两份，卷宗里当场给这三个视图的入口，点一下进去，不用回左栏找。

### 更顺手

- **会认文件类型**：上传后自动认出是公文、小说、历史、理论还是别的，把用不上的功能收起来。读公文不显示人物关系图，读小说不显示公文结构。
- **上传支持 Word**：补上了 docx / md，公文常用的 Word 现在能直接传。
- **全站文案说人话**：把功能说明里的机器腔理了一遍，话说得更像人。

### 底层

- 公文这套复用了读书的引擎：一次精读出带原文证据的结构，所有结论锚回原文核得到才盖「鉴」印，推断标「研判」不冒充事实，和读书一个规矩。

## [1.5.4] - 2026-06-26 · 关系图更好用、功能分了组、按书的类型摆功能

这一版把左栏几十个功能理清楚了，关系图重做得更顺手，还让 BookScope 会看书是什么类型、把用不上的功能收起来。

### 更顺手

- **关系图重做**：人物多的书以前又卡、名字挤成一团、想点哪个点不中。现在不卡了，缩放或悬停就看清名字，点击区域放大点得准；颜色也简单了——一个人一个色、谁戏份重谁的点就大，不再用一堆看不懂的分色。
- **左栏功能分成五组**：以前二十来个功能平铺一长条，扫不出哪个干啥。现在按你想干的事归了五堆——「问 & 读」「人物」「情节脉络」「思想 · 理论」「质量 · 写作」，每组能收起来。
- **按书的类型摆功能**：选好一本书，BookScope 会先认它是小说、理论书还是别的，然后把用不上的那组收起来——读小说收起「思想 · 理论」，读理论书收起「人物」。像「论点结构」这种只对讲道理的书才有意义的功能，跑到小说上不会再硬抽出一堆怪结论，而是干脆说一句「这本是叙事，没有论点结构可梳理」。
- **模型设置更新了**：各家模型名换成当前在用的（DeepSeek / 智谱 / 通义 / Kimi / Claude 等），加上了几家的 coding plan 套餐入口，还能自己填模型名。

### 修复

- **关系图里主角的简称能正确归并**：以前像《三国》里的「玄德」会和「刘备」各算一个人、连不到一起；现在简称能并回本名。
- **叙事曲线纵轴换了口径**：改成「能数得清、每个点都能翻回原文」的事件密度，不再是一条说不清来历的曲线。

### 底层

- 选 Anthropic 时不填模型名，默认走到 claude-opus-4-8（和设置面板里写的「默认最强」对上了）。

## [1.5.2] - 2026-06-25 · 大书分析不丢章，人物弧和关系图更好用

这一版主要修大书的可靠性，再把人物弧线和关系图打磨得更顺手。

### 修复

- **几十万到上百万字的大书，分析不再丢章**：以前超长的书（比如上千章的网络小说）出整本分析时，会有些章节被悄悄漏掉；现在每一章都保证被读到、漏了的单独补回来，长书也放心跑。

### 更顺手

- **人物弧线能搜人、按戏份排**：几百号人物的书，以前角色列表铺一屏根本点不过来；现在能搜人名、按戏份多少排序，默认只列主要几位，想看全部一键展开。
- **关系图能缩放、能拖**：一打开自动铺满看得清，可以滚轮放大、拖动平移，几百个人物的大图也理得清；分群更诚实——不再把只有一个人的「群」硬标成「某某一方」，并讲明分群是按「谁和谁常同场」的近似聚类、不是剧情阵营定论。

## [1.5.1] - 2026-06-25 · 关系演变重做成「关系编年」，各图证据对得上结论

这一版把「关系演变」整个重做，又把一批图挂的原文证据修准。

### 重做

- **关系演变 →「关系编年」**：以前是几根看不懂的线，现在挑一对人（或直接搜人名），看他俩的关系一章章怎么走——开头一句总判点透本质（像「互为镜像的枭雄、注定两立的政敌」），再一幕幕排开：哪一回发生了什么、此刻是敌是友、为什么变，每一笔都钉着原文。在关系图里点一个人，直接跳过去看他的关系编年。

### 修准了什么

- **一批图挂的原文，现在真讲这条结论了**：伏笔、设定一致性、叙事曲线、概念图、概念演进、支线这些图，过去给某条结论配的「原文」其实是那一章里最显眼的那句、未必关乎这条结论；现在改成按这条结论去原文里找真讲它的那句，找不到就老实标「待核」、不硬凑。比如一条伏笔，挂的就是埋它那句原话，不再是同章里另一件热闹事。

### 底层

- 关系演变、各图的证据都从「章脉」（整本读一次的逐章带证据记录）派生，同一本书重开秒出。

## [1.5.0] - 2026-06-24 · 大部头也扛得住：整本画出来，分析在大书上修成对的

这一版围着「大书」做。几百万字的网文、几十万字的名著，以前一些图和分析会漏、会糊、会算错——整本塞不进模型，只能截一段看。这版改成整本精读一次、出一份带原文证据的逐章结构，各种图和分析都从这一份派生。大书也跑得动，同一本书第二次打开缓存秒出。顺带把人物关系图、关系演变、伏笔这些重画了一遍。（含原计划 1.4 的输出穷尽化。）

### 新增 / 改进

- **关系图画全书所有人**：一百多回的书就有几百号人，以前只画前 40 个、还堆在中间一团。现在全画（《三国演义》348 人），自动散开看得清，敌红盟绿，点一条线看那一章原文。
- **关系演变（新视图）**：挑戏份最重的几十对，每对一行时间线，线往上走是越来越紧、往下是渐疏，一眼看完谁和谁怎么一章章走到这一步。和关系图分工：那张看「谁连着谁」，这张看「关系怎么变」。
- **山水叙事曲线 / 花鸟人物弧 / 叙事流**：数据补到全量，不再稀稀拉拉；叙事流泳道多了也不再挤成发丝。
- **大书先打个招呼**：点整本分析前，先告诉你这本多大、大概等多久、为什么第一次慢（之后缓存秒出）。

### 修了什么（大书上以前会漏 / 会错的，现在对了）

- **伏笔**：现在追得到跨大半本书的真伏笔。诸葛亮第 53 回断言魏延脑后有反骨、第 105 回应验，这种早埋晚收的；以前只在同章、邻章里打转，长程的全漏了。
- **时间线**：倒叙、插叙也理清真实的故事先后，不再只照书里讲的顺序排。
- **设定一致性 / 概念演进 / 声口 / 支线**：这些要「看完全书才能判」的分析，以前大书塞不进、只看了前面一截就下结论，现在扫得到整本。

### 底层

- **章脉共享索引**：整本书只精读一次，出一份带原文证据的逐章结构；关系图、曲线、伏笔、时间线等十来个功能都从这一份派生，不用每画一张就把全书重读一遍。几百万字也跑得动，重开同一本书命中缓存、秒出。

## [1.3.0] - 2026-06-22 · 精读变成一台真阅读器

以前的「精读」只把有批注的那几章摊出来，字号也调不了。这一版把它做成一台真阅读器：整本书从头读到尾，字号、行距、页边、背景（纸色 / 护眼 / 夜间）、字体随手调，读到哪下次进来接着读。想看脉络时切到「批注」，原文行间浮出带原文证据的朱砂批注（伏笔、矛盾、母题、人物），点开就是支撑它的那段原文。

### Added

- **真阅读器**：整本书按章通读，目录一点即跳，上一章 / 下一章顺着翻。
- **排版随手调**：字号、行距、页边、背景（纸色 / 护眼 / 夜间）、字体（宋 / 黑），调过的设置记住、下次还在；夜间只暗下读书那块，不晃整个界面。
- **接着读**：每本书记得你读到哪章，下次进来直接续上。
- **通读 / 批注两种读法**：纯读用「通读」，看脉络切「批注」（行间朱砂批注，能力照旧）。

## [1.2.1] - 2026-06-22 · 「给目标」连跑多个分析更快更省

「给目标」模式一次会跑好几个分析，每个都得把整本书读进去。之前缓存没接上，每个分析都把整本书重新算一遍、重新等一遍。这版修好了：同一本书在第一个分析之后就缓存住，后面的分析直接命中，不再重复付整本的账。三国（六十多万字）实测，第二个分析起缓存命中率 99%。书越大、一次跑的分析越多，省得越多、等得越短。

## [1.2.0] - 2026-06-18 · 「给目标」模式：说一句话，它把相关分析串起来

以前用书鉴得自己挑功能点。这一版加了「给目标」：在问书里切过去，说你想搞清楚什么（比如"理清这本书的人物分属哪些阵营、彼此什么关系"），它自己决定该跑哪几个分析、按什么顺序，跑完综合成一份结论，每条结论挂得到原文、盖「鉴」印，整个过程摊在你眼前。22 个功能一个没少：知道要看什么就直接点按钮；有目标但不知道用哪个、或想要一份综合，就交给它。

### Added

- **「给目标」模式**：在问书里切到「给目标」，描述你想搞清楚的事，它规划（"我打算跑 X、Y，因为……"）、逐个跑、再综合成带原文证据的回答，综合不掺没原文支撑的话。
- **两扇门连起来**：综合里每块点一下就进对应功能的完整视图；在某个功能视图里也能一键把它跟别的维度串起来看。
- **顺手的建议**：问得比较开放、或连着看了好几个功能时，它会问一句要不要替你编排着跑（嫌烦能在设置里关掉）。

### Known limitations

- 综合的深度受它编排的单个分析的深度限制：目前单个分析只列最核心的部分（比如人物关系图约 30 条关系），所以综合可能不够全——理阵营时可能漏掉次要人物、甚至漏掉某一方。把单个分析做穷尽是后续版本的重点。

## [1.1.0] - 2026-06-18 · 可视化深化 + 精读注释 + 摄入与锚位更稳

这一版把"看见书的脉络"做深了一截，加了一个直接读原文的形态，并把摄入和原文定位的几个老毛病从根上修了。所有结论仍以原文证据为根——挂不上原文的判断一律不出。普通电脑可跑、自带 key（BYOK）不变。

### Added

- **可视化深化**——六张新图，直接看见人物与情节的脉络：
  - 人物叙事流图：谁和谁逐章同场
  - 多维叙事曲线：逐章的张力 / 情感 / 视角 / 主支线
  - 关系随时间演变：两人关系强度逐章升降，转折点配原文
  - 戏份 / 人物弧线：角色逐章的戏份密度与处境起落
  - 伏笔 → 回收弧线：哪个伏笔埋了、收没收，断掉的坑一眼可见
  - 支线编织图：每条支线何时活跃、在哪一章交汇
- **声口一致**：看每个角色说话的腔调稳不稳，标出"这句不像他说的"
- **改稿清单**：把一致性 / 伏笔 / 节奏 / 文体的诊断发现，聚成一张可勾选（待改 / 已改 / 不改）、可导出的修改清单
- **精读注释层**：读原文时行间浮出带证据的批注（伏笔、母题、矛盾、人物），点开就是支撑它的那段原文
- **格式扩大**：支持 docx、markdown、多文件系列（几十个 txt 当一本书读）
- **静态演示**：不用配 key、不用起后端，点进网页就能试，样本取自公版书的真实运行

### Fixed

- **原文锚位更准**：同一句话在多章重复出现时，引用不再贴错章——这条改善了全站所有功能的原文证据定位
- **章节识别对"脏书"更稳**：带目录、卷首摘录、重复回目的真实电子书不再把章号数错（某 120 回的书此前会被数成 240 章）；识别不出时安全退到顺序编号、绝不丢章

## [1.0.0] - 2026-06-17 · 首次公开发布

公开发布到 [github.com/moyu-good/BookScope](https://github.com/moyu-good/BookScope)，品牌「书鉴·BookScope」。核心：查询时智能代理 + 以原文证据为根的书籍深度分析——拒绝"批量预处理 + 静态展示"，所有结论现场由代理依据原文生成。此前的 `0.x` 为公开发布前的开发期版本（见下）。

## [0.10.0] - 2026-04-20 · r0 冻结 + r1-agent-loop 代际启动

本版本把项目从"批量预处理 + 静态展示"（r0/v7）整体切换到"查询时智能代理"（r1）。v7 独有代码通过 `git mv` 全部归档到 `legacy/v7/`，保留历史；r1 代际在 `bookscope/agent/` 下从零搭起，对外文档体系同步重建。

### Added

- **r1-agent-loop 代际**：查询时智能代理架构骨架全部落地，位于 `bookscope/agent/`
  - `tools/`：`search_chunks` / `get_chapter_range` / `list_characters_in_chapter` 的 Pydantic schema、dispatcher、以及 `ChunkRetrievalBackend` / `ChapterTextBackend` / `CharacterIndexBackend` 三个 Protocol
  - `backends/`：`R0SearchChunksBackend` / `R0ChapterRangeBackend` / `R0ListCharactersBackend` 三个 r0 数据接入实现 + `R0BookAssembler` 一键装配层
  - `adapters/`：`LLMClient` Protocol + `DeepSeekAdapter`（默认）+ `AnthropicAdapter`（备选），lazy import 各家 SDK
  - `loop.py`：`AgentLoop` 核心类，包含 duck-typed client、message loop、tool dispatch、citation 强制、失败重试、超时、LoopTrace 全链路
  - `prompts/`：版本化 system prompt（`loop_system_prompt_v1.md` + `citation_format_v1.md`）
  - `models.py`：`AgentQueryResult`、`LoopTrace`
  - `errors.py`：`AgentError` 层级 + provider 层 `ProviderError` / `ProviderUnavailable` / `RateLimited` / `ContextLimitExceeded`
- **架构决策记录（ADR）三份**
  - ADR-001：r1 三个 tool 接口规范，只做 3 个 tool，统一 `ToolResultBase` + `source_version` 追溯字段
  - ADR-002 v2：agent loop 技术选型（驳回 v1 锁定 Anthropic 的决策，改为"默认 DeepSeek function calling + Anthropic 备选 + provider-agnostic adapter 层"）
  - ADR-003：provider adapter 层设计，内容包括 `LLMClient` Protocol 契约、adapter 清单（DeepSeek / Anthropic / 后续 GLM / Qwen / Kimi）、OpenAI ↔ Anthropic 格式转换规范
- **长期工作手册与运行时核心文件**
  - `docs/internal/WORKFLOW.md`：十二节 CEO + AI 团队工作手册
  - `docs/internal/DEPUTY_MANAGER.md`：副管理模式完整操作手册（auto-accept 清单 + escalation 触发条件 + 汇报格式）
  - `docs/internal/NORTH_STAR.md` / `docs/internal/STATE.md` / `docs/internal/FLAGS.md`：方向、状态、告警三件套
- **文档目录七件套**：`docs/` 下新建 `build-log/` / `dogfood-notes/` / `architecture-decisions/` / `research-notes/` / `experiments/` / `reflections/` / `case-study/`
- **实验 001 设计**：`docs/internal/experiments/001-baseline-comparison-mingchao.md`，对《明朝那些事儿》第一卷的 6 对照组 × 5 题 × 3 维 rubric 横评设计
- **研究笔记 001 v1**：`docs/internal/research-notes/001-agentic-rag-landscape-v1.md`，agentic RAG + 长文本推理 + 书籍级 QA + grounded generation 四主线 13 篇 paper 地图
- **不变量"LLM provider 国内优先"**：写入 `docs/internal/NORTH_STAR.md`，首选 DeepSeek / GLM / Qwen / Kimi，Anthropic / OpenAI 降为备选；所有 LLM 调用必须 provider-agnostic

### Changed

- `AgentLoop` 默认 model 从 `claude-sonnet-4-6` 切到 `deepseek-chat`
- `CLAUDE.md` 重写为 r1 代际的入口文档：身份匿名化硬规则（禁止真实姓名 / 公司名出现）+ 项目目的三条 + 代际管理表 + 核心文件必读顺序 + 副管理模式
- `README.md` / `README.zh.md` / `README.ja.md` 三份 README 全部重写，反映 r1 代际现状
- `VERSION` 由 `0.9.3` 升至 `0.10.0`（minor 级跃迁，标记代际切换）

### Deprecated / Archived

- v7 三阶段流水线及全部独有代码归档至 `legacy/v7/`（167 个文件用 `git mv` 保留 git history）
  - `bookscope/{nlp, services, api, eval, viz, insights.py, app_utils.py, config.py}`
  - `bookscope-frontend/`（御览模式 React 前端）
  - `app/`（Streamlit 入口）
  - 根层 v7 文件：`PLAN.md`、`TODOS.md`、`landing.html`、`book-analyzer-project-plan.md`、`viz-module-design.md`、`render_gilded_library.py`
  - `scripts/inject_analysis.py`、`scripts/benchmark_embedding.py`
  - `tests/` 下 30 个 v7 测试文件
- `legacy/v7/README.md` 做归档导航

### Removed

- 临时 inject 脚本（`bookscope/api/routers/inject.py` + 根层 `inject_mingchao.py`），r1 不再需要无 API key 场景下的 KG 手工注入

### Fixed

- 清理项目文档里残留的真实姓名与系统用户名路径片段，统一使用 `moyu-good` 或职能称谓

### Internal

- Tests：r1 新套件 162 用例全绿（`tests/agent/`），覆盖三个 tool schema / dispatcher / 三个 r0 backend / 装配层 / `AgentLoop` 主循环 / 两个 adapter 的格式转换；r0 基础设施测试 133 个保持全绿
- Git：建立 `r0-baseline` 分支冻结 v7 最后状态（commit `3bd9676`），`r1-agent-loop` 为当前主线；每轮产出独立 commit，便于追溯
- Memory：长期偏好 `feedback_china_llm_first.md` / `feedback_anonymization.md` 等归档入 memory 体系

## [0.9.x] - 2026-03-28 至 2026-04-19 · v6 / v7 迭代（summarized）

本段期间的工作不在此 changelog 单独逐条列举，汇总要点如下（详细记录见 `legacy/v7/` 下的历史文档）：

- v6：御览模式前端落地（`ImperialBrush` / `MemorialSection` / `VermillionAnnotation` 等组件），以及 V2 / V3 共 13 项 UI/UX 修复
- v7：三阶段分析流水线（`chunk_scanner` → `chunk_selector` → 深度分析），从 v6 盲采样 20% 覆盖提升到全量覆盖
- 性能：分析耗时从 ~40 分钟降到 ~2 分钟
- `TransformerAnalyzer` 因要求 GPU 才可跑，在 Web 产品定位下被移除（无 GPU 不变量写入 NORTH_STAR）

## [0.5.2.0] - 2026-03-27

### Added
- **spaCy NER for character extraction** — `extract_character_names` now tries
  `spacy.load("en_core_web_sm")` first (proper PERSON entity recognition, handles
  multi-word names, eliminates common false positives). Falls back to regex NER
  automatically if spaCy / the model is not installed — zero behavior change for
  existing users. Enable with: `pip install -e ".[spacy]"`.
- **`[spacy]` optional extra** in `pyproject.toml` (`spacy>=3.7.0,<4.0.0`).
  `requirements.txt` includes the spaCy model wheel for Streamlit Cloud.
- **CJK genre labels in fiction Quick Insight** — `_EMOTIONAL_GENRE` ZH/JA labels
  (already defined in the mapping) are now displayed for Chinese and Japanese users.
  Previously the fiction headline card showed only arc + emotion name for non-EN users;
  now it shows the localized genre label (e.g. "心理悬疑 — 乐极生悲 ↗↘").

## [0.5.1.0] - 2026-03-27

### Added
- **Demo mode** — "📖 Try with a demo book" button on the welcome screen; loads a
  20-paragraph embedded story ("The Lighthouse Keeper's Last Storm") so visitors can
  explore all features without uploading a file. Demo badge + "× New analysis" clear
  button shown in the main area. Demo state cleared automatically when a real file/URL
  is provided.
- **`app/demo_book.txt`** — embedded demo story; Man-in-a-Hole arc, strong emotion mix,
  designed to exercise all 7 Full Analysis tabs and Quick Insight cards.
- **`requirements.txt`** — Streamlit Cloud compatible dependency list, kept in sync with
  `pyproject.toml`. Streamlit Cloud also auto-installs the `bookscope` package via
  `pyproject.toml` at build time.

## [0.5.0.0] - 2026-03-27

### Added
- **Load saved analysis from sidebar** — `▶ Load` button on each saved entry resumes a
  prior analysis instantly without re-uploading. Loaded badge + "× New analysis" clear button
  shown in main area. Save button hidden when viewing a saved result.
- **`detected_lang` field in `AnalysisResult`** — persisted to JSON (backward-compatible,
  defaults to `"en"` for old saves) so loaded analyses display the correct language label
  and drive CJK-aware features.

### Fixed
- **Chunks tab guarded for saved results** — shows info message instead of crashing when raw
  chunk text is not available (saved analyses store only scores, not source text)
- **Quick Insight `chunks=None` guards** — character extraction, key-theme extraction, and
  first-person density now handle `chunks=None` gracefully (return `[]` / `0.0`)
- **Export tab `detected_lang`** — analysis results exported/saved now include detected
  language field

## [0.4.0.0] - 2026-03-27

### Added
- **Quick Insight mode** — book-type-aware insight cards (headline + 3-col grid + "Who it's for")
  replacing the 7-tab view for general users; Full Analysis mode preserves all existing tabs
- **Book type selector** in sidebar (Fiction / Academic / Essay) — user-selected before upload,
  drives Quick Insight card content (no unreliable auto-detection)
- **`bookscope/insights.py`** — zero-new-dependency helpers: character extraction, key themes,
  readability grade, SVG sparkline, first-person density
- **`bookscope/app_utils.py`** — shared language/mode persistence via `st.query_params`
  (survives page navigation) + Google Fonts CDN injection
- **Language persistence across pages** — `?lang=` query param written on change; compare page
  reads it on load, language no longer resets when navigating main ↔ compare
- **Font override by language** — Instrument Serif + Inter (EN), Noto Serif/Sans SC (ZH),
  Noto Serif/Sans JP (JA); injected with `!important` to override OS system fonts
- **Compare page full i18n** — all labels, headers, captions in EN/ZH/JA
- **PDF support in compare page** — file uploader now accepts `.pdf` alongside `.txt` and `.epub`
- **Emotional genre classification** (EN fiction) — 11 arc×emotion combos mapped to reading-group
  recommendations; CJK books show emotion profile without uncertain genre labels
- New pytest tests for `bookscope/insights.py` (35 tests)

### Fixed
- **XSS via `unsafe_allow_html=True`** — all user-derived strings (book title, arc name,
  emotion name) now HTML-escaped before injection
- **`langdetect` non-determinism** — `DetectorFactory.seed = 0` in both pages for reproducible
  language detection inside `@st.cache_data`
- **PDF title stripping in compare page** — `.pdf` suffix now removed from book title display
- **`bookscope/app_utils.py` location** — moved from `app/ui_utils.py` into installed package
  to eliminate fragile `sys.path.insert` pattern
- **Sparkline zero-division** — flat valence series (common for CJK books) returns midpoint
  line instead of crashing
- **Character extraction CJK guard** — returns `[]` for ZH/JA/KO text immediately (no false
  positives from regex NER)
- **CSS animation replay** — session-keyed class prevents stagger animations replaying on
  every Streamlit widget interaction
- **disgust color** changed from `#a855f7` (clashed with purple accent) to `#84cc16`

### Changed
- `app/main.py`: mode toggle (Quick Insight / Full Analysis) appears below hero card;
  book type selector moved to sidebar (before upload); query_params language persistence
- `app/pages/02_compare.py`: full trilingual i18n, PDF support, language sync, langdetect seed
- `.streamlit/config.toml`: background `#0d1117`, card `#161b22`, text `#e6edf3`

## [0.3.0.0] - 2026-03-27

### Added
- Full trilingual UI (English / 中文 / 日本語): sidebar language toggle switches all labels,
  descriptions, tab names, arc names, and metric help text instantly without re-running analysis
- Hero insight card at top of analysis page: book title, one-sentence story summary,
  dominant emotion badge (color-coded), localized arc name with shape arrow, word count, chunk count
- Modern dark theme: deep navy background, purple accent (`#7c3aed`), gradient hero card,
  frosted-glass metric tiles, plain-language chart descriptions for general users
- Localized arc names — ZH idioms: 乐极生悲 / 好事多磨 / 回光返照 / 白手起家 / 盛极而衰 / 跌入谷底
- Localized arc names — JA: イカロス / シンデレラ / オイディプス / どん底からの成功 / etc.
- Emotion labels translated in bar charts, timeline selector, and chunk explorer (all 3 languages)
- Style metric labels and help text translated in Style tab
- Centered welcome screen with hero layout replaces plain info message

### Changed
- `app/main.py`: complete UI rewrite with i18n string dict, hero card HTML/CSS, language state
- `.streamlit/config.toml`: `primaryColor` updated to `#7c3aed` (purple)

## [0.2.0.0] - 2026-03-27

### Added
- Multilingual support: automatic language detection (English / Chinese / Japanese) via langdetect
- Chinese emotion analysis with jieba tokenization and bundled NRC Chinese lexicon (`nrc_zh.json`)
- Japanese emotion analysis with janome tokenization and bundled NRC Japanese lexicon (`nrc_ja.json`)
- CJK-aware word count: non-whitespace character count used as word proxy for Chinese and Japanese text
- Janome Tokenizer instance cached with `@lru_cache` to avoid 25–90 ms reload per chunk
- Language flag displayed in Overview tab (🇬🇧 / 🇨🇳 / 🇯🇵) alongside detected language name
- Test files: `test_book_zh.txt` (4-chapter Chinese), `test_book_ja.txt` (4-chapter Japanese)
- QA report: `.gstack/qa-reports/qa-report-localhost-2026-03-27.md` — health score 97/100

### Fixed
- ISSUE-004: `ChunkResult.word_count` returned 0–1 for CJK text because `model_post_init` used space-based splitting; chunker now passes `word_count=_word_count(text, lang)` explicitly
- Duplicate entries removed from `nrc_ja.json`: おびえる (fear ×2→×1), まさか (surprise ×2→×1)
- Unused `EMOTIONS` constant removed from `bookscope/nlp/multilingual.py`

### Changed
- `tests/test_multilingual.py`: 14 new tests covering CJK word count, language normalization, ISSUE-004 regression

## [0.1.0.0] - 2026-03-27

### Added
- Initial implementation of BookScope — multi-dimensional book text analysis and visualization tool
- Support for `.txt` and `.epub` file ingestion with HTML extraction and EPUB parsing
- Emotion analysis via NRCLex lexicon with per-chunk scoring for 10 emotion dimensions
- Style analysis: TTR, sentence length, noun/verb/adjective/adverb ratios
- Narrative arc classification (Freytag, Hero's Journey, Tragedy, Cinderella, Oedipus, Man in Hole, Linear)
- Streamlit UI with 7 analysis tabs: Overview, Heatmap, Timeline, Style Radar, Arc Pattern, Export, Chunks
- Book comparison page (`/compare`) — overlay emotion timelines and valence arcs for 2 books
- JSON persistence via Repository store
- 145 pytest tests (unit + Hypothesis property tests), 97% coverage

### Fixed
- CORS config conflict: `enableCORS = false` conflicted with `enableXsrfProtection = true` default — changed to `enableCORS = true`
- Info text on Overview tab now correctly mentions both `.txt` and `.epub` upload formats

### Changed
- `.hypothesis/` excluded from version control (auto-generated test data)
- Local editor settings excluded from version control (session-specific)
