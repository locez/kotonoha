"""Behavior tests for the keyring-backed async secret storage boundary."""

from __future__ import annotations

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.backends.fail import Keyring as FailKeyring
from keyring.errors import PasswordDeleteError

from kotonoha.async_worker import BlockingCallRunner
from kotonoha.secrets import KeyringSecretStore, SecretStoreError, translation_secret_key


class _MemoryKeyring(KeyringBackend):
    priority = 10

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        key = (service, username)
        if key not in self._store:
            raise PasswordDeleteError("absent")
        del self._store[key]


async def test_keyring_secret_store_roundtrips_and_deletes_idempotently(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _MemoryKeyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    monkeypatch.setattr(keyring, "get_password", backend.get_password)
    monkeypatch.setattr(keyring, "set_password", backend.set_password)
    monkeypatch.setattr(keyring, "delete_password", backend.delete_password)

    store = KeyringSecretStore(worker=BlockingCallRunner("test-secrets"), environ={})
    try:
        availability = await store.availability()
        assert availability.available is True
        assert availability.reason is None

        key = translation_secret_key("deepl")
        assert await store.get_secret(key) is None
        await store.set_secret(key, "  secret-key:fx  ")
        assert await store.get_secret(key) == "secret-key:fx"

        await store.delete_secret(key)
        assert await store.get_secret(key) is None
        # Deleting an already-absent secret must succeed quietly.
        await store.delete_secret(key)
    finally:
        store.close()


async def test_keyring_unavailable_reports_reason_and_uses_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    fail_backend = FailKeyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: fail_backend)

    store = KeyringSecretStore(
        worker=BlockingCallRunner("test-secrets-fail"),
        environ={"KOTONOHA_DEEPL_API_KEY": "env-key:fx"},
    )
    try:
        availability = await store.availability()
        assert availability.available is False
        assert availability.reason == "no-backend"

        assert await store.get_secret(translation_secret_key("deepl")) == "env-key:fx"
        with pytest.raises(SecretStoreError):
            await store.set_secret(translation_secret_key("deepl"), "cannot-store")
    finally:
        store.close()
