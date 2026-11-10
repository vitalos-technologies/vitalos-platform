# ADR 056 Client portal: customers track, collaborate on and approve their work, in the Super Admin's database

- **Status:** Accepted (engineering), 28 Oct 2026. Nothing is customer-facing until the owner binds `portal.vitalos.co.uk` (DNS and custom domain) and the portal host resolves to the app. File storage for production is a separate owner step.
- **Owner request:** one place where a customer sees the challenges they have discussed with Vitalos, collaborates on delivery, approves work and monitors managed systems, connected to the AI & Data site and the Super Admin.
- **Journey it serves:** Submitted challenge, Discovery, Assessment, Proposal, Active project, Handover, Managed operations. The original challenge (`aidata.Opportunity`, which keeps the submitted text and its history) and the discussion stay attached throughout. A customer may have several challenges and projects.

## Context

AI & Data (ADR-052) records enquiries, opportunities, qualification and proposals for staff only. Delivery has no customer view: updates, questions, deliverables and approvals happen in email, which loses version-specific decisions and leaves no record both sides can see. The Super Admin already owns authentication (accounts, django-axes, django-otp), mail (`apps.mailer`), audit (`apps.audit`), the AI gateway (`apps.aicore`) and PostgreSQL. A second application would duplicate all of that and need its own sync.

## Decision

### 1. Placement: a Django app inside the Super Admin, not a separate application

`apps.portal` shares the database, `apps.mailer` (shared layout, ADR-030; automated headers, ADR-046), `apps.audit`, `apps.aicore` and the `accounts.User` model. Staff-only models and customer-visible models are the same rows with explicit publication fields, so staff enter data once and "publish" is a state change, not a copy. Cost: a customer-facing surface lives in an internal system's process, so the boundary has to be enforced in code (below) and the portal must be switchable off independently.

### 2. Routing and hosts

- `PORTAL_HOST` set: the portal URLs are served only on that host, by a separate URL configuration (`config/portal_urls.py`) holding the portal routes and nothing else. Super Admin pages, APIs and the Django admin do not exist on that host (404). Health and static are answered by middleware before routing.
- **Owner decision (28 Oct 2026): the production host is `portal.vitalos.co.uk`.** Production settings default `PORTAL_HOST` to it (env-overridable), add it to `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`, and `deploy.sh` and `superadmin-deploy.yml` pass it with the existing variable pattern. `PORTAL_ENABLED` defaults to on in production only when `PORTAL_HOST` is set, and production refuses to start with `PORTAL_ENABLED` and no host. Until the custom domain resolves to the app the portal host receives no traffic, so nothing is exposed; the DNS record and the Azure custom-domain binding are owner/main-session steps.
- `PORTAL_HOST` empty (local default): the portal is mounted at `/portal/` for local preview only. With a host set, `/portal/` on any other host is a 404, and `PORTAL_ENABLED=false` makes both the host and `/portal/` answer 404.
- Staff tools live at `/client-portal/` on the admin host regardless of `PORTAL_ENABLED`, so content can be prepared before launch.
- **Cookies, session and CSP.** The session and CSRF cookies are host-only: `SESSION_COOKIE_DOMAIN` and `CSRF_COOKIE_DOMAIN` are `None` and a test fails otherwise, so an admin session is never sent to the portal host and the reverse. Sessions keep the 8-hour lifetime, HTTP-only, `Secure` in production, `SameSite=Lax`. The strict nonce-based CSP applies unchanged (the portal has its own stylesheet and one small script, no inline styles or handlers). The customer UI sets `Cache-Control: private, no-store` for signed-in pages and `no-store` for access pages. In local `/portal/` mode the portal and admin share one cookie jar on one host, so one account is signed in at a time; that mode is for preview only.

### 3. Who is a customer

A customer is an `accounts.User` with no staff role plus an active, accepted `Membership`. Access follows the membership on every request: revoking it, deactivating the user or deactivating the organisation closes every surface immediately (pages, downloads, search, AI, notifications, email on retry).

`CustomerBoundaryMiddleware` is deny-by-default and independent of what each admin view checks: a signed-in user with no staff role may reach portal URLs and static files only; every other path answers 403 (`/` and `/login/` send them to the portal). A test iterates the URL resolver for a customer and fails on any Super Admin URL that answers 200, including APIs, with an API token, and downloads. Staff never use the customer UI directly: they reach it through "Preview as customer" (`/client-portal/preview/<member>/as/`), which is read-only (every write is refused), bannered and audited, and bound to one member so staff see exactly what that member sees. Staff cannot be invited as members and cannot sign in to the portal.

