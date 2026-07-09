"""citation 校验层 —— 把"引用来自原文"从 LLM 自称变成系统比对的事实。

设计出处：``docs/internal/design/WP1-citation-trust-chain.md``（2026-06-10 过闸）。

工作方式：``AgentLoop.query`` / ``run_fast_path`` 在一次查询内登记所有
工具返回的原文（证据登记表），final answer 解析成功后调
:func:`verify_citations` 给每条 citation 附加四个字段：

- ``verified``：snippet 能否在登记过的原文里找到（精确子串或 3-gram
  containment ≥ :data:`CONTAINMENT_THRESHOLD`）
- ``chunk_id``：命中的登记条目 id；没命中为 ``None``
- ``match_score``：匹配分（精确命中 1.0；否则最大 containment，两位小数）
- ``match_type``：证据强度三态——``"quote"`` 逐字命中 / ``"paraphrase"``
  诚实转述（过阈值但非逐字）/ ``"none"`` 未核验。把"verified 二元"细化成
  用户能分辨可信度的三档（exp-008 发现程序校验分不开逐字与转述，这里分开）。

**首版只观测不执法**：unverified 的 citation 不删除、不重答、不改
answer——先把 verified 率变成可观测量（钱学森控制论：观测先于执法），
拿到真实分布数据后再定 enforcement 策略。

**宽松二次核验（exp022 补的召回短板）**：主比对是纯字符串比对，繁简不一致、
LLM 给术语加引号、用省略号拼接跨段原话、超短片段带一处装饰性差异——这些真原文
会被主比对判成 ``none``（exp022 实测漏报 10.1%，人物图 / 时间线同吃这个亏）。
所以主比对判 ``none`` 后再走一道 :func:`_loose_verify`：繁体折简体、去引号、
按省略号切片段逐段逐字核，够长的片段全部命中才认（拼接跨段的真原话）；单片段
够长且是子串就认 ``quote``、否则回落到高重叠 containment 认 ``paraphrase``。
**命根子是提召回不丢精度**：宽松通路只做归一化后的逐字子串 + 同一条 0.6
containment 阈，不相干文本仍然进不来——归一化只会把语义相同的字折到一起，不会
把两段无关文本折成相等。繁简折叠表来自 OpenCC（真实标准，非拍脑袋），见
:data:`_T2S_TABLE`。

纯标准库实现，不引入新依赖（Karpathy 简洁原则）。
"""

from __future__ import annotations

import re

CONTAINMENT_THRESHOLD: float = 0.6
"""3-gram containment 的 verified 阈值。

工程起点值，留调——阈值标定实验不在 WP1 首版做（见设计稿"不做什么"）。
"""

_NGRAM_SIZE: int = 3
"""字符 n-gram 的 n。中文场景 3 字一组已能区分改写与编造。"""

_LOOSE_MIN_LEN: int = 4
"""省略号拼接的多片段核验里，一个片段够长才拿去要求"必须逐字命中"（CJK 字符数）。

只管多片段这条路：把几段非连续的原话拼一起时，短到 2-3 字的碎片单独太容易碰巧命中，
凑一块会把"编的拼接"也放进来，所以只认够长（≥ 本值）的片段、且要求它们全部命中。
单片段整条逐字子串不受此限（与主比对一致，见 :func:`_loose_verify` 通路 2）。
"""

# 全角标点 → 半角等价物。归一化的目的：LLM 引用原文时常把全半角标点
# 互换（"，"↔","、中文引号↔ASCII 引号），这不该影响"是否原文"的判定。
_PUNCT_TRANSLATION = str.maketrans({
    "，": ",",
    "。": ".",
    "！": "!",
    "？": "?",
    "；": ";",
    "：": ":",
    "“": '"',  # 左双引号 “
    "”": '"',  # 右双引号 ”
    "‘": "'",  # 左单引号 ‘
    "’": "'",  # 右单引号 ’
    "（": "(",
    "）": ")",
    "【": "[",
    "】": "]",
    "《": "<",
    "》": ">",
    "、": ",",
    "—": "-",
    "…": ".",
})

