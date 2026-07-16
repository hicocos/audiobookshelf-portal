from datetime import timedelta

import pytest

from app.security import create_access_token, decode_access_token, hash_password, verify_password


def test_password_hash_round_trip_and_hash_is_not_plaintext():
    password = "StrongPassword-521"

    hashed = hash_password(password)

    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("wrong", hashed) is False


def test_jwt_round_trip_contains_subject_and_role():
    token = create_access_token(subject="user-id", role="admin", expires_delta=timedelta(minutes=5))

    payload = decode_access_token(token)

    assert payload["sub"] == "user-id"
    assert payload["role"] == "admin"


def test_invalid_jwt_raises_value_error():
    with pytest.raises(ValueError):
        decode_access_token("not-a-token")
