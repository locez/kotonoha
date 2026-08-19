"""Undo the grammar a publisher wraps around a song name.

Pure text: an upload title carries decoration that no catalogue lists — bracketed
credits, "Official MV", featured performers, a channel's own name fused into the
artist — and every ingest path needs the same rules applied, whether the metadata
arrived over MPRIS, from a browser bridge, or from a player plugin. Nothing here
knows what a candidate or a match is.
"""

from __future__ import annotations

import re
from unicodedata import normalize as unicode_normalize

from .hanzi_fold import fold_to_simplified

_PARENS = re.compile(r"[\(（\[【『](.*?)[\)）\]】』]")
_DASH_SUFFIX = re.compile(r"\s+[-–—]\s+(.+)$")
_FEAT_SUFFIX = re.compile(r"(?:\b(?:feat(?:uring)?|ft)\b\.?|合作演出\s*[:：]?).*$", re.IGNORECASE)
_ARTIST_SEPARATOR = re.compile(
    r"\s*(?:,|/|&|;|、|，|\band\b|\bwith\b|\bfeat(?:uring)?\b\.?|\bft\b\.?)\s*",
    re.IGNORECASE,
)
# "和" is the Chinese "and" and a common artist-list separator in CJK metadata
# ("初音ミク和鏡音リン"). CJK has no word boundaries, so split on it only when it sits
# between two runs of >=2 non-space characters — that separates a genuinely fused
# list without fragmenting a single name that merely contains 和 (山田和樹, 大和).
# NOTE: the katakana middle dot "・" is deliberately NOT a separator here. Unlike 和
# (which joins whole names, so two different people stay distinct tokens), "・"
# separates the forename and surname WITHIN one katakana name (テイラー・スウィフト),
# so splitting it makes two different artists who merely share a given name
# (ジョン・レノン / ジョン・デンバー) collide — a confident wrong-lyrics match.
# Spaced "和" is YouTube Music's own join in a Chinese UI ("Lady Gaga 和 Bruno
# Mars"); a performer name that contains 和 (和田, 平和) does not carry spaces
# around just that character, so the spaced form is unambiguous.
_AND_SEPARATOR = re.compile(r"(?<=\S\S)和(?=\S\S)|\s+和\s+")
_TITLE_DASH = re.compile(r"\s+[-–—－]\s+")
_UPLOADER_ARTIST = re.compile(
    r"(?i)(?:channel|頻道|频道|label(?:s)?|records?|music(?:channel)?|vevo|animation|studio|工作室)"
)
_KEEP = re.compile(r"[^\w一-鿿]+")
_VERSION_TAGS = {
    # "acounstic" is not a typo here: it is how the upload spells it, and the
    # misspelling is what the title actually carries.
    "acoustic": ("acoustic", "acounstic", "unplugged", "原声版", "原聲版"),
    # 歌ってみた is the Japanese "I tried singing it" — a user cover, so the words
    # are the same but the performance and its timings are not.
    "cover": ("cover", "翻唱", "歌ってみた"),
    # An alternate vocalist for the same song (Vocaloid uploads name the singer).
    # A re-sung 女声版/男声版 keeps the words and changes every timing, which is what
    # let 不谓侠(女声版) stand in for 不谓侠 when no artist was reported.
    "alt_vocal": ("バーチャル・シンガーver", "バーチャルシンガーver", "女声版", "女聲版", "男声版", "男聲版"),
    "demo": ("demo",),
    "edit": ("edit",),
    "extended": ("extended",),
    # 钢琴版 and 纯音乐 carry no words at all, so accepting one hands the overlay a
    # lyric sheet for a recording that never sings it.
    "instrumental": (
        "instrumental", "instrumental version", "off vocal", "off-vocal", "伴奏",
        "钢琴版", "鋼琴版", "纯音乐版", "純音樂版", "纯音乐", "純音樂",
    ),
    "karaoke": ("karaoke", "卡拉ok"),
    "live": ("live", "live版", "现场", "現場"),
    "remaster": ("remaster", "remastered"),
    "remix": ("remix", "dj版"),
    "guitar": ("吉他版",),
    "strum": ("弹唱版", "彈唱版"),
    "opera": ("戏腔版", "戲腔版"),
    "cantonese": ("粤语版", "粵語版"),
    # The slowed/sped/reverb family is what a re-upload channel actually publishes,
    # and the timing differs from the studio take, so the lyrics do not line up.
    "sped_up": ("sped up", "sped-up", "spedup", "加速版"),
    "slowed": ("slowed", "slowed down", "slowed + reverb", "slowed and reverb", "慢速版", "降速版"),
    "reverb": ("reverb", "reverbed"),
    "nightcore": ("nightcore",),
    "rhythm": ("律动版", "律動版"),
    "rnb": ("r&b版", "r&b心碎版"),
    "smoky": ("烟嗓版", "煙嗓版"),
    "full": ("full version",),
    "opening": ("opening title version",),
    "choreography": ("choreography ver", "choreography version"),
}
# Tags that change the recording but NOT the lyrics: a remaster has the same
# words as the studio take, so it must not force a version conflict that rejects
# the only correct candidate. (live/acoustic/instrumental/remix/etc. can differ.)
# A remaster and a choreography video are the same performance: the words and
# their timings are the studio take's, so neither may reject the only
# candidate that has lyrics at all.
_LYRIC_NEUTRAL_TAGS = frozenset({"remaster", "choreography"})

