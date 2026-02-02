"""Shared Shopify → MishiPay promotion mapping logic.

Extracted from ``promotions.management.commands.shopify_promotion_import``
so both the batch management command and the webhook-driven promotion
handler can reuse the same mapping, SKU-resolution and promo-building
functions.

Usage from batch command::

    from shopify_webhooks.services.promotion_sync import (
        get_products_from_collections,
        get_products_sku,
        get_sku_from_variants,
        parse_easy_level_promotion,
        parse_basket_level_promotion,
        parse_automatic_codes_easy_level_promotion,
        parse_automatic_mix_match_discount_target,
    )

Usage from webhook handler::

    # Construct a promotion_settings dict from ShopifyWebhookConfig
    settings = build_promotion_settings_from_config(config)
    skus = get_products_sku(product_ids, settings)
"""

import datetime
import decimal
import logging
import time

import requests

from django.conf import settings as django_settings

from mishipay_core.common_functions import send_slack_message, get_rounded_value
from mishipay_items import mpay_promo
from mishipay_items.mpay_promo_enums import (
    PromoFamily,
    PromoEvaluateCriteria,
    DiscountTypeStrategy,
    DiscountType,
    DiscountOn,
    Availability,
    NodeType,
    GroupItemSelectionCriteria,
    ApplicationType,
)

logger = logging.getLogger(__name__)

DEFAULT_END_DATE = "2050-01-01T16:39:39+10:00"
RETRY_DELAY = 2.5


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def extract_id(gid_string):
    """Extract the numeric ID from a Shopify GID string.

    Example: ``"gid://shopify/Product/12345"`` → ``"12345"``
    """
    parts = gid_string.split("/")
    return parts[-1]


def get_start_datetime(start_date):
    """Parse a Shopify ISO-8601 date string into a datetime."""
    return datetime.datetime.strptime(start_date, "%Y-%m-%dT%H:%M:%S%z")


def get_end_datetime(end_date):
    """Parse end-date, defaulting to far-future if ``None``, and add 1 day buffer."""
    if end_date is None:
        end_date = DEFAULT_END_DATE
    date_time = datetime.datetime.strptime(end_date, "%Y-%m-%dT%H:%M:%S%z")
    date_time += datetime.timedelta(days=1)
    return date_time


def is_promotion_active(start_date, end_date):
    """Return ``True`` if the promotion is currently within its active window."""
    current_date = datetime.datetime.now(datetime.timezone.utc)
    return start_date <= current_date <= end_date


def compute_evaluate_priority(discount_type, discount_value):
    """Compute the evaluate_priority value for a promotion.

    Lower priority = better discount → evaluated first.
    """
    try:
        if discount_type == DiscountType.PERCENT_OFF.value:
            return max(0, 100 - int(float(discount_value)))
        elif discount_type == DiscountType.VALUE_OFF.value:
            return int(10000 / decimal.Decimal(discount_value))
        else:
            return int(10000 / decimal.Decimal(discount_value))
    except (ZeroDivisionError, decimal.InvalidOperation):
        return 32767


# ---------------------------------------------------------------------------
# Family determination
# ---------------------------------------------------------------------------

def determine_family(price_rule):
    """Map a Shopify price rule to a MishiPay promotion family code.

    Returns:
        str or None: ``'e'`` (Easy), ``'b'`` (Basket Threshold), or ``None``
        if the price rule is not mappable (e.g. shipping-type rules).
    """
    if price_rule.get("target_type") != "line_item":
        return None
    target_selection = price_rule.get("target_selection")
    if target_selection == "all":
        return PromoFamily.BASKET_THRESHOLD.value
    elif target_selection == "entitled":
        return PromoFamily.EASY.value
    return None


# ---------------------------------------------------------------------------
# SKU resolution — Shopify Admin API calls
# ---------------------------------------------------------------------------

def get_products_from_collections(collection_ids, promotion_settings):
    """Resolve Shopify collection IDs → barcodes/SKUs via the Admin API.

    Fetches products in each collection then delegates to
    :func:`get_products_sku` for barcode resolution.

    Args:
        collection_ids: list of collection IDs (will be mutated/popped).
        promotion_settings: dict with keys ``products_in_collection_fetch_endpoint``,
            ``products_sku_fetch_endpoint``, ``access_token``.
    """
    url_base = promotion_settings["products_in_collection_fetch_endpoint"]
    token = promotion_settings["access_token"]
    headers = {"X-Shopify-Access-Token": f"{token}"}
    skus = {"skus": []}
    product_ids = {"product_id": []}
    while collection_ids:
        collection_id = collection_ids.pop(0)
        url = f"{url_base}/{collection_id}/products.json"
        try:
            response = requests.get(url=url, headers=headers, timeout=300)
            if response.status_code == 429:
                print(f"Status code 429 received for {url}, retrying after {RETRY_DELAY}s")
                time.sleep(RETRY_DELAY)
                collection_ids.insert(0, collection_id)
                continue
            elif response.status_code != 200:
                error = f" - get_products_from_collections status code - {str(response.status_code)}"
                logger.error(error)
                send_slack_message(f'[{django_settings.ENV_TYPE}]: ' + error, "#alerts_client_data")
                continue
            response_dict = response.json()
            for product in response_dict.get("products", []):
                product_ids["product_id"].append(product.get("id"))
            product_sku = get_products_sku(product_ids["product_id"], promotion_settings)
            while product_sku["skus"]:
                item_sku = product_sku["skus"].pop(0)
                skus["skus"].append(str(item_sku))
        except Exception as e:
            error = f"error in standard shopify promotion import while fetching products in collection - {str(e)}"
            logger.error(error)
            send_slack_message(f'[{django_settings.ENV_TYPE}]: ' + error, "#alerts_client_data")
            raise Exception(error)
    return skus


