"""Generic Shopify order fulfilment using ShopifyWebhookConfig.

Provides a config-driven alternative to the existing
:class:`~mishipay_items.shopify_utility.client.ShopifyPostTransaction` and
:class:`~mishipay_items.shopify_utility.refund_client.ShopifyRefundTransaction`
which load credentials from per-store ``GlobalConfig``.

This module loads Shopify API credentials from
:class:`~shopify_webhooks.models.ShopifyWebhookConfig` instead, making it
work for **any** Shopify-connected store without per-retailer code.

Usage from ``order_fulfilment.py``::

    from shopify_webhooks.services.order_sync import (
        generic_shopify_webhook_order_fulfilment,
    )
"""

import json
import logging

from django.conf import settings

from mishipay_core.common_functions import (
    check_for_discrepancy,
    get_requests_session_client,
    send_slack_message,
)
from mishipay_items.models import BasketEntityAuditLog
from mishipay_items.shopify_utility.client import (
    ShopifyPostTransaction,
    _generate_payload_data,
)
from mishipay_items.shopify_utility.refund_client import (
    ShopifyRefundTransaction,
    _generate_calculate_refund_payload_data,
    _generate_create_refund_payload_data,
)

from ..models import ShopifyWebhookConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_shopify_endpoints(config):
    """Build Shopify Admin REST API endpoint URLs from a ShopifyWebhookConfig.

    The returned dict uses the same key names as the existing
    ``post_transaction_settings`` dict in ``GlobalConfig`` so that
    inherited methods on :class:`ShopifyWebhookPostTransaction` work
    without modification.
    """
    base = f"https://{config.shopify_domain}/admin/api/{config.api_version}"
    return {
        "post_transaction_endpoint": f"{base}/orders.json",
        "inventory_adjust_endpoint": f"{base}/inventory_levels/adjust.json",
        "refund_transaction_calculate_endpoint": f"{base}/orders/order_id/refunds/calculate.json",
        "refund_transaction_endpoint": f"{base}/orders/order_id/refunds.json",
        "get_fulfillment_order_endpoint": f"{base}/orders/{{}}/fulfillment_orders.json",
        "move_fulfillment_order_endpoint": f"{base}/fulfillment_orders/{{}}/move.json",
    }


def _enhance_order_payload(payload_data, order, basket):
    """Enhance a Shopify order payload with MishiPay-specific fields.

    Additions:

    * **note_attributes** — ``mishipay_order_id`` (from ``order.o_id``) and
      ``poslog_transaction_id`` (from ``order.extra_data``).
    * **line item properties** — ``barcode``, ``modified_monetary_value``,
      and ``promo_info`` per line item.

    The base *payload_data* is produced by
    :func:`~mishipay_items.shopify_utility.client._generate_payload_data`.
    """
    order_data = payload_data.get("order", {})

    # --- Order-level note_attributes ---
    note_attributes = [
        {"name": "mishipay_order_id", "value": str(order.o_id)},
    ]
    transaction_id = order.extra_data.get("transaction_id_poslog", "")
    if transaction_id:
        note_attributes.append(
            {"name": "poslog_transaction_id", "value": str(transaction_id)}
        )
    order_data["note_attributes"] = note_attributes

    # --- Per-line-item properties ---
    audit_items = list(
        BasketEntityAuditLog.objects.filter(basket=basket)
    )
    line_items = order_data.get("line_items", [])

    for idx, item_obj in enumerate(audit_items):
        if idx >= len(line_items):
            break
        line_item = line_items[idx]
        properties = line_item.get("properties", [])

        # barcode
        item_info = item_obj.extra_data.get("item_info", {})
        barcodes = item_info.get("barcodes", [])
        barcode = (
            barcodes[0]
            if barcodes
            else item_info.get("barcode", str(item_obj.entity_identifier))
        )
        if barcode:
            properties.append({"name": "barcode", "value": str(barcode)})

        # modified_monetary_value
        if item_obj.modified_monetary_value is not None:
            properties.append(
                {
                    "name": "modified_monetary_value",
                    "value": str(item_obj.modified_monetary_value),
                }
            )

        # promo_info
        promo_info = item_obj.extra_data.get("applied_promos")
        if promo_info:
            properties.append(
                {"name": "promo_info", "value": json.dumps(promo_info)}
            )

        if properties:
            line_item["properties"] = properties

    return payload_data


