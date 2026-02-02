# Shopify Webhooks Plugin — Developer Handoff

## What This Is

A new Django app `shopify_webhooks` that adds **webhook-driven real-time sync** for inventory, promotions, and orders between Shopify stores and MishiPay. It layers on top of the existing batch import commands — it does not replace them.

**Architecture flow:**
```
Shopify store event
  → POST to /webhooks/shopify/{inventory|promotions|orders}/
  → HMAC signature verification (per-store secret)
  → Idempotency check (unique webhook_id)
  → WebhookEvent audit record created
  → 202 Accepted returned to Shopify (< 5 seconds)
  → Dramatiq async task dispatched
  → Handler resolves ShopifyWebhookConfig for the store
  → Service layer maps Shopify → MishiPay format
  → Calls Inventory Service / Promotions Service / Shopify Order API
```

---

## New Files Created

All files are in `mainServer/shopify_webhooks/`. Total: **29 Python files** across 6 directories.

### Core App

| File | Purpose |
|------|---------|
| `models.py` | `ShopifyWebhookConfig` (per-store config) and `WebhookEvent` (audit log) |
| `views.py` | 3 DRF views — inventory, promotions, orders. HMAC verification + idempotency |
| `middleware.py` | `verify_shopify_hmac()` — HMAC-SHA256 signature verification |
| `router.py` | Topic-to-handler dispatch map (e.g. `products/create` → `handle_product_create`) |
| `tasks.py` | Dramatiq async tasks: `process_shopify_inventory_event`, `process_shopify_promotion_event` |
| `urls.py` | 3 endpoints under `webhooks/shopify/` |
| `utils.py` | `to_shopify_gid()` helper for GID conversion |
| `admin.py` | Django admin registration for both models |
| `apps.py` | `ShopifyWebhooksConfig` app config |

### Handlers

| File | Purpose |
|------|---------|
| `handlers/inventory.py` | `handle_product_create`, `handle_product_update`, `handle_product_delete`, `handle_inventory_level_update` + variant cache helpers |
| `handlers/promotions.py` | `handle_price_rule_create`, `handle_price_rule_update`, `handle_price_rule_delete`, `handle_collection_update` |

### Services (business logic)

| File | Purpose |
|------|---------|
| `services/inventory_sync.py` | Maps Shopify product → Inventory Service items. Handles barcodes, variants, images, pricing/buying guidance, categories, themes |
| `services/promotion_sync.py` | Maps Shopify price rules → MishiPay promotions. Contains all 3 family builders (Easy, Basket Threshold, BXGY) + SKU resolution + shared parsing from existing `shopify_promotion_import.py` |
| `services/order_sync.py` | `generic_shopify_webhook_order_fulfilment()` — posts MishiPay orders to Shopify using existing `ShopifyPostTransaction` |

### Management Commands

| File | Purpose |
|------|---------|
| `management/commands/register_shopify_webhooks.py` | CLI command to register/update webhook subscriptions via Shopify Admin API |

### Migration

| File | Purpose |
|------|---------|
| `migrations/0001_initial.py` | Creates `shopify_webhook_config` and `shopify_webhook_event` tables |

### Tests

| File | Tests | Needs Django ORM |
|------|-------|------------------|
| `tests/test_hmac.py` | 8 tests — HMAC signature verification | No |
| `tests/test_inventory_sync.py` | 39 tests — field mapping, barcodes, images, pricing, themes | No |
| `tests/test_promotion_sync.py` | 52 tests — all 3 family builders, SKU resolution, priority | No |
| `tests/test_models.py` | Model creation, uniqueness, idempotency | **Yes** |
| `tests/test_views.py` | HTTP endpoints, HMAC rejection, 202 response | **Yes** |
| `tests/test_handlers.py` | Handler dispatch, caching, promo CRUD | **Yes** |
| `tests/run_standalone_tests.py` | Standalone runner for tests that don't need Django ORM (101 tests) | No |

---

## Changes to Existing Files

### 1. `mainServer/settings.py`

**What changed:** Added `'shopify_webhooks'` to `INSTALLED_APPS` (end of list, before closing bracket).

```python
INSTALLED_APPS = [
    ...
    'ddf_price_activation',
    'shopify_webhooks',       # ← NEW
]
```

### 2. `mainServer/urls.py`

**What changed:** Added URL route for webhook endpoints.

```python
urlpatterns = [
    ...
    path("mishipay-config/", include("mishipay_config.urls")),
    path("webhooks/shopify/", include("shopify_webhooks.urls")),  # ← NEW
    ...
]
```

**Resulting endpoints:**
| URL | View | Shopify Topics Handled |
|-----|------|----------------------|
| `POST /webhooks/shopify/inventory/` | `ShopifyInventoryWebhookView` | `products/create`, `products/update`, `products/delete`, `inventory_levels/update` |
| `POST /webhooks/shopify/promotions/` | `ShopifyPromotionWebhookView` | `price_rules/create`, `price_rules/update`, `price_rules/delete`, `collections/update` |
| `POST /webhooks/shopify/orders/` | `ShopifyOrderWebhookView` | Order events (Phase 2) |