def get_products_sku(product_ids, promotion_settings):
    """Resolve Shopify product IDs → barcodes/SKUs via the Admin API.

    Args:
        product_ids: list of product IDs (will be mutated/popped).
        promotion_settings: dict with keys ``products_sku_fetch_endpoint``,
            ``access_token``.
    """
    url_base = promotion_settings["products_sku_fetch_endpoint"]
    token = promotion_settings["access_token"]
    headers = {"X-Shopify-Access-Token": f"{token}"}
    skus = {"skus": []}
    while product_ids:
        product_id = product_ids.pop(0)
        url = f"{url_base}/{product_id}.json"
        try:
            response = requests.get(url=url, headers=headers, timeout=300)
            if response.status_code == 429:
                print(f"Status code 429 received for {url}, retrying after {RETRY_DELAY}s")
                time.sleep(RETRY_DELAY)
                product_ids.insert(0, product_id)
                continue
            elif response.status_code != 200:
                error = f" - get_products_sku status code - {str(response.status_code)}"
                logger.error(error)
                send_slack_message(f'[{django_settings.ENV_TYPE}]: ' + error, "#alerts_client_data")
                continue
            response_dict = response.json()
            product = response_dict.get("product")
            for variant in product.get("variants", []):
                if variant.get("barcode", None):
                    skus["skus"].append(variant.get("barcode"))
        except Exception as e:
            error = f"error in standard shopify promotion import while fetching skus in products - {str(e)}"
            logger.error(error)
            send_slack_message(f'[{django_settings.ENV_TYPE}]: ' + error, "#alerts_client_data")
            raise Exception(error)
    return skus


def get_sku_from_variants(variant_ids, promotion_settings):
    """Resolve Shopify variant IDs → barcodes/SKUs via the Admin API.

    Args:
        variant_ids: list of variant IDs (will be mutated/popped).
        promotion_settings: dict with keys ``variants_sku_fetch_endpoint``,
            ``access_token``.
    """
    base_url = promotion_settings["variants_sku_fetch_endpoint"]
    token = promotion_settings["access_token"]
    headers = {"X-Shopify-Access-Token": f"{token}"}
    skus = {"skus": []}
    while variant_ids:
        variant_id = variant_ids.pop(0)
        print(f"product ID {variant_id}")
        url = f"{base_url}/{variant_id}.json"
        try:
            response = requests.get(url=url, headers=headers, timeout=300)
            if response.status_code == 429:
                print(f"Status code 429 received for {url}, retrying after {RETRY_DELAY}s")
                time.sleep(RETRY_DELAY)
                variant_ids.insert(0, variant_id)
            elif response.status_code != 200:
                error = f" - get_sku_from_variants status code - {str(response.status_code)}"
                logger.error(error)
                send_slack_message(f'[{django_settings.ENV_TYPE}]: ' + error, "#alerts_client_data")
                continue
            else:
                response_dict = response.json()
                variant = response_dict.get("variant")
                skus["skus"].append(variant.get("barcode", None))
        except Exception as e:
            error = f"error in standard shopify promotion import while fetching products in collection - {str(e)}"
            logger.error(error)
            send_slack_message(f'[{django_settings.ENV_TYPE}]: ' + error, "#alerts_client_data")
            raise Exception(error)
    return skus


# ---------------------------------------------------------------------------
# SKU resolution helper — resolves items from GraphQL edge structures
# ---------------------------------------------------------------------------

def resolve_skus_from_edges(customer_data_items, promotion_settings):
    """Resolve SKUs from a GraphQL ``customerGets.items`` or ``customerBuys.items`` block.

    Handles collections, products, and productVariants edge types.

    Returns:
        dict: ``{"skus": [barcode, ...]}``

    Raises:
        Exception: if no resolvable items found.
    """
    collections_edge = customer_data_items.get("collections")
    products_edge = customer_data_items.get("products")
    variants_edge = customer_data_items.get("productVariants")

    collections = collections_edge.get("edges", []) if collections_edge else []
    products = products_edge.get("edges", []) if products_edge else []
    variants = variants_edge.get("edges", []) if variants_edge else []

    if collections:
        collection_ids = [extract_id(c["node"]["id"]) for c in collections]
        return get_products_from_collections(collection_ids, promotion_settings)
    elif products:
        product_ids = [extract_id(p["node"]["id"]) for p in products]
        return get_products_sku(product_ids, promotion_settings)
    elif variants:
        variant_ids = [extract_id(v["node"]["id"]) for v in variants]
        return get_sku_from_variants(variant_ids, promotion_settings)
    else:
        raise Exception("Promo: entitled/requisite items not found")


# ---------------------------------------------------------------------------
# Promotion parsing — Price Rules (REST API format)
# ---------------------------------------------------------------------------

