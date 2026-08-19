from typing import cast

import aiohttp
import pytest
from fixtures.mpris_titles import MPRIS_TITLE_CASES

from kotonoha.lyrics import kugou
from kotonoha.lyrics.match import (
    Candidate,
    MatchConfidence,
    TrackMetadata,
    _weighted_similarity,
    best_match,
    evaluate_match,
    nearest_miss,
    query_variants,
    ranked_matches,
)
from kotonoha.lyrics.titles import (
    artist_tokens,
    clean_title,
    noisy_title_queries,
    normalize,
    recover_artist,
    split_title,
)


# Real lines from the live Netease api/song/lyric/v1 response (id=299981).
@pytest.mark.asyncio
async def test_kugou_undecodable_krc_falls_back_to_lrc(monkeypatch):
    record = kugou.Record("1", "key", "Song", "Artist", 180.0)

    async def fake_search(*_args, **_kwargs):
        return [record]

    async def fake_download_krc(*_args, **_kwargs):
        return b"broken"

    async def fake_download_lrc(*_args, **_kwargs):
        return "[00:01.00]fallback"

    monkeypatch.setattr(kugou, "search", fake_search)
    monkeypatch.setattr(kugou, "download_krc", fake_download_krc)
    monkeypatch.setattr(kugou, "download_lrc", fake_download_lrc)

    artifact = await kugou.fetch_artifact(
        cast(aiohttp.ClientSession, None), TrackMetadata("Song", "Artist", duration_s=180.0)
    )

    assert artifact is not None
    assert [line.text for line in artifact.lines] == ["fallback"]


@pytest.mark.asyncio
async def test_kugou_a_failed_krc_download_moves_on_instead_of_raising(monkeypatch):
    # Fetching and parsing shared one try block, so a network error left krc unbound:
    # the branch below it raised UnboundLocalError, which no caller catches.
    record = kugou.Record("1", "key", "Song", "Artist", 180.0)

    async def fake_search(*_args, **_kwargs):
        return [record]

    async def failing_download(*_args, **_kwargs):
        raise aiohttp.ClientError("network down")

    monkeypatch.setattr(kugou, "search", fake_search)
    monkeypatch.setattr(kugou, "download_krc", failing_download)

    assert (
        await kugou.fetch_artifact(
            cast(aiohttp.ClientSession, None), TrackMetadata("Song", "Artist", duration_s=180.0)
        )
        is None
    )


@pytest.mark.parametrize(
    ("reported", "expected"),
    [
        ("Ariana Grande - hate that i made you love me (official music video)", "hate that i made you love me"),
        ("Bad Bunny - Tití Me Preguntó (Video Oficial) | Un Verano Sin Ti", "tití me preguntó"),
        ("汪峰《春天里》高清MV", "春天里"),
        ("美秀集團 Amazing Show－捲菸 Roll-Cigg【Official Music Video】", "美秀集團 Amazing Show 捲菸 Roll-Cigg"),
    ],
)
def test_platform_title_grammar_is_removed_before_matching(reported, expected):
    artist = "Ariana Grande" if "Ariana" in reported else "Bad Bunny" if "Bad Bunny" in reported else "汪峰"
    track = TrackMetadata(reported, artist)
    candidate = Candidate("song", expected, track.artist, None)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.HIGH


@pytest.mark.parametrize(
    ("reported", "expected"),
    [
        ("BTS (방탄소년단) '2.0' Official MV", "2.0"),
        ("BTS (방탄소년단) ‘SWIM’ Official MV", "SWIM"),
        ("Hearts2Hearts 하츠투하츠 'RUDE!' MV", "RUDE!"),
        ('"PINKY UP" MV (Choreography Ver.) | KATSEYE', "PINKY UP (Choreography Ver.)"),
    ],
)
def test_quoted_platform_titles_keep_the_real_title(reported, expected):
    track = TrackMetadata(reported, "HYBE LABELS" if reported.startswith("BTS") else "KATSEYE")
    candidate = Candidate("song", expected, track.artist, None)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.HIGH


