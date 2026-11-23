"""Async secret storage boundary backed by the OS keyring.

Credentials such as translation API keys are never persisted into ``config.json``.
Blocking keyring calls run on an explicitly owned :class:`BlockingWorkerPort` so
D-Bus or wallet prompts never stall the Qt/asyncio event loop.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import keyring
from keyring.backends.fail import Keyring as FailKeyring
from keyring.backends.null import Keyring as NullKeyring
from keyring.errors import KeyringError, PasswordDeleteError

from .async_worker import BlockingWorkerPort

KEYRING_SERVICE_NAME = "kotonoha"

_ENV_FALLBACKS: dict[str, tuple[str, ...]] = {
    "translation_api_key.deepl": ("KOTONOHA_DEEPL_API_KEY", "KOTONOHA_TRANSLATION_API_KEY"),
    "translation_api_key.openai-compatible": (
        "KOTONOHA_OPENAI_API_KEY",
        "KOTONOHA_TRANSLATION_API_KEY",
    ),
}


class SecretStoreError(RuntimeError):
    """A credential storage operation failed at the system keyring boundary."""


@dataclass(frozen=True, slots=True)
class SecretAvailability:
    """Report whether the platform secret store can persist credentials."""

    available: bool
    backend_name: str
    reason: str | None = None


class SecretStore(Protocol):
    """Application-facing async contract for credential persistence."""

    def start(self) -> None:
        """Reopen the owned worker if it was previously closed."""
        ...

    def close(self) -> None:
        """Release the owned blocking worker."""
        ...

    async def availability(self) -> SecretAvailability:
        """Probe whether a usable persistent keyring backend is active."""
        ...

    async def get_secret(self, key: str) -> str | None:
        """Return the stored secret for ``key``, or ``None`` when absent."""
        ...

    async def set_secret(self, key: str, value: str) -> None:
        """Store or replace ``key`` with a non-empty secret value."""
        ...

    async def delete_secret(self, key: str) -> None:
        """Remove ``key`` if present; deleting an absent key succeeds."""
        ...


def translation_secret_key(provider: str) -> str:
    """Return the stable keyring account name for one translation provider."""
    cleaned = provider.strip()
    if not cleaned:
        raise ValueError("translation provider id must not be empty")
    return f"translation_api_key.{cleaned}"


class KeyringSecretStore:
    """Run ``keyring`` operations on an owned blocking worker with explicit errors."""

    def __init__(
        self,
        *,
        worker: BlockingWorkerPort,
        service_name: str = KEYRING_SERVICE_NAME,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        """Create a secret store without contacting the system keyring."""
        if not service_name:
            raise ValueError("keyring service name must not be empty")
        self._worker = worker
        self._service_name = service_name
        self._environ = environ

    def start(self) -> None:
        """Reopen the owned worker after a previous shutdown."""
        self._worker.reopen()

    def close(self) -> None:
        """Release the worker without blocking the event loop."""
        self._worker.close()

    async def availability(self) -> SecretAvailability:
        """Inspect the active keyring backend without swallowing unexpected failures."""
        try:
            return await self._worker.run(self._probe_sync)
        except (KeyringError, OSError, RuntimeError, TimeoutError) as exc:
            return SecretAvailability(
                available=False,
                backend_name="unknown",
                reason=f"Keyring backend probe failed: {exc}",
            )

    async def get_secret(self, key: str) -> str | None:
        """Read a secret from the system keyring, falling back to environment overrides."""
        _validate_key(key)
        env_value = self._env_override(key)
        try:
            stored = await self._worker.run(self._get_sync, key)
        except (KeyringError, OSError, RuntimeError, TimeoutError) as exc:
            if env_value is not None:
                return env_value
            raise SecretStoreError(f"Could not read secret {key!r} from system keyring: {exc}") from exc
        if stored is not None and stored.strip():
            return stored.strip()
        return env_value

    async def set_secret(self, key: str, value: str) -> None:
        """Persist a trimmed non-empty secret in the system keyring."""
        _validate_key(key)
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("secret value must not be empty")
        try:
            await self._worker.run(self._set_sync, key, cleaned)
        except (KeyringError, OSError, RuntimeError, TimeoutError) as exc:
            raise SecretStoreError(f"Could not save secret {key!r} to system keyring: {exc}") from exc

    async def delete_secret(self, key: str) -> None:
        """Delete a stored secret from the system keyring when present."""
        _validate_key(key)
        try:
            await self._worker.run(self._delete_sync, key)
        except (KeyringError, OSError, RuntimeError, TimeoutError) as exc:
            raise SecretStoreError(f"Could not delete secret {key!r} from system keyring: {exc}") from exc

    def _probe_sync(self) -> SecretAvailability:
        backend = keyring.get_keyring()
        backend_name = f"{type(backend).__module__}.{type(backend).__name__}"
        if isinstance(backend, (FailKeyring, NullKeyring)):
            return SecretAvailability(
                available=False,
                backend_name=backend_name,
                reason="no-backend",
            )
        return SecretAvailability(available=True, backend_name=backend_name)

    def _get_sync(self, key: str) -> str | None:
        probe = self._probe_sync()
        if not probe.available:
            return None
        return keyring.get_password(self._service_name, key)

    def _set_sync(self, key: str, value: str) -> None:
        probe = self._probe_sync()
        if not probe.available:
            raise KeyringError("No usable system keyring backend is available")
        keyring.set_password(self._service_name, key, value)

    def _delete_sync(self, key: str) -> None:
        probe = self._probe_sync()
        if not probe.available:
            return
        try:
            keyring.delete_password(self._service_name, key)
        except PasswordDeleteError:
            return

    def _env_override(self, key: str) -> str | None:
        env = os.environ if self._environ is None else self._environ
        for name in _ENV_FALLBACKS.get(key, ()):
            value = env.get(name)
            if value is not None and value.strip():
                return value.strip()
        return None


def _validate_key(key: str) -> None:
    if not key or not key.strip():
        raise ValueError("secret key must not be empty")


__all__ = [
    "KEYRING_SERVICE_NAME",
    "KeyringSecretStore",
    "SecretAvailability",
    "SecretStore",
    "SecretStoreError",
    "translation_secret_key",
]