### 3. `mishipay_retail_orders/order_fulfilment.py`

**What changed:** Added import of `generic_shopify_webhook_order_fulfilment` from `shopify_webhooks.services.order_sync` (re-exported so `app_settings.py` can reference it).

```python
from shopify_webhooks.services.order_sync import (  # noqa: F401
    generic_shopify_webhook_order_fulfilment,
)
```

Also contains the existing `generic_shopify_order_fulfilment` function at ~line 1337 which uses `ShopifyPostTransaction` directly. The new webhook version in `order_sync.py` wraps this with config lookup.

### 4. `mishipay_retail_orders/app_settings.py`

**What changed (3 areas):**

**a) New import:**
```python
from shopify_webhooks.services.order_sync import (
    generic_shopify_webhook_order_fulfilment,
)
```

**b) New store type entries in `ORDER_FULFILMENT_FUNCTION_MAP`:**
```python
'evokesstoretype': (generic_shopify_order_fulfilment,),
'eighteendegreesstoretype': (generic_shopify_order_fulfilment,),
```

**c) Dynamic fallback in `get_order_fulfilment_functions()`:**
If a store type is not in the static map, it now checks for a `ShopifyWebhookConfig` with `sync_orders_to_shopify=True` and dynamically returns the webhook order fulfilment function. This means **any new Shopify store** can get order sync without adding a new store type entry.

```python
def get_order_fulfilment_functions(store):
    functions = ORDER_FULFILMENT_FUNCTION_MAP.get(store.store_type, None)
    if functions is not None:
        return functions

    # Dynamic fallback: check for ShopifyWebhookConfig
    try:
        from shopify_webhooks.models import ShopifyWebhookConfig
        config = ShopifyWebhookConfig.objects.get(
            store=store, is_active=True, sync_orders_to_shopify=True
        )
        if config:
            return (generic_shopify_webhook_order_fulfilment,)
    except Exception:
        pass

    return ()
```

---

## Database Changes

Run the migration after deployment:

```bash
python manage.py migrate shopify_webhooks
```

This creates two tables:

**`shopify_webhook_config`** — One row per Shopify-connected store.

| Column | Type | Notes |
|--------|------|-------|
| `id` | auto PK | |
| `store_id` | FK → `dos.Store` | OneToOne, CASCADE |
| `retailer_id` | UUID | MishiPay retailer UUID |
| `shopify_domain` | varchar(255) | e.g. `my-shop.myshopify.com` |
| `api_access_token` | text | Shopify Admin API token |
| `webhook_secret` | varchar(255) | HMAC signing secret (per-store) |
| `api_version` | varchar(10) | Default `2024-07` |
| `sync_inventory` | bool | Default `True` |
| `sync_promotions` | bool | Default `True` |
| `sync_orders_to_shopify` | bool | Default `True` |
| `extra_data` | JSON | Tax mapping, buying guidance, promo_retailer, etc. |
| `is_active` | bool | Default `True` |
| `created_at` | datetime | Auto |
| `updated_at` | datetime | Auto |

**`shopify_webhook_event`** — Audit log. Every webhook received gets a row.

| Column | Type | Notes |
|--------|------|-------|
| `id` | auto PK | |
| `webhook_id` | varchar(255) | Shopify's `X-Shopify-Webhook-Id` header. **Unique constraint** for idempotency |
| `topic` | varchar(100) | e.g. `products/create` |
| `shop_domain` | varchar(255) | |
| `store_id` | FK → `dos.Store` | Nullable, SET_NULL |
| `status` | varchar(20) | `received` → `processing` → `success` / `failed` / `duplicate` |
| `payload_hash` | varchar(64) | SHA-256 of payload body |
| `error_message` | text | Empty unless failed |
| `processing_time_ms` | int | Nullable |
| `created_at` | datetime | Auto |
| `updated_at` | datetime | Auto |

Indexes on `webhook_id` and composite `(shop_domain, topic, created_at)`.

---

## Configuration — How to Onboard a New Store

1. **Create a Shopify custom app** in the store's admin panel and get:
   - Admin API access token
   - Webhook signing secret

2. **Create a `ShopifyWebhookConfig` record** (via Django admin or shell):
   ```python
   from shopify_webhooks.models import ShopifyWebhookConfig
   from dos.models import Store

   store = Store.objects.get(store_id="<uuid>")
   ShopifyWebhookConfig.objects.create(
       store=store,
       retailer_id="<retailer-uuid>",
       shopify_domain="my-shop.myshopify.com",
       api_access_token="shpat_...",
       webhook_secret="whsec_...",
       extra_data={
           # Optional: tax config for pricingGuidance
           "tax_mapping": {
               "tax_code": "VAT20",
               "vat_percentage": 20,
               "tax_inclusive": True,
           },
           # Optional: for age-gated products
           "buying_guidance": {
               "restrictedItem": True,
               "ageRestriction": 18,
           },
           # Optional: promo retailer name
           "promo_retailer": "EVOKES-AU",
       }
   )
   ```