def parse_easy_level_promotion(
    promotion_dict,
    original_promotion,
    *,
    store_id,
    promo_retailer,
    region,
    promotion_settings,
    test=False,
    coupon_check_fn=None,
):
    """Build an Easy-family promotion from a Shopify price rule.

    Args:
        promotion_dict: accumulator dict ``{promo_id: Promotion}``.
        original_promotion: Shopify price rule dict.
        store_id: UUID of the MishiPay store.
        promo_retailer: retailer string (e.g. ``"EVOKES"``).
        region: store region string (e.g. ``"AU"``).
        promotion_settings: dict with Shopify API endpoints and token.
        test: if True, override end date to +5 days.
        coupon_check_fn: callable(title) → bool, checks if promo needs coupons.
    """
    if test:
        valid_to_date = datetime.datetime.today() + datetime.timedelta(days=5)
        original_promotion["ends_at"] = valid_to_date.strftime("%Y-%m-%d") + "T00:00:00+11:00"

    promo = mpay_promo.Promotion()
    promo.retailer = promo_retailer
    promo.add_store(store_id)

    promo.date_start = get_start_datetime(original_promotion["starts_at"])
    promo.date_end = get_end_datetime(original_promotion["ends_at"])
    promo.availability = Availability.ALL.value
    promo.discount_value_on = DiscountOn.FP.value
    promo.max_application_limit = 65535
    if original_promotion["once_per_customer"]:
        promo.max_application_limit = 1
    if original_promotion["allocation_method"] == "across":
        promo.discount_type_strategy = DiscountTypeStrategy.ALL_ITEMS.value
    elif original_promotion["allocation_method"] == "each":
        promo.discount_type_strategy = DiscountTypeStrategy.EACH_ITEM.value
    else:
        raise Exception("Easy Promo: allocation method not found")
    promo.discounted_group_item_selection_criteria = GroupItemSelectionCriteria.LEAST_EXPENSIVE.value
    promo.layer = 1
    promo.evaluate_criteria = PromoEvaluateCriteria.PRIORITY.value
    promo.is_active = True
    promo.title = original_promotion["title"]
    promo.description = original_promotion["title"]
    title = original_promotion["title"]

    if coupon_check_fn and coupon_check_fn(title=title):
        promo.availability = Availability.SPECIAL.value
        promo.special_promo_info = [
            {
                "group_qualifier_id": f"b-{region.lower()}-{title.lower()}",
                "description": original_promotion["title"],
            }
        ]

    discount_value = abs(float(original_promotion["value"]))
    if original_promotion["value_type"] == "fixed_amount":
        promo.discount_type = DiscountType.VALUE_OFF.value
        promo.discount_value = get_rounded_value(decimal.Decimal(discount_value), 2)
    elif original_promotion["value_type"] == "percentage":
        promo.discount_type = DiscountType.PERCENT_OFF.value
        promo.discount_value = get_rounded_value(decimal.Decimal(discount_value), 2)
    else:
        raise Exception("Easy Promo: Unknown discount method {}".format(original_promotion["value_type"]))

    promo.evaluate_priority = compute_evaluate_priority(promo.discount_type, promo.discount_value)

    promo.promo_id = str(original_promotion["id"])
    promo.layer = "1"
    promo.family = PromoFamily.EASY.value

    pg1 = mpay_promo.Group()
    pg1.name = str(original_promotion["id"])
    pg1.qty_or_value_min = 1
    pg1.qty_or_value_max = None

    if len(original_promotion["entitled_product_ids"]) != 0:
        product_ids = original_promotion.get("entitled_product_ids")
        skus = get_products_sku(product_ids, promotion_settings)
    elif len(original_promotion["entitled_variant_ids"]) != 0:
        variant_ids = original_promotion.get("entitled_variant_ids")
        skus = get_sku_from_variants(variant_ids, promotion_settings)
    elif len(original_promotion["entitled_collection_ids"]) != 0:
        collection_ids = original_promotion.get("entitled_collection_ids")
        skus = get_products_from_collections(collection_ids, promotion_settings)
    else:
        raise Exception("Easy Promo: entitled item not found")

    pg1.nodes = []
    for line_item in skus.get("skus", None):
        node = mpay_promo.Node()
        item_id = line_item
        if not item_id:
            return promotion_dict
        node.node_type = NodeType.ITEM.value
        node.node_id = item_id
        pg1.nodes.append(node)

    promo.groups = [pg1]
    promotion_dict[promo.promo_id] = promo
    return promotion_dict


