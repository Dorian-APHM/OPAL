"""Tests for password encryption utilities."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.crypto import encrypt_password, decrypt_password


def test_encrypt_decrypt_roundtrip():
    """Encrypted password can be decrypted back."""
    original = "my_secret_password_123!"
    encrypted = encrypt_password(original)
    assert encrypted != original
    assert encrypted != ""
    decrypted = decrypt_password(encrypted)
    assert decrypted == original


def test_encrypt_empty_string():
    """Empty string returns empty string."""
    assert encrypt_password("") == ""
    assert decrypt_password("") == ""


def test_encrypt_unicode():
    """Unicode passwords work correctly."""
    original = "mot_de_passe_français_éàü"
    encrypted = encrypt_password(original)
    decrypted = decrypt_password(encrypted)
    assert decrypted == original


def test_encrypt_produces_different_ciphertexts():
    """Same password produces different ciphertexts (Fernet uses random IV)."""
    password = "test_password"
    enc1 = encrypt_password(password)
    enc2 = encrypt_password(password)
    assert enc1 != enc2
    assert decrypt_password(enc1) == password
    assert decrypt_password(enc2) == password
