from kotonoha.providers.mpris import _unwrap, parse_metadata


def test_parse_basic():
    info = parse_metadata(
        {
            "xesam:title": "Bloom",
            "xesam:artist": ["Radwimps"],
            "xesam:album": "Your Name",
            "mpris:length": 215_000_000,
            "mpris:trackid": "/track/1",
        }
    )
    assert info.title == "Bloom"
    assert info.artist == "Radwimps"
    assert info.album == "Your Name"
    assert info.length_s == 215.0
    assert info.track_id == "/track/1"


def test_parse_multiple_artists_joined():
    assert parse_metadata({"xesam:artist": ["A", "B"]}).artist == "A / B"


def test_parse_artist_as_plain_string():
    assert parse_metadata({"xesam:artist": "Solo"}).artist == "Solo"


def test_parse_missing_fields():
    info = parse_metadata({"xesam:title": "T"})
    assert info.title == "T"
    assert info.artist == ""
    assert info.album == ""
    assert info.length_s is None
    assert info.track_id == ""


def test_parse_length_bool_rejected():
    assert parse_metadata({"mpris:length": True}).length_s is None


def test_unwrap_variants():
    class FakeVariant:
        def __init__(self, value):
            self.value = value

    raw = {"a": FakeVariant(5), "b": FakeVariant("x")}
    assert _unwrap(raw) == {"a": 5, "b": "x"}
