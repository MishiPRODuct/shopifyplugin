"""Tests for inventory sync service — field mapping."""

import uuid
from unittest.mock import MagicMock

import pytest

from shopify_webhooks.services.inventory_sync import (
    _build_pricing_guidance,
    _determine_theme,
    _get_variant_barcode,
    _get_variant_images,
    map_shopify_product_to_inventory,
    send_to_inventory_service,
    strip_html,
)

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixtures: realistic Shopify product payloads
# ---------------------------------------------------------------------------

MULTI_VARIANT_PRODUCT = {
    "id": 7524702552295,
    "title": "#MyConfidant Conditioner",
    "body_html": (
        "<p>Make your hair feel oh so soft and super clean with this "
        "conditioner!</p>"
    ),
    "vendor": "#myDentity",
    "product_type": "Conditioner",
    "status": "active",
    "tags": "acorn import, Conditioner, Shine",
    "variants": [
        {
            "id": 42663392641255,
            "product_id": 7524702552295,
            "title": "10 oz",
            "price": "22.50",
            "option1": "10 oz",
            "option2": None,
            "option3": None,
            "taxable": True,
            "barcode": "014926411246",
            "sku": None,
            "inventory_item_id": 44758024388839,
            "inventory_quantity": 200,
            "image_id": 40275842203879,
            "requires_shipping": True,
        },
        {
            "id": 42391589617895,
            "product_id": 7524702552295,
            "title": "LTR",
            "price": "45.00",
            "option1": "LTR",
            "option2": None,
            "option3": None,
            "taxable": True,
            "barcode": "014926411253",
            "sku": None,
            "inventory_item_id": 44485818384615,
            "inventory_quantity": 200,
            "image_id": 40275842236647,
            "requires_shipping": True,
        },
    ],
    "options": [
        {
            "id": 9576870150375,
            "product_id": 7524702552295,
            "name": "Size",
            "position": 1,
            "values": ["10 oz", "LTR"],
        }
    ],
    "images": [
        {
            "id": 40275842203879,
            "position": 1,
            "product_id": 7524702552295,
            "src": "https://cdn.shopify.com/products/277190.png",
            "variant_ids": [42663392641255],
        },
        {
            "id": 40275842236647,
            "position": 2,
            "product_id": 7524702552295,
            "src": "https://cdn.shopify.com/products/277191.png",
            "variant_ids": [42391589617895],
        },
    ],
}

SINGLE_VARIANT_PRODUCT = {
    "id": 9999999,
    "title": "Simple Widget",
    "body_html": "A simple widget.",
    "product_type": "Widgets",
    "status": "active",
    "variants": [
        {
            "id": 1111111,
            "product_id": 9999999,
            "title": "Default Title",
            "price": "10.00",
            "option1": "Default Title",
            "option2": None,
            "option3": None,
            "taxable": True,
            "barcode": "WIDGET001",
            "sku": "WDG-001",
            "inventory_quantity": 50,
            "inventory_item_id": 2222222,
            "image_id": None,
        },
    ],
    "options": [
        {"name": "Title", "position": 1, "values": ["Default Title"]}
    ],
    "images": [
        {
            "id": 3333333,
            "src": "https://cdn.shopify.com/widget.png",
            "variant_ids": [],
        }
    ],
}


def _make_config(**extra_data_overrides):
    """Build a mock ShopifyWebhookConfig with extra_data."""
    config = MagicMock()
    config.extra_data = extra_data_overrides
    config.retailer_id = uuid.uuid4()
    return config


# ---------------------------------------------------------------------------
# strip_html
# ---------------------------------------------------------------------------


class TestStripHtml:
    def test_strips_tags(self):
        assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_empty_string(self):
        assert strip_html("") == ""

    def test_none_input(self):
        assert strip_html(None) == ""

    def test_preserves_plain_text(self):
        assert strip_html("No tags here") == "No tags here"

    def test_collapses_whitespace(self):
        result = strip_html("<p>Line 1</p>\n\n<p>Line 2</p>")
        assert result == "Line 1 Line 2"

    def test_nested_tags(self):
        assert strip_html("<div><span>nested</span></div>") == "nested"


