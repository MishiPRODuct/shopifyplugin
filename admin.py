from django.contrib import admin

from .models import ShopifyWebhookConfig, WebhookEvent


@admin.register(ShopifyWebhookConfig)
class ShopifyWebhookConfigAdmin(admin.ModelAdmin):
    list_display = (
        "store",
        "shopify_domain",
        "sync_inventory",
        "sync_promotions",
        "sync_orders_to_shopify",
        "is_active",
        "api_version",
        "updated_at",
    )
    list_filter = (
        "is_active",
        "sync_inventory",
        "sync_promotions",
        "sync_orders_to_shopify",
    )
    search_fields = (
        "shopify_domain",
        "store__store_id",
    )
    raw_id_fields = ("store",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = (
        "webhook_id",
        "topic",
        "shop_domain",
        "status",
        "processing_time_ms",
        "created_at",
    )
    list_filter = (
        "status",
        "topic",
    )
    search_fields = (
        "webhook_id",
        "shop_domain",
    )
    raw_id_fields = ("store",)
    readonly_fields = ("payload_hash", "processing_time_ms")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
