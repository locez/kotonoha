from kotonoha.lyrics.lrc_parser import merge_translation, parse_lrc
from kotonoha.lyrics.match import (
    Candidate,
    MatchConfidence,
    TrackMetadata,
    artist_tokens,
    best_match,
    evaluate_match,
    normalize,
    query_variants,
)
from kotonoha.lyrics.yrc_parser import parse_yrc

# Real lines from the live Netease api/song/lyric/v1 response (id=299981).
YRC_SAMPLE = (
    '{"t":0,"c":[{"tx":"作词: "},{"tx":"林夕"}]}\n'
    "[1300,1950](1300,243,0)眉(1543,243,0)目(1786,243,0)里(2029,243,0)似(2272,243,0)哭(2515,243,0)不(2758,243,0)似(3001,249,0)哭\n"
    "[3440,6530](3440,240,0)还(3680,450,0)祈(4130,2660,0)求\n"
)


def test_parse_yrc_word_timing():
    lines = parse_yrc(YRC_SAMPLE)
    assert len(lines) == 2  # JSON metadata line skipped
    first = lines[0]
    assert first.text == "眉目里似哭不似哭"
    assert first.start == 1.3
    assert first.end == 3.25  # 1300 + 1950 ms
    assert len(first.words) == 8
    assert first.words[0].text == "眉"
    assert first.words[0].start == 1.3
    assert first.words[0].end == 1.543
    assert first.has_word_timing


def test_parse_yrc_skips_metadata_and_blank():
    assert parse_yrc('{"t":0,"c":[{"tx":"x"}]}\n\n   \n') == []


LRC_SAMPLE = "[00:01.30]眉目里似哭不似哭\n[00:03.44]还祈求什么说不出\n[00:10.560]陪着你轻呼着烟圈\n"


def test_parse_lrc_lines_and_end_times():
    lines = parse_lrc(LRC_SAMPLE)
    assert [round(line.start, 2) for line in lines] == [1.3, 3.44, 10.56]
    assert lines[0].end == 3.44  # next line's start
    assert lines[0].text == "眉目里似哭不似哭"
    assert not lines[0].has_word_timing  # line-timed only


def test_parse_lrc_multiple_tags_same_line():
    lines = parse_lrc("[00:01.00][00:05.00]repeat\n")
    assert len(lines) == 2
    assert all(line.text == "repeat" for line in lines)


def test_merge_translation_by_nearest_time():
    base = parse_lrc("[00:01.00]hello\n[00:05.00]world\n")
    trans = parse_lrc("[00:01.05]你好\n[00:05.10]世界\n")
    merged = merge_translation(base, trans)
    assert merged[0].translation == "你好"
    assert merged[1].translation == "世界"


def test_merge_translation_out_of_tolerance_left_blank():
    base = parse_lrc("[00:01.00]hello\n")
    trans = parse_lrc("[00:09.00]too far\n")
    assert merge_translation(base, trans)[0].translation == ""


def test_normalize_strips_notes_and_punctuation():
    assert normalize("暧昧 (Live)") == "暧昧"
    assert normalize("Song feat. X") == "song"
    assert normalize("A - B!") == "ab"


def test_normalize_uses_nfkc_and_safe_feat_boundaries():
    assert normalize("Ｓｏｎｇ") == "song"
    assert normalize("Feather") == "feather"
    assert normalize("FTISLAND") == "ftisland"
    assert normalize("Song feat. Guest") == "song"


def test_duration_alone_is_not_a_match():
    track = TrackMetadata("Target", "Artist", "", 180.0)
    candidate = Candidate("1", "Other", "Someone", 180.0)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.NONE


def test_explicit_live_version_conflict_is_rejected():
    track = TrackMetadata("Song", "Artist", "Album", 200.0)
    candidate = Candidate("1", "Song (Live)", "Artist", 200.5, album="Album")
    assert evaluate_match(candidate, track).confidence is MatchConfidence.NONE


def test_dash_suffix_live_version_conflict_is_rejected():
    track = TrackMetadata("Song", "Artist", "Album", 200.0)
    candidate = Candidate("1", "Song - Live at Wembley", "Artist", 200.5, album="Album")
    assert evaluate_match(candidate, track).confidence is MatchConfidence.NONE


def test_same_artist_and_duration_do_not_rescue_unrelated_title():
    track = TrackMetadata("Target", "Artist", "", 180.0)
    candidate = Candidate("1", "Completely Different", "Artist", 180.0)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.NONE


def test_artist_order_does_not_change_identity():
    track = TrackMetadata("Song", "A / B", "", 180.0)
    candidate = Candidate("1", "Song", "B, A", 180.5)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.HIGH


