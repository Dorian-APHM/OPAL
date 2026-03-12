"""
Password encryption utilities using Fernet symmetric encryption.
Ported from achilles_like/crypto_utils.py.
"""
import os
from pathlib import Path

from cryptography.fernet import Fernet

SECRET_KEY_FILE = Path(__file__).parent.parent / "data" / ".secret_key"


def get_or_create_key() -> bytes:
    """Retrieve or generate the Fernet encryption key."""
    SECRET_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if SECRET_KEY_FILE.exists():
        try:
            with open(SECRET_KEY_FILE, "rb") as f:
                return f.read()
        except PermissionError:
            os.chmod(SECRET_KEY_FILE, 0o644)
            with open(SECRET_KEY_FILE, "rb") as f:
                return f.read()
    key = Fernet.generate_key()
    fd = os.open(str(SECRET_KEY_FILE), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
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


def decrypt_password(encrypted_password: str) -> str:
    """Decrypt an encrypted password string.
    Returns empty string if decryption fails (e.g. key mismatch after volume recreate).
    """
    if not encrypted_password:
        return ""
    try:
        return get_fernet().decrypt(encrypted_password.encode("utf-8")).decode("utf-8")
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "Failed to decrypt password — encryption key may have changed. "
            "Please re-enter the CDM password in Settings."
        )
        return ""
