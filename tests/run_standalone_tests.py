#!/usr/bin/env python3
"""
Comprehensive standalone test runner for shopify_webhooks.
Stubs external dependencies and runs all pure-logic tests without full Django env.
"""
import sys
import os
import enum
import types
import decimal
import importlib

# ============================================================================
# Step 1: Add project to path
# ============================================================================
MAINSERVER = "/Users/theo/master-documentation/MishiPay/mainServer"
sys.path.insert(0, MAINSERVER)

# ============================================================================
# Step 2: Create proper enum stubs BEFORE anything imports them
# ============================================================================

@enum.unique
class PromoFamily(enum.Enum):
    EASY = "e"
    EASY_PLUS = "p"
    REQUISITE_GROUPS_WITH_DISCOUNTED_TARGET = "r"
    COMBO = "c"
    LINE_SPECIAL = "l"
    BASKET_THRESHOLD = "b"
    BASKET_THRESHOLD_WITH_DISCOUNTED_TARGET = "t"
    EVENLY_DISTRIBUTED_MULTILINE_DISCOUNT = "m"

@enum.unique
class PromoEvaluateCriteria(enum.Enum):
    PRIORITY = "p"
    BEST_DISCOUNT = "b"

@enum.unique
class DiscountType(enum.Enum):
    PERCENT_OFF = "p"
    VALUE_OFF = "v"
    FIXED = "f"

@enum.unique
class DiscountTypeStrategy(enum.Enum):
    ALL_ITEMS = "a"
    EACH_ITEM = "e"

@enum.unique
class DiscountOn(enum.Enum):
    MRP = "m"
    SP = "s"
    FP = "f"

@enum.unique
class ApplicationType(enum.Enum):
    BASKET = "b"
    CASHBACK = "c"
    TENDER = "t"

@enum.unique
class Availability(enum.Enum):
    ALL = "a"
    SPECIAL = "s"

@enum.unique
class GroupItemSelectionCriteria(enum.Enum):
    LEAST_EXPENSIVE = "l"
    MOST_EXPENSIVE = "m"

@enum.unique
class NodeType(enum.Enum):
    ITEM = "i"
    CATEGORY1 = "c1"
    CATEGORY2 = "c2"
    CATEGORY3 = "c3"
    CATEGORY4 = "c4"
    CATEGORY5 = "c5"
    CATEGORY6 = "c6"
    CATEGORY7 = "c7"


# Create the mishipay_items.mpay_promo_enums module
enums_mod = types.ModuleType("mishipay_items.mpay_promo_enums")
enums_mod.PromoFamily = PromoFamily
enums_mod.PromoEvaluateCriteria = PromoEvaluateCriteria
enums_mod.DiscountType = DiscountType
enums_mod.DiscountTypeStrategy = DiscountTypeStrategy
enums_mod.DiscountOn = DiscountOn
enums_mod.ApplicationType = ApplicationType
enums_mod.Availability = Availability
enums_mod.GroupItemSelectionCriteria = GroupItemSelectionCriteria
enums_mod.NodeType = NodeType

# Create simple data classes for mpay_promo
class Promotion:
    def __init__(self):
        self.retailer = None
        self.stores = []
        self.date_start = None
        self.date_end = None
        self.availability = None
        self.discount_value_on = None
        self.max_application_limit = 65535
        self.discount_type_strategy = None
        self.discounted_group_item_selection_criteria = None
        self.requisite_groups_item_selection_criteria = None
        self.layer = None
        self.evaluate_criteria = None
        self.is_active = True
        self.title = ""
        self.description = ""
        self.promo_id = ""
        self.family = ""
        self.discount_type = None
        self.discount_value = None
        self.evaluate_priority = None
        self.groups = []
        self.discount_apply_type = None
        self.apply_on_discounted_items = None
        self.special_promo_info = None
        self.target_discounted_group_name = None
        self.target_discounted_group_qty_min = None

    def add_store(self, store_id):
        self.stores.append(store_id)


class Group:
    def __init__(self):
        self.name = ""
        self.qty_or_value_min = None
        self.qty_or_value_max = None
        self.nodes = []


class Node:
    def __init__(self):
        self.node_type = None
        self.node_id = None


class PromotionBatchOperation:
    def __init__(self, *args, **kwargs):
        pass
    def create(self, promo):
        pass
    def delete(self, promo):
        pass
    def commit(self):
        pass


mpay_promo_mod = types.ModuleType("mishipay_items.mpay_promo")
mpay_promo_mod.Promotion = Promotion
mpay_promo_mod.Group = Group
mpay_promo_mod.Node = Node
mpay_promo_mod.PromotionBatchOperation = PromotionBatchOperation

# Create mishipay_items package
mishipay_items_mod = types.ModuleType("mishipay_items")
mishipay_items_mod.mpay_promo = mpay_promo_mod
mishipay_items_mod.mpay_promo_enums = enums_mod

# Create mishipay_core stubs
mishipay_core_mod = types.ModuleType("mishipay_core")
mishipay_core_common = types.ModuleType("mishipay_core.common_functions")

def send_slack_message(*args, **kwargs):
    pass

def get_rounded_value(value, decimals):
    return round(value, decimals)

def get_requests_session_client(*args, **kwargs):
    pass

def check_for_discrepancy(*args, **kwargs):
    pass

mishipay_core_common.send_slack_message = send_slack_message
mishipay_core_common.get_rounded_value = get_rounded_value
mishipay_core_common.get_requests_session_client = get_requests_session_client
mishipay_core_common.check_for_discrepancy = check_for_discrepancy
mishipay_core_mod.common_functions = mishipay_core_common