def test_exact_title_artist_and_album_survive_unreliable_player_duration():
    track = TrackMetadata("Song", "Artist", "Serving You", 358.039136)
    candidate = Candidate("1", "Song", "Artist", 229.28, album="Serving You")
    assert evaluate_match(candidate, track).confidence is MatchConfidence.MEDIUM


def test_duration_conflict_without_album_identity_is_rejected():
    track = TrackMetadata("Song", "Artist", duration_s=358.039136)
    candidate = Candidate("1", "Song", "Artist", 229.28)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.NONE


def test_duration_conflict_with_partial_artist_overlap_is_rejected():
    track = TrackMetadata("Song", "Artist / Guest", "Album", 358.039136)
    candidate = Candidate("1", "Song", "Artist", 229.28, album="Album")
    assert evaluate_match(candidate, track).confidence is MatchConfidence.NONE


def test_missing_artist_and_duration_is_not_persistent_confidence():
    track = TrackMetadata("Song", "")
    candidate = Candidate("1", "Song", "Other Artist", None)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.MEDIUM


def test_artist_tokens_split_on_chinese_and():
    assert artist_tokens("初音ミク和鏡音リン") == artist_tokens("初音ミク / 鏡音リン")


def test_fused_chinese_and_list_matches_separated_candidate():
    # MPRIS reports a fused "A、B和C"; Netease lists the same artists separately.
    track = TrackMetadata("Song", "とあ、初音ミク和鏡音リン", "", 180.0)
    candidate = Candidate("1", "Song", "初音ミク / 鏡音リン", 180.0)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.HIGH


def test_artist_name_containing_and_still_matches_itself():
    # 大和 is a single name; 和 must not split it (only >=2 chars each side split).
    track = TrackMetadata("Song", "大和", "", 180.0)
    candidate = Candidate("1", "Song", "大和", 180.0)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.HIGH


def test_and_does_not_fragment_a_multi_char_single_name():
    # 山田和樹 (Yamada Kazuki) is ONE person: 和 has only a single char after it,
    # so it must stay whole instead of fragmenting into 山田 + 樹.
    assert artist_tokens("山田和樹") == artist_tokens("山田和树")
    assert len(artist_tokens("山田和樹")) == 1


def test_empty_normalized_titles_do_not_match():
    # Both titles normalize to "" (all parenthetical); SequenceMatcher("","") is
    # 1.0, which previously let unrelated interludes match on a shared artist.
    track = TrackMetadata("(intro)", "A", "", 100.0)
    candidate = Candidate("1", "(outro)", "A", 101.0)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.NONE


def test_normalize_folds_traditional_to_simplified():
    assert normalize("李榮浩") == normalize("李荣浩")
    assert normalize("愛情轉移") == normalize("爱情转移")


def test_convert_script_both_directions():
    from kotonoha.lyrics.hanzi_fold import convert_script

    assert convert_script("李荣浩", "zh-Hant") == "李榮浩"
    assert convert_script("李榮浩", "zh-Hans") == "李荣浩"
    assert convert_script("李荣浩", "off") == "李荣浩"  # no-op when disabled


def test_traditional_track_matches_simplified_netease_candidate():
    # zh-Hant browser reports 麻雀 / 李榮浩; Netease lists 简体 麻雀 / 李荣浩.
    track = TrackMetadata("麻雀", "李榮浩", "", None)
    candidate = Candidate("1", "麻雀", "李荣浩", None)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.HIGH


def test_query_variants_add_simplified_fold_for_traditional_input():
    assert "麻雀 李荣浩" in query_variants(TrackMetadata("麻雀", "李榮浩"))


def test_noisy_title_queries_salvage_cluttered_browser_titles():
    from kotonoha.lyrics.match import noisy_title_queries

    track = TrackMetadata(
        "【HD】陳一發兒- 童話鎮 [歌詞字幕][完整高清音] Chen Yifa - Fairy Town BELLA PING MUSIC CHANNEL", ""
    )
    queries = noisy_title_queries(track)
    assert any("陳一發兒" in q and "童話鎮" in q for q in queries)  # CJK run pulled out
    assert "Chen Yifa Fairy Town" in queries  # Latin run, channel tail dropped
    # Corner-bracket titles: the title inside 「」is kept, upload noise removed.
    lemon = noisy_title_queries(TrackMetadata("米津玄師 MV「Lemon」【完整高清】YouTube Music", ""))
    assert any("Lemon" in q and "米津玄師" in q for q in lemon)


