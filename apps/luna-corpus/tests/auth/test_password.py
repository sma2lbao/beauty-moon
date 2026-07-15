"""Tests for bcrypt password hashing."""
from app.auth.password import hash_password, verify_password


def test_hash_is_not_plaintext():
    hashed = hash_password("s3cret-pw")
    assert hashed != "s3cret-pw"
    assert hashed.startswith("$2")  # bcrypt prefix


def test_verify_correct_password():
    hashed = hash_password("s3cret-pw")
    assert verify_password("s3cret-pw", hashed) is True


def test_verify_wrong_password():
    hashed = hash_password("s3cret-pw")
    assert verify_password("wrong", hashed) is False