# 繁体 → 简体单字折叠表，仅用于宽松二次核验（不进主比对，不改 quote/paraphrase 语义）。
# provenance：OpenCC ``TSCharacters.txt``（Apache-2.0，源出 Unihan），取每个繁体字的
# 首选简体，只留繁简真不同的 1:1 折叠，共 3222 条。构建时一次性抓取生成、静态嵌入，
# 运行期纯查表（str.translate，C 级），无网络、无新依赖。双向都折同一张表 → 精度不丢：
# 只把语义相同的字折到一起，不会把两段无关文本折成相等。
_T2S_TRAD = "㑯㑳㑶㓨㗲㘚㜄㜏㜢㠏㠣㥮㩜㩳㩵㺏䁪䁻䃮䊷䋙䋚䋹䋻䍦䎱䓣䙡䜀䝼䡵䥇䥑䥕䥱䦛䦟䧢䮄䯀䰾䱷䱽䲁䲘䴉丟並乾亂亙亞佇佈佔併來侖侶侷俁係俔俠俥俬倀倆倈倉個們倖倫倲偉偑側偵偽傌傑傖傘備傢傭傯傳傴債傷傾僂僅僉僑僕僞僤僥僨僱價儀儁儂億儈儉儎儐儔儕儘償優儲儷儸儺儻儼兇兌兒兗內兩冊冑冪凈凍凜凱別刪剄則剋剎剗剛剝剮剴創剷劃劄劇劉劊劌劍劏劑劚勁動務勛勝勞勢勣勩勱勳勵勸勻匭匯匱區協卹卻卽厙厠厤厭厲厴參叄叢吒吳吶呂咼員唄唸問啓啞啟啢喎喚喪喫喬單喲嗆嗇嗊嗎嗚嗩嗰嗶嘆嘍嘓嘔嘖嘗嘜嘩嘮嘯嘰嘵嘸嘽噁噓噚噝噠噥噦噯噲噴噸噹嚀嚇嚌嚐嚕嚙嚥嚦嚧嚨嚮嚲嚳嚴嚶囀囁囂囅囈囉囌囑囪圇國圍園圓圖團垻埡埨埰執堅堊堖堝堯報場塊塋塏塒塗塚塢塤塵塸塹塿墊墜墠墮墰墳墶墻墾壇壋壎壓壗壘壙壚壜壞壟壠壢壩壪壯壺壼壽夠夢夥夾奐奧奩奪奬奮奼妝姍姦娙娛婁婦婭媧媯媰媼媽嫋嫗嫵嫺嫻嫿嬀嬃嬈嬋嬌嬙嬡嬤嬪嬰嬸孃孋孌孫學孻孿宮寀寢實寧審寫寬寵寶將專尋對導尷屆屍屓屜屢層屨屬岡峯峴島峽崍崑崗崙崢崬嵐嵗嵽嵾嶁嶄嶇嶔嶗嶠嶢嶧嶨嶮嶸嶺嶼嶽巋巒巔巖巘巰巹帥師帳帶幀幃幓幗幘幟幣幫幬幷幹幾庫廁廂廄廈廎廕廚廝廞廟廠廡廢廣廩廬廳弒弔弳張強彄彆彈彌彎彔彙彠彥彫彲彿後徑從徠復徵徹恆恥悅悞悵悶悽惡惱惲惻愛愜愨愴愷愾慄態慍慘慚慟慣慤慪慫慮慳慶慺慼慾憂憊憐憑憒憖憚憤憫憮憲憶懇應懌懍懞懟懣懤懨懲懶懷懸懺懼懾戀戇戔戧戩戰戱戲戶扞拋拚挩挱挾捨捫捱捲掃掄掆掗掙掛採揀揚換揮揯損搖搗搧搵搶摑摜摟摯摳摶摺摻撈撏撐撓撝撟撣撥撫撲撳撻撾撿擁擄擇擊擋擓擔據擠擡擣擬擯擰擱擲擴擷擺擻擼擽擾攄攆攏攔攖攙攛攜攝攢攣攤攪攬敎敓敗敘敵數斂斃斆斕斬斷於旂旣昇時晉晛晝暈暉暐暘暢暫曄曆曇曉曏曖曠曥曨曬書會朥朧朮東枴柵柺査桱桿梔梘梜條梟梲棄棊棖棗棟棡棧棲棶椏椲楊楓楨業極榘榦榪榮榲榿構槍槓槤槧槨槮槳槶槼樁樂樅樑樓標樞樢樣樧樫樳樸樹樺樿橈橋機橢橫橯檁檉檔檜檟檢檣檮檯檳檸檻櫃櫍櫓櫚櫛櫝櫞櫟櫥櫧櫨櫪櫫櫬櫱櫳櫸櫻欄欅權欏欒欓欖欞欽歎歐歟歡歲歷歸歿殘殞殤殨殫殭殮殯殰殲殺殻殼毀毆毿氂氈氌氣氫氬氳氾汎汙決沒沖況泝洩洶浹浿涇涗涼淒淚淥淨淩淪淵淶淺渙減渢渦測渾湊湋湞湧湯溈準溝溫溮溳溼滄滅滌滎滙滬滯滲滷滸滻滾滿漁漊漍漚漢漣漬漲漵漸漿潁潑潔潕潙潚潛潤潯潰潷潿澀澆澇澐澗澠澤澦澩澫澮澱澾濁濃濄濆濕濘濚濛濜濟濤濧濫濰濱濺濼濾瀂瀅瀆瀇瀉瀋瀏瀕瀘瀝瀟瀠瀦瀧瀨瀰瀲瀾灃灄灑灒灕灘灙灝灡灣灤灧灩災為烏烴無煉煒煙煢煥煩煬煱熅熒熗熰熱熲熾燀燁燈燉燒燖燙燜營燦燬燭燴燶燻燼燾爍爐爛爭爲爺爾牀牆牘牴牽犖犛犢犧狀狹狽猙猶猻獁獃獄獅獎獨獪獫獮獰獱獲獵獷獸獺獻獼玀現琱琺琿瑋瑒瑣瑤瑩瑪瑲璉璊璕璗璡璣璦璫璯環璵璸璽璿瓅瓊瓏瓔瓚瓛甌甕產産畝畢畫異畵當疇疊痙痠痾瘂瘋瘍瘓瘞瘡瘧瘮瘲瘺瘻療癆癇癉癒癘癟癡癢癤癥癧癩癬癭癮癰癱癲發皁皚皰皸皺盃盜盞盡監盤盧盪眞眥眾睍睏睜睞瞘瞜瞞瞶瞼矇矓矚矯硃硜硤硨硯碕碩碭碸確碼碽磑磚磠磣磧磯磽磾礄礎礐礙礦礪礫礬礱祕祿禍禎禕禡禦禪禮禰禱禿秈稅稈稏稜稟種稱穀穇穌積穎穠穡穢穩穫穭窩窪窮窯窵窶窺竄竅竇竈竊竪競筆筍筧筴箇箋箏箚節範築篋篔篠篢篤篩篳篸簀簍簑簞簡簣簫簹簽簾籃籅籌籔籙籛籜籟籠籤籩籪籬籮籲粵糉糝糞糧糰糲糴糶糹糾紀紂紃約紅紆紇紈紉紋納紐紓純紕紖紗紘紙級紛紜紝紞紡紬紮細紱紲紳紵紹紺紼紿絀終絃組絅絆絎結絕絛絝絞絡絢給絨絪絰統絲絳絶絹絺綁綃綄綆綈綉綌綎綏綐綑經綖綜綝綞綠綡綢綣綧綪綫綬維綯綰綱網綳綴綵綸綹綺綻綽綾綿緄緇緊緋緑緒緓緔緗緘緙線緝緞締緡緣緦編緩緬緯緱緲練緶緹緻緼縈縉縊縋縐縑縕縗縛縝縞縟縣縧縫縭縮縯縱縲縳縴縵縶縷縹總績繃繅繆繒織繕繚繞繡繢繩繪繫繭繮繯繰繳繶繸繹繻繼繽繾繿纁纆纇纈纊續纍纏纓纔纕纖纘纜缽罃罈罌罎罰罵罷羅羆羈羋羣羥羨義羶習翫翬翹翽耬耮聖聞聯聰聲聳聵聶職聹聽聾肅脅脈脛脣脩脫脹腎腖腡腦腫腳腸膃膕膚膞膠膢膩膽膾膿臉臍臏臘臚臟臠臢臥臨臺與興舉舊舖舘艙艤艦艫艱艷芻苧茲荊莊莖莢莧華菴菸萇萊萬萴萵葉葒葤葦葯葷蒍蒐蒓蒔蒕蒞蒼蓀蓆蓋蓮蓯蓴蓽蔄蔔蔘蔞蔣蔥蔦蔭蔯蔿蕁蕆蕎蕒蕓蕕蕘蕢蕩蕪蕭蕷薀薈薊薌薑薔薘薟薦薩薳薴薵薹薺藍藎藝藥藪藭藴藶藹藺蘀蘄蘆蘇蘊蘋蘚蘞蘟蘢蘭蘺蘿虆虉處虛虜號虧虯蛺蛻蜆蝀蝕蝟蝦蝨蝸螄螞螢螮螻螿蟄蟈蟎蟣蟬蟯蟲蟳蟶蟻蠁蠅蠆蠍蠐蠑蠔蠟蠣蠨蠱蠶蠻衆衊術衕衚衛衝袞袷裊裏補裝裡製複褌褘褲褳褸褻襀襇襉襏襖襝襠襤襪襬襯襲襴覈見覎規覓視覘覡覥覦親覬覯覲覷覺覽覿觀觴觶觸訁訂訃計訊訌討訏訐訒訓訕訖託記訛訝訟訢訣訥訩訪設許訴訶診註証詀詁詆詎詐詒詔評詖詗詘詛詝詞詠詡詢詣試詩詪詫詬詭詮詰話該詳詵詷詼詿誄誅誆誇誌認誑誒誕誘誚語誠誡誣誤誥誦誨說説誰課誶誹誼誾調諂諄談諉請諍諏諑諒諓論諗諛諜諝諞諟諡諢諤諦諧諫諭諮諱諲諳諴諶諷諸諺諼諾謀謁謂謄謅謊謎謏謐謔謖謗謙謚講謝謠謡謨謫謬謭謳謹謾譁證譎譏譓譖識譙譚譜譞譟譫譭譯議譴護譸譽譾讀讅變讋讌讎讒讓讕讖讚讜讞谿豈豎豐豔豬豶貍貓貙貝貞貟負財貢貧貨販貪貫責貯貰貲貳貴貶買貸貺費貼貽貿賀賁賂賃賄賅資賈賊賑賒賓賕賙賚賜賞賠賡賢賣賤賦賧質賫賬賭賰賴賵賺賻購賽賾贄贅贇贈贊贋贍贏贐贓贔贖贗贛贜赬趕趙趨趲跡踐踰踴蹌蹕蹟蹠蹣蹤蹺躂躉躊躋躍躎躑躒躓躕躚躡躥躦躪軀車軋軌軍軏軑軒軔軛軝軟軤軫軲軸軹軺軻軼軾較輄輅輇輈載輊輋輒輓輔輕輗輛輜輝輞輟輥輦輩輪輬輮輯輳輶輸輻輼輾輿轀轂轄轅轆轉轍轎轔轟轡轢轤辦辭辮辯農迴逕這連週進遊運過達違遙遜遞遠遡適遲遶遷選遺遼邁還邇邊邏邐郟郵鄆鄉鄒鄔鄖鄧鄩鄭鄰鄲鄳鄴鄶鄺酇酈醃醖醜醞醟醣醫醬醱醲釀釁釃釅釋釐釒釓釔釕釗釘釙針釣釤釦釧釩釴釵釷釹釺釾釿鈀鈁鈃鈄鈅鈇鈈鈉鈍鈎鈐鈑鈒鈔鈕鈞鈡鈣鈥鈦鈧鈮鈰鈳鈴鈷鈸鈹鈺鈽鈾鈿鉀鉅鉆鉈鉉鉊鉋鉍鉑鉕鉗鉚鉛鉝鉞鉢鉤鉥鉦鉧鉬鉭鉮鉳鉶鉷鉸鉺鉻鉿銀銃銅銈銍銑銓銖銘銚銛銜銠銣銥銦銨銩銪銫銬銱銳銶銷銹銻銼鋁鋃鋅鋇鋌鋏鋐鋒鋗鋙鋝鋟鋣鋤鋥鋦鋨鋩鋪鋭鋮鋯鋰鋱鋶鋸鋹鋼錀錁錄錆錇錈錏錐錒錕錘錙錚錛錞錟錠錡錢錤錦錨錩錫錮錯録錳錶錸錼鍀鍁鍃鍅鍆鍇鍈鍊鍋鍍鍔鍘鍚鍛鍠鍤鍥鍩鍬鍭鍰鍵鍶鍺鍼鍾鎂鎄鎇鎊鎌鎓鎔鎖鎘鎚鎛鎝鎡鎢鎣鎦鎧鎩鎪鎬鎭鎮鎰鎲鎳鎵鎶鎸鎿鏃鏇鏈鏌鏍鏏鏐鏑鏗鏘鏜鏝鏞鏟鏡鏢鏤鏨鏰鏵鏷鏹鏺鏻鏽鐃鐄鐇鐋鐍鐏鐐鐒鐓鐔鐘鐙鐝鐠鐥鐦鐧鐨鐩鐫鐮鐯鐲鐳鐵鐶鐸鐺鐽鐿鑄鑊鑌鑑鑒鑔鑕鑞鑠鑣鑥鑪鑭鑰鑱鑲鑷鑹鑼鑽鑾鑿钁钂長門閂閃閆閈閉開閌閎閏閑閒間閔閘閡閣閤閥閨閩閫閬閭閱閲閶閹閻閼閽閾閿闃闆闇闈闉闊闋闌闍闐闑闒闓闔闕闖關闞闠闡闢闤闥陘陝陞陣陰陳陸陽隉隊階隑隕際隤隨險隮隯隱隴隸隻雋雖雙雛雜雞離難雲電霑霢霧霽靂靄靆靈靉靚靜靝靦靨鞏鞝鞦鞽韁韃韆韉韋韌韍韓韙韜韝韞韻響頁頂頃項順頇須頊頌頍頎頏預頑頒頓頔頗領頜頠頡頤頦頫頭頮頰頲頴頵頷頸頹頻頽顆題額顎顏顒顓顔顗願顙顛類顢顥顧顫顬顯顰顱顳顴風颭颮颯颱颳颶颸颺颻颼飀飄飆飈飛飠飢飣飥飩飪飫飭飯飱飲飴飼飽飾飿餃餄餅餈餉養餌餎餏餑餒餓餕餖餗餘餚餛餜餞餡館餬餱餳餵餶餷餸餺餼餾餿饁饃饅饈饉饊饋饌饑饒饗饘饜饞饢馬馭馮馱馳馴馹馼駁駃駉駐駑駒駓駔駕駘駙駛駝駟駡駢駪駭駰駱駸駼駿騁騂騄騅騊騌騍騎騏騑騖騙騞騠騤騧騫騭騮騰騱騵騶騷騸騾驀驁驂驃驄驅驊驌驍驎驏驕驗驚驛驟驢驤驥驦驪驫骯髏髒體髕髖髮鬆鬍鬚鬢鬥鬧鬨鬩鬮鬱鬹魎魘魚魛魟魢魨魯魴魷魺鮀鮁鮃鮆鮈鮊鮋鮍鮎鮐鮑鮒鮓鮚鮜鮝鮞鮟鮠鮡鮣鮦鮪鮫鮭鮮鮳鮶鮸鮺鯀鯁鯇鯉鯊鯒鯔鯕鯖鯗鯛鯝鯡鯢鯤鯧鯨鯪鯫鯰鯴鯷鯻鯽鯿鰁鰂鰃鰆鰈鰉鰊鰌鰍鰏鰐鰒鰓鰛鰜鰟鰠鰣鰤鰥鰧鰨鰩鰭鰮鰱鰲鰳鰵鰶鰷鰹鰺鰻鰼鰾鱀鱂鱅鱇鱈鱉鱒鱔鱖鱗鱘鱚鱝鱟鱠鱣鱤鱧鱨鱭鱯鱲鱷鱸鱺鳥鳧鳩鳬鳲鳳鳴鳶鳾鴆鴇鴉鴒鴕鴛鴝鴞鴟鴣鴦鴨鴯鴰鴴鴷鴻鴿鵁鵂鵃鵏鵐鵑鵒鵓鵜鵝鵟鵠鵡鵪鵬鵮鵯鵰鵲鵷鵾鶄鶇鶉鶊鶓鶖鶘鶚鶠鶡鶥鶩鶪鶬鶯鶱鶲鶴鶹鶺鶻鶼鶿鷀鷁鷂鷄鷉鷊鷓鷖鷗鷙鷚鷟鷥鷦鷫鷭鷯鷲鷳鷴鷸鷹鷺鷽鸂鸇鸊鸌鸏鸑鸕鸘鸚鸛鸝鸞鹵鹹鹺鹼鹽麗麥麩麪麫麬麯麳麴麵麼麽黃黌點黨黲黴黶黷黽黿鼂鼉鼕鼴齊齋齎齏齒齔齕齗齘齙齜齟齠齡齣齦齧齪齬齮齯齲齶齷齼龍龎龐龑龔龕龜鿁鿓𠁞𠗣𡃕𡅏𡑍𡑭𡓾𡔖𡞵𡠹𡢃𡮉𡮣𡳳𡻕𡾱𢣚𢶫𢹿𣈶𣙎𣞻𣠩𣠲𣯶𣾷𤁣𤅶𤓩𤪺𤫩𤳸𥊝𥌃𥕥𥖅𥗽𥢢𥸠𥼽𦘧𦣎𦪙𧜗𧜵𧝞𧟀𧩙𧵳𧶧𨊰𨊸𨋢𨤻𨦫𨧀𨧜𨨏𨭆𨭎𨯅𩞯𩠴𩣑𩶘𰻞"  # noqa: E501
_T2S_SIMP = "㑔㑇㐹刾𠵾㘎㚯㛣𡞱㟆𫵷㤘㨫㧐擜𤠋𥇢䀥鿎䌶䌺䌻䌿䌾䍠䎬𬜯䙌䜧䞍𫟦䦂鿏𬭯䥾䦶䦷𨸟𫠊䯅鲃䲣䲝鳚鳤鹮丢并干乱亘亚伫布占并来仑侣局俣系伣侠伡私伥俩俫仓个们幸伦㑈伟㐽侧侦伪㐷杰伧伞备家佣偬传伛债伤倾偻仅佥侨仆伪𫢸侥偾雇价仪俊侬亿侩俭傤傧俦侪尽偿优储俪㑩傩傥俨凶兑儿兖内两册胄幂净冻凛凯别删刭则克刹刬刚剥剐剀创铲划札剧刘刽刿剑㓥剂㔉劲动务勋胜劳势𪟝勚劢勋励劝匀匦汇匮区协恤却即厍厕历厌厉厣参叁丛咤吴呐吕呙员呗念问启哑启唡㖞唤丧吃乔单哟呛啬唝吗呜唢𠮶哔叹喽啯呕啧尝唛哗唠啸叽哓呒啴恶嘘㖊咝哒哝哕嗳哙喷吨当咛吓哜尝噜啮咽呖𠰷咙向亸喾严嘤啭嗫嚣冁呓啰苏嘱囱囵国围园圆图团坝垭𫭢采执坚垩垴埚尧报场块茔垲埘涂冢坞埙尘𫭟堑𪣻垫坠𫮃堕坛坟垯墙垦坛垱埙压𡋤垒圹垆坛坏垄垅坜坝塆壮壶壸寿够梦伙夹奂奥奁夺奖奋姹妆姗奸𫰛娱娄妇娅娲妫㛀媪妈袅妪妩娴娴婳妫媭娆婵娇嫱嫒嬷嫔婴婶娘㛤娈孙学𡥧孪宫采寝实宁审写宽宠宝将专寻对导尴届尸屃屉屡层屦属冈峰岘岛峡崃昆岗仑峥岽岚岁𫶇㟥嵝崭岖嵚崂峤峣峄峃崄嵘岭屿岳岿峦巅岩𪩘巯卺帅师帐带帧帏㡎帼帻帜币帮帱并干几库厕厢厩厦庼荫厨厮𫷷庙厂庑废广廪庐厅弑吊弪张强𫸩别弹弥弯录汇彟彦雕彨佛后径从徕复征彻恒耻悦悮怅闷凄恶恼恽恻爱惬悫怆恺忾栗态愠惨惭恸惯悫怄怂虑悭庆㥪戚欲忧惫怜凭愦慭惮愤悯怃宪忆恳应怿懔蒙怼懑㤽恹惩懒怀悬忏惧慑恋戆戋戗戬战戯戏户捍抛拼捝挲挟舍扪挨卷扫抡㧏挜挣挂采拣扬换挥搄损摇捣扇揾抢掴掼搂挚抠抟折掺捞挦撑挠㧑挢掸拨抚扑揿挞挝捡拥掳择击挡㧟担据挤抬捣拟摈拧搁掷扩撷摆擞撸㧰扰摅撵拢拦撄搀撺携摄攒挛摊搅揽教敚败叙敌数敛毙敩斓斩断于旗既升时晋𬀪昼晕晖𬀩旸畅暂晔历昙晓向暧旷𣆐昽晒书会𦛨胧术东拐栅拐查𣐕杆栀枧𬂩条枭棁弃棋枨枣栋㭎栈栖梾桠㭏杨枫桢业极矩干杩荣榅桤构枪杠梿椠椁椮桨椢椝桩乐枞梁楼标枢㭤样榝㭴桪朴树桦椫桡桥机椭横𣓿檩柽档桧槚检樯梼台槟柠槛柜𬃊橹榈栉椟橼栎橱槠栌枥橥榇蘖栊榉樱栏榉权椤栾𣗋榄棂钦叹欧欤欢岁历归殁残殒殇㱮殚僵殓殡㱩歼杀壳壳毁殴毵牦毡氇气氢氩氲泛泛污决没冲况溯泄汹浃𬇙泾涚凉凄泪渌净凌沦渊涞浅涣减沨涡测浑凑𣲗浈涌汤沩准沟温浉涢湿沧灭涤荥汇沪滞渗卤浒浐滚满渔溇𬇹沤汉涟渍涨溆渐浆颍泼洁𣲘沩㴋潜润浔溃滗涠涩浇涝沄涧渑泽滪泶𬇕浍淀㳠浊浓㳡𣸣湿泞溁蒙浕济涛㳔滥潍滨溅泺滤澛滢渎㲿泻沈浏濒泸沥潇潆潴泷濑弥潋澜沣滠洒𪷽漓滩𣺼灏㳕湾滦滟滟灾为乌烃无炼炜烟茕焕烦炀㶽煴荧炝𬉼热颎炽𬊤烨灯炖烧𬊈烫焖营灿毁烛烩㶶熏烬焘烁炉烂争为爷尔床墙牍抵牵荦牦犊牺状狭狈狰犹狲犸呆狱狮奖独狯猃狝狞㺍获猎犷兽獭献猕猡现雕珐珲玮玚琐瑶莹玛玱琏𫞩𬍤𬍡琎玑瑷珰㻅环玙瑸玺璇𬍛琼珑璎瓒𤩽瓯瓮产产亩毕画异画当畴叠痉酸疴痖疯疡痪瘗疮疟瘆疭瘘瘘疗痨痫瘅愈疠瘪痴痒疖症疬癞癣瘿瘾痈瘫癫发皂皑疱皲皱杯盗盏尽监盘卢荡真眦众𪾢困睁睐眍䁖瞒瞆睑蒙眬瞩矫朱硁硖砗砚埼硕砀砜确码䂵硙砖硵碜碛矶硗䃅硚础𬒈碍矿砺砾矾砻秘禄祸祯祎祃御禅礼祢祷秃籼税秆䅉棱禀种称谷䅟稣积颖秾穑秽稳获穞窝洼穷窑窎窭窥窜窍窦灶窃竖竞笔笋笕䇲个笺筝札节范筑箧筼筿𬕂笃筛筚𥮾箦篓蓑箪简篑箫筜签帘篮𥫣筹䉤箓篯箨籁笼签笾簖篱箩吁粤粽糁粪粮团粝籴粜纟纠纪纣𬘓约红纡纥纨纫纹纳纽纾纯纰纼纱纮纸级纷纭纴𬘘纺䌷扎细绂绁绅纻绍绀绋绐绌终弦组䌹绊绗结绝绦绔绞络绚给绒𬘡绖统丝绛绝绢𫄨绑绡𬘫绠绨绣绤𬘩绥䌼捆经𫄧综𬘭缍绿𫟅绸绻𬘯𬘬线绶维绹绾纲网绷缀彩纶绺绮绽绰绫绵绲缁紧绯绿绪绬绱缃缄缂线缉缎缔缗缘缌编缓缅纬缑缈练缏缇致缊萦缙缢缒绉缣缊缞缚缜缟缛县绦缝缡缩𬙂纵缧䌸纤缦絷缕缥总绩绷缫缪缯织缮缭绕绣缋绳绘系茧缰缳缲缴𫄷䍁绎𦈡继缤缱䍀𫄸𬙊颣缬纩续累缠缨才𬙋纤缵缆钵䓨坛罂坛罚骂罢罗罴羁芈群羟羡义膻习玩翚翘翙耧耢圣闻联聪声耸聩聂职聍听聋肃胁脉胫唇修脱胀肾胨脶脑肿脚肠腽腘肤䏝胶𦝼腻胆脍脓脸脐膑腊胪脏脔臜卧临台与兴举旧铺馆舱舣舰舻艰艳刍苎兹荆庄茎荚苋华庵烟苌莱万荝莴叶荭荮苇药荤𫇭搜莼莳蒀莅苍荪席盖莲苁莼荜𬜬卜参蒌蒋葱茑荫𫈟𫇭荨蒇荞荬芸莸荛蒉荡芜萧蓣蕰荟蓟芗姜蔷荙莶荐萨䓕苧䓓苔荠蓝荩艺药薮䓖蕴苈蔼蔺萚蕲芦苏蕴苹藓蔹𦻕茏兰蓠萝蔂𬟁处虚虏号亏虬蛱蜕蚬𬟽蚀猬虾虱蜗蛳蚂萤䗖蝼螀蛰蝈螨虮蝉蛲虫𫊻蛏蚁蚃蝇虿蝎蛴蝾蚝蜡蛎蟏蛊蚕蛮众蔑术同胡卫冲衮夹袅里补装里制复裈袆裤裢褛亵𫌀裥裥袯袄裣裆褴袜摆衬袭襕核见觃规觅视觇觋觍觎亲觊觏觐觑觉览觌观觞觯触讠订讣计讯讧讨𬣙讦讱训讪讫托记讹讶讼䜣诀讷讻访设许诉诃诊注证𧮪诂诋讵诈诒诏评诐诇诎诅𬣞词咏诩询诣试诗𬣳诧诟诡诠诘话该详诜𫍣诙诖诔诛诓夸志认诳诶诞诱诮语诚诫诬误诰诵诲说说谁课谇诽谊訚调谄谆谈诿请诤诹诼谅𬣡论谂谀谍谞谝𬤊谥诨谔谛谐谏谕咨讳𬤇谙𫍯谌讽诸谚谖诺谋谒谓誊诌谎谜𫍲谧谑谡谤谦谥讲谢谣谣谟谪谬谫讴谨谩哗证谲讥𬤝谮识谯谭谱𫍽噪谵毁译议谴护诪誉谫读谉变詟䜩雠谗让谰谶赞谠谳溪岂竖丰艳猪豮狸猫䝙贝贞贠负财贡贫货贩贪贯责贮贳赀贰贵贬买贷贶费贴贻贸贺贲赂赁贿赅资贾贼赈赊宾赇赒赉赐赏赔赓贤卖贱赋赕质赍账赌䞐赖赗赚赙购赛赜贽赘赟赠赞赝赡赢赆赃赑赎赝赣赃赪赶赵趋趱迹践逾踊跄跸迹跖蹒踪跷跶趸踌跻跃䟢踯跞踬蹰跹蹑蹿躜躏躯车轧轨军𫐄轪轩轫轭𬨂软轷轸轱轴轵轺轲轶轼较𨐈辂辁辀载轾𪨶辄挽辅轻𫐐辆辎辉辋辍辊辇辈轮辌𫐓辑辏𬨎输辐辒辗舆辒毂辖辕辘转辙轿辚轰辔轹轳办辞辫辩农回径这连周进游运过达违遥逊递远溯适迟绕迁选遗辽迈还迩边逻逦郏邮郓乡邹邬郧邓𬩽郑邻郸𫑡邺郐邝酂郦腌酝丑酝蒏糖医酱酦𬪩酿衅酾酽释厘钅钆钇钌钊钉钋针钓钐扣钏钒𬬩钗钍钕钎䥺𬬱钯钫钘钭钥𫓧钚钠钝钩钤钣钑钞钮钧钟钙钬钛钪铌铈钶铃钴钹铍钰钸铀钿钾巨钻铊铉𬬿铇铋铂钷钳铆铅𫟷钺钵钩𬬸钲𬭁钼钽𬬹锫铏𫟹铰铒铬铪银铳铜𫓯铚铣铨铢铭铫铦衔铑铷铱铟铵铥铕铯铐铞锐𨱇销锈锑锉铝锒锌钡铤铗𬭎锋𫓶铻锊锓铘锄锃锔锇铓铺锐铖锆锂铽锍锯𬬮钢𬬭锞录锖锫锩铔锥锕锟锤锱铮锛𬭚锬锭锜钱𫓹锦锚锠锡锢错录锰表铼镎锝锨锪钫钔锴锳炼锅镀锷铡钖锻锽锸锲锘锹𬭤锾键锶锗针钟镁锿镅镑镰𬭩镕锁镉锤镈𨱏镃钨蓥镏铠铩锼镐镇镇镒镋镍镓鿔镌镎镞旋链镆镙𬭬镠镝铿锵镗镘镛铲镜镖镂錾镚铧镤镪䥽𬭸锈铙𨱑𫔍铴𫔎𨱔镣铹镦镡钟镫镢镨䦅锎锏镄𬭼镌镰䦃镯镭铁镮铎铛𫟼镱铸镬镔鉴鉴镲锧镴铄镳镥𬬻镧钥镵镶镊镩锣钻銮凿镢镋长门闩闪闫闬闭开闶闳闰闲闲间闵闸阂阁合阀闺闽阃阆闾阅阅阊阉阎阏阍阈阌阒板暗闱𬮱阔阕阑阇阗𫔶阘闿阖阙闯关阚阓阐辟阛闼陉陕升阵阴陈陆阳陧队阶𬮿陨际𬯎随险𬯀陦隐陇隶只隽虽双雏杂鸡离难云电沾霡雾霁雳霭叇灵叆靓静靔腼靥巩绱秋鞒缰鞑千鞯韦韧韨韩韪韬鞲韫韵响页顶顷项顺顸须顼颂𫠆颀颃预顽颁顿𬱖颇领颌𬱟颉颐颏𫖯头颒颊颋颕𫖳颔颈颓频颓颗题额颚颜颙颛颜𫖮愿颡颠类颟颢顾颤颥显颦颅颞颧风飐飑飒台刮飓飔飏飖飕飗飘飙飚飞饣饥饤饦饨饪饫饬饭飧饮饴饲饱饰饳饺饸饼糍饷养饵饹饻饽馁饿馂饾𫗧余肴馄馃饯馅馆糊糇饧喂馉馇𩠌馎饩馏馊馌馍馒馐馑馓馈馔饥饶飨𫗴餍馋馕马驭冯驮驰驯驲𫘜驳𫘝𬳶驻驽驹𬳵驵驾骀驸驶驼驷骂骈𬳽骇骃骆骎𬳿骏骋骍𫘧骓𫘦骔骒骑骐𬴂骛骗𬴃𫘨骙䯄骞骘骝腾𫘬𫘪驺骚骟骡蓦骜骖骠骢驱骅骕骁𬴊骣骄验惊驿骤驴骧骥骦骊骉肮髅脏体髌髋发松胡须鬓斗闹哄阋阄郁鬶魉魇鱼鱽𫚉鱾鲀鲁鲂鱿鲄𬶍鲅鲆𫚖𬶋鲌鲉鲏鲇鲐鲍鲋鲊鲒鲘鲞鲕𩽾𬶏𬶐䲟鲖鲔鲛鲑鲜鲓鲪𩾃鲝鲧鲠鲩鲤鲨鲬鲻鲯鲭鲞鲷鲴鲱鲵鲲鲳鲸鲮鲰鲶鲺鳀𬶟鲫鳊鳈鲗鳂䲠鲽鳇𬶠䲡鳅鲾鳄鳆鳃鳁鳒鳑鳋鲥𫚕鳏䲢鳎鳐鳍鳁鲢鳌鳓鳘𬶭鲦鲣鲹鳗鳛鳔𬶨鳉鳙𩾌鳕鳖鳟鳝鳜鳞鲟𬶮鲼鲎鲙鳣鳡鳢鲿鲚鳠𫚭鳄鲈鲡鸟凫鸠凫鸤凤鸣鸢䴓鸩鸨鸦鸰鸵鸳鸲鸮鸱鸪鸯鸭鸸鸹鸻䴕鸿鸽䴔鸺鸼𬷕鹀鹃鹆鹁鹈鹅𫛭鹄鹉鹌鹏鹐鹎雕鹊鹓鹍䴖鸫鹑鹒鹋鹙鹕鹗𬸘鹖鹛鹜䴗鸧莺𬸣鹟鹤鹠鹡鹘鹣鹚鹚鹢鹞鸡䴘鹝鹧鹥鸥鸷鹨𬸦鸶鹪鹔𬸪鹩鹫鹇鹇鹬鹰鹭鸴㶉鹯䴙鹱鹲𬸚鸬鹴鹦鹳鹂鸾卤咸鹾碱盐丽麦麸面面𤿲曲𪎌曲面么么黄黉点党黪霉黡黩黾鼋鼌鼍冬鼹齐斋赍齑齿龀龁龂𬹼龅龇龃龆龄出龈啮龊龉𬺈𫠜龋腭龌𬺓龙厐庞䶮龚龛龟䜤鿒𠀾㓆𠴛𠲥𫭼𡋗𡋀𡍣㛟㛿㛠𡭜𡭬𡳃岁㟜𢘝𢫞𢬦暅㭣𣘓𣞎𣑶毶㳢𣺽𣷷𤊰㻘㻏𤳄𥅿𥅘𥐰𥐯𬒗䅪𥮋𥹥𡳒𦟗䑽䘞䙊䘛𧝧䜥䞌䞎䢀䢁䢂𨤰䦀𬭊䦁𬭛𬭶𬭳䥿䭪𩠠䯃䲞𰻝"  # noqa: E501
_T2S_TABLE = str.maketrans(_T2S_TRAD, _T2S_SIMP)