_TITLE_BARS = re.compile(r"[|｜丨]")
# A closing ’ is never followed by a letter; a contraction's apostrophe always is.
# Without that guard the title ILLIT (아일릿) ‘It’s Me’ Official MV closed on the
# apostrophe in It's and searched for "It s Me’", which matched nothing.
_TITLE_QUOTE = re.compile(r"""[\"“](.+?)[\"”]|‘(.+?)’(?![A-Za-z])|(?<![\w])'(.+)'""")
_TITLE_NOISE_LATIN = re.compile(
    r"(?i)(?<![A-Za-z])(?:official hd mv|official hd|official music video|official lyric video|"
    r"official visualizer|official audio|official video|official mv|video oficial|music video|"
    r"audio|mv)(?![A-Za-z])"
)
_TITLE_NOISE_CJK = re.compile(
    r"動態歌詞Lyrics|动态歌词Lyrics|歌詞字幕|歌词字幕|完整高清音質|完整高清音质|官方高畫質|官方高画质|"
    r"高清MV|高清mv|高清|官方MV|官方mv|Chinese Subs|中文字幕",
    re.IGNORECASE,
)
_TITLE_TAIL_NOISE = re.compile(
    r"(?i)\b(?:music video|one hour|played by|kpop demon hunters|sony animation|league of legends)\b|"
    r"串燒|無間斷|完整聆聽|KTV必唱|在频道内|在頻道內|放鬆音樂"
)

# Compiled marker matchers are reused for every candidate; CJK markers use literal
# matching while Latin markers use ASCII-letter boundaries to avoid substring hits.


def _version_pattern(marker: str) -> re.Pattern[str]:
    escaped = re.escape(marker)
    if any(char.isascii() and char.isalpha() for char in marker):
        return re.compile(r"(?<![A-Za-z])" + escaped + r"(?![A-Za-z])", re.IGNORECASE)
    return re.compile(escaped)

_VERSION_TAG_PATTERNS = {
    tag: tuple(_version_pattern(marker) for marker in markers)
    for tag, markers in _VERSION_TAGS.items()
}
_VERSION_SUFFIX_PATTERNS = tuple(
    _version_pattern(marker) for markers in _VERSION_TAGS.values() for marker in markers
)

NORMALIZER_VERSION = 2