def parse_basket_level_promotion(
    promotion_dict,
    original_promotion,
    *,
    store_id,
    promo_retailer,
    region,
    promotion_settings,
    test=False,
    coupon_check_fn=None,
):
    """Build a Basket Threshold promotion from a Shopify price rule.

    Args:
        promotion_dict: accumulator dict ``{promo_id: Promotion}``.
        original_promotion: Shopify price rule dict (``target_selection="all"``).
        store_id: UUID of the MishiPay store.
        promo_retailer: retailer string.
        region: store region string.
        promotion_settings: dict with Shopify API endpoints and token.
        test: if True, override end date to +5 days.
        coupon_check_fn: callable(title) → bool.
    """
    if test:
        valid_to_date = datetime.datetime.today() + datetime.timedelta(days=5)
        original_promotion["ends_at"] = valid_to_date.strftime("%Y-%m-%d") + "T00:00:00+11:00"

    promo = mpay_promo.Promotion()
    promo.retailer = promo_retailer
    promo.add_store(store_id)

    promo.date_start = get_start_datetime(original_promotion["starts_at"])
    promo.date_end = get_end_datetime(original_promotion["ends_at"])
    title = original_promotion["title"]
    promo.availability = Availability.SPECIAL.value
    if coupon_check_fn and coupon_check_fn(title=title):
        promo.special_promo_info = [
            {
                "group_qualifier_id": f"b-{region.lower()}-{title.lower()}",
                "description": original_promotion["title"],
            }
        ]
    promo.discount_value_on = DiscountOn.FP.value
    promo.apply_on_discounted_items = False
    promo.max_application_limit = 65535
    if original_promotion["once_per_customer"]:
        promo.max_application_limit = 1
    promo.discount_type_strategy = DiscountTypeStrategy.ALL_ITEMS.value
    promo.discounted_group_item_selection_criteria = GroupItemSelectionCriteria.MOST_EXPENSIVE.value
    promo.layer = 100
    promo.evaluate_criteria = PromoEvaluateCriteria.PRIORITY.value
    promo.is_active = True
    if not original_promotion["title"]:
        raise Exception("Threshold Promo: Promo Name not found")
    promo.title = original_promotion["title"]

    discount_value = abs(float(original_promotion["value"]))
    if original_promotion["value_type"] == "percentage":
        promo.discount_type = DiscountType.PERCENT_OFF.value
        promo.discount_value = get_rounded_value(decimal.Decimal(discount_value), 2)
        promo.evaluate_priority = max(0, 100 - int(float(promo.discount_value)))
    elif original_promotion["value_type"] == "fixed_amount":
        promo.discount_type = DiscountType.VALUE_OFF.value
        promo.discount_value = get_rounded_value(decimal.Decimal(discount_value), 2)
        promo.evaluate_priority = int(10000 / decimal.Decimal(promo.discount_value))
    else:
        raise Exception("Threshold Promo: Unknown discount method")

    promo.promo_id = str(original_promotion["id"])
    promo.family = PromoFamily.BASKET_THRESHOLD.value
    promo.discount_apply_type = ApplicationType.BASKET.value

    pg1 = mpay_promo.Group()
    pg1.name = str(original_promotion["id"])
    pg1.qty_or_value_min = 1
    pg1.qty_or_value_max = None

    pg1.nodes = []
    node = mpay_promo.Node()
    node.node_type = NodeType.ITEM.value
    node.node_id = "all"
    pg1.nodes.append(node)

    promo.groups = [pg1]
    promotion_dict[promo.promo_id] = promo
    return promotion_dict


# ---------------------------------------------------------------------------
# Promotion parsing — Automatic Codes (GraphQL format)
# ---------------------------------------------------------------------------

class AutomaticCodesStatus:
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class AutomaticCodesType:
    DiscountAutomaticBasic = "DiscountAutomaticBasic"
    DiscountAutomaticBxgy = "DiscountAutomaticBxgy"


class AutomaticCodesDiscountType:
    DiscountPercentage = "DiscountPercentage"
    DiscountAmount = "DiscountAmount"
    DiscountQuantity = "DiscountQuantity"
    DiscountOnQuantity = "DiscountOnQuantity"


def parse_automatic_codes_easy_level_promotion(
    promotion_dict,
    original_promotion,
    *,
    store_id,
    promo_retailer,
    promotion_settings,
    test=False,
):
    """Build an Easy/Basket Threshold promotion from a Shopify automatic basic discount.

    If ``minimumRequirement.greaterThanOrEqualToSubtotal`` is present, the
    promotion is upgraded to Basket Threshold family.

    Args:
        promotion_dict: accumulator dict.
        original_promotion: parsed GraphQL ``DiscountAutomaticBasic`` node.
        store_id: UUID of the MishiPay store.
        promo_retailer: retailer string.
        promotion_settings: dict with Shopify API endpoints and token.
        test: if True, override end date to +5 days.
    """
    if test:
        valid_to_date = datetime.datetime.today() + datetime.timedelta(days=5)
        original_promotion["endsAt"] = valid_to_date.strftime("%Y-%m-%d") + "T00:00:00+11:00"

    promo = mpay_promo.Promotion()
    promo.retailer = promo_retailer
    promo.add_store(store_id)

    promo.date_start = get_start_datetime(original_promotion["startsAt"])
    promo.date_end = get_end_datetime(original_promotion["endsAt"])
    promo.availability = Availability.ALL.value
    promo.discount_value_on = DiscountOn.FP.value
    promo.max_application_limit = 65535
    promo.discount_type_strategy = DiscountTypeStrategy.ALL_ITEMS.value
    promo.discounted_group_item_selection_criteria = GroupItemSelectionCriteria.LEAST_EXPENSIVE.value
    promo.layer = 1
    promo.evaluate_criteria = PromoEvaluateCriteria.PRIORITY.value
    promo.is_active = True
    promo.title = original_promotion["title"]
    promo.description = original_promotion["summary"]

    customer_gets_data = original_promotion["customerGets"]
    discount_values = customer_gets_data.get("value", {})
    if not discount_values:
        raise Exception("Easy Promo for automatic codes: Unknown discount method {}".format(customer_gets_data))
    discount_type = discount_values.get("__typename")
    if discount_type == AutomaticCodesDiscountType.DiscountPercentage:
        promo.discount_type = DiscountType.PERCENT_OFF.value
        promo.discount_value = str(discount_values.get("percentage") * 100)
    elif discount_type == AutomaticCodesDiscountType.DiscountAmount:
        promo.discount_type = DiscountType.VALUE_OFF.value
        promo.discount_value = discount_values.get("amount").get("amount")
    else:
        raise Exception("Easy Promo for automatic codes: Unknown discount method {}".format(customer_gets_data))

    promo.evaluate_priority = compute_evaluate_priority(promo.discount_type, promo.discount_value)

    promo.promo_id = str(original_promotion["id"])
    promo.layer = "1"
    promo.family = PromoFamily.EASY.value

    pg1 = mpay_promo.Group()
    pg1.name = str(original_promotion["id"])
    minimum_requirement = original_promotion.get("minimumRequirement", {})
    if minimum_requirement:
        if minimum_requirement.get("greaterThanOrEqualToSubtotal", {}):
            pg1.qty_or_value_min = minimum_requirement.get("greaterThanOrEqualToSubtotal").get("amount")
            promo.family = PromoFamily.BASKET_THRESHOLD.value
            promo.max_application_limit = 1
            promo.apply_on_discounted_items = False
        elif minimum_requirement.get("greaterThanOrEqualToQuantity", {}):
            pg1.qty_or_value_min = minimum_requirement.get("greaterThanOrEqualToQuantity")
        else:
            raise Exception("Easy Promo for automatic codes: Unknown minimum requirement {}".format(minimum_requirement))
    pg1.qty_or_value_max = None

    skus = resolve_skus_from_edges(customer_gets_data.get("items", {}), promotion_settings)

    pg1.nodes = []
    for line_item in skus.get("skus", None):
        node = mpay_promo.Node()
        item_id = line_item
        if not item_id:
            return promotion_dict
        node.node_type = NodeType.ITEM.value
        node.node_id = item_id
        pg1.nodes.append(node)

    promo.groups = [pg1]
    promotion_dict[promo.promo_id] = promo
    return promotion_dict


