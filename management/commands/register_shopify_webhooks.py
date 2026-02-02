"""
Register Shopify webhook subscriptions for a store.

Usage:
    docker exec backend_v2 python3 manage.py register_shopify_webhooks \
        --store-id <uuid> --base-url https://api.mishipay.com

    # List current registrations
    docker exec backend_v2 python3 manage.py register_shopify_webhooks \
        --store-id <uuid> --list

    # Remove all webhooks
    docker exec backend_v2 python3 manage.py register_shopify_webhooks \
        --store-id <uuid> --delete-all
"""

import logging

import requests
from django.core.management.base import BaseCommand

from shopify_webhooks.models import ShopifyWebhookConfig
from shopify_webhooks.router import INVENTORY_TOPICS, PROMOTION_TOPICS

logger = logging.getLogger(__name__)

# Map each topic to its callback URL path.
TOPIC_ENDPOINT_MAP = {}
for _topic in INVENTORY_TOPICS:
    TOPIC_ENDPOINT_MAP[_topic] = "/webhooks/shopify/inventory/"
for _topic in PROMOTION_TOPICS:
    TOPIC_ENDPOINT_MAP[_topic] = "/webhooks/shopify/promotions/"

# Ordered list of all topics to register.
WEBHOOK_TOPICS = [
    "products/create",
    "products/update",
    "products/delete",
    "inventory_levels/update",
    "price_rules/create",
    "price_rules/update",
    "price_rules/delete",
    "collections/update",
]


class Command(BaseCommand):
    help = "Register Shopify webhook subscriptions for a store"

    def add_arguments(self, parser):
        parser.add_argument(
            "--store-id",
            type=str,
            required=True,
            help="The store UUID (dos.Store.store_id).",
        )
        parser.add_argument(
            "--base-url",
            type=str,
            default="",
            help="Public base URL for webhook callbacks (e.g. https://api.mishipay.com).",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            dest="list_webhooks",
            help="List currently registered webhooks for this store.",
        )
        parser.add_argument(
            "--delete-all",
            action="store_true",
            help="Delete all registered webhooks for this store.",
        )

    def handle(self, *args, **options):
        store_id = options["store_id"]

        try:
            config = ShopifyWebhookConfig.objects.get(
                store__store_id=store_id, is_active=True
            )
        except ShopifyWebhookConfig.DoesNotExist:
            print(f"ERROR: No active ShopifyWebhookConfig for store_id={store_id}")
            return

        if options["list_webhooks"]:
            self._list_webhooks(config)
            return

        if options["delete_all"]:
            self._delete_all_webhooks(config)
            return

        base_url = options["base_url"]
        if not base_url:
            print("ERROR: --base-url is required when registering webhooks.")
            return

        # Strip trailing slash for clean URL construction.
        base_url = base_url.rstrip("/")

        self._register_webhooks(config, base_url)

    # ------------------------------------------------------------------
    # Shopify Admin API helpers
    # ------------------------------------------------------------------

    def _api_url(self, config, path):
        """Build a Shopify Admin API URL."""
        return (
            f"https://{config.shopify_domain}/admin/api/"
            f"{config.api_version}/{path}"
        )

    def _api_headers(self, config):
        """Return headers for authenticated Shopify Admin API requests."""
        return {
            "X-Shopify-Access-Token": config.api_access_token,
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    def _list_webhooks(self, config):
        """List all webhook subscriptions registered for this store."""
        url = self._api_url(config, "webhooks.json")
        response = requests.get(url, headers=self._api_headers(config), timeout=30)
        if response.status_code != 200:
            print(
                f"ERROR: Failed to list webhooks "
                f"(HTTP {response.status_code}): {response.text}"
            )
            return

        webhooks = response.json().get("webhooks", [])
        if not webhooks:
            print(f"No webhooks registered for {config.shopify_domain}")
            return

        print(f"Webhooks for {config.shopify_domain}:")
        print(f"{'ID':<15} {'Topic':<30} {'Address'}")
        print("-" * 80)
        for wh in webhooks:
            print(f"{wh['id']:<15} {wh['topic']:<30} {wh.get('address', '')}")
        print(f"\nTotal: {len(webhooks)}")

    # ------------------------------------------------------------------
    # Delete all
    # ------------------------------------------------------------------

    def _delete_all_webhooks(self, config):
        """Delete all webhook subscriptions for this store."""
        url = self._api_url(config, "webhooks.json")
        response = requests.get(url, headers=self._api_headers(config), timeout=30)
        if response.status_code != 200:
            print(
                f"ERROR: Failed to list webhooks "
                f"(HTTP {response.status_code}): {response.text}"
            )
            return

        webhooks = response.json().get("webhooks", [])
        if not webhooks:
            print(f"No webhooks to delete for {config.shopify_domain}")
            return

        deleted = 0
        for wh in webhooks:
            wh_id = wh["id"]
            del_url = self._api_url(config, f"webhooks/{wh_id}.json")
            del_resp = requests.delete(
                del_url, headers=self._api_headers(config), timeout=30
            )
            if del_resp.status_code == 200:
                print(f"  Deleted webhook {wh_id} ({wh['topic']})")
                deleted += 1
            else:
                print(
                    f"  FAILED to delete webhook {wh_id} "
                    f"(HTTP {del_resp.status_code}): {del_resp.text}"
                )

        print(f"\nDeleted {deleted}/{len(webhooks)} webhooks")

    # ------------------------------------------------------------------
    # Register
    # ------------------------------------------------------------------

    def _register_webhooks(self, config, base_url):
        """Register all 8 webhook topics, skipping any that already exist."""
        # Fetch existing registrations to make the operation idempotent.
        list_url = self._api_url(config, "webhooks.json")
        list_resp = requests.get(
            list_url, headers=self._api_headers(config), timeout=30
        )
        existing_topics = set()
        if list_resp.status_code == 200:
            for wh in list_resp.json().get("webhooks", []):
                existing_topics.add(wh["topic"])

        created = 0
        skipped = 0
        failed = 0

        for topic in WEBHOOK_TOPICS:
            callback_path = TOPIC_ENDPOINT_MAP.get(topic)
            if callback_path is None:
                print(f"  WARNING: No endpoint mapping for topic '{topic}', skipping")
                failed += 1
                continue

            callback_url = f"{base_url}{callback_path}"

            if topic in existing_topics:
                print(f"  SKIP: {topic} (already registered)")
                skipped += 1
                continue

            payload = {
                "webhook": {
                    "topic": topic,
                    "address": callback_url,
                    "format": "json",
                }
            }

            create_url = self._api_url(config, "webhooks.json")
            resp = requests.post(
                create_url,
                json=payload,
                headers=self._api_headers(config),
                timeout=30,
            )

            if resp.status_code in (200, 201):
                wh_data = resp.json().get("webhook", {})
                print(
                    f"  SUCCESS: {topic} → {callback_url} "
                    f"(id={wh_data.get('id', '?')})"
                )
                created += 1
            elif resp.status_code == 422:
                # Shopify returns 422 when the webhook already exists.
                print(f"  SKIP: {topic} (already exists per Shopify)")
                skipped += 1
            else:
                print(
                    f"  FAILED: {topic} "
                    f"(HTTP {resp.status_code}): {resp.text}"
                )
                failed += 1

        print(
            f"\nDone: {created} created, {skipped} skipped, {failed} failed "
            f"(store={config.store_id}, domain={config.shopify_domain})"
        )