### 4. Access

- Staff invite a member explicitly. The invitation is a single-use, expiring (72 h) token, **only its SHA-256 hash is stored**, sent through `apps.mailer` with `Auto-Submitted`, `X-Auto-Response-Suppress` and `X-Vitalos-Notification`. Re-sending replaces older links.
- The member sets a password on the portal host (12+ characters, Django validators). A person who already has a portal password confirms it to join a second organisation.
- django-axes locks sign-in (email + IP) after repeated failures, with a portal lockout page. Password reset is portal-specific (30-minute single-use link to the portal host), answers identically for unknown addresses, is rate-limited per address and only reaches live members.
- Second factor: optional TOTP through the existing django-otp devices, enrolled and verified inside the portal. Email OTP is a later phase.
- **New enquiries stay private.** Nothing is created in the portal by an enquiry. A challenge exists only when staff explicitly link an opportunity to an organisation, and it is invisible until staff share it. Access is never granted because someone knows an email address or a reference.
- Roles: viewer (read-only), contributor (comment, answer, upload, request a change), approver (also approve or request changes to a specific deliverable version, accept a brief), authorised signatory (also contractual acceptance).

### 5. Visibility model

Every customer-facing model has an explicit publication state; every internal-only field is named `internal_*` (or lives on an internal thread/file) so tests can plant markers in each and assert they never appear.

| Record                            | Customer sees it when                                                                                                                                                               |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Challenge                         | `shared_at` is set by staff (the text is a snapshot taken when linked)                                                                                                              |
| Brief version                     | proposed, agreed, superseded or changes-requested; never a draft                                                                                                                    |
| Project, milestone, project item  | `published_at` set                                                                                                                                                                  |
| Deliverable                       | published, and only its **shared**, not withdrawn versions                                                                                                                          |
| Update                            | status published (a draft is invisible; a published update is frozen)                                                                                                               |
| Question (information request)    | sent (`published_at`)                                                                                                                                                               |
| Discussion thread                 | not internal; internal threads exist for staff only                                                                                                                                 |
| File                              | `visibility = customer`; internal files are never listed or downloadable                                                                                                            |
| File version                      | its own `customer_visible` flag: customer uploads, the version pinned to a shared deliverable, or every version when staff share the whole file; never an earlier internal revision |
| Managed service and status report | published                                                                                                                                                                           |
| Change request                    | always, to the organisation that raised it                                                                                                                                          |
| Activity event, notification      | written by services from published fields only                                                                                                                                      |

All reads go through `apps/portal/selectors.py`, which scopes by organisation **and** publication; a record in another organisation or not yet published behaves exactly like one that does not exist (`Http404`). Views, search, exports, downloads, notifications and AI context builders use only those selectors. Hiding a control in a template is never the mechanism. One test module (`tests/test_portal_isolation.py`) iterates every surface for a second synthetic organisation and asserts 404 with no leakage.

Operators can preview content before publishing ("Preview: not published" banner) for a draft update, a brief version and a deliverable version, and "Preview as customer" for everything published.

### 6. Briefs, approvals, changes

- **Brief versions** carry segments tagged `customer_statement`, `ai_suggestion` or `agreed_fact`. An AI-suggested segment reaches the customer only inside a version a person proposed, and is labelled. Accepting a brief records a shared understanding, not a contract.
- **Customer statements are only words the customer sent** (lead fix, 28 Oct 2026, `apps/portal/continuity.py` `customer_words`). From an inbound enquiry: the typed sections of the classic form, or, for a guided brief, the "You said" line, the visitor's answers and blocks marked "edited by you". Never the `[vitalos-brief]` marker, checklist or AI suggestion blocks, contact rows, sector or budget, and never a staff paste (staff may paste their own call notes). An opportunity without a source enquiry carries its problem and outcome as `agreed_fact`, Vitalos's own wording, for staff to review before proposing.
- **Approvals are version-specific.** An `Approval` records who (id, email, name, role), when and which `DeliverableVersion`. A new version starts unshared and unapproved and never inherits anything; approving v1 does not approve v2 (tested). A version that has been superseded by a newer shared, non-withdrawn version refuses every decision (approve, request changes, contractual acceptance), whatever state it was in when the newer one was shared. Decisions and brief reviews lock the deliverable (or brief) row and re-check inside the transaction, so a concurrent share cannot slip a decision onto a superseded version. A database constraint allows one approval and one contractual acceptance per version. Review approval and contractual acceptance are different kinds of record; contractual acceptance needs an authorised signatory, a version flagged contractual, an explicit confirmation and stores the exact statement shown. It is not an e-signature (later phase) and is evidence of the customer's action, not a substitute for the signed scope.
- **Change requests.** The portal can only request. Staff move a request through submitted, under review, accepted or declined with a customer-visible response and a trail (who, when, from and to). Accepting records the decision; scope, price and dates change only through the staff process, and the portal has no code path that edits them.