def parse_automatic_mix_match_discount_target(
    promotion_dict,
    original_promotion,
    *,
    store_id,
    promo_retailer,
    promotion_settings,
    test=False,
):
    """Build a Requisite Groups with Discounted Target promotion from a Shopify BXGY discount.

    Creates a 2-group promotion: ``g1`` (buy/requisite group) and
    ``g2`` (get/target discounted group).

    Args:
        promotion_dict: accumulator dict.
        original_promotion: parsed GraphQL ``DiscountAutomaticBxgy`` node.
        store_id: UUID of the MishiPay store.
        promo_retailer: retailer string.
        promotion_settings: dict with Shopify API endpoints and token.
        test: if True, override end date to +5 days.
    """
    if test:
        valid_to_date = datetime.datetime.today() + datetime.timedelta(days=5)
        original_promotion["endsAt"] = valid_to_date.strftime("%Y-%m-%d") + "T00:00:00+11:00"

    promo = mpay_promo.Promotion()
    promo.retailer = promo_retailer
    promo.add_store(store_id)

    promo.date_start = get_start_datetime(original_promotion["startsAt"])
    promo.date_end = get_end_datetime(original_promotion["endsAt"])
    promo.availability = Availability.ALL.value
    promo.discount_value_on = DiscountOn.MRP.value
    promo.max_application_limit = 65535
    promo.discount_type_strategy = DiscountTypeStrategy.ALL_ITEMS.value
    promo.discounted_group_item_selection_criteria = GroupItemSelectionCriteria.LEAST_EXPENSIVE.value
    promo.requisite_groups_item_selection_criteria = GroupItemSelectionCriteria.LEAST_EXPENSIVE.value
    promo.layer = 1
    promo.evaluate_criteria = PromoEvaluateCriteria.PRIORITY.value
    promo.is_active = True
    promo.title = original_promotion["title"]
    promo.description = original_promotion["summary"]
    promo.family = PromoFamily.REQUISITE_GROUPS_WITH_DISCOUNTED_TARGET.value
    promo.discount_apply_type = ApplicationType.BASKET.value

    customer_gets_data = original_promotion["customerGets"]
    customer_buys_data = original_promotion["customerBuys"]

    # --- Discount type & value from customerGets ---
    discount_values = customer_gets_data.get("value", {})
    if (
        discount_values.get("__typename") == AutomaticCodesDiscountType.DiscountOnQuantity
        or discount_values.get("__typename") == AutomaticCodesDiscountType.DiscountPercentage
    ):
        promo.discount_type = DiscountType.PERCENT_OFF.value
        promo.discount_value = 100
        if discount_values.get("__typename") == AutomaticCodesDiscountType.DiscountPercentage:
            promo.discount_value = discount_values.get("percentage")
    elif discount_values.get("__typename") == AutomaticCodesDiscountType.DiscountAmount:
        promo.discount_type = DiscountType.VALUE_OFF.value
        promo.discount_value = discount_values.get("amount").get("amount")
    else:
        raise Exception("requisites Promo for automatic codes: Unknown discount method {}".format(customer_gets_data))

    promo.evaluate_priority = compute_evaluate_priority(promo.discount_type, promo.discount_value)

    promo.promo_id = str(original_promotion["id"])
    promo.target_discounted_group_name = "g2"
    promo.target_discounted_group_qty_min = ""

    # --- Target group (customerGets → g2) ---
    target_group_skus = resolve_skus_from_edges(
        customer_gets_data.get("items", {}), promotion_settings
    )

    target_group_qty_or_value_min = ""
    target_group_discount_values = customer_gets_data.get("value", {})
    if target_group_discount_values.get("__typename") == AutomaticCodesDiscountType.DiscountPercentage:
        target_group_qty_or_value_min = target_group_discount_values.get("percentage")
    elif target_group_discount_values.get("__typename") == "DiscountOnQuantity":
        target_group_qty_or_value_min = target_group_discount_values.get("quantity").get("quantity")
    elif target_group_discount_values.get("__typename") == AutomaticCodesDiscountType.DiscountAmount:
        target_group_qty_or_value_min = target_group_discount_values.get("amount").get("amount")
    else:
        raise Exception("target Promo for automatic codes: Unknown discount method {}".format(customer_gets_data))

    promo.target_discounted_group_qty_min = target_group_qty_or_value_min

    # --- Requisite group (customerBuys → g1) ---
    requisite_group_skus = resolve_skus_from_edges(
        customer_buys_data.get("items", {}), promotion_settings
    )

    requisite_group_qty_or_value_min = ""
    requisites_group_discount_values = customer_buys_data.get("value", {})
    if requisites_group_discount_values.get("__typename") == AutomaticCodesDiscountType.DiscountPercentage:
        requisite_group_qty_or_value_min = requisites_group_discount_values.get("percentage")
    elif requisites_group_discount_values.get("__typename") == AutomaticCodesDiscountType.DiscountQuantity:
        requisite_group_qty_or_value_min = requisites_group_discount_values.get("quantity")
    elif requisites_group_discount_values.get("__typename") == AutomaticCodesDiscountType.DiscountAmount:
        requisite_group_qty_or_value_min = requisites_group_discount_values.get("amount").get("amount")
    else:
        raise Exception("target Promo for automatic codes: Unknown discount method {}".format(customer_buys_data))

    # --- Build groups ---
    pg1 = mpay_promo.Group()
    pg1.name = "g1"
    pg1.nodes = []
    pg1.qty_or_value_min = requisite_group_qty_or_value_min
    for line_item in requisite_group_skus.get("skus", None):
        node = mpay_promo.Node()
        item_id = line_item
        if not item_id:
            return promotion_dict
        node.node_type = NodeType.ITEM.value
        node.node_id = item_id
        pg1.nodes.append(node)
    promo.groups = [pg1]

    pg2 = mpay_promo.Group()
    pg2.name = "g2"
    pg2.nodes = []
    pg2.qty_or_value_min = target_group_qty_or_value_min
    for line_item in target_group_skus.get("skus", None):
        node = mpay_promo.Node()
        item_id = line_item
        if not item_id:
            return promotion_dict
        node.node_type = NodeType.ITEM.value
        node.node_id = item_id
        pg2.nodes.append(node)
    promo.groups.append(pg2)

    promotion_dict[promo.promo_id] = promo
    return promotion_dict


