"""Tests for HMAC signature verification."""

import base64
import hashlib
import hmac as hmac_mod

import pytest

from shopify_webhooks.middleware import verify_shopify_hmac

pytestmark = pytest.mark.django_db

SECRET = "test-webhook-secret-key"


def _compute_hmac(body: bytes, secret: str) -> str:
    """Compute a valid Shopify-style HMAC-SHA256 for testing."""
    return base64.b64encode(
        hmac_mod.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("utf-8")


class TestVerifyShopifyHmac:
    """Tests for verify_shopify_hmac()."""

    def test_valid_signature(self):
        body = b'{"id": 12345, "title": "Test Product"}'
        hmac_header = _compute_hmac(body, SECRET)
        assert verify_shopify_hmac(body, hmac_header, SECRET) is True

    def test_tampered_payload_rejected(self):
        body = b'{"id": 12345, "title": "Test Product"}'
        hmac_header = _compute_hmac(body, SECRET)
        tampered_body = b'{"id": 12345, "title": "TAMPERED"}'
        assert verify_shopify_hmac(tampered_body, hmac_header, SECRET) is False

    def test_empty_hmac_header_rejected(self):
        body = b'{"id": 12345}'
        assert verify_shopify_hmac(body, "", SECRET) is False

    def test_wrong_secret_rejected(self):
        body = b'{"id": 12345}'
        hmac_header = _compute_hmac(body, SECRET)
        assert verify_shopify_hmac(body, hmac_header, "wrong-secret") is False

    def test_empty_body(self):
        body = b""
        hmac_header = _compute_hmac(body, SECRET)
        assert verify_shopify_hmac(body, hmac_header, SECRET) is True

    def test_garbage_hmac_rejected(self):
        body = b'{"id": 12345}'
        assert verify_shopify_hmac(body, "not-valid-base64!", SECRET) is False

    def test_unicode_payload(self):
        body = '{"name": "café résumé"}'.encode("utf-8")
        hmac_header = _compute_hmac(body, SECRET)
        assert verify_shopify_hmac(body, hmac_header, SECRET) is True

    def test_large_payload(self):
        body = b"x" * 100_000
        hmac_header = _compute_hmac(body, SECRET)
        assert verify_shopify_hmac(body, hmac_header, SECRET) is True