def test_platform_title_bars_choose_the_song_segment_and_keep_cjk_pipe():
    # Segment selection only. This particular upload never reaches the matcher in
    # production — the corpus classifies it as not_music and the lookup gate skips
    # it on the "一小時" marker — so this asserts which segment is chosen, not that
    # a one-hour compilation should get the song's lyrics.
    track = TrackMetadata(
        "路小雨 Lu Xiao Yu｜不能說的秘密 Secret OST | One hour 一小時放鬆音樂｜周杰倫 Jay Chou｜"
        "Played by Elvis Piano 維敏彈鋼琴",
        "Elvis Piano 維敏彈鋼琴",
    )
    candidate = Candidate("song", "不能說的秘密 Secret OST", "Elvis Piano 維敏彈鋼琴", None)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.HIGH

    # Asserted through the title path, not through normalize(): that function is
    # also the comparison key for artist and album, so a title-only rule applied
    # there would rewrite an identity rather than tidy a title.
    cjk_pipe = TrackMetadata("单曲循环丨张远深情嗓好适合《达尔文》！", "中國浙江衛視官方頻道")
    plain = TrackMetadata("张远深情嗓好适合《达尔文》！", cjk_pipe.artist)
    assert normalize(split_title(cjk_pipe.title, cjk_pipe.artist)[0]) == normalize(
        split_title(plain.title, plain.artist)[0]
    )


def test_platform_bar_skips_artist_segment_before_matching():
    track = TrackMetadata("老王樂隊｜我還年輕 我還年輕 Official Music Video", "老王樂隊")
    candidate = Candidate("song", "我還年輕 我還年輕", "老王樂隊", None)
    assert split_title(track.title, track.artist) == ("我還年輕 我還年輕", frozenset())
    assert evaluate_match(candidate, track).confidence is MatchConfidence.HIGH


def test_platform_title_whitespace_and_case_are_comparison_insensitive():
    track = TrackMetadata("阿拉善  ", "貳佰")
    candidate = Candidate("song", "阿拉善", "贰佰", None)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.HIGH

    spaced_artist = TrackMetadata("顽疾 (Live)", "薛之 謙")
    candidate = Candidate("song", "顽疾 (Live)", "薛之謙", None)
    assert evaluate_match(candidate, spaced_artist).confidence is MatchConfidence.HIGH


def test_duration_alone_is_not_a_match():
    track = TrackMetadata("Target", "Artist", "", 180.0)
    candidate = Candidate("1", "Other", "Someone", 180.0)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.NONE


def test_explicit_live_version_conflict_is_rejected():
    track = TrackMetadata("Song", "Artist", "Album", 200.0)
    candidate = Candidate("1", "Song (Live)", "Artist", 200.5, album="Album")
    assert evaluate_match(candidate, track).confidence is MatchConfidence.NONE


def test_chinese_instrumental_title_does_not_match_vocal_candidate():
    marked_track = TrackMetadata("甲乙丙丁 (你我怎麼兩清伴奏)", "李佳薇")
    vocal_candidate = Candidate("vocal", "甲乙丙丁 (你我怎麼兩清)", "李佳薇", None)
    assert evaluate_match(vocal_candidate, marked_track).confidence is MatchConfidence.NONE


def test_chinese_alternate_title_still_matches_vocal_candidate():
    alternate_track = TrackMetadata("甲乙丙丁 (你我怎麼兩清)", "李佳薇")
    vocal_candidate = Candidate("vocal", "甲乙丙丁 (你我怎麼兩清)", "李佳薇", None)
    assert evaluate_match(vocal_candidate, alternate_track).confidence is MatchConfidence.HIGH


