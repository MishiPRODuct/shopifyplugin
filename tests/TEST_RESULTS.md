# Shopify Webhooks Test Results

**Date:** 2026-02-02
**Environment:** Standalone (no Docker / no full Django env)

## Compilation Check: 29/29 files pass

All Python files in `shopify_webhooks/` compile without syntax errors.

## Test Execution: 101/101 tests pass

| Test Suite | File | Tests | Status |
|---|---|---|---|
| HMAC Verification | test_hmac.py | 8 | All pass |
| Inventory Sync | test_inventory_sync.py | 39 | All pass |
| Promotion Sync | test_promotion_sync.py | 52 | All pass |
| Utils | utils.py | 2 | All pass |

### HMAC Verification (8 tests)
- valid_signature
- tampered_payload_rejected
- empty_hmac_header_rejected
- wrong_secret_rejected
- empty_body
- garbage_hmac_rejected
- unicode_payload
- large_payload

### Inventory Sync (39 tests)
- strip_html: tags, empty, None, plain, nested
- barcode: present, fallback_to_sku, None_fallback_to_sku, fallback_to_id, all_empty_to_id, no_fields
- images: variant_specific, fallback_to_first, no_images, multiple, empty_src_skipped
- mapping: multi_variant_creates_two, variant_names, single_default_title, html_stripped, retailer_product_id, barcodes, base_price, stock_level, per_variant_images, categories, size_from_options, colour_extracted, theme_invariant, theme_from_option, inactive_product, no_variants
- pricing: no_tax_mapping, tax_inclusive, tax_exclusive
- buying: no_buying_guidance, buying_guidance
- barcode edge: empty_falls_back, sku_null

### Promotion Sync (52 tests)
- extract_id: product, variant, collection, discount
- priority: percent_10, percent_50, percent_100, value_off, zero_value
- family: entitled=easy, all=basket, shipping=None, empty=None, unknown=None
- settings: builds_correct_urls
- groups: single_with_nodes, custom_qty_min, skips_empty_skus, empty_list
- resolve: products, variants, collections, raises_on_empty
- easy: percentage_discount, fixed_amount, once_per_customer, allocation_each, allocation_across, groups_from_resolved_skus, unknown_raises, retailer_from_extra_data
- basket: basic_threshold, single_group_all_node, prerequisite_subtotal, no_subtotal_defaults_1, fixed_amount, missing_title_raises, once_per_customer
- bxgy: two_group_structure, requisite_group_nodes, target_group_nodes, 100_percent_off, percentage_type, amount_type, unknown_type_raises, promo_fields
- extract_min: percentage, on_quantity, quantity, amount, unknown, empty

## Tests Not Run (require full Django ORM)

These test files require the full Docker-based development environment:

| File | Reason |
|---|---|
| test_models.py | Django ORM (model creation, uniqueness constraints) |
| test_views.py | DRF APIClient, HTTP POST with HMAC, DB records |
| test_handlers.py | StoreFactory, ShopifyWebhookConfig.objects.create, DB queries |

**Dependencies needed:** PostgreSQL, `inventory-common` (private), `mishipay-python-logger` (private), all 60+ Django apps loaded.

## How to Run

### Standalone tests (no Docker needed)
```bash
python shopify_webhooks/tests/run_standalone_tests.py
```

### Full test suite (requires Docker environment)
```bash
python manage.py test shopify_webhooks --verbosity=2
# or
pytest shopify_webhooks/tests/ --ds=mainServer.settings -v
```
