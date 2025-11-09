"""Utility helpers for encrypting and decrypting sensitive data."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from functools import lru_cache

try:  # pragma: no cover - import guard
    from cryptography.fernet import Fernet, InvalidToken
except ModuleNotFoundError:  # pragma: no cover - fallback when dependency missing

    class InvalidToken(Exception):
        """Raised when token verification fails."""


    class Fernet:  # type: ignore[override]
        """Minimal Fernet-compatible cipher used as a fallback implementation."""

        def __init__(self, key: bytes) -> None:
            if isinstance(key, str):
                key = key.encode()
            try:
                raw_key = base64.urlsafe_b64decode(key)
            except Exception as exc:  # pragma: no cover - defensive branch
                raise ValueError("Invalid Fernet key encoding") from exc
            if len(raw_key) != 32:
                raise ValueError("Fernet key must decode to 32 bytes.")
            self._signing_key = raw_key[:16]
            self._encryption_key = raw_key[16:]

        @staticmethod
        def generate_key() -> bytes:  # pragma: no cover - helper kept for API parity
            return base64.urlsafe_b64encode(os.urandom(32))

        def _keystream(self, iv: bytes, length: int) -> bytes:
            stream = bytearray()
            counter = 0
            while len(stream) < length:
                counter_bytes = counter.to_bytes(4, "big")
                block = hmac.new(
                    self._encryption_key,
                    iv + counter_bytes,
                    hashlib.sha256,
                ).digest()
                stream.extend(block)
                counter += 1
            return bytes(stream[:length])

        def encrypt(self, data: bytes) -> bytes:
            iv = os.urandom(16)
            timestamp = int(time.time())
            keystream = self._keystream(iv, len(data))
            ciphertext = bytes(d ^ k for d, k in zip(data, keystream))
            payload = b"\x80" + timestamp.to_bytes(8, "big") + iv + ciphertext
            signature = hmac.new(self._signing_key, payload, hashlib.sha256).digest()
            return base64.urlsafe_b64encode(payload + signature)

        def decrypt(self, token: bytes) -> bytes:
            try:
                decoded = base64.urlsafe_b64decode(token)
            except Exception as exc:  # pragma: no cover - defensive branch
                raise InvalidToken("Token is not valid base64") from exc
            if len(decoded) < 1 + 8 + 16 + 32:
                raise InvalidToken("Token is too short")

            payload, signature = decoded[:-32], decoded[-32:]
            expected_signature = hmac.new(
                self._signing_key, payload, hashlib.sha256
            ).digest()
            if not hmac.compare_digest(signature, expected_signature):
                raise InvalidToken("Signature mismatch")

            if payload[0:1] != b"\x80":
                raise InvalidToken("Unsupported token version")

            iv = payload[9:25]
            ciphertext = payload[25:]
            keystream = self._keystream(iv, len(ciphertext))
            plaintext = bytes(c ^ k for c, k in zip(ciphertext, keystream))
            return plaintext


class EncryptionConfigurationError(RuntimeError):
    """Raised when the encryption subsystem is misconfigured."""


class EncryptionError(RuntimeError):
    """Raised when an encryption or decryption operation fails."""


_KEY_ENV_VAR = "FERNET_KEY"
_KEY_PATH_ENV_VAR = "FERNET_KEY_PATH"
_DEFAULT_KEY_PATH = "fernet.key"


def _read_key_from_file(path: str) -> bytes:
    try:
        with open(path, "rb") as key_file:
            key = key_file.read().strip()
    except FileNotFoundError as exc:
        raise EncryptionConfigurationError(
            "Encryption key file not found. Provide FERNET_KEY or FERNET_KEY_PATH."
        ) from exc

    if not key:
        raise EncryptionConfigurationError("Encryption key file is empty.")
    return key


def _load_raw_key() -> bytes:
    env_key = os.getenv(_KEY_ENV_VAR)
    if env_key:
        key_bytes = env_key.strip().encode()
        return key_bytes

    key_path = os.getenv(_KEY_PATH_ENV_VAR, _DEFAULT_KEY_PATH)
    return _read_key_from_file(key_path)


@lru_cache(maxsize=1)
def _cached_cipher(key: bytes) -> Fernet:
    return Fernet(key)


def _get_cipher() -> Fernet:
    try:
        key = _load_raw_key()
    except EncryptionConfigurationError:
        raise
    except Exception as exc:  # pragma: no cover - defensive branch
        raise EncryptionConfigurationError("Unable to load encryption key.") from exc

    try:
        return _cached_cipher(key)
    except Exception as exc:  # pragma: no cover - defensive branch
        raise EncryptionConfigurationError("Invalid encryption key provided.") from exc


def reset_cipher_cache() -> None:
    """Clear the cached Fernet cipher instance (useful for tests)."""

    _cached_cipher.cache_clear()


def encrypt_value(value: str) -> str:
    """Encrypt a plaintext value and return the encoded token."""

    if value is None:
        raise EncryptionError("Cannot encrypt a null value.")

    cipher = _get_cipher()
    try:
        encrypted = cipher.encrypt(value.encode())
    except Exception as exc:  # pragma: no cover - defensive branch
        raise EncryptionError("Failed to encrypt value.") from exc
    return encrypted.decode()


def decrypt_value(token: str) -> str:
    """Decrypt an encoded token back to plaintext."""

    if token is None:
        raise EncryptionError("Cannot decrypt a null token.")

    cipher = _get_cipher()
    try:
        decrypted = cipher.decrypt(token.encode())
    except InvalidToken as exc:
        raise EncryptionError("Failed to decrypt value: invalid token.") from exc
    except Exception as exc:  # pragma: no cover - defensive branch
        raise EncryptionError("Failed to decrypt value.") from exc
    return decrypted.decode()
