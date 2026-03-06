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
        with open(SECRET_KEY_FILE, "rb") as f:
            return f.read()
    key = Fernet.generate_key()
    with open(SECRET_KEY_FILE, "wb") as f:
        f.write(key)
    os.chmod(SECRET_KEY_FILE, 0o600)
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
    """Decrypt an encrypted password string."""
    if not encrypted_password:
        return ""
    return get_fernet().decrypt(encrypted_password.encode("utf-8")).decode("utf-8")
