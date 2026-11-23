"""Small HTTP capability shared by lyric provider implementations."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Protocol

import aiohttp


class LyricsResponseContent(Protocol):
    """Bounded response body reader needed by lyric payload parsers."""

    async def read(self, size: int = -1, /) -> bytes: ...


class LyricsHttpError(RuntimeError):
    """A transport-level HTTP failure normalized for lyric feature callers."""


class LyricsResponse(Protocol):
    """The response facts consumed by provider boundary helpers."""

    @property
    def status(self) -> int: ...

    @property
    def content(self) -> LyricsResponseContent: ...

    def raise_for_status(self) -> None: ...

    async def __aenter__(self) -> LyricsResponse: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
        /,
    ) -> None: ...


class LyricsSession(Protocol):
    """HTTP capability exposed to lyric sources instead of a concrete client."""

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: object | None = None,
    ) -> AbstractAsyncContextManager[LyricsResponse]: ...

    def post(
        self,
        url: str,
        *,
        json: object | None = None,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: object | None = None,
    ) -> AbstractAsyncContextManager[LyricsResponse]: ...

    async def close(self) -> None: ...


class AioHttpLyricsSession:
    """Adapt one aiohttp session to the toolkit-neutral lyric HTTP port."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: object | None = None,
    ) -> AbstractAsyncContextManager[LyricsResponse]:
        """Forward a validated request to aiohttp."""
        try:
            response = self._session.get(
                url,
                params=params,
                headers=headers,
                timeout=_aiohttp_timeout(timeout),
            )
        except aiohttp.ClientError as exc:
            raise LyricsHttpError("lyric HTTP GET request failed") from exc
        return _AioHttpResponse(response)

    def post(
        self,
        url: str,
        *,
        json: object | None = None,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: object | None = None,
    ) -> AbstractAsyncContextManager[LyricsResponse]:
        """Forward a validated request to aiohttp."""
        try:
            response = self._session.post(
                url,
                json=json,
                params=params,
                headers=headers,
                timeout=_aiohttp_timeout(timeout),
            )
        except aiohttp.ClientError as exc:
            raise LyricsHttpError("lyric HTTP POST request failed") from exc
        return _AioHttpResponse(response)

    async def close(self) -> None:
        """Close the wrapped client session."""
        await self._session.close()


class _AioHttpContent:
    """Normalize body-read failures from one aiohttp response."""

    def __init__(self, content: aiohttp.StreamReader) -> None:
        self._content = content

    async def read(self, size: int = -1, /) -> bytes:
        try:
            return await self._content.read(size)
        except aiohttp.ClientError as exc:
            raise LyricsHttpError("lyric HTTP response read failed") from exc


class _AioHttpResponse:
    """Adapt one aiohttp response context manager to the lyric response port."""

    def __init__(self, response: AbstractAsyncContextManager[aiohttp.ClientResponse]) -> None:
        self._response = response
        self._entered: aiohttp.ClientResponse | None = None

    @property
    def status(self) -> int:
        """Return the response status after the request has entered."""
        response = self._entered
        if response is None:
            raise RuntimeError("lyric HTTP response was read before entering its context")
        return response.status

    @property
    def content(self) -> LyricsResponseContent:
        """Return the normalized bounded response body reader."""
        response = self._entered
        if response is None:
            raise RuntimeError("lyric HTTP response was read before entering its context")
        return _AioHttpContent(response.content)

    def raise_for_status(self) -> None:
        """Turn aiohttp response errors into the feature-neutral transport error."""
        response = self._entered
        if response is None:
            raise RuntimeError("lyric HTTP response was checked before entering its context")
        try:
            response.raise_for_status()
        except aiohttp.ClientError as exc:
            raise LyricsHttpError("lyric HTTP response returned an error") from exc

    async def __aenter__(self) -> LyricsResponse:
        """Enter the response and normalize connection failures."""
        try:
            self._entered = await self._response.__aenter__()
        except aiohttp.ClientError as exc:
            raise LyricsHttpError("lyric HTTP request could not be opened") from exc
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
        /,
    ) -> None:
        """Release the response while preserving the normalized error boundary."""
        try:
            await self._response.__aexit__(exc_type, exc_value, traceback)
        except aiohttp.ClientError as exc:
            raise LyricsHttpError("lyric HTTP response could not be released") from exc


def new_lyrics_session() -> AioHttpLyricsSession:
    """Create the bounded, cookie-isolated session shared by lyric workflows."""
    return AioHttpLyricsSession(
        aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20.0, connect=5.0, sock_connect=5.0),
            cookie_jar=aiohttp.DummyCookieJar(),
        )
    )


def _aiohttp_timeout(value: object | None) -> aiohttp.ClientTimeout | None:
    """Accept only timeout values supported by the concrete HTTP adapter."""
    if value is None or isinstance(value, aiohttp.ClientTimeout):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        total = float(value)
        return aiohttp.ClientTimeout(total=total, sock_connect=min(5.0, total))
    raise TypeError("unsupported lyric HTTP timeout")


__all__ = [
    "AioHttpLyricsSession",
    "LyricsHttpError",
    "LyricsResponse",
    "LyricsResponseContent",
    "LyricsSession",
    "new_lyrics_session",
]