def test_noisy_title_queries_keep_a_title_that_lives_inside_brackets():
    from kotonoha.lyrics.match import noisy_title_queries

    # Some channels put the SONG TITLE in 【】/[ ] — it must be kept, not stripped
    # like the junk brackets (【HD】, [歌詞字幕]) are.
    q1 = noisy_title_queries(TrackMetadata("薛之謙 Joker Xue【演員】Official Music Video", ""))
    assert any("薛之謙" in q and "演員" in q for q in q1)
    q2 = noisy_title_queries(TrackMetadata("告五人 Accusefive [ 唯一 The One And Only ] Official MV", ""))
    assert any("告五人" in q and "唯一" in q for q in q2)
    # ...while a junk-only bracket is still dropped.
    q3 = noisy_title_queries(TrackMetadata("【HD】周杰倫 - 晴天 [官方MV][歌詞字幕] Jay Chou", ""))
    assert any(q == "周杰倫 晴天" for q in q3)


def test_generic_alias_without_track_artist_does_not_reach_high():
    # A track with no artist (the common browser case) must not be promoted to HIGH
    # by a short generic alias + a coincidental duration — that would cache the wrong
    # song's lyrics as authoritative.
    track = TrackMetadata("Lemon", "", "", 240.0)
    candidate = Candidate("1", "檸檬", "某歌手", 238.0, aliases=("Lemon",))
    assert evaluate_match(candidate, track).confidence is not MatchConfidence.HIGH
    # With a matching artist it is trustworthy again.
    track2 = TrackMetadata("Lemon", "米津玄師", "", 240.0)
    candidate2 = Candidate("2", "檸檬", "米津玄師", 238.0, aliases=("Lemon",))
    assert evaluate_match(candidate2, track2).confidence is MatchConfidence.HIGH


def test_noisy_title_queries_strip_fused_cjk_upload_noise():
    from kotonoha.lyrics.match import noisy_title_queries

    # CJK upload noise fused to real text (官方MV, 完整版, 歌詞) must be stripped even
    # with no surrounding spaces — \b never sits between two Han characters.
    q = noisy_title_queries(TrackMetadata("周杰倫 晴天 官方MV 完整版", ""))
    assert any("晴天" in item and "官方" not in item and "完整版" not in item for item in q)


def test_noisy_title_queries_keep_a_genuinely_all_caps_title():
    from kotonoha.lyrics.match import noisy_title_queries

    q = noisy_title_queries(TrackMetadata("TALK THAT TALK", "TWICE"))
    assert any("TALK THAT TALK" in item for item in q)  # not truncated to "TALK THAT"


def test_fuzzy_containment_rejects_a_too_short_title_even_when_contained():
    # A 1-char CJK candidate title sitting inside the noisy track title, with its
    # artist token co-occurring, is still rejected — a single common character must
    # not match a long title by coincidence (the length guard is the safety net).
    track = TrackMetadata("周杰伦 爱 官方现场", "", "", None)
    candidate = Candidate("1", "爱", "周杰伦", None)
    assert evaluate_match(candidate, track, fuzzy=True).confidence is MatchConfidence.NONE


def test_fuzzy_matches_a_title_that_fuses_artist_and_song():
    # A cluttered title carrying both names; only fuzzy mode rescues it, and only
    # when an artist token co-occurs (so a bare title substring can't match).
    track = TrackMetadata("周杰伦 晴天 official mv", "", "", None)
    right = Candidate("1", "晴天", "周杰伦 / A-LNK", 269.0)
    wrong = Candidate("2", "晴天", "林俊杰", 240.0)
    assert evaluate_match(right, track, fuzzy=True).confidence is MatchConfidence.MEDIUM
    assert evaluate_match(right, track, fuzzy=False).confidence is MatchConfidence.NONE
    assert evaluate_match(wrong, track, fuzzy=True).confidence is MatchConfidence.NONE


def test_query_variants_fuzzy_adds_cleaned_forms():
    track = TrackMetadata("【MV】告白氣球 周杰倫 官方", "")
    plain = query_variants(track)
    fuzzy = query_variants(track, fuzzy=True)
    assert set(plain).issubset(set(fuzzy))
    assert any("告白" in q for q in fuzzy)
    assert "告白气球 周杰伦" in fuzzy  # simplified fold of the cleaned query


def test_english_title_matches_candidate_via_translated_alias():
    # A browser reports the English name; Netease lists the song under 生如夏花 with
    # "Life Like Summer Flowers" among its transNames. The alias bridges them.
    track = TrackMetadata("Life Like Summer Flowers", "朴树", "", 272.0)
    candidate = Candidate(
        "1", "生如夏花", "朴树", 272.0, aliases=("Life Like Summer Flowers",)
    )
    assert evaluate_match(candidate, track).confidence is MatchConfidence.HIGH


