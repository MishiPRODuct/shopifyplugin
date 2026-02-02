"""Tests for webhook handlers — inventory and promotion."""

import uuid
from unittest.mock import MagicMock, call, patch

import pytest

from dos.tests.factories import StoreFactory
from shopify_webhooks.handlers.inventory import (
    _cache_variant_mappings,
    _inv_item_cache_key,
    _resolve_inventory_item_to_barcode,
    handle_inventory_level_update,
    handle_product_create,
    handle_product_delete,
    handle_product_update,
)
from shopify_webhooks.models import ShopifyWebhookConfig, WebhookEvent

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(store, **overrides):
    defaults = {
        "store": store,
        "retailer_id": uuid.uuid4(),
        "shopify_domain": "test-shop.myshopify.com",
        "api_access_token": "shpat_test",
        "webhook_secret": "secret",
    }
    defaults.update(overrides)
    return ShopifyWebhookConfig.objects.create(**defaults)


def _make_event(store, topic="products/create"):
    return WebhookEvent.objects.create(
        webhook_id=f"wh_{uuid.uuid4().hex[:12]}",
        topic=topic,
        shop_domain="test-shop.myshopify.com",
        store=store,
        status=WebhookEvent.Status.RECEIVED,
        payload_hash="a" * 64,
    )


SAMPLE_PRODUCT_PAYLOAD = {
    "id": 7524702552295,
    "title": "Test Product",
    "body_html": "<p>Description</p>",
    "product_type": "Widget",
    "status": "active",
    "variants": [
        {
            "id": 42663392641255,
            "product_id": 7524702552295,
            "title": "Default Title",
            "price": "22.50",
            "option1": "Default Title",
            "barcode": "014926411246",
            "sku": None,
            "inventory_item_id": 44758024388839,
            "inventory_quantity": 200,
            "image_id": None,
            "taxable": True,
        },
    ],
    "options": [
        {"name": "Title", "position": 1, "values": ["Default Title"]}
    ],
    "images": [],
}


# ---------------------------------------------------------------------------
# handle_product_create
# ---------------------------------------------------------------------------


class TestHandleProductCreate:
    @patch("shopify_webhooks.handlers.inventory.send_to_inventory_service")
    @patch("shopify_webhooks.handlers.inventory.map_shopify_product_to_inventory")
    def test_calls_mapping_and_sends(self, mock_map, mock_send, store):
        config = _make_config(store)
        event = _make_event(store, "products/create")
        mock_map.return_value = [{"name": "Item", "barcodes": ["123"]}]

        handle_product_create(event, SAMPLE_PRODUCT_PAYLOAD)

        mock_map.assert_called_once_with(SAMPLE_PRODUCT_PAYLOAD, config)
        mock_send.assert_called_once_with(
            [{"name": "Item", "barcodes": ["123"]}],
            str(store.store_id),
            str(config.retailer_id),
        )

    @patch("shopify_webhooks.handlers.inventory.send_to_inventory_service")
    @patch("shopify_webhooks.handlers.inventory.map_shopify_product_to_inventory")
    def test_caches_variant_mappings(self, mock_map, mock_send, store, mocker):
        _make_config(store)
        event = _make_event(store, "products/create")
        mock_map.return_value = []
        mock_cache = mocker.patch(
            "shopify_webhooks.handlers.inventory.cache"
        )

        handle_product_create(event, SAMPLE_PRODUCT_PAYLOAD)

        # Should have cached the variant's inventory_item_id → barcode
        mock_cache.set.assert_called()
        call_args = mock_cache.set.call_args
        cache_key = call_args[0][0]
        cached_value = call_args[0][1]
        assert "44758024388839" in cache_key
        assert cached_value == "014926411246"


# ---------------------------------------------------------------------------
# handle_product_update
# ---------------------------------------------------------------------------


class TestHandleProductUpdate:
    @patch("shopify_webhooks.handlers.inventory.send_to_inventory_service")
    @patch("shopify_webhooks.handlers.inventory.map_shopify_product_to_inventory")
    def test_calls_mapping_and_sends(self, mock_map, mock_send, store):
        config = _make_config(store)
        event = _make_event(store, "products/update")
        mock_map.return_value = [{"name": "Updated"}]

        handle_product_update(event, SAMPLE_PRODUCT_PAYLOAD)

        mock_map.assert_called_once_with(SAMPLE_PRODUCT_PAYLOAD, config)
        mock_send.assert_called_once()


# ---------------------------------------------------------------------------
# handle_product_delete
# ---------------------------------------------------------------------------