@pytest.mark.parametrize(
    ("marker", "opening", "closing"),
    [
        ("伴奏", "(", ")"),
        ("instrumental version", "[", "]"),
        ("off vocal", "【", "】"),
        ("karaoke", "（", "）"),
        ("live", "(", ")"),
        ("Live版", "", ""),
        ("remix", "(", ")"),
        ("cover", "(", ")"),
        ("acoustic", "(", ")"),
        ("吉他版", "(", ")"),
        ("彈唱版", "(", ")"),
        ("戏腔版", "(", ")"),
        ("粤语版", "(", ")"),
        ("原声版", "(", ")"),
        ("Sped Up Version", "(", ")"),
        ("Full Version", "(", ")"),
        ("Opening Title Version", "(", ")"),
        # The re-upload family: same words, different tempo, so the timings a
        # karaoke overlay needs do not line up with the studio take.
        ("Slowed", "(", ")"),
        ("Slowed + Reverb", "(", ")"),
        ("Nightcore", "(", ")"),
        ("烟嗓版", "(", ")"),
        ("律动版", "（", "）"),
        ("R&B心碎版", "(", ")"),
    ],
)
def test_version_markers_conflict_in_both_directions(marker, opening, closing):
    marked_title = f"Song {opening}{marker}{closing}"
    marked_track = TrackMetadata(marked_title, "Artist")
    plain_track = TrackMetadata("Song", "Artist")
    plain_candidate = Candidate("plain", "Song", "Artist", None)
    marked_candidate = Candidate("marked", marked_title, "Artist", None)

    assert evaluate_match(plain_candidate, marked_track).confidence is MatchConfidence.NONE
    assert evaluate_match(marked_candidate, plain_track).confidence is MatchConfidence.NONE
    assert evaluate_match(marked_candidate, marked_track).confidence is MatchConfidence.HIGH


def test_localized_collaboration_credit_is_not_a_version_marker():
    track = TrackMetadata("恋の才能 (合作演出：初音ミク)", "Artist")
    candidate = Candidate("song", "恋の才能", "Artist", None)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.HIGH
    assert normalize("恋の才能 合作演出：初音ミク") == normalize("恋の才能")


@pytest.mark.parametrize(
    ("opening", "closing"),
    [("(", ")"), ("（", "）"), ("[", "]"), ("【", "】"), ("『", "』")],
)
def test_bracketed_alternate_title_is_not_a_version_marker(opening, closing):
    track = TrackMetadata(f"甲乙丙丁 {opening}你我怎麼兩清{closing}", "李佳薇")
    candidate = Candidate("vocal", "甲乙丙丁", "李佳薇", None)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.HIGH


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


def test_empty_normalized_titles_do_not_match():
    # Both titles normalize to "" (all parenthetical); SequenceMatcher("","") is
    # 1.0, which previously let unrelated interludes match on a shared artist.
    track = TrackMetadata("(intro)", "A", "", 100.0)
    candidate = Candidate("1", "(outro)", "A", 101.0)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.NONE


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
    # A Simplified-only catalogue never sees the Traditional spelling. Every provider
    # gets this rung now; two of them used to assemble their own ladder without it.
    texts = [variant.text for variant in query_variants(TrackMetadata("麻雀", "李榮浩"))]

    assert "麻雀 李荣浩" in texts


def test_noisy_title_queries_salvage_cluttered_browser_titles():
    from kotonoha.lyrics.titles import noisy_title_queries

    track = TrackMetadata(
        "【HD】陳一發兒- 童話鎮 [歌詞字幕][完整高清音] Chen Yifa - Fairy Town BELLA PING MUSIC CHANNEL", ""
    )
    queries = noisy_title_queries(track.title)
    assert any("陳一發兒" in q and "童話鎮" in q for q in queries)  # CJK run pulled out
    assert "Chen Yifa Fairy Town" in queries  # Latin run, channel tail dropped
    # Corner-bracket titles: the title inside 「」is kept, upload noise removed.
    lemon = noisy_title_queries("米津玄師 MV「Lemon」【完整高清】YouTube Music")
    assert any("Lemon" in q and "米津玄師" in q for q in lemon)


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
    texts = [variant.text for variant in fuzzy]
    assert any("告白" in text for text in texts)
    assert "告白气球 周杰伦" in texts  # simplified fold of the cleaned query
    # A salvaged reading carries no artist: it comes out of an upload title whose
    # "artist" is the channel that posted it.
    assert all(not v.artist for v in fuzzy if v.rung.startswith("salvaged"))


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


