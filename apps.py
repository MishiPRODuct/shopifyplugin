from django.apps import AppConfig


class ShopifyWebhooksConfig(AppConfig):
    name = "shopify_webhooks"
    verbose_name = "Shopify Webhooks"

    def ready(self):
        # Import handler modules to trigger topic registration in router.
        import shopify_webhooks.handlers.inventory  # noqa: F401
        import shopify_webhooks.handlers.promotions  # noqa: F401