def parse_shopify_order_response(response_text):
    """Parse a Shopify order creation response into standardised fields.

    Returns:
        dict with keys:
            * ``order_posted`` (bool) — ``True`` if Shopify created the order.
            * ``email_receipt_sent`` (bool) — ``True`` if Shopify confirmed the
              order (confirmation email sent depends on store settings).
            * ``error`` (str) — Error message, empty on success.
            * ``raw`` (dict) — Full parsed JSON body.
    """
    result = {
        "order_posted": False,
        "email_receipt_sent": False,
        "error": "",
        "raw": {},
    }

    try:
        data = (
            json.loads(response_text)
            if isinstance(response_text, str)
            else response_text
        )
        result["raw"] = data
    except (json.JSONDecodeError, TypeError):
        result["error"] = str(response_text)[:2000]
        return result

    if "errors" in data:
        errors = data["errors"]
        result["error"] = (
            json.dumps(errors) if isinstance(errors, dict) else str(errors)
        )
        return result

    if "order" in data:
        result["order_posted"] = True
        order_data = data["order"]
        result["email_receipt_sent"] = order_data.get("confirmed", False)

    return result


# ---------------------------------------------------------------------------
# Transaction classes using ShopifyWebhookConfig
# ---------------------------------------------------------------------------

class ShopifyWebhookPostTransaction(ShopifyPostTransaction):
    """Post-transaction client that reads credentials from ShopifyWebhookConfig.

    Overrides :meth:`__init__` to avoid GlobalConfig and
    :meth:`create_order` to inject the enhanced payload fields.

    All other inherited methods (``send``, ``adjust_inventory``,
    ``get_fulfillment_order_ids_to_move``, ``move_fulfillment_orders``)
    work unchanged because they reference ``self.access_token`` and
    ``self.post_transaction_settings`` which are set from
    ShopifyWebhookConfig.
    """

    def __init__(self, order):
        # Intentionally bypass super().__init__() — we load credentials
        # from ShopifyWebhookConfig instead of GlobalConfig.
        self.order = order
        self.basket = order.basket
        self.store = order.store

        config = ShopifyWebhookConfig.objects.get(store=self.store)
        self.access_token = config.api_access_token
        self.post_transaction_settings = _build_shopify_endpoints(config)
        self.inventory_settings = {"access_token": config.api_access_token}

    def create_order(self, client, extra_data, phone_number=True):
        """Create order with enhanced payload (barcode, note_attributes, etc.)."""
        if extra_data["order_created"]:
            return True

        url = self.post_transaction_settings["post_transaction_endpoint"]
        payload = _generate_payload_data(
            self.order, self.basket, self.store, phone_number
        )
        payload = _enhance_order_payload(payload, self.order, self.basket)

        headers = {
            "X-Shopify-Access-Token": self.access_token,
            "Content-Type": "application/json",
        }

        self.order.extra_data["poslog_req"] = payload
        response = client.post(url, headers=headers, json=payload, timeout=10)

        # Enhanced response parsing.
        parsed = parse_shopify_order_response(response.text)
        self.order.extra_data["order_posted"] = parsed["order_posted"]
        self.order.extra_data["email_receipt_sent"] = parsed["email_receipt_sent"]

        self.order.extra_data["poslog_res"] = response.text
        if not response.ok:
            if self.check_for_phone_number_error(response):
                return self.create_order(client, extra_data, False)
            self.order.extra_data["poslog_error"] = (
                parsed["error"] or response.text
            )
            return False

        self.order.extra_data["poslog_res"] = json.loads(response.text)
        self.order.extra_data["order_created"] = True
        return True