def _fold_latin_accents(text: str) -> str:
    """Strip accents from Latin letters only (é->e, ö->o, ñ->n) so an accented
    title matches its unaccented spelling (Déjà Vu vs Deja Vu, Motörhead vs
    Motorhead). A Japanese dakuten (が = か + U+3099) or any non-Latin base is
    left untouched: only a character whose NFD base is an ASCII letter is folded,
    so kana/hangul/cyrillic/CJK are never mangled."""
    folded: list[str] = []
    for char in text:
        decomposed = unicode_normalize("NFD", char)
        base = decomposed[0]
        folded.append(base if len(decomposed) > 1 and base.isascii() and base.isalpha() else char)
    return "".join(folded)


# The bracket characters alone, for the case where removing bracketed spans
# would leave the title empty.
_BRACKET_EDGES = re.compile(r"[【】\[\]（）()『』「」《》〈〉]+")


def _is_bracket_only(title: str) -> bool:
    """True when removing bracketed spans would leave the title with no content."""
    return bool(title.strip()) and not _KEEP.sub("", _PARENS.sub("", title)).strip()


def normalize(text: str) -> str:
    """Return a comparison form without changing version semantics elsewhere.

    Traditional Chinese is folded to Simplified so a traditional-tagged track
    (李榮浩 / 麻雀 from a zh-Hant browser) compares equal to Netease's simplified
    catalogue (李荣浩), and Latin accents are folded so accented Western titles
    match their plain spelling. Both folds are applied to the track and the
    candidate alike, so they are symmetric and only ever affect this comparison
    key (never display, search queries, or version semantics).

    Deliberately free of the title-only platform cleaning: this is also the
    comparison key for artist and album, and an upload-grammar rule applied to a
    performer's name rewrites an identity rather than tidying a title. Titles
    reach here already cleaned, by split_title()."""
    value = _fold_latin_accents(unicode_normalize("NFKC", text).casefold())
    value = fold_to_simplified(value)
    stripped = _PARENS.sub("", value)
    # A title wholly inside brackets ("【七月上】", "(intro)") strips to nothing and
    # could then never match anything. Keep the bracketed text as the title in
    # that case: there it is the name, not a qualifier attached to one.
    if not _KEEP.sub("", stripped).strip():
        stripped = _BRACKET_EDGES.sub(" ", value)
    value = _FEAT_SUFFIX.sub("", stripped)
    return _KEEP.sub("", value).strip()


def split_title(title: str, artist: str = "") -> tuple[str, frozenset[str]]:
    """Split a display title into its base title and known version qualifiers."""
    value = _clean_platform_title(title, artist)
    tags: set[str] = set()
    for group in _PARENS.findall(value):
        tags.update(_extract_version_tags(group))
    def remove_parenthetical(match: re.Match[str]) -> str:
        # Parentheses can be part of a token, as in the artist name (G)I-DLE.
        if match.end() < len(value) and value[match.end()].isalnum() and len(match.group(1)) <= 3:
            return match.group(0)
        return ""

    base = _PARENS.sub(remove_parenthetical, value).strip()
    # A title wholly inside brackets is the name, not a qualifier: "【七月上】"
    # would otherwise leave nothing to match on.
    if not base:
        base = _BRACKET_EDGES.sub(" ", value).strip()
    suffix = _DASH_SUFFIX.search(base)
    if suffix is not None:
        suffix_tags = _extract_version_tags(suffix.group(1))
        if suffix_tags:
            tags.update(suffix_tags)
            base = base[: suffix.start()].strip()
    # Only a marker the name ends on qualifies it. Scanning the whole base title
    # tagged the name itself: "Live and Learn" came out tagged `live`, agreed with
    # "Live and Learn (Live)", and the live recording outranked the studio one the
    # user was playing. A trailing "Song Live版" is still a qualifier and still
    # conflicts with a plain candidate, which is what this loop already located.
    for pattern in _VERSION_SUFFIX_PATTERNS:
        suffix_match = pattern.search(base)
        if suffix_match is not None and not base[suffix_match.end() :].strip():
            prefix = base[: suffix_match.start()].rstrip()
            if prefix:
                tags.update(_extract_version_tags(base[suffix_match.start() :]))
                base = prefix
                break
    return base, frozenset(tags)


