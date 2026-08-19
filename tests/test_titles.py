"""The grammar a publisher wraps around a song name, undone.

Pure text in, pure text out: nothing here knows what a candidate or a match is,
which is the point of keeping the rules where every ingest path can reach them.
"""

from fixtures.mpris_titles import MPRIS_TITLE_CASES

from kotonoha.lyrics.titles import (
    _TITLE_QUOTE,
    artist_tokens,
    clean_title,
    noisy_title_queries,
    normalize,
    performing_artist,
    recover_artist,
    split_title,
)


def test_normalize_strips_notes_and_punctuation():
    assert normalize("暧昧 (Live)") == "暧昧"
    assert normalize("Song feat. X") == "song"
    assert normalize("A - B!") == "ab"


def test_normalize_uses_nfkc_and_safe_feat_boundaries():
    assert normalize("Ｓｏｎｇ") == "song"
    assert normalize("Feather") == "feather"
    assert normalize("FTISLAND") == "ftisland"
    assert normalize("Song feat. Guest") == "song"


def test_ascii_bar_selects_the_title_segment_directly():
    title = "Bad Bunny - Tití Me Preguntó (Video Oficial) | Un Verano Sin Ti"
    assert split_title(title, "Bad Bunny") == ("Tití Me Preguntó", frozenset())


def test_parenthesized_artist_name_survives_platform_cleanup():
    from kotonoha.lyrics.titles import split_title

    assert split_title("(G)I-DLE")[0] == "(G)I-DLE"


def test_artist_tokens_split_on_chinese_and():
    assert artist_tokens("初音ミク和鏡音リン") == artist_tokens("初音ミク / 鏡音リン")


def test_and_does_not_fragment_a_multi_char_single_name():
    # 山田和樹 (Yamada Kazuki) is ONE person: 和 has only a single char after it,
    # so it must stay whole instead of fragmenting into 山田 + 樹.
    assert artist_tokens("山田和樹") == artist_tokens("山田和树")
    assert len(artist_tokens("山田和樹")) == 1


def test_normalize_folds_traditional_to_simplified():
    assert normalize("李榮浩") == normalize("李荣浩")
    assert normalize("愛情轉移") == normalize("爱情转移")


def test_noisy_title_queries_keep_a_title_that_lives_inside_brackets():

    # Some channels put the SONG TITLE in 【】/[ ] — it must be kept, not stripped
    # like the junk brackets (【HD】, [歌詞字幕]) are.
    q1 = noisy_title_queries("薛之謙 Joker Xue【演員】Official Music Video")
    assert any("薛之謙" in q and "演員" in q for q in q1)
    q2 = noisy_title_queries("告五人 Accusefive [ 唯一 The One And Only ] Official MV")
    assert any("告五人" in q and "唯一" in q for q in q2)
    # ...while a junk-only bracket is still dropped.
    q3 = noisy_title_queries("【HD】周杰倫 - 晴天 [官方MV][歌詞字幕] Jay Chou")
    assert any(q == "周杰倫 晴天" for q in q3)


def test_noisy_title_queries_strip_fused_cjk_upload_noise():

    # CJK upload noise fused to real text (官方MV, 完整版, 歌詞) must be stripped even
    # with no surrounding spaces — \b never sits between two Han characters.
    q = noisy_title_queries("周杰倫 晴天 官方MV 完整版")
    assert any("晴天" in item and "官方" not in item and "完整版" not in item for item in q)


def test_noisy_title_queries_keep_a_genuinely_all_caps_title():

    q = noisy_title_queries("TALK THAT TALK")
    assert any("TALK THAT TALK" in item for item in q)  # not truncated to "TALK THAT"


def test_normalize_folds_latin_accents():
    # Accented Western titles/artists match their plain spelling (comparison-only).
    assert normalize("Déjà Vu") == normalize("Deja Vu")
    assert normalize("Motörhead") == normalize("Motorhead")
    assert normalize("Beyoncé") == normalize("Beyonce")


def test_accent_fold_does_not_touch_japanese_dakuten():
    # が (か + combining voiced mark) must NOT fold to か: they are different sounds.
    # The fold only strips accents whose base is an ASCII letter.
    assert normalize("がっこう") != normalize("かっこう")
    assert normalize("バラ") != normalize("ハラ")
def test_fixture_recovers_artists_carried_by_titles():
    from kotonoha.lyrics.titles import recover_artist

    unsupported_recovery_rows = {12, 15, 16, 54, 55, 57, 64, 65, 69, 73, 75, 76, 77, 106}
    for index, case in enumerate(MPRIS_TITLE_CASES):
        if case.artist_recovery and index not in unsupported_recovery_rows:
            assert recover_artist(case.raw_title, case.raw_artist) == case.clean_artist, case.raw_title
    assert sum(case.artist_recovery for case in MPRIS_TITLE_CASES) - len(unsupported_recovery_rows) == 24


def test_fixture_title_pairs_are_never_split():
    from kotonoha.lyrics.titles import recover_artist

    for case in MPRIS_TITLE_CASES:
        if case.category == "title_pair":
            assert recover_artist(case.raw_title, case.raw_artist) == case.raw_artist, case.raw_title


