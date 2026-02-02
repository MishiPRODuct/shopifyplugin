import logging

import requests as http_requests
from django.conf import settings
from django.core.cache import cache
from inventory_service.client import InventoryV1Client

from ..models import ShopifyWebhookConfig
from ..router import register_handler
from ..services.inventory_sync import (
    map_shopify_product_to_inventory,
    send_to_inventory_service,
)

logger = logging.getLogger(__name__)

# Cache settings for inventory_item_id → barcode mapping.
# Populated proactively from product webhooks and lazily from Shopify API.
_INV_ITEM_CACHE_PREFIX = "shopify:inv_item"
_INV_ITEM_CACHE_TIMEOUT = 86400  # 24 hours


def _inv_item_cache_key(shop_domain, inventory_item_id):
    """Build a cache key for an inventory_item_id → barcode mapping."""
    return f"{_INV_ITEM_CACHE_PREFIX}:{shop_domain}:{inventory_item_id}"


def _cache_variant_mappings(payload, shop_domain):
    """Extract inventory_item_id → barcode mappings from a product payload and cache them.

    Called from product create/update handlers to proactively populate the
    cache so that subsequent ``inventory_levels/update`` webhooks can resolve
    barcodes without a Shopify API call.
    """
    variants = payload.get("variants", [])
    for variant in variants:
        inv_item_id = variant.get("inventory_item_id")
        if not inv_item_id:
            continue
        # Use the same fallback chain as the inventory sync service:
        # variant.barcode → variant.sku → str(variant.id)
        barcode = (
            variant.get("barcode")
            or variant.get("sku")
            or str(variant.get("id", ""))
        )
        if barcode:
            cache.set(
                _inv_item_cache_key(shop_domain, inv_item_id),
                barcode,
                _INV_ITEM_CACHE_TIMEOUT,
            )


def _resolve_inventory_item_to_barcode(inventory_item_id, config):
    """Resolve a Shopify inventory_item_id to a barcode/SKU.

    Checks the Django cache first (populated by product create/update
    handlers).  On cache miss, calls the Shopify Admin REST API to
    fetch the inventory item's SKU and caches the result.

    Returns:
        str: barcode or SKU for the variant.
    """
    cache_key = _inv_item_cache_key(config.shopify_domain, inventory_item_id)
    barcode = cache.get(cache_key)
    if barcode:
        return barcode

    # Cache miss — call Shopify Admin API for the inventory item.
    url = (
        f"https://{config.shopify_domain}/admin/api/{config.api_version}"
        f"/inventory_items/{inventory_item_id}.json"
    )
    headers = {"X-Shopify-Access-Token": config.api_access_token}
    response = http_requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()

    inventory_item = response.json().get("inventory_item", {})
    # SKU is the best identifier available from the inventory_items endpoint.
    barcode = inventory_item.get("sku") or str(inventory_item_id)

    cache.set(cache_key, barcode, _INV_ITEM_CACHE_TIMEOUT)
    logger.debug(
        "Cached inventory_item_id %s → barcode %s (shop=%s)",
        inventory_item_id,
        barcode,
        config.shopify_domain,
    )
    return barcode


def handle_product_create(event, payload):
    """Handle products/create webhook — create items in Inventory Service.

    Maps the Shopify product payload to the inventory schema and sends
    it to the Inventory Service with delta=True (upsert behaviour).
    Also proactively caches inventory_item_id → barcode mappings for
    future stock-level webhooks.
    """
    config = ShopifyWebhookConfig.objects.get(store=event.store)
    _cache_variant_mappings(payload, config.shopify_domain)
    items = map_shopify_product_to_inventory(payload, config)
    send_to_inventory_service(
        items, str(event.store.store_id), str(config.retailer_id)
    )
    logger.info(
        "Created %d inventory items for product %s (store=%s)",
        len(items),
        payload.get("id"),
        event.store_id,
    )


def handle_product_update(event, payload):
    """Handle products/update webhook — update items in Inventory Service.

    Same as create — the inventory import uses upsert semantics with
    delta=True, so existing items are updated and new variants are created.
    Also refreshes the inventory_item_id → barcode cache.
    """
    config = ShopifyWebhookConfig.objects.get(store=event.store)
    _cache_variant_mappings(payload, config.shopify_domain)
    items = map_shopify_product_to_inventory(payload, config)
    send_to_inventory_service(
        items, str(event.store.store_id), str(config.retailer_id)
    )
    logger.info(
        "Updated %d inventory items for product %s (store=%s)",
        len(items),
        payload.get("id"),
        event.store_id,
    )