# ---------------------------------------------------------------------------
# _get_variant_barcode
# ---------------------------------------------------------------------------


class TestGetVariantBarcode:
    def test_barcode_present(self):
        variant = {"id": 1, "barcode": "123456", "sku": "SKU-1"}
        assert _get_variant_barcode(variant) == "123456"

    def test_fallback_to_sku(self):
        variant = {"id": 1, "barcode": "", "sku": "SKU-1"}
        assert _get_variant_barcode(variant) == "SKU-1"

    def test_barcode_none_fallback_to_sku(self):
        variant = {"id": 1, "barcode": None, "sku": "SKU-1"}
        assert _get_variant_barcode(variant) == "SKU-1"

    def test_fallback_to_variant_id(self):
        variant = {"id": 42, "barcode": None, "sku": None}
        assert _get_variant_barcode(variant) == "42"

    def test_all_empty_fallback_to_variant_id(self):
        variant = {"id": 99, "barcode": "", "sku": ""}
        assert _get_variant_barcode(variant) == "99"

    def test_no_fields_returns_empty_string(self):
        assert _get_variant_barcode({}) == ""


# ---------------------------------------------------------------------------
# _get_variant_images
# ---------------------------------------------------------------------------


class TestGetVariantImages:
    def test_variant_specific_image(self):
        variant = {"id": 100}
        images = [
            {"src": "img1.png", "variant_ids": [100]},
            {"src": "img2.png", "variant_ids": [200]},
        ]
        assert _get_variant_images(variant, images) == ["img1.png"]

    def test_fallback_to_first_product_image(self):
        variant = {"id": 999}
        images = [
            {"src": "first.png", "variant_ids": [100]},
            {"src": "second.png", "variant_ids": [200]},
        ]
        assert _get_variant_images(variant, images) == ["first.png"]

    def test_no_product_images(self):
        assert _get_variant_images({"id": 1}, []) == []

    def test_multiple_images_for_variant(self):
        variant = {"id": 100}
        images = [
            {"src": "a.png", "variant_ids": [100]},
            {"src": "b.png", "variant_ids": [100]},
        ]
        assert _get_variant_images(variant, images) == ["a.png", "b.png"]

    def test_skips_images_with_empty_src(self):
        variant = {"id": 100}
        images = [{"src": "", "variant_ids": [100]}]
        # Empty src is skipped, and fallback also has empty src
        assert _get_variant_images(variant, images) == []


# ---------------------------------------------------------------------------
# map_shopify_product_to_inventory — core mapping
# ---------------------------------------------------------------------------


