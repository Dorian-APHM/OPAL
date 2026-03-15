"""
Shared rate limiter instance.

Kept here to avoid circular imports between main.py and router modules.
"""
import os

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    enabled=os.getenv("TESTING", "").lower() not in ("1", "true"),
)