@pytest.mark.parametrize(
    ("has_artist", "has_album", "expected"),
    [
        (True, True, 0.4 * 0.5 + 0.2 * 0.6 + 0.4 * 0.7),
        (True, False, 0.7 * 0.5 + 0.3 * 0.6),
        (False, True, 0.8 * 0.5 + 0.2 * 0.7),
        (False, False, 0.5),
    ],
)
def test_weighted_similarity_degrades_by_available_track_fields(has_artist, has_album, expected):
    score = _weighted_similarity(0.5, 0.6, 0.7, has_artist=has_artist, has_album=has_album)
    assert score == pytest.approx(expected)


def test_similarity_ranks_real_title_album_variants_between_exact_and_missing():
    real_case = MPRIS_TITLE_CASES[0]
    track = TrackMetadata(real_case.clean_title, real_case.clean_artist, "安和橋北", 250.0)
    exact = Candidate("exact", real_case.clean_title, real_case.clean_artist, 250.0, album="安和橋北")
    edition = Candidate(
        "edition", real_case.clean_title, real_case.clean_artist, 250.0, album="安和橋北 - Deluxe Edition"
    )
    missing = Candidate("missing", real_case.clean_title, real_case.clean_artist, 250.0)

    ranked = ranked_matches([missing, edition, exact], track)

    assert [match.candidate.song_id for match in ranked] == ["exact", "edition", "missing"]


def test_similarity_uses_normalized_artist_and_album_text():
    track = TrackMetadata("Song", "Beyoncé", "安和橋北")
    candidate = Candidate("candidate", "Song", "Beyonce", None, album="安和桥北")

    evidence = evaluate_match(candidate, track)

    assert evidence.similarity_score == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [("", "", 0.0), ("a", "a", 1.0), ("a", "b", 0.0), ("安和", "安和", 1.0)],
)
def test_similarity_handles_degenerate_and_cjk_strings(left, right, expected):
    from kotonoha.lyrics.match import _similarity

    assert _similarity(left, right) == expected


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
    evidence = best_match(candidates, track)
    assert evidence is not None
    assert evidence.candidate.song_id == "art"


def test_query_variants_are_raw_then_base_title_primary_artist():
    track = TrackMetadata("Song (Remastered 2011)", "A feat. B", "Album", 180.0)

    variants = query_variants(track)

    assert [(v.rung, v.text) for v in variants] == [
        ("reported", "Song (Remastered 2011) A feat. B"),
        ("title-only", "Song"),
        ("base+primary", "Song A"),
    ]


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


def test_a_title_that_is_only_a_bracketed_span_is_still_a_title():
    # "【七月上】" stripped to nothing and could then never match the song it names.
    assert normalize("【七月上】") == normalize("七月上")
    assert split_title("【不露聲色】")[0] == "不露聲色"

    track = TrackMetadata("【七月上】", "Jam", "", None)
    assert evaluate_match(Candidate("1", "七月上", "Jam", None), track).confidence is MatchConfidence.HIGH

    # Two such titles must still agree exactly: different interludes, not a ratio.
    interlude = TrackMetadata("(intro)", "A", "", 100.0)
    assert evaluate_match(Candidate("2", "(outro)", "A", 101.0), interlude).confidence is MatchConfidence.NONE


def test_a_choreography_video_keeps_the_studio_lyrics():
    # A dance-practice upload carries the studio recording's audio, so it must not
    # reject the only candidate that has lyrics.
    track = TrackMetadata("PINKY UP (Choreography Ver.)", "KATSEYE", "", None)
    candidate = Candidate("1", "PINKY UP", "KATSEYE", None)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.HIGH


def test_title_cleaning_never_rewrites_an_artist_identity():
    # normalize() is the comparison key for artist and album as well as titles, so
    # applying the title-only upload-grammar rules there turned two different
    # performers into one: "Audio Love" lost its first word and matched "Love".
    assert normalize("Audio Love") != normalize("Love")
    assert artist_tokens("Audio Love") != artist_tokens("Love")

    track = TrackMetadata("Song", "Audio Love")
    candidate = Candidate("c", "Song", "Love", None)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.NONE

    # The same rule still applies where it belongs — to the title.
    assert clean_title("Track - Official Audio", "Artist") == "Track"
    assert (
        evaluate_match(
            Candidate("c", "Track", "Artist", None),
            TrackMetadata("Track - Official Audio", "Artist"),
            fuzzy=True,
        ).confidence
        is MatchConfidence.HIGH
    )


