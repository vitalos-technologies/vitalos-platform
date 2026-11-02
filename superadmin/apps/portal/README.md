# apps.portal: the Vitalos client portal

Customers track the challenges they discussed with Vitalos, collaborate on delivery, approve work and see managed
systems. Architecture, visibility model, auth, AI boundaries and retention: [ADR-056](../../../docs/adr/ADR-056-client-portal.md).

## Layout

| File                                       | Role                                                                                                       |
| ------------------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| `models.py`                                | Organisation, Membership, Invitation, Challenge, BriefVersion, Project, Milestone, Deliverable(Version), Approval, ChangeRequest, InformationRequest, Thread/Message, Update, File(Version), ManagedService/ServiceStatusReport, Event, Notification, EmailDelivery |
| `selectors.py`                             | **Every customer read.** Scopes by organisation and publication; foreign or unpublished records are 404.   |
| `services.py`                              | Every write: customer actions (role-checked) and staff actions (explicit publication). Audited.            |
| `access.py`                                | `portal_view` (member resolution, roles, preview), `staff_required`, URL helpers, last-visit tracking.     |
| `middleware.py`                            | `PortalRoutingMiddleware` (PORTAL_HOST) and `CustomerBoundaryMiddleware` (deny-by-default for customers).  |
| `notifications.py`                         | In-app notifications, preferences, email with durable `EmailDelivery`, bounded retries.                    |
| `files.py`                                 | Allow-list, content sniffing, size cap, private storage.                                                   |
| `ai.py`                                    | Six assistant activities: scoped context, deterministic answers, gateway path, validation, replay.         |
| `pwa.py`, `views/pwa.py`                   | Installable app: manifest values, the service worker's precache list and cache version, the three public routes. |
| `push.py`, `views/push.py`                 | Push notifications: keys, endpoint allowlist, RFC 8291 encryption, VAPID, queueing, delivery and retries; the four push routes. |
| `deliveries.py`                            | Staff delivery status: email and push in one list, summary, detail, Retry now, Cancel, capped bulk retry. Never exposes endpoints, keys or payloads. |
| `retention.py`                             | Daily deletion of old delivery records and turned-off devices (content tick; a dry run until `RETENTION_ENFORCE=true`). |
| `staff_selectors.py`                       | Staff-only reads, including `awaiting_decision_versions` (one query; also used by AI & Data › Delivery).   |
| `views/`                                   | `auth.py` (sign-in, invitation, reset, TOTP), `customer.py` (workspace), `staff.py` (Super Admin tools).   |
| `urls.py`, `preview_urls.py`, `admin_urls.py` | Customer routes; the same routes for staff preview; staff routes at `/client-portal/`.                  |
| `management/commands/portal_seed_demo.py`  | Synthetic data for local screenshots. Refuses to run unless DEBUG is on outside production.                |
| `management/commands/portal_send_pending.py` | Bounded retry of queued and failed portal emails and pushes (run from a scheduler).                     |
| `management/commands/portal_delivery_retention.py` | The delivery retention by hand: prints what would be deleted; deletes only with `RETENTION_ENFORCE=true`. |
| `fixtures/ai_replay/`                      | Hand-written, labelled "simulated" assistant answers for local demonstrations.                             |
| `static/portal/`, `templates/portal/`      | Customer UI (own stylesheet using the `--aid-*` token names; no framework). `templates/portaladmin/` is the staff UI. |

Prompts live with the gateway: `apps/aicore/core/prompt_configs/portal_<activity>@1.json`.

## URLs

- Customer, production: `https://portal.vitalos.co.uk/` (only portal URLs are served on that host).
- Customer, local: `http://localhost:8000/portal/` (when `PORTAL_HOST` is empty).
- Staff: `/client-portal/` (organisations, members, challenges, projects, deliverables, updates, questions, files, change requests, services, notification deliveries). "Preview as customer" is on each member row.
- Opportunity workspace: a "Client portal" panel (`templates/aidata/_opportunity_extensions.html`) links an opportunity to an organisation.

## Run it locally

```sh
cd superadmin
DJANGO_SETTINGS_MODULE=config.settings.dev python manage.py migrate
DJANGO_SETTINGS_MODULE=config.settings.dev python manage.py portal_seed_demo --staff-email staff.demo@example.test
# prints the synthetic password; sign in at /portal/sign-in/ as approver@northwind.example.test
```