# 引号类字符整体去掉。全半角引号在 normalize_text 已折成 ASCII 引号，这里进一步删掉，
# 专治"原文没引号、LLM 引用时给术语加了引号"（如原文「魏王」被引成 '魏王'）。两边都删，一致。
_QUOTE_STRIP = str.maketrans({c: None for c in "\"'`"})

# 省略号切分：… / ⋯ 一串，或 2 个以上 ASCII 点。单个句号（。已折成 .）不切——
# 否则会把正常一句话切碎。用来把"跨段原话用省略号拼起来"拆回可逐段核的片段。
_ELLIPSIS_RE = re.compile(r"[…⋯]+|\.{2,}")


def normalize_text(s: str) -> str:
    """归一化文本：去掉所有空白字符，全角标点转半角。

    比对前两边都过这一层，让空白差异与全半角标点差异不影响匹配。
    """
    no_space = "".join(s.split())
    return no_space.translate(_PUNCT_TRANSLATION)


def _normalize_loose(s: str) -> str:
    """宽松归一：在 :func:`normalize_text` 之上再做繁→简折叠 + 去引号。

    只在主比对判 ``none`` 后的二次核验里用，不参与主比对，不改其语义。
    """
    return normalize_text(s).translate(_T2S_TABLE).translate(_QUOTE_STRIP)


