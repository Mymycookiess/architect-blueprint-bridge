# Render deploy settings

The repository root is ready for Render Docker deployment.

Health endpoint: `/health`
Shopify paid-order webhook: `/webhooks/shopify/orders-paid`

Set these environment variables in Render (do NOT commit secrets):
- SHOPIFY_WEBHOOK_SECRET
- SHOPIFY_SHOP_DOMAIN
- SHOPIFY_ADMIN_ACCESS_TOKEN
- SHOPIFY_API_VERSION (optional; defaults to 2026-07)
- BLUEPRINT_PRODUCT_HANDLES=the-architect-blueprint
- LOCATION_RESOLVER_URL (can be blank during bridge-only testing)
- ASTROLOGYAPI_BASE_URL
- ASTROLOGYAPI_USER_ID
- ASTROLOGYAPI_KEY
- ARCHITECT_AI_TOKEN (optional)

`BLUEPRINT_OUTPUT_ROOT` defaults to `/app/production_runs` in the Dockerfile.
