"""Tests for Shopify webhook views — security, idempotency, and routing."""

import base64
import hashlib
import hmac as hmac_mod
import json
import uuid

import pytest
from rest_framework.test import APIClient

from dos.tests.factories import StoreFactory
from shopify_webhooks.models import ShopifyWebhookConfig, WebhookEvent

pytestmark = pytest.mark.django_db

WEBHOOK_SECRET = "test-secret-for-views"
SHOP_DOMAIN = "test-shop.myshopify.com"
INVENTORY_URL = "/webhooks/shopify/inventory/"
PROMOTIONS_URL = "/webhooks/shopify/promotions/"


def _hmac_header(body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    """Compute a valid HMAC-SHA256 header value."""
    return base64.b64encode(
        hmac_mod.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("utf-8")


def _make_config(store, **overrides):
    """Create a ShopifyWebhookConfig for tests."""
    defaults = {
        "store": store,
        "retailer_id": uuid.uuid4(),
        "shopify_domain": SHOP_DOMAIN,
        "api_access_token": "shpat_test",
        "webhook_secret": WEBHOOK_SECRET,
        "is_active": True,
    }
    defaults.update(overrides)
    return ShopifyWebhookConfig.objects.create(**defaults)


def _post_webhook(client, url, payload, topic="products/create",
                  shop_domain=SHOP_DOMAIN, webhook_id=None, secret=WEBHOOK_SECRET):
    """Helper to POST a webhook with correct Shopify headers."""
    body = json.dumps(payload).encode("utf-8")
    if webhook_id is None:
        webhook_id = f"wh_{uuid.uuid4().hex[:12]}"
    return client.post(
        url,
        data=body,
        content_type="application/json",
        HTTP_X_SHOPIFY_SHOP_DOMAIN=shop_domain,
        HTTP_X_SHOPIFY_HMAC_SHA256=_hmac_header(body, secret),
        HTTP_X_SHOPIFY_TOPIC=topic,
        HTTP_X_SHOPIFY_WEBHOOK_ID=webhook_id,
    )


class TestBaseWebhookViewSecurity:
    """Security-critical tests for the base webhook view."""

    def setup_method(self):
        self.client = APIClient()

    def test_missing_shop_domain_returns_400(self):
        body = b'{"id": 1}'
        response = self.client.post(
            INVENTORY_URL,
            data=body,
            content_type="application/json",
            HTTP_X_SHOPIFY_HMAC_SHA256=_hmac_header(body),
            HTTP_X_SHOPIFY_TOPIC="products/create",
            HTTP_X_SHOPIFY_WEBHOOK_ID="wh_test",
        )
        assert response.status_code == 400
        assert "Missing" in response.json()["error"]

    def test_unknown_shop_domain_returns_404(self, store):
        _make_config(store)
        body = b'{"id": 1}'
        response = self.client.post(
            INVENTORY_URL,
            data=body,
            content_type="application/json",
            HTTP_X_SHOPIFY_SHOP_DOMAIN="unknown-shop.myshopify.com",
            HTTP_X_SHOPIFY_HMAC_SHA256=_hmac_header(body),
            HTTP_X_SHOPIFY_TOPIC="products/create",
            HTTP_X_SHOPIFY_WEBHOOK_ID="wh_test",
        )
        assert response.status_code == 404

    def test_inactive_config_returns_404(self, store):
        _make_config(store, is_active=False)
        response = _post_webhook(self.client, INVENTORY_URL, {"id": 1})
        assert response.status_code == 404

    def test_invalid_hmac_returns_401(self, store):
        _make_config(store)
        body = json.dumps({"id": 1}).encode("utf-8")
        response = self.client.post(
            INVENTORY_URL,
            data=body,
            content_type="application/json",
            HTTP_X_SHOPIFY_SHOP_DOMAIN=SHOP_DOMAIN,
            HTTP_X_SHOPIFY_HMAC_SHA256="invalid-hmac-value",
            HTTP_X_SHOPIFY_TOPIC="products/create",
            HTTP_X_SHOPIFY_WEBHOOK_ID="wh_test",
        )
        assert response.status_code == 401

    def test_wrong_secret_hmac_returns_401(self, store):
        _make_config(store)
        response = _post_webhook(
            self.client, INVENTORY_URL, {"id": 1}, secret="wrong-secret"
        )
        assert response.status_code == 401

    def test_missing_webhook_id_returns_400(self, store):
        _make_config(store)
        body = json.dumps({"id": 1}).encode("utf-8")
        response = self.client.post(
            INVENTORY_URL,
            data=body,
            content_type="application/json",
            HTTP_X_SHOPIFY_SHOP_DOMAIN=SHOP_DOMAIN,
            HTTP_X_SHOPIFY_HMAC_SHA256=_hmac_header(body),
            HTTP_X_SHOPIFY_TOPIC="products/create",
            # No HTTP_X_SHOPIFY_WEBHOOK_ID
        )
        assert response.status_code == 400


class TestWebhookIdempotency:
    """Tests for duplicate webhook rejection."""

    def setup_method(self):
        self.client = APIClient()

    def test_valid_webhook_creates_event(self, store, mocker):
        _make_config(store)
        mocker.patch(
            "shopify_webhooks.views.process_shopify_inventory_event"
        )
        payload = {"id": 123, "title": "Test Product"}
        webhook_id = "wh_new_event"
        response = _post_webhook(
            self.client,
            INVENTORY_URL,
            payload,
            topic="products/create",
            webhook_id=webhook_id,
        )
        assert response.status_code == 200
        assert WebhookEvent.objects.filter(webhook_id=webhook_id).exists()
        event = WebhookEvent.objects.get(webhook_id=webhook_id)
        assert event.topic == "products/create"
        assert event.shop_domain == SHOP_DOMAIN
        assert event.store == store
        assert event.status == WebhookEvent.Status.RECEIVED

    def test_duplicate_webhook_id_returns_200_no_new_record(self, store, mocker):
        _make_config(store)
        mocker.patch(
            "shopify_webhooks.views.process_shopify_inventory_event"
        )
        webhook_id = "wh_duplicate"
        payload = {"id": 456}

        # First request
        resp1 = _post_webhook(
            self.client, INVENTORY_URL, payload,
            webhook_id=webhook_id,
        )
        assert resp1.status_code == 200
        assert WebhookEvent.objects.filter(webhook_id=webhook_id).count() == 1

        # Second request — same webhook_id
        resp2 = _post_webhook(
            self.client, INVENTORY_URL, payload,
            webhook_id=webhook_id,
        )
        assert resp2.status_code == 200
        # Still only one record
        assert WebhookEvent.objects.filter(webhook_id=webhook_id).count() == 1


class TestWebhookTopicRouting:
    """Tests for topic validation on each endpoint."""

    def setup_method(self):
        self.client = APIClient()

    def test_inventory_endpoint_accepts_product_topics(self, store, mocker):
        _make_config(store)
        mocker.patch(
            "shopify_webhooks.views.process_shopify_inventory_event"
        )
        for topic in [
            "products/create",
            "products/update",
            "products/delete",
            "inventory_levels/update",
        ]:
            response = _post_webhook(
                self.client, INVENTORY_URL, {"id": 1}, topic=topic
            )
            assert response.status_code == 200, f"Failed for topic {topic}"

    def test_inventory_endpoint_rejects_promotion_topic(self, store):
        _make_config(store)
        response = _post_webhook(
            self.client, INVENTORY_URL, {"id": 1}, topic="price_rules/create"
        )
        assert response.status_code == 400

    def test_promotions_endpoint_accepts_promotion_topics(self, store, mocker):
        _make_config(store)
        mocker.patch(
            "shopify_webhooks.views.process_shopify_promotion_event"
        )
        for topic in [
            "price_rules/create",
            "price_rules/update",
            "price_rules/delete",
            "collections/update",
        ]:
            response = _post_webhook(
                self.client, PROMOTIONS_URL, {"id": 1}, topic=topic
            )
            assert response.status_code == 200, f"Failed for topic {topic}"

    def test_promotions_endpoint_rejects_inventory_topic(self, store):
        _make_config(store)
        response = _post_webhook(
            self.client, PROMOTIONS_URL, {"id": 1}, topic="products/create"
        )
        assert response.status_code == 400


class TestWebhookEventRecording:
    """Tests for WebhookEvent audit trail."""

    def setup_method(self):
        self.client = APIClient()

    def test_event_records_payload_hash(self, store, mocker):
        _make_config(store)
        mocker.patch(
            "shopify_webhooks.views.process_shopify_inventory_event"
        )
        payload = {"id": 789, "title": "Hash Test"}
        webhook_id = "wh_hash_test"
        body = json.dumps(payload).encode("utf-8")
        expected_hash = hashlib.sha256(body).hexdigest()

        _post_webhook(
            self.client, INVENTORY_URL, payload, webhook_id=webhook_id
        )

        event = WebhookEvent.objects.get(webhook_id=webhook_id)
        assert event.payload_hash == expected_hash

    def test_event_enqueues_dramatiq_task(self, store, mocker):
        _make_config(store)
        mock_task = mocker.patch(
            "shopify_webhooks.views.process_shopify_inventory_event"
        )
        webhook_id = "wh_task_test"
        payload = {"id": 999}

        _post_webhook(
            self.client, INVENTORY_URL, payload, webhook_id=webhook_id
        )

        event = WebhookEvent.objects.get(webhook_id=webhook_id)
        mock_task.send.assert_called_once_with(event.id, payload)
