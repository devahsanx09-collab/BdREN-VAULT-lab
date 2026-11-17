"""Encryption of device passwords (Fernet, key in data/secret.key)."""
from functools import lru_cache

from cryptography.fernet import Fernet
from django.conf import settings

from .keys import load_or_create_key


@lru_cache(maxsize=1)
def _fernet():
    return Fernet(load_or_create_key(settings.FERNET_KEY_FILE, Fernet.generate_key))


def encrypt(value):
    """Plain text -> encrypted text ('' stays '')."""
    return _fernet().encrypt(value.encode()).decode() if value else ""


def decrypt(token):
    """Encrypted text -> plain text ('' stays '')."""
    return _fernet().decrypt(token.encode()).decode() if token else ""
