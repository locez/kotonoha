"""Reads of the session bus, against a bus that answers the way real ones do."""

import pytest
from dbus_fast import Variant

from kotonoha.providers.mpris_session import MprisSession


class _Props:
    def __init__(self, identity, detail=None, detail_fails=False):
        self._identity = identity
        self._detail = detail or {}
        self._detail_fails = detail_fails

    async def call_get(self, interface, name):
        assert (interface, name) == ("org.mpris.MediaPlayer2", "Identity")
        return self._identity

    async def call_get_all(self, _interface):
        if self._detail_fails:
            raise RuntimeError("player went away mid-read")
        return self._detail


class _Bus:
    def __init__(self, props):
        self._props = props

    def get_proxy_object(self, _name, _path, _introspection):
        return self

    def get_interface(self, name):
        assert name == "org.freedesktop.DBus.Properties"
        return self._props


async def test_a_single_property_arrives_as_a_variant():
    # One property comes back as a Variant, not the a{sv} map the metadata unwrapper
    # takes, and passing it there made every player show as "{}".
    session = MprisSession(bus=_Bus(_Props(Variant("s", "ElectronNCM"))))

    identity, _status, _info = await session.describe("org.mpris.MediaPlayer2.ElectronNCM")

    assert identity == "ElectronNCM"


async def test_a_failed_detail_read_still_names_the_player():
    # The identity read is what makes a player appear at all; status and metadata are
    # only what the row shows beside it. Sharing one attempt dropped a reachable
    # player from the picker whenever the optional detail failed.
    session = MprisSession(bus=_Bus(_Props(Variant("s", "VLC"), detail_fails=True)))

    identity, status, info = await session.describe("org.mpris.MediaPlayer2.vlc")

    assert identity == "VLC"
    assert status == ""
    assert info.title == "" and info.artist == ""


async def test_an_unreachable_player_is_not_a_player():
    class _Dead:
        def get_proxy_object(self, *_args):
            raise RuntimeError("no such name")

    with pytest.raises(LookupError):
        await MprisSession(bus=_Dead()).describe("org.mpris.MediaPlayer2.gone")


async def test_a_read_that_never_answers_gives_up():
    # A player can own its bus name and simply not reply. There is one poll task, so
    # without a deadline it waits inside that call and every other player stops being
    # looked at too.
    import asyncio

    async def never() -> str:
        await asyncio.sleep(3600)
        return "Playing"

    from kotonoha.providers import mpris_session

    original = mpris_session.DBUS_CALL_TIMEOUT
    mpris_session.DBUS_CALL_TIMEOUT = 0.05
    try:
        assert await MprisSession.ask("status read", never(), "") == ""
    finally:
        mpris_session.DBUS_CALL_TIMEOUT = original


def test_a_property_reads_the_same_wrapped_or_not():
    # The boundary sees both shapes: a single property arrives as a Variant, an a{sv}
    # map arrives already unwrapped, and the same read has to cope with either.
    from kotonoha.providers.mpris_session import plain_value

    assert plain_value(Variant("s", "ElectronNCM")) == "ElectronNCM"
    assert plain_value("ElectronNCM") == "ElectronNCM"
    assert plain_value(None) is None


async def test_the_identity_of_an_unsubscribed_session_is_empty():
    assert await MprisSession().identity() == ""
