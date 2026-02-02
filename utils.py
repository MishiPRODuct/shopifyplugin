"""Utility helpers for the Shopify webhooks app."""


def to_shopify_gid(resource_type, numeric_id):
    """Convert a numeric Shopify ID to the Global ID (GID) format.

    Shopify's GraphQL API uses GID strings as identifiers. This helper
    converts the numeric IDs returned by the REST API or stored locally
    into the GID format required by GraphQL mutations.

    Args:
        resource_type: Shopify resource name, e.g. ``"Product"``,
            ``"ProductVariant"``, ``"Order"``, ``"Collection"``.
        numeric_id: Numeric ID (int or str).

    Returns:
        str: GID string, e.g. ``"gid://shopify/Product/9154924904679"``.

    Examples::

        >>> to_shopify_gid("Product", "9154924904679")
        'gid://shopify/Product/9154924904679'
        >>> to_shopify_gid("ProductVariant", 50840830771431)
        'gid://shopify/ProductVariant/50840830771431'
    """
    return f"gid://shopify/{resource_type}/{numeric_id}"