@pytest.mark.parametrize(
    ("marked", "plain"),
    [
        ("Song (Acounstic Version)", "Song"),          # the upload's own spelling
        ("ツギハギスタッカート 歌ってみた。", "ツギハギスタッカート"),   # a user cover
        ("ハローセカイ / バーチャル・シンガーver.", "ハローセカイ"),  # another vocalist
    ],
)
def test_real_version_markers_from_the_corpus_conflict(marked, plain):
    # Each of these appears in a real library. Unrecognised, the studio take was
    # matched to a different performance and every line landed out of time.
    marked_track = TrackMetadata(marked, "Artist")
    plain_candidate = Candidate("plain", plain, "Artist", None)

    assert evaluate_match(plain_candidate, marked_track).confidence is MatchConfidence.NONE


def test_spaced_han_conjunction_separates_performers():
    # YouTube Music joins performers with 和 in a Chinese UI. A name that contains
    # 和 (和田光司, 山田和樹) does not carry spaces around just that character, so
    # only the spaced form is treated as a separator.
    assert artist_tokens("Lady Gaga 和 Bruno Mars") == artist_tokens("Lady Gaga, Bruno Mars")
    assert len(artist_tokens("和田光司")) == 1
    assert len(artist_tokens("山田和樹")) == 1

    track = TrackMetadata("Die With A Smile", "Lady Gaga, Bruno Mars", "", None)
    candidate = Candidate("1", "Die With A Smile", "Lady Gaga 和 Bruno Mars", None)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.HIGH


def test_a_parenthesised_letter_stays_part_of_the_performer_name():
    # (G)I-DLE is a name, not a name followed by a qualifier. The title cleaner
    # already protects that shape; truncating at the bracket here destroyed the
    # identity it preserves.
    assert recover_artist("Artist (G)I-DLE - Song", "Channel") == "(G)I-DLE"

    track = TrackMetadata("Song", "(G)I-DLE")
    assert evaluate_match(Candidate("c", "Song", "(G)I-DLE", None), track).confidence is MatchConfidence.HIGH


def test_a_marker_inside_the_name_is_not_a_version_qualifier():
    # Scanning the whole base title tagged the name itself: "Live and Learn" came
    # out tagged `live`, agreed with "Live and Learn (Live)", and the live
    # recording outranked the studio one the user was actually playing.
    track = TrackMetadata("Live and Learn", "Crush 40", duration_s=200.0)
    live = Candidate("live", "Live and Learn (Live)", "Crush 40", 200.0)
    studio = Candidate("studio", "Live and Learn", "Crush 40", 200.0)

    ranked = ranked_matches([live, studio], track)

    assert [match.candidate.song_id for match in ranked] == ["studio"]


def test_a_marker_the_name_ends_on_is_still_a_version_qualifier():
    # The other half: a track that really is a live version must not take the
    # plain studio candidate's lyrics.
    evidence = evaluate_match(
        Candidate("plain", "Song", "Artist", None), TrackMetadata("Song Live版", "Artist")
    )

    assert evidence.confidence is MatchConfidence.NONE


def test_a_salvaged_query_is_also_judged_by_what_it_salvaged():
    # The salvage widened the search and not the acceptance: searching for a clip
    # titled "Those Bygone Years 那些年" returns 那些年 / 胡夏 as the first candidate,
    # and every one of the ten was then rejected, because the scorer still compared
    # them against the uploader's decorated title.
    track = TrackMetadata("Those Bygone Years 那些年", "胡夏", "", None)
    candidate = Candidate("1", "那些年", "胡夏", None)

    assert evaluate_match(candidate, track, fuzzy=True).confidence is MatchConfidence.NONE
    assert ranked_matches([candidate], track, fuzzy=True)[0].confidence is MatchConfidence.HIGH