def _extract_version_tags(value: str) -> set[str]:
    return {
        tag
        for tag, patterns in _VERSION_TAG_PATTERNS.items()
        if any(pattern.search(value) for pattern in patterns)
    }


def base_title(title: str) -> str:
    return split_title(title)[0]


def _artist_parts(artist: str) -> tuple[str, ...]:
    value = unicode_normalize("NFKC", artist).strip()
    parts: list[str] = []
    for chunk in _ARTIST_SEPARATOR.split(value):
        parts.extend(_AND_SEPARATOR.split(chunk))
    return tuple(part.strip() for part in parts if part.strip())


def artist_tokens(artist: str) -> frozenset[str]:
    return frozenset(token for token in (normalize(part) for part in _artist_parts(artist)) if token)


def primary_artist(artist: str) -> str:
    parts = _artist_parts(artist)
    return parts[0].strip() if parts else artist.strip()


def _is_title_pair(left: str, right: str) -> bool:
    left_has_cjk = bool(_CJK_ONE.search(left))
    right_has_latin = bool(re.search(r"[A-Za-z]", right))
    return left_has_cjk and right_has_latin


def _artist_from_prefix(prefix: str) -> str:
    prefix = prefix.strip(" \t\r\n-–—－")
    prefix = re.sub(r"(?i)\b(?:feat(?:uring)?|ft)\b.*$", "", prefix).strip()
    if "（" in prefix:
        if re.search(r"[一-鿿ぁ-ヿ]", prefix.split("（", 1)[1]):
            return prefix
        return prefix.split("（", 1)[0].strip()
    if "(" in prefix:
        # A single-letter parenthetical glued to the next word is part of the name,
        # not a qualifier after it: (G)I-DLE. The title cleaner already protects
        # that shape, so truncating at the bracket destroyed the same identity it
        # preserves — and it is where the performer's name starts.
        protected = re.search(r"\([A-Za-z]\)(?=[A-Za-z])", prefix)
        if protected is None:
            return prefix.split("(", 1)[0].strip()
        return prefix[protected.start() :].strip()
    # A bilingual display name usually puts the Latin alias after the real CJK name.
    cjk = re.findall(rf"[{_CJK_CLASS}]+", prefix)
    if cjk:
        return cjk[-1]
    return prefix


_LEADING_BRACKET = re.compile(r"^\s*[【『「\[]([^】』」\]]*)[】』」\]]\s*")


def recover_artist(title: str, artist: str) -> str:
    """Recover a leading title credit only when generic upload grammar supports it."""
    fallback = artist.strip()
    value = title.strip()
    if " / " in fallback:
        return fallback
    dash_parts = _TITLE_DASH.split(value, maxsplit=1)
    if len(dash_parts) == 2:
        # Strip the upload tail before deciding: "Official MV" trailing the Latin
        # half says nothing about whether the two halves are the same title, and
        # letting it veto the guard split 螺旋 - RASEN into artist and song.
        right = _TITLE_NOISE_CJK.sub(" ", _TITLE_NOISE_LATIN.sub(" ", dash_parts[1])).strip()
        # A pair is the same title twice, so the Latin half carries no CJK of its
        # own; "童話鎮 … Chen Yifa - Fairy Town" is a credit plus a translation, not
        # a pair, and treating it as one would keep the uploader as the performer.
        if right and not _CJK_ONE.search(right) and _is_title_pair(dash_parts[0], right):
            return fallback
    # Recover only a leading title credit when generic upload grammar distinguishes it from the song title.
    if not (_UPLOADER_ARTIST.search(fallback) or _TITLE_NOISE_LATIN.search(value)):
        return fallback
    prefix = dash_parts[0] if len(dash_parts) == 2 else value
    if prefix == value and not _TITLE_QUOTE.search(value) and not any(
        marker in value for marker in ("《", "『", "【", "「")
    ):
        # Nothing in the title separates a credit from the song name, so the whole
        # title is the song. Returning it as the artist replaced a real performer
        # with the title itself for every upload whose artist field happens to say
        # "records", "studio" or "channel".
        return fallback
    quoted = _TITLE_QUOTE.search(prefix)
    if quoted:
        prefix = prefix[: quoted.start()]
    # What sits before the bracket has to read like a name. A bar-separated
    # commentary lead-in ("单曲循环丨张远深情嗓好适合《达尔文》！") is a sentence about
    # the song, and taking it as the performer overwrote the reported artist for a
    # row the corpus marks as carrying no leading credit at all.
    if _TITLE_BARS.search(prefix):
        return fallback
    # A leading upload bracket goes before the markers are used as cut points:
    # "【HD】陳一發兒" would otherwise truncate at 【 and lose the performer. Only at
    # the head, so a parenthetical that is part of a name (Jam（阿敬）) survives.
    prefix = _LEADING_BRACKET.sub("", prefix, count=1).strip()
    for marker in ("《", "『", "【", "「"):
        prefix = prefix.split(marker, 1)[0]
    candidate = _artist_from_prefix(prefix)
    return candidate or fallback