class ShopifyWebhookRefundTransaction:
    """Refund transaction client using ShopifyWebhookConfig for credentials.

    Mirrors :class:`~mishipay_items.shopify_utility.refund_client.ShopifyRefundTransaction`
    but reads API credentials from ShopifyWebhookConfig instead of GlobalConfig.
    """

    def __init__(self, order, refund_order):
        self.order = order
        self.refund_order = refund_order

    def send(self):
        """Send refund transaction to Shopify.

        Returns:
            tuple: ``(payload, response_data, ok)``
        """
        basket = self.order.basket
        store = basket.store

        config = ShopifyWebhookConfig.objects.get(store=store)
        endpoints = _build_shopify_endpoints(config)
        access_token = config.api_access_token

        poslog_res_order_id = (
            self.order.extra_data.get("poslog_res", {})
            .get("order", {})
            .get("id", "")
        )

        # Step 1: Calculate refund.
        url = endpoints["refund_transaction_calculate_endpoint"]
        url = url.replace("order_id", str(poslog_res_order_id))
        payload = _generate_calculate_refund_payload_data(
            self.order, self.refund_order, basket, store
        )
        headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
        }

        try:
            client = get_requests_session_client()
            response = client.post(url, headers=headers, json=payload, timeout=10)
            if not response.ok:
                return payload, response.text, False
        except Exception as e:
            logger.error("Shopify webhook refund calculate error - %s", e)
            raise

        refund_response_json = response.json()["refund"]
        refund_line_items = refund_response_json["refund_line_items"]
        transactions = refund_response_json["transactions"]

        # Step 2: Create refund.
        url = endpoints["refund_transaction_endpoint"]
        url = url.replace("order_id", str(poslog_res_order_id))
        payload = _generate_create_refund_payload_data(
            store, refund_line_items, transactions
        )

        try:
            client = get_requests_session_client()
            response = client.post(url, headers=headers, json=payload, timeout=10)
            if not response.ok:
                return payload, response.text, False
        except Exception as e:
            logger.error("Shopify webhook refund create error - %s", e)
            raise

        return payload, response.json(), True


# ---------------------------------------------------------------------------
# Main fulfilment function
# ---------------------------------------------------------------------------

def _get_default_result():
    """Return the default order fulfilment result dict."""
    return {"status": True, "data": {}, "error": ""}


@check_for_discrepancy
def generic_shopify_webhook_order_fulfilment(
    order, refund_order=None, daily_job=False
):
    """Generic Shopify order fulfilment using ShopifyWebhookConfig.

    Drop-in replacement for
    :func:`~mishipay_retail_orders.order_fulfilment.generic_shopify_order_fulfilment`
    that works for **any** store with a :class:`ShopifyWebhookConfig` record.

    Key differences from the original:

    * Credentials loaded from ``ShopifyWebhookConfig`` (not ``GlobalConfig``).
    * Line items enhanced with ``barcode``, ``modified_monetary_value``, and
      ``promo_info`` as line item properties.
    * ``o_id`` and ``transaction_id_poslog`` stored as ``note_attributes``.
    * Response parsed for ``order_posted``, ``email_receipt_sent``, ``error``.

    Args:
        order: :class:`~mishipay_retail_orders.models.Order` instance.
        refund_order: Optional refund order instance.
        daily_job: ``True`` when called from the daily retry job.

    Returns:
        dict: ``{"status": bool, "data": dict, "error": str}``
    """
    result = _get_default_result()
    error = None
    store = order.basket.store

    try:
        if refund_order is None:
            cli = ShopifyWebhookPostTransaction(order)
            cli.send()
            ok = order.extra_data.get("poslog_sent", False)
            order.save()
        else:
            cli = ShopifyWebhookRefundTransaction(order, refund_order)
            req, res, ok = cli.send()
            refund_order.extra_data["poslog_req"] = req
            refund_order.extra_data["poslog_sent"] = ok
            refund_order.extra_data["poslog_res"] = res
            refund_order.save()

        if not ok:
            error = "Shopify Webhook Post Transaction API failure."
    except ShopifyWebhookConfig.DoesNotExist:
        error = (
            f"ShopifyWebhookConfig not found for store {store.store_id}"
        )
    except Exception as e:
        error = "Shopify Webhook Post Transaction Exception: " + str(e)
        try:
            order.save()
        except Exception as save_err:
            error += " | Error while saving order: " + str(save_err)

    if error:
        extra_message = (
            "Daily Job" if daily_job else "Post Transaction order fulfilment"
        )
        err = f"{error}({extra_message}): Order Id {order.order_id}"
        if refund_order is not None:
            err += f" refund_order_id:{refund_order.refund_order_id}"
        result["status"] = False
        result["error"] = err
        header = f"[{settings.ENV_TYPE}]: {store.store_type}: {err}"
        send_slack_message(header, "#alerts_poslog")

    return result