# Register all stub modules
sys.modules["mishipay_items"] = mishipay_items_mod
sys.modules["mishipay_items.mpay_promo"] = mpay_promo_mod
sys.modules["mishipay_items.mpay_promo_enums"] = enums_mod
sys.modules["mishipay_core"] = mishipay_core_mod
sys.modules["mishipay_core.common_functions"] = mishipay_core_common

# Stub remaining modules
from unittest.mock import MagicMock
for mod_name in [
    "mishipay_items.models",
    "mishipay_items.shopify_utility",
    "mishipay_items.shopify_utility.client",
    "mishipay_items.shopify_utility.refund_client",
    "mishipay_dashboard",
    "mishipay_dashboard.config",
    "mishipay_retail_payments",
    "mishipay_retail_payments.models",
    "dos", "dos.models", "dos.tests", "dos.tests.factories",
    "analytics", "analytics.models",
    "inventory_service", "inventory_service.client",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

# ============================================================================
# Step 3: Minimal Django config (enough for imports, not for ORM)
# ============================================================================
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "stub_settings")

# Create a minimal settings module
settings_mod = types.ModuleType("stub_settings")
settings_mod.INVENTORY_SERVICE_URL = "http://localhost:8081"
settings_mod.SHOPIFY_API_VERSION = "2024-01"
settings_mod.ENV_TYPE = "test"
settings_mod.SECRET_KEY = "test-secret-key"
settings_mod.DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
settings_mod.INSTALLED_APPS = []
settings_mod.DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
sys.modules["stub_settings"] = settings_mod

# Stub Django
import django
from django.conf import settings
if not settings.configured:
    settings.configure(
        INVENTORY_SERVICE_URL="http://localhost:8081",
        SHOPIFY_API_VERSION="2024-01",
        ENV_TYPE="test",
        SECRET_KEY="test",
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
        INSTALLED_APPS=[],
        DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    )

# ============================================================================
# Step 4: Now import and run the tests
# ============================================================================

import traceback

tests_run = 0
tests_passed = 0
tests_failed = 0
failed_tests = []

def run_test(name, func, *args, **kwargs):
    global tests_run, tests_passed, tests_failed
    tests_run += 1
    try:
        func(*args, **kwargs)
        tests_passed += 1
        print(f"  PASS  {name}")
    except Exception as e:
        tests_failed += 1
        failed_tests.append((name, str(e)))
        print(f"  FAIL  {name}: {e}")
        traceback.print_exc()

# ---- HMAC Tests ----
print("\n" + "=" * 70)
print("TEST SUITE: HMAC Verification (test_hmac.py)")
print("=" * 70)

from shopify_webhooks.middleware import verify_shopify_hmac
import base64
import hashlib
import hmac as hmac_mod

