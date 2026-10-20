"""Password hashing, random tokens, at-rest encryption and HMAC-signed capability tokens."""

import base64
import hashlib
import hmac
import json
import secrets
from functools import lru_cache
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

_hasher = PasswordHasher()  # Argon2id with library defaults

MIN_PASSWORD_LENGTH = 12
_COMMON = {
    "password1234", "123456789012", "qwertyuiop12", "passwordpassword", "iloveyou1234", "letmein12345",
    "welcome12345", "administrator", "changeme1234", "password123!", "qwerty123456", "abc123456789",
    "111111111111", "000000000000", "trustno11234", "football1234", "monkey123456", "dragon123456",
    "baseball1234", "sunshine1234", "princess1234", "superman1234", "1q2w3e4r5t6y", "qwertyuiopas",
}


def validate_password(password: str) -> str | None:
    """Return a human-readable problem, or None if the password is acceptable."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters."
    if password.lower() in _COMMON or len(set(password)) < 4:
        return "This password is too common or too simple. Choose a longer passphrase."
    return None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def sha256_hex(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def _key_file(name: str) -> Path:
    return get_settings().data_dir / "secrets" / name


def _load_or_create(name: str, factory) -> str:
    path = _key_file(name)
    if path.exists():
        return path.read_text().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    value = factory()
    path.write_text(value)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return value


@lru_cache
def secret_key() -> bytes:
    configured = get_settings().secret_key
    if configured:
        return configured.encode()
    return _load_or_create("secret.key", lambda: secrets.token_hex(32)).encode()


@lru_cache
def _fernet() -> Fernet:
    configured = get_settings().encryption_key
    key = configured or _load_or_create("encryption.key", lambda: Fernet.generate_key().decode())
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Stored secret cannot be decrypted with the current key") from exc


def sign(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).decode()
    mac = hmac.new(secret_key(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{mac}"


def verify_signed(token: str) -> dict | None:
    try:
        body, mac = token.rsplit(".", 1)
    except ValueError:
        return None
    expected = hmac.new(secret_key(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected):
        return None
    try:
        return json.loads(base64.urlsafe_b64decode(body.encode()))
    except (ValueError, json.JSONDecodeError):
        return None


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
