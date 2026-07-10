from kotonoha.model import EMPTY_SNAPSHOT, parse_payload


def _word_payload():
    return {
        "source": "kotonoha-cider-lyrics",
        "playback": {
            "isPlaying": True,
            "nowPlayingItem": {"attributes": {"name": "Bloom", "artistName": "Radwimps"}},
        },
        "lyrics": {
            "found": True,
            "provider": "Apple Music",
            "songId": "123",
            "timing": "Word",
            "language": "ja",
            "currentTime": 12.5,
            "currentLine": {
                "index": 4,
                "id": "L4",
                "start": 12.0,
                "end": 15.0,
                "text": "君の名は",
                "translation": "your name",
                "words": [
                    {"start": 12.0, "end": 12.6, "text": "君"},
                    {"start": 12.6, "end": 13.2, "text": "の"},
                ],
            },
            "previousLine": {"index": 3, "id": "L3", "start": 9.0, "end": 12.0, "text": "prev", "translation": ""},
            "nextLine": {"index": 5, "id": "L5", "start": 15.0, "end": 18.0, "text": "next", "translation": ""},
            "aroundLines": [],
        },
    }


def test_parse_full_word_payload():
    snap = parse_payload(_word_payload())
    assert snap.found is True
    assert snap.provider == "Apple Music"
    assert snap.song_id == "123"
    assert snap.timing == "Word"
    assert snap.current_time == 12.5
    assert snap.title == "Bloom"
    assert snap.artist == "Radwimps"
    assert snap.is_playing is True
    assert snap.current is not None
    assert snap.current.text == "君の名は"
    assert snap.current.translation == "your name"
    assert len(snap.current.words) == 2
    assert snap.previous is not None and snap.previous.text == "prev"
    assert snap.next is not None and snap.next.text == "next"


def test_parse_playback_album_and_duration():
    payload = {
        "playback": {
            "currentPlaybackDuration": 194.222,
            "nowPlayingItem": {
                "attributes": {
                    "name": "Song",
                    "artistName": "Artist",
                    "albumName": "Album",
                }
            },
        }
    }

    snap = parse_payload(payload)

    assert snap.album == "Album"
    assert snap.duration_s == 194.222


def test_word_karaoke_true_when_word_timing_present():
    assert parse_payload(_word_payload()).word_karaoke is True


def test_word_karaoke_false_for_line_timing():
    payload = _word_payload()
    payload["lyrics"]["timing"] = "Line"
    assert parse_payload(payload).word_karaoke is False


def test_word_karaoke_false_without_word_times():
    payload = _word_payload()
    for w in payload["lyrics"]["currentLine"]["words"]:
        w["start"] = None
        w["end"] = None
    assert parse_payload(payload).word_karaoke is False


def test_parse_non_dict_returns_empty():
    assert parse_payload(None) is EMPTY_SNAPSHOT
    assert parse_payload("nope") is EMPTY_SNAPSHOT
    assert parse_payload([1, 2, 3]) is EMPTY_SNAPSHOT


def test_parse_missing_lyrics_section_is_safe():
    snap = parse_payload({"playback": {}})
    assert snap.found is False
    assert snap.current is None
    assert snap.around == ()


def test_parse_tolerates_garbage_line_and_word_shapes():
    payload = {
        "lyrics": {
            "found": True,
            "timing": "Word",
            "currentLine": {
                "index": "oops",
                "start": "x",
                "words": ["notadict", {"text": "ok", "start": 1, "end": 2}, 42],
            },
            "aroundLines": ["bad", {"text": "good"}, None],
        }
    }
    snap = parse_payload(payload)
    assert snap.current is not None
    assert snap.current.index == -1  # bad int -> default
    assert snap.current.start == 0.0  # bad float -> 0.0
    assert [w.text for w in snap.current.words] == ["ok"]
    assert [line.text for line in snap.around] == ["good"]


def test_bool_is_not_treated_as_number():
    payload = {"lyrics": {"currentTime": True}}
    assert parse_payload(payload).current_time is None
