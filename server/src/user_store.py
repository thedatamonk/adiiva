"""
Demo user store to seed users
In a production setting, we will have to have a signup option
"""

import bcrypt
from loguru import logger

_users: dict[str, bytes] = {}


def _hash_password(password: str) -> bytes:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt())


def _check_password(password: str, hashed: bytes) -> bool:
    return bcrypt.checkpw(password.encode(), hashed)


def _seed_demo_users():
    """
    Pre-populate a few demo users.
    """
    demo_users = {
        "kalika": "kalika@adiiva",
        "robin": "robin@adiiva",
        "rohil": "rohil@adiiva",
    }
    for uid, pw in demo_users.items():
        _users[uid] = _hash_password(pw)
    logger.info(f"Seeded {len(demo_users)} demo users: {list(demo_users.keys())}")


def authenticate_user(user_id: str, password: str) -> bool:
    """
    Verify user_id and password against the store.
    """
    hashed = _users.get(user_id)
    if hashed is None:
        logger.warning(f"Authentication failed: unknown user '{user_id}'")
        return False
    if not _check_password(password, hashed):
        logger.warning(f"Authentication failed: wrong password for '{user_id}'")
        return False
    logger.info(f"Authentication successful for '{user_id}'")
    return True


_seed_demo_users()
