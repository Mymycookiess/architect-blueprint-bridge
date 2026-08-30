
# Architect Blueprint — Shopify Front Door V1

## What this does

A real customer can now enter birth details directly on the Shopify Blueprint product page.

After the customer pays:

1. Shopify sends an `orders/paid` webhook.
2. The bridge verifies the Shopify HMAC signature.
3. It finds the Blueprint line item.
4. It extracts the saved line-item properties.
5. It creates `customer_intake.json`.
6. Birth location is resolved to latitude / longitude / timezone.
7. The bundled Blueprint Engine runs automatically.
8. The final report is released only if `00_manifest.json` says `PASS`.
9. A passing PDF is uploaded to private Cloudflare R2 storage and delivered by
   email through a time-limited signed download link.

## Customer delivery configuration

Successful delivery requires a private Cloudflare R2 bucket and a verified
Resend sending domain/address. Configure these Render environment variables:

- `R2_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET_NAME`
- `R2_ENDPOINT_URL` (optional; defaults to the account R2 S3 endpoint)
- `BLUEPRINT_DOWNLOAD_TTL_SECONDS` (optional; defaults to `604800`, seven days)
- `RESEND_API_KEY`
- `BLUEPRINT_FROM_EMAIL`

The R2 bucket remains private. Signed URLs are created only for delivery and
are not persisted. Delivery state is stored as `delivery.json` in each run
directory, independently from the Blueprint generation status.

After Resend accepts the delivery email, the bridge can automatically fulfill
only the delivered Blueprint line item in Shopify. This requires a Shopify
Admin API token with `read_merchant_managed_fulfillment_orders` and
`write_merchant_managed_fulfillment_orders` access. Configure:

- `SHOPIFY_SHOP_DOMAIN` (the bare `store-name.myshopify.com` domain)
- `SHOPIFY_ADMIN_ACCESS_TOKEN`
- `SHOPIFY_API_VERSION` (optional; defaults to `2026-07`)

The fulfillment is created with `notifyCustomer: false` because the customer
already receives the branded Blueprint delivery email. Mixed orders are safe:
the bridge fulfills only the line item whose PDF was delivered.

## Why this approach

Shopify supports custom line-item properties inside the product form. That ties each customer's birth details to the exact purchased line item.

The trigger is `orders/paid`, not merely add-to-cart or order-created, so the Blueprint does not start before successful payment.

## What still requires a one-time setup outside this package

### 1. Shopify theme
Install `shopify_theme/architect-blueprint-intake.liquid` inside the Blueprint product form.

### 2. Shopify app / webhook
Create or use a Shopify app that subscribes to `orders/paid` and points to:

`https://YOUR-BRIDGE-DOMAIN/webhooks/shopify/orders-paid`

Shopify signs webhooks. Set the same app secret as `SHOPIFY_WEBHOOK_SECRET`.

### 3. Host the bridge
The bridge is a FastAPI service and includes a Dockerfile. It needs a public HTTPS URL.

### 4. Resolve the typed birth location
The customer should type a human-readable location, not latitude/longitude.

Set `LOCATION_RESOLVER_URL` to a small resolver service that returns:
- latitude
- longitude
- the correct UTC offset for the customer's birth date/time

If this resolver is not configured, the order is safely parked in:
`WAITING_FOR_LOCATION_RESOLUTION`
instead of guessing coordinates or timezone.

### 5. AstrologyAPI credentials
Configure:
- ASTROLOGYAPI_BASE_URL
- ASTROLOGYAPI_USER_ID
- ASTROLOGYAPI_KEY

## Run states

A paid Blueprint order moves through:

`PAID_ORDER_RECEIVED`
→ `WAITING_FOR_LOCATION_RESOLUTION` (only when needed)
→ `RUNNING_BLUEPRINT_ENGINE`
→ `BLUEPRINT_READY`

or:

`REVIEW_REQUIRED`
`ENGINE_ERROR`
`FRONTDOOR_ERROR`

## Duplicate protection

Each order line gets its own production-run folder. Once the run has a
`frontdoor_completed.flag`, duplicate webhook deliveries do not regenerate the report.

## FULL vs PARTIAL

The customer explicitly selects whether the exact birth time is known.

- KNOWN → FULL Blueprint
- UNKNOWN → PARTIAL Blueprint
- PARTIAL never receives Rising or house interpretations.

## Recommended launch sequence

1. Install intake on a duplicated/unpublished Shopify theme.
2. Create one test product/order.
3. Confirm line-item properties appear in Shopify Admin.
4. Deploy the bridge.
5. Send a test `orders/paid` webhook.
6. Confirm `customer_intake.json` is correct.
7. Configure location resolution + AstrologyAPI.
8. Run one paid sandbox/test order from end to end.
9. Only then publish the theme.