### 7. Notifications and delivery

In-app notifications are per user, unique per event (`dedupe_key`), and scoped to organisations the user is still a live member of. Email goes through `apps.mailer.system.send` only (the email-sender guard needs no exception), to live members only, respecting per-kind preferences. Each email has a durable `EmailDelivery` (queued, sent, failed; attempts; last error category, never message text). A failed send never blocks or loses the action: it is recorded, retried at most three times by `portal_send_pending`, never duplicated (a sent record is terminal and rows are locked), and visible to operators under Client portal > Notification deliveries with a manual retry (see "Delivery status and retention" below). A retry re-checks that the recipient is still a member and still wants that kind of email.

### 8. Files

Private storage alias `portal_files` (a private S3-compatible bucket when `PORTAL_FILES_BUCKET` is set, local disk in development, none in production, in which case the customer is told contents were not kept). Validation: allow-list of types, magic-byte sniffing, Office archives inspected for structure and macros, filename/extension match, UTF-8 for text, 10 MB cap, sanitised names, random keys, SHA-256 recorded. A customer may add a version only to a file a customer uploaded. `.doc` and `.xls` (OLE) are refused with a clear message because they can carry macros the archive checks cannot see (the enquiries allow-list is unchanged). Downloads go through a view that re-checks visibility, including the version's own flag, on every request and always sends an attachment with `nosniff` and a sandbox CSP.

### 9. AI boundaries

