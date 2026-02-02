import logging
import time

import dramatiq
from datadog import statsd
from requests.exceptions import ConnectionError, Timeout

from .models import WebhookEvent
from .router import get_handler

logger = logging.getLogger(__name__)

SHOPIFY_WEBHOOK_QUEUE = "shopify_webhooks"


def should_retry(retries_so_far, exception):
    """Return True for transient errors, False for permanent ones.

    Transient (retry): ConnectionError, Timeout, HTTP 5xx, HTTP 429.
    Permanent (fail):  ValueError, KeyError, HTTP 4xx (except 429), etc.
    """
    if isinstance(exception, (ConnectionError, Timeout, OSError)):
        return True
    if hasattr(exception, "response") and exception.response is not None:
        status_code = exception.response.status_code
        if status_code == 429 or 500 <= status_code < 600:
            return True
    return False


def _process_event(webhook_event_id, payload):
    """Common processing logic for webhook events.

    Loads the WebhookEvent, transitions it to processing, calls the
    registered handler, and records the outcome with elapsed time.
    """
    try:
        event = WebhookEvent.objects.get(id=webhook_event_id)
    except WebhookEvent.DoesNotExist:
        logger.error("WebhookEvent %s not found", webhook_event_id)
        return

    event.status = WebhookEvent.Status.PROCESSING
    event.save(update_fields=["status", "updated_at"])

    tags = [f"topic:{event.topic}", f"shop_domain:{event.shop_domain}"]
    statsd.increment("shopify.webhook.received", tags=tags)

    start = time.monotonic()
    try:
        handler = get_handler(event.topic)
        if handler is None:
            logger.warning("No handler registered for topic: %s", event.topic)
            event.status = WebhookEvent.Status.FAILED
            event.error_message = f"No handler for topic: {event.topic}"
        else:
            handler(event, payload)
            event.status = WebhookEvent.Status.SUCCESS
    except Exception as exc:
        event.status = WebhookEvent.Status.FAILED
        event.error_message = str(exc)[:2000]
        logger.exception(
            "Failed to process webhook event %s (topic=%s)",
            webhook_event_id,
            event.topic,
        )
        raise
    finally:
        event.processing_time_ms = int((time.monotonic() - start) * 1000)
        event.save(
            update_fields=[
                "status",
                "error_message",
                "processing_time_ms",
                "updated_at",
            ]
        )
        result_tags = tags + [f"status:{event.status}"]
        if event.status == WebhookEvent.Status.SUCCESS:
            statsd.increment("shopify.webhook.processed", tags=result_tags)
        elif event.status == WebhookEvent.Status.FAILED:
            statsd.increment("shopify.webhook.failed", tags=result_tags)
        statsd.histogram(
            "shopify.webhook.processing_time_ms",
            event.processing_time_ms,
            tags=result_tags,
        )


@dramatiq.actor(
    queue_name=SHOPIFY_WEBHOOK_QUEUE,
    max_retries=5,
    min_backoff=30_000,
    max_backoff=600_000,
    retry_when=should_retry,
)
def process_shopify_inventory_event(webhook_event_id, payload):
    """Process an inventory webhook event asynchronously."""
    _process_event(webhook_event_id, payload)


@dramatiq.actor(
    queue_name=SHOPIFY_WEBHOOK_QUEUE,
    max_retries=5,
    min_backoff=30_000,
    max_backoff=600_000,
    retry_when=should_retry,
)
def process_shopify_promotion_event(webhook_event_id, payload):
    """Process a promotion webhook event asynchronously."""
    _process_event(webhook_event_id, payload)
