import hashlib
import json
import logging

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .middleware import verify_shopify_hmac
from .models import ShopifyWebhookConfig, WebhookEvent
from .router import INVENTORY_TOPICS, ORDER_TOPICS, PROMOTION_TOPICS
from .tasks import process_shopify_inventory_event, process_shopify_promotion_event

logger = logging.getLogger(__name__)


class BaseShopifyWebhookView(APIView):
    """Base view for all Shopify webhook endpoints.

    Handles HMAC verification, idempotency, and event recording.
    Concrete subclasses define ``allowed_topics`` to validate that
    the incoming topic matches the endpoint category, and
    ``task_actor`` to specify the Dramatiq actor for async processing.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    allowed_topics = frozenset()
    task_actor = None

    def post(self, request):
        # 1. Extract shop domain
        shop_domain = request.META.get("HTTP_X_SHOPIFY_SHOP_DOMAIN")
        if not shop_domain:
            return Response(
                {"error": "Missing X-Shopify-Shop-Domain header"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 2. Look up active config for this shop
        try:
            config = ShopifyWebhookConfig.objects.get(
                shopify_domain=shop_domain, is_active=True
            )
        except ShopifyWebhookConfig.DoesNotExist:
            logger.warning("No active config for domain: %s", shop_domain)
            return Response(
                {"error": "Unknown shop domain"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 3. Verify HMAC signature
        raw_body = request.body
        hmac_header = request.META.get("HTTP_X_SHOPIFY_HMAC_SHA256", "")
        if not verify_shopify_hmac(raw_body, hmac_header, config.webhook_secret):
            logger.warning("HMAC verification failed for %s", shop_domain)
            return Response(
                {"error": "HMAC verification failed"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # 4. Extract topic and webhook ID
        topic = request.META.get("HTTP_X_SHOPIFY_TOPIC", "")
        webhook_id = request.META.get("HTTP_X_SHOPIFY_WEBHOOK_ID", "")

        if not webhook_id:
            return Response(
                {"error": "Missing X-Shopify-Webhook-Id header"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 5. Validate topic matches this endpoint
        if self.allowed_topics and topic not in self.allowed_topics:
            logger.warning(
                "Topic %s not allowed for %s", topic, self.__class__.__name__
            )
            return Response(
                {"error": f"Topic '{topic}' not handled by this endpoint"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 6. Idempotency — reject duplicate webhook deliveries
        if WebhookEvent.objects.filter(webhook_id=webhook_id).exists():
            return Response(status=status.HTTP_200_OK)

        # 7. Record the webhook event
        payload_hash = hashlib.sha256(raw_body).hexdigest()
        event = WebhookEvent.objects.create(
            webhook_id=webhook_id,
            topic=topic,
            shop_domain=shop_domain,
            store=config.store,
            status=WebhookEvent.Status.RECEIVED,
            payload_hash=payload_hash,
        )

        # 8. Enqueue async processing via Dramatiq
        if self.task_actor is not None:
            payload = json.loads(raw_body)
            self.task_actor.send(event.id, payload)

        logger.info(
            "Recorded webhook event: topic=%s, webhook_id=%s, shop=%s",
            topic,
            webhook_id,
            shop_domain,
        )
        return Response(status=status.HTTP_200_OK)


class ShopifyInventoryWebhookView(BaseShopifyWebhookView):
    """Handles products/create, products/update, products/delete,
    and inventory_levels/update topics."""

    allowed_topics = INVENTORY_TOPICS
    task_actor = process_shopify_inventory_event


class ShopifyPromotionWebhookView(BaseShopifyWebhookView):
    """Handles price_rules/create, price_rules/update,
    price_rules/delete, and collections/update topics."""

    allowed_topics = PROMOTION_TOPICS
    task_actor = process_shopify_promotion_event


class ShopifyOrderWebhookView(BaseShopifyWebhookView):
    """Handles orders/create topic."""

    allowed_topics = ORDER_TOPICS