3. **Register webhooks with Shopify:**
   ```bash
   python manage.py register_shopify_webhooks \
       --domain my-shop.myshopify.com \
       --topics products/create products/update products/delete inventory_levels/update \
               price_rules/create price_rules/update price_rules/delete collections/update
   ```

---

## Running Tests

### Without Docker (101 tests — business logic only)

```bash
cd mainServer
python shopify_webhooks/tests/run_standalone_tests.py
```

This runs all HMAC, inventory sync, and promotion sync tests using stubbed dependencies. No database, no Docker, no private packages needed.

### With Full Environment (all 6 test files)

```bash
# Via pytest (recommended)
pytest shopify_webhooks/tests/ --ds=mainServer.settings -v

# Via Django test runner
python manage.py test shopify_webhooks --verbosity=2
```

Requires: PostgreSQL, all pip dependencies (including private `inventory-common` and `mishipay-python-logger`), the full Django settings.

---

## Things to Verify Before Going Live

### Code Review Checklist

- [ ] **HMAC verification** — `middleware.py` uses `hmac.compare_digest()` for constant-time comparison. Confirm the `X-Shopify-Hmac-Sha256` header name matches your Shopify app version.

- [ ] **Idempotency** — `WebhookEvent.webhook_id` has a unique constraint. Duplicate webhooks get a 200 response and are skipped. Verify Shopify sends the `X-Shopify-Webhook-Id` header.

- [ ] **Dramatiq broker** — `tasks.py` uses `@dramatiq.actor`. Ensure your Dramatiq broker (Redis/RabbitMQ) is configured in settings and workers are running.

- [ ] **Inventory Service URL** — `services/inventory_sync.py` reads `settings.INVENTORY_SERVICE_URL`. Confirm this setting exists in your environment.

- [ ] **Theme values** — `_determine_theme()` in `inventory_sync.py` returns `"invariant"` or the Shopify option name (e.g. `"Size"`). The `inventory-common` library defines a `Theme` enum with values `INVARIANT`, `COLOUR_SIZE`, `COLOUR_HEX_SIZE`, `ADDON`. Verify the Inventory Service accepts the strings we send, or map them to the enum values.

- [ ] **OperationType strings** — We hardcode `"upsert"` in payloads. The `inventory-common` library has `OperationType.UPSERT`. Confirm the string value matches.

- [ ] **Order sync** — `services/order_sync.py` uses `ShopifyPostTransaction` and `ShopifyRefundTransaction` from `mishipay_items.shopify_utility`. These already exist. Verify the `note_attributes` and line item property format matches what Shopify expects.

- [ ] **Promotion sync** — `services/promotion_sync.py` uses `mishipay_items.mpay_promo.Promotion`, `Group`, `Node`, and `PromotionBatchOperation`. These are the existing promo SDK objects. The mapping logic was extracted from the existing `shopify_promotion_import.py` management command.

- [ ] **Django admin** — `ShopifyWebhookConfig` and `WebhookEvent` are registered in the admin. `WebhookEvent` is read-only (no add/delete permissions).

### Environment Settings Needed

| Setting | Example | Used By |
|---------|---------|---------|
| `INVENTORY_SERVICE_URL` | `http://inventory-service:8081` | `inventory_sync.py` |
| Dramatiq broker config | `DRAMATIQ_BROKER` in settings | `tasks.py` |
| Database | PostgreSQL | models, migrations |

### Shopify App Permissions Required

The Shopify custom app needs these API scopes:
- `read_products`, `write_products`
- `read_inventory`
- `read_price_rules`
- `read_orders`, `write_orders`

---

## Architecture Notes

- **Multi-tenant by design.** Each store has its own `ShopifyWebhookConfig` with its own credentials. No per-retailer code paths.
- **Webhooks layer on top of batch imports.** The existing `general_shopify_import` and `shopify_promotion_import` management commands still work. Webhooks provide real-time updates between batch runs.
- **Delete = zero stock (Phase 1).** Product deletion zeros stock for all variants rather than removing items from the catalog. This is deliberate — the Inventory Service's delete endpoint is a Phase 2 item.
- **Async processing.** Views return 202 within Shopify's 5-second timeout. Actual processing happens in Dramatiq workers.
- **`promotion_sync.py` is the largest file (45KB).** It contains the full promotion mapping logic extracted from the existing 55KB `shopify_promotion_import.py` command, plus new webhook-facing builders. Both the batch command and webhook handler can share this code.