class TestMapShopifyProductToInventory:
    """Full mapping tests using realistic payloads."""

    def test_multi_variant_product_creates_two_items(self):
        config = _make_config()
        items = map_shopify_product_to_inventory(MULTI_VARIANT_PRODUCT, config)
        assert len(items) == 2

    def test_variant_names(self):
        config = _make_config()
        items = map_shopify_product_to_inventory(MULTI_VARIANT_PRODUCT, config)
        assert items[0]["name"] == "#MyConfidant Conditioner - 10 oz"
        assert items[1]["name"] == "#MyConfidant Conditioner - LTR"

    def test_single_variant_default_title_not_appended(self):
        config = _make_config()
        items = map_shopify_product_to_inventory(SINGLE_VARIANT_PRODUCT, config)
        assert len(items) == 1
        assert items[0]["name"] == "Simple Widget"

    def test_html_stripped_from_description(self):
        config = _make_config()
        items = map_shopify_product_to_inventory(MULTI_VARIANT_PRODUCT, config)
        desc = items[0]["description"]
        assert "<p>" not in desc
        assert "conditioner!" in desc

    def test_retailer_product_id(self):
        config = _make_config()
        items = map_shopify_product_to_inventory(MULTI_VARIANT_PRODUCT, config)
        for item in items:
            assert item["retailerProductId"] == "7524702552295"

    def test_barcodes_populated(self):
        config = _make_config()
        items = map_shopify_product_to_inventory(MULTI_VARIANT_PRODUCT, config)
        assert items[0]["barcodes"] == ["014926411246"]
        assert items[1]["barcodes"] == ["014926411253"]

    def test_base_price(self):
        config = _make_config()
        items = map_shopify_product_to_inventory(MULTI_VARIANT_PRODUCT, config)
        assert items[0]["basePrice"] == "22.50"
        assert items[1]["basePrice"] == "45.00"

    def test_stock_level(self):
        config = _make_config()
        items = map_shopify_product_to_inventory(MULTI_VARIANT_PRODUCT, config)
        assert items[0]["stockLevel"] == 200
        assert items[1]["stockLevel"] == 200

    def test_per_variant_images_matched(self):
        config = _make_config()
        items = map_shopify_product_to_inventory(MULTI_VARIANT_PRODUCT, config)
        assert items[0]["images"] == [
            "https://cdn.shopify.com/products/277190.png"
        ]
        assert items[1]["images"] == [
            "https://cdn.shopify.com/products/277191.png"
        ]

    def test_categories_from_product_type(self):
        config = _make_config()
        items = map_shopify_product_to_inventory(MULTI_VARIANT_PRODUCT, config)
        assert items[0]["categories"] == [
            {"name": "Conditioner", "image": "", "parent": None}
        ]

    def test_size_extracted_from_options(self):
        config = _make_config()
        items = map_shopify_product_to_inventory(MULTI_VARIANT_PRODUCT, config)
        assert items[0]["size"] == "10 oz"
        assert items[1]["size"] == "LTR"

    def test_colour_extracted_when_present(self):
        payload = {
            "id": 100,
            "title": "T-Shirt",
            "body_html": "",
            "product_type": "Apparel",
            "status": "active",
            "variants": [
                {
                    "id": 1,
                    "title": "Red / S",
                    "price": "20.00",
                    "option1": "Red",
                    "option2": "S",
                    "barcode": "TS-RED-S",
                    "inventory_quantity": 10,
                },
            ],
            "options": [
                {"name": "Color", "position": 1, "values": ["Red", "Blue"]},
                {"name": "Size", "position": 2, "values": ["S", "M", "L"]},
            ],
            "images": [],
        }
        config = _make_config()
        items = map_shopify_product_to_inventory(payload, config)
        assert items[0]["colour"] == "Red"
        assert items[0]["size"] == "S"

    def test_theme_invariant_for_single_default_option(self):
        config = _make_config()
        items = map_shopify_product_to_inventory(SINGLE_VARIANT_PRODUCT, config)
        assert items[0]["theme"] == "invariant"

    def test_theme_from_first_option_name(self):
        config = _make_config()
        items = map_shopify_product_to_inventory(MULTI_VARIANT_PRODUCT, config)
        assert items[0]["theme"] == "Size"

    def test_inactive_product_returns_empty(self):
        payload = {**SINGLE_VARIANT_PRODUCT, "status": "draft"}
        config = _make_config()
        items = map_shopify_product_to_inventory(payload, config)
        assert items == []

    def test_no_variants_returns_empty(self):
        payload = {
            "id": 1,
            "title": "Empty",
            "body_html": "",
            "product_type": "",
            "status": "active",
            "variants": [],
            "options": [],
            "images": [],
        }
        config = _make_config()
        assert map_shopify_product_to_inventory(payload, config) == []


# ---------------------------------------------------------------------------
# map_shopify_product_to_inventory — barcode fallback
# ---------------------------------------------------------------------------


class TestBarcodeEdgeCases:
    def test_barcode_empty_falls_back_to_sku(self):
        payload = {
            "id": 1,
            "title": "Prod",
            "body_html": "",
            "product_type": "",
            "status": "active",
            "variants": [
                {
                    "id": 10,
                    "title": "Default Title",
                    "price": "5.00",
                    "barcode": "",
                    "sku": "FALLBACK-SKU",
                    "inventory_quantity": 1,
                }
            ],
            "options": [{"name": "Title", "position": 1, "values": ["Default Title"]}],
            "images": [],
        }
        config = _make_config()
        items = map_shopify_product_to_inventory(payload, config)
        assert items[0]["barcodes"] == ["FALLBACK-SKU"]

    def test_barcode_and_sku_null_falls_back_to_variant_id(self):
        payload = {
            "id": 1,
            "title": "Prod",
            "body_html": "",
            "product_type": "",
            "status": "active",
            "variants": [
                {
                    "id": 42,
                    "title": "Default Title",
                    "price": "5.00",
                    "barcode": None,
                    "sku": None,
                    "inventory_quantity": 1,
                }
            ],
            "options": [{"name": "Title", "position": 1, "values": ["Default Title"]}],
            "images": [],
        }
        config = _make_config()
        items = map_shopify_product_to_inventory(payload, config)
        assert items[0]["barcodes"] == ["42"]


