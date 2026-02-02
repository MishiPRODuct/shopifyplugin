import base64
import hashlib
import hmac


def verify_shopify_hmac(request_body: bytes, hmac_header: str, secret: str) -> bool:
    """Verify the HMAC-SHA256 signature from a Shopify webhook request.

    Shopify sends an X-Shopify-Hmac-Sha256 header containing a Base64-encoded
    HMAC-SHA256 digest of the raw request body, computed using the app's
    webhook secret.

    Args:
        request_body: The raw HTTP request body bytes.
        hmac_header: The value of X-Shopify-Hmac-Sha256 header.
        secret: The webhook secret from ShopifyWebhookConfig.

    Returns:
        True if the signature is valid, False otherwise.
    """
    computed = base64.b64encode(
        hmac.new(secret.encode("utf-8"), request_body, hashlib.sha256).digest()
    ).decode("utf-8")
    return hmac.compare_digest(computed, hmac_header)