def _artist_variants(artist: str) -> tuple[str, ...]:
    """The performer's name split out of a fused bilingual channel name.

    A YouTube channel commonly carries both names at once ("周杰倫 Jay Chou"), and no
    catalogue lists that fused form, so the artist comparison rejected every candidate
    for 告白氣球 until the CJK half was tried on its own.
    """
    halves = (
        " ".join(_CJK_TOKEN.findall(artist)).strip(),
        " ".join(_LATIN_TOKEN.findall(artist)).strip(),
    )
    return tuple(half for half in dict.fromkeys(halves) if half and half != artist.strip())


_BRACKETED = re.compile(r"[【『\[（(]([^】』\]）)]*)[】』\]）)]")
# Corner/angle quotes and separators usually WRAP the title (「Lemon」《告白气球》)
# rather than junk, so they are flattened to spaces (delimiters), not removed.
_DELIMITERS = re.compile(r"[「」『』《》〈〉|/_~•・\-–—]+")
# Pure upload noise that is never part of a song name — stripped case-insensitively.
# Version words (cover/live/remix/acoustic/…) are deliberately NOT here: they change
# the recording and are handled by the version-tag logic, not thrown away.
# Latin terms use \b so they don't eat substrings of real words; the CJK terms get
# no \b — adjacent Han characters are all \w, so a word boundary never sits between
# them and "官方MV" / "完整版" would otherwise never strip out of a fused title.
_UPLOAD_NOISE_LATIN = re.compile(
    r"\b(?:officical|official|mv|m/v|hd|hq|uhd|sd|4k|8k|60fps|1080p|720p|480p|"
    r"lyrics?|lyric video|audio|music video|official (?:music )?video|official audio|"
    r"visualizer|vevo|topic|full version|hi-?res|high quality)\b",
    re.IGNORECASE,
)
_UPLOAD_NOISE_CJK = re.compile(
    r"高畫質|高画质|超高清|高清|超清|標清|完整版|完整|无损|無損|音質|音质|画质|畫質|字幕|歌词|歌詞|官方|"
    r"试听|試聽|现场|現場|直播|電視劇|电视剧|插曲|主題曲|主题曲|片頭曲|片头曲|片尾曲|主題歌|主题歌"
)
_CJK_CLASS = "㐀-鿿豈-﫿぀-ヿ가-힯"
_CJK_TOKEN = re.compile(rf"[{_CJK_CLASS}]+")
_CJK_ONE = re.compile(rf"[{_CJK_CLASS}]")
_NONWORD = re.compile(rf"[^\w{_CJK_CLASS}]+")
_LATIN_TOKEN = re.compile(r"[0-9A-Za-z][0-9A-Za-z'’&.]*")


