# Architect Blueprint — Built-in Location Resolver

This package adds a built-in `POST /resolve-location` endpoint to the existing Shopify bridge.

## What it accepts

```json
{
  "birth_location": "Oakland, CA, USA",
  "birth_date": "1996-10-27",
  "birth_time": "02:18"
}
```

`birth_time` may be `null` for unknown-time/PARTIAL mode.

## What it returns

```json
{
  "latitude": 37.8044,
  "longitude": -122.2712,
  "timezone_offset": -8.0,
  "timezone": "America/Los_Angeles"
}
```

The bridge only consumes `latitude`, `longitude`, and `timezone_offset`; the extra fields are diagnostic.

## How it works

1. Geocodes the entered birthplace with Open-Meteo's keyless geocoding service.
2. Uses the returned IANA timezone (for example `America/Los_Angeles`).
3. Calculates the UTC offset for the *birth date/time* using Python's timezone database, including daylight-saving history.
4. Refuses to guess known birth times that fall into ambiguous/nonexistent DST transition periods.
5. Unknown birth time uses local noon only to obtain a deterministic date offset; Rising/houses remain governed by the Blueprint Engine's PARTIAL-mode rules.

## Render setting

After the updated bridge deploys, set this environment variable on the same Render service:

`LOCATION_RESOLVER_URL=https://architect-blueprint-bridge.onrender.com/resolve-location`

Use your actual Render hostname if it differs.

Save the variable and let Render restart/redeploy.

## Free verification

Open:

`https://YOUR-RENDER-SERVICE.onrender.com/health`

Then submit a new paid test order. Render logs will now print a line beginning with `BLUEPRINT_STATUS`, such as:

- `RUNNING_BLUEPRINT_ENGINE`
- `ENGINE_ERROR`
- `BLUEPRINT_READY`
- `WAITING_FOR_LOCATION_RESOLUTION`

This removes the need for paid Render Shell access just to inspect status.

## Important production note

The geocoder is an external dependency. The resolver deliberately stops with an error rather than inventing coordinates or timezone data when a location cannot be resolved safely.
