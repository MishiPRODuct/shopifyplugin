from django.urls import path

from .views import (
    ShopifyInventoryWebhookView,
    ShopifyOrderWebhookView,
    ShopifyPromotionWebhookView,
)

urlpatterns = [
    path(
        "inventory/",
        ShopifyInventoryWebhookView.as_view(),
        name="shopify_inventory_webhook",
    ),
    path(
        "promotions/",
        ShopifyPromotionWebhookView.as_view(),
        name="shopify_promotion_webhook",
    ),
    path(
        "orders/",
        ShopifyOrderWebhookView.as_view(),
        name="shopify_order_webhook",
    ),
]
