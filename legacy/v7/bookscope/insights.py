"""BookScope quick-insight helpers.

Derives character names, key themes, readability grade, SVG sparkline,
and first-person density from existing analysis results.

Character extraction uses spaCy en_core_web_sm when available
(install with: pip install -e ".[spacy]"), falling back to regex NER.
All other helpers have zero new runtime dependencies (re + Counter only).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bookscope.models import ReaderVerdict

# ── spaCy NER — lazy-loaded, optional ────────────────────────────────────────

_spacy_nlp_loaded: bool = False
_spacy_nlp = None  # spacy.Language object or None


def _get_spacy_nlp():
    """Load spaCy en_core_web_sm once and cache. Returns None if unavailable."""
    global _spacy_nlp, _spacy_nlp_loaded
    if _spacy_nlp_loaded:
        return _spacy_nlp
    _spacy_nlp_loaded = True
    try:
        import spacy  # noqa: PLC0415
        _spacy_nlp = spacy.load("en_core_web_sm")
    except (ImportError, OSError):
        _spacy_nlp = None
    return _spacy_nlp


def _spacy_extract_names(
    chunks, top_n: int, min_frac: float
) -> list[str] | None:
    """Use spaCy PERSON entities. Returns None if spaCy is unavailable."""
    nlp = _get_spacy_nlp()
    if nlp is None:
        return None

    n = len(chunks)
    min_c = max(2, int(n * min_frac))
    chunk_pres: Counter = Counter()
    global_freq: Counter = Counter()

    for chunk in chunks:
        # Cap text per chunk so large chunks don't slow the pipeline
        doc = nlp(chunk.text[:5000])
        seen: set[str] = set()
        for ent in doc.ents:
            if ent.label_ == "PERSON":
                name = ent.text.strip()
                if len(name) >= 2:
                    global_freq[name] += 1
                    seen.add(name)
        for name in seen:
            chunk_pres[name] += 1

    candidates = {w: f for w, f in global_freq.items() if chunk_pres[w] >= min_c}
    return [w for w, _ in Counter(candidates).most_common(top_n)]


# ── Regex NER fallback ────────────────────────────────────────────────────────

_NON_NAMES = frozenset([
    "The", "He", "She", "They", "It", "We", "You", "But", "And",
    "So", "Then", "When", "While", "After", "His", "Her", "Their",
    "Its", "Our", "Mr", "Mrs", "Dr", "Chapter", "Part", "One", "Two",
    "Said", "Into", "From", "That", "This", "With", "Have", "Been",
    "Just", "Now", "Here", "There", "Again", "Like", "Even", "Well",
])

_NAME_PAT = re.compile(r'(?:^|(?<=[.!?\s]))[A-Z][a-z]{2,}\b')


def _regex_extract_names(chunks, top_n: int, min_frac: float) -> list[str]:
    n = len(chunks)
    min_c = max(2, int(n * min_frac))
    chunk_pres: Counter = Counter()
    global_freq: Counter = Counter()

    for chunk in chunks:
        seen: set[str] = set()
        for w in _NAME_PAT.findall(chunk.text):
            if w not in _NON_NAMES:
                global_freq[w] += 1
                if w not in seen:
                    chunk_pres[w] += 1
                    seen.add(w)

    candidates = {w: f for w, f in global_freq.items() if chunk_pres[w] >= min_c}
    return [w for w, _ in Counter(candidates).most_common(top_n)]


def extract_character_names(
    chunks, top_n: int = 5, min_frac: float = 0.05, lang: str = "en"
) -> list[str]:
    """Return top character-name candidates from English fiction chunks.

    Uses spaCy en_core_web_sm NER when installed (better accuracy, handles
    multi-word names and titles). Falls back to regex NER automatically.
    Returns [] immediately for CJK-script languages.
    """
    if lang in ("zh", "ja", "ko") or chunks is None:
        return []

    # Prefer spaCy NER (optional dep)
    result = _spacy_extract_names(chunks, top_n, min_frac)
    if result is not None:
        return result

    # Regex fallback
    return _regex_extract_names(chunks, top_n, min_frac)


# ── Key themes (academic / essay) ────────────────────────────────────────────

_STOPWORDS = frozenset([
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "is", "are", "was", "were", "be", "been", "has", "have",
    "had", "do", "does", "did", "will", "would", "could", "should", "this", "that",
    "these", "those", "it", "its", "we", "they", "he", "she", "you", "which", "who",
    "what", "when", "how", "also", "more", "most", "not", "no", "so", "if", "as",
    "than", "into", "about", "each", "other", "new", "however", "thus", "therefore",
    "said", "just", "very", "can", "may", "one", "two", "all", "any", "such", "then",
])

_WORD_PAT = re.compile(r'\b[a-z]{4,}\b')


def extract_key_themes(chunks, style_scores, top_n: int = 6) -> list[str]:
    """Return top thematic words weighted by noun_ratio.

    Uses noun_ratio from existing StyleScore objects — no POS re-tagging.
    """
    nr_map = {s.chunk_index: s.noun_ratio for s in style_scores}
    weighted: dict[str, float] = {}
    pres: Counter = Counter()

    for chunk in chunks:
        nr = nr_map.get(chunk.index, 0.2)
        weight = 0.5 + nr
        words = _WORD_PAT.findall(chunk.text.lower())
        seen: set[str] = set()
        for word in words:
            if word not in _STOPWORDS:
                weighted[word] = weighted.get(word, 0.0) + weight
                if word not in seen:
                    pres[word] += 1
                    seen.add(word)

    min_c = max(3, int(len(chunks) * 0.20))
    cands = {w: s for w, s in weighted.items() if pres[w] >= min_c}
    return [w for w, _ in sorted(cands.items(), key=lambda x: -x[1])[:top_n]]


# ── Readability grade ─────────────────────────────────────────────────────────

_READABILITY_LABELS = {
    "en": ("Accessible", "Moderate", "Dense", "Specialist"),
    "zh": ("通俗易读", "一般难度", "较难", "专业级"),
    "ja": ("読みやすい", "普通", "難しい", "専門的"),
}


def compute_readability(style_scores, ui_lang: str = "en") -> tuple[float, str, float]:
    """Return (score 0–1, label str, confidence 0–1).

    Confidence is low for short texts (<10 chunks).
    """
    if not style_scores:
        labels = _READABILITY_LABELS.get(ui_lang, _READABILITY_LABELS["en"])
        return 0.5, labels[1], 0.0

    confidence = min(1.0, len(style_scores) / 10.0)
    n = len(style_scores)
    ttr  = sum(s.ttr for s in style_scores) / n
    sent = sum(s.avg_sentence_length for s in style_scores) / n
    noun = sum(s.noun_ratio for s in style_scores) / n

    ttr_n  = min(1.0, max(0.0, (ttr  - 0.30) / 0.55))
    sent_n = min(1.0, max(0.0, (sent - 8.0)  / 27.0))
    noun_n = min(1.0, max(0.0, (noun - 0.15) / 0.30))

    score = 0.4 * sent_n + 0.35 * ttr_n + 0.25 * noun_n
    labels = _READABILITY_LABELS.get(ui_lang, _READABILITY_LABELS["en"])
    label = (
        labels[0] if score < 0.30 else
        labels[1] if score < 0.55 else
        labels[2] if score < 0.78 else
        labels[3]
    )
    return score, label, confidence


# ── SVG sparkline ─────────────────────────────────────────────────────────────

def compute_sparkline_points(
    valence_series: list[float],
    width: int = 200,
    height: int = 40,
    pad: int = 4,
) -> str:
    """Return SVG polyline points string for the valence series.

    Guards against empty list and flat line (zero range).
    """
    if not valence_series:
        mid = height // 2
        return f"0,{mid} {width},{mid}"

    v_min, v_max = min(valence_series), max(valence_series)
    r = v_max - v_min
    if r == 0:
        mid = height // 2
        return f"0,{mid} {width},{mid}"

    n = len(valence_series)
    pts = []
    for i, v in enumerate(valence_series):
        x = (i / max(n - 1, 1)) * width
        y = height - pad - ((v - v_min) / r) * (height - 2 * pad)
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


# ── First-person density ──────────────────────────────────────────────────────

_FP_BY_LANG: dict[str, re.Pattern] = {
    "en": re.compile(
        r'\b(I|me|my|myself|mine|we|our|ourselves|ours)\b', re.IGNORECASE
    ),
    "zh": re.compile(r'[我咱俺我们咱们]'),
    "ja": re.compile(r'[私僕俺わたし自分]'),
}


def first_person_density(chunks, lang: str = "en") -> float:
    """Return fraction of words that are first-person pronouns.

    Dispatches to language-appropriate pattern for CJK texts.
    """
    pat = _FP_BY_LANG.get(lang, _FP_BY_LANG["en"])
    total_words = 0
    fp_count = 0
    for chunk in chunks:
        words = chunk.text.split()
        total_words += len(words)
        fp_count += len(pat.findall(chunk.text))
    return fp_count / max(total_words, 1)


# ── Reader Verdict ─────────────────────────────────────────────────────────────
# Tuple layout per entry (9 fields):
#   [0] sentence_en   [1] sentence_zh   [2] sentence_ja
#   [3] for_you_en    [4] for_you_zh    [5] for_you_ja
#   [6] not_for_you_en [7] not_for_you_zh [8] not_for_you_ja

_VERDICT_TABLE: dict[tuple[str, str], tuple[str, ...]] = {
    # ── Icarus ────────────────────────────────────────────────────────────────
    ("Icarus", "anger"): (
        "Escalating rage powers the ascent — and accelerates the fall.",
        "愤怒层层积累推动上升，也加速了坠落。",
        "高まる怒りが上昇を加速し、やがて崩壊へと突き進む。",
        "Fans of dark social commentary and anti-hero arcs",
        "喜欢黑色社会批判和反英雄故事的读者",
        "ダークな社会批評と反英雄の物語が好きな読者",
        "Readers wanting cathartic, uplifting resolutions",
        "期望有宣泄感或鼓舞人心结局的读者",
        "カタルシスのある前向きな結末を求める読者",
    ),
    ("Icarus", "anticipation"): (
        "Breathless ambition soars — then shatters on its own hubris.",
        "屏息凝神的野心飞翔到顶，又在傲慢中碎裂。",
        "息をのむような野望が頂点に達し、傲慢さで砕け散る。",
        "Readers who love watching characters chase impossible dreams",
        "喜欢看人物追逐遥不可及梦想的读者",
        "不可能な夢を追いかけるキャラクターの物語が好きな読者",
        "Readers who need characters to succeed or learn clear lessons",
        "需要角色成功或获得明确教训的读者",
        "キャラクターの成功や明確な教訓を必要とする読者",
    ),
    ("Icarus", "disgust"): (
        "Moral rot festers at the peak of power before everything collapses.",
        "权力顶端的道德腐败，在崩塌之前早已溃烂。",
        "権力の頂点で腐敗が膿み、すべてが崩壊する前に臭いが漂う。",
        "Readers drawn to stories of corruption and moral decline",
        "喜欢腐败与道德堕落主题的读者",
        "腐敗と道徳的堕落の物語に引き込まれる読者",
        "Readers who prefer protagonists with clear moral compasses",
        "偏好主角有清晰道德准则的读者",
        "明確な道徳観を持つ主人公を好む読者",
    ),
    ("Icarus", "fear"): (
        "Relentless dread tightens its grip — the fall is both inevitable and horrifying.",
        "步步收紧的恐惧，坠落既无法避免又令人心惊。",
        "容赦ない恐怖が締め付ける——崩壊は避けられず、なおかつ恐ろしい。",
        "Readers who thrive on psychological tension and dread",
        "喜欢心理张力和恐惧感的读者",
        "心理的緊張と恐怖が好きな読者",
        "Readers sensitive to relentless darkness without relief",
        "对持续黑暗无法接受的读者",
        "容赦のない暗さに耐えられない読者",
    ),
    ("Icarus", "joy"): (
        "Joy blazes at the summit — making the inevitable fall hit twice as hard.",
        "顶峰时刻的喜悦耀眼夺目，坠落时的冲击因此加倍沉重。",
        "頂点での喜びが輝くほど、崩壊の衝撃は二倍になる。",
        "Readers who appreciate emotional contrast and earned tragedy",
        "欣赏情感对比和有价值悲剧的读者",
        "感情的なコントラストと意味ある悲劇を評価する読者",
        "Readers who need the joy to last — or a hopeful ending",
        "需要喜悦延续或希望结局的读者",
        "喜びが続くことや希望のある結末を必要とする読者",
    ),
    ("Icarus", "sadness"): (
        "A grief-soaked descent from everything that once seemed golden.",
        "曾经辉煌的一切，如今在悲怆中一点点消散。",
        "かつて輝いていたすべてが、悲しみの中で崩れ落ちていく。",
        "Readers drawn to emotional depth and literary catharsis",
        "追求情感深度和文学宣泄的读者",
        "感情的な深みと文学的カタルシスを求める読者",
        "Readers who need hope or uplift woven into the story",
        "需要故事中有希望或振奋元素的读者",
        "物語に希望や励ましが必要な読者",
    ),
    ("Icarus", "surprise"): (
        "Shocking reversals strip away the illusion of control one by one.",
        "一次次令人震惊的逆转，剥去每一层控制的幻象。",
        "衝撃的な逆転が、支配という幻想を一枚ずつ剥ぎ取っていく。",
        "Readers who love plot twists and narrative misdirection",
        "喜欢情节反转和叙事误导的读者",
        "どんでん返しや叙述的な誘導が好きな読者",
        "Readers who prefer coherent, predictable story beats",
        "偏好连贯可预测故事节奏的读者",
        "一貫性のある予測可能な展開を好む読者",
    ),
    ("Icarus", "trust"): (
        "Trust extended becomes the very blade that brings the hero down.",
        "给予的信任，最终化为刺穿英雄的那把刀。",
        "差し伸べた信頼が、やがて英雄を倒す刃となる。",
        "Readers fascinated by betrayal and the corruption of loyalty",
        "对背叛与忠诚腐败着迷的读者",
        "裏切りと忠誠の腐敗に魅せられた読者",
        "Readers who need to trust and root for the protagonist",
        "需要认同并信任主角的读者",
        "主人公を信頼し応援できることが必要な読者",
    ),
    # ── Cinderella ────────────────────────────────────────────────────────────
    ("Cinderella", "anger"): (
        "Fury as fuel — knocked down, climbing back up fighting.",
        "愤怒化为燃料，被打倒后奋力攀回。",
        "怒りを糧に——叩き落とされても、戦いながら這い上がる。",
        "Readers who love underdog resilience and emotional fire",
        "喜欢底层逆袭和情感烈度的读者",
        "下剋上のレジリエンスと情熱的な感情が好きな読者",
        "Readers looking for a calm, contemplative reading experience",
        "寻求平静沉思阅读体验的读者",
        "落ち着いた内省的な読書体験を求める読者",
    ),
    ("Cinderella", "anticipation"): (
        "Hope deferred through every setback — and finally, fully delivered.",
        "希望一次次被推迟，在每次挫折后，最终完整兑现。",
        "幾度もの挫折に阻まれた希望が、ついに完全に実を結ぶ。",
        "Readers who enjoy the slow burn of anticipation and payoff",
        "享受慢热期待与最终回报的读者",
        "じりじりとした期待と報酬のスローバーンを楽しむ読者",
        "Readers who need immediate gratification or fast pacing",
        "需要即时满足或快节奏的读者",
        "即時の満足感や速いペースを必要とする読者",
    ),
    ("Cinderella", "disgust"): (
        "Rising above a world of disgrace to reclaim deserved dignity.",
        "从耻辱的世界中崛起，夺回理所应得的尊严。",
        "不名誉な世界を乗り越え、正当な尊厳を取り戻す。",
        "Readers moved by dignity won back through perseverance",
        "被通过坚持重获尊严的故事所感动的读者",
        "忍耐によって取り戻される尊厳の物語に感動する読者",
        "Readers uncomfortable with depictions of humiliation",
        "对屈辱场景感到不适的读者",
        "屈辱の描写が苦手な読者",
    ),
    ("Cinderella", "fear"): (
        "Fear and courage locked in step on the road to a hard-won triumph.",
        "恐惧与勇气同行，在通往胜利的路上步步为营。",
        "恐怖と勇気が共に歩み、勝ち取った勝利への道を進む。",
        "Readers who enjoy characters overcoming fear through action",
        "喜欢看角色通过行动克服恐惧的读者",
        "行動を通じて恐怖を乗り越えるキャラクターが好きな読者",
        "Readers who avoid stress-heavy narratives",
        "回避高压力叙事的读者",
        "緊張感の強い物語を避ける読者",
    ),
    ("Cinderella", "joy"): (
        "Pure, earned joy — the comebacks feel as good as the final triumph.",
        "纯粹的、值得的喜悦，每一次逆袭都和最终胜利一样令人心旷神怡。",
        "純粋で勝ち取った喜び——カムバックは最後の勝利と同じくらい心地よい。",
        "Readers who love comeback stories with genuinely hopeful endings",
        "喜欢有真正希望结局的逆袭故事的读者",
        "真に希望のある結末を持つカムバックストーリーが好きな読者",
        "Readers seeking morally complex or ambiguous outcomes",
        "寻求道德复杂或模糊结局的读者",
        "道徳的に複雑または曖昧な結末を求める読者",
    ),
    ("Cinderella", "sadness"): (
        "Tears pave the path; the final rise makes every one of them worth it.",
        "泪水铺就前路，最终的崛起让每一滴都有了意义。",
        "涙が道を開く——最後の上昇が、その一粒一粒を意味あるものにする。",
        "Readers who appreciate emotional catharsis with a hopeful resolution",
        "欣赏有希望结局情感宣泄的读者",
        "希望のある解決を伴う感情的なカタルシスを評価する読者",
        "Readers allergic to long stretches of sadness before relief arrives",
        "不能忍受长时间悲伤后才得到缓解的读者",
        "救いが来るまでの長い悲しみに耐えられない読者",
    ),
    ("Cinderella", "surprise"): (
        "Fortune arrives in forms no one — including the hero — expected.",
        "机遇以任何人都意想不到的方式出现，连主角也措手不及。",
        "幸運は誰も——主人公さえも——予期しない形で訪れる。",
        "Readers who love plot surprises and unexpected character growth",
        "喜欢情节惊喜和出乎意料角色成长的读者",
        "どんでん返しと予期せぬキャラクターの成長が好きな読者",
        "Readers who prefer tightly plotted, foreshadowed narratives",
        "偏好精心策划、有预示叙事的读者",
        "しっかり構成され、伏線のある物語を好む読者",
    ),
    ("Cinderella", "trust"): (
        "Broken bonds, slowly rebuilt into something more solid than before.",
        "断裂的纽带，缓缓重建，比从前更加牢固。",
        "壊れた絆が、以前よりも強固なものへと少しずつ再建される。",
        "Readers moved by stories of forgiveness and restored relationships",
        "被宽恕和关系修复故事所感动的读者",
        "赦しと関係の修復の物語に感動する読者",
        "Readers who prefer stories without extended relationship breakdowns",
        "不喜欢长期关系破裂故事的读者",
        "長い関係崩壊のある物語が苦手な読者",
    ),
    # ── Rags to Riches ────────────────────────────────────────────────────────
    ("Rags to Riches", "anger"): (
        "Injustice met with iron will — every obstacle sharpens the drive upward.",
        "用钢铁意志回应不公，每一个障碍都磨砺着向上的动力。",
        "不正義に鉄の意志で立ち向かう——すべての障害が上昇への意欲を研ぎ澄ます。",
        "Readers energized by underdog determination and righteous drive",
        "被底层坚韧和正义驱动所激励的读者",
        "下剋上の決意と正義の駆動力に活力をもらう読者",
        "Readers who prefer calm, reflective journeys",
        "偏好平静内省旅程的读者",
        "穏やかで内省的な旅を好む読者",
    ),
    ("Rags to Riches", "anticipation"): (
        "Unshakeable forward momentum — from the first page to the last.",
        "从第一页到最后一页，不可动摇的向前动力。",
        "最初のページから最後まで、揺るぎない前進の勢い。",
        "Readers who love sustained momentum and forward-driving plots",
        "喜欢持续动力和推进情节的读者",
        "継続的な勢いと前進する展開が好きな読者",
        "Readers who prefer quieter, more introspective pacing",
        "偏好更安静、更内省节奏的读者",
        "より静かで内省的なペースを好む読者",
    ),
    ("Rags to Riches", "disgust"): (
        "Rising above a broken system through sheer, grinding determination.",
        "以纯粹的、不屈的意志，凌驾于破碎的体制之上。",
        "壊れたシステムを純粋な、ひたすらな決意で乗り越えていく。",
        "Readers drawn to stories of systemic injustice overcome by individual will",
        "被个人意志战胜系统性不公的故事所吸引的读者",
        "個人の意志がシステム的不正義を乗り越える物語に引き込まれる読者",
        "Readers who prefer systemic change over individual triumph",
        "偏好系统变革而非个人胜利的读者",
        "個人の勝利より社会的変革を好む読者",
    ),
    ("Rags to Riches", "fear"): (
        "Fear acknowledged, faced, and conquered — one step at a time.",
        "承认恐惧、面对恐惧、一步一步地克服恐惧。",
        "恐怖を認め、向き合い、一歩一歩と克服していく。",
        "Readers who find courage-in-adversity stories deeply satisfying",
        "觉得逆境中勇气故事极具满足感的读者",
        "逆境における勇気の物語に深い満足感を覚える読者",
        "Readers who find sustained tension and struggle exhausting",
        "觉得持续的紧张和挣扎令人疲惫的读者",
        "持続的な緊張と葛藤を消耗に感じる読者",
    ),
    ("Rags to Riches", "joy"): (
        "A joyful climb — growth that feels both earned and inevitable.",
        "愉快的攀升，成长感觉既来之不易又理所当然。",
        "喜びに満ちた上昇——成長は勝ち取ったものでもあり、必然でもある。",
        "Readers who enjoy watching characters grow and find their place",
        "享受看角色成长并找到立足点的读者",
        "キャラクターが成長し居場所を見つけるのを楽しむ読者",
        "Readers seeking darker, more complex emotional territory",
        "寻求更黑暗、更复杂情感领域的读者",
        "よりダークで複雑な感情領域を求める読者",
    ),
    ("Rags to Riches", "sadness"): (
        "What is lost along the way gives weight and meaning to the final rise.",
        "一路上的失去，赋予了最终崛起应有的份量与意义。",
        "途中で失われたものが、最後の上昇に重みと意味を与える。",
        "Readers who appreciate bittersweet victories and earned growth",
        "欣赏苦乐参半的胜利和来之不易成长的读者",
        "苦くも甘い勝利と勝ち取った成長を評価する読者",
        "Readers who need a pure, uncomplicated triumph",
        "需要纯粹、简单胜利的读者",
        "純粋でシンプルな勝利が必要な読者",
    ),
    ("Rags to Riches", "surprise"): (
        "Luck intervenes at unexpected moments — and the hero is ready when it does.",
        "幸运在意想不到的时刻介入，而英雄总是做好了准备。",
        "幸運は予期せぬ瞬間に訪れ、主人公はその時に備えている。",
        "Readers who enjoy serendipity woven into growth narratives",
        "享受机缘巧合融入成长叙事的读者",
        "成長の物語に縁やめぐり合いが織り込まれるのを楽しむ読者",
        "Readers who prefer earned success with no luck involved",
        "偏好完全凭实力获得成功的读者",
        "運頼みのない純粋な努力による成功を好む読者",
    ),
    ("Rags to Riches", "trust"): (
        "Quiet faith in others — and oneself — rewarded in the end.",
        "对他人和自己的默默信任，最终得到了回报。",
        "他者と自分自身への静かな信頼が、最後に報われる。",
        "Readers who love stories of perseverance and quiet belonging",
        "喜欢坚持不懈和默默归属感故事的读者",
        "忍耐と静かな帰属感の物語が好きな読者",
        "Readers looking for fast-paced action or dramatic conflict",
        "寻找快节奏动作或戏剧性冲突的读者",
        "速いペースのアクションや劇的な対立を求める読者",
    ),
    # ── Man in a Hole ─────────────────────────────────────────────────────────
    ("Man in a Hole", "anger"): (
        "Rage-fueled recovery from absolute rock bottom.",
        "怒火驱动的绝境重生。",
        "怒りに駆られた、どん底からの回復。",
        "Readers energized by raw, visceral comeback stories",
        "被原始、本能的逆袭故事所激励的读者",
        "生々しく本能的なカムバックストーリーに活力をもらう読者",
        "Readers who prefer composed, reflective protagonists",
        "偏好冷静、内省主角的读者",
        "落ち着いた内省的な主人公を好む読者",
    ),
    ("Man in a Hole", "anticipation"): (
        "Crisis hits, hope sputters — but refuses to go out completely.",
        "危机降临，希望摇曳——却始终不肯完全熄灭。",
        "危機が訪れ、希望は揺らぐ——それでも完全には消えない。",
        "Readers who enjoy tension-and-release cycles with eventual uplift",
        "享受紧张-释放循环最终上升的读者",
        "緊張と解放のサイクルと最終的な上昇を楽しむ読者",
        "Readers who need quick emotional resolution",
        "需要快速情感解决的读者",
        "素早い感情的解決を必要とする読者",
    ),
    ("Man in a Hole", "disgust"): (
        "Stripped to nothing — and finding what truly matters in that emptiness.",
        "被剥夺一切，在那片空无之中，找到了真正重要的东西。",
        "すべてを剥ぎ取られ——その空虚の中で、本当に大切なものを見つける。",
        "Readers drawn to redemption through loss and disillusionment",
        "被通过失去和幻灭实现救赎的故事所吸引的读者",
        "喪失と幻滅による贖罪の物語に引き込まれる読者",
        "Readers who find rock-bottom stories disorienting or too grim",
        "觉得绝境故事令人迷失或过于阴沉的读者",
        "どん底の物語を方向感覚を失わせるか暗すぎると感じる読者",
    ),
    ("Man in a Hole", "fear"): (
        "Survival instinct tested at the absolute limit of endurance.",
        "生存本能在忍耐的极限被彻底考验。",
        "生存本能が、耐久の極限まで試される。",
        "Readers who thrive on high-stakes suspense with a hopeful arc",
        "享受有希望弧线的高风险悬疑的读者",
        "希望のある弧を持つハイステークスサスペンスを楽しむ読者",
        "Readers who avoid prolonged suffering in fiction",
        "避免虚构作品中长时间痛苦的读者",
        "フィクションの長い苦しみを避ける読者",
    ),
    ("Man in a Hole", "joy"): (
        "Joy rediscovered after total collapse — earned, not given.",
        "在完全崩溃之后重新发现的喜悦，是挣来的，不是赠予的。",
        "完全な崩壊の後に再発見された喜び——与えられたものではなく、勝ち取ったもの。",
        "Readers who love finding light at the end of a dark tunnel",
        "喜欢在黑暗隧道尽头找到光明的读者",
        "暗いトンネルの先に光を見つけることが好きな読者",
        "Readers who need joy present throughout rather than deferred",
        "需要全程而非延迟出现喜悦的读者",
        "喜びが全体を通じて感じられる必要がある読者",
    ),
    ("Man in a Hole", "sadness"): (
        "Deep grief that slowly, stubbornly finds its way back to light.",
        "深沉的悲痛，缓慢而顽强地找到了返回光明的路。",
        "深い悲しみが、ゆっくりと、頑固に光への道を見つけていく。",
        "Readers moved by stories of recovery and hard-won second chances",
        "被康复和来之不易的第二次机会故事所感动的读者",
        "回復と勝ち取った第二のチャンスの物語に感動する読者",
        "Readers who find the descent too prolonged before the recovery",
        "觉得复苏前下降过于漫长的读者",
        "回復前の下降が長すぎると感じる読者",
    ),
    ("Man in a Hole", "surprise"): (
        "Rock bottom hides a door that only opens from the inside.",
        "绝境之中藏着一扇门，只能从内部打开。",
        "どん底には、内側からしか開かない扉が隠れている。",
        "Readers who enjoy unexpected turning points and internal revelation",
        "享受意外转折和内在启示的读者",
        "予期せぬ転換点と内的啓示を楽しむ読者",
        "Readers who need a clear, external catalyst for the recovery",
        "需要清晰外部催化剂来推动复苏的读者",
        "回復のための明確な外的触媒を必要とする読者",
    ),
    ("Man in a Hole", "trust"): (
        "Trust destroyed, tested — and rebuilt with something harder at the core.",
        "信任被摧毁，被考验，然后以更坚硬的内核重建。",
        "信頼は壊され、試され——より硬い核を持って再建される。",
        "Readers fascinated by the long, difficult work of restoring trust",
        "对恢复信任的漫长、艰难过程着迷的读者",
        "信頼回復の長くて困難なプロセスに魅せられた読者",
        "Readers who find repeated betrayal narratives emotionally exhausting",
        "觉得反复背叛叙事情感上令人精疲力竭的读者",
        "繰り返しの裏切り叙述を感情的に消耗と感じる読者",
    ),
    # ── Oedipus ───────────────────────────────────────────────────────────────
    ("Oedipus", "anger"): (
        "Fury cycles through generations, finding no resolution.",
        "愤怒在代际间循环往复，找不到任何解脱。",
        "怒りが世代を超えて繰り返し、解決の糸口が見えない。",
        "Readers drawn to cycles of systemic tragedy and inherited violence",
        "被系统性悲剧和代际暴力循环所吸引的读者",
        "システム的な悲劇と継承された暴力の循環に引き込まれる読者",
        "Readers who need a narrative resolution or moment of peace",
        "需要叙事解决或平静时刻的读者",
        "物語の解決や平和な瞬間を必要とする読者",
    ),
    ("Oedipus", "anticipation"): (
        "Every new hope arrives pre-loaded with the seed of its own undoing.",
        "每一个新的希望都预先内置了自我毁灭的种子。",
        "新しい希望はすべて、自らの崩壊の種を内包して現れる。",
        "Readers who appreciate the tragic irony of hope turning to ruin",
        "欣赏希望转化为毁灭的悲剧讽刺的读者",
        "希望が破滅へと変わる悲劇的な皮肉を評価する読者",
        "Readers who need their hopes (and the character's) to eventually pay off",
        "需要希望（包括角色的）最终得到回报的读者",
        "希望が最終的に報われることを必要とする読者",
    ),
    ("Oedipus", "disgust"): (
        "Corruption replicates itself each time the wheel turns.",
        "每当车轮转动，腐败就会自我复制。",
        "車輪が回るたびに、腐敗は自らを複製する。",
        "Readers engaged by systemic moral failure played out over time",
        "被随时间演变的系统性道德失败所吸引的读者",
        "時間をかけて展開するシステム的な道徳的失敗に引き込まれる読者",
        "Readers who need moral clarity or a just resolution",
        "需要道德清晰或公正解决的读者",
        "道徳的な明瞭さや公正な解決を必要とする読者",
    ),
    ("Oedipus", "fear"): (
        "Worst fears confirmed — again and again, with clinical precision.",
        "最坏的恐惧被一次次以精准的冷酷证实。",
        "最悪の恐怖が、冷徹な精度で何度も何度も確認される。",
        "Readers who find dread-fulfillment narratives hauntingly compelling",
        "觉得恐惧实现叙事令人萦绕于心的读者",
        "恐怖が実現される叙述を不思議なほど魅力的と感じる読者",
        "Readers who find unrelenting dread without relief unbearable",
        "无法忍受没有缓解的持续恐惧的读者",
        "救いのない絶え間ない恐怖に耐えられない読者",
    ),
    ("Oedipus", "joy"): (
        "Fleeting joy — each time more fragile, more overshadowed by approaching doom.",
        "短暂的喜悦，每次都更脆弱，更被逼近的厄运所遮蔽。",
        "束の間の喜び——そのたびに脆くなり、迫りくる破滅に影を落とされる。",
        "Readers who appreciate tragic irony and the bittersweetness of doomed joy",
        "欣赏悲剧讽刺和注定喜悦苦甜参半的读者",
        "悲劇的な皮肉と滅びゆく喜びの苦甘さを評価する読者",
        "Readers who need their joy to last",
        "需要喜悦持久的读者",
        "喜びが続くことを必要とする読者",
    ),
    ("Oedipus", "sadness"): (
        "Grief compounds — by the final page, nothing has been left untouched.",
        "悲伤不断叠加，到最后一页，什么都没有被幸免。",
        "悲しみは積み重なり——最後のページまでに、何一つ無傷では残らない。",
        "Readers who value emotional truth and unflinching literary tragedy",
        "重视情感真实和毫不回避文学悲剧的读者",
        "感情的な真実と揺るぎない文学的悲劇を大切にする読者",
        "Readers who need hope or uplift to sustain their engagement",
        "需要希望或振奋来维持参与感的读者",
        "関与を維持するために希望や励ましが必要な読者",
    ),
    ("Oedipus", "surprise"): (
        "Fate delivers whiplash twists that no preparation could have prevented.",
        "命运送来急转的逆转，任何准备都无法阻止。",
        "運命は、どんな備えも防ぎ得なかった急転の変転をもたらす。",
        "Readers who love structurally intricate, fate-driven narratives",
        "喜欢结构复杂、命运驱动叙事的读者",
        "構造的に複雑で運命に駆動される物語が好きな読者",
        "Readers who prefer predictable, character-driven arcs",
        "偏好可预测、角色驱动弧线的读者",
        "予測可能なキャラクター主導の弧を好む読者",
    ),
    ("Oedipus", "trust"): (
        "Every trust extended becomes the next wound to reopen.",
        "每一次给予的信任，都成为下一个重新裂开的伤口。",
        "差し伸べるたびに信頼は、次に開く傷となる。",
        "Readers drawn to the tragedy of misplaced faith and cyclical betrayal",
        "被错误信任和循环背叛的悲剧所吸引的读者",
        "置き違えた信頼と循環する裏切りの悲劇に引き込まれる読者",
        "Readers who find pervasive betrayal emotionally draining",
        "觉得普遍背叛情感上令人精疲力竭的读者",
        "普遍的な裏切りを感情的に消耗と感じる読者",
    ),
    # ── Riches to Rags ────────────────────────────────────────────────────────
    ("Riches to Rags", "anger"): (
        "Righteous fury as privilege crumbles — and the system that built it stands exposed.",
        "特权崩塌时的正义愤怒，建构了它的系统也随之暴露。",
        "特権が崩れる時の義憤——それを築いたシステムも露わになる。",
        "Readers drawn to stories of power, accountability, and comeuppance",
        "被权力、问责和报应故事所吸引的读者",
        "権力・説明責任・天罰の物語に引き込まれる読者",
        "Readers who prefer sympathetic protagonists",
        "偏好值得同情主角的读者",
        "共感できる主人公を好む読者",
    ),
    ("Riches to Rags", "anticipation"): (
        "Dread builds as the walls close in — brick by methodical brick.",
        "随着四壁步步收紧，恐惧一砖一砖地堆积。",
        "壁がひたひたと迫る中、恐怖が一レンガずつ積み重なっていく。",
        "Readers who appreciate slow-burn tension and impending doom",
        "欣赏慢热张力和迫在眉睫厄运的读者",
        "スローバーンの緊張と迫りくる破滅を評価する読者",
        "Readers who need narrative momentum and forward movement",
        "需要叙事动力和向前推进的读者",
        "叙述の勢いと前進を必要とする読者",
    ),
    ("Riches to Rags", "disgust"): (
        "Systemic rot laid bare through one person's irreversible decline.",
        "通过一个人不可逆转的堕落，系统性腐朽被彻底揭露。",
        "ひとりの不可逆的な没落を通じて、システム的な腐敗が白日の下にさらされる。",
        "Readers engaged by social critique embedded in personal tragedy",
        "被个人悲剧中嵌入的社会批评所吸引的读者",
        "個人的な悲劇に組み込まれた社会批評に引き込まれる読者",
        "Readers looking for agency, redemption, or systemic change",
        "寻找能动性、救赎或系统变革的读者",
        "主体性・贖罪・システム変革を求める読者",
    ),
    ("Riches to Rags", "fear"): (
        "The quiet, sustained terror of watching everything you have dissolve.",
        "亲眼目睹一切慢慢消散的那种安静而持久的恐惧。",
        "持っているすべてが溶けていくのを見守る、静かで持続的な恐怖。",
        "Readers who appreciate psychological dread over action-based tension",
        "欣赏心理恐惧而非行动张力的读者",
        "アクション的な緊張よりも心理的な恐怖を評価する読者",
        "Readers who need characters to fight back or change their fate",
        "需要角色反抗或改变命运的读者",
        "反撃したり運命を変えたりするキャラクターを必要とする読者",
    ),
    ("Riches to Rags", "joy"): (
        "Joy fades so gradually that the reader mourns its absence before the character does.",
        "喜悦消逝得如此缓慢，读者在角色之前便已开始哀悼它的离去。",
        "喜びはあまりにもゆっくりと消えていくので、読者はキャラクターより先にその不在を悼む。",
        "Readers who appreciate the quiet devastation of lost happiness",
        "欣赏失去幸福的平静毁灭的读者",
        "失われた幸福の静かな破壊を評価する読者",
        "Readers who need emotional uplift or recovery in their stories",
        "需要故事中有情感提升或恢复的读者",
        "物語の中に感情的な向上や回復が必要な読者",
    ),
    ("Riches to Rags", "sadness"): (
        "An elegiac, slow fall — beautiful in its devastation.",
        "挽歌式的、缓慢的坠落，在毁灭中透着一种凄美。",
        "挽歌のような、緩やかな没落——その壊滅の中に美しさがある。",
        "Readers who value understated emotional power and literary melancholy",
        "重视低调情感力量和文学忧郁的读者",
        "控えめな感情的力と文学的メランコリーを大切にする読者",
        "Readers who need hope, recovery, or light at the story's end",
        "需要故事结尾有希望、恢复或光明的读者",
        "物語の終わりに希望・回復・光が必要な読者",
    ),
    ("Riches to Rags", "surprise"): (
        "The collapse arrives faster, from a direction no one anticipated.",
        "崩塌来得比任何人预料的都快，来自一个意想不到的方向。",
        "崩壊は誰もが予期しない方向から、予想より速く訪れる。",
        "Readers who enjoy structural surprise and sudden loss of control",
        "享受结构惊喜和突然失控的读者",
        "構造的な驚きと突然の制御喪失を楽しむ読者",
        "Readers who prefer steady, foreshadowed narrative trajectories",
        "偏好稳定、有预示叙事轨迹的读者",
        "安定した、伏線のある物語の軌跡を好む読者",
    ),
    ("Riches to Rags", "trust"): (
        "Betrayal was choreographing the fall the entire time.",
        "从头到尾，背叛一直在幕后编排着这场坠落。",
        "裏切りは最初から、この没落を振り付けていた。",
        "Readers fascinated by the mechanics of long-game betrayal",
        "对长期背叛机制着迷的读者",
        "長期的な裏切りのメカニズムに魅せられた読者",
        "Readers who find pervasive betrayal emotionally exhausting",
        "觉得普遍背叛情感上令人精疲力竭的读者",
        "普遍的な裏切りを感情的に消耗と感じる読者",
    ),
}

_VERDICT_FALLBACK: tuple[str, ...] = (
    "An emotionally resonant story with a distinctive arc.",
    "情感共鸣的故事，有着独特的叙事弧线。",
    "感情的な共鳴を持つ、独自の弧を描く物語。",
    "Readers open to emotionally driven storytelling",
    "对情感驱动叙事持开放态度的读者",
    "感情に駆動される物語に開かれた読者",
    "Readers seeking a specific genre formula or predictable pacing",
    "寻求特定类型公式或可预测节奏的读者",
    "特定のジャンル形式や予測可能なペースを求める読者",
)

_LANG_IDX = {"en": 0, "zh": 1, "ja": 2}


def _style_modifier(style_scores: list, ui_lang: str) -> str:
    """Return a short modifier phrase derived from style metrics.

    Returns an empty string when style_scores is empty or no modifier applies.
    The phrase is prepended with a connector so it can be appended to a sentence.
    """
    if not style_scores:
        return ""
    n = len(style_scores)
    avg_sent = sum(s.avg_sentence_length for s in style_scores) / n
    avg_ttr = sum(s.ttr for s in style_scores) / n
    avg_adj = sum(s.adj_ratio for s in style_scores) / n

    parts: dict[str, list[str]] = {"en": [], "zh": [], "ja": []}
    if avg_sent > 20:
        parts["en"].append("written in immersive, unhurried prose")
        parts["zh"].append("文笔沉浸舒缓")
        parts["ja"].append("没入感のある筆致")
    if avg_ttr > 0.6:
        parts["en"].append("with unusually rich vocabulary")
        parts["zh"].append("词汇丰富多样")
        parts["ja"].append("語彙が豊か")
    if avg_adj > 0.10:
        parts["en"].append("vivid with sensory detail")
        parts["zh"].append("感官细节鲜明")
        parts["ja"].append("感覚的な描写が鮮明")

    chosen = parts.get(ui_lang, parts["en"])
    if not chosen:
        return ""
    if ui_lang == "en":
        return " — " + ", ".join(chosen)
    elif ui_lang == "zh":
        return "，" + "、".join(chosen)
    else:
        return "、" + "・".join(chosen)


def build_reader_verdict(
    arc_value: str,
    top_emotion_key: str,
    style_scores: list,
    book_type: str = "fiction",
    ui_lang: str = "en",
) -> ReaderVerdict:
    """Derive a plain-language reading verdict from existing analysis data.

    Zero LLM dependency — all judgment comes from the arc × emotion lookup
    table plus optional style modifiers.

    Args:
        arc_value:      ArcPattern.value string (e.g. "Rags to Riches").
        top_emotion_key: Dominant emotion name (e.g. "joy").
        style_scores:   List of StyleScore objects (may be empty).
        book_type:      "fiction" | "academic" | "essay" (currently unified table).
        ui_lang:        "en" | "zh" | "ja" — falls back to "en" for other values.

    Returns:
        ReaderVerdict with sentence, for_you, not_for_you, and confidence fields.
    """
    from bookscope.models import ReaderVerdict  # local import avoids circular dep

    if ui_lang not in _LANG_IDX:
        ui_lang = "en"
    idx = _LANG_IDX[ui_lang]

    entry = _VERDICT_TABLE.get((arc_value, top_emotion_key))
    table_miss = entry is None
    if table_miss:
        entry = _VERDICT_FALLBACK

    sentence = entry[idx]
    for_you = entry[3 + idx]
    not_for_you = entry[6 + idx]

    # Append style modifier to sentence
    modifier = _style_modifier(style_scores, ui_lang)
    if modifier:
        sentence = sentence.rstrip(".") + modifier

    # Confidence calculation
    if arc_value == "Unknown":
        confidence = 0.2
    elif table_miss:
        confidence = 0.1
    else:
        confidence = 0.9

    if not style_scores:
        confidence = max(0.0, confidence - 0.2)

    return ReaderVerdict(
        sentence=sentence,
        for_you=for_you,
        not_for_you=not_for_you,
        confidence=confidence,
    )
