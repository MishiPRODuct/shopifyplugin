"""Tests for promotion sync service — family determination, promo builders, helpers."""

import datetime
import uuid
from unittest.mock import MagicMock, patch

import pytest

from mishipay_items.mpay_promo_enums import (
    ApplicationType,
    Availability,
    DiscountOn,
    DiscountType,
    DiscountTypeStrategy,
    GroupItemSelectionCriteria,
    NodeType,
    PromoEvaluateCriteria,
    PromoFamily,
)
from shopify_webhooks.services.promotion_sync import (
    _extract_qty_or_value_min,
    build_basket_threshold_promotion,
    build_bxgy_promotion,
    build_easy_promotion,
    build_promo_groups,
    build_promotion_settings_from_config,
    compute_evaluate_priority,
    determine_family,
    extract_id,
    resolve_entitled_skus,
)

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides):
    """Build a mock ShopifyWebhookConfig."""
    config = MagicMock()
    config.store_id = uuid.uuid4()
    config.shopify_domain = "test-shop.myshopify.com"
    config.api_access_token = "shpat_test"
    config.api_version = "2024-07"
    config.extra_data = overrides.pop("extra_data", {})
    for k, v in overrides.items():
        setattr(config, k, v)
    return config


def _make_price_rule(**overrides):
    """Build a minimal Shopify price rule dict."""
    defaults = {
        "id": 12345,
        "title": "Test Promo",
        "target_type": "line_item",
        "target_selection": "entitled",
        "value_type": "percentage",
        "value": "-10.0",
        "starts_at": "2025-01-01T00:00:00+00:00",
        "ends_at": "2025-12-31T23:59:59+00:00",
        "once_per_customer": False,
        "allocation_method": "across",
        "entitled_product_ids": [111, 222],
        "entitled_variant_ids": [],
        "entitled_collection_ids": [],
        "prerequisite_subtotal_range": None,
    }
    defaults.update(overrides)
    return defaults