The seed creates Northwind Synthetic Ltd and Contoso Synthetic plc (flagged synthetic; a banner shows), sends no email, and
refuses to run in production or without `DEBUG`. `--reset` rebuilds only the synthetic data.

## Files: uploading

The entry point is **Upload a file**, at the top right of Files (`templates/portal/files.html`) and in its empty state. It
opens the dialog in `_upload_dialog.html` / `_upload_form.html` and posts to `files/upload/` (`customer.file_upload`,
POST only, CSRF).

- **Fields:** the file, the challenge (`selectors.challenges`: this organisation's shared challenges), an optional
  project (`selectors.projects`, grouped by challenge; `portal.js` hides the other challenges' projects) and an optional
  title. A posted challenge or project id from another organisation is a 404.
- **Before upload:** the accepted types, the size limit and the legacy-type note come from `files.py`
  (`accepted_summary`, `accept_attribute`, `MAX_BYTES`, `LEGACY_NOTE`), so the page cannot promise a type the checks
  refuse. The privacy line says who can see the file.
- **Validation:** unchanged and server-side: `files.check` decides on type, content, size and `.doc`/`.xls`; the form
  allows one file at a time; the service refuses a project from another challenge.
  - A refusal comes back inline in the open dialog: HTMX swaps the form, or without JavaScript the page renders again
    with the dialog open.
  - Success redirects to the file's page with a toast.
- **Who can upload:** `services.customer_upload_refusal` decides, and the button stays visible, disabled, with the
  reason under it:
  - a viewer gets "Your role can view files but not upload them";
  - a member with no shared challenge gets "You can upload once Vitalos shares a challenge with you";
  - staff preview is read-only.
- **Without storage:** the page says file storage is not set up, and an upload is recorded as "Not stored".
- **Staff:** they see the upload on the challenge page and under recent customer activity; it is audited as
  `portal.file_uploaded`.
- **New versions:** a new version of a customer-uploaded file is added from that file's page (`file_id`).

## Account settings

`settings_base.html` gives Account a section menu beside the content (`_settings_nav.html`), sticky on wide screens;
at 52rem or narrower it is a scrollable chip row above the content, and `portal.js` scrolls the current chip into view.
Each section is its own page, so the menu is real links and the view marks the current one with `aria-current="page"`
(`settings_section`).

| Section                      | URL (portal host; `/portal/…` locally) | View                                   |
| ---------------------------- | -------------------------------------- | -------------------------------------- |
| Profile                      | `/account/`                            | `customer.account`                     |
| Sign-in & security           | `/account/security/`                   | `customer.account_security`            |
| (two-step set-up)            | `/account/security/two-step/`          | `auth.otp_setup` (`portal:otp_setup`)  |
| Notifications on this device | `/account/device/`                     | `customer.account_device`              |
| Notification preferences     | `/notifications/preferences/`          | `customer.notification_preferences`    |
| Install the app              | `/account/install/`                    | `customer.account_install`             |

- **Two-step set-up** sits under Sign-in & security (its item stays current) and returns there when it is done or
  cancelled. It moved from `/account/security/`, which is now the section itself, one click from set-up.
- **Push and install hooks** (`data-push…`, `data-install…`) are only on their own pages. A device removed with the
  plain form, and the test notification, return to `/account/device/`.
- **Staff preview:** the device and install items are hidden, and their URLs (and set-up) lead back to the shell.
- **Old links:** the sections used to be anchors on `/account/` (`#profile`, `#device`, …). `/account/` still opens
  Profile, so those links still land in the shell.

## Installable app (Phase 1)

The portal installs as an app from the browser (no app store). The decision and the privacy rule are in [ADR-056, Phase 1](../../../docs/adr/ADR-056-client-portal.md#phase-1-installable-app-29-oct-2026).

| Route                  | Portal host             | Local preview                  | What                                                                      |
| ---------------------- | ----------------------- | ------------------------------ | ------------------------------------------------------------------------- |
| `manifest.webmanifest` | `/manifest.webmanifest` | `/portal/manifest.webmanifest` | Web app manifest (`application/manifest+json`).                           |
| `sw.js`                | `/sw.js`                | `/portal/sw.js`                | Service worker, `no-cache`, rendered from `templates/portal/pwa/sw.js`.   |
| `offline/`             | `/offline/`             | `/portal/offline/`             | Public offline page (`noindex`, no organisation or member data).          |

None of the three exists on the admin host or in staff preview. The worker caches public static files and the offline page only: never a page, a partial, a download or an export. Signing out therefore needs no cache purge.

- **Mobile shell:** `templates/portal/_tabbar.html` (bottom tab bar) and the "Mobile app shell" block in `static/portal/portal.css`. It shows at 52rem or narrower and always in the installed app.
- **Head tags:** `templates/portal/_pwa_head.html`, added by `base.html` and `auth/shell.html` through the `portal_pwa` tag. The tag returns nothing in staff preview, without a request, or when a view passes `pwa_skip`.
- **Install card:** Account › Install the app (`/account/install/`). `portal.js` swaps the manual steps for an Install button, the iOS instruction or "Installed on this device".

### Regenerate the icons

The icons live in `static/portal/icons/` and are made from `apps/web/public/brand/vitalos-symbol-512.png` (the mark is not redrawn). To regenerate them, run this from the repository root and commit the PNGs:

```sh
pnpm install --frozen-lockfile                 # Playwright's Chromium comes with @playwright/test
node tooling/scripts/generate-portal-icons.mjs
```

### Test offline

1. Run the portal locally (above) and sign in at `http://localhost:8000/portal/sign-in/`. Service workers need a secure context. `localhost` and `127.0.0.1` count as one; a LAN address over plain http does not.
2. In DevTools, open Application. Under Service workers, `/portal/sw.js` should be active with scope `/portal/`. The Manifest pane should show the icons and no installability errors. Cache storage should hold only `/static/...` files and `/portal/offline/`.
3. In the Network panel, choose Offline, then open any portal page, including one you visited before. You should get the offline page, never a cached copy of the workspace.
4. Automated checks are in `tests/test_portal_pwa.py`. If the caching rules change but no static file does, bump `SW_REVISION` in `pwa.py`.

### Remove the worker (rollback)

Reverting the change makes `sw.js` answer 404. Browsers then stop updating the worker, but an installed worker keeps
serving the offline page when the network fails. It only ever holds public files, so this is safe, but to remove it
everywhere, deploy a `sw.js` that unregisters itself:
`self.addEventListener("install", () => self.skipWaiting()); self.addEventListener("activate", (e) => e.waitUntil(caches.keys().then((k) => Promise.all(k.map((n) => caches.delete(n)))).then(() => self.registration.unregister())));`
Keep it in place until every customer has opened the portal at least once.

## Push notifications (Phase 2)

Customers get a notification on their phone or computer when something needs them. The decision, standards, privacy
default and SSRF allowlist are in [ADR-056, Phase 2](../../../docs/adr/ADR-056-client-portal.md#phase-2-push-notifications-30-oct-2026).

| Route                | Who                                   | What                                                                                     |
| -------------------- | ------------------------------------- | ---------------------------------------------------------------------------------------- |
| `push/subscribe/`    | signed-in member, CSRF, POST (JSON)   | Store this browser's subscription `{endpoint, keys: {p256dh, auth}}`. 20 an hour.        |
| `push/unsubscribe/`  | signed-in member, CSRF, POST          | Remove one of the member's devices (JSON `{endpoint}` or form `subscription=<id>`). 30 an hour. |
| `push/test/`         | signed-in member, CSRF, POST          | Send a test notification to one of the member's devices, now. 5 an hour.                 |
| `push/renew/`        | the service worker, POST (JSON)       | Replace a subscription the browser rotated; proven by the old one's secret. Always 204. |

On the portal host they sit at the root (`/push/...`), locally at `/portal/push/...`. None exists in staff preview or on
the admin host, and a member only ever reaches their own devices (anything else is a 404).

| Setting                          | Default                          | What                                                                                     |
| -------------------------------- | -------------------------------- | ---------------------------------------------------------------------------------------- |
| `PORTAL_PUSH_VAPID_PRIVATE_KEY`  | empty (push off)                 | Secret. Raw P-256 private scalar, base64url, 43 characters. Production: generated by the deploy. |
| `PORTAL_PUSH_SUBJECT`            | `mailto:support@vitalos.co.uk`   | VAPID contact (`mailto:` or `https:`).                                                    |
| `PORTAL_PUSH_DEV_ORIGINS`        | empty                            | Local only: origins of a fake push server (e.g. `http://127.0.0.1:8765`). Production refuses it. |

- **Card and preferences:** "Notifications on this device" on Account (`/account/device/`, `templates/portal/account_device.html`; `portal.js`
  works out unavailable, iOS not installed, off, on or blocked) with the device list, and push toggles beside email on
  Notification preferences. The browser's permission prompt only follows a click on "Turn on".
- **What a phone shows:** one generic line per kind from `push.MESSAGES` ("A new question needs your answer"), never a
  project, item or organisation name, or message text. Tapping it opens `/notifications/<id>/open/`.
- **Delivery:** `notifications.notify` queues a `PushDelivery` per device and sends after commit; the content tick and
  `manage.py portal_send_pending` retry (at most three attempts). A 404/410 switches the device off.
- **Signing out** removes the device that signed out.

### Test it on a real phone (after deploy)

1. Android (Chrome): open `https://portal.vitalos.co.uk/`, sign in, optionally install the app (Account, "Install the
   app"), then Account, "Notifications on this device", **Turn on notifications** and allow the prompt.
2. iPhone or iPad (iOS 16.4+): in Safari tap Share, then Add to Home Screen, open the portal from the Home Screen icon,
   sign in, then Account, **Turn on notifications** and allow the prompt. In Safari itself the card says to install first.
3. Press **Send a test notification**. A "Vitalos: Test notification" should appear within seconds. The card reports what
   the push service answered; a failed test is recorded as a `PushDelivery` with an error category.
4. Check a real event: have staff ask the member a question. The phone shows "A new question needs your answer";
   tapping it opens the question in the portal.

To try it locally, set `PORTAL_PUSH_VAPID_PRIVATE_KEY` in your shell to a throwaway key (never commit it). On Linux:
`openssl ecparam -name prime256v1 -genkey -noout | openssl ec -outform DER 2>/dev/null | tail -c +8 | head -c 32 | base64 -w0 | tr '+/' '-_' | tr -d '='`.
A real browser on `localhost` can then subscribe to its real push service. Headless browsers cannot: the tests use a
fake push server allowed through `PORTAL_PUSH_DEV_ORIGINS`.

### Rotate the push key

Rotation invalidates every subscription: customers see "Turn on notifications" again. Remove the secret from the app
and the release job, then deploy (the workflow generates a new key; `deploy.sh` keeps whatever exists, so it only
generates one when none is there):

```sh
az containerapp update -n superadmin -g rg-vitalos-superadmin --remove-env-vars PORTAL_PUSH_VAPID_PRIVATE_KEY
az containerapp secret remove -n superadmin -g rg-vitalos-superadmin --secret-names portal-push-vapid-private-key
az containerapp job update -n superadmin-release -g rg-vitalos-superadmin --remove-env-vars PORTAL_PUSH_VAPID_PRIVATE_KEY
az containerapp job secret remove -n superadmin-release -g rg-vitalos-superadmin --secret-names portal-push-vapid-private-key
gh workflow run superadmin-deploy.yml -f confirm=DEPLOY
```

The env var goes first because Container Apps refuses to remove a secret an env var still references. Subscriptions
made with the old key are switched off the next time something would be sent to them.

## Notification deliveries (staff)

Client portal › **Notification deliveries** (`/client-portal/deliveries/`) shows every portal email and push. The
decision and its rules are in [ADR-056, "Delivery status and retention"](../../../docs/adr/ADR-056-client-portal.md#delivery-status-and-retention-30-oct-2026).

- **Summary:** per channel, for the last 24 hours and 7 days: sent, pending or retrying, failed for good. Push devices:
  active, and turned off in the last 7 days by reason. Each number opens the matching list.
- **List:** both channels, newest first, 50 a page. Filters: channel, status, organisation, kind, queued in the last N
  days. Status "Last attempt failed" (`?status=failed`, where the overview and the work queue link) covers retrying and
  failed for good; "Failed for good" (`final`) only the latter.
- **Detail** (`deliveries/<email|push>/<id>/`): the error category in plain English, the device's state, a link to the
  record, and the history from the audit trail.
- **Actions:** Retry now (queued, retrying or failed), Cancel (queued or retrying), and Retry all failed in this
  filter: at most `deliveries.BULK_RETRY_CAP` (100), newest first, no new attempt after 20 seconds, behind the styled
  confirmation dialog. Retries go through `notifications.deliver` / `push.deliver` with `manual=True` and every
  re-check still applies: membership, the member's current preference, the device, the server key, the one-day push
  expiry and the allowlist. Each action is audited (`portal.delivery_*`).
- **Never shown:** push endpoints, keys, auth secrets, push-service responses or payloads; no email body is stored.
- **Cancelled** is stored as status `failed` with the error category `cancelled` (no migration). Both `deliver`
  functions refuse it, and the overview banner and the work queue leave it out.

### Retention of delivery records

Policy: [`docs/ai-data/operations/portal-delivery-retention.md`](../../../docs/ai-data/operations/portal-delivery-retention.md).
The content tick's daily step `portal_deliveries` runs `retention.run`. It is a dry run that logs the counts until
`RETENTION_ENFORCE=true`; `manage.py portal_delivery_retention` prints the same by hand.

| Setting                                  | Default | Deletes                                                                                   |
| ---------------------------------------- | ------- | ----------------------------------------------------------------------------------------- |
| `PORTAL_DELIVERY_SENT_RETENTION_DAYS`    | 90      | Sent email and push records, counted from sending.                                        |
| `PORTAL_DELIVERY_FAILED_RETENTION_DAYS`  | 180     | Failed-for-good and cancelled records, counted from queueing.                             |
| `PORTAL_PUSH_DISABLED_RETENTION_DAYS`    | 90      | Turned-off devices, counted from turning off, once none of their records is still kept.   |

Never deleted: queued or retrying records, active devices, notifications, audit events. Values below 7 count as 7.

## Operator workflow (no duplicate entry)

1. Create the organisation, invite members (roles: viewer, contributor, approver, authorised signatory).
2. From the opportunity, **Link to client portal**: the customer's own words are copied in as a snapshot and a first brief draft (all `customer_statement`). Review, then **Share**.
3. Edit and **Propose** brief versions; tag each segment `customer:`, `fact:` or `ai:`.
4. Create the project, milestones (status label and target date; no percentage), responsibilities, dependencies, blockers and deliverables; **Publish** each.
5. Create a deliverable **version**, preview it, **Share** it (this also makes its file visible and notifies approvers).
6. Prepare an **update** as a draft, preview it, **Publish**.
7. **Ask a question** (owner, due date); answers appear on the challenge page.
8. Review **change requests** (submitted, under review, accepted, declined, with a response the customer sees).
9. Report **managed service** status by hand; it is labelled manual with its time and goes stale after 72 hours.
10. **Outstanding customer decisions** are on the Client portal overview; **Notification deliveries** is its second tab.

## Configuration still needed before customers use it

| Setting                                | Where                                    | What                                                                                                                 |
| -------------------------------------- | ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| DNS and custom domain                  | Cloudflare DNS, Azure Container App      | `portal.vitalos.co.uk` CNAME to the app and the managed-certificate binding (owner/main session). Until then the portal host receives no traffic. |
| `PORTAL_HOST`                          | repo variable (optional)                 | Defaults to `portal.vitalos.co.uk` in production.                                                                    |
| `PORTAL_ENABLED`                       | repo variable (optional)                 | Defaults on in production when a host is set. Set `false` to take the portal host back to 404.                       |
| File storage                           | `PORTAL_FILES_BUCKET` (+ `OBJECT_STORAGE_*`) | A private bucket. Without it production keeps no file bytes and tells the customer so.                           |
| Retry of failed emails                 | none needed                              | The content tick (ADR-042) retries due portal emails (at most three attempts each). `manage.py portal_send_pending` does the same by hand. |
| Delivery retention                     | `RETENTION_ENFORCE` (owner)              | A dry run until set. Read the first dry run (`manage.py portal_delivery_retention`) first; the switch also enforces the enquiry and recruitment policies. |

## Implemented and later

Implemented: everything above, the first-release journey end to end (invitation, set password, sign in, challenge, brief, milestones,
answer a question, review a deliverable, request changes or approve a specific version, recorded decision visible on both sides),
six assistant activities with deterministic fallbacks, notification preferences, delivery records, files with validation,
the installable app (Phase 1: manifest, privacy-first service worker, offline page, mobile tab bar, install guidance) and
push notifications (Phase 2: Web Push with VAPID, generic lock-screen text, per-kind preferences, a test button), and the
staff delivery status page with retention of delivery records (below).

Later phases: native apps (paid store accounts the owner buys), a "detailed text" push option, staff push, live monitoring
integrations, contractual e-signature, email OTP and customer SSO, retention jobs for anything but delivery records, customer-side organisation administration, inbound
email into discussions.