class TestHandleProductDelete:
    @patch("shopify_webhooks.handlers.inventory.InventoryV1Client")
    def test_zeros_stock_for_all_variants(self, mock_client_cls, store):
        config = _make_config(store)
        event = _make_event(store, "products/delete")

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.list_variants_by_filters.return_value = {
            "items": [
                {"barcodes": ["BC-001"]},
                {"barcodes": ["BC-002"]},
            ]
        }

        handle_product_delete(event, {"id": 7524702552295})

        mock_client.update_inventory.assert_called_once()
        payload = mock_client.update_inventory.call_args[0][0]
        assert payload["performInserts"] is False
        assert len(payload["items"]) == 2
        for item in payload["items"]:
            assert item["stockLevel"] == 0
            assert item["operation"] == "upsert"

    @patch("shopify_webhooks.handlers.inventory.InventoryV1Client")
    def test_no_variants_found_logs_warning(self, mock_client_cls, store):
        _make_config(store)
        event = _make_event(store, "products/delete")

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.list_variants_by_filters.return_value = {"items": []}

        # Should not raise, just log warning.
        handle_product_delete(event, {"id": 9999})
        mock_client.update_inventory.assert_not_called()

    def test_missing_product_id_raises(self, store):
        _make_config(store)
        event = _make_event(store, "products/delete")
        with pytest.raises(ValueError, match="Missing product ID"):
            handle_product_delete(event, {})

    @patch("shopify_webhooks.handlers.inventory.InventoryV1Client")
    def test_skips_variants_without_barcodes(self, mock_client_cls, store):
        _make_config(store)
        event = _make_event(store, "products/delete")

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.list_variants_by_filters.return_value = {
            "items": [
                {"barcodes": ["BC-001"]},
                {"barcodes": []},  # No barcodes — should be skipped.
            ]
        }

        handle_product_delete(event, {"id": 123})

        payload = mock_client.update_inventory.call_args[0][0]
        assert len(payload["items"]) == 1
        assert payload["items"][0]["barcodes"] == ["BC-001"]


# ---------------------------------------------------------------------------
# handle_inventory_level_update (stock level)
# ---------------------------------------------------------------------------


class TestHandleInventoryLevelUpdate:
    @patch("shopify_webhooks.handlers.inventory._resolve_inventory_item_to_barcode")
    @patch("shopify_webhooks.handlers.inventory.InventoryV1Client")
    def test_updates_correct_variant(
        self, mock_client_cls, mock_resolve, store
    ):
        _make_config(store)
        event = _make_event(store, "inventory_levels/update")

        mock_resolve.return_value = "BC-001"
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        payload = {
            "inventory_item_id": 44758024388839,
            "available": 15,
            "updated_at": "2025-01-01T00:00:00Z",
        }

        handle_inventory_level_update(event, payload)

        mock_client.update_inventory.assert_called_once()
        update_payload = mock_client.update_inventory.call_args[0][0]
        assert update_payload["items"][0]["barcodes"] == ["BC-001"]
        assert update_payload["items"][0]["stockLevel"] == 15
        assert update_payload["performInserts"] is False

    @patch("shopify_webhooks.handlers.inventory._resolve_inventory_item_to_barcode")
    @patch("shopify_webhooks.handlers.inventory.InventoryV1Client")
    def test_negative_available_clamped_to_zero(
        self, mock_client_cls, mock_resolve, store
    ):
        _make_config(store)
        event = _make_event(store, "inventory_levels/update")

        mock_resolve.return_value = "BC-NEG"
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        payload = {"inventory_item_id": 123, "available": -5}

        handle_inventory_level_update(event, payload)

        update_payload = mock_client.update_inventory.call_args[0][0]
        assert update_payload["items"][0]["stockLevel"] == 0

    @patch("shopify_webhooks.handlers.inventory.InventoryV1Client")
    def test_available_null_skips_update(self, mock_client_cls, store):
        _make_config(store)
        event = _make_event(store, "inventory_levels/update")

        payload = {"inventory_item_id": 123, "available": None}

        handle_inventory_level_update(event, payload)
        mock_client_cls.assert_not_called()

    def test_missing_inventory_item_id_raises(self, store):
        _make_config(store)
        event = _make_event(store, "inventory_levels/update")
        with pytest.raises(ValueError, match="Missing inventory_item_id"):
            handle_inventory_level_update(event, {"available": 10})


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


class TestCacheVariantMappings:
    def test_caches_barcode_for_each_variant(self, mocker):
        mock_cache = mocker.patch(
            "shopify_webhooks.handlers.inventory.cache"
        )
        payload = {
            "variants": [
                {
                    "inventory_item_id": 111,
                    "barcode": "BARCODE-A",
                    "sku": "SKU-A",
                    "id": 1,
                },
                {
                    "inventory_item_id": 222,
                    "barcode": "",
                    "sku": "SKU-B",
                    "id": 2,
                },
            ]
        }

        _cache_variant_mappings(payload, "shop.myshopify.com")

        assert mock_cache.set.call_count == 2
        # First variant uses barcode.
        first_call = mock_cache.set.call_args_list[0]
        assert first_call[0][1] == "BARCODE-A"
        # Second variant falls back to SKU.
        second_call = mock_cache.set.call_args_list[1]
        assert second_call[0][1] == "SKU-B"

    def test_skips_variant_without_inventory_item_id(self, mocker):
        mock_cache = mocker.patch(
            "shopify_webhooks.handlers.inventory.cache"
        )
        payload = {"variants": [{"id": 1, "barcode": "X"}]}

        _cache_variant_mappings(payload, "shop.myshopify.com")
        mock_cache.set.assert_not_called()


