"""Password hashing utilities backed by bcrypt."""
from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(raw: str) -> str:
    """Return a bcrypt hash of the given plaintext password."""
    return _pwd_context.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    """Return True if the plaintext matches the stored hash."""
    return _pwd_context.verify(raw, hashed)
