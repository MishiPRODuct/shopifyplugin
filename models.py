from django.db import models


class ShopifyWebhookConfig(models.Model):
    """Per-tenant Shopify connection configuration. One record per store."""

    store = models.OneToOneField("dos.Store", on_delete=models.CASCADE)
    retailer_id = models.UUIDField()
    shopify_domain = models.CharField(max_length=255)
    api_access_token = models.TextField()
    webhook_secret = models.CharField(max_length=255)
    api_version = models.CharField(max_length=10, default="2024-07")
    sync_inventory = models.BooleanField(default=True)
    sync_promotions = models.BooleanField(default=True)
    sync_orders_to_shopify = models.BooleanField(default=True)
    extra_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "shopify_webhook_config"

    def __str__(self):
        return f"{self.shopify_domain} (store={self.store_id})"


class WebhookEvent(models.Model):
    """Audit log for idempotency and debugging. Every webhook received is recorded."""

    class Status(models.TextChoices):
        RECEIVED = "received"
        PROCESSING = "processing"
        SUCCESS = "success"
        FAILED = "failed"
        DUPLICATE = "duplicate"

    webhook_id = models.CharField(max_length=255, db_index=True)
    topic = models.CharField(max_length=100)
    shop_domain = models.CharField(max_length=255, db_index=True)
    store = models.ForeignKey("dos.Store", on_delete=models.SET_NULL, null=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.RECEIVED
    )
    payload_hash = models.CharField(max_length=64)
    error_message = models.TextField(blank=True, default="")
    processing_time_ms = models.IntegerField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "shopify_webhook_event"
        indexes = [
            models.Index(fields=["webhook_id"]),
            models.Index(fields=["shop_domain", "topic", "created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["webhook_id"], name="unique_webhook_id"
            ),
        ]

    def __str__(self):
        return f"{self.topic} [{self.status}] ({self.webhook_id})"
