"""Inventory sync service — maps Shopify product payloads to Inventory Service schema."""

import logging
import re

from django.conf import settings
from inventory_service.client import InventoryV1Client

logger = logging.getLogger(__name__)


def strip_html(html_string):
    """Strip HTML tags from a string and collapse whitespace."""
    if not html_string:
        return ""
    clean = re.sub(r"<[^>]+>", "", html_string)
    # Collapse multiple whitespace/newlines into single space.
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


def _get_variant_barcode(variant):
    """Get barcode for a variant using the fallback chain.

    Priority: variant.barcode → variant.sku → str(variant.id)
    """
    return (
        variant.get("barcode")
        or variant.get("sku")
        or str(variant.get("id", ""))
    )


def _get_variant_images(variant, product_images):
    """Get image URLs for a specific variant.

    Matches images by checking if the variant's id is in the image's
    ``variant_ids`` list.  Falls back to the first product image if
    no variant-specific image is found.
    """
    variant_id = variant.get("id")
    images = []

    for img in product_images:
        variant_ids = img.get("variant_ids", [])
        if variant_id and variant_id in variant_ids:
            src = img.get("src", "")
            if src:
                images.append(src)

    # Fallback: first product image if no variant-specific match.
    if not images and product_images:
        src = product_images[0].get("src", "")
        if src:
            images.append(src)

    return images


def _extract_option_value(variant, payload, option_name):
    """Extract a variant option value by option name (e.g. 'Size', 'Color').

    REST API webhooks store options as ``option1``, ``option2``, ``option3``
    on the variant.  The ``options`` array on the product tells us which
    position maps to which name.
    """
    for opt in payload.get("options", []):
        if opt.get("name", "").lower() == option_name.lower():
            pos = opt.get("position", 1)
            return variant.get(f"option{pos}")
    return None


def _build_pricing_guidance(variant, config):
    """Build pricingGuidance dict from tax config if present in extra_data.

    Returns None if ``ShopifyWebhookConfig.extra_data`` has no ``tax_mapping``.
    """
    tax_mapping = config.extra_data.get("tax_mapping")
    if not tax_mapping:
        return None

    base_price = float(variant.get("price", "0"))
    vat_percentage = float(tax_mapping.get("vat_percentage", 0))
    tax_code = tax_mapping.get("tax_code", "")
    tax_inclusive = tax_mapping.get("tax_inclusive", True)

    if tax_inclusive:
        including_vat = base_price
        excluding_vat = round(base_price / (1 + vat_percentage / 100), 2)
    else:
        excluding_vat = base_price
        including_vat = round(base_price * (1 + vat_percentage / 100), 2)

    return {
        "taxCode": str(tax_code),
        "vatPercentage": str(vat_percentage),
        "includingVat": str(including_vat),
        "excludingVat": str(excluding_vat),
    }


def _build_categories(payload):
    """Build categories list from product_type."""
    categories = []
    product_type = payload.get("product_type")
    if product_type:
        categories.append({"name": product_type, "image": "", "parent": None})
    return categories


def _determine_theme(payload):
    """Determine item theme based on product options.

    Returns ``"invariant"`` when there are no meaningful options
    (single option named "Title" is Shopify's default for no-options products).
    """
    options = payload.get("options", [])
    if not options:
        return "invariant"
    if len(options) == 1 and options[0].get("name") == "Title":
        return "invariant"
    return options[0].get("name", "invariant")


def map_shopify_product_to_inventory(payload, config):
    """Map a Shopify product webhook payload to Inventory Service items.

    Each Shopify variant becomes one inventory item.

    Args:
        payload: Shopify product webhook payload dict.
        config: ShopifyWebhookConfig instance.

    Returns:
        List of item dicts in Inventory Service schema.
    """
    # Skip inactive products.
    if payload.get("status") != "active":
        return []

    product_title = payload.get("title", "")
    description = strip_html(payload.get("body_html", ""))
    product_id = str(payload.get("id", ""))
    product_images = payload.get("images", [])
    categories = _build_categories(payload)
    theme = _determine_theme(payload)

    variants = payload.get("variants", [])
    items = []

    for variant in variants:
        variant_title = variant.get("title", "")
        # Append variant name unless it's the Shopify default "Default Title".
        if variant_title and variant_title != "Default Title":
            name = f"{product_title} - {variant_title}"
        else:
            name = product_title

        barcode = _get_variant_barcode(variant)
        images = _get_variant_images(variant, product_images)

        item = {
            "name": name,
            "description": description,
            "retailerProductId": product_id,
            "barcodes": [barcode] if barcode else [],
            "images": images,
            "stockLevel": variant.get("inventory_quantity", 0),
            "basePrice": str(variant.get("price", "0")),
            "categories": categories,
            "theme": theme,
        }

        # Variant-specific fields from options.
        size = _extract_option_value(variant, payload, "Size")
        if size:
            item["size"] = size

        colour = (
            _extract_option_value(variant, payload, "Color")
            or _extract_option_value(variant, payload, "Colour")
        )
        if colour:
            item["colour"] = colour

        # Optional: pricingGuidance (only when tax_mapping configured).
        pricing_guidance = _build_pricing_guidance(variant, config)
        if pricing_guidance:
            item["pricingGuidance"] = pricing_guidance

        # Optional: buyingGuidance (only when configured).
        buying_guidance = config.extra_data.get("buying_guidance")
        if buying_guidance:
            item["buyingGuidance"] = buying_guidance

        items.append(item)

    return items


def send_to_inventory_service(items, store_id, retailer_id):
    """Send mapped items to the Inventory Service with upsert semantics.

    Args:
        items: List of inventory item dicts from map_shopify_product_to_inventory().
        store_id: Store UUID string.
        retailer_id: Retailer UUID string.
    """
    if not items:
        return

    categories = items[0].get("categories", []) if items else []

    client = InventoryV1Client(settings.INVENTORY_SERVICE_URL)
    payload = {
        "storeId": store_id,
        "retailerId": retailer_id,
        "categories": categories,
        "items": [
            {"operation": "upsert", **item}
            for item in items
        ],
    }
    client.update_inventory(payload)
    logger.info(
        "Sent %d items to Inventory Service (store=%s)", len(items), store_id
    )
