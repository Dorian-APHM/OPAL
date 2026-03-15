"""
Password encryption utilities using Fernet symmetric encryption.
Ported from achilles_like/crypto_utils.py.

Supports key from ENCRYPTION_KEY env var (preferred) or auto-generated file.
"""
import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

SECRET_KEY_FILE = Path(__file__).parent.parent / "data" / ".secret_key"


def get_or_create_key() -> bytes:
    """Retrieve or generate the Fernet encryption key.

    Priority:
    1. ENCRYPTION_KEY environment variable (base64-encoded Fernet key)
    2. File-based key at SECRET_KEY_FILE
    3. Auto-generate a new key and persist to file
    """
    # Prefer env var (supports external secret managers / Kubernetes secrets)
    env_key = os.getenv("ENCRYPTION_KEY")
    if env_key:
        return env_key.encode("utf-8")

    SECRET_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if SECRET_KEY_FILE.exists():
        try:
            with open(SECRET_KEY_FILE, "rb") as f:
                return f.read()
        except PermissionError:
            os.chmod(SECRET_KEY_FILE, 0o600)
            with open(SECRET_KEY_FILE, "rb") as f:
                return f.read()
    key = Fernet.generate_key()
    fd = os.open(str(SECRET_KEY_FILE), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key


def get_fernet() -> Fernet:
    """Return a configured Fernet instance."""
    return Fernet(get_or_create_key())


def encrypt_password(password: str) -> str:
    """Encrypt a password string."""
    if not password:
        return ""
    return get_fernet().encrypt(password.encode("utf-8")).decode("utf-8")


class DecryptionError(Exception):
    """Raised when password decryption fails due to key mismatch."""
    pass


def decrypt_password(encrypted_password: str) -> str:
    """Decrypt an encrypted password string.

    Raises DecryptionError if decryption fails (e.g. key mismatch after
    volume recreate), so callers can inform the user to re-enter the password.
    """
    if not encrypted_password:
        return ""
    try:
        return get_fernet().decrypt(encrypted_password.encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception) as exc:
        logger.error(
            "Failed to decrypt password — encryption key may have changed. "
            "Please re-enter the CDM password in Settings."
        )
        raise DecryptionError(
            "Decryption failed — the encryption key may have changed. "
            "Please re-enter the CDM password in Settings."
        ) from exc