# ---------------------------------------------------------------------------
# Webhook-facing helpers
# ---------------------------------------------------------------------------

def build_promotion_settings_from_config(config):
    """Build the ``promotion_settings`` dict from a :class:`ShopifyWebhookConfig`.

    Returns a dict compatible with the SKU resolution functions
    (``get_products_sku``, ``get_products_from_collections``,
    ``get_sku_from_variants``).
    """
    base_url = f"https://{config.shopify_domain}/admin/api/{config.api_version}"
    return {
        "access_token": config.api_access_token,
        "products_in_collection_fetch_endpoint": f"{base_url}/collections",
        "products_sku_fetch_endpoint": f"{base_url}/products",
        "variants_sku_fetch_endpoint": f"{base_url}/variants",
    }


def resolve_entitled_skus(price_rule, promotion_settings):
    """Resolve SKUs from a price rule's entitled product/variant/collection IDs.

    Checks ``entitled_product_ids``, ``entitled_variant_ids``, and
    ``entitled_collection_ids`` in order and delegates to the appropriate
    SKU-resolution function.

    Returns:
        dict: ``{"skus": [barcode, ...]}``

    Raises:
        ValueError: if no entitled items are found on the price rule.
    """
    if price_rule.get("entitled_product_ids"):
        return get_products_sku(
            list(price_rule["entitled_product_ids"]), promotion_settings
        )
    elif price_rule.get("entitled_variant_ids"):
        return get_sku_from_variants(
            list(price_rule["entitled_variant_ids"]), promotion_settings
        )
    elif price_rule.get("entitled_collection_ids"):
        return get_products_from_collections(
            list(price_rule["entitled_collection_ids"]), promotion_settings
        )
    else:
        raise ValueError("Price rule has no entitled items (products, variants, or collections)")


def build_promo_groups(promo_id, resolved_skus, *, qty_or_value_min=1):
    """Construct a single-group list of :class:`~mishipay_items.mpay_promo.Group`
    and :class:`~mishipay_items.mpay_promo.Node` objects from resolved SKUs.

    Args:
        promo_id: Shopify price rule ID (used as group name).
        resolved_skus: dict ``{"skus": [barcode, ...]}``.
        qty_or_value_min: minimum quantity/value for the group (default 1).

    Returns:
        list: ``[Group]`` with nodes populated from *resolved_skus*.
    """
    group = mpay_promo.Group()
    group.name = str(promo_id)
    group.qty_or_value_min = qty_or_value_min
    group.qty_or_value_max = None
    group.nodes = []
    for sku in resolved_skus.get("skus", []):
        if not sku:
            continue
        node = mpay_promo.Node()
        node.node_type = NodeType.ITEM.value
        node.node_id = sku
        group.nodes.append(node)
    return [group]


# ---------------------------------------------------------------------------
# Webhook-facing promotion builders
# ---------------------------------------------------------------------------