def _make_bxgy_discount(**overrides):
    """Build a minimal Shopify DiscountAutomaticBxgy payload."""
    defaults = {
        "id": "gid://shopify/DiscountAutomaticNode/99999",
        "title": "Buy 2 Get 1 Free",
        "summary": "Buy 2 items, get 1 free",
        "startsAt": "2025-01-01T00:00:00+00:00",
        "endsAt": "2025-12-31T23:59:59+00:00",
        "customerBuys": {
            "value": {
                "__typename": "DiscountQuantity",
                "quantity": 2,
            },
            "items": {
                "products": {
                    "edges": [
                        {"node": {"id": "gid://shopify/Product/111"}},
                    ]
                }
            },
        },
        "customerGets": {
            "value": {
                "__typename": "DiscountOnQuantity",
                "quantity": {"quantity": 1},
                "effect": {
                    "__typename": "DiscountPercentage",
                    "percentage": 100,
                },
            },
            "items": {
                "products": {
                    "edges": [
                        {"node": {"id": "gid://shopify/Product/222"}},
                    ]
                }
            },
        },
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# extract_id
# ---------------------------------------------------------------------------


class TestExtractId:
    def test_product_gid(self):
        assert extract_id("gid://shopify/Product/12345") == "12345"

    def test_variant_gid(self):
        assert extract_id("gid://shopify/ProductVariant/67890") == "67890"

    def test_collection_gid(self):
        assert extract_id("gid://shopify/Collection/100") == "100"

    def test_discount_gid(self):
        assert (
            extract_id("gid://shopify/DiscountAutomaticNode/999") == "999"
        )


# ---------------------------------------------------------------------------
# compute_evaluate_priority
# ---------------------------------------------------------------------------


class TestComputeEvaluatePriority:
    def test_percent_off_10(self):
        result = compute_evaluate_priority(DiscountType.PERCENT_OFF.value, "10")
        assert result == 90

    def test_percent_off_50(self):
        result = compute_evaluate_priority(DiscountType.PERCENT_OFF.value, "50")
        assert result == 50

    def test_percent_off_100(self):
        result = compute_evaluate_priority(DiscountType.PERCENT_OFF.value, "100")
        assert result == 0

    def test_value_off(self):
        result = compute_evaluate_priority(DiscountType.VALUE_OFF.value, "5")
        assert result == 2000

    def test_zero_value_returns_max(self):
        result = compute_evaluate_priority(DiscountType.VALUE_OFF.value, "0")
        assert result == 32767


# ---------------------------------------------------------------------------
# determine_family — Section 6.1 mapping table
# ---------------------------------------------------------------------------


class TestDetermineFamily:
    """Each row of the Section 6.1 mapping table."""

    def test_line_item_entitled_returns_easy(self):
        pr = {"target_type": "line_item", "target_selection": "entitled"}
        assert determine_family(pr) == PromoFamily.EASY.value

    def test_line_item_all_returns_basket_threshold(self):
        pr = {"target_type": "line_item", "target_selection": "all"}
        assert determine_family(pr) == PromoFamily.BASKET_THRESHOLD.value

    def test_shipping_line_returns_none(self):
        pr = {"target_type": "shipping_line", "target_selection": "all"}
        assert determine_family(pr) is None

    def test_no_target_type_returns_none(self):
        assert determine_family({}) is None

    def test_unknown_target_selection_returns_none(self):
        pr = {"target_type": "line_item", "target_selection": "unknown"}
        assert determine_family(pr) is None


# ---------------------------------------------------------------------------
# build_promotion_settings_from_config
# ---------------------------------------------------------------------------


class TestBuildPromotionSettingsFromConfig:
    def test_builds_correct_urls(self):
        config = _make_config()
        result = build_promotion_settings_from_config(config)
        base = "https://test-shop.myshopify.com/admin/api/2024-07"
        assert result["access_token"] == "shpat_test"
        assert result["products_in_collection_fetch_endpoint"] == f"{base}/collections"
        assert result["products_sku_fetch_endpoint"] == f"{base}/products"
        assert result["variants_sku_fetch_endpoint"] == f"{base}/variants"


# ---------------------------------------------------------------------------
# build_promo_groups
# ---------------------------------------------------------------------------


class TestBuildPromoGroups:
    def test_single_group_with_nodes(self):
        skus = {"skus": ["BC-001", "BC-002"]}
        groups = build_promo_groups("PR-123", skus)
        assert len(groups) == 1
        group = groups[0]
        assert group.name == "PR-123"
        assert group.qty_or_value_min == 1
        assert group.qty_or_value_max is None
        assert len(group.nodes) == 2
        assert group.nodes[0].node_id == "BC-001"
        assert group.nodes[0].node_type == NodeType.ITEM.value
        assert group.nodes[1].node_id == "BC-002"

    def test_custom_qty_min(self):
        skus = {"skus": ["X"]}
        groups = build_promo_groups("P1", skus, qty_or_value_min=5)
        assert groups[0].qty_or_value_min == 5

    def test_skips_empty_skus(self):
        skus = {"skus": ["BC-001", None, "", "BC-002"]}
        groups = build_promo_groups("P1", skus)
        assert len(groups[0].nodes) == 2

    def test_empty_skus_list(self):
        skus = {"skus": []}
        groups = build_promo_groups("P1", skus)
        assert len(groups[0].nodes) == 0


# ---------------------------------------------------------------------------
# resolve_entitled_skus
# ---------------------------------------------------------------------------


class TestResolveEntitledSkus:
    @patch("shopify_webhooks.services.promotion_sync.get_products_sku")
    def test_resolves_product_ids(self, mock_fn):
        mock_fn.return_value = {"skus": ["BC-1"]}
        pr = _make_price_rule(entitled_product_ids=[111])
        result = resolve_entitled_skus(pr, {})
        assert result == {"skus": ["BC-1"]}
        mock_fn.assert_called_once()

    @patch("shopify_webhooks.services.promotion_sync.get_sku_from_variants")
    def test_resolves_variant_ids(self, mock_fn):
        mock_fn.return_value = {"skus": ["BC-2"]}
        pr = _make_price_rule(
            entitled_product_ids=[],
            entitled_variant_ids=[333],
        )
        result = resolve_entitled_skus(pr, {})
        assert result == {"skus": ["BC-2"]}

    @patch(
        "shopify_webhooks.services.promotion_sync.get_products_from_collections"
    )
    def test_resolves_collection_ids(self, mock_fn):
        mock_fn.return_value = {"skus": ["BC-3"]}
        pr = _make_price_rule(
            entitled_product_ids=[],
            entitled_variant_ids=[],
            entitled_collection_ids=[444],
        )
        result = resolve_entitled_skus(pr, {})
        assert result == {"skus": ["BC-3"]}

    def test_raises_when_no_entitled_items(self):
        pr = _make_price_rule(
            entitled_product_ids=[],
            entitled_variant_ids=[],
            entitled_collection_ids=[],
        )
        with pytest.raises(ValueError, match="no entitled items"):
            resolve_entitled_skus(pr, {})


# ---------------------------------------------------------------------------
# build_easy_promotion — percentage and fixed amount
# ---------------------------------------------------------------------------


class TestBuildEasyPromotion:
    @patch("shopify_webhooks.services.promotion_sync.resolve_entitled_skus")
    def test_percentage_discount(self, mock_resolve):
        mock_resolve.return_value = {"skus": ["BC-001"]}
        config = _make_config()
        pr = _make_price_rule(
            value_type="percentage",
            value="-15.0",
        )
        promo = build_easy_promotion(pr, config)

        assert promo.family == PromoFamily.EASY.value
        assert promo.discount_type == DiscountType.PERCENT_OFF.value
        assert float(promo.discount_value) == 15.0
        assert promo.promo_id == "12345"
        assert promo.layer == "1"
        assert promo.availability == Availability.ALL.value
        assert promo.discount_value_on == DiscountOn.FP.value

    @patch("shopify_webhooks.services.promotion_sync.resolve_entitled_skus")
    def test_fixed_amount_discount(self, mock_resolve):
        mock_resolve.return_value = {"skus": ["BC-001"]}
        config = _make_config()
        pr = _make_price_rule(
            value_type="fixed_amount",
            value="-5.00",
        )
        promo = build_easy_promotion(pr, config)

        assert promo.discount_type == DiscountType.VALUE_OFF.value
        assert float(promo.discount_value) == 5.0

    @patch("shopify_webhooks.services.promotion_sync.resolve_entitled_skus")
    def test_once_per_customer(self, mock_resolve):
        mock_resolve.return_value = {"skus": ["BC-001"]}
        config = _make_config()
        pr = _make_price_rule(once_per_customer=True)
        promo = build_easy_promotion(pr, config)
        assert promo.max_application_limit == 1

    @patch("shopify_webhooks.services.promotion_sync.resolve_entitled_skus")
    def test_allocation_method_each(self, mock_resolve):
        mock_resolve.return_value = {"skus": ["BC-001"]}
        config = _make_config()
        pr = _make_price_rule(allocation_method="each")
        promo = build_easy_promotion(pr, config)
        assert promo.discount_type_strategy == DiscountTypeStrategy.EACH_ITEM.value

    @patch("shopify_webhooks.services.promotion_sync.resolve_entitled_skus")
    def test_allocation_method_across(self, mock_resolve):
        mock_resolve.return_value = {"skus": ["BC-001"]}
        config = _make_config()
        pr = _make_price_rule(allocation_method="across")
        promo = build_easy_promotion(pr, config)
        assert promo.discount_type_strategy == DiscountTypeStrategy.ALL_ITEMS.value

    @patch("shopify_webhooks.services.promotion_sync.resolve_entitled_skus")
    def test_groups_built_from_resolved_skus(self, mock_resolve):
        mock_resolve.return_value = {"skus": ["BC-001", "BC-002"]}
        config = _make_config()
        pr = _make_price_rule()
        promo = build_easy_promotion(pr, config)

        assert len(promo.groups) == 1
        assert len(promo.groups[0].nodes) == 2
        assert promo.groups[0].nodes[0].node_id == "BC-001"
        assert promo.groups[0].nodes[0].node_type == NodeType.ITEM.value

    @patch("shopify_webhooks.services.promotion_sync.resolve_entitled_skus")
    def test_unknown_value_type_raises(self, mock_resolve):
        mock_resolve.return_value = {"skus": ["BC-001"]}
        config = _make_config()
        pr = _make_price_rule(value_type="bogus")
        with pytest.raises(ValueError, match="Unknown discount value_type"):
            build_easy_promotion(pr, config)

    @patch("shopify_webhooks.services.promotion_sync.resolve_entitled_skus")
    def test_promo_retailer_from_extra_data(self, mock_resolve):
        mock_resolve.return_value = {"skus": ["BC-001"]}
        config = _make_config(extra_data={"promo_retailer": "EVOKES-AU"})
        pr = _make_price_rule()
        promo = build_easy_promotion(pr, config)
        assert promo.retailer == "EVOKES-AU"


# ---------------------------------------------------------------------------
# build_basket_threshold_promotion
# ---------------------------------------------------------------------------


class TestBuildBasketThresholdPromotion:
    def test_basic_basket_threshold(self):
        config = _make_config()
        pr = _make_price_rule(
            target_selection="all",
            value_type="percentage",
            value="-20.0",
        )
        promo = build_basket_threshold_promotion(pr, config)

        assert promo.family == PromoFamily.BASKET_THRESHOLD.value
        assert promo.layer == 100
        assert promo.discount_apply_type == ApplicationType.BASKET.value
        assert promo.discount_type == DiscountType.PERCENT_OFF.value
        assert float(promo.discount_value) == 20.0

    def test_single_group_with_all_node(self):
        config = _make_config()
        pr = _make_price_rule(target_selection="all")
        promo = build_basket_threshold_promotion(pr, config)

        assert len(promo.groups) == 1
        group = promo.groups[0]
        assert len(group.nodes) == 1
        assert group.nodes[0].node_id == "all"
        assert group.nodes[0].node_type == NodeType.ITEM.value

    def test_prerequisite_subtotal_range(self):
        config = _make_config()
        pr = _make_price_rule(
            target_selection="all",
            prerequisite_subtotal_range={
                "greater_than_or_equal_to": "50.00"
            },
        )
        promo = build_basket_threshold_promotion(pr, config)
        assert promo.groups[0].qty_or_value_min == "50.00"

    def test_no_subtotal_range_defaults_to_1(self):
        config = _make_config()
        pr = _make_price_rule(
            target_selection="all",
            prerequisite_subtotal_range=None,
        )
        promo = build_basket_threshold_promotion(pr, config)
        assert promo.groups[0].qty_or_value_min == 1

    def test_fixed_amount_discount(self):
        config = _make_config()
        pr = _make_price_rule(
            target_selection="all",
            value_type="fixed_amount",
            value="-10.00",
        )
        promo = build_basket_threshold_promotion(pr, config)
        assert promo.discount_type == DiscountType.VALUE_OFF.value
        assert float(promo.discount_value) == 10.0

    def test_missing_title_raises(self):
        config = _make_config()
        pr = _make_price_rule(target_selection="all", title="")
        with pytest.raises(ValueError, match="requires a title"):
            build_basket_threshold_promotion(pr, config)

    def test_once_per_customer(self):
        config = _make_config()
        pr = _make_price_rule(
            target_selection="all", once_per_customer=True
        )
        promo = build_basket_threshold_promotion(pr, config)
        assert promo.max_application_limit == 1


# ---------------------------------------------------------------------------
# build_bxgy_promotion — 2-group structure
# ---------------------------------------------------------------------------


class TestBuildBxgyPromotion:
    @patch("shopify_webhooks.services.promotion_sync.resolve_skus_from_edges")
    def test_two_group_structure(self, mock_resolve):
        # First call = target (customerGets), second = requisite (customerBuys)
        mock_resolve.side_effect = [
            {"skus": ["TARGET-BC"]},
            {"skus": ["REQ-BC"]},
        ]
        config = _make_config()
        discount = _make_bxgy_discount()
        promo = build_bxgy_promotion(discount, config)

        assert promo.family == PromoFamily.REQUISITE_GROUPS_WITH_DISCOUNTED_TARGET.value
        assert promo.target_discounted_group_name == "g2"
        assert len(promo.groups) == 2
        assert promo.groups[0].name == "g1"
        assert promo.groups[1].name == "g2"

    @patch("shopify_webhooks.services.promotion_sync.resolve_skus_from_edges")
    def test_requisite_group_nodes(self, mock_resolve):
        mock_resolve.side_effect = [
            {"skus": ["T1"]},
            {"skus": ["R1", "R2"]},
        ]
        config = _make_config()
        discount = _make_bxgy_discount()
        promo = build_bxgy_promotion(discount, config)

        g1 = promo.groups[0]
        assert len(g1.nodes) == 2
        assert g1.nodes[0].node_id == "R1"
        assert g1.nodes[1].node_id == "R2"

    @patch("shopify_webhooks.services.promotion_sync.resolve_skus_from_edges")
    def test_target_group_nodes(self, mock_resolve):
        mock_resolve.side_effect = [
            {"skus": ["T1", "T2"]},
            {"skus": ["R1"]},
        ]
        config = _make_config()
        discount = _make_bxgy_discount()
        promo = build_bxgy_promotion(discount, config)

        g2 = promo.groups[1]
        assert len(g2.nodes) == 2
        assert g2.nodes[0].node_id == "T1"
        assert g2.nodes[1].node_id == "T2"

    @patch("shopify_webhooks.services.promotion_sync.resolve_skus_from_edges")
    def test_discount_on_quantity_100_percent(self, mock_resolve):
        mock_resolve.side_effect = [{"skus": ["T"]}, {"skus": ["R"]}]
        config = _make_config()
        discount = _make_bxgy_discount()
        promo = build_bxgy_promotion(discount, config)

        assert promo.discount_type == DiscountType.PERCENT_OFF.value
        assert promo.discount_value == 100

    @patch("shopify_webhooks.services.promotion_sync.resolve_skus_from_edges")
    def test_discount_percentage_type(self, mock_resolve):
        mock_resolve.side_effect = [{"skus": ["T"]}, {"skus": ["R"]}]
        config = _make_config()
        discount = _make_bxgy_discount()
        discount["customerGets"]["value"] = {
            "__typename": "DiscountPercentage",
            "percentage": 50,
        }
        promo = build_bxgy_promotion(discount, config)

        assert promo.discount_type == DiscountType.PERCENT_OFF.value
        assert promo.discount_value == 50

    @patch("shopify_webhooks.services.promotion_sync.resolve_skus_from_edges")
    def test_discount_amount_type(self, mock_resolve):
        mock_resolve.side_effect = [{"skus": ["T"]}, {"skus": ["R"]}]
        config = _make_config()
        discount = _make_bxgy_discount()
        discount["customerGets"]["value"] = {
            "__typename": "DiscountAmount",
            "amount": {"amount": "10.00"},
        }
        promo = build_bxgy_promotion(discount, config)

        assert promo.discount_type == DiscountType.VALUE_OFF.value
        assert promo.discount_value == "10.00"

    @patch("shopify_webhooks.services.promotion_sync.resolve_skus_from_edges")
    def test_unknown_discount_type_raises(self, mock_resolve):
        mock_resolve.side_effect = [{"skus": ["T"]}, {"skus": ["R"]}]
        config = _make_config()
        discount = _make_bxgy_discount()
        discount["customerGets"]["value"] = {"__typename": "Bogus"}
        with pytest.raises(ValueError, match="unknown discount type"):
            build_bxgy_promotion(discount, config)

    @patch("shopify_webhooks.services.promotion_sync.resolve_skus_from_edges")
    def test_promo_fields(self, mock_resolve):
        mock_resolve.side_effect = [{"skus": ["T"]}, {"skus": ["R"]}]
        config = _make_config()
        discount = _make_bxgy_discount()
        promo = build_bxgy_promotion(discount, config)

        assert promo.discount_value_on == DiscountOn.MRP.value
        assert promo.discount_apply_type == ApplicationType.BASKET.value
        assert promo.evaluate_criteria == PromoEvaluateCriteria.PRIORITY.value
        assert promo.availability == Availability.ALL.value


# ---------------------------------------------------------------------------
# _extract_qty_or_value_min
# ---------------------------------------------------------------------------


class TestExtractQtyOrValueMin:
    def test_discount_percentage(self):
        block = {"__typename": "DiscountPercentage", "percentage": 25}
        assert _extract_qty_or_value_min(block) == 25

    def test_discount_on_quantity(self):
        block = {
            "__typename": "DiscountOnQuantity",
            "quantity": {"quantity": 3},
        }
        assert _extract_qty_or_value_min(block) == 3

    def test_discount_quantity(self):
        block = {"__typename": "DiscountQuantity", "quantity": 2}
        assert _extract_qty_or_value_min(block) == 2

    def test_discount_amount(self):
        block = {
            "__typename": "DiscountAmount",
            "amount": {"amount": "50.00"},
        }
        assert _extract_qty_or_value_min(block) == "50.00"

    def test_unknown_returns_empty(self):
        assert _extract_qty_or_value_min({"__typename": "Unknown"}) == ""

    def test_empty_block(self):
        assert _extract_qty_or_value_min({}) == ""