def char_ngram_containment(needle: str, haystack: str, n: int = _NGRAM_SIZE) -> float:
    """needle 的字符 n-gram 集合有多大比例出现在 haystack 里，返回 0-1。

    containment 而不是 Jaccard：haystack（整个 chunk）天然比 needle
    （一句引用）长得多，Jaccard 会被 haystack 的体量稀释；containment
    只问"引用里的碎片有多少真在原文里"，方向正确。

    needle 太短凑不出一个 n-gram 时返回 0.0（无法判定按不命中处理）。
    """
    if len(needle) < n or len(haystack) < n:
        return 0.0
    needle_grams = {needle[i : i + n] for i in range(len(needle) - n + 1)}
    if not needle_grams:
        return 0.0
    haystack_grams = {haystack[i : i + n] for i in range(len(haystack) - n + 1)}
    hit = sum(1 for g in needle_grams if g in haystack_grams)
    return hit / len(needle_grams)


def _disambiguate_by_chapter(
    cids: list[str],
    self_chapter: object,
    evidence: dict[str, dict],
) -> str:
    """多个 chunk 都逐字命中同一 snippet 时，用调用方传入的自报章号当弱先验选一个。

    同/近文字跨章复现（母题回环、伏笔回收、同名不同事）是注释类功能的高频场景——
    旧实现取字典里第一个命中者、不看上下文，会系统性贴到错的那一章（probe 实测
    锚错率 60%）。这里用 LLM 自报章号（verify 时尚未被真章号覆盖）做 tie-break：
    先取章号正相等的，没有就取最近的；无可用先验时退回确定性首个——不传章号的
    调用方行为完全不变，向后兼容。

    自报章号是弱先验、不是真值：只在"都逐字命中"的候选之间做选择，最终章号仍由
    调用方拿命中 chunk 的真章号覆盖。
    """
    if len(cids) == 1 or not isinstance(self_chapter, int):
        return cids[0]
    same = [c for c in cids if evidence.get(c, {}).get("chapter") == self_chapter]
    if same:
        return same[0]
    numbered = [c for c in cids if isinstance(evidence.get(c, {}).get("chapter"), int)]
    if numbered:
        return min(numbered, key=lambda c: abs(evidence[c]["chapter"] - self_chapter))
    return cids[0]