# A bracketed guest credit is not part of the song name: "(特別演出: 派偉俊)【告白氣球
# Love Confession】" reached the catalogues carrying the guest's name and matched
# nothing, where 告白氣球 alone matches. The colon is required, so a bracketed version
# marker such as (演唱會版) — which does change which recording is meant — is never
# mistaken for a credit.
_BRACKETED_CREDIT = re.compile(r"^\s*(?:特別演出|特别演出|合唱|對唱|对唱|客串|和聲|和声)\s*[:：]")


def _debracket(text: str) -> str:
    """Replace 【…】 / […] / (…) segments: drop the ones whose content is only
    upload noise (【HD】, [歌詞字幕], (Official MV)), but KEEP the content of the
    rest — some channels put the actual song title in brackets (【演員】, [ 唯一 The
    One And Only ]), and blindly stripping every bracket loses the title."""
    def keep_or_drop(match: re.Match[str]) -> str:
        inner = match.group(1)
        if match.end() < len(text) and text[match.end()].isalnum() and len(inner) <= 3:
            return match.group(0)
        if _BRACKETED_CREDIT.search(inner):
            return " "
        residue = _UPLOAD_NOISE_CJK.sub("", _UPLOAD_NOISE_LATIN.sub("", inner))
        residue = _NONWORD.sub("", residue)
        substantial = len(_CJK_ONE.findall(residue)) >= 2 or len(residue) >= 4
        return f" {inner} " if substantial else " "

    return _BRACKETED.sub(keep_or_drop, text)
_WHITESPACE = re.compile(r"\s+")


def _quote_at_top_level(text: str) -> tuple[str, int] | None:
    for match in _TITLE_QUOTE.finditer(text):
        depth = 0
        for char in text[: match.start()]:
            if char in "([{【（":
                depth += 1
            elif char in ")]}】）" and depth:
                depth -= 1
        if depth == 0:
            content = next((group for group in match.groups() if group is not None), "").strip()
            if content:
                return content, match.end()
    return None


# A Latin run at the head of a title, ending at a separator or a CJK character:
# the romanised form of a CJK performer name that precedes it.
_LEADING_ROMANISATION = re.compile(
    r"[A-Za-z][A-Za-z.'\-]*(?:\s+[A-Za-z][A-Za-z.'\-]*){0,3}\s*"
    r"(?=[-–—－:：《〈「『【\[]|[一-鿿ぁ-ヿ])"
)


def _strip_leading_artist(value: str, artist: str) -> str:
    candidate = artist.strip()
    if not candidate or not value.casefold().startswith(candidate.casefold()):
        return value
    remainder = value[len(candidate) :]
    # A CJK credit is commonly followed straight by its romanisation with no
    # separator at all ("廖俊濤Liao juntao - 誰"), so a Latin letter is allowed there.
    immediate_latin = bool(remainder) and remainder[0].isascii() and remainder[0].isalpha()
    if remainder and not remainder[0].isspace() and remainder[0] not in "-–—－:：《〈「『【[":
        if not (immediate_latin and _CJK_ONE.search(candidate)):
            return value
    remainder = remainder.lstrip(" \t\r\n-–—－:：")
    # An upload that leads with a CJK performer usually repeats it romanised
    # ("廖俊濤Liao juntao - 誰", "美秀集團 Amazing Show－捲菸"). That Latin run is the
    # same credit, so it goes with the name rather than staying in the title.
    if _CJK_ONE.search(candidate):
        romanisation = _LEADING_ROMANISATION.match(remainder)
        if romanisation is not None:
            remainder = remainder[romanisation.end() :].lstrip(" \t\r\n-–—－:：")
    return remainder


def _segment_key(value: str) -> str:
    folded = _fold_latin_accents(unicode_normalize("NFKC", value).casefold())
    folded = fold_to_simplified(folded)
    return _KEEP.sub("", folded)