class TestResolveInventoryItemToBarcode:
    def test_cache_hit(self, mocker):
        mock_cache = mocker.patch(
            "shopify_webhooks.handlers.inventory.cache"
        )
        mock_cache.get.return_value = "CACHED-BARCODE"

        config = MagicMock()
        config.shopify_domain = "shop.myshopify.com"

        result = _resolve_inventory_item_to_barcode(12345, config)
        assert result == "CACHED-BARCODE"

    @patch("shopify_webhooks.handlers.inventory.http_requests")
    def test_cache_miss_calls_shopify_api(self, mock_requests, mocker):
        mock_cache = mocker.patch(
            "shopify_webhooks.handlers.inventory.cache"
        )
        mock_cache.get.return_value = None

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "inventory_item": {"sku": "API-SKU"}
        }
        mock_response.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_response

        config = MagicMock()
        config.shopify_domain = "shop.myshopify.com"
        config.api_version = "2024-07"
        config.api_access_token = "shpat_test"

        result = _resolve_inventory_item_to_barcode(12345, config)

        assert result == "API-SKU"
        mock_requests.get.assert_called_once()
        call_url = mock_requests.get.call_args[0][0]
        assert "12345" in call_url
        assert "2024-07" in call_url
        # Should cache the result.
        mock_cache.set.assert_called_once()

    @patch("shopify_webhooks.handlers.inventory.http_requests")
    def test_api_sku_null_falls_back_to_item_id(self, mock_requests, mocker):
        mock_cache = mocker.patch(
            "shopify_webhooks.handlers.inventory.cache"
        )
        mock_cache.get.return_value = None

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "inventory_item": {"sku": None}
        }
        mock_response.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_response

        config = MagicMock()
        config.shopify_domain = "shop.myshopify.com"
        config.api_version = "2024-07"
        config.api_access_token = "shpat_test"

        result = _resolve_inventory_item_to_barcode(99999, config)
        assert result == "99999"


# ===========================================================================
# Promotion handlers
# ===========================================================================

from shopify_webhooks.handlers.promotions import (
    handle_collection_update,
    handle_price_rule_create,
    handle_price_rule_delete,
    handle_price_rule_update,
)

SAMPLE_PRICE_RULE_PAYLOAD = {
    "id": 55555,
    "title": "10% Off Everything",
    "target_type": "line_item",
    "target_selection": "entitled",
    "value_type": "percentage",
    "value": "-10.0",
    "starts_at": "2025-01-01T00:00:00+00:00",
    "ends_at": "2025-12-31T23:59:59+00:00",
    "once_per_customer": False,
    "allocation_method": "across",
    "entitled_product_ids": [111],
    "entitled_variant_ids": [],
    "entitled_collection_ids": [],
    "prerequisite_subtotal_range": None,
}


# ---------------------------------------------------------------------------
# handle_price_rule_create
# ---------------------------------------------------------------------------


class TestHandlePriceRuleCreate:
    @patch("shopify_webhooks.handlers.promotions.mpay_promo")
    @patch("shopify_webhooks.handlers.promotions.build_easy_promotion")
    @patch("shopify_webhooks.handlers.promotions.determine_family")
    def test_creates_easy_promo(
        self, mock_family, mock_build, mock_mpay, store
    ):
        _make_config(store)
        event = _make_event(store, "price_rules/create")

        mock_family.return_value = "e"
        mock_promo = MagicMock()
        mock_promo.promo_id = "55555"
        mock_promo.family = "e"
        mock_build.return_value = mock_promo

        handle_price_rule_create(event, SAMPLE_PRICE_RULE_PAYLOAD)

        mock_build.assert_called_once()
        mock_mpay.PromotionBatchOperation.return_value.create.assert_called_once_with(
            mock_promo
        )
        mock_mpay.PromotionBatchOperation.return_value.commit.assert_called_once()

    @patch("shopify_webhooks.handlers.promotions.mpay_promo")
    @patch("shopify_webhooks.handlers.promotions.determine_family")
    def test_unmappable_price_rule_skips(
        self, mock_family, mock_mpay, store
    ):
        _make_config(store)
        event = _make_event(store, "price_rules/create")

        # Shipping-type rule → None family.
        mock_family.return_value = None

        payload = {**SAMPLE_PRICE_RULE_PAYLOAD, "target_type": "shipping_line"}
        handle_price_rule_create(event, payload)

        mock_mpay.PromotionBatchOperation.assert_not_called()