def test_alias_does_not_manufacture_a_match_for_a_different_song():
    # An unrelated alias must not turn a wrong candidate into a match.
    track = TrackMetadata("Blue Bird", "Anna", "", 200.0)
    candidate = Candidate("1", "青鸟", "别人", 120.0, aliases=("Green Sky",))
    assert evaluate_match(candidate, track).confidence is MatchConfidence.NONE


def test_exact_title_and_artist_survive_a_wildly_wrong_duration():
    # A browser reported a 27-minute container length for a 5-minute song; the exact
    # title + exact artist must still match (as MEDIUM) so the lyrics are not dropped.
    track = TrackMetadata("Life Like Summer Flowers", "Pu Shu", "", 1644.0)
    candidate = Candidate("1", "Life Like Summer Flowers", "Pu Shu", 295.0)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.MEDIUM


def test_duration_accurate_candidate_still_outranks_the_duration_skewed_one():
    # When both share the exact title+artist, the one whose duration matches wins.
    track = TrackMetadata("Song", "Band", "", 300.0)
    good = Candidate("good", "Song", "Band", 300.0)
    skewed = Candidate("skew", "Song", "Band", 1644.0)
    best = best_match([skewed, good], track)
    assert best is not None and best.candidate.song_id == "good"


def test_middle_dot_is_not_split_so_different_same_forename_artists_do_not_match():
    # "・" separates the forename/surname inside ONE katakana name, so it must not
    # be a token separator: two different people who share a given name (ジョン・レノン
    # vs ジョン・デンバー) must not collide into a confident wrong-artist match.
    track = TrackMetadata("Imagine", "ジョン・レノン", "", None)
    candidate = Candidate("1", "Imagine", "ジョン・デンバー", None)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.NONE


def test_full_katakana_name_still_matches_itself():
    # The same katakana name (dot and all) is still an exact artist identity.
    track = TrackMetadata("Beat It", "マイケル・ジャクソン", "", 258.0)
    candidate = Candidate("1", "Beat It", "マイケル・ジャクソン", 258.0)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.HIGH


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


def test_accented_title_reaches_high_confidence():
    track = TrackMetadata("Déjà Vu", "Olivia Rodrigo", "", 215.0)
    candidate = Candidate("1", "Deja Vu", "Olivia Rodrigo", 215.0)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.HIGH


def test_remaster_is_not_a_version_conflict():
    # A remaster shares the studio lyrics, so it must not be rejected as a conflict.
    track = TrackMetadata("Song", "Artist", "", 180.0)
    candidate = Candidate("1", "Song (Remastered 2011)", "Artist", 180.0)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.HIGH


def test_exact_title_and_artist_survive_small_duration_skew():
    track = TrackMetadata("Song", "Artist", "", 180.0)
    candidate = Candidate("1", "Song", "Artist", 186.0)  # 6s skew, exact title + artist
    assert evaluate_match(candidate, track).confidence is MatchConfidence.HIGH


def test_best_match_prefers_genuine_artist_over_missing_artist():
    track = TrackMetadata("Song", "Artist", "", 180.0)
    candidates = [Candidate("noart", "Song", "", 180.0), Candidate("art", "Song", "Artist", 180.0)]
    assert best_match(candidates, track).candidate.song_id == "art"


def test_query_variants_are_raw_then_base_title_primary_artist():
    track = TrackMetadata("Song (Remastered 2011)", "A feat. B", "Album", 180.0)
    assert query_variants(track) == (
        "Song (Remastered 2011) A feat. B",
        "Song A",
    )


def test_best_match_prefers_duration():
    cands = [
        Candidate("1", "暧昧", "王菲", 282.0),   # right duration
        Candidate("2", "暧昧 (Live)", "王菲", 350.0),  # wrong duration
    ]
    best = best_match(cands, TrackMetadata("曖昧", "王菲", duration_s=281.0))
    assert best is not None
    assert best.candidate.song_id == "1"
    # The traditional 曖昧 folds to the simplified 暧昧, so the title is an exact
    # match and the close duration lifts it to HIGH.
    assert best.confidence is MatchConfidence.HIGH


def test_best_match_rejects_when_nothing_close():
    cands = [Candidate("9", "totally other", "someone", 999.0)]
    assert best_match(cands, TrackMetadata("暧昧", "王菲", duration_s=281.0)) is None


def test_best_match_empty():
    assert best_match([], TrackMetadata("t", "a", duration_s=100.0)) is None
