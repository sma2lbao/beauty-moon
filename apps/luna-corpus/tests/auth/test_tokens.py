"""Tests for JWT access tokens and refresh token helpers."""
import pytest

from app.auth.tokens import (
    TokenError,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_refresh_token,
)


def test_access_token_roundtrip():
    token = create_access_token("user-123")
    assert decode_access_token(token) == "user-123"


def test_decode_rejects_tampered_token():
    token = create_access_token("user-123")
    tampered = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
    with pytest.raises(TokenError):
        decode_access_token(tampered)


def test_decode_rejects_garbage():
    with pytest.raises(TokenError):
        decode_access_token("not-a-jwt")


def test_refresh_token_is_random_and_hashable():
    a = generate_refresh_token()
    b = generate_refresh_token()
    assert a != b
    assert hash_refresh_token(a) == hash_refresh_token(a)
    assert hash_refresh_token(a) != hash_refresh_token(b)
    assert len(hash_refresh_token(a)) == 64  # sha256 hex