def _compute_hmac(body, secret):
    return base64.b64encode(
        hmac_mod.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("utf-8")

SECRET = "test-webhook-secret-key"

def assert_true(val):
    assert val is True, f"Expected True, got {val}"

def assert_false(val):
    assert val is False, f"Expected False, got {val}"

def assert_eq(a, b):
    assert a == b, f"Expected {b!r}, got {a!r}"

run_test("HMAC: valid_signature", lambda: assert_true(
    verify_shopify_hmac(b'{"id": 12345}', _compute_hmac(b'{"id": 12345}', SECRET), SECRET)
))
run_test("HMAC: tampered_payload", lambda: assert_false(
    verify_shopify_hmac(b'{"id": 99999}', _compute_hmac(b'{"id": 12345}', SECRET), SECRET)
))
run_test("HMAC: empty_hmac_header", lambda: assert_false(
    verify_shopify_hmac(b'{"id": 12345}', "", SECRET)
))
run_test("HMAC: wrong_secret", lambda: assert_false(
    verify_shopify_hmac(b'{"id": 12345}', _compute_hmac(b'{"id": 12345}', SECRET), "wrong")
))
run_test("HMAC: empty_body", lambda: assert_true(
    verify_shopify_hmac(b"", _compute_hmac(b"", SECRET), SECRET)
))
run_test("HMAC: garbage_hmac", lambda: assert_false(
    verify_shopify_hmac(b'{"id": 12345}', "not-valid-base64!", SECRET)
))
run_test("HMAC: unicode_payload", lambda: assert_true(
    verify_shopify_hmac(
        '{"name": "café"}'.encode("utf-8"),
        _compute_hmac('{"name": "café"}'.encode("utf-8"), SECRET),
        SECRET,
    )
))
run_test("HMAC: large_payload", lambda: assert_true(
    verify_shopify_hmac(b"x" * 100_000, _compute_hmac(b"x" * 100_000, SECRET), SECRET)
))

# ---- Inventory Sync Tests ----
print("\n" + "=" * 70)
print("TEST SUITE: Inventory Sync (test_inventory_sync.py)")
print("=" * 70)

from shopify_webhooks.services.inventory_sync import (
    _build_pricing_guidance,
    _determine_theme,
    _get_variant_barcode,
    _get_variant_images,
    map_shopify_product_to_inventory,
    send_to_inventory_service,
    strip_html,
)
import uuid

MULTI_VARIANT_PRODUCT = {
    "id": 7524702552295,
    "title": "#MyConfidant Conditioner",
    "body_html": "<p>Make your hair feel oh so soft and super clean with this conditioner!</p>",
    "vendor": "#myDentity",
    "product_type": "Conditioner",
    "status": "active",
    "tags": "acorn import, Conditioner, Shine",
    "variants": [
        {"id": 42663392641255, "product_id": 7524702552295, "title": "10 oz",
         "price": "22.50", "option1": "10 oz", "option2": None, "option3": None,
         "taxable": True, "barcode": "014926411246", "sku": None,
         "inventory_item_id": 44758024388839, "inventory_quantity": 200,
         "image_id": 40275842203879, "requires_shipping": True},
        {"id": 42391589617895, "product_id": 7524702552295, "title": "LTR",
         "price": "45.00", "option1": "LTR", "option2": None, "option3": None,
         "taxable": True, "barcode": "014926411253", "sku": None,
         "inventory_item_id": 44485818384615, "inventory_quantity": 200,
         "image_id": 40275842236647, "requires_shipping": True},
    ],
    "options": [{"id": 9576870150375, "product_id": 7524702552295, "name": "Size", "position": 1, "values": ["10 oz", "LTR"]}],
    "images": [
        {"id": 40275842203879, "position": 1, "product_id": 7524702552295, "src": "https://cdn.shopify.com/products/277190.png", "variant_ids": [42663392641255]},
        {"id": 40275842236647, "position": 2, "product_id": 7524702552295, "src": "https://cdn.shopify.com/products/277191.png", "variant_ids": [42391589617895]},
    ],
}

SINGLE_VARIANT_PRODUCT = {
    "id": 9999999, "title": "Simple Widget", "body_html": "A simple widget.",
    "product_type": "Widgets", "status": "active",
    "variants": [{"id": 1111111, "product_id": 9999999, "title": "Default Title",
                   "price": "10.00", "option1": "Default Title", "option2": None, "option3": None,
                   "taxable": True, "barcode": "WIDGET001", "sku": "WDG-001",
                   "inventory_quantity": 50, "inventory_item_id": 2222222, "image_id": None}],
    "options": [{"name": "Title", "position": 1, "values": ["Default Title"]}],
    "images": [{"id": 3333333, "src": "https://cdn.shopify.com/widget.png", "variant_ids": []}],
}

def _make_config(**extra_data_overrides):
    config = MagicMock()
    config.extra_data = extra_data_overrides
    config.retailer_id = uuid.uuid4()
    return config

# strip_html
run_test("strip_html: tags", lambda: assert_eq(strip_html("<p>Hello <b>world</b></p>"), "Hello world"))
run_test("strip_html: empty", lambda: assert_eq(strip_html(""), ""))
run_test("strip_html: None", lambda: assert_eq(strip_html(None), ""))
run_test("strip_html: plain", lambda: assert_eq(strip_html("No tags"), "No tags"))
run_test("strip_html: nested", lambda: assert_eq(strip_html("<div><span>nested</span></div>"), "nested"))

# _get_variant_barcode
run_test("barcode: present", lambda: assert_eq(_get_variant_barcode({"id": 1, "barcode": "123456", "sku": "SKU-1"}), "123456"))
run_test("barcode: fallback_to_sku", lambda: assert_eq(_get_variant_barcode({"id": 1, "barcode": "", "sku": "SKU-1"}), "SKU-1"))
run_test("barcode: None_fallback_to_sku", lambda: assert_eq(_get_variant_barcode({"id": 1, "barcode": None, "sku": "SKU-1"}), "SKU-1"))
run_test("barcode: fallback_to_id", lambda: assert_eq(_get_variant_barcode({"id": 42, "barcode": None, "sku": None}), "42"))
run_test("barcode: all_empty_to_id", lambda: assert_eq(_get_variant_barcode({"id": 99, "barcode": "", "sku": ""}), "99"))
run_test("barcode: no_fields", lambda: assert_eq(_get_variant_barcode({}), ""))

# _get_variant_images
run_test("images: variant_specific", lambda: assert_eq(
    _get_variant_images({"id": 100}, [{"src": "img1.png", "variant_ids": [100]}, {"src": "img2.png", "variant_ids": [200]}]), ["img1.png"]))
run_test("images: fallback_to_first", lambda: assert_eq(
    _get_variant_images({"id": 999}, [{"src": "first.png", "variant_ids": [100]}]), ["first.png"]))
run_test("images: no_images", lambda: assert_eq(_get_variant_images({"id": 1}, []), []))
run_test("images: multiple", lambda: assert_eq(
    _get_variant_images({"id": 100}, [{"src": "a.png", "variant_ids": [100]}, {"src": "b.png", "variant_ids": [100]}]), ["a.png", "b.png"]))
run_test("images: empty_src_skipped", lambda: assert_eq(
    _get_variant_images({"id": 100}, [{"src": "", "variant_ids": [100]}]), []))

# map_shopify_product_to_inventory
def test_multi_variant_creates_two():
    items = map_shopify_product_to_inventory(MULTI_VARIANT_PRODUCT, _make_config())
    assert_eq(len(items), 2)

def test_variant_names():
    items = map_shopify_product_to_inventory(MULTI_VARIANT_PRODUCT, _make_config())
    assert_eq(items[0]["name"], "#MyConfidant Conditioner - 10 oz")
    assert_eq(items[1]["name"], "#MyConfidant Conditioner - LTR")

def test_single_default_title():
    items = map_shopify_product_to_inventory(SINGLE_VARIANT_PRODUCT, _make_config())
    assert_eq(len(items), 1)
    assert_eq(items[0]["name"], "Simple Widget")

def test_html_stripped():
    items = map_shopify_product_to_inventory(MULTI_VARIANT_PRODUCT, _make_config())
    assert "<p>" not in items[0]["description"]
    assert "conditioner!" in items[0]["description"]

def test_retailer_product_id():
    items = map_shopify_product_to_inventory(MULTI_VARIANT_PRODUCT, _make_config())
    for item in items:
        assert_eq(item["retailerProductId"], "7524702552295")

def test_barcodes():
    items = map_shopify_product_to_inventory(MULTI_VARIANT_PRODUCT, _make_config())
    assert_eq(items[0]["barcodes"], ["014926411246"])
    assert_eq(items[1]["barcodes"], ["014926411253"])

def test_base_price():
    items = map_shopify_product_to_inventory(MULTI_VARIANT_PRODUCT, _make_config())
    assert_eq(items[0]["basePrice"], "22.50")
    assert_eq(items[1]["basePrice"], "45.00")

def test_stock_level():
    items = map_shopify_product_to_inventory(MULTI_VARIANT_PRODUCT, _make_config())
    assert_eq(items[0]["stockLevel"], 200)
    assert_eq(items[1]["stockLevel"], 200)

def test_per_variant_images():
    items = map_shopify_product_to_inventory(MULTI_VARIANT_PRODUCT, _make_config())
    assert_eq(items[0]["images"], ["https://cdn.shopify.com/products/277190.png"])
    assert_eq(items[1]["images"], ["https://cdn.shopify.com/products/277191.png"])

def test_categories():
    items = map_shopify_product_to_inventory(MULTI_VARIANT_PRODUCT, _make_config())
    assert_eq(items[0]["categories"], [{"name": "Conditioner", "image": "", "parent": None}])

def test_size_from_options():
    items = map_shopify_product_to_inventory(MULTI_VARIANT_PRODUCT, _make_config())
    assert_eq(items[0]["size"], "10 oz")
    assert_eq(items[1]["size"], "LTR")

def test_colour_extracted():
    payload = {
        "id": 100, "title": "T-Shirt", "body_html": "", "product_type": "Apparel", "status": "active",
        "variants": [{"id": 1, "title": "Red / S", "price": "20.00", "option1": "Red", "option2": "S", "barcode": "TS-RED-S", "inventory_quantity": 10}],
        "options": [{"name": "Color", "position": 1, "values": ["Red"]}, {"name": "Size", "position": 2, "values": ["S"]}],
        "images": [],
    }
    items = map_shopify_product_to_inventory(payload, _make_config())
    assert_eq(items[0]["colour"], "Red")
    assert_eq(items[0]["size"], "S")

def test_theme_invariant():
    items = map_shopify_product_to_inventory(SINGLE_VARIANT_PRODUCT, _make_config())
    assert_eq(items[0]["theme"], "invariant")

def test_theme_from_option():
    items = map_shopify_product_to_inventory(MULTI_VARIANT_PRODUCT, _make_config())
    assert_eq(items[0]["theme"], "Size")

def test_inactive_product():
    payload = {**SINGLE_VARIANT_PRODUCT, "status": "draft"}
    assert_eq(map_shopify_product_to_inventory(payload, _make_config()), [])

def test_no_variants():
    payload = {"id": 1, "title": "Empty", "body_html": "", "product_type": "", "status": "active", "variants": [], "options": [], "images": []}
    assert_eq(map_shopify_product_to_inventory(payload, _make_config()), [])

def test_no_tax_mapping():
    items = map_shopify_product_to_inventory(SINGLE_VARIANT_PRODUCT, _make_config())
    assert "pricingGuidance" not in items[0]

def test_tax_inclusive():
    config = _make_config(tax_mapping={"tax_code": "VAT20", "vat_percentage": 20, "tax_inclusive": True})
    result = _build_pricing_guidance({"price": "120.00"}, config)
    assert_eq(result["taxCode"], "VAT20")
    assert_eq(result["vatPercentage"], "20.0")
    assert_eq(result["includingVat"], "120.0")
    assert_eq(result["excludingVat"], "100.0")

def test_tax_exclusive():
    config = _make_config(tax_mapping={"tax_code": "VAT5", "vat_percentage": 5, "tax_inclusive": False})
    result = _build_pricing_guidance({"price": "100.00"}, config)
    assert_eq(result["includingVat"], "105.0")
    assert_eq(result["excludingVat"], "100.0")

def test_no_buying_guidance():
    items = map_shopify_product_to_inventory(SINGLE_VARIANT_PRODUCT, _make_config())
    assert "buyingGuidance" not in items[0]

def test_buying_guidance():
    config = _make_config(buying_guidance={"restrictedItem": True, "ageRestriction": 18})
    items = map_shopify_product_to_inventory(SINGLE_VARIANT_PRODUCT, config)
    assert_eq(items[0]["buyingGuidance"], {"restrictedItem": True, "ageRestriction": 18})

def test_barcode_empty_falls_back():
    payload = {
        "id": 1, "title": "Prod", "body_html": "", "product_type": "", "status": "active",
        "variants": [{"id": 10, "title": "Default Title", "price": "5.00", "barcode": "", "sku": "FALLBACK-SKU", "inventory_quantity": 1}],
        "options": [{"name": "Title", "position": 1, "values": ["Default Title"]}], "images": [],
    }
    items = map_shopify_product_to_inventory(payload, _make_config())
    assert_eq(items[0]["barcodes"], ["FALLBACK-SKU"])

def test_barcode_sku_null():
    payload = {
        "id": 1, "title": "Prod", "body_html": "", "product_type": "", "status": "active",
        "variants": [{"id": 42, "title": "Default Title", "price": "5.00", "barcode": None, "sku": None, "inventory_quantity": 1}],
        "options": [{"name": "Title", "position": 1, "values": ["Default Title"]}], "images": [],
    }
    items = map_shopify_product_to_inventory(payload, _make_config())
    assert_eq(items[0]["barcodes"], ["42"])

for fn in [test_multi_variant_creates_two, test_variant_names, test_single_default_title,
           test_html_stripped, test_retailer_product_id, test_barcodes, test_base_price,
           test_stock_level, test_per_variant_images, test_categories, test_size_from_options,
           test_colour_extracted, test_theme_invariant, test_theme_from_option,
           test_inactive_product, test_no_variants, test_no_tax_mapping, test_tax_inclusive,
           test_tax_exclusive, test_no_buying_guidance, test_buying_guidance,
           test_barcode_empty_falls_back, test_barcode_sku_null]:
    run_test(f"inventory: {fn.__name__}", fn)

# ---- Promotion Sync Tests ----
print("\n" + "=" * 70)
print("TEST SUITE: Promotion Sync (test_promotion_sync.py)")
print("=" * 70)

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

def _make_promo_config(**overrides):
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
    defaults = {
        "id": 12345, "title": "Test Promo", "target_type": "line_item",
        "target_selection": "entitled", "value_type": "percentage",
        "value": "-10.0", "starts_at": "2025-01-01T00:00:00+00:00",
        "ends_at": "2025-12-31T23:59:59+00:00", "once_per_customer": False,
        "allocation_method": "across",
        "entitled_product_ids": [111, 222], "entitled_variant_ids": [],
        "entitled_collection_ids": [], "prerequisite_subtotal_range": None,
    }
    defaults.update(overrides)
    return defaults

# extract_id
run_test("extract_id: product", lambda: assert_eq(extract_id("gid://shopify/Product/12345"), "12345"))
run_test("extract_id: variant", lambda: assert_eq(extract_id("gid://shopify/ProductVariant/67890"), "67890"))
run_test("extract_id: collection", lambda: assert_eq(extract_id("gid://shopify/Collection/100"), "100"))
run_test("extract_id: discount", lambda: assert_eq(extract_id("gid://shopify/DiscountAutomaticNode/999"), "999"))

# compute_evaluate_priority
run_test("priority: percent_10", lambda: assert_eq(compute_evaluate_priority(DiscountType.PERCENT_OFF.value, "10"), 90))
run_test("priority: percent_50", lambda: assert_eq(compute_evaluate_priority(DiscountType.PERCENT_OFF.value, "50"), 50))
run_test("priority: percent_100", lambda: assert_eq(compute_evaluate_priority(DiscountType.PERCENT_OFF.value, "100"), 0))
run_test("priority: value_off", lambda: assert_eq(compute_evaluate_priority(DiscountType.VALUE_OFF.value, "5"), 2000))
run_test("priority: zero_value", lambda: assert_eq(compute_evaluate_priority(DiscountType.VALUE_OFF.value, "0"), 32767))

# determine_family
run_test("family: entitled=easy", lambda: assert_eq(determine_family({"target_type": "line_item", "target_selection": "entitled"}), PromoFamily.EASY.value))
run_test("family: all=basket", lambda: assert_eq(determine_family({"target_type": "line_item", "target_selection": "all"}), PromoFamily.BASKET_THRESHOLD.value))
run_test("family: shipping=None", lambda: assert_eq(determine_family({"target_type": "shipping_line", "target_selection": "all"}), None))
run_test("family: empty=None", lambda: assert_eq(determine_family({}), None))
run_test("family: unknown=None", lambda: assert_eq(determine_family({"target_type": "line_item", "target_selection": "unknown"}), None))

# build_promotion_settings_from_config
def test_settings_urls():
    config = _make_promo_config()
    result = build_promotion_settings_from_config(config)
    base = "https://test-shop.myshopify.com/admin/api/2024-07"
    assert_eq(result["access_token"], "shpat_test")
    assert_eq(result["products_in_collection_fetch_endpoint"], f"{base}/collections")
    assert_eq(result["products_sku_fetch_endpoint"], f"{base}/products")
    assert_eq(result["variants_sku_fetch_endpoint"], f"{base}/variants")
run_test("settings: builds_correct_urls", test_settings_urls)

# build_promo_groups
def test_single_group():
    groups = build_promo_groups("PR-123", {"skus": ["BC-001", "BC-002"]})
    assert_eq(len(groups), 1)
    assert_eq(groups[0].name, "PR-123")
    assert_eq(groups[0].qty_or_value_min, 1)
    assert groups[0].qty_or_value_max is None
    assert_eq(len(groups[0].nodes), 2)
    assert_eq(groups[0].nodes[0].node_id, "BC-001")
    assert_eq(groups[0].nodes[0].node_type, NodeType.ITEM.value)
run_test("groups: single_with_nodes", test_single_group)

def test_custom_qty():
    groups = build_promo_groups("P1", {"skus": ["X"]}, qty_or_value_min=5)
    assert_eq(groups[0].qty_or_value_min, 5)
run_test("groups: custom_qty_min", test_custom_qty)

def test_skips_empty():
    groups = build_promo_groups("P1", {"skus": ["BC-001", None, "", "BC-002"]})
    assert_eq(len(groups[0].nodes), 2)
run_test("groups: skips_empty_skus", test_skips_empty)

def test_empty_skus():
    groups = build_promo_groups("P1", {"skus": []})
    assert_eq(len(groups[0].nodes), 0)
run_test("groups: empty_list", test_empty_skus)

# resolve_entitled_skus
from unittest.mock import patch

def test_resolve_products():
    with patch("shopify_webhooks.services.promotion_sync.get_products_sku") as mock_fn:
        mock_fn.return_value = {"skus": ["BC-1"]}
        pr = _make_price_rule(entitled_product_ids=[111])
        result = resolve_entitled_skus(pr, {})
        assert_eq(result, {"skus": ["BC-1"]})
        mock_fn.assert_called_once()
run_test("resolve: products", test_resolve_products)

def test_resolve_variants():
    with patch("shopify_webhooks.services.promotion_sync.get_sku_from_variants") as mock_fn:
        mock_fn.return_value = {"skus": ["BC-2"]}
        pr = _make_price_rule(entitled_product_ids=[], entitled_variant_ids=[333])
        result = resolve_entitled_skus(pr, {})
        assert_eq(result, {"skus": ["BC-2"]})
run_test("resolve: variants", test_resolve_variants)

def test_resolve_collections():
    with patch("shopify_webhooks.services.promotion_sync.get_products_from_collections") as mock_fn:
        mock_fn.return_value = {"skus": ["BC-3"]}
        pr = _make_price_rule(entitled_product_ids=[], entitled_variant_ids=[], entitled_collection_ids=[444])
        result = resolve_entitled_skus(pr, {})
        assert_eq(result, {"skus": ["BC-3"]})
run_test("resolve: collections", test_resolve_collections)

def test_resolve_raises():
    import pytest
    pr = _make_price_rule(entitled_product_ids=[], entitled_variant_ids=[], entitled_collection_ids=[])
    try:
        resolve_entitled_skus(pr, {})
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "no entitled items" in str(e)
run_test("resolve: raises_on_empty", test_resolve_raises)

# build_easy_promotion
def test_easy_percentage():
    with patch("shopify_webhooks.services.promotion_sync.resolve_entitled_skus") as mock_res:
        mock_res.return_value = {"skus": ["BC-001"]}
        config = _make_promo_config()
        pr = _make_price_rule(value_type="percentage", value="-15.0")
        promo = build_easy_promotion(pr, config)
        assert_eq(promo.family, PromoFamily.EASY.value)
        assert_eq(promo.discount_type, DiscountType.PERCENT_OFF.value)
        assert_eq(float(promo.discount_value), 15.0)
        assert_eq(promo.promo_id, "12345")
        assert_eq(promo.layer, "1")
        assert_eq(promo.availability, Availability.ALL.value)
        assert_eq(promo.discount_value_on, DiscountOn.FP.value)
run_test("easy: percentage_discount", test_easy_percentage)

def test_easy_fixed():
    with patch("shopify_webhooks.services.promotion_sync.resolve_entitled_skus") as mock_res:
        mock_res.return_value = {"skus": ["BC-001"]}
        config = _make_promo_config()
        pr = _make_price_rule(value_type="fixed_amount", value="-5.00")
        promo = build_easy_promotion(pr, config)
        assert_eq(promo.discount_type, DiscountType.VALUE_OFF.value)
        assert_eq(float(promo.discount_value), 5.0)
run_test("easy: fixed_amount", test_easy_fixed)

def test_easy_once_per_customer():
    with patch("shopify_webhooks.services.promotion_sync.resolve_entitled_skus") as mock_res:
        mock_res.return_value = {"skus": ["BC-001"]}
        config = _make_promo_config()
        pr = _make_price_rule(once_per_customer=True)
        promo = build_easy_promotion(pr, config)
        assert_eq(promo.max_application_limit, 1)
run_test("easy: once_per_customer", test_easy_once_per_customer)

def test_easy_each_allocation():
    with patch("shopify_webhooks.services.promotion_sync.resolve_entitled_skus") as mock_res:
        mock_res.return_value = {"skus": ["BC-001"]}
        config = _make_promo_config()
        pr = _make_price_rule(allocation_method="each")
        promo = build_easy_promotion(pr, config)
        assert_eq(promo.discount_type_strategy, DiscountTypeStrategy.EACH_ITEM.value)
run_test("easy: allocation_each", test_easy_each_allocation)

def test_easy_across_allocation():
    with patch("shopify_webhooks.services.promotion_sync.resolve_entitled_skus") as mock_res:
        mock_res.return_value = {"skus": ["BC-001"]}
        config = _make_promo_config()
        pr = _make_price_rule(allocation_method="across")
        promo = build_easy_promotion(pr, config)
        assert_eq(promo.discount_type_strategy, DiscountTypeStrategy.ALL_ITEMS.value)
run_test("easy: allocation_across", test_easy_across_allocation)

def test_easy_groups():
    with patch("shopify_webhooks.services.promotion_sync.resolve_entitled_skus") as mock_res:
        mock_res.return_value = {"skus": ["BC-001", "BC-002"]}
        config = _make_promo_config()
        pr = _make_price_rule()
        promo = build_easy_promotion(pr, config)
        assert_eq(len(promo.groups), 1)
        assert_eq(len(promo.groups[0].nodes), 2)
        assert_eq(promo.groups[0].nodes[0].node_id, "BC-001")
        assert_eq(promo.groups[0].nodes[0].node_type, NodeType.ITEM.value)
run_test("easy: groups_from_resolved_skus", test_easy_groups)

def test_easy_unknown_raises():
    with patch("shopify_webhooks.services.promotion_sync.resolve_entitled_skus") as mock_res:
        mock_res.return_value = {"skus": ["BC-001"]}
        config = _make_promo_config()
        pr = _make_price_rule(value_type="bogus")
        try:
            build_easy_promotion(pr, config)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Unknown discount value_type" in str(e)
run_test("easy: unknown_raises", test_easy_unknown_raises)

def test_easy_retailer_from_extra():
    with patch("shopify_webhooks.services.promotion_sync.resolve_entitled_skus") as mock_res:
        mock_res.return_value = {"skus": ["BC-001"]}
        config = _make_promo_config(extra_data={"promo_retailer": "EVOKES-AU"})
        pr = _make_price_rule()
        promo = build_easy_promotion(pr, config)
        assert_eq(promo.retailer, "EVOKES-AU")
run_test("easy: retailer_from_extra_data", test_easy_retailer_from_extra)

# build_basket_threshold_promotion
def test_basket_basic():
    config = _make_promo_config()
    pr = _make_price_rule(target_selection="all", value_type="percentage", value="-20.0")
    promo = build_basket_threshold_promotion(pr, config)
    assert_eq(promo.family, PromoFamily.BASKET_THRESHOLD.value)
    assert_eq(promo.layer, 100)
    assert_eq(promo.discount_apply_type, ApplicationType.BASKET.value)
    assert_eq(promo.discount_type, DiscountType.PERCENT_OFF.value)
    assert_eq(float(promo.discount_value), 20.0)
run_test("basket: basic_threshold", test_basket_basic)

def test_basket_all_node():
    config = _make_promo_config()
    pr = _make_price_rule(target_selection="all")
    promo = build_basket_threshold_promotion(pr, config)
    assert_eq(len(promo.groups), 1)
    assert_eq(len(promo.groups[0].nodes), 1)
    assert_eq(promo.groups[0].nodes[0].node_id, "all")
    assert_eq(promo.groups[0].nodes[0].node_type, NodeType.ITEM.value)
run_test("basket: single_group_all_node", test_basket_all_node)

def test_basket_subtotal_range():
    config = _make_promo_config()
    pr = _make_price_rule(target_selection="all", prerequisite_subtotal_range={"greater_than_or_equal_to": "50.00"})
    promo = build_basket_threshold_promotion(pr, config)
    assert_eq(promo.groups[0].qty_or_value_min, "50.00")
run_test("basket: prerequisite_subtotal", test_basket_subtotal_range)

def test_basket_no_subtotal():
    config = _make_promo_config()
    pr = _make_price_rule(target_selection="all", prerequisite_subtotal_range=None)
    promo = build_basket_threshold_promotion(pr, config)
    assert_eq(promo.groups[0].qty_or_value_min, 1)
run_test("basket: no_subtotal_defaults_1", test_basket_no_subtotal)

def test_basket_fixed():
    config = _make_promo_config()
    pr = _make_price_rule(target_selection="all", value_type="fixed_amount", value="-10.00")
    promo = build_basket_threshold_promotion(pr, config)
    assert_eq(promo.discount_type, DiscountType.VALUE_OFF.value)
    assert_eq(float(promo.discount_value), 10.0)
run_test("basket: fixed_amount", test_basket_fixed)

def test_basket_missing_title():
    config = _make_promo_config()
    pr = _make_price_rule(target_selection="all", title="")
    try:
        build_basket_threshold_promotion(pr, config)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "requires a title" in str(e)
run_test("basket: missing_title_raises", test_basket_missing_title)

def test_basket_once_per_customer():
    config = _make_promo_config()
    pr = _make_price_rule(target_selection="all", once_per_customer=True)
    promo = build_basket_threshold_promotion(pr, config)
    assert_eq(promo.max_application_limit, 1)
run_test("basket: once_per_customer", test_basket_once_per_customer)

# build_bxgy_promotion
def _make_bxgy_discount(**overrides):
    defaults = {
        "id": "gid://shopify/DiscountAutomaticNode/99999", "title": "Buy 2 Get 1 Free",
        "summary": "Buy 2 items, get 1 free",
        "startsAt": "2025-01-01T00:00:00+00:00", "endsAt": "2025-12-31T23:59:59+00:00",
        "customerBuys": {"value": {"__typename": "DiscountQuantity", "quantity": 2},
            "items": {"products": {"edges": [{"node": {"id": "gid://shopify/Product/111"}}]}}},
        "customerGets": {"value": {"__typename": "DiscountOnQuantity", "quantity": {"quantity": 1},
                "effect": {"__typename": "DiscountPercentage", "percentage": 100}},
            "items": {"products": {"edges": [{"node": {"id": "gid://shopify/Product/222"}}]}}},
    }
    defaults.update(overrides)
    return defaults

def test_bxgy_two_groups():
    with patch("shopify_webhooks.services.promotion_sync.resolve_skus_from_edges") as mock_res:
        mock_res.side_effect = [{"skus": ["TARGET-BC"]}, {"skus": ["REQ-BC"]}]
        config = _make_promo_config()
        promo = build_bxgy_promotion(_make_bxgy_discount(), config)
        assert_eq(promo.family, PromoFamily.REQUISITE_GROUPS_WITH_DISCOUNTED_TARGET.value)
        assert_eq(promo.target_discounted_group_name, "g2")
        assert_eq(len(promo.groups), 2)
        assert_eq(promo.groups[0].name, "g1")
        assert_eq(promo.groups[1].name, "g2")
run_test("bxgy: two_group_structure", test_bxgy_two_groups)

def test_bxgy_requisite_nodes():
    with patch("shopify_webhooks.services.promotion_sync.resolve_skus_from_edges") as mock_res:
        mock_res.side_effect = [{"skus": ["T1"]}, {"skus": ["R1", "R2"]}]
        config = _make_promo_config()
        promo = build_bxgy_promotion(_make_bxgy_discount(), config)
        assert_eq(len(promo.groups[0].nodes), 2)
        assert_eq(promo.groups[0].nodes[0].node_id, "R1")
        assert_eq(promo.groups[0].nodes[1].node_id, "R2")
run_test("bxgy: requisite_group_nodes", test_bxgy_requisite_nodes)

def test_bxgy_target_nodes():
    with patch("shopify_webhooks.services.promotion_sync.resolve_skus_from_edges") as mock_res:
        mock_res.side_effect = [{"skus": ["T1", "T2"]}, {"skus": ["R1"]}]
        config = _make_promo_config()
        promo = build_bxgy_promotion(_make_bxgy_discount(), config)
        g2 = promo.groups[1]
        assert_eq(len(g2.nodes), 2)
        assert_eq(g2.nodes[0].node_id, "T1")
        assert_eq(g2.nodes[1].node_id, "T2")
run_test("bxgy: target_group_nodes", test_bxgy_target_nodes)

def test_bxgy_100_percent():
    with patch("shopify_webhooks.services.promotion_sync.resolve_skus_from_edges") as mock_res:
        mock_res.side_effect = [{"skus": ["T"]}, {"skus": ["R"]}]
        config = _make_promo_config()
        promo = build_bxgy_promotion(_make_bxgy_discount(), config)
        assert_eq(promo.discount_type, DiscountType.PERCENT_OFF.value)
        assert_eq(promo.discount_value, 100)
run_test("bxgy: 100_percent_off", test_bxgy_100_percent)

def test_bxgy_percentage_type():
    with patch("shopify_webhooks.services.promotion_sync.resolve_skus_from_edges") as mock_res:
        mock_res.side_effect = [{"skus": ["T"]}, {"skus": ["R"]}]
        config = _make_promo_config()
        d = _make_bxgy_discount()
        d["customerGets"]["value"] = {"__typename": "DiscountPercentage", "percentage": 50}
        promo = build_bxgy_promotion(d, config)
        assert_eq(promo.discount_type, DiscountType.PERCENT_OFF.value)
        assert_eq(promo.discount_value, 50)
run_test("bxgy: percentage_type", test_bxgy_percentage_type)

def test_bxgy_amount_type():
    with patch("shopify_webhooks.services.promotion_sync.resolve_skus_from_edges") as mock_res:
        mock_res.side_effect = [{"skus": ["T"]}, {"skus": ["R"]}]
        config = _make_promo_config()
        d = _make_bxgy_discount()
        d["customerGets"]["value"] = {"__typename": "DiscountAmount", "amount": {"amount": "10.00"}}
        promo = build_bxgy_promotion(d, config)
        assert_eq(promo.discount_type, DiscountType.VALUE_OFF.value)
        assert_eq(promo.discount_value, "10.00")
run_test("bxgy: amount_type", test_bxgy_amount_type)

def test_bxgy_unknown_raises():
    with patch("shopify_webhooks.services.promotion_sync.resolve_skus_from_edges") as mock_res:
        mock_res.side_effect = [{"skus": ["T"]}, {"skus": ["R"]}]
        config = _make_promo_config()
        d = _make_bxgy_discount()
        d["customerGets"]["value"] = {"__typename": "Bogus"}
        try:
            build_bxgy_promotion(d, config)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "unknown discount type" in str(e)
run_test("bxgy: unknown_type_raises", test_bxgy_unknown_raises)

def test_bxgy_fields():
    with patch("shopify_webhooks.services.promotion_sync.resolve_skus_from_edges") as mock_res:
        mock_res.side_effect = [{"skus": ["T"]}, {"skus": ["R"]}]
        config = _make_promo_config()
        promo = build_bxgy_promotion(_make_bxgy_discount(), config)
        assert_eq(promo.discount_value_on, DiscountOn.MRP.value)
        assert_eq(promo.discount_apply_type, ApplicationType.BASKET.value)
        assert_eq(promo.evaluate_criteria, PromoEvaluateCriteria.PRIORITY.value)
        assert_eq(promo.availability, Availability.ALL.value)
run_test("bxgy: promo_fields", test_bxgy_fields)

# _extract_qty_or_value_min
run_test("extract_min: percentage", lambda: assert_eq(_extract_qty_or_value_min({"__typename": "DiscountPercentage", "percentage": 25}), 25))
run_test("extract_min: on_quantity", lambda: assert_eq(_extract_qty_or_value_min({"__typename": "DiscountOnQuantity", "quantity": {"quantity": 3}}), 3))
run_test("extract_min: quantity", lambda: assert_eq(_extract_qty_or_value_min({"__typename": "DiscountQuantity", "quantity": 2}), 2))
run_test("extract_min: amount", lambda: assert_eq(_extract_qty_or_value_min({"__typename": "DiscountAmount", "amount": {"amount": "50.00"}}), "50.00"))
run_test("extract_min: unknown", lambda: assert_eq(_extract_qty_or_value_min({"__typename": "Unknown"}), ""))
run_test("extract_min: empty", lambda: assert_eq(_extract_qty_or_value_min({}), ""))

# ---- Utils Tests ----
print("\n" + "=" * 70)
print("TEST SUITE: Utils (utils.py)")
print("=" * 70)

from shopify_webhooks.utils import to_shopify_gid

run_test("gid: product", lambda: assert_eq(to_shopify_gid("Product", 12345), "gid://shopify/Product/12345"))
run_test("gid: variant", lambda: assert_eq(to_shopify_gid("ProductVariant", 67890), "gid://shopify/ProductVariant/67890"))

# ============================================================================
# Summary
# ============================================================================

print("\n" + "=" * 70)
print(f"RESULTS: {tests_passed} passed, {tests_failed} failed, {tests_run} total")
print("=" * 70)

if failed_tests:
    print("\nFailed tests:")
    for name, error in failed_tests:
        print(f"  - {name}: {error}")

sys.exit(1 if tests_failed else 0)