def build_easy_promotion(price_rule, config):
    """Build an Easy-family promotion from a Shopify price rule webhook payload.

    For price rules with ``target_selection='entitled'``.  Resolves entitled
    SKUs via the Shopify Admin API using credentials from *config*.

    Args:
        price_rule: Shopify price rule dict (REST webhook payload).
        config: :class:`~shopify_webhooks.models.ShopifyWebhookConfig` instance.

    Returns:
        :class:`~mishipay_items.mpay_promo.Promotion`
    """
    promotion_settings = build_promotion_settings_from_config(config)

    promo = mpay_promo.Promotion()
    promo.retailer = config.extra_data.get("promo_retailer", str(config.store_id))
    promo.add_store(str(config.store_id))
    promo.promo_id = str(price_rule["id"])
    promo.family = PromoFamily.EASY.value
    promo.layer = "1"

    promo.date_start = get_start_datetime(price_rule["starts_at"])
    promo.date_end = get_end_datetime(price_rule.get("ends_at"))
    promo.availability = Availability.ALL.value
    promo.discount_value_on = DiscountOn.FP.value
    promo.max_application_limit = 65535
    if price_rule.get("once_per_customer"):
        promo.max_application_limit = 1

    if price_rule.get("allocation_method") == "across":
        promo.discount_type_strategy = DiscountTypeStrategy.ALL_ITEMS.value
    elif price_rule.get("allocation_method") == "each":
        promo.discount_type_strategy = DiscountTypeStrategy.EACH_ITEM.value
    else:
        promo.discount_type_strategy = DiscountTypeStrategy.ALL_ITEMS.value

    promo.discounted_group_item_selection_criteria = (
        GroupItemSelectionCriteria.LEAST_EXPENSIVE.value
    )
    promo.evaluate_criteria = PromoEvaluateCriteria.PRIORITY.value
    promo.is_active = is_promotion_active(promo.date_start, promo.date_end)
    promo.title = price_rule.get("title", "")
    promo.description = price_rule.get("title", "")

    # Discount type and value
    discount_value = abs(float(price_rule["value"]))
    if price_rule["value_type"] == "percentage":
        promo.discount_type = DiscountType.PERCENT_OFF.value
        promo.discount_value = get_rounded_value(decimal.Decimal(discount_value), 2)
    elif price_rule["value_type"] == "fixed_amount":
        promo.discount_type = DiscountType.VALUE_OFF.value
        promo.discount_value = get_rounded_value(decimal.Decimal(discount_value), 2)
    else:
        raise ValueError(
            f"Unknown discount value_type: {price_rule['value_type']}"
        )

    promo.evaluate_priority = compute_evaluate_priority(
        promo.discount_type, promo.discount_value
    )

    # Resolve entitled SKUs and build groups
    resolved_skus = resolve_entitled_skus(price_rule, promotion_settings)
    promo.groups = build_promo_groups(price_rule["id"], resolved_skus)

    return promo


def build_basket_threshold_promotion(price_rule, config):
    """Build a Basket Threshold promotion from a Shopify price rule webhook payload.

    For price rules with ``target_selection='all'``.  Basket Threshold promos
    use ``layer=100``, a single group with an ``"all"`` node, and optionally
    honour ``prerequisite_subtotal_range`` as the minimum basket value.

    Args:
        price_rule: Shopify price rule dict (REST webhook payload).
        config: :class:`~shopify_webhooks.models.ShopifyWebhookConfig` instance.

    Returns:
        :class:`~mishipay_items.mpay_promo.Promotion`
    """
    promo = mpay_promo.Promotion()
    promo.retailer = config.extra_data.get("promo_retailer", str(config.store_id))
    promo.add_store(str(config.store_id))
    promo.promo_id = str(price_rule["id"])
    promo.family = PromoFamily.BASKET_THRESHOLD.value
    promo.layer = 100
    promo.discount_apply_type = ApplicationType.BASKET.value

    promo.date_start = get_start_datetime(price_rule["starts_at"])
    promo.date_end = get_end_datetime(price_rule.get("ends_at"))
    promo.availability = Availability.ALL.value
    promo.discount_value_on = DiscountOn.FP.value
    promo.apply_on_discounted_items = False
    promo.max_application_limit = 65535
    if price_rule.get("once_per_customer"):
        promo.max_application_limit = 1

    promo.discount_type_strategy = DiscountTypeStrategy.ALL_ITEMS.value
    promo.discounted_group_item_selection_criteria = (
        GroupItemSelectionCriteria.MOST_EXPENSIVE.value
    )
    promo.evaluate_criteria = PromoEvaluateCriteria.PRIORITY.value
    promo.is_active = is_promotion_active(promo.date_start, promo.date_end)

    title = price_rule.get("title", "")
    if not title:
        raise ValueError("Basket Threshold promotion requires a title")
    promo.title = title

    # Discount type and value
    discount_value = abs(float(price_rule["value"]))
    if price_rule["value_type"] == "percentage":
        promo.discount_type = DiscountType.PERCENT_OFF.value
        promo.discount_value = get_rounded_value(decimal.Decimal(discount_value), 2)
    elif price_rule["value_type"] == "fixed_amount":
        promo.discount_type = DiscountType.VALUE_OFF.value
        promo.discount_value = get_rounded_value(decimal.Decimal(discount_value), 2)
    else:
        raise ValueError(
            f"Unknown discount value_type: {price_rule['value_type']}"
        )

    promo.evaluate_priority = compute_evaluate_priority(
        promo.discount_type, promo.discount_value
    )

    # Single group with "all" node; honour prerequisite_subtotal_range
    group = mpay_promo.Group()
    group.name = str(price_rule["id"])
    group.qty_or_value_max = None

    subtotal_range = price_rule.get("prerequisite_subtotal_range")
    if subtotal_range and subtotal_range.get("greater_than_or_equal_to"):
        group.qty_or_value_min = subtotal_range["greater_than_or_equal_to"]
    else:
        group.qty_or_value_min = 1

    group.nodes = []
    node = mpay_promo.Node()
    node.node_type = NodeType.ITEM.value
    node.node_id = "all"
    group.nodes.append(node)

    promo.groups = [group]

    return promo


