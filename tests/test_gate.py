from kotonoha.config import Config
from kotonoha.providers.gate import SourceGate


def test_gate_default_accepts_ws():
    # With no external source consulted (e.g. dbus down), Cider keeps working.
    assert SourceGate().accept_ws is True


def test_gate_set():
    gate = SourceGate()
    gate.set_accept_ws(False)
    assert gate.accept_ws is False
    gate.set_accept_ws(True)
    assert gate.accept_ws is True


def test_lyrics_sources_default():
    assert Config().lyrics_sources == ["netease", "lrclib", "cider"]


def test_lyrics_sources_cleaned():
    cfg = Config(lyrics_sources=["cider", "bogus", "netease", "netease"]).clamped()
    assert cfg.lyrics_sources == ["cider", "netease"]  # unknown dropped, deduped, order kept


def test_lyrics_sources_empty_falls_back():
    assert Config(lyrics_sources=[]).clamped().lyrics_sources == ["netease", "lrclib", "cider"]
    assert Config(lyrics_sources=["nope"]).clamped().lyrics_sources == ["netease", "lrclib", "cider"]


def test_lyrics_sources_roundtrip():
    cfg = Config.from_dict({"lyrics_sources": ["lrclib", "netease"]})
    assert cfg.lyrics_sources == ["lrclib", "netease"]