def handle_product_delete(event, payload):
    """Handle products/delete webhook — zero stock for all variants (Phase 1).

    Shopify ``products/delete`` only sends ``{"id": <product_id>}``.
    We query the Inventory Service for existing variants by
    ``retailerProductId``, then push them back with ``stockLevel: 0``.

    Phase 2 (future) will call a proper DELETE endpoint on the
    Inventory Service once it exists.
    """
    config = ShopifyWebhookConfig.objects.get(store=event.store)
    product_id = str(payload.get("id", ""))
    if not product_id:
        raise ValueError("Missing product ID in delete webhook payload")

    store_id = str(event.store.store_id)
    retailer_id = str(config.retailer_id)

    # Look up existing items for this product in the Inventory Service.
    client = InventoryV1Client(settings.INVENTORY_SERVICE_URL)
    response = client.list_variants_by_filters(
        store_id, {"retailerProductId": [product_id]}
    )
    variants = response.get("items", [])
    if not variants:
        logger.warning(
            "No inventory items found for deleted product %s (store=%s)",
            product_id,
            store_id,
        )
        return

    # Build zero-stock update payload using the existing update_inventory API.
    zero_stock_items = []
    for variant in variants:
        barcodes = variant.get("barcodes", [])
        if not barcodes:
            continue
        zero_stock_items.append(
            {
                "operation": "upsert",
                "barcodes": barcodes,
                "stockLevel": 0,
            }
        )

    if not zero_stock_items:
        logger.warning(
            "No barcodes found for deleted product %s (store=%s)",
            product_id,
            store_id,
        )
        return

    inventory_update_body = {
        "storeId": store_id,
        "retailerId": retailer_id,
        "categories": [],
        "items": zero_stock_items,
        "performInserts": False,
    }
    client.update_inventory(inventory_update_body)
    logger.info(
        "Zeroed stock for %d variants of deleted product %s (store=%s)",
        len(zero_stock_items),
        product_id,
        store_id,
    )


def handle_inventory_level_update(event, payload):
    """Handle inventory_levels/update webhook — update stock for one variant.

    This webhook fires when stock changes independently of product updates.
    The payload shape is different from product webhooks::

        {
            "inventory_item_id": 808950810,
            "location_id": 905684977,
            "available": 6,
            "updated_at": "2024-01-01T00:00:00Z"
        }

    Resolution flow:
    1. Resolve ``inventory_item_id`` to barcode via cache (populated by
       product create/update handlers) or Shopify Admin API fallback.
    2. Send stock-level update to the Inventory Service.
    """
    config = ShopifyWebhookConfig.objects.get(store=event.store)

    inventory_item_id = payload.get("inventory_item_id")
    available = payload.get("available")

    if inventory_item_id is None:
        raise ValueError("Missing inventory_item_id in inventory_levels/update payload")

    # ``available`` can be null when inventory tracking is disabled.
    if available is None:
        logger.info(
            "Skipping inventory_levels/update with available=null "
            "(inventory_item_id=%s, store=%s)",
            inventory_item_id,
            event.store_id,
        )
        return

    barcode = _resolve_inventory_item_to_barcode(inventory_item_id, config)

    store_id = str(event.store.store_id)
    retailer_id = str(config.retailer_id)

    client = InventoryV1Client(settings.INVENTORY_SERVICE_URL)
    inventory_update_body = {
        "storeId": store_id,
        "retailerId": retailer_id,
        "categories": [],
        "items": [
            {
                "operation": "upsert",
                "barcodes": [barcode],
                "stockLevel": max(0, available),
            }
        ],
        "performInserts": False,
    }
    client.update_inventory(inventory_update_body)
    logger.info(
        "Updated stock to %d for barcode %s (inventory_item_id=%s, store=%s)",
        available,
        barcode,
        inventory_item_id,
        store_id,
    )


# ---------------------------------------------------------------------------
# Handler registration — called when this module is imported via apps.ready()
# ---------------------------------------------------------------------------
register_handler("products/create", handle_product_create)
register_handler("products/update", handle_product_update)
register_handler("products/delete", handle_product_delete)
register_handler("inventory_levels/update", handle_inventory_level_update)
