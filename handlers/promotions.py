import logging

import requests as http_requests

from mishipay_items import mpay_promo
from mishipay_items.mpay_promo_enums import PromoFamily

from ..models import ShopifyWebhookConfig
from ..router import register_handler
from ..services.promotion_sync import (
    build_basket_threshold_promotion,
    build_easy_promotion,
    determine_family,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_retailer_name(config):
    """Return the retailer name used for PromotionBatchOperation.

    Reads ``promo_retailer`` from ``config.extra_data``, falling back to
    the string representation of ``config.store_id``.
    """
    return config.extra_data.get("promo_retailer", str(config.store_id))


def _build_promotion_for_price_rule(price_rule, config):
    """Determine family and build the appropriate promotion object.

    Returns:
        :class:`~mishipay_items.mpay_promo.Promotion` or ``None`` if the
        price rule is not mappable (e.g. shipping-type rules).
    """
    family = determine_family(price_rule)
    if family is None:
        logger.info(
            "Price rule %s not mappable to MishiPay family "
            "(target_type=%s, target_selection=%s)",
            price_rule.get("id"),
            price_rule.get("target_type"),
            price_rule.get("target_selection"),
        )
        return None

    if family == PromoFamily.EASY.value:
        return build_easy_promotion(price_rule, config)
    elif family == PromoFamily.BASKET_THRESHOLD.value:
        return build_basket_threshold_promotion(price_rule, config)
    else:
        logger.warning(
            "Unhandled family '%s' for price rule %s",
            family,
            price_rule.get("id"),
        )
        return None


# ---------------------------------------------------------------------------
# Webhook handlers
# ---------------------------------------------------------------------------

def handle_price_rule_create(event, payload):
    """Handle ``price_rules/create`` — create promotion in ms-promo.

    Determines the MishiPay family from the price rule payload, builds
    the appropriate promotion object, and pushes it to the promotions
    service via :class:`~mishipay_items.mpay_promo.PromotionBatchOperation`.
    """
    config = ShopifyWebhookConfig.objects.get(store=event.store)
    price_rule = payload

    promo = _build_promotion_for_price_rule(price_rule, config)
    if promo is None:
        return

    retailer = _get_retailer_name(config)
    batch_op = mpay_promo.PromotionBatchOperation(retailer=retailer)
    batch_op.create(promo)
    batch_op.commit()

    logger.info(
        "Created promotion %s (family=%s) for price rule %s (store=%s)",
        promo.promo_id,
        promo.family,
        price_rule.get("id"),
        event.store_id,
    )


def handle_price_rule_update(event, payload):
    """Handle ``price_rules/update`` — replace promotion in ms-promo.

    Deletes the existing promotion by ``promo_id_retailer`` (the Shopify
    price rule ID), then creates the new version.  Both operations are
    sent in a single batch transaction.
    """
    config = ShopifyWebhookConfig.objects.get(store=event.store)
    price_rule = payload

    promo = _build_promotion_for_price_rule(price_rule, config)
    if promo is None:
        return

    store_id = str(event.store.store_id)
    retailer = _get_retailer_name(config)

    # Build a minimal promo object for deletion (needs promo_id set).
    delete_promo = mpay_promo.Promotion()
    delete_promo.promo_id = str(price_rule["id"])

    batch_op = mpay_promo.PromotionBatchOperation(retailer=retailer)
    batch_op.delete(delete_promo, store_id)
    batch_op.create(promo)
    batch_op.commit()

    logger.info(
        "Updated promotion %s (family=%s) for price rule %s (store=%s)",
        promo.promo_id,
        promo.family,
        price_rule.get("id"),
        event.store_id,
    )


def handle_price_rule_delete(event, payload):
    """Handle ``price_rules/delete`` — delete promotion from ms-promo.

    Shopify ``price_rules/delete`` sends ``{"id": <price_rule_id>}``.
    Deletes the promotion by ``promo_id_retailer`` via
    :class:`~mishipay_items.mpay_promo.PromotionBatchOperation`.
    """
    config = ShopifyWebhookConfig.objects.get(store=event.store)
    price_rule_id = payload.get("id")
    if not price_rule_id:
        raise ValueError("Missing price rule ID in delete webhook payload")

    store_id = str(event.store.store_id)
    retailer = _get_retailer_name(config)

    delete_promo = mpay_promo.Promotion()
    delete_promo.promo_id = str(price_rule_id)

    batch_op = mpay_promo.PromotionBatchOperation(retailer=retailer)
    batch_op.delete(delete_promo, store_id)
    batch_op.commit()

    logger.info(
        "Deleted promotion for price rule %s (store=%s)",
        price_rule_id,
        event.store_id,
    )


def handle_collection_update(event, payload):
    """Handle ``collections/update`` — re-evaluate affected promotions.

    When a collection changes (products added/removed), any promotion
    that references the collection needs its SKU list rebuilt.

    Flow:
    1. Get the changed collection ID from the payload.
    2. Fetch all active price rules from Shopify for this store.
    3. For each price rule that references the changed collection
       (in ``entitled_collection_ids`` or ``prerequisite_collection_ids``),
       rebuild the promotion (delete old + create new).
    """
    config = ShopifyWebhookConfig.objects.get(store=event.store)
    collection_id = payload.get("id")
    if not collection_id:
        raise ValueError("Missing collection ID in collections/update payload")

    # Fetch all price rules from Shopify Admin API.
    base_url = (
        f"https://{config.shopify_domain}/admin/api/{config.api_version}"
    )
    headers = {"X-Shopify-Access-Token": config.api_access_token}

    price_rules = []
    url = f"{base_url}/price_rules.json?limit=250"
    while url:
        response = http_requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        price_rules.extend(data.get("price_rules", []))
        # Handle pagination via Link header.
        link_header = response.headers.get("Link", "")
        url = None
        if 'rel="next"' in link_header:
            for part in link_header.split(","):
                if 'rel="next"' in part:
                    url = part.split("<")[1].split(">")[0]
                    break

    # Find price rules that reference the changed collection.
    affected = []
    for pr in price_rules:
        entitled = pr.get("entitled_collection_ids", [])
        prerequisite = pr.get("prerequisite_collection_ids", [])
        if collection_id in entitled or collection_id in prerequisite:
            affected.append(pr)

    if not affected:
        logger.info(
            "No promotions reference collection %s (store=%s)",
            collection_id,
            event.store_id,
        )
        return

    store_id = str(event.store.store_id)
    retailer = _get_retailer_name(config)
    batch_op = mpay_promo.PromotionBatchOperation(retailer=retailer)

    rebuilt = 0
    for price_rule in affected:
        promo = _build_promotion_for_price_rule(price_rule, config)
        if promo is None:
            continue

        delete_promo = mpay_promo.Promotion()
        delete_promo.promo_id = str(price_rule["id"])
        batch_op.delete(delete_promo, store_id)
        batch_op.create(promo)
        rebuilt += 1

    if rebuilt > 0:
        batch_op.commit()

    logger.info(
        "Rebuilt %d promotions after collection %s update (store=%s)",
        rebuilt,
        collection_id,
        event.store_id,
    )


# ---------------------------------------------------------------------------
# Handler registration — called when this module is imported via apps.ready()
# ---------------------------------------------------------------------------
register_handler("price_rules/create", handle_price_rule_create)
register_handler("price_rules/update", handle_price_rule_update)
register_handler("price_rules/delete", handle_price_rule_delete)
register_handler("collections/update", handle_collection_update)
