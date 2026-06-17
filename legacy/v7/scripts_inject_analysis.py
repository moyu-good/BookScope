"""Inject high-quality analysis data into the 明朝那些事儿 session.

Based on actual reading of book chunks. This replaces the sparse auto-generated
KG data with comprehensive, content-grounded analysis.
"""

import json
import shutil
from pathlib import Path

SESSION_PATH = Path("data/sessions/2ae908744956.json")
BACKUP_PATH = SESSION_PATH.with_suffix(".json.bak")


def build_knowledge_graph() -> dict:
    """Build a comprehensive knowledge graph from actual book content."""

    overall_summary = (
        "《明朝那些事儿》第一部以诙谐幽默而又不失深度的笔法，讲述了明朝从建立到靖难之役结束的历史。"
        "全书以朱元璋的传奇人生为主线——从一个赤贫的放牛娃、在饥荒中失去全部亲人的孤儿、"
        "四处乞讨的游方和尚，到投身红巾军、在群雄逐鹿中以弱胜强击败陈友谅和张士诚、"
        "北伐驱逐蒙元、建立大明王朝的开国皇帝。建国后，朱元璋以铁腕治国，"
        "胡惟庸案牵连三万余人废除丞相制度，蓝玉案再诛一万五千人清洗武将集团，"
        "空印案和郭桓案波及全国官僚体系。作者以'权力对人性的异化'为暗线，"
        "展现了朱元璋从苦难中崛起的英雄如何一步步变成被权力彻底改变的铁血帝王。"
        "全书以朱元璋驾崩、建文帝朱允炆继位后急于削藩引发靖难之役、"
        "燕王朱棣历时四年从北平起兵最终攻入南京夺取皇位作为终章，"
        "建文帝的下落成为千古之谜。作者用现代人的视角重新解读历史，"
        "将古人的抉择放在人性的框架下分析，让六百年前的故事鲜活如昨。"
    )

    book_outline = (
        "一、苦难起源（序章-第2章，chunk 0-3）\n"
        "朱元璋出身赤贫，祖上数代皆为佃农，连名字都只能用数字——朱重八。"
        "1344年，元末大饥荒与瘟疫同时降临，短短半个月内，父亲朱五四、"
        "母亲陈氏、大哥朱重四相继饿死。17岁的朱重八连安葬亲人的土地都没有，"
        "靠邻居刘继祖施舍了一块坟地。走投无路之下出家为僧，"
        "但寺庙也断了粮，被迫外出化缘——实际上就是沿淮西一带乞讨三年。"
        "这段刻骨铭心的苦难经历，是理解朱元璋一生行为的密钥。\n\n"
        "二、投军崛起（第3-6章，chunk 4-10）\n"
        "至正十二年，儿时伙伴汤和写信劝朱重八投奔红巾军首领郭子兴。"
        "朱元璋到濠州城差点被当作奸细杀掉，郭子兴看他面对死亡毫无惧色，"
        "收为亲兵。他作战勇猛、处事冷静、深谋远虑，迅速脱颖而出，"
        "并娶了郭子兴养女马氏（后来的马皇后）。在定远收编散兵建立嫡系部队，"
        "收得徐达、常遇春等猛将。采纳'高筑墙、广积粮、缓称王'策略，"
        "渡江攻占集庆（南京），正式建立争霸根据地。\n\n"
        "三、群雄争霸（第7-12章，chunk 11-37）\n"
        "这是全书最精彩的华章。元末三大势力——朱元璋、陈友谅、张士诚三足鼎立。"
        "陈友谅兵力最强、手段最狠，弑主自立控制长江上游；张士诚最富、地盘最好，"
        "占据江浙鱼米之乡。朱元璋在谋士刘基的建议下，决定'先强后弱'——"
        "先打最强的陈友谅。洪都之战中，朱元璋的侄子朱文正以四万守军抵挡"
        "陈友谅六十万大军长达八十五天，创造了战争史上的奇迹。"
        "鄱阳湖决战更是史诗级的高潮——朱元璋的小船对阵陈友谅的三层铁甲巨舰，"
        "火攻、肉搏、诈降、反击，每一个转折都惊心动魄。"
        "最终陈友谅中箭身亡。随后围攻张士诚的苏州城，张士诚困守到底，"
        "城破后纵火自焚未死，被俘后自缢而亡。\n\n"
        "四、北伐驱元（第13-15章，chunk 38-57）\n"
        "统一江南后，朱元璋发出'驱逐胡虏，恢复中华'的北伐檄文，"
        "这是汉族政权时隔近百年向蒙元发出的宣战书。徐达、常遇春率军北上，"
        "势如破竹收复大都，结束蒙古统治。常遇春在北伐途中暴病而亡，年仅四十。"
        "远征沙漠追击北元残余，名将王保保（扩廓帖木儿）成为明军最顽强的对手。\n\n"
        "五、铁腕治国（第16-22章，chunk 58-119）\n"
        "朱元璋定都南京，国号'明'，取光明之意。着手构建严密的帝国制度——"
        "八股取士、卫所制度、户籍制度。然而伴随建国的是大规模政治清洗："
        "胡惟庸案以谋反罪诛杀丞相，牵连三万余人，朱元璋借此永久废除丞相制度；"
        "蓝玉案清洗武将集团，再杀一万五千人，开国功臣几乎被屠戮殆尽。"
        "空印案和郭桓案波及全国官僚，朱元璋发明了'剥皮实草'等酷刑惩治贪腐。"
        "作者深入分析了这个从底层爬上来的皇帝为何如此残暴——"
        "对饥饿的恐惧转化为对权力的极端执着，对贪官的仇恨演变为不分青红皂白的屠杀。"
        "然而他也是唯一一个真心为农民减负的皇帝。\n\n"
        "六、帝位之争（第23-31章，chunk 120-168）\n"
        "朱元璋晚年，太子朱标英年早逝，他力排众议立年幼的孙子朱允炆为继承人。"
        "1398年朱元璋驾崩，建文帝即位后急于削藩，连废数王。"
        "最强的燕王朱棣在谋士姚广孝的策划下以'清君侧'为名起兵。"
        "靖难之役历时四年，建文帝一方虽然兵力占优但用人失误——"
        "信任纸上谈兵的李景隆而弃用老将耿炳文，又因'不要让我背上杀叔叔的名声'"
        "的命令束缚了军队手脚。铁铉在济南城死守挡住朱棣南下，方孝孺以死殉节，"
        "成为全书最悲壮的场景之一。朱棣最终攻入南京，建文帝在宫中大火中失踪，"
        "其下落成为明史最大的悬案。"
    )

    themes = ["权力与人性", "草根逆袭", "政治博弈", "历史叙事", "乱世生存"]

    theme_analyses = [
        {
            "theme": "权力的代价",
            "description": (
                "全书最深层的主题是权力对人的异化。朱元璋从一个为生存而挣扎的穷人，"
                "变成了为权力而杀戮的帝王。他杀功臣、灭丞相、屠贪官，每一步都有其逻辑——"
                "胡惟庸确实在揽权、蓝玉确实跋扈、贪官确实横行——但累积起来呈现的是"
                "一个被权力彻底改变的灵魂。最讽刺的是，他屠尽功臣是为了保护孙子朱允炆的皇位，"
                "结果正因为无人可用，朱允炆才在靖难之役中惨败。"
            ),
        },
        {
            "theme": "小人物的命运与抗争",
            "description": (
                "作者始终关注大历史洪流中个体的命运。朱元璋从最底层崛起，证明了"
                "'英雄不问出处'；朱文正以纨绔之名镇守洪都创造战争奇迹，颠覆了所有人的偏见；"
                "铁铉以一介书生之身在济南城挡住朱棣大军；方孝孺面对灭十族的威胁仍然拒绝为朱棣撰写即位诏书。"
                "这些小人物在历史转折点上的选择，构成了全书最动人的篇章。"
            ),
        },
        {
            "theme": "以史为鉴的现代叙事",
            "description": (
                "当年明月用现代人的视角和语言重新解读历史，将古人的选择放在人性的框架下分析。"
                "他用'档案'形式介绍朱元璋、用经济学分析私盐贩卖、用心理学解读陈友谅的性格缺陷、"
                "用管理学评价朱元璋的用人之道。这种跨越时空的对话，让读者感受到历史不是冰冷的记载，"
                "而是一个个鲜活的人在特定处境下做出的选择——与我们并无不同。"
            ),
        },
        {
            "theme": "乱世生存法则",
            "description": (
                "元末群雄并起的章节深入探讨了乱世中的生存智慧。'高筑墙、广积粮、缓称王'"
                "是全书最经典的战略哲学——当别人急着称王称帝时，朱元璋默默积蓄实力。"
                "先打最强的陈友谅而非最弱的张士诚，体现了'真理往往站在少数人一边'的决策勇气。"
                "这些智慧穿越六百年依然具有现实意义。"
            ),
        },
        {
            "theme": "制度与人治的困境",
            "description": (
                "朱元璋试图通过制度设计来保证王朝的长治久安——废丞相、建卫所、定户籍、严刑法。"
                "但他设计的每一个制度都有致命缺陷：废丞相导致皇帝必须亲力亲为、"
                "严刑法制造了更多冤案、杀功臣留下了军事人才断层。"
                "他是中国历史上最勤政的皇帝之一，却也创造了最不可持续的治理模式。"
                "这种制度设计的悖论，是全书政治哲学层面最深刻的反思。"
            ),
        },
    ]

    chapter_analyses = [
        {
            "chapter_index": 0,
            "title": "童年与灾难（第1-2章）",
            "chunk_indices": list(range(0, 4)),
            "analysis": (
                "开篇以档案形式介绍朱元璋——'姓名：朱元璋，学历：无文凭，职业：皇帝，"
                "座右铭：你的就是我的，我还是我的'——幽默中透着心酸。1344年，"
                "元末大饥荒如死神降临，短短十几天内，父亲朱五四（初六）、大哥（初九）、"
                "大哥长子（十二日）、母亲（二十二日）相继饿死。作者评价'如果这是日记，"
                "那应该是世界上最悲惨的日记'。17岁的朱重八连埋葬亲人的土地都没有，"
                "是邻居刘继祖给了一块坟地。这段赤贫的经历是理解朱元璋一生的密钥——"
                "他对饥饿的恐惧、对贪官的仇恨、对权力的执着，都根植于此。"
                "随后他在皇觉寺出家为僧，不久寺庙也断粮，被迫外出'化缘'——"
                "实际就是沿淮西一带乞讨三年。"
            ),
            "key_points": [
                "朱元璋家庭赤贫，祖上数代以数字为名",
                "1344年大饥荒，半月内父母兄长饿死",
                "出家为僧后被迫乞讨三年",
                "苦难经历奠定其一生性格底色",
            ],
            "characters_involved": ["朱元璋", "朱五四"],
            "significance": "奠定全书基调：从最低处起步的逆袭叙事",
        },
        {
            "chapter_index": 1,
            "title": "投军崛起（第3-6章）",
            "chunk_indices": list(range(4, 11)),
            "analysis": (
                "至正十二年，儿时伙伴汤和来信劝朱重八投军。他到濠州城差点被当作奸细杀掉，"
                "但面对死亡'眼中只有镇定'。郭子兴收他为亲兵，他作战勇猛、处事冷静、"
                "深谋远虑，迅速脱颖而出。他娶了郭子兴的养女马氏，获得了一生中最重要的伴侣。"
                "在定远收编散兵时展现了高超的政治手腕——先设饭局请寨主来，趁机扣押，"
                "然后以寨主名义收编三千人。这种'先礼后兵'的手段成为他的招牌。"
                "攻占集庆（南京）是他事业的关键转折，采纳了'高筑墙、广积粮、缓称王'的战略，"
                "在群雄称王称帝时默默积蓄实力。作者评价：'当朱元璋的目光投向集庆时，"
                "他已经不再是一个简单的起义者，而是一个有野心的政治家。'"
            ),
            "key_points": [
                "汤和劝投军，郭子兴收为亲兵",
                "娶马氏（马皇后），获得关键政治支持",
                "定远收编散兵展现政治手腕",
                "攻占集庆建立根据地",
                "'高筑墙、广积粮、缓称王'战略",
            ],
            "characters_involved": ["朱元璋", "郭子兴", "马皇后", "汤和", "徐达"],
            "significance": "展现朱元璋从士兵到领袖的蜕变",
        },
        {
            "chapter_index": 2,
            "title": "可怕的对手（第7-8章）",
            "chunk_indices": list(range(11, 16)),
            "analysis": (
                "作者以'根据顾恺之吃甘蔗的理论，先介绍弱一点的'引出两大对手。"
                "张士诚是泰州私盐贩子，不怕死、有钱、仇恨元朝。他在高邮之战中创造了奇迹——"
                "以区区几千人抵挡元朝百万大军的围攻，连元朝最后的名将脱脱都败在他手下。"
                "陈友谅则更加可怕——渔民之子出身，心黑手狠，弑主自立。"
                "他在五通庙中诱杀名义上的皇帝徐寿辉的场景是全书最阴冷的段落之一："
                "'陈友谅没有回头，只是淡淡的说：可惜你看不到那一天了。'"
                "两个对手的性格对比揭示了元末乱世的残酷法则：张士诚'器小'缺少远见，"
                "陈友谅'志骄'好生事端。朱元璋正是看透了这一点才决定先打陈友谅。"
            ),
            "key_points": [
                "张士诚高邮之战以少胜多",
                "陈友谅弑主自立的阴狠",
                "五通庙诱杀徐寿辉的经典场景",
                "朱元璋'先强后弱'的战略决策",
            ],
            "characters_involved": [
                "张士诚", "陈友谅", "徐寿辉", "脱脱",
            ],
            "significance": "三国鼎立格局形成，为决战埋下伏笔",
        },
        {
            "chapter_index": 3,
            "title": "洪都奇迹（第9-11章）",
            "chunk_indices": list(range(16, 31)),
            "analysis": (
                "至正二十三年，陈友谅率六十万大军进攻洪都（南昌）。"
                "守将是朱元璋的侄子朱文正——一个公认的纨绔子弟，到任后'留连于烟花之所，"
                "整日饮酒作乐'。所有人都认为'这真是个大爷，什么也指望不上他了'。"
                "然而当陈友谅大军压境时，朱文正判若两人，展现出惊人的军事才能——"
                "以四万人抵挡六十万大军，坚守整整八十五天。"
                "这是中国战争史上最不可思议的防守战之一。"
                "作者以此传达了一个深刻的主题：不要用偏见定义一个人，"
                "'纨绔子弟'的标签差点埋没了一个军事天才。"
                "然而最令人唏嘘的是，洪都之战后朱文正因功高赏薄而心生怨恨，"
                "密谋勾结张士诚，被朱元璋发现后囚禁至死。英雄与叛徒只在一念之间。"
            ),
            "key_points": [
                "朱文正以纨绔之名镇守洪都",
                "四万对六十万坚守85天",
                "中国战争史上最传奇的防守战之一",
                "朱文正战后因不满赏赐密谋叛变",
            ],
            "characters_involved": ["朱文正", "陈友谅", "朱元璋", "邓愈"],
            "significance": "以弱守强的奇迹，为鄱阳湖决战赢得时间",
        },
        {
            "chapter_index": 4,
            "title": "鄱阳湖决死战（第12章）",
            "chunk_indices": list(range(32, 38)),
            "analysis": (
                "全书最高潮。七月二十一日，双方在鄱阳湖摆开阵势，"
                "朱元璋的士兵才发现一个恐怖的事实：陈友谅的战船'长十五丈，宽两丈，高三丈'，"
                "分三层，船面可以骑马巡逻，外裹铁皮——这是当时的'航空母舰'。"
                "朱元璋的战船'站在自己的战船上只能仰视敌船'，主力居然还是三年前缴获的旧船。"
                "徐达率先发起突击，将舰队分成十一队从不同角度围攻巨舰（群狼战术）。"
                "常遇春在最危急时刻射出关键一箭。朱元璋的座船一度搁浅，差点被俘。"
                "最终利用东北风发起火攻，陈友谅的巨舰相互碰撞，'湖水尽赤'。"
                "陈友谅在突围时被流箭射穿头颅身亡。作者评价这场战役的规模——"
                "双方投入兵力超过八十万，远超赤壁之战，是中世纪最大的水战。"
            ),
            "key_points": [
                "陈友谅巨舰对朱元璋小船的巨大优势",
                "徐达群狼战术突破敌阵",
                "火攻扭转战局，湖水尽赤",
                "陈友谅中箭身亡",
                "中世纪最大规模水战",
            ],
            "characters_involved": [
                "朱元璋", "陈友谅", "徐达", "常遇春", "廖永忠",
            ],
            "significance": "全书最高潮，奠定明朝统一基础",
        },
        {
            "chapter_index": 5,
            "title": "消灭张士诚与北伐（第13-15章）",
            "chunk_indices": list(range(38, 58)),
            "analysis": (
                "解决陈友谅后，朱元璋转攻张士诚。张士诚困守苏州城，"
                "展现出令人意外的坚韧——他不是个好将军，却是个硬骨头，"
                "城破后纵火自焚未死，被俘后在押解途中自缢而亡。"
                "朱元璋对张士诚的评价颇为复杂，虽是敌人却不无惺惺相惜。"
                "统一江南后，朱元璋发出'驱逐胡虏，恢复中华'的北伐檄文——"
                "这是汉族政权时隔近百年向蒙元发出的宣战书，极具感召力。"
                "徐达、常遇春率军势如破竹收复大都。常遇春在北伐途中暴病而亡，年仅四十，"
                "作者叹息'他是在马背上度过一生的战神，却没能看到最终的胜利'。"
                "远征沙漠中，名将王保保（扩廓帖木儿）成为明军最顽强的对手——"
                "朱元璋评价他是'天下奇男子'。"
            ),
            "key_points": [
                "张士诚困守苏州城破后自缢",
                "'驱逐胡虏，恢复中华'檄文",
                "徐达常遇春收复大都",
                "常遇春北伐途中病逝",
                "王保保成为明军最强对手",
            ],
            "characters_involved": [
                "朱元璋", "张士诚", "徐达", "常遇春", "王保保",
            ],
            "significance": "从南方政权到统一王朝的关键转折",
        },
        {
            "chapter_index": 6,
            "title": "建国与制度设计（第16章）",
            "chunk_indices": list(range(58, 68)),
            "analysis": (
                "朱元璋定都南京，国号'明'，建元洪武。作为一个从最底层爬上来的皇帝，"
                "他对制度设计有着异乎寻常的执着——亲自制定律法、设计官僚体系、"
                "建立卫所制度和户籍制度。他是中国历史上最勤政的皇帝，"
                "每天批阅数百件奏折，事必躬亲到了偏执的程度。"
                "然而这种'一人治天下'的模式注定不可持续。"
                "作者以制度分析的视角揭示了明朝体制的深层矛盾：八股取士束缚思想、"
                "卫所制度逐渐腐化、户籍制度将人固定在土地上。"
                "这些制度在朱元璋的铁腕下尚能运转，但一旦换一个能力平庸的皇帝，"
                "整个体系就会出问题。这是对后续数百年明朝历史的伏笔。"
            ),
            "key_points": [
                "定都南京建元洪武",
                "亲自制定制度体系",
                "中国历史上最勤政的皇帝之一",
                "制度设计中的深层矛盾",
            ],
            "characters_involved": ["朱元璋", "李善长", "刘基"],
            "significance": "从战争到治国的转型，制度与人治的矛盾初现",
        },
        {
            "chapter_index": 7,
            "title": "胡惟庸案与蓝玉案（第17-21章）",
            "chunk_indices": list(range(68, 104)),
            "analysis": (
                "全书最沉重的部分。丞相胡惟庸权势日盛，朱元璋以谋反罪将其诛杀，"
                "并借此案永久废除丞相制度——从此皇帝直接管理六部，再无人分权。"
                "此案牵连三万余人，朝野震动。之后刘基（刘伯温）之死疑云浮现，"
                "作者暗示其可能被胡惟庸下毒害死，而朱元璋并未追究。"
                "蓝玉案更为惨烈——蓝玉是常遇春妻弟、朱元璋最后的名将，"
                "北征蒙古立下赫赫战功，但因骄横跋扈被朱元璋以谋反罪诛杀，"
                "牵连一万五千人。作者分析了朱元璋的深层逻辑：他屠尽功臣，"
                "是因为太子朱标已死，年幼的孙子朱允炆根本压不住这些骄兵悍将。"
                "'不是我心狠，而是我不这样做，你们就会欺负我的孙子。'"
                "李善长作为开国第一功臣，七十七岁高龄仍被牵连处死，全家七十余口灭门，"
                "堪称全书最令人唏嘘的段落之一。"
            ),
            "key_points": [
                "胡惟庸案废除丞相制度",
                "牵连三万余人",
                "刘基之死疑云",
                "蓝玉案清洗武将集团",
                "李善长七十七岁满门被诛",
                "朱元璋为孙子朱允炆扫清障碍的深层逻辑",
            ],
            "characters_involved": [
                "朱元璋", "胡惟庸", "蓝玉", "李善长", "刘基", "朱标",
            ],
            "significance": "权力对人性的异化达到顶峰，全书最深刻的反思",
        },
        {
            "chapter_index": 8,
            "title": "制度与反腐（第22章）",
            "chunk_indices": list(range(104, 120)),
            "analysis": (
                "朱元璋对贪腐的打击达到了中国历史上的极致。他发明了'剥皮实草'——"
                "将贪官的皮剥下来填上稻草做成标本，挂在衙门口示众。"
                "他规定贪污六十两银子以上就要处死。然而如此严刑峻法之下，"
                "贪腐依然屡禁不止，朱元璋自己都感叹'我才杀完早上的，晚上又有人犯了'。"
                "作者以此揭示了一个深刻的制度困境：靠恐惧维持的清廉是不可持续的。"
                "空印案和郭桓案波及数万人，很多都是冤枉的，但朱元璋'宁可错杀，不可放过'。"
                "这一章的意义在于展示了朱元璋身上的深刻矛盾——"
                "他是真心为老百姓好的皇帝，但他的方法却制造了更多的苦难。"
            ),
            "key_points": [
                "剥皮实草等酷刑惩贪",
                "贪污六十两银子即处死",
                "空印案和郭桓案波及数万人",
                "严刑峻法仍无法根除贪腐",
            ],
            "characters_involved": ["朱元璋"],
            "significance": "制度反腐的困境，人治与法治的悖论",
        },
        {
            "chapter_index": 9,
            "title": "靖难之役（第23-31章）",
            "chunk_indices": list(range(120, 169)),
            "analysis": (
                "朱元璋驾崩后，21岁的建文帝朱允炆即位。他是一个仁慈聪明的年轻人，"
                "但面对的是朱元璋留下的藩王割据局面。在黄子澄、齐泰的建议下急于削藩，"
                "连废周王、齐王等数位藩王，逼得最强的燕王朱棣不得不反。"
                "靖难之役是一场实力悬殊的战争——朱棣仅有北平一隅之地，"
                "建文帝坐拥天下。但建文帝的致命失误在于用人："
                "派纸上谈兵的李景隆率五十万大军北伐，结果一败涂地；"
                "而弃用了老将耿炳文。更荒唐的是'不要让我背上杀叔叔的名声'的命令，"
                "使前线将士不敢对朱棣下杀手。铁铉在济南城死守，将朱棣的牌位悬挂城头"
                "让其不敢炮轰，堪称全书最精彩的智将故事之一。"
                "姚广孝——一个奇特的和尚，是靖难之役真正的策划者。"
                "方孝孺拒绝为朱棣撰写登基诏书，被灭十族（包括学生），"
                "是全书最悲壮的殉道者。建文帝在宫中大火后下落成谜，"
                "成为明史最大的悬案。"
            ),
            "key_points": [
                "建文帝削藩逼反朱棣",
                "李景隆五十万大军惨败",
                "铁铉济南城智守",
                "姚广孝策划靖难",
                "方孝孺被灭十族殉节",
                "建文帝失踪成千古悬案",
            ],
            "characters_involved": [
                "朱允炆", "朱棣", "姚广孝", "李景隆", "耿炳文",
                "铁铉", "方孝孺", "黄子澄", "齐泰",
            ],
            "significance": "王朝第一次内部权力交接的剧痛，全书终章",
        },
    ]

    characters = [
        {
            "name": "朱元璋",
            "aliases": ["朱重八", "朱国瑞"],
            "description": "明朝开国皇帝，从赤贫农民到一代帝王的传奇人物。作者笔下最复杂的角色",
            "voice_style": "坚毅果断，时而粗犷，时而深沉",
            "motivations": ["生存", "复仇", "建立理想王朝", "巩固皇权", "保护子孙"],
            "arc_summary": "从苦难中崛起的英雄，最终被权力异化为铁腕帝王。他的一生是草根逆袭的巅峰，也是权力悲剧的典型",
            "key_chapter_indices": [0, 1, 2, 3, 4, 5, 6, 7, 8],
            "personality_type": "ENTJ",
            "key_relationships": [],
            "worldview": "",
        },
        {
            "name": "陈友谅",
            "aliases": [],
            "description": "朱元璋最强大的对手，渔民之子出身，心黑手狠的枭雄",
            "voice_style": "阴沉有力，充满压迫感",
            "motivations": ["称霸天下", "消灭一切对手"],
            "arc_summary": "从渔民之子到弑主称帝的枭雄，拥有最强兵力和最先进战舰，最终在鄱阳湖之战中被流箭射杀。性格决定命运的典型",
            "key_chapter_indices": [2, 3, 4],
            "personality_type": "ENTJ",
            "key_relationships": [],
            "worldview": "",
        },
        {
            "name": "徐达",
            "aliases": [],
            "description": "明朝开国第一名将，朱元璋的发小和最信赖的将领",
            "voice_style": "沉稳谦逊，言简意赅",
            "motivations": ["报效知遇之恩", "北伐驱元", "守护战友"],
            "arc_summary": "从农家少年到帝国第一将，鄱阳湖决战中首当其冲，北伐中收复大都。功高盖世却以谦逊善终，是乱世中少有的完人",
            "key_chapter_indices": [1, 4, 5],
            "personality_type": "ISTJ",
            "key_relationships": [],
            "worldview": "",
        },
        {
            "name": "常遇春",
            "aliases": [],
            "description": "明朝开国猛将，以'常十万'自称，战场上无人能敌",
            "voice_style": "豪放直率，狂放不羁",
            "motivations": ["建功立业", "驱逐蒙元"],
            "arc_summary": "自称'给我十万兵马就能横行天下'的猛将。鄱阳湖战役中射出关键一箭，北伐途中势如破竹，却在四十岁英年暴病而亡，未能看到最终胜利",
            "key_chapter_indices": [4, 5],
            "personality_type": "ESTP",
            "key_relationships": [],
            "worldview": "",
        },
        {
            "name": "马皇后",
            "aliases": ["马氏", "马秀英"],
            "description": "朱元璋之妻，郭子兴养女，朱元璋一生中唯一的柔软",
            "voice_style": "温和坚定，以理服人",
            "motivations": ["守护家庭", "劝谏丈夫"],
            "arc_summary": "在朱元璋最困难时嫁给他，在他最残暴时劝阻他。她是朱元璋铁石心肠背后唯一的温情，她的去世让朱元璋失去了最后的制衡",
            "key_chapter_indices": [1, 7],
            "personality_type": "INFJ",
            "key_relationships": [],
            "worldview": "",
        },
        {
            "name": "刘基",
            "aliases": ["刘伯温"],
            "description": "明朝开国谋臣，浙东集团领袖，'天下第一谋士'",
            "voice_style": "睿智冷静，洞察人心",
            "motivations": ["辅佐明主", "实现治国理想"],
            "arc_summary": "在朱元璋最关键的决策中提供了正确建议——先打陈友谅。功成后与淮西集团（李善长）形成党争，被排挤回乡。疑似被胡惟庸下毒致死，朱元璋对此心知肚明却未追究",
            "key_chapter_indices": [1, 4, 7],
            "personality_type": "INTJ",
            "key_relationships": [],
            "worldview": "",
        },
        {
            "name": "李善长",
            "aliases": [],
            "description": "明朝开国第一功臣，淮西集团领袖，朱元璋的'萧何'",
            "voice_style": "老谋深算，圆滑世故",
            "motivations": ["维护淮西集团利益", "安享荣华"],
            "arc_summary": "六十多岁退休后以为可以安度晚年，却在七十七岁高龄被牵连进胡惟庸案，全家七十余口灭门。全书最令人唏嘘的结局之一",
            "key_chapter_indices": [6, 7],
            "personality_type": "ISTJ",
            "key_relationships": [],
            "worldview": "",
        },
        {
            "name": "胡惟庸",
            "aliases": [],
            "description": "明朝最后一任丞相，因谋反罪被诛",
            "voice_style": "圆滑世故，暗藏野心",
            "motivations": ["揽权", "控制朝政"],
            "arc_summary": "从政治投机者到权臣，权势日盛直到威胁皇权。成为朱元璋废除丞相制度的祭品——无论他是否真的谋反，这个结果都是注定的",
            "key_chapter_indices": [7],
            "personality_type": "ENTP",
            "key_relationships": [],
            "worldview": "",
        },
        {
            "name": "蓝玉",
            "aliases": [],
            "description": "明朝最后的名将，常遇春妻弟，北征蒙古的英雄",
            "voice_style": "骄横跋扈，目中无人",
            "motivations": ["建功立业", "享受权势"],
            "arc_summary": "北征蒙古立下赫赫战功，却因骄横触怒朱元璋。被以谋反罪诛杀，牵连一万五千人。他的覆灭标志着开国武将集团被彻底清洗",
            "key_chapter_indices": [7],
            "personality_type": "ESTP",
            "key_relationships": [],
            "worldview": "",
        },
        {
            "name": "张士诚",
            "aliases": ["张九四"],
            "description": "元末群雄之一，泰州私盐贩子，占据江浙富庶之地",
            "voice_style": "豪爽中带着市井气",
            "motivations": ["称霸一方", "享受富贵"],
            "arc_summary": "高邮之战以少胜多创造奇迹，却在富贵中丧失进取心。城破后纵火自焚未死，被俘后自缢身亡，保住了最后的尊严",
            "key_chapter_indices": [2, 5],
            "personality_type": "ISFP",
            "key_relationships": [],
            "worldview": "",
        },
        {
            "name": "朱棣",
            "aliases": ["燕王"],
            "description": "朱元璋第四子，靖难之役发动者，后来的永乐大帝",
            "voice_style": "深沉内敛，关键时刻果决无情",
            "motivations": ["自保", "夺取皇位", "证明自己配得上这个天下"],
            "arc_summary": "在父亲的阴影下隐忍多年，面对侄儿削藩的步步紧逼被迫起兵。从北平一隅之地起兵，历经四年浴血奋战攻入南京，是中国历史上唯一以藩王身份夺取皇位的人",
            "key_chapter_indices": [9],
            "personality_type": "ENTJ",
            "key_relationships": [],
            "worldview": "",
        },
        {
            "name": "朱允炆",
            "aliases": ["建文帝"],
            "description": "朱元璋之孙，明朝第二任皇帝",
            "voice_style": "温和儒雅，缺少杀伐决断",
            "motivations": ["推行仁政", "削藩集权"],
            "arc_summary": "一个仁慈聪明但缺乏政治手腕的年轻人，坐在了需要铁腕的位置上。'不要让我背上杀叔叔的名声'的命令成为致命败笔。失踪后成为千古之谜",
            "key_chapter_indices": [9],
            "personality_type": "INFP",
            "key_relationships": [],
            "worldview": "",
        },
        {
            "name": "郭子兴",
            "aliases": [],
            "description": "红巾军首领，朱元璋的第一个上司和岳父",
            "voice_style": "多疑善变，反复无常",
            "motivations": ["割据称雄"],
            "arc_summary": "收留朱元璋并将养女嫁给他，却又多次猜忌排挤。是朱元璋军事生涯的起点，也让朱元璋学会了在复杂人际中生存的智慧",
            "key_chapter_indices": [1],
            "personality_type": "ESFP",
            "key_relationships": [],
            "worldview": "",
        },
        {
            "name": "朱文正",
            "aliases": [],
            "description": "朱元璋亲侄子，洪都保卫战的英雄",
            "voice_style": "不羁张扬，骨子里有血性",
            "motivations": ["建功立业", "获得认可"],
            "arc_summary": "以纨绔子弟的面目示人，却在洪都之战中以四万人抵挡六十万大军85天，创造战争奇迹。然而功高赏薄的怨恨让他走上了叛变的道路，最终被囚禁至死",
            "key_chapter_indices": [3],
            "personality_type": "ENTP",
            "key_relationships": [],
            "worldview": "",
        },
        {
            "name": "姚广孝",
            "aliases": ["道衍"],
            "description": "靖难之役的真正策划者，一个奇特的和尚",
            "voice_style": "高深莫测，言语间暗藏玄机",
            "motivations": ["实现政治抱负", "改变历史走向"],
            "arc_summary": "一个身披袈裟的政治家，主动找到朱棣送上'白帽子'——王上加白即为皇。他是靖难之役的灵魂人物，却在功成后拒绝一切赏赐，继续做和尚",
            "key_chapter_indices": [9],
            "personality_type": "INTJ",
            "key_relationships": [],
            "worldview": "",
        },
        {
            "name": "铁铉",
            "aliases": [],
            "description": "建文朝忠臣，济南城的守护者",
            "voice_style": "刚正不阿，临危不惧",
            "motivations": ["忠君报国", "守护济南"],
            "arc_summary": "一介书生，在济南城面对朱棣大军时展现出惊人的智慧和勇气——将朱元璋牌位悬挂城头让朱棣不敢炮轰。朱棣攻入南京后将其处以极刑，铁铉至死不屈",
            "key_chapter_indices": [9],
            "personality_type": "ISTJ",
            "key_relationships": [],
            "worldview": "",
        },
        {
            "name": "方孝孺",
            "aliases": [],
            "description": "建文朝大儒，被灭十族的殉道者",
            "voice_style": "正气凛然，视死如归",
            "motivations": ["忠于正统", "坚守道义"],
            "arc_summary": "朱棣攻入南京后要求他撰写登基诏书，方孝孺怒写'燕贼篡位'。朱棣威胁灭九族，方孝孺答'灭十族又如何？'朱棣果真灭其十族（包括学生），共诛杀873人。全书最悲壮的殉道者",
            "key_chapter_indices": [9],
            "personality_type": "INFJ",
            "key_relationships": [],
            "worldview": "",
        },
        {
            "name": "李景隆",
            "aliases": [],
            "description": "李文忠之子，建文帝信任的将领，靖难之役的'猪队友'",
            "voice_style": "浮夸自信，华而不实",
            "motivations": ["立功证明自己", "享受权势"],
            "arc_summary": "顶着名将之后的光环率五十万大军北伐朱棣，却一败涂地，成为中国历史上最著名的'草包将军'之一。讽刺的是，最后开金川门迎朱棣入南京的正是他",
            "key_chapter_indices": [9],
            "personality_type": "ESFP",
            "key_relationships": [],
            "worldview": "",
        },
        {
            "name": "耿炳文",
            "aliases": [],
            "description": "明朝开国老将，擅长防守",
            "voice_style": "沉稳持重，不急不躁",
            "motivations": ["忠于朝廷"],
            "arc_summary": "朱元璋屠尽功臣后硕果仅存的老将，擅长防守。建文帝最初派他对抗朱棣，虽然被打败但稳住了局面。然而建文帝听信黄子澄换上李景隆，从此一败涂地",
            "key_chapter_indices": [9],
            "personality_type": "ISTJ",
            "key_relationships": [],
            "worldview": "",
        },
        {
            "name": "汤和",
            "aliases": [],
            "description": "朱元璋儿时伙伴，写信劝其投军的人",
            "voice_style": "憨厚质朴",
            "motivations": ["建功立业", "活命"],
            "arc_summary": "最早劝朱元璋投军的人，但能力不及徐达常遇春。他最大的智慧在于知进退——看到朱元璋大杀功臣时主动交出兵权，成为少数善终的开国功臣",
            "key_chapter_indices": [1, 7],
            "personality_type": "ISFJ",
            "key_relationships": [],
            "worldview": "",
        },
        {
            "name": "王保保",
            "aliases": ["扩廓帖木儿"],
            "description": "元朝最后的名将，朱元璋称他为'天下奇男子'",
            "voice_style": "坚韧不拔，百折不挠",
            "motivations": ["忠于元朝", "恢复蒙元"],
            "arc_summary": "在蒙元土崩瓦解时仍然坚持抵抗，多次在沙漠中击败明军追兵。朱元璋评价他是'天下奇男子'，想招降他却始终未能如愿",
            "key_chapter_indices": [5],
            "personality_type": "INTJ",
            "key_relationships": [],
            "worldview": "",
        },
        {
            "name": "朱标",
            "aliases": ["太子"],
            "description": "朱元璋长子，被寄予厚望却英年早逝",
            "voice_style": "仁厚宽和",
            "motivations": ["继承大统", "推行仁政"],
            "arc_summary": "朱元璋最疼爱的儿子，性格仁厚，多次劝阻父亲的杀戮。他的早逝改变了历史走向——朱元璋不得不立年幼的孙子为继承人，并因此屠尽功臣为其扫清障碍",
            "key_chapter_indices": [7, 8],
            "personality_type": "INFJ",
            "key_relationships": [],
            "worldview": "",
        },
    ]

    narrative_rhythm = [
        # Chapter 0: 童年与灾难
        {"chapter_index": 0, "title": "童年", "intensity": 0.3,
         "event_label": "赤贫之家，以数字为名", "point_type": "normal"},
        {"chapter_index": 0, "title": "灾难降临", "intensity": 0.75,
         "event_label": "大饥荒——父母兄长半月内相继饿死", "point_type": "turning_point"},
        {"chapter_index": 0, "title": "出家化缘", "intensity": 0.5,
         "event_label": "入皇觉寺为僧，后被迫乞讨三年", "point_type": "normal"},

        # Chapter 1: 投军崛起
        {"chapter_index": 1, "title": "投奔红巾军", "intensity": 0.55,
         "event_label": "汤和来信，投奔郭子兴差点被杀", "point_type": "turning_point"},
        {"chapter_index": 1, "title": "崭露头角", "intensity": 0.6,
         "event_label": "娶马氏，收徐达，建立嫡系", "point_type": "normal"},
        {"chapter_index": 1, "title": "攻占集庆", "intensity": 0.7,
         "event_label": "渡江占领南京，确立争霸根据地", "point_type": "climax"},

        # Chapter 2: 可怕的对手
        {"chapter_index": 2, "title": "高邮之战", "intensity": 0.65,
         "event_label": "张士诚以少胜多击败元军百万大军", "point_type": "normal"},
        {"chapter_index": 2, "title": "弑君夺位", "intensity": 0.8,
         "event_label": "陈友谅五通庙诱杀徐寿辉", "point_type": "turning_point"},
        {"chapter_index": 2, "title": "战略抉择", "intensity": 0.6,
         "event_label": "朱元璋决定先打最强的陈友谅", "point_type": "normal"},

        # Chapter 3: 洪都奇迹
        {"chapter_index": 3, "title": "六十万围城", "intensity": 0.85,
         "event_label": "陈友谅六十万大军进攻洪都", "point_type": "climax"},
        {"chapter_index": 3, "title": "纨绔变战神", "intensity": 0.9,
         "event_label": "朱文正四万守军坚守85天", "point_type": "climax"},
        {"chapter_index": 3, "title": "英雄陨落", "intensity": 0.55,
         "event_label": "朱文正因功高赏薄叛变被囚", "point_type": "turning_point"},

        # Chapter 4: 鄱阳湖决战
        {"chapter_index": 4, "title": "巨舰压城", "intensity": 0.8,
         "event_label": "陈友谅铁甲巨舰对朱元璋小船", "point_type": "normal"},
        {"chapter_index": 4, "title": "群狼战术", "intensity": 0.85,
         "event_label": "徐达分11队围攻巨舰", "point_type": "normal"},
        {"chapter_index": 4, "title": "火烧鄱阳湖", "intensity": 0.95,
         "event_label": "火攻扭转战局，湖水尽赤", "point_type": "climax"},
        {"chapter_index": 4, "title": "枭雄陨落", "intensity": 0.9,
         "event_label": "陈友谅中箭身亡", "point_type": "climax"},

        # Chapter 5: 统一与北伐
        {"chapter_index": 5, "title": "围攻苏州", "intensity": 0.65,
         "event_label": "张士诚困守苏州城破后自缢", "point_type": "normal"},
        {"chapter_index": 5, "title": "北伐檄文", "intensity": 0.75,
         "event_label": "'驱逐胡虏，恢复中华'震动天下", "point_type": "turning_point"},
        {"chapter_index": 5, "title": "收复大都", "intensity": 0.85,
         "event_label": "徐达收复大都，蒙元百年统治终结", "point_type": "climax"},
        {"chapter_index": 5, "title": "战神陨落", "intensity": 0.6,
         "event_label": "常遇春北伐途中暴病而亡", "point_type": "turning_point"},

        # Chapter 6-7: 建国与清洗
        {"chapter_index": 6, "title": "建元洪武", "intensity": 0.7,
         "event_label": "定都南京，明朝正式建立", "point_type": "normal"},
        {"chapter_index": 7, "title": "废除丞相", "intensity": 0.75,
         "event_label": "胡惟庸案，废丞相制度，诛三万人", "point_type": "turning_point"},
        {"chapter_index": 7, "title": "毒杀刘基", "intensity": 0.6,
         "event_label": "刘伯温之死疑云", "point_type": "normal"},
        {"chapter_index": 7, "title": "蓝玉覆灭", "intensity": 0.8,
         "event_label": "蓝玉案再诛一万五千人", "point_type": "turning_point"},
        {"chapter_index": 7, "title": "满门抄斩", "intensity": 0.7,
         "event_label": "李善长七十七岁全家灭门", "point_type": "normal"},

        # Chapter 8: 反腐
        {"chapter_index": 8, "title": "剥皮实草", "intensity": 0.65,
         "event_label": "朱元璋以极刑惩治贪腐", "point_type": "normal"},

        # Chapter 9: 靖难之役
        {"chapter_index": 9, "title": "削藩风暴", "intensity": 0.6,
         "event_label": "建文帝急于削藩逼反朱棣", "point_type": "turning_point"},
        {"chapter_index": 9, "title": "靖难起兵", "intensity": 0.8,
         "event_label": "朱棣以'清君侧'为名从北平起兵", "point_type": "climax"},
        {"chapter_index": 9, "title": "铁铉守城", "intensity": 0.75,
         "event_label": "铁铉悬牌位于城头智退朱棣", "point_type": "normal"},
        {"chapter_index": 9, "title": "南京陷落", "intensity": 0.9,
         "event_label": "李景隆开门献城，建文帝失踪", "point_type": "climax"},
        {"chapter_index": 9, "title": "殉道者", "intensity": 0.85,
         "event_label": "方孝孺被灭十族，873人遇难", "point_type": "turning_point"},
    ]

    return {
        "book_title": "明朝那些事儿",
        "language": "zh",
        "overall_summary": overall_summary,
        "book_outline": book_outline,
        "themes": themes,
        "theme_analyses": theme_analyses,
        "chapter_summaries": [],
        "chapter_analyses": chapter_analyses,
        "characters": characters,
        "narrative_rhythm": narrative_rhythm,
    }


def main():
    # Backup
    print(f"Backing up to {BACKUP_PATH} ...")
    shutil.copy2(SESSION_PATH, BACKUP_PATH)

    # Load
    print("Loading session JSON ...")
    with open(SESSION_PATH, "r", encoding="utf-8") as f:
        session = json.load(f)

    # Replace KG
    kg = build_knowledge_graph()
    session["knowledge_graph"] = kg

    # Write
    print("Writing updated session ...")
    with open(SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)

    # Stats
    print("\nInjection complete!")
    print(f"  chapter_analyses: {len(kg['chapter_analyses'])}")
    print(f"  characters: {len(kg['characters'])}")
    print(f"  narrative_rhythm: {len(kg['narrative_rhythm'])}")
    print(f"  outline length: {len(kg['book_outline'])} chars")
    print(f"  summary length: {len(kg['overall_summary'])} chars")
    print(f"  themes: {len(kg['themes'])}")
    print(f"  theme_analyses: {len(kg['theme_analyses'])}")


if __name__ == "__main__":
    main()
