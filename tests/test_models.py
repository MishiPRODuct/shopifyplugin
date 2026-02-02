"""Tests for ShopifyWebhookConfig and WebhookEvent models."""

import uuid

import pytest
from django.db import IntegrityError

from dos.tests.factories import StoreFactory
from shopify_webhooks.models import ShopifyWebhookConfig, WebhookEvent

pytestmark = pytest.mark.django_db


class TestShopifyWebhookConfig:
    """Tests for the ShopifyWebhookConfig model."""

    def test_create_config(self, store):
        config = ShopifyWebhookConfig.objects.create(
            store=store,
            retailer_id=uuid.uuid4(),
            shopify_domain="test-store.myshopify.com",
            api_access_token="shpat_abc123",
            webhook_secret="whsec_test",
        )
        assert config.pk is not None
        assert config.is_active is True
        assert config.sync_inventory is True
        assert config.sync_promotions is True
        assert config.sync_orders_to_shopify is True
        assert config.api_version == "2024-07"
        assert config.extra_data == {}

    def test_one_to_one_with_store(self, store):
        ShopifyWebhookConfig.objects.create(
            store=store,
            retailer_id=uuid.uuid4(),
            shopify_domain="store1.myshopify.com",
            api_access_token="tok1",
            webhook_secret="sec1",
        )
        with pytest.raises(IntegrityError):
            ShopifyWebhookConfig.objects.create(
                store=store,
                retailer_id=uuid.uuid4(),
                shopify_domain="store2.myshopify.com",
                api_access_token="tok2",
                webhook_secret="sec2",
            )

    def test_extra_data_json_field(self, store):
        tax_mapping = {
            "tax_mapping": {"default_rate": 20.0, "reduced_rate": 5.0}
        }
        config = ShopifyWebhookConfig.objects.create(
            store=store,
            retailer_id=uuid.uuid4(),
            shopify_domain="store.myshopify.com",
            api_access_token="tok",
            webhook_secret="sec",
            extra_data=tax_mapping,
        )
        config.refresh_from_db()
        assert config.extra_data == tax_mapping
        assert config.extra_data["tax_mapping"]["default_rate"] == 20.0

    def test_str_representation(self, store):
        config = ShopifyWebhookConfig.objects.create(
            store=store,
            retailer_id=uuid.uuid4(),
            shopify_domain="mystore.myshopify.com",
            api_access_token="tok",
            webhook_secret="sec",
        )
        assert "mystore.myshopify.com" in str(config)
        assert str(store.store_id) in str(config)

    def test_timestamps_auto_set(self, store):
        config = ShopifyWebhookConfig.objects.create(
            store=store,
            retailer_id=uuid.uuid4(),
            shopify_domain="store.myshopify.com",
            api_access_token="tok",
            webhook_secret="sec",
        )
        assert config.created_at is not None
        assert config.updated_at is not None


class TestWebhookEvent:
    """Tests for the WebhookEvent model."""

    def test_create_event(self, store):
        event = WebhookEvent.objects.create(
            webhook_id="wh_abc123",
            topic="products/create",
            shop_domain="store.myshopify.com",
            store=store,
            status=WebhookEvent.Status.RECEIVED,
            payload_hash="a" * 64,
        )
        assert event.pk is not None
        assert event.status == "received"
        assert event.error_message == ""
        assert event.processing_time_ms is None

    def test_unique_webhook_id(self, store):
        WebhookEvent.objects.create(
            webhook_id="wh_unique_001",
            topic="products/create",
            shop_domain="store.myshopify.com",
            store=store,
            status=WebhookEvent.Status.RECEIVED,
            payload_hash="a" * 64,
        )
        with pytest.raises(IntegrityError):
            WebhookEvent.objects.create(
                webhook_id="wh_unique_001",
                topic="products/update",
                shop_domain="store.myshopify.com",
                store=store,
                status=WebhookEvent.Status.RECEIVED,
                payload_hash="b" * 64,
            )

    def test_status_transitions(self, store):
        event = WebhookEvent.objects.create(
            webhook_id="wh_transition",
            topic="products/update",
            shop_domain="store.myshopify.com",
            store=store,
            status=WebhookEvent.Status.RECEIVED,
            payload_hash="c" * 64,
        )
        assert event.status == WebhookEvent.Status.RECEIVED

        event.status = WebhookEvent.Status.PROCESSING
        event.save(update_fields=["status"])
        event.refresh_from_db()
        assert event.status == WebhookEvent.Status.PROCESSING

        event.status = WebhookEvent.Status.SUCCESS
        event.processing_time_ms = 150
        event.save(update_fields=["status", "processing_time_ms"])
        event.refresh_from_db()
        assert event.status == WebhookEvent.Status.SUCCESS
        assert event.processing_time_ms == 150

    def test_failed_status_with_error(self, store):
        event = WebhookEvent.objects.create(
            webhook_id="wh_fail",
            topic="products/delete",
            shop_domain="store.myshopify.com",
            store=store,
            status=WebhookEvent.Status.FAILED,
            payload_hash="d" * 64,
            error_message="Connection refused",
        )
        event.refresh_from_db()
        assert event.status == WebhookEvent.Status.FAILED
        assert event.error_message == "Connection refused"

    def test_str_representation(self, store):
        event = WebhookEvent.objects.create(
            webhook_id="wh_str_test",
            topic="products/create",
            shop_domain="store.myshopify.com",
            store=store,
            status=WebhookEvent.Status.RECEIVED,
            payload_hash="e" * 64,
        )
        result = str(event)
        assert "products/create" in result
        assert "received" in result
        assert "wh_str_test" in result

    def test_store_nullable(self):
        """WebhookEvent.store is nullable (SET_NULL on delete)."""
        event = WebhookEvent.objects.create(
            webhook_id="wh_no_store",
            topic="products/create",
            shop_domain="orphan.myshopify.com",
            store=None,
            status=WebhookEvent.Status.RECEIVED,
            payload_hash="f" * 64,
        )
        assert event.store is None

    def test_status_choices(self):
        assert WebhookEvent.Status.RECEIVED == "received"
        assert WebhookEvent.Status.PROCESSING == "processing"
        assert WebhookEvent.Status.SUCCESS == "success"
        assert WebhookEvent.Status.FAILED == "failed"
        assert WebhookEvent.Status.DUPLICATE == "duplicate"