# ---------------------------------------------------------------------------
# pricingGuidance
# ---------------------------------------------------------------------------


class TestPricingGuidance:
    def test_no_tax_mapping_omits_pricing_guidance(self):
        config = _make_config()
        items = map_shopify_product_to_inventory(SINGLE_VARIANT_PRODUCT, config)
        assert "pricingGuidance" not in items[0]

    def test_tax_inclusive_pricing(self):
        config = _make_config(
            tax_mapping={
                "tax_code": "VAT20",
                "vat_percentage": 20,
                "tax_inclusive": True,
            }
        )
        variant = {"price": "120.00"}
        result = _build_pricing_guidance(variant, config)
        assert result["taxCode"] == "VAT20"
        assert result["vatPercentage"] == "20.0"
        assert result["includingVat"] == "120.0"
        assert result["excludingVat"] == "100.0"

    def test_tax_exclusive_pricing(self):
        config = _make_config(
            tax_mapping={
                "tax_code": "VAT5",
                "vat_percentage": 5,
                "tax_inclusive": False,
            }
        )
        variant = {"price": "100.00"}
        result = _build_pricing_guidance(variant, config)
        assert result["includingVat"] == "105.0"
        assert result["excludingVat"] == "100.0"

    def test_pricing_guidance_included_in_mapped_items(self):
        config = _make_config(
            tax_mapping={
                "tax_code": "STD",
                "vat_percentage": 10,
                "tax_inclusive": True,
            }
        )
        items = map_shopify_product_to_inventory(SINGLE_VARIANT_PRODUCT, config)
        assert "pricingGuidance" in items[0]
        pg = items[0]["pricingGuidance"]
        assert pg["taxCode"] == "STD"


# ---------------------------------------------------------------------------
# buyingGuidance
# ---------------------------------------------------------------------------


class TestBuyingGuidance:
    def test_no_config_omits_buying_guidance(self):
        config = _make_config()
        items = map_shopify_product_to_inventory(SINGLE_VARIANT_PRODUCT, config)
        assert "buyingGuidance" not in items[0]

    def test_buying_guidance_from_config(self):
        config = _make_config(
            buying_guidance={"restrictedItem": True, "ageRestriction": 18}
        )
        items = map_shopify_product_to_inventory(SINGLE_VARIANT_PRODUCT, config)
        assert items[0]["buyingGuidance"] == {
            "restrictedItem": True,
            "ageRestriction": 18,
        }


# ---------------------------------------------------------------------------
# send_to_inventory_service
# ---------------------------------------------------------------------------


class TestSendToInventoryService:
    def test_sends_correct_payload(self, mocker):
        mock_client_cls = mocker.patch(
            "shopify_webhooks.services.inventory_sync.InventoryV1Client"
        )
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        items = [
            {
                "name": "Widget",
                "barcodes": ["W001"],
                "basePrice": "10.00",
                "stockLevel": 5,
                "categories": [{"name": "Cat", "image": "", "parent": None}],
            }
        ]
        send_to_inventory_service(items, "store-uuid", "retailer-uuid")

        mock_client.update_inventory.assert_called_once()
        payload = mock_client.update_inventory.call_args[0][0]
        assert payload["storeId"] == "store-uuid"
        assert payload["retailerId"] == "retailer-uuid"
        assert payload["categories"] == [
            {"name": "Cat", "image": "", "parent": None}
        ]
        assert len(payload["items"]) == 1
        assert payload["items"][0]["operation"] == "upsert"
        assert payload["items"][0]["name"] == "Widget"

    def test_empty_items_does_nothing(self, mocker):
        mock_client_cls = mocker.patch(
            "shopify_webhooks.services.inventory_sync.InventoryV1Client"
        )
        send_to_inventory_service([], "s", "r")
        mock_client_cls.assert_not_called()