def build_evidence_map(chunks: list[dict]) -> dict[str, dict]:
    """把 chunk 列表收成 :func:`verify_citations` 要的证据登记表 ``{chunk_id: {chapter, text}}``。

    缺 ``chunk_id`` 的 chunk 丢掉（没它当不了登记 id）；``chapter`` 缺退 0、``text`` 缺退空串。
    各结构化抽取功能（人物图 / 时间线 / 伏笔弧等）核验前都先建这张表，逻辑一份收在这里。
    """
    return {
        str(c["chunk_id"]): {"chapter": c.get("chapter", 0), "text": c.get("text", "")}
        for c in chunks
        if c.get("chunk_id")
    }


def _loose_verify(
    snippet_raw: str,
    self_chapter: object,
    loose_evidence: dict[str, str],
    evidence: dict[str, dict],
) -> tuple[bool, str, float, str] | None:
    """宽松二次核验：主比对判 none 后再核一遍。命中返回 ``(True, chunk_id, score, match_type)``，
    仍核不上返回 ``None``。

    三条通路，条条守精度（不相干文本进不来）：

    1. **省略号切片段**：snippet 含省略号时拆成片段，够长（≥ :data:`_LOOSE_MIN_LEN`）的
       片段**逐个**都要是某 chunk 的宽松逐字子串——全部命中才算 ``quote``；任一够长片段
       找不到就不认（这正是拼接跨段真原话的形态：每段都真才认）。
    2. **单片段逐字**：整条（够长）是某 chunk 的宽松逐字子串 → ``quote`` 1.0。治繁简不一致 /
       多了引号 / 超短带一处装饰差异的真原文——归一化后它就是原文里的字，一字不差。
    3. **单片段高重叠**：逐字不中时求 n-gram containment，≥ :data:`CONTAINMENT_THRESHOLD`
       → ``paraphrase``。治被繁体打断、主比对没够着阈值的轻改写。

    ``loose_evidence`` 是各 chunk 过 :func:`_normalize_loose` 的文本；``evidence`` 供
    多命中时按章号消歧（复用 :func:`_disambiguate_by_chapter`）。
    """
    frags = [nf for nf in (_normalize_loose(f) for f in _ELLIPSIS_RE.split(snippet_raw)) if nf]
    if not frags:
        return None

    # ---- 通路 1：省略号拼接的多片段，逐段逐字核 ----
    if len(frags) > 1:
        substantive = [f for f in frags if len(f) >= _LOOSE_MIN_LEN]
        if not substantive:
            return None  # 全是碎片，单独谁都不足以断定出处 → 守精度不认
        anchor: tuple[str, list[str]] | None = None
        for f in substantive:
            hits = [cid for cid, text in loose_evidence.items() if text and f in text]
            if not hits:
                return None  # 有一段够长的找不到 → 不是"每段都真" → 不认
            if anchor is None or len(f) > len(anchor[0]):
                anchor = (f, hits)
        assert anchor is not None
        return True, _disambiguate_by_chapter(anchor[1], self_chapter, evidence), 1.0, "quote"

    # ---- 单片段 ----
    frag = frags[0]

    # 通路 2：整条是某 chunk 的宽松逐字子串。不设长度下限——与主比对的逐字判一致
    # （主比对对精确子串也不设下限），归一化后一字不差的就是原文，无论长短；这样
    # 短到 2-3 字、只差一个引号/繁简的真原文（如原文「魏王」被引成 '魏王'）也捞得回来。
    hits = [cid for cid, text in loose_evidence.items() if text and frag in text]
    if hits:
        return True, _disambiguate_by_chapter(hits, self_chapter, evidence), 1.0, "quote"

    # 通路 3：高重叠子串（轻改写被繁简打断的召回）
    best_score = 0.0
    best_chunk_id: str | None = None
    for cid, text in loose_evidence.items():
        if not text:
            continue
        score = char_ngram_containment(frag, text)
        if score > best_score:
            best_score = score
            best_chunk_id = cid
    if best_score >= CONTAINMENT_THRESHOLD and best_chunk_id is not None:
        return True, best_chunk_id, best_score, "paraphrase"

    return None


