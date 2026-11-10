# ADR 044 Product Pipeline and the Askbridge status integration

Status: Proposed (engineering, 22 October 2026). Nothing is deployed or configured in production until the owner approves the pull request.

## Context

Vitalos is building products as well as services. The first is Askbridge by Vitalos, an AI customer assistant sold to businesses as a subscription, which runs as its own deployment at `askbridge.vitalos.co.uk` with its own database, sign-in and platform roles. The owner's brief for the Askbridge Superadmin (22 October 2026) asks for an entry point in the Vitalos Main Admin: Product Pipeline → Askbridge → Open Superadmin. The Product Pipeline section did not exist ("not there, add it"). The entry must show the product's identity and logo, current environment, operational status from real health data, tenant and active-subscription counts, critical alerts, and an "Open Askbridge Superadmin" action gated by product-specific access. It must not pass long-lived credentials in URLs or show fake numbers.

## Decision

1. **Products are configuration, not data.** `superadmin/apps/products/registry.py` lists each product (key, name, endorsement, summary, logo paths, the names of its settings and its open permission). There is no product table. Adding a product is a code change: a registry entry, its settings and a permission.
2. **Permissions follow the Insights and Careers pattern.** SuperAdmin holds everything. Anyone else needs a role and the Django permission:
   - `products.view_product_pipeline`: see the section (identity, environment, status).
   - `products.open_askbridge_superadmin`: see tenant and subscription counts and alerts, and open the Askbridge Superadmin.
     The permissions hang from an unmanaged model (`ProductAccess`, no table; the migration is a single `CreateModel`). They are granted with `manage.py product_access`, which writes `products.access_granted` and `products.access_revoked` audit events. Views check them on the server; the nav entry and button only follow.
3. **Status is read on the server only.** `GET {ASKBRIDGE_STATUS_URL}` with `Authorization: Bearer {ASKBRIDGE_STATUS_TOKEN}`. The adapter (`client.py`) uses a 3-second overall timeout, reads at most 64 KiB, requires `application/json`, and refuses redirects so the token is never forwarded to another host. Production settings require https. The browser never sees the token or the status URL.
4. **The response is validated strictly** (`status.py`) against this contract:

   ```
   { product: "askbridge", environment: "<lowercase slug>", status: "operational" | "degraded" | "down",
     checkedAt: ISO 8601 with offset, tenants: {total, active, trial, suspended},
     subscriptions: {active, trialing, pastDue}, alerts: [{severity: "critical" | "warning" | "info",
     title, since: ISO 8601 with offset, url: https URL on the product's own host | null}], superadminUrl: https URL }
   ```

   Counts are non-negative integers (booleans and strings are refused), and no tenant breakdown may exceed the total. Times may not be naive or more than 5 minutes in the future. There are at most 100 alerts, and every alert has a `url` key. Alert links must point to the status or superadmin host. Unknown keys are ignored, so the producer can add fields. Any failure makes the whole answer unusable.

5. **Honest states.** No token: "Status not configured", and no request is made. Any failure (timeout, network, non-200, redirect, bad JSON, invalid shape): "Status unavailable" with the time of the last good check if this server has one, and no figures. Good answers are cached for 60 seconds and failures for 30 seconds in the Django cache; the last good snapshot is kept for 7 days.
6. **Open is an audited POST redirect.** `POST /products/askbridge/open/` (CSRF-protected) checks the permission again, writes `products.superadmin_opened` (actor, product, destination), then redirects to `ASKBRIDGE_SUPERADMIN_URL`. Users without the permission get 403; an unknown product gives 404. Nothing is appended to the URL: the Askbridge Superadmin runs its own sign-in and platform roles, so no Django session or token crosses to it. The redirect target comes from settings, never from the status payload. CSP `form-action` also governs the redirect after a form submission, so Product Pipeline pages that show the button add the superadmin's origin to `form-action` (no other page does).

## Options