def _segment_score(segment: str, index: int, artist_key: str = "") -> tuple[int, int]:
    cleaned = _TITLE_NOISE_CJK.sub(" ", _TITLE_NOISE_LATIN.sub(" ", segment))
    score = len(_WHITESPACE.sub("", cleaned))
    score += 2 * len(_CJK_ONE.findall(cleaned))
    if len(_LATIN_TOKEN.findall(cleaned)) > 2 and _CJK_ONE.search(cleaned):
        score -= 5 * (len(_LATIN_TOKEN.findall(cleaned)) - 2)
    if _TITLE_QUOTE.search(segment):
        score += 1000
    if _TITLE_TAIL_NOISE.search(segment):
        score -= 100
    segment_key = _segment_key(segment)
    if artist_key and segment_key and segment_key in artist_key:
        # A bar-delimited segment contained in the reported artist is metadata,
        # not the title to send to lyric matching.
        score -= 10_000
    if index == 0:
        score += 4
    return score, -index


# A bracket holding nothing but a delivery-format tag is upload grammar.
_FORMAT_TAG = re.compile(r"(?i)(?:hd|hq|sd|uhd|4k|8k|2k|1080p?|720p?|mv|cc|hi-?res)")


def _clean_platform_title(title: str, artist: str = "") -> str:
    original = title.strip()
    value = unicode_normalize("NFKC", title).replace("\u3000", " ")
    segments = _TITLE_BARS.split(value)
    artist_key = _segment_key(artist)
    value = max(
        enumerate(segments),
        key=lambda item: _segment_score(item[1], item[0], artist_key),
    )[1].strip()

    quoted = _quote_at_top_level(value)
    if quoted is not None:
        content, end = quoted
        value = f"{content} {value[end:]}"
    value = _strip_leading_artist(value, artist)
    protected = re.sub(r"\([A-Za-z]\)(?=[A-Za-z])", lambda match: f"__PAREN_{match.group(0)[1]}__", value)
    value = protected
    def remove_upload_bracket(match: re.Match[str]) -> str:
        inner = match.group(1)
        # A bracket holding only a format tag (【HD】, [4K], 【1080P】) is upload
        # grammar; keeping it hid the performer credit that follows it.
        if _FORMAT_TAG.fullmatch(inner.strip()):
            return " "
        residue = _TITLE_NOISE_CJK.sub("", _TITLE_NOISE_LATIN.sub("", inner))
        residue = _NONWORD.sub("", residue)
        return " " if not residue else match.group(0)

    value = _BRACKETED.sub(remove_upload_bracket, value)
    # Again, now that a leading 【HD】-style bracket no longer hides the credit.
    value = _strip_leading_artist(value.strip(), artist)
    value = re.sub(r"__PAREN_([A-Za-z])__", r"(\1)", value)
    value = re.sub(r"[《》〈〉「」]", " ", value)
    value = _TITLE_NOISE_LATIN.sub(" ", value)
    value = _TITLE_NOISE_CJK.sub(" ", value)
    value = _WHITESPACE.sub(" ", value).strip(" \t\r\n-–—－")
    return value or original


# A lyric-video channel announces itself inside corner brackets (『動態歌詞』,
# 『歌词版』). Publisher grammar, so every ingest path needs it stripped, not only
# the MPRIS one it used to live in.
_LYRIC_VIDEO_BRACKET = re.compile(r"『[^』]*(?:動態歌詞|歌詞|歌词)[^』]*』", re.IGNORECASE)
# YouTube names an auto-generated artist channel "<Artist> - Topic" and reports it
# verbatim as the performer, a form no catalogue lists: 富士山下 found nothing under
# "Eason Chan - Topic" and 41 lines without the suffix.
_TOPIC_CHANNEL_SUFFIX = re.compile(r"\s*-\s*Topic\s*$", re.IGNORECASE)


def clean_title(title: str, artist: str = "") -> str:
    """Remove observed platform grammar while retaining recording markers."""
    cleaned = _LYRIC_VIDEO_BRACKET.sub("", _clean_platform_title(title, artist))
    return cleaned.strip() or title.strip()