def verify_citations(
    citations: list[dict],
    evidence: dict[str, dict],
) -> list[dict]:
    """对每条 citation 比对证据登记表，附加 verified / chunk_id / match_score。

    Args:
        citations: final answer 解析出的引用列表，每条至少含
            ``chapter`` + ``snippet``。原有字段不动，新字段附加。``chapter``
            （LLM 自报值）还兼作多命中消歧的弱先验——同一 snippet 在多个 chunk
            逐字命中时，优先选章号与自报值相符/最近的那个（见
            :func:`_disambiguate_by_chapter`）；不传 ``chapter`` 的调用方退回首个，行为不变。
        evidence: 证据登记表，``{chunk_id: {"chapter": int, "text": str}}``。

    Returns:
        同一批 citation dict（原地附加后返回）。标注算法：

        1. snippet 归一化后是任一登记 chunk 归一化文本的精确子串
           → ``verified=True, match_score=1.0, chunk_id=命中者``
        2. 否则对全部登记 chunk 求最大 3-gram containment：
           ≥ :data:`CONTAINMENT_THRESHOLD` → ``verified=True`` + 命中 chunk_id；
        3. 主比对（1、2）都没过，再走 :func:`_loose_verify` 宽松二次核验（繁简折叠 /
           去引号 / 省略号切片段），命中就把 verified / chunk_id / match_score /
           match_type 覆盖成宽松通路的结果；仍不过才落 ``verified=False,
           chunk_id=None, match_type="none"``，``match_score`` 记主比对最大值（供观测分布用）。
    """
    # 登记表归一化只做一遍，不在每条 citation 里重复算
    normalized_evidence = {
        cid: normalize_text(str(entry.get("text", "")))
        for cid, entry in evidence.items()
    }
    # 宽松登记表按需构建（只有真出现主比对不过的 citation 才建，happy path 零开销）：
    # 复用已算好的 normalized_evidence，只再叠繁简折叠 + 去引号。
    loose_evidence: dict[str, str] | None = None

    for cit in citations:
        snippet = normalize_text(str(cit.get("snippet", "")))

        # 第一遍只收逐字命中（子串判断便宜）。收全部、不 break——多命中时要消歧，
        # 不能像旧实现那样取字典首个（那会在文字跨章复现时系统性锚错章，probe 锚错 60%）。
        exact_cids = [
            cid
            for cid, norm_text in normalized_evidence.items()
            if snippet and norm_text and snippet in norm_text
        ]

        if exact_cids:
            cit["verified"] = True
            cit["chunk_id"] = _disambiguate_by_chapter(
                exact_cids, cit.get("chapter"), evidence
            )
            cit["match_score"] = 1.0
            cit["match_type"] = "quote"  # 逐字命中（归一化后精确子串）
            continue

        # 没逐字命中才求 containment（贵），取最大的那个 chunk
        best_score = 0.0
        best_chunk_id: str | None = None
        for cid, norm_text in normalized_evidence.items():
            if not snippet or not norm_text:
                continue
            score = char_ngram_containment(snippet, norm_text)
            if score > best_score:
                best_score = score
                best_chunk_id = cid

        if best_score >= CONTAINMENT_THRESHOLD:
            cit["verified"] = True
            cit["chunk_id"] = best_chunk_id
            cit["match_score"] = round(best_score, 2)
            cit["match_type"] = "paraphrase"  # 诚实转述（n-gram 覆盖过阈值但非逐字）
            continue

        # 主比对判 none —— 走宽松二次核验，把繁简 / 引号 / 省略号 / 超短的真原文捞回来
        if loose_evidence is None:
            loose_evidence = {
                cid: norm_text.translate(_T2S_TABLE).translate(_QUOTE_STRIP)
                for cid, norm_text in normalized_evidence.items()
            }
        loose = _loose_verify(
            str(cit.get("snippet", "")), cit.get("chapter"), loose_evidence, evidence
        )
        if loose is not None:
            verified, chunk_id, score, match_type = loose
            cit["verified"] = verified
            cit["chunk_id"] = chunk_id
            cit["match_score"] = round(score, 2)
            cit["match_type"] = match_type
        else:
            cit["verified"] = False
            cit["chunk_id"] = None
            cit["match_score"] = round(best_score, 2)
            cit["match_type"] = "none"  # 未核验（原文里找不到对应，宽松也没捞回）

    return citations


__all__ = [
    "CONTAINMENT_THRESHOLD",
    "build_evidence_map",
    "char_ngram_containment",
    "normalize_text",
    "verify_citations",
]