def build_bxgy_promotion(automatic_discount, config):
    """Build a Requisite Groups w/ Discounted Target promotion from a Shopify BXGY discount.

    For ``DiscountAutomaticBxgy`` payloads (GraphQL format).  Creates a 2-group
    promotion: ``g1`` (buy/requisite group from ``customerBuys``) and ``g2``
    (get/target discounted group from ``customerGets``).

    Handles ``DiscountPercentage``, ``DiscountOnQuantity``, and
    ``DiscountAmount`` discount types on the ``customerGets`` side.

    Args:
        automatic_discount: parsed GraphQL ``DiscountAutomaticBxgy`` node dict.
        config: :class:`~shopify_webhooks.models.ShopifyWebhookConfig` instance.

    Returns:
        :class:`~mishipay_items.mpay_promo.Promotion`
    """
    promotion_settings = build_promotion_settings_from_config(config)

    promo = mpay_promo.Promotion()
    promo.retailer = config.extra_data.get("promo_retailer", str(config.store_id))
    promo.add_store(str(config.store_id))
    promo.promo_id = str(automatic_discount["id"])
    promo.family = PromoFamily.REQUISITE_GROUPS_WITH_DISCOUNTED_TARGET.value
    promo.layer = 1
    promo.discount_apply_type = ApplicationType.BASKET.value

    promo.date_start = get_start_datetime(automatic_discount["startsAt"])
    promo.date_end = get_end_datetime(automatic_discount.get("endsAt"))
    promo.availability = Availability.ALL.value
    promo.discount_value_on = DiscountOn.MRP.value
    promo.max_application_limit = 65535
    promo.discount_type_strategy = DiscountTypeStrategy.ALL_ITEMS.value
    promo.discounted_group_item_selection_criteria = (
        GroupItemSelectionCriteria.LEAST_EXPENSIVE.value
    )
    promo.requisite_groups_item_selection_criteria = (
        GroupItemSelectionCriteria.LEAST_EXPENSIVE.value
    )
    promo.evaluate_criteria = PromoEvaluateCriteria.PRIORITY.value
    promo.is_active = is_promotion_active(promo.date_start, promo.date_end)
    promo.title = automatic_discount.get("title", "")
    promo.description = automatic_discount.get("summary", "")
    promo.target_discounted_group_name = "g2"

    # --- Discount type & value from customerGets ---
    customer_gets = automatic_discount["customerGets"]
    customer_buys = automatic_discount["customerBuys"]

    discount_values = customer_gets.get("value", {})
    discount_typename = discount_values.get("__typename", "")

    if discount_typename in (
        AutomaticCodesDiscountType.DiscountOnQuantity,
        AutomaticCodesDiscountType.DiscountPercentage,
    ):
        promo.discount_type = DiscountType.PERCENT_OFF.value
        promo.discount_value = 100
        if discount_typename == AutomaticCodesDiscountType.DiscountPercentage:
            promo.discount_value = discount_values.get("percentage")
    elif discount_typename == AutomaticCodesDiscountType.DiscountAmount:
        promo.discount_type = DiscountType.VALUE_OFF.value
        promo.discount_value = discount_values.get("amount", {}).get("amount")
    else:
        raise ValueError(
            f"BXGY promotion: unknown discount type '{discount_typename}'"
        )

    promo.evaluate_priority = compute_evaluate_priority(
        promo.discount_type, promo.discount_value
    )

    # --- Target group quantity (customerGets → g2) ---
    target_qty_min = _extract_qty_or_value_min(discount_values)
    promo.target_discounted_group_qty_min = target_qty_min

    # --- Resolve SKUs for both groups ---
    target_group_skus = resolve_skus_from_edges(
        customer_gets.get("items", {}), promotion_settings
    )
    requisite_group_skus = resolve_skus_from_edges(
        customer_buys.get("items", {}), promotion_settings
    )

    # --- Requisite group quantity (customerBuys → g1) ---
    buys_value = customer_buys.get("value", {})
    requisite_qty_min = _extract_qty_or_value_min(buys_value)

    # --- Build g1 (requisite / buy group) ---
    g1 = mpay_promo.Group()
    g1.name = "g1"
    g1.qty_or_value_min = requisite_qty_min
    g1.nodes = []
    for sku in requisite_group_skus.get("skus", []):
        if not sku:
            continue
        node = mpay_promo.Node()
        node.node_type = NodeType.ITEM.value
        node.node_id = sku
        g1.nodes.append(node)

    # --- Build g2 (target / get group) ---
    g2 = mpay_promo.Group()
    g2.name = "g2"
    g2.qty_or_value_min = target_qty_min
    g2.nodes = []
    for sku in target_group_skus.get("skus", []):
        if not sku:
            continue
        node = mpay_promo.Node()
        node.node_type = NodeType.ITEM.value
        node.node_id = sku
        g2.nodes.append(node)

    promo.groups = [g1, g2]

    return promo


def _extract_qty_or_value_min(value_block):
    """Extract the quantity or value minimum from a GraphQL discount value block.

    Supports ``DiscountPercentage`` (percentage), ``DiscountOnQuantity``
    (quantity.quantity), and ``DiscountAmount`` (amount.amount).

    Args:
        value_block: dict from ``customerGets.value`` or ``customerBuys.value``.

    Returns:
        Numeric minimum value, or ``""`` if not determinable.
    """
    typename = value_block.get("__typename", "")
    if typename == AutomaticCodesDiscountType.DiscountPercentage:
        return value_block.get("percentage", "")
    elif typename == AutomaticCodesDiscountType.DiscountOnQuantity:
        return value_block.get("quantity", {}).get("quantity", "")
    elif typename == AutomaticCodesDiscountType.DiscountQuantity:
        return value_block.get("quantity", "")
    elif typename == AutomaticCodesDiscountType.DiscountAmount:
        return value_block.get("amount", {}).get("amount", "")
    return ""