def performing_artist(artist: str) -> str:
    """The performer without the channel naming a platform wrapped around it."""
    return _TOPIC_CHANNEL_SUFFIX.sub("", artist).strip()


# A featured performer is credited inside the title and is not part of the song
# name: "feat. BLUMENGARTEN & SHIRIN DAVID - GUT GENUG" and "大展鸿图 ft.AR刘夫阳"
# both matched nothing while the names alone match. The credit runs to the next
# separator. Only feat/ft/featuring qualify — "with" opens too many real titles
# ("Dancing With Myself") to treat as a credit marker.
_FEAT_CREDIT = re.compile(r"\s*\b(?:feat|ft|featuring)\b\.?\s*[^-–—()\[\]【】]*", re.IGNORECASE)


def noisy_title_queries(title: str) -> tuple[str, ...]:
    """Extra search queries salvaged from a noisy browser/YouTube title, used only
    in fuzzy mode. Strips bracketed junk (【HD】, [歌詞字幕], …) then pulls the
    CJK-only and Latin-only runs as separate queries, so a dual-language,
    channel-tagged title like "【HD】陳一發兒- 童話鎮 [歌詞字幕] Chen Yifa - Fairy Town
    BELLA PING MUSIC CHANNEL" still yields "陳一發兒 童話鎮" and "Chen Yifa Fairy
    Town" to search on. A trailing ALL-CAPS channel/uploader tail is dropped."""
    stripped = _debracket(title)
    # CJK noise first: removing 官方 from "官方MV" isolates the "MV" so the Latin pass
    # can then strip it (running Latin first would leave "MV" fused to 官方).
    stripped = _UPLOAD_NOISE_CJK.sub(" ", stripped)
    stripped = _UPLOAD_NOISE_LATIN.sub(" ", stripped)
    # The credit is bounded by the separator that follows it, so it has to go before
    # the separators are flattened: "feat. X & Y - GUT GENUG" loses its dash here and
    # the credit would then run to the end of the line.
    credited = stripped
    stripped = _DELIMITERS.sub(" ", stripped)
    queries: list[str] = []
    # Combined query first (both scripts, cleaned) — the best shot when the title
    # simply fused artist and song across a separator ("米津玄師 Lemon", "周杰倫 晴天").
    combined = _WHITESPACE.sub(" ", stripped).strip()
    if len(combined) >= 2:
        queries.append(combined)
    # Added rather than substituted: the credited form is what some catalogues index
    # ("Old Town Road ft. Billy Ray Cyrus" resolves as it stands), so it stays first.
    uncredited = _WHITESPACE.sub(" ", _DELIMITERS.sub(" ", _FEAT_CREDIT.sub(" ", credited))).strip()
    if len(uncredited) >= 2 and uncredited != combined:
        queries.append(uncredited)
    cjk = _WHITESPACE.sub(" ", " ".join(_CJK_TOKEN.findall(stripped))).strip()
    if len(cjk) >= 2:
        queries.append(cjk)
    has_cjk = bool(cjk)
    latin_tokens = _LATIN_TOKEN.findall(stripped)
    # Drop a trailing ALL-CAPS uploader/channel tail (BELLA PING MUSIC CHANNEL). When
    # the title is pure Latin, keep an all-caps run whole if EVERYTHING is caps — that
    # is a genuinely all-caps title (TALK THAT TALK), not a tail. When the title also
    # has CJK, the Latin run is secondary, so strip the tail freely.
    while (
        len(latin_tokens) > 2
        and latin_tokens[-1].isupper()
        and len(latin_tokens[-1]) >= 2
        and (has_cjk or not all(token.isupper() for token in latin_tokens[:-1]))
    ):
        latin_tokens.pop()
    latin = " ".join(latin_tokens).strip()
    if len(latin) >= 2:
        queries.append(latin)
    return tuple(dict.fromkeys(queries))