def test_a_fused_bilingual_channel_name_is_tried_one_name_at_a_time():
    # YouTube channels carry both of the performer's names at once and no catalogue
    # lists that fused form, so 告白氣球 was refused for the artist alone.
    track = TrackMetadata("告白氣球", "周杰倫 Jay Chou", "", None)
    candidate = Candidate("1", "告白气球", "周杰伦", None)

    assert ranked_matches([candidate], track, fuzzy=True), "the CJK half of the channel name was never tried"


def test_the_salvage_does_not_accept_a_different_song():
    # The negative control for both widenings. Each candidate shares a salvaged
    # fragment with what played and is still the wrong recording.
    refusals = [
        (("田馥甄 Hebe Tien 小幸運", "Liang Rainner"), ("Hebe Tien", "Various")),
        (("Those Bygone Years 那些年", "胡夏"), ("那些花兒", "朴樹")),
        (("【小酒窩 Dimples】(合唱:蔡卓妍 A-Sa)官方完整版", "林俊傑"), ("Dimples", "Some Band")),
        (("(特別演出: 派偉俊)【告白氣球 Love Confession】", "周杰倫 Jay Chou"), ("派偉俊", "派偉俊")),
    ]
    for (title, artist), (candidate_title, candidate_artist) in refusals:
        track = TrackMetadata(title, artist, "", None)
        candidate = Candidate("1", candidate_title, candidate_artist, None)
        assert not ranked_matches([candidate], track, fuzzy=True), f"{candidate_title!r} accepted for {title!r}"


def test_a_bracketed_guest_credit_is_dropped_but_a_version_marker_is_kept():
    credited = TrackMetadata("(特別演出: 派偉俊)【告白氣球 Love Confession】", "周杰倫", "", None)
    versioned = TrackMetadata("告白氣球 (演唱會版)", "周杰倫", "", None)

    assert "告白氣球" in noisy_title_queries(credited.title)
    # The version changes which recording is meant, so it must survive the same pass.
    assert all("演唱會版" in query for query in noisy_title_queries(versioned.title))


def test_a_featured_credit_in_the_title_is_offered_without_it():
    # A credited performer inside the title is not part of the song name, and the
    # credit is bounded by the separator after it, so it has to be removed before the
    # separators are flattened — otherwise it swallows the song too.
    prefixed = TrackMetadata("feat. BLUMENGARTEN & SHIRIN DAVID - GUT GENUG", "KITSCHKRIEG", "", None)
    suffixed = TrackMetadata("大展鸿图 ft.AR刘夫阳", "揽佬", "", None)

    assert "GUT GENUG" in noisy_title_queries(prefixed.title)
    assert "大展鸿图" in noisy_title_queries(suffixed.title)


def test_the_credited_title_is_still_offered_first():
    # Some catalogues index the credited form, so it is added to and not replaced.
    track = TrackMetadata("Old Town Road ft. Billy Ray Cyrus", "Lil Nas X", "", None)

    queries = noisy_title_queries(track.title)

    assert queries[0] == "Old Town Road ft. Billy Ray Cyrus"
    assert "Old Town Road" in queries


def test_with_does_not_read_as_a_credit():
    track = TrackMetadata("Dancing With Myself", "Billy Idol", "", None)

    assert noisy_title_queries(track.title) == ("Dancing With Myself",)


def test_a_channel_in_the_artist_field_yields_to_the_performer_in_the_title():
    # YouTube credits the uploading channel while the performer stays in the title.
    track = TrackMetadata("IU (아이유) _ Good Day (좋은 날) _", "1theK (원더케이)", "", None)
    candidate = Candidate("1", "Good Day", "IU", None)

    assert ranked_matches([candidate], track, fuzzy=True), "the performer named in the title was never tried"


