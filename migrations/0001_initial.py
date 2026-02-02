# Generated manually for shopify_webhooks app

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("dos", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ShopifyWebhookConfig",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("retailer_id", models.UUIDField()),
                ("shopify_domain", models.CharField(max_length=255)),
                ("api_access_token", models.TextField()),
                ("webhook_secret", models.CharField(max_length=255)),
                (
                    "api_version",
                    models.CharField(default="2024-07", max_length=10),
                ),
                ("sync_inventory", models.BooleanField(default=True)),
                ("sync_promotions", models.BooleanField(default=True)),
                ("sync_orders_to_shopify", models.BooleanField(default=True)),
                ("extra_data", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "store",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="dos.store",
                    ),
                ),
            ],
            options={
                "db_table": "shopify_webhook_config",
            },
        ),
        migrations.CreateModel(
            name="WebhookEvent",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("webhook_id", models.CharField(db_index=True, max_length=255)),
                ("topic", models.CharField(max_length=100)),
                ("shop_domain", models.CharField(db_index=True, max_length=255)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("received", "Received"),
                            ("processing", "Processing"),
                            ("success", "Success"),
                            ("failed", "Failed"),
                            ("duplicate", "Duplicate"),
                        ],
                        default="received",
                        max_length=20,
                    ),
                ),
                ("payload_hash", models.CharField(max_length=64)),
                ("error_message", models.TextField(blank=True, default="")),
                ("processing_time_ms", models.IntegerField(null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "store",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="dos.store",
                    ),
                ),
            ],
            options={
                "db_table": "shopify_webhook_event",
                "indexes": [
                    models.Index(
                        fields=["webhook_id"],
                        name="shopify_web_webhook_idx",
                    ),
                    models.Index(
                        fields=["shop_domain", "topic", "created_at"],
                        name="shopify_web_shop_do_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("webhook_id",),
                        name="unique_webhook_id",
                    ),
                ],
            },
        ),
    ]
