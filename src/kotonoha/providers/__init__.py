"""Player providers (data sources) for Kotonoha.

Each provider feeds the shared ``LyricsState`` (snapshot + tick). The Cider probe
is an external WebSocket client (see receiver.py); MPRIS is an in-process D-Bus
provider for any standard Linux media player.
"""