def test_an_unusable_artist_alone_does_not_open_the_title_to_anyone():
    # The performer has to be present somewhere. Without that, judging on the title
    # alone accepts a different band's song of the same name, and a common title makes
    # that likely rather than rare.
    refusals = [
        (("Forever", "Some Channel"), ("Forever", "A Different Band")),
        (("Alone", "Uploader"), ("Alone", "Another Artist")),
        # The guest is named in the reported title and has already been ruled out of
        # the song name, so it must not stand in for the performer either.
        (("(特別演出: 派偉俊)【告白氣球 Love Confession】", "周杰倫 Jay Chou"), ("派偉俊", "派偉俊")),
    ]
    for (title, artist), (candidate_title, candidate_artist) in refusals:
        track = TrackMetadata(title, artist, "", None)
        candidate = Candidate("1", candidate_title, candidate_artist, None)
        assert not ranked_matches([candidate], track, fuzzy=True), f"{candidate_title!r} accepted for {title!r}"


def test_a_re_sung_version_no_longer_stands_in_for_the_recording():
    track = TrackMetadata("不谓侠", "", "", 259.0)

    resung = evaluate_match(Candidate("1", "不谓侠(女声版)", "慵狐", 266.0), track, fuzzy=True)
    plain = evaluate_match(Candidate("2", "不谓侠", "萧忆情Alex", 266.0), track, fuzzy=True)

    assert resung.confidence is MatchConfidence.NONE
    assert plain.confidence is not MatchConfidence.NONE


def test_a_salvaged_title_may_not_cross_a_version():
    # The salvage strips a version marker along with the decoration around it — 不谓侠
    # (DJ版) is salvaged as 不谓侠 — so the rescue was handing a DJ cut the studio
    # recording's words. A DJ or live cut often does not even share them.
    catalogue = [
        Candidate("1", "不谓侠", "萧忆情Alex", None),
        Candidate("2", "不谓侠 (DJ版)", "DJ Wave", None),
        Candidate("3", "不谓侠(女声版)", "慵狐", None),
    ]

    for reported, expected in [
        ("不谓侠", ["不谓侠"]),
        ("不谓侠 (DJ版)", ["不谓侠 (DJ版)"]),
        ("不谓侠(女声版)", ["不谓侠(女声版)"]),
    ]:
        got = ranked_matches(catalogue, TrackMetadata(reported, "", "", None), fuzzy=True)
        assert [m.candidate.title for m in got] == expected, f"{reported!r} accepted {got}"


def test_every_outcome_names_the_rule_that_produced_it():
    # "No lyrics" reads the same whether the catalogue has never heard of the song,
    # holds only a re-cut of it, or holds it under a name the search never reached —
    # and those want opposite fixes.
    track = TrackMetadata("不谓侠", "", "", 259.0)

    refused = evaluate_match(Candidate("1", "不谓侠(女声版)", "慵狐", 266.0), track, fuzzy=True)
    unrelated = evaluate_match(Candidate("2", "Forever", "A Band", 200.0),
                               TrackMetadata("Forever", "Another Band", "", 200.0), fuzzy=True)
    accepted = evaluate_match(Candidate("3", "告白氣球", "周杰倫", 200.0),
                              TrackMetadata("告白氣球", "周杰倫", "", 200.0), fuzzy=True)

    assert refused.reason == "version-conflict"
    assert unrelated.reason == "no-artist-overlap"
    assert accepted.confidence is MatchConfidence.HIGH
    assert accepted.reason and accepted.reason not in {"version-conflict", "no-artist-overlap"}


def test_the_refusal_that_dominates_is_the_one_reported():
    # One example is not a diagnosis: the reason that accounts for most of the
    # refusals is what points at the fix, and the closest title shows what was near.
    track = TrackMetadata("不谓侠", "", "", 259.0)
    candidates = [
        Candidate("1", "不谓侠(女声版)", "慵狐", 266.0),
        Candidate("2", "不谓侠 (DJ版)", "DJ Wave", 260.0),
        Candidate("3", "something else", "someone", 200.0),
    ]

    summary = nearest_miss(candidates, track, fuzzy=True)

    assert summary.startswith("version-conflict (2 of 3")
    assert "不谓侠" in summary


def test_a_lookup_with_no_candidates_says_so():
    assert nearest_miss([], TrackMetadata("x", "y", "", None)) == "nothing came back"
