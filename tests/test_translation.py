"""Behavior tests for lyrics translation contracts, providers, cache, and service."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

from kotonoha.async_worker import BlockingCallRunner
from kotonoha.config import (
    Config,
    TranslationPolicy,
    TranslationProvider,
    TranslationServiceConfig,
    load_config,
    save_config,
)
from kotonoha.i18n import (
    normalize_translation_language,
    resolve_lyrics_translation_language,
    translation_language_display_name,
)
from kotonoha.lyrics.artifact import LyricsArtifact
from kotonoha.lyrics.cache.models import LyricsCacheMode
from kotonoha.lyrics.cache.storage import LyricsCacheStorage
from kotonoha.lyrics.match import MatchConfidence
from kotonoha.lyrics.models import LyricLine, LyricsDocument, LyricWord, TimingKind
from kotonoha.secrets import SecretAvailability, translation_secret_key
from kotonoha.translation import (
    DEEPL_FREE_URL,
    DEEPL_PRO_URL,
    DeepLTranslator,
    LyricsTranslationService,
    OpenAICompatibleTranslator,
    TranslationCache,
    TranslationCacheDeleteStatus,
    TranslationCacheKey,
    TranslationCacheQuery,
    TranslationCacheStorage,
    TranslationConfig,
    TranslationError,
    TranslationErrorKind,
    TranslationRequest,
    TranslationResult,
    content_hash,
    deduplicate_lines,
    deepl_endpoint_for_key,
    detect_primary_language,
    existing_translation_matches_target,
    looks_like_target_language,
    map_deepl_target_lang,
    match_preset_id,
    reconstruct_lines,
    validate_base_url,
)


@dataclass
class _RecordedPost:
    url: str
    json_body: object
    headers: dict[str, str]
    timeout: object | None


class _FakeContent:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self._offset = 0

    async def read(self, size: int = -1, /) -> bytes:
        if self._offset >= len(self._body):
            return b""
        if size < 0:
            chunk = self._body[self._offset :]
            self._offset = len(self._body)
            return chunk
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class _FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.content = _FakeContent(body)

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class _FakeHttpSession:
    def __init__(self, responses: list[tuple[int, object]]) -> None:
        self._responses = list(responses)
        self.posts: list[_RecordedPost] = []
        self.closed = False

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: object | None = None,
    ):
        del url, params, headers, timeout
        raise AssertionError("GET should not be called by translation providers")

    @asynccontextmanager
    async def post(
        self,
        url: str,
        *,
        json: object | None = None,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: object | None = None,
    ):
        del params
        self.posts.append(_RecordedPost(url, json, dict(headers or {}), timeout))
        status, payload = self._responses.pop(0)
        body = payload if isinstance(payload, bytes) else _json_bytes(payload)
        yield _FakeResponse(status, body)

    async def close(self) -> None:
        self.closed = True


class _InMemorySecrets:
    def __init__(self, values: dict[str, str] | None = None, *, available: bool = True) -> None:
        self.values: dict[str, str] = dict(values or {})
        self.available = available
        self.closed = False

    def start(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def availability(self) -> SecretAvailability:
        return SecretAvailability(self.available, "memory", None if self.available else "no-backend")

    async def get_secret(self, key: str) -> str | None:
        return self.values.get(key)

    async def set_secret(self, key: str, value: str) -> None:
        self.values[key] = value

    async def delete_secret(self, key: str) -> None:
        self.values.pop(key, None)


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _sample_document(*, translation: str = "") -> LyricsDocument:
    return LyricsDocument(
        source_id="amll",
        song_id="song-1",
        timing=TimingKind.WORD,
        title="Sample Song",
        artist="Sample Artist",
        duration_s=180.0,
        lines=(
            LyricLine(
                0,
                "L0",
                0.0,
                3.0,
                "Hello world",
                translation,
                (LyricWord(0.0, 1.5, "Hello "), LyricWord(1.5, 3.0, "world")),
            ),
            LyricLine(1, "L1", 3.0, 5.0, "   ", "", ()),
            LyricLine(2, "L2", 5.0, 8.0, "Hello world", translation, ()),
        ),
    )


def test_translation_language_normalization_preserves_regional_variants() -> None:
    assert normalize_translation_language("pt_PT.UTF-8") == "pt-PT"
    assert normalize_translation_language("pt-BR") == "pt-BR"
    assert normalize_translation_language("zh_TW") == "zh-Hant"
    assert normalize_translation_language("zh_CN") == "zh-Hans"
    assert normalize_translation_language("en_GB") == "en-GB"
    assert normalize_translation_language("bad tag!") == "en"
    assert resolve_lyrics_translation_language("auto", locale_name="pt_PT") == "pt-PT"
    assert resolve_lyrics_translation_language("pt-PT", locale_name="zh_CN") == "pt-PT"
    assert translation_language_display_name("pt-PT") == "Português (Portugal)"
    assert translation_language_display_name("zh-Hans") == "简体中文"
    assert translation_language_display_name("en") == "English"


def test_deduplicate_and_reconstruct_preserves_blank_lines_and_repeats() -> None:
    lines = ("Chorus line", "", "Verse line", "Chorus line", "   ")
    unique, mapping = deduplicate_lines(lines)

    assert unique == ("Chorus line", "Verse line")
    assert mapping == (0, None, 1, 0, None)
    assert reconstruct_lines(("Refrão", "Verso"), mapping) == ("Refrão", "", "Verso", "Refrão", "")


def test_same_language_detection_handles_mixed_cjk_and_latin_languages() -> None:
    # Chinese pop with English phrases and a decorative の must still count as Chinese.
    cpop = ("Baby 你是我的唯一", "Oh yeah 每天都在想你", "最美の瞬间留在这里")
    assert looks_like_target_language(cpop, "zh-Hans") is True
    assert looks_like_target_language(cpop, "ja") is False
    assert looks_like_target_language(cpop, "en") is False

    # Japanese pop with English hook counts as Japanese, never Chinese.
    jpop = ("Baby 君の声を聴かせて", "Tonight 星空の下で踊ろう", "いつもここにいるよ")
    assert looks_like_target_language(jpop, "ja") is True
    assert looks_like_target_language(jpop, "zh-Hans") is False

    # Korean pop with English hook counts as Korean.
    kpop = ("Baby 너와 함께 걷고 싶어", "Oh yeah 이 밤이 지나가면")
    assert looks_like_target_language(kpop, "ko") is True

    # English song skips when target is English, but translates for Portuguese or Chinese.
    english = (
        "When the night is dark and you are far away from home",
        "I know that we will find our way through all the rain",
    )
    assert looks_like_target_language(english, "en") is True
    assert looks_like_target_language(english, "pt-PT") is False
    assert looks_like_target_language(english, "zh-Hans") is False

    # Portuguese song skips for Portuguese targets, translates for English.
    portuguese = (
        "Quando a noite cai eu não consigo esquecer você",
        "Com tudo o que eu tenho para te dizer agora",
    )
    assert looks_like_target_language(portuguese, "pt-PT") is True
    assert looks_like_target_language(portuguese, "en") is False

    # Chinese song with heavy bilingual English credits (like Netease/AMLL C-pop) must still detect as Chinese.
    cpop_with_credits = (
        "小小奇迹 - 鸣潮先约电台/jixwang/飞行雪绒",
        "词 Lyricist: Xulai",
        "曲 Composer: jixwang",
        "编曲 Arranger: jixwang",
        "演唱 Vocal: 飞行雪绒",
        "和声编写 Voicing Arrangement: jixwang",
        "混音 Mixing Engineer: Mitsunori Aizawa",
        "乐器独奏 Instrument Solo: Guitar: 愤怒的糖",
        "飞行雪绒粉丝合音团 Fleet Snowfluff Choir Club: jixwang",
        "录音棚 Studio: 无音区杜比全景声棚",
        "录音师 Recording Engineer: Koimoon",
        "微风轻轻吹过你的脸庞",
        "每个瞬间都闪耀着微光",
        "让我们一起走向远方",
        "把小小奇迹留在心上",
    )
    assert looks_like_target_language(cpop_with_credits, "zh-Hans") is True
    assert looks_like_target_language(cpop_with_credits, "en") is False

    # English song with a couple of Chinese credit lines must NOT be mistaken for Chinese.
    english_with_zh_credits = (
        "作词：John Doe",
        "作曲：Jane Doe",
        "When the night is dark and you are far away from home",
        "I know that we will find our way through all the rain",
        "Hold my hand and never let the morning fade away",
        "Every step we take is leading back to where we stay",
    )
    assert looks_like_target_language(english_with_zh_credits, "zh-Hans") is False
    assert looks_like_target_language(english_with_zh_credits, "en") is True

    # Explicit document language tag skips even on short ambiguous lyrics.
    assert looks_like_target_language(("La la",), "zh-Hans", document_language="zh-CN") is True
    # pt-BR document must NOT skip when target is pt-PT.
    assert looks_like_target_language(("La la",), "pt-PT", document_language="pt-BR") is False

    # Simplified vs Traditional Chinese script detection distinguishes zh-Hans and zh-Hant.
    hans_lines = ("让我听见你的声音", "我一直都在这里", "微风轻轻吹过你的脸庞")
    hant_lines = ("讓我聽見你的聲音", "我一直都在這裡", "微風輕輕吹過你的臉龐")
    neutral_zh = ("我在天上看月光", "你在山海看星火")
    assert detect_primary_language(hans_lines) == "zh-Hans"
    assert detect_primary_language(hant_lines) == "zh-Hant"
    assert detect_primary_language(neutral_zh) == "zh"
    assert existing_translation_matches_target(hans_lines, "zh-Hans") is True
    assert existing_translation_matches_target(hans_lines, "zh-Hant") is False
    assert existing_translation_matches_target(hant_lines, "zh-Hant") is True
    assert existing_translation_matches_target(hant_lines, "zh-Hans") is False
    assert existing_translation_matches_target(neutral_zh, "zh-Hans") is True
    assert existing_translation_matches_target(neutral_zh, "zh-Hant") is True


def test_base_url_validation_allows_https_and_loopback_only() -> None:
    assert validate_base_url("https://api.deepseek.com/v1/") == "https://api.deepseek.com/v1"
    assert validate_base_url("http://localhost:11434/v1/") == "http://localhost:11434/v1"
    assert match_preset_id("https://generativelanguage.googleapis.com/v1beta/openai/") == "gemini"
    assert match_preset_id("https://custom.example/v1") == "custom"

    for invalid in (
        "",
        "http://api.example.com/v1",
        "https://user:pass@api.example.com/v1",
        "https://api.example.com/v1?key=secret",
    ):
        with pytest.raises(TranslationError) as exc_info:
            validate_base_url(invalid)
        assert exc_info.value.kind is TranslationErrorKind.CONFIG


async def test_deepl_routes_free_and_pro_keys_and_chunks_over_50_lines() -> None:
    assert deepl_endpoint_for_key("abc:fx") == DEEPL_FREE_URL
    assert deepl_endpoint_for_key("abc-pro") == DEEPL_PRO_URL
    assert map_deepl_target_lang("pt-PT") == "PT-PT"
    assert map_deepl_target_lang("pt-BR") == "PT-BR"
    assert map_deepl_target_lang("zh-Hans") == "ZH-HANS"

    lines = tuple(f"Line {index}" for index in range(55))
    session = _FakeHttpSession(
        [
            (200, {"translations": [{"text": f"Linha {i}"} for i in range(50)]}),
            (200, {"translations": [{"text": f"Linha {i}"} for i in range(50, 55)]}),
        ]
    )
    translator = DeepLTranslator(session)

    result = await translator.translate(
        TranslationRequest(lines=lines, target_language="pt-PT", title="Song", artist="Artist"),
        api_key="my-free-key:fx",
    )

    assert len(session.posts) == 2
    assert all(post.url == DEEPL_FREE_URL for post in session.posts)
    assert session.posts[0].headers["Authorization"] == "DeepL-Auth-Key my-free-key:fx"
    assert result.model == "deepl-free"
    assert len(result.translations) == 55
    assert result.translations[0] == "Linha 0"
    assert result.translations[54] == "Linha 54"


async def test_deepl_maps_auth_rate_limit_and_mismatched_counts() -> None:
    for status, expected_kind in ((403, TranslationErrorKind.AUTH), (456, TranslationErrorKind.RATE_LIMIT)):
        session = _FakeHttpSession([(status, {"message": f"detail {status}"})])
        with pytest.raises(TranslationError) as exc_info:
            await DeepLTranslator(session, transient_retry_delay_s=0.0).translate(
                TranslationRequest(lines=("Hello",), target_language="pt-PT"),
                api_key="key:fx",
            )
        assert exc_info.value.kind is expected_kind
        assert f"detail {status}" in str(exc_info.value)

    # Transient HTTP 503 retries once automatically and succeeds on recovery.
    flaky_session = _FakeHttpSession(
        [
            (503, {"message": "Temporarily unavailable"}),
            (200, {"translations": [{"text": "Olá"}]}),
        ]
    )
    recovered = await DeepLTranslator(flaky_session, transient_retry_delay_s=0.0).translate(
        TranslationRequest(lines=("Hello",), target_language="pt-PT"),
        api_key="key:fx",
    )
    assert len(flaky_session.posts) == 2
    assert recovered.translations == ("Olá",)

    mismatch_session = _FakeHttpSession([(200, {"translations": [{"text": "Only one"}]})])
    with pytest.raises(TranslationError) as exc_info:
        await DeepLTranslator(mismatch_session, transient_retry_delay_s=0.0).translate(
            TranslationRequest(lines=("One", "Two"), target_language="pt-PT"),
            api_key="key:fx",
        )
    assert exc_info.value.kind is TranslationErrorKind.INVALID_RESPONSE


async def test_openai_compatible_parses_fenced_json_and_retries_without_response_format() -> None:
    session = _FakeHttpSession(
        [
            (400, {"error": {"message": "response_format unsupported"}}),
            (
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": '```json\n{"translations": {"0": "Olá mundo", "1": "Boa noite"}}\n```'
                            }
                        }
                    ]
                },
            ),
        ]
    )
    translator = OpenAICompatibleTranslator(
        session,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        model="gemini-3.5-flash-lite",
        style_prompt="Use concise poetic European Portuguese.",
    )

    result = await translator.translate(
        TranslationRequest(lines=("Hello world", "Good night"), target_language="pt-PT", title="Test"),
        api_key="gemini-key",
    )

    assert len(session.posts) == 2
    assert session.posts[0].url == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert isinstance(session.posts[0].json_body, Mapping)
    assert isinstance(session.posts[1].json_body, Mapping)
    assert "response_format" in session.posts[0].json_body
    assert "response_format" not in session.posts[1].json_body
    messages = session.posts[0].json_body["messages"]
    assert isinstance(messages, list)
    assert "Use concise poetic European Portuguese." in messages[0]["content"]
    assert '"translations"' in messages[0]["content"]
    assert result.translations == ("Olá mundo", "Boa noite")


async def test_openai_compatible_retries_503_once_and_surfaces_upstream_error_detail() -> None:
    # Single transient 503 recovers on retry.
    recovering_session = _FakeHttpSession(
        [
            (503, [{"error": {"code": 503, "message": "Model overloaded"}}]),
            (200, {"choices": [{"message": {"content": '{"translations": {"0": "Olá"}}'}}]}),
        ]
    )
    recovering = OpenAICompatibleTranslator(
        recovering_session,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        model="gemini-3.5-flash-lite",
        transient_retry_delay_s=0.0,
    )
    result = await recovering.translate(TranslationRequest(lines=("Hello",), target_language="pt-PT"), api_key="k")
    assert len(recovering_session.posts) == 2
    assert result.translations == ("Olá",)

    # Repeated 503 surfaces the truncated upstream Gemini error message in TranslationError.
    failing_session = _FakeHttpSession(
        [
            (503, [{"error": {"code": 503, "message": "The model is currently experiencing high demand"}}]),
            (503, [{"error": {"code": 503, "message": "The model is currently experiencing high demand"}}]),
        ]
    )
    failing = OpenAICompatibleTranslator(
        failing_session,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        model="gemini-3.5-flash-lite",
        transient_retry_delay_s=0.0,
    )
    with pytest.raises(TranslationError) as exc_info:
        await failing.translate(TranslationRequest(lines=("Hello",), target_language="pt-PT"), api_key="k")
    assert len(failing_session.posts) == 2
    assert exc_info.value.kind is TranslationErrorKind.NETWORK
    assert exc_info.value.retryable is True
    assert "high demand" in str(exc_info.value)


def test_translation_timeouts_enforce_fast_connect_and_fallback_budget() -> None:
    from kotonoha.lyrics.http import _aiohttp_timeout
    from kotonoha.translation.deepl import DEFAULT_DEEPL_TIMEOUT_S
    from kotonoha.translation.openai_compatible import DEFAULT_OPENAI_TIMEOUT_S, FALLBACK_OPENAI_TIMEOUT_S
    from kotonoha.translation.service import default_translator_factory

    normal_timeout = _aiohttp_timeout(15.0)
    assert normal_timeout is not None
    assert normal_timeout.total == 15.0
    assert normal_timeout.sock_connect == 5.0

    short_timeout = _aiohttp_timeout(2.0)
    assert short_timeout is not None
    assert short_timeout.sock_connect == 2.0

    session = _FakeHttpSession([])
    openai_svc = TranslationServiceConfig(
        id="gemini",
        name="Gemini",
        provider=TranslationProvider.OPENAI_COMPATIBLE,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        model="gemini-3.5-flash-lite",
    )
    deepl_svc = TranslationServiceConfig(id="deepl", name="DeepL", provider=TranslationProvider.DEEPL)

    with_fallback = default_translator_factory(session, openai_svc, "", has_fallback=True)
    sole_service = default_translator_factory(session, openai_svc, "", has_fallback=False)
    deepl_translator = default_translator_factory(session, deepl_svc, "", has_fallback=False)
    assert isinstance(with_fallback, OpenAICompatibleTranslator)
    assert isinstance(sole_service, OpenAICompatibleTranslator)
    assert isinstance(deepl_translator, DeepLTranslator)
    assert with_fallback.timeout_s == FALLBACK_OPENAI_TIMEOUT_S == 15.0
    assert sole_service.timeout_s == DEFAULT_OPENAI_TIMEOUT_S == 25.0
    assert deepl_translator.timeout_s == DEFAULT_DEEPL_TIMEOUT_S == 15.0


async def test_openai_compatible_allows_keyless_localhost_and_rejects_incomplete_output() -> None:
    local_session = _FakeHttpSession(
        [(200, {"choices": [{"message": {"content": '{"translations": {"0": "Olá"}}'}}]})]
    )
    local = OpenAICompatibleTranslator(local_session, base_url="http://localhost:11434/v1", model="gemma3")
    result = await local.translate(TranslationRequest(lines=("Hello",), target_language="pt-PT"), api_key="")
    assert result.translations == ("Olá",)
    assert "Authorization" not in local_session.posts[0].headers

    remote = OpenAICompatibleTranslator(
        _FakeHttpSession([]),
        base_url="https://api.deepseek.com/v1",
        model="deepseek-flash",
    )
    with pytest.raises(TranslationError) as auth_exc:
        await remote.translate(TranslationRequest(lines=("Hello",), target_language="pt-PT"), api_key="")
    assert auth_exc.value.kind is TranslationErrorKind.AUTH

    incomplete_session = _FakeHttpSession(
        [(200, {"choices": [{"message": {"content": '{"translations": {"0": "Olá"}}'}}]})]
    )
    incomplete = OpenAICompatibleTranslator(
        incomplete_session,
        base_url="http://localhost:11434/v1",
        model="gemma3",
    )
    with pytest.raises(TranslationError) as bad_exc:
        await incomplete.translate(
            TranslationRequest(lines=("Hello", "World"), target_language="pt-PT"),
            api_key="",
        )
    assert bad_exc.value.kind is TranslationErrorKind.INVALID_RESPONSE


def test_translation_cache_is_content_addressed_prunes_lru_and_preserves_lyrics_table(tmp_path: Path) -> None:
    db_path = tmp_path / "lyrics.sqlite3"
    lyrics_storage = LyricsCacheStorage(db_path, max_entries=10)
    assert lyrics_storage.count() == 0

    storage = TranslationCacheStorage(db_path, max_entries=2)
    h1 = content_hash(("Hello", "World"))
    h2 = content_hash(("Hello", "World!"))
    h3 = content_hash(("Another", "Song"))

    # Legacy row without source_lines/timestamps automatically backfills on cache hit.
    storage.store(h1, "pt-PT", ("Olá", "Mundo"), provider="deepl", model="deepl-free")
    record_before = storage.get_record(TranslationCacheKey(h1, "pt-PT"))
    assert record_before is not None
    assert record_before.source_lines == ()
    assert record_before.timestamps == ()
    storage.store(h1, "en", ("Hello", "World"), provider="deepl", model="deepl-free")
    assert storage.lookup(h1, "pt-PT", 2, ("Hello", "World"), (1.25, 4.5)) == TranslationResult(
        translations=("Olá", "Mundo"), provider="deepl", model="deepl-free", from_cache=True
    )
    record_after = storage.get_record(TranslationCacheKey(h1, "pt-PT"))
    assert record_after is not None
    assert record_after.source_lines == ("Hello", "World")
    assert record_after.timestamps == (1.25, 4.5)
    assert storage.lookup(h2, "pt-PT", 2) is None  # changed lyrics must never reuse old translation

    # Corrupt row is automatically deleted rather than crashing callers.
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE lyric_translations SET translations_json = '{bad' WHERE content_hash = ? AND target_lang = ?",
            (h1, "en"),
        )
    assert storage.lookup(h1, "en", 2) is None

    # LRU eviction keeps newest two entries.
    storage.store(
        h2, "pt-PT", ("Olá", "Mundo!"), provider="deepl", model="deepl-free", title="Song B", artist="Artist B"
    )
    storage.store(
        h3,
        "pt-PT",
        ("Outra", "Canção"),
        provider="openai-compatible",
        model="gemini-3.5-flash-lite",
        source_lines=("Another", "Song"),
        title="Song C",
        artist="Artist C",
    )
    assert storage.count() == 2

    found = storage.search(TranslationCacheQuery(keyword="gemini"))
    assert len(found) == 1
    assert found[0].title == "Song C"
    assert found[0].key == TranslationCacheKey(h3, "pt-PT")

    record = storage.get_record(TranslationCacheKey(h3, "pt-PT"))
    assert record is not None
    assert record.source_lines == ("Another", "Song")
    assert record.translations == ("Outra", "Canção")

    assert storage.update_translations(TranslationCacheKey(h3, "pt-PT"), ("Outra linha", "Música")) is True
    assert storage.lookup(h3, "pt-PT", 2) == TranslationResult(
        translations=("Outra linha", "Música"),
        provider="openai-compatible",
        model="gemini-3.5-flash-lite",
        from_cache=True,
    )
    with pytest.raises(ValueError, match="expected 2"):
        storage.update_translations(TranslationCacheKey(h3, "pt-PT"), ("Only one",))

    deleted = storage.delete_many((TranslationCacheKey(h3, "pt-PT"), TranslationCacheKey("missing", "pt-PT")))
    assert deleted[0].status is TranslationCacheDeleteStatus.DELETED
    assert deleted[1].status is TranslationCacheDeleteStatus.NOT_FOUND
    assert storage.count() == 1

    storage.clear()
    assert storage.count() == 0


def test_translation_cache_recovers_legacy_sources_and_timestamps_from_sibling_lyrics_table(tmp_path: Path) -> None:
    db_path = tmp_path / "lyrics.sqlite3"
    lyrics_storage = LyricsCacheStorage(db_path, max_entries=10)
    parsed_lines = (
        LyricLine(0, "L0", 0.5, 3.0, "Hello", ""),
        LyricLine(1, "L1", 3.25, 6.0, "World", ""),
    )
    lyrics_storage.upsert(
        LyricsArtifact(
            provider="lrclib",
            provider_song_id="100",
            title="Song A",
            artist="Artist A",
            album="",
            duration_s=10.0,
            payload={"lrc": "[00:00.50]Hello\n[00:03.25]World"},
            lines=parsed_lines,
            confidence=MatchConfidence.HIGH,
        ),
        LyricsCacheMode.AUTO,
    )

    digest = content_hash(("Hello", "World"))
    storage = TranslationCacheStorage(
        db_path,
        max_entries=10,
        lyrics_parsers={"lrclib": lambda _payload: parsed_lines},
    )
    storage.store(digest, "pt-PT", ("Olá", "Mundo"), provider="deepl", model="deepl-free", title="Song A")

    recovered = storage.get_record(TranslationCacheKey(digest, "pt-PT"))
    assert recovered is not None
    assert recovered.source_lines == ("Hello", "World")
    assert recovered.timestamps == (0.5, 3.25)


async def test_service_caches_deduplicates_inflight_and_preserves_word_timing(tmp_path: Path) -> None:
    worker = BlockingCallRunner("test-translation-cache")
    cache = TranslationCache(tmp_path / "lyrics.sqlite3", worker=worker)
    secrets = _InMemorySecrets({translation_secret_key("deepl"): "secret:fx"})
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    class _CountingTranslator:
        async def translate(self, request: TranslationRequest, *, api_key: str) -> TranslationResult:
            nonlocal calls
            assert api_key == "secret:fx"
            calls += 1
            started.set()
            await release.wait()
            return TranslationResult(
                translations=tuple(f"PT:{line}" for line in request.lines),
                provider="deepl",
                model="deepl-free",
            )

    service = LyricsTranslationService(
        config=TranslationConfig(
            policy=TranslationPolicy.REPLACE,
            target_language="pt-PT",
            services=(
                TranslationServiceConfig(
                    id="deepl",
                    name="DeepL API",
                    provider=TranslationProvider.DEEPL,
                    enabled=True,
                ),
            ),
            cache_enabled=True,
        ),
        cache=cache,
        secrets=secrets,
        session_factory=lambda: _FakeHttpSession([]),
        translator_factory=lambda _session, _svc, _prompt, _fb: _CountingTranslator(),
    )
    await service.start()
    try:
        doc = _sample_document(translation="你好世界")
        first_task = asyncio.create_task(service.translate_document(doc))
        second_task = asyncio.create_task(service.translate_document(doc))
        await asyncio.wait_for(started.wait(), timeout=1.0)
        release.set()
        first, second = await asyncio.gather(first_task, second_task)

        assert calls == 1  # shared in-flight request prevented double API call
        assert first is not None and second is not None
        assert tuple(line.translation for line in first.lines) == ("PT:Hello world", "", "PT:Hello world")
        assert first.lines[0].words == doc.lines[0].words  # word timing intact

        # Third call hits SQLite cache without invoking the translator again.
        cached = await service.translate_document(doc)
        assert cached is not None
        assert calls == 1
        assert tuple(line.translation for line in cached.lines) == ("PT:Hello world", "", "PT:Hello world")
    finally:
        await service.stop()
        cache.close()


async def test_service_falls_back_in_priority_order_with_per_service_cooldown(tmp_path: Path) -> None:
    worker = BlockingCallRunner("test-translation-fallback")
    cache = TranslationCache(tmp_path / "lyrics.sqlite3", worker=worker)
    secrets = _InMemorySecrets(
        {
            translation_secret_key("gemini"): "gem-key",
            translation_secret_key("deepl"): "deepl-key:fx",
        }
    )
    now = 100.0
    gemini_down = True
    attempts: list[str] = []

    class _RoutingTranslator:
        def __init__(self, service_id: str) -> None:
            self._service_id = service_id

        async def translate(self, request: TranslationRequest, *, api_key: str) -> TranslationResult:
            attempts.append(self._service_id)
            if self._service_id == "gemini":
                assert api_key == "gem-key"
                if gemini_down:
                    raise TranslationError(
                        "Translation API server error (HTTP 503: high demand)",
                        kind=TranslationErrorKind.NETWORK,
                        retryable=True,
                    )
                return TranslationResult(
                    translations=tuple(f"GEM:{line}" for line in request.lines),
                    provider="openai-compatible",
                    model="gemini-3.5-flash-lite",
                )
            assert api_key == "deepl-key:fx"
            return TranslationResult(
                translations=tuple(f"DEEPL:{line}" for line in request.lines),
                provider="deepl",
                model="deepl-free",
            )

    service = LyricsTranslationService(
        config=TranslationConfig(
            policy=TranslationPolicy.REPLACE,
            target_language="pt-PT",
            services=(
                TranslationServiceConfig(
                    id="gemini",
                    name="Gemini",
                    provider=TranslationProvider.OPENAI_COMPATIBLE,
                    enabled=True,
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                    model="gemini-3.5-flash-lite",
                ),
                TranslationServiceConfig(
                    id="deepl",
                    name="DeepL",
                    provider=TranslationProvider.DEEPL,
                    enabled=True,
                ),
            ),
            cache_enabled=True,
        ),
        cache=cache,
        secrets=secrets,
        session_factory=lambda: _FakeHttpSession([]),
        translator_factory=lambda _session, svc, _prompt, _fb: _RoutingTranslator(svc.id),
        negative_ttl_s=60.0,
        clock=lambda: now,
    )
    await service.start()
    try:
        # Song 1: Gemini 503 -> falls back immediately to DeepL.
        doc1 = LyricsDocument(
            "amll",
            song_id="s1",
            timing=TimingKind.LINE,
            lines=(LyricLine(0, "L0", 0.0, 3.0, "First song line", ""),),
        )
        translated1 = await service.translate_document(doc1)
        assert translated1 is not None
        assert translated1.lines[0].translation == "DEEPL:First song line"
        assert attempts == ["gemini", "deepl"]

        # Song 2 (10s later): Gemini is in per-service cooldown -> skipped immediately (0 calls) -> DeepL directly!
        now = 110.0
        doc2 = LyricsDocument(
            "amll",
            song_id="s2",
            timing=TimingKind.LINE,
            lines=(LyricLine(0, "L0", 0.0, 3.0, "Second song line", ""),),
        )
        translated2 = await service.translate_document(doc2)
        assert translated2 is not None
        assert translated2.lines[0].translation == "DEEPL:Second song line"
        assert attempts == ["gemini", "deepl", "deepl"]

        # Song 3 (after cooldown expires & Gemini recovers): Gemini runs first again and succeeds!
        now = 170.0
        gemini_down = False
        doc3 = LyricsDocument(
            "amll",
            song_id="s3",
            timing=TimingKind.LINE,
            lines=(LyricLine(0, "L0", 0.0, 3.0, "Third song line", ""),),
        )
        translated3 = await service.translate_document(doc3)
        assert translated3 is not None
        assert translated3.lines[0].translation == "GEM:Third song line"
        assert attempts == ["gemini", "deepl", "deepl", "gemini"]
    finally:
        await service.stop()
        cache.close()


async def test_service_respects_missing_only_policy_and_config_roundtrip(tmp_path: Path) -> None:
    worker = BlockingCallRunner("test-translation-policy")
    cache = TranslationCache(tmp_path / "lyrics.sqlite3", worker=worker)
    deepl_only = (
        TranslationServiceConfig(
            id="deepl",
            name="DeepL API",
            provider=TranslationProvider.DEEPL,
            enabled=True,
        ),
    )

    # Target pt-PT with Chinese provider translation: missing-only MUST translate to pt-PT!
    service_pt = LyricsTranslationService(
        config=TranslationConfig(
            policy=TranslationPolicy.MISSING_ONLY,
            target_language="pt-PT",
            services=deepl_only,
        ),
        cache=cache,
        secrets=_InMemorySecrets(),
        session_factory=lambda: _FakeHttpSession([]),
    )
    zh_translated_doc = LyricsDocument(
        source_id="amll",
        song_id="song-jp",
        timing=TimingKind.LINE,
        lines=(
            LyricLine(0, "L0", 0.0, 3.0, "君の声を聴かせて", "让我听见你的声音"),
            LyricLine(1, "L1", 3.0, 6.0, "いつもここにいるよ", "我一直都在这里"),
        ),
    )
    assert service_pt.should_translate(zh_translated_doc) is True

    # Target zh-Hans with Simplified Chinese provider translation: missing-only skips.
    service_zh = LyricsTranslationService(
        config=TranslationConfig(
            policy=TranslationPolicy.MISSING_ONLY,
            target_language="zh-Hans",
            services=deepl_only,
        ),
        cache=cache,
        secrets=_InMemorySecrets(),
        session_factory=lambda: _FakeHttpSession([]),
    )
    assert service_zh.should_translate(zh_translated_doc) is False
    assert service_zh.should_translate(_sample_document(translation="")) is True

    # Target zh-Hant with Simplified Chinese provider translation: missing-only MUST translate to zh-Hant.
    service_zh_hant = LyricsTranslationService(
        config=TranslationConfig(
            policy=TranslationPolicy.MISSING_ONLY,
            target_language="zh-Hant",
            services=deepl_only,
        ),
        cache=cache,
        secrets=_InMemorySecrets(),
        session_factory=lambda: _FakeHttpSession([]),
    )
    assert service_zh_hant.should_translate(zh_translated_doc) is True

    # Target zh-Hans with Traditional Chinese provider translation: missing-only MUST translate to zh-Hans.
    zh_hant_translated_doc = LyricsDocument(
        source_id="amll",
        song_id="song-jp-hant",
        timing=TimingKind.LINE,
        lines=(
            LyricLine(0, "L0", 0.0, 3.0, "君の声を聴かせて", "讓我聽見你的聲音"),
            LyricLine(1, "L1", 3.0, 6.0, "いつもここにいるよ", "我一直都在這裡"),
        ),
    )
    assert service_zh_hant.should_translate(zh_hant_translated_doc) is False
    assert service_zh.should_translate(zh_hant_translated_doc) is True
    cache.close()

    path = tmp_path / "config.json"
    cfg = Config(
        translation_language="pt-PT",
        translation_policy=TranslationPolicy.REPLACE,
        translation_services=[
            TranslationServiceConfig(
                id="custom",
                name="Custom A",
                provider=TranslationProvider.OPENAI_COMPATIBLE,
                enabled=True,
                base_url="https://api.example.com/v1",
                model="model-a",
            ),
            TranslationServiceConfig(
                id="custom-2",
                name="Custom B",
                provider=TranslationProvider.OPENAI_COMPATIBLE,
                enabled=True,
                base_url="https://backup.example.com/v1",
                model="model-b",
            ),
            TranslationServiceConfig(
                id="deepl",
                name="DeepL API",
                provider=TranslationProvider.DEEPL,
                enabled=False,
            ),
        ],
    )
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.translation_language == "pt-PT"
    assert loaded.translation_policy is TranslationPolicy.REPLACE
    assert [svc.id for svc in loaded.translation_services] == ["custom", "custom-2", "deepl"]
    assert loaded.translation_services[1].model == "model-b"
    assert "api_key" not in path.read_text(encoding="utf-8")

    # Legacy single-provider config.json migrates cleanly preserving keyring service id.
    migrated = Config.from_dict(
        {
            "translation_policy": "missing-only",
            "translation_provider": "deepl",
            "translation_base_url": "https://api.deepseek.com/v1",
            "translation_model": "deepseek-flash",
        }
    )
    assert migrated.translation_services[0].id == "deepl"
    assert migrated.translation_services[0].enabled is True
    assert migrated.translation_services[1].id == "openai-compatible"
    assert migrated.translation_services[1].model == "deepseek-flash"
