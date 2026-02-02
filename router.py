import logging

logger = logging.getLogger(__name__)

# Topic sets for each webhook view category.
# Used by views to validate that the received topic matches the endpoint.
INVENTORY_TOPICS = frozenset(
    {
        "products/create",
        "products/update",
        "products/delete",
        "inventory_levels/update",
    }
)

PROMOTION_TOPICS = frozenset(
    {
        "price_rules/create",
        "price_rules/update",
        "price_rules/delete",
        "collections/update",
    }
)

ORDER_TOPICS = frozenset(
    {
        "orders/create",
    }
)

# Registry mapping Shopify topic strings to handler callables.
# Handlers are registered by handler modules (inventory.py, promotions.py)
# during Django app ready() or at module import time.
_topic_handlers = {}


def register_handler(topic, handler):
    """Register a handler callable for a Shopify webhook topic."""
    _topic_handlers[topic] = handler
    logger.debug("Registered handler for topic: %s", topic)


def get_handler(topic):
    """Return the handler callable for the given topic, or None."""
    return _topic_handlers.get(topic)