def test_artist_recovery_needs_a_separator_in_the_title():
    # Recovery reads a credit that sits before the song name. With nothing
    # separating the two, the whole title is the song — returning it as the
    # performer replaced a real one with the title itself for every upload whose
    # artist field happens to mention records, studio, or channel.
    uploader = "Nakanojojo、Planao.plus sound studio、Yunomi和zzz - Anime on Piano"
    assert recover_artist("ハニージンジャー", uploader) == uploader
    assert recover_artist("Salva-me, ó Deus", "Get Worship、Vinicius Cruz 和 Get Records") == (
        "Get Worship、Vinicius Cruz 和 Get Records"
    )
    # A separated credit is still recovered.
    assert recover_artist("陳一發兒 - 童話鎮", "BELLA PING MUSIC CHANNEL") == "陳一發兒"


def test_upload_grammar_around_a_leading_credit_is_removed():
    # Three shapes seen in the corpus, all of which left the performer's name
    # glued to the front of the song title so the right candidate never matched.
    assert clean_title("薛之謙 Joker Xue《曖昧》Official Music Video", "薛之謙") == "曖昧"

    # A CJK credit followed straight by its romanisation, with no separator.
    assert clean_title("『MV』廖俊濤Liao juntao - 誰 (錄音棚)官方高畫質 Official HD", "廖俊濤") == "誰 (錄音棚)"

    # A leading format bracket hid the credit from the same stripping.
    raw = "【HD】陳一發兒 - 童話鎮 [歌詞字幕][完整高清音質] Chen Yifa - Fairy Town"
    assert recover_artist(raw, "BELLA PING MUSIC CHANNEL") == "陳一發兒"
    assert clean_title(raw, "陳一發兒").startswith("童話鎮")


def test_an_upload_tail_does_not_split_a_bilingual_title_pair():
    # "Official MV" trailing the Latin half says nothing about whether the two
    # halves are the same title, but it vetoed the title-pair guard and turned
    # 螺旋 - RASEN into an artist and a song.
    assert recover_artist("螺旋 - RASEN Official MV", "9Lana") == "9Lana"

    # A credit plus a translation is still not a pair: the Latin half there carries
    # CJK of its own, so the leading name is a performer.
    raw = "【HD】陳一發兒 - 童話鎮 [歌詞字幕] Chen Yifa - Fairy Town"
    assert recover_artist(raw, "BELLA PING MUSIC CHANNEL") == "陳一發兒"


def test_a_bar_separated_lead_in_is_not_a_performer():
    # A commentary lead-in before the title is a sentence about the song. Taking it
    # as the performer overwrote the reported artist for a row the corpus marks as
    # carrying no leading credit at all.
    title = "单曲循环丨张远深情嗓好适合《达尔文》！「我的青春 有时还蛮单纯」"
    assert recover_artist(title, "中國浙江衛視官方頻道") == "中國浙江衛視官方頻道"


def test_a_contraction_does_not_close_a_quoted_title():
    # Channels wrap the song in typographic quotes, and the non-greedy close landed
    # on the apostrophe inside the song's own name: ILLIT (아일릿) ‘It’s Me’ Official
    # MV was searched for as "It s Me’" and matched nothing.
    contracted = _TITLE_QUOTE.search("ILLIT (아일릿) ‘It’s Me’ Official MV")
    plain = _TITLE_QUOTE.search("ILLIT (아일릿) ‘Magnetic’ Official MV")

    assert contracted is not None and plain is not None
    assert contracted.group(2) == "It’s Me"
    assert plain.group(2) == "Magnetic"


def test_lyric_video_brackets_and_topic_channels_are_shared_grammar():
    # Both describe how a publisher decorates an upload, not how the metadata
    # travelled, so every ingest path must reach them — the Cider plugin supplies
    # track metadata that never passes through MPRIS, where these used to live.
    assert clean_title("隱形的翅膀 張韶涵『動態歌詞Lyrics』") == "隱形的翅膀 張韶涵"
    assert clean_title("告白氣球『歌词版』") == "告白氣球"
    assert performing_artist("Eason Chan - Topic") == "Eason Chan"
    # A hyphen inside a real name is not a channel suffix.
    assert performing_artist("Jay-Z") == "Jay-Z"


def test_a_chinese_version_marker_is_read_as_a_version():
    # These were stripped as decoration and recorded as no tag at all, so the
    # version-conflict check could never fire on them: searching 不谓侠 with no
    # artist returned 不谓侠(女声版) as the best match, whose words are the same and
    # whose timings are not.
    for title, tag in [
        ("不谓侠(女声版)", "alt_vocal"),
        ("不谓侠 (DJ版)", "remix"),
        ("大鱼(钢琴版)", "instrumental"),
        ("大鱼（纯音乐版）", "instrumental"),
    ]:
        _base, tags = split_title(title, "")
        assert tag in tags, f"{title!r} recorded {sorted(tags)}"


def test_the_studio_pressing_is_not_a_version_conflict():
    # The negative control. 唱片版 is the ordinary studio recording, not a re-cut of
    # it, so reading it as a version would reject the one candidate that is right.
    base, tags = split_title("大鱼 (唱片版)", "")

    assert base == "大鱼"
    assert not tags