Six assistant activities (summarise my project, what changed since my last visit, what do you need from me, explain this deliverable, which questions are unanswered, help me clarify this challenge), each with a versioned prompt (`portal_<activity>@1`) and output schema through the `apps.aicore` gateway only. Context is built only from selector-visible records; every answer cites records with links and lists what is missing or possibly out of date; model dates not present in the records are dropped, so the assistant cannot promise a date; citations that do not map to a provided record are dropped, and an answer left with no valid citations falls back to the compiled one. The assistant never changes a milestone, approval, scope or date; it may draft text into the composer, which the customer edits and sends. When the model is unavailable (today's production state: no key, off, kill switch, budget) the answer is **compiled deterministically from the records** and labelled "Compiled from your project records: no AI used"; "What do you need from me?" and "Which questions are unanswered?" are fully answerable without a model. The assistant is throttled per member (`PORTAL_AI_PER_MEMBER_PER_HOUR`, default 10 answers an hour; over it the answer is the compiled one with a note that the limit was reached) and, with website brief assist, held to a share of the daily run cap (`AI_DATA_PORTAL_DAILY_SHARE_PERCENT`, default 30%) so customer use cannot exhaust the pool staff workflows need. A hand-written replay fixture path labelled "Simulated answer for demonstration" exists only where `PORTAL_AI_REPLAY` is on (development and tests; forced off in production). Executions store metadata and hashes only.

### 10. Retention (proposal, not enforced)

Organisation, membership, approval and audit records are decision evidence and are kept for the life of the engagement. Approvals are protected from cascade deletion. Customer files carry a `retention_note`. The only automatic deletion is of delivery records and turned-off push devices (see "Delivery status and retention" below); any other job needs a documented policy (ADR) and a dry run first, per AGENTS.md. Offboarding an organisation today means revoking its members and deactivating the organisation, which closes every surface and keeps the records. Removing one person is described under "Member management" below.

### 11. Later phases (not built)

Live monitoring integrations (service status is manual only, labelled with source and last-updated, stale after `PORTAL_STATUS_STALE_HOURS`); contractual e-signature; email OTP and SSO for customers; customer self-service organisation administration; per-organisation retention jobs; billing visibility; inbound email into discussions; real-time updates; a customer-facing data export beyond the project CSV.

### 12. Review follow-ups (from the independent security review, not built)

- **Cookie tossing.** A sibling subdomain (or a page on the parent domain) could set a cookie that shadows the portal's session or CSRF cookie. Move the session and CSRF cookies to `__Host-` names (no `Domain`, `Secure`, path `/`) on the portal host and test the login, preview and logout flows with them.
- **Password-reset timing.** The reset endpoint answers identically for known and unknown addresses but the known path does more work (a token and a queued email), so response time can reveal membership. Do the work for unknown addresses too (or queue the work after responding) and measure.

## Consequences

- Customer-facing code ships in the Super Admin deploy. A mistake in the boundary is a customer-data incident, so the boundary, isolation and internal-exclusion tests are release gates (they run in the existing Super Admin CI).
- New owner steps: the DNS record and Azure custom-domain binding for `portal.vitalos.co.uk`; a private bucket and `PORTAL_FILES_BUCKET` before customers upload production files; the `PORTAL_HOST`/`PORTAL_ENABLED`/`PORTAL_FILES_BUCKET` repository variables only if the defaults need changing.
- Customer email links, invitations and password resets are absolute `https://portal.vitalos.co.uk/...` links in production.
- `apps.portal` adds the admin area "Client portal" and a panel in the opportunity workspace (`templates/aidata/_opportunity_extensions.html`).

## Phase 1: installable app (29 Oct 2026)

**Owner decision:** a mobile app for the portal starts as an installable web app (PWA) on `portal.vitalos.co.uk`, with no app store. Native apps and Web Push are later phases.

### Decision

- **Routes.** `manifest.webmanifest`, `sw.js` and `offline/` sit at the portal root (`/portal/...` in local preview) and exist only in the portal URL configuration (`pwa_patterns` in `apps/portal/urls.py`). They are public and rendered without a request context, so every visitor gets the same bytes and no personal data. Staff "Preview as customer" mounts only the workspace routes, so a preview page has no manifest link and registers no worker. The admin host answers 404 for all three, and the portal host still answers 404 for every admin route.
- **Manifest.** "Vitalos Client Portal" (short name "Vitalos"). `id`, `start_url` and `scope` are the portal root. `display: standalone`, theme colour `--aid-ink-950` (the portal header), background `--aid-bg`. Icons: 192, 512 and a maskable 512, with shortcuts to Questions and Notifications. `tooling/scripts/generate-portal-icons.mjs` generates the icons from the Vitalos symbol raster: Chromium screenshots a tile and the mark is not redrawn.
- **Service worker privacy rule.** The portal holds customers' private project data, and customers may use shared devices.
  - The worker caches only two things: public static files (same-origin `GET` under `/static/`) and the offline page.
  - Navigations are network-only. When the network fails, the worker shows the cached offline page.
  - It never stores a page, an HTMX partial, a file download, an export, a POST or API response, or anything else from the workspace.
  - It does not intercept other requests or other origins.
  - Static files are cache-first when content-hashed (production's manifest storage) and network-first otherwise (development).
  - The cache name is versioned from the precached URLs, and activating a new worker deletes every other cache.

  Nothing private is cached, so **signing out needs no cache purge**. Signed-in pages keep `Cache-Control: private, no-store`. `tests/test_portal_pwa.py` checks the precache list and the worker's source.

- **CSP unchanged.** The worker is a same-origin script (`script-src 'self'`; without `worker-src` the policy falls back to it), `portal.js` registers it (no inline script) and the manifest loads under `manifest-src 'self'`.
- **Mobile app shell.** At 52rem or narrower, and always in `display-mode: standalone`, a fixed bottom tab bar replaces the header menu. Its five tabs are Home, Challenges, Questions, Notifications (with the unread badge) and More. More opens the existing menu as a sheet with Files, Search, Account and Sign out. The shell also has:
  - 44px targets, `aria-current` on the active tab and the landmark `nav aria-label="Primary"`;
  - safe-area insets, and scroll padding so the bar never hides keyboard focus;
  - the 52rem breakpoint, which is unchanged.

  Desktop in a browser tab keeps the current layout.

- **Install guidance.** Account › Install the app (its own page, `/account/install/`, since 2 Nov 2026) has an install card instead of a popup:
  - The server HTML shows the manual steps.
  - When Chromium fires its deferred `beforeinstallprompt`, the steps become an Install button.
  - On iOS Safari the card says "Tap Share, then Add to Home Screen".
  - In the installed app it says "Installed on this device".

  The browser's automatic install banner is held back on portal pages.

### Deferred (not built)

- **Web Push.** Built in Phase 2 (below).
- **Native apps (Expo).** Need Apple Developer Program and Google Play developer accounts, which are paid and which the owner must buy, plus store review and privacy labels.
- **Offline reading of project data.** Left out on purpose because it would put private data on devices. It would first need encryption at rest and a wipe-on-sign-out design.

## Phase 2: push notifications (30 Oct 2026)

**Owner request:** notifications on the customer's phone or computer, from the installed portal, at no cost and with nothing for the owner to buy or paste.

### Decision

- **Standards.**
  - Standard Web Push: an HTTP POST to the push service the browser chose (RFC 8030), with `TTL: 86400` (a day-old notification is not worth showing), `Urgency: normal` and a `Topic` per kind, so a device that was offline gets only the latest message of each kind.
  - VAPID (RFC 8292): an ES256 JWT with `aud` set to the endpoint's origin, `exp` 12 hours ahead (24 at most) and `sub` from `PORTAL_PUSH_SUBJECT` (default `mailto:support@vitalos.co.uk`), plus the public key in `Authorization: vapid t=..., k=...`.
  - Payload encryption with `aes128gcm` (RFC 8291 and RFC 8188): ECDH on P-256 with the browser's key, HKDF-SHA256 with its authentication secret, and AES-128-GCM in one 4096-octet record.
  - A test reproduces the RFC 8291 Appendix A example byte for byte.
- **Library.** `cryptography` (Apache-2.0 OR BSD-3-Clause), pinned exactly (50.0.2), provides the primitives: ECDH, ECDSA, HKDF and AES-GCM. No elliptic-curve maths is written here. `pywebpush` and `http_ece` were not used because they are MPL-licensed and add layers we do not need; encryption, VAPID signing and the POST take about 150 lines of `apps/portal/push.py`. HTTP is `urllib` in the house style of `apps/aicore/core/providers.py`: 5-second timeouts, no redirects and bounded response reads.
- **Key lifecycle.**
  - The secret `PORTAL_PUSH_VAPID_PRIVATE_KEY` is the raw 32-byte P-256 private scalar, base64url without padding (43 characters, one line, so it passes cleanly through the workflow and `az`). The public key, a 65-byte uncompressed point, is derived at runtime and handed to the page and the service worker.
  - Generated once: the deploy workflow makes it with `openssl ecparam -name prime256v1 -genkey -noout`, extracts the scalar and masks it. `deploy.sh` `resolve`s it into the Container Apps secret `portal-push-vapid-private-key` on the app and the release job, exactly like `django-secret-key`: an existing value is always kept, so a deploy never rotates it.
  - Rotation: delete the secret (the README gives the commands) and deploy. The next deploy generates a new key. Every existing subscription is then invalid. Each subscription records the fingerprint of the key it was made with, so old ones are switched off and never sent to, and customers see "Turn on" again.
  - With no key (or an invalid one, reported by system check `portal.W001`), push is off everywhere: nothing is queued, the routes refuse politely, and the card says notifications on this device aren't available yet.
- **Lock-screen privacy (default the owner can change later).** Phones are shared and lock screens are visible.
  - A push carries only a generic line per kind ("A new question needs your answer", "A deliverable is ready for your review", "There's an update on your project"), a tag that collapses repeats of a kind, and the path of the notification's open route (`/notifications/<id>/open/`), which reveals nothing and re-checks access when followed.
  - It never carries project, item or organisation names, or message text.
  - The strings are one mapping (`push.MESSAGES`), so a later per-member "detailed text" option is a small change.
  - Pushes come only from `notifications.notify`, which services call for customer-visible, published records only. Internal notes, drafts and unpublished items never push.
- **SSRF.** The server POSTs to a URL a browser supplied, so an endpoint must:
  - be `https`, with no credentials, no port other than 443 and no fragment;
  - name a host, not an IP literal;
  - be on the allowlist: `fcm.googleapis.com`, `updates.push.services.mozilla.com`, `push.services.mozilla.com`, `web.push.apple.com`, `*.push.apple.com` or `*.notify.windows.com`. The wider `*.googleapis.com` is not needed and not allowed.

  It is checked when the subscription is stored and again before every send; a stored endpoint that no longer passes is switched off. Redirects are never followed. `PORTAL_PUSH_DEV_ORIGINS` admits exact local origins for a fake push server in development and tests, and production refuses to start with it set.

- **Records.** Migration `portal` 0005 is additive:
  - `PushSubscription`: the member, the endpoint (unique), `p256dh` and `auth` (validated: a point on the curve and 16 bytes), a coarse device label from the user agent (the raw user agent is never stored), the key fingerprint, and the last success, failure count and disabled time with a reason.
  - At most ten active devices per person; the oldest beyond that are switched off.
  - `PushDelivery`: the notification, the device, status, attempts, next attempt and an error category, never a response body. It works like `EmailDelivery`.
  - `NotificationPreference` gains `push_*` per kind, on by default. Nothing is pushed until the member turns a device on, so the default means "on once a device is added".
- **Delivery.**
  - `notify` queues a push per active device when the member's push preference for that kind allows it, under the same `send_email` and seed-suppression rules as email, and sends them once the transaction commits (at most 20 and 10 seconds per action; the rest wait).
  - `send_pending` (the content tick and `portal_send_pending`) retries 429, 5xx, timeouts and network errors at 1 and 5 minutes, honouring `Retry-After` up to an hour, for at most three attempts.
  - 404 and 410 switch the device off. 400, 401, 403, 413 and redirects are permanent, and five final failures in a row switch a device off.
  - Each send re-checks that the recipient is still a live member. Nothing in this path can break the email or the action that caused it.
- **Routes** (customer surface only; staff preview and the admin host answer 404):
  - `push/subscribe/`, `push/unsubscribe/` and `push/test/`: member auth, CSRF, POST only and per-member hourly limits from the audit trail (20, 30 and 5). A member reaches only their own devices; anything else is a 404.
  - `push/renew/`: the service worker calls it when the browser rotates a subscription. It is CSRF-exempt because a worker has no session or token. It is authenticated by the old subscription's endpoint and authentication secret, known only to that browser and this server, and answers 204 whatever happened.
  - Signing out removes the device that signed out (`portal.js` sends its endpoint with the sign-out form). An endpoint posted by a different person moves to them only when it comes with the same keys (the same browser, for example a shared computer whose last user did not sign out). Knowing another person's endpoint is not enough; with different keys the request is refused.
- **Service worker** (`SW_REVISION` 2). The Phase 1 caching rule is unchanged.
  - `push` shows the notification with `icon-192` and a monochrome `badge-96`, even for an unreadable payload.
  - `notificationclick` focuses or opens only a same-origin path inside the portal scope. Anything else opens the portal home.
  - `pushsubscriptionchange` re-subscribes and posts to `push/renew/`, best effort. Failing that, the next portal visit re-registers a rotated subscription quietly, and only in a browser where the member turned notifications on.
- **UI.**
  - Account › Notifications on this device (its own page, `/account/device/`, since 2 Nov 2026) has these states: unavailable; iOS not installed ("Install the app first: tap Share, then Add to Home Screen, then turn notifications on from the app"); off; on (Turn off, Send a test notification); blocked (how to allow it).
  - The permission prompt only ever follows a click on "Turn on".
  - A device list (label, date added, "This device", Remove).
  - Push toggles beside email on Notification preferences.
  - No inline script, and the CSP is unchanged.
- **iOS limits.** Safari supports Web Push only for a portal added to the Home Screen, on iOS or iPadOS 16.4 or later. In Safari itself the card asks the customer to install the app first.

### Consequences

- No new service, account or cost: push services are free to senders and the key lives in the existing secret store.
- After a deploy the owner turns notifications on from Account › Notifications on this device on a real phone and presses "Send a test notification". On an iPhone, install the app first.
- Headless browsers cannot register with real push services. The automated checks use a fake push service on 127.0.0.1 and a stubbed browser subscription, so the first real-device test is the proof that each push service accepts our messages.

### Deferred (not built)

- A per-member "detailed text" option (titles on the lock screen), behind an explicit choice.
- Push for staff or the Super Admin.
- Operator views of push deliveries and a retention job for delivery rows. Built on 30 Oct 2026: see "Delivery status and retention" below.
- Quiet hours and digesting several events into one notification.

## Delivery status and retention (30 Oct 2026)

**Owner request:** an admin page that shows the delivery status of portal notifications, and the clean-up of old delivery rows that Phase 2 deferred.

### Decision

- **One page for both channels.** Client portal › Notification deliveries (`/client-portal/deliveries/`, which replaces the email-only "Email delivery" page at the same address) lists email and push deliveries together, newest first. The list is one `UNION ALL` of the two tables, so the page is a fixed number of queries whatever its length.
  - **Summary:** per channel, for rows queued in the last 24 hours and 7 days, the number sent, pending or retrying, and failed for good (and how many staff cancelled). It also shows the active push devices, and the devices turned off in the last 7 days by reason.
  - **Columns:** time queued, notification kind and channel (with the push device's coarse label), organisation, member (with the address for email), status and attempts, last error category, and the send time or the next automatic attempt.
  - **Filters:** channel, status, organisation, kind and "queued in the last N days", with 50 rows a page.
  - **Status filter:** "Last attempt failed" (`status=failed`) keeps the meaning the Client portal overview and the work queue already link to: retrying and failed for good together. "Failed for good" (`final`) is the narrower one.
  - **Row detail:** the error category in plain English (for example, `gone`: "The browser removed this subscription; the device has been turned off"), the device's state and reason, a link to the record in the staff UI, and the history from the audit trail. Each failed email attempt is audited; a push attempt is not recorded separately, and the page says so.
- **What staff never see.** Push endpoints, browser keys, authentication secrets, push-service responses (never stored) and the push payload. Rows reach the templates as view models built from an allow-list of fields, and the queries do not load the subscription's endpoint or keys at all. Email rows show the address and the subject; no email body is stored. A test asserts none of those values appears on any of the pages.
- **States.** Queued, retrying (the last attempt failed and an automatic attempt remains), sent, failed (for good) and cancelled. Neither model has a "cancelled" status, and adding one would alter a column, which the migration guard forbids. So a cancelled row is `failed` with the error category `cancelled` and no attempts left, and both `deliver` functions refuse it. No migration was needed.
- **Actions** (CSRF-protected POSTs, staff only, audited as `portal.delivery_retried`, `portal.delivery_cancelled` and `portal.delivery_bulk_retried`):
  - **Retry now** on a queued, retrying or failed delivery. It goes through `notifications.deliver` or `push.deliver` with `manual=True`, which may try once more after the automatic attempts have run out. Every re-check still applies: live membership, the member's current preference for that kind, the device being on, the server key's fingerprint, the push's one-day expiry and the endpoint allowlist.
  - The preference re-check is new: it now applies to automatic retries as well, so a member who turns a kind off is not emailed or pushed by a later retry.
  - A refused retry says why ("Not sent: the member has since turned this kind of notification off"). On the list the answer is a toast and the list refreshes; without JavaScript it is a message after a redirect.
  - **Cancel** a queued or retrying delivery. The row is locked, so a send already in progress finishes first.
  - **Retry all failed in this filter:** at most 100 rows, newest first, and no new attempt after 20 seconds. It asks first in the admin's styled confirmation dialog. Whatever is left is reported, and pressing again continues.
- **Permissions and hosts.** The page is staff-only (`staff_required`: SuperAdmin and ServiceLead), like every Client portal staff page. A Viewer, a user with no role and a portal customer are refused. The portal host serves none of these routes, and the customer URLconf has no equivalent.
- **Retention** (policy: [`docs/ai-data/operations/portal-delivery-retention.md`](../ai-data/operations/portal-delivery-retention.md)). Once a day the content tick's daily step (`portal_deliveries`, beside recruitment retention) deletes:
  - sent delivery rows 90 days after sending (`PORTAL_DELIVERY_SENT_RETENTION_DAYS`);
  - failed-for-good and cancelled rows 180 days after queueing (`PORTAL_DELIVERY_FAILED_RETENTION_DAYS`);
  - turned-off push devices 90 days after they were turned off (`PORTAL_PUSH_DISABLED_RETENTION_DAYS`), but only once none of their delivery records is kept, because deleting a device deletes its records.

  It never deletes queued or retrying rows, active devices, notifications or audit events. A setting below 7 days counts as 7. Like the enquiry and recruitment jobs it is a **dry run that logs the counts per category until `RETENTION_ENFORCE=true`**. Enforced, it writes one `portal.delivery_retention` audit event with the counts. `manage.py portal_delivery_retention` prints the same dry run by hand.

### Consequences

- No new dependency, service or cost. No migration: the existing indexes (status, and the foreign keys) are enough at portal volumes, and retention keeps the tables small.
- `/client-portal/deliveries/<pk>/retry/` (the email-only retry address) still works, so existing links keep working.
- **Owner step:** read the first dry run (zero in every category until late January 2027) before setting `RETENTION_ENFORCE=true`. That switch also enforces the enquiry and recruitment policies.

### Deferred (not built)

- A per-attempt history for push (only the latest attempt's category and count are kept).
- A work-queue entry for failed pushes. The work queue lists failed portal emails only, because a device going away is routine; the summary on the delivery page shows push failures.

## Member management (30 Oct 2026)

Staff could invite, re-send, revoke and restore a member, but could not withdraw a mistyped invitation or take a person out of an organisation for good. The owner asked for both, plus an account-level view of every customer.

### Constraints

- The schema keeps customer-authored rows with `on_delete=PROTECT`: `Message.author`, `Approval.user`, `BriefReview.user`, `ChangeRequest.raised_by` and `InformationResponse.user`. The migration policy for this change is additive only, so those cannot become `SET_NULL`.
- §10 treats approvals, memberships and the audit trail as decision evidence.

### Decision

- **Actions on the Members table.** Every action is a CSRF-protected POST, needs `staff_can_manage` (SuperAdmin or ServiceLead) and is audited. Each is scoped to the organisation in the URL, `/client-portal/orgs/<org>/members/<member>/<action>/`: a member of another organisation answers 404.
  - **Change role.**
  - **Resend invitation**, while invited.
  - **Suspend access** (the existing revoke: the membership stays and access ends on the next request) and **Restore access**.
  - **Cancel invitation**, for an invitation nobody accepted: the membership and its invitation links are deleted.
  - **Remove from organisation**, for an accepted member: the membership is deleted.
- **Settling the account** (`apps/portal/members.py`). After a cancel or a removal, the person's account is:
  1. **Kept** while it has another membership or holds a staff role. Roles are read from the groups, so a suspended staff account still counts.
  2. **Deleted** when it left no footprint in any project. Its notifications, preferences, email-delivery rows and authenticators go with it.
  3. **Erased** when it did leave one. A footprint is any of: a message, an answer, a brief review, an approval, a change request, an uploaded file or file version, a change-review step, an agreed brief, or an activity event.
- **What erasing does.** The account row stays, because the record needs its author and the schema protects it. Everything personal on the row goes:
  - the email becomes `former-member-<id>@erased.invalid` (the reserved `.invalid` domain, which can never receive mail);
  - the name becomes "Former member";
  - the password is made unusable, the account is inactive and the last sign-in is cleared;
  - groups, sessions, authenticators and API tokens are removed;
  - the person's portal notifications, preferences and email-delivery rows are deleted;
  - their name and email are replaced with "Former member" in the activity-feed summaries they caused.

  Every message, answer, review, approval, change request and file stays, and customers and staff see the author as "Former member". `accounts.erasure.is_erased` recognises the account. It appears in neither user list.

- **What is kept on purpose:**
  - `Approval.user_name` and `user_email`, the name and email captured at the moment of the decision, as contractual evidence (§10);
  - `ChangeReview.actor_email`;
  - the audit trail, which is append-only and never edited. It keeps its own actor email. The new events (`portal.invitation_cancelled`, `portal.member_removed`, `portal.account_deleted`, `portal.account_erased`) name records by id, for example "Deleted portal user #12";
  - django-axes sign-in records, which are a security log.
- **Why erase rather than refuse.** Refusing would leave staff unable to remove anyone who had ever written a message, and that person would keep a live account. Reassigning their rows to one shared "Former member" account would rewrite who did what, and would update a dozen tables. A per-person tombstone keeps the project record exactly as it happened, and still removes the personal data from the account.
- **Account level.** Settings › Users & roles › Client portal users (SuperAdmin only) lists customers across organisations. A customer is an account with a membership and no staff role. The list shows name, email, organisations with role, state and last sign-in. Suspend, Restore and Remove call the same services for every membership. Staff and customers are separate lists, and the customer list has no role select.
- **No migration.**

### Consequences

- A removed person who is invited again gets a new account. Their earlier contributions stay with the erased one.
- Erased accounts are visible only in Django admin, as `former-member-<id>@erased.invalid`.
- No job deletes member or project records. The only automatic deletion is the delivery-record clean-up above (§10).
