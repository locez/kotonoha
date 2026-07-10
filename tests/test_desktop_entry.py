from configparser import ConfigParser
from pathlib import Path

DESKTOP_ENTRY_PATH = Path(__file__).parents[1] / "packaging" / "kotonoha.desktop"


class CaseSensitiveConfigParser(ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr


def load_desktop_entry() -> ConfigParser:
    parser = CaseSensitiveConfigParser(interpolation=None)
    with DESKTOP_ENTRY_PATH.open(encoding="utf-8") as desktop_entry:
        parser.read_file(desktop_entry)
    return parser


def test_desktop_entry_has_required_commands_and_localizations() -> None:
    desktop_entry = load_desktop_entry()["Desktop Entry"]

    assert desktop_entry["Type"] == "Application"
    assert desktop_entry["Exec"] == "kotonoha"
    assert desktop_entry["Icon"] == "kotonoha"
    assert desktop_entry["Terminal"] == "false"
    assert desktop_entry["Categories"] == "AudioVideo;Audio;Utility;"

    expected_localized_values = {
        "Name": "Kotonoha",
        "Name[zh_CN]": "Kotonoha 歌词 HUD",
        "Name[zh_TW]": "Kotonoha 歌詞 HUD",
        "Name[ja]": "Kotonoha 歌詞 HUD",
        "GenericName": "Lyrics Overlay",
        "GenericName[zh_CN]": "桌面歌词悬浮窗",
        "GenericName[zh_TW]": "桌面歌詞懸浮視窗",
        "GenericName[ja]": "デスクトップ歌詞オーバーレイ",
        "Comment": "Show synchronized lyrics for the current track",
        "Comment[zh_CN]": "显示当前歌曲的同步歌词",
        "Comment[zh_TW]": "顯示目前歌曲的同步歌詞",
        "Comment[ja]": "再生中の曲の同期歌詞を表示",
        "Keywords": "lyrics;music;overlay;karaoke;",
        "Keywords[zh_CN]": "歌词;音乐;悬浮窗;卡拉OK;",
        "Keywords[zh_TW]": "歌詞;音樂;懸浮視窗;卡拉OK;",
        "Keywords[ja]": "歌詞;音楽;オーバーレイ;カラオケ;",
    }
    assert {key: desktop_entry[key] for key in expected_localized_values} == expected_localized_values
    assert desktop_entry["Categories"].endswith(";")
    assert all(desktop_entry[key].endswith(";") for key in expected_localized_values if key.startswith("Keywords"))