# ---------------------------------------------------------------------------
# handle_price_rule_update
# ---------------------------------------------------------------------------


class TestHandlePriceRuleUpdate:
    @patch("shopify_webhooks.handlers.promotions.mpay_promo")
    @patch("shopify_webhooks.handlers.promotions.build_easy_promotion")
    @patch("shopify_webhooks.handlers.promotions.determine_family")
    def test_deletes_then_creates(
        self, mock_family, mock_build, mock_mpay, store
    ):
        _make_config(store)
        event = _make_event(store, "price_rules/update")

        mock_family.return_value = "e"
        mock_promo = MagicMock()
        mock_promo.promo_id = "55555"
        mock_promo.family = "e"
        mock_build.return_value = mock_promo

        handle_price_rule_update(event, SAMPLE_PRICE_RULE_PAYLOAD)

        batch_op = mock_mpay.PromotionBatchOperation.return_value
        # delete is called before create.
        batch_op.delete.assert_called_once()
        batch_op.create.assert_called_once_with(mock_promo)
        batch_op.commit.assert_called_once()

        # The delete promo should use the price rule ID.
        delete_promo_arg = batch_op.delete.call_args[0][0]
        assert delete_promo_arg.promo_id == "55555"


# ---------------------------------------------------------------------------
# handle_price_rule_delete
# ---------------------------------------------------------------------------


class TestHandlePriceRuleDelete:
    @patch("shopify_webhooks.handlers.promotions.mpay_promo")
    def test_soft_deletes(self, mock_mpay, store):
        _make_config(store)
        event = _make_event(store, "price_rules/delete")

        handle_price_rule_delete(event, {"id": 55555})

        batch_op = mock_mpay.PromotionBatchOperation.return_value
        batch_op.delete.assert_called_once()
        batch_op.commit.assert_called_once()

        delete_promo_arg = batch_op.delete.call_args[0][0]
        assert delete_promo_arg.promo_id == "55555"

    def test_missing_id_raises(self, store):
        _make_config(store)
        event = _make_event(store, "price_rules/delete")
        with pytest.raises(ValueError, match="Missing price rule ID"):
            handle_price_rule_delete(event, {})


# ---------------------------------------------------------------------------
# handle_collection_update
# ---------------------------------------------------------------------------


class TestHandleCollectionUpdate:
    @patch("shopify_webhooks.handlers.promotions.mpay_promo")
    @patch(
        "shopify_webhooks.handlers.promotions._build_promotion_for_price_rule"
    )
    @patch("shopify_webhooks.handlers.promotions.http_requests")
    def test_rebuilds_affected_promotions(
        self, mock_requests, mock_build_pr, mock_mpay, store
    ):
        _make_config(store)
        event = _make_event(store, "collections/update")

        # Simulate Shopify returning 2 price rules, 1 affected.
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "price_rules": [
                {
                    "id": 100,
                    "entitled_collection_ids": [777],
                    "prerequisite_collection_ids": [],
                },
                {
                    "id": 200,
                    "entitled_collection_ids": [],
                    "prerequisite_collection_ids": [],
                },
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {}
        mock_requests.get.return_value = mock_response

        mock_promo = MagicMock()
        mock_promo.promo_id = "100"
        mock_build_pr.return_value = mock_promo

        handle_collection_update(event, {"id": 777})

        # Only 1 price rule affected (id=100).
        mock_build_pr.assert_called_once()
        batch_op = mock_mpay.PromotionBatchOperation.return_value
        batch_op.delete.assert_called_once()
        batch_op.create.assert_called_once_with(mock_promo)
        batch_op.commit.assert_called_once()

    @patch("shopify_webhooks.handlers.promotions.mpay_promo")
    @patch("shopify_webhooks.handlers.promotions.http_requests")
    def test_no_affected_promotions_skips_commit(
        self, mock_requests, mock_mpay, store
    ):
        _make_config(store)
        event = _make_event(store, "collections/update")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "price_rules": [
                {
                    "id": 100,
                    "entitled_collection_ids": [999],
                    "prerequisite_collection_ids": [],
                },
            ]
        }
        mock_response.headers = {}
        mock_requests.get.return_value = mock_response

        # Collection 777 is not referenced by any price rule.
        handle_collection_update(event, {"id": 777})

        mock_mpay.PromotionBatchOperation.return_value.commit.assert_not_called()

    def test_missing_collection_id_raises(self, store):
        _make_config(store)
        event = _make_event(store, "collections/update")
        with pytest.raises(ValueError, match="Missing collection ID"):
            handle_collection_update(event, {})