- **A `Product` model edited in the admin**: rejected for now. One product does not justify a table, an editor and a migration path; the registry is reviewed code.
- **Fetching status in the browser**: rejected. It would expose the token and need a CORS opening on Askbridge.
- **Single sign-on into the Askbridge Superadmin** (signed hand-off token in the URL or a shared identity provider): deferred. The Super Admin uses Django sessions with TOTP and Askbridge uses Supabase Auth; a hand-off token in a URL is the long-lived-credential pattern the brief forbids, and Entra SSO for the Super Admin is still in Phase 2.
- **Signing the status request with HMAC like Relay (ADR-035)**: not chosen. The endpoint is read-only and returns no personal data, so a Bearer token over https with no redirects is enough. Revisit if the payload grows to include customer data.

## Consequences

- One outbound request per product per minute per worker at most (the cache is per process in the default LocMem configuration). A down endpoint costs at most one 3-second wait per 30 seconds per worker on Product Pipeline pages.
- The "last good check" lives in the cache, so a restart or scale-to-zero forgets it and the page says there has been no good check since the server started.
- `ASKBRIDGE_STATUS_TOKEN` must match the token the Askbridge status endpoint accepts. Rotate by accepting both tokens on Askbridge first, then changing the Super Admin secret.
- The Askbridge side must implement `GET /api/platform/v1/status` to this contract. Until then the card shows "Status not configured" (no token) or "Status unavailable".

## Revisit triggers

A second product with different needs; the Super Admin moves to Entra SSO (sign-in continuity into product superadmins); the status payload needs personal or tenant-identifying data; the cache moves to a shared backend.

## Addendum, 10 Nov 2026: Relay, and the legacy site assistant's name

**Relay in the registry.** Owner decision: Relay, Vitalos's social media publishing product (plan content, manage conversations, AI assistant; https://relay.vitalos.co.uk), joins the Product Pipeline under the same contract, with no change to the client, the parser, the cache or the Open flow.

- Key `relay` (`/products/relay/`, `products:detail`/`products:open` with `key="relay"`), name "Relay", endorsement "by Vitalos" (as for Askbridge, Answerd and Pitline), summary "Social media publishing, inbox and AI assistant for teams.", marks `static/products/relay-mark.svg` and `relay-app-icon.svg` (from Relay's official logo files: the mark unchanged, the dark app-icon tile rescaled to the 512 viewBox the other icons use).
- Permission `products.open_relay_superadmin` (migration `0005_product_pipeline_relay`, state only).
- Settings `RELAY_PRODUCT_STATUS_URL` (default `https://relay.vitalos.co.uk/api/platform/v1/status`), `RELAY_PRODUCT_STATUS_TOKEN` (secret `relay-product-status-token`, unset until the owner sets it, so the card shows "Status not configured" and no request is made) and `RELAY_PRODUCT_SUPERADMIN_URL` (default `https://relay.vitalos.co.uk/admin/platform`). The `RELAY_PRODUCT_` prefix keeps them apart from the legacy site assistant's `RELAY_*` settings (`RELAY_API_BASE_URL`, `RELAY_SUPERADMIN_EMAILS`, `RELAY_SUPERADMIN_WEBHOOK_URL` and the rest), which are unchanged.
- Relay serves `GET /api/platform/v1/status` with a Bearer token and `product: "relay"`. Tenants are Relay workspaces; subscriptions are Relay subscriptions.

**"Relay" now means the social product.** The repository's older "Vitalos Relay" (the vitalos.co.uk chat assistant: `packages/relay-core`, `packages/relay-knowledge`, `packages/relay-widget`, `/api/relay/*`, `docs/relay/`, the Super Admin's `apps.relay` hand-over inbox), superseded on the public site by Askbridge (ADR-045), is labelled **"Site assistant (legacy)"** in the Super Admin: the navigation entry, the section heading and page titles, the bell, toasts, alert titles and emails, audit summaries and form labels ("the site assistant" in sentences, "the AI" where the copy meant Relay's AI). Nothing else is renamed: package names, routes (`/relay/...`, `/api/relay/*`), URL names, settings names (`RELAY_*`), permissions, database tables, stored data (including audit summaries already written) and the `RELAY_EMAIL_FROM` value stay as they are, so nothing breaks. The public widget, its system prompt and the website's legal pages still call the legacy assistant "Relay"; changing visitor-facing or legal wording is left to the owner.
