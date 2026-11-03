# Key flows and security

Snapshot: 3 Nov 2026, commit `2096148`. Back to the [architecture index](README.md).

## Key flows

### 1. Website enquiry

The record is written before anything is sent. Email is a notification channel, never the record (ADR-019).

```mermaid
sequenceDiagram
  autonumber
  actor V as Visitor
  participant W as Website server action
  participant T as Turnstile
  participant DB as Website Postgres
  participant M as Resend or Postmark
  participant S as Super Admin
  V->>W: Submit the contact form
  W->>T: Verify the token server-side
  T-->>W: Valid
  W->>DB: rate_limit_consume with a salted key
  W->>DB: submit_enquiry, record and outbox row in one transaction
  DB-->>W: Reference, or the original one for a replayed key
  W-->>V: Thank-you page with the reference
  Note over W,DB: Runs after the response, and daily from Vercel Cron as a backstop
  W->>DB: claim_outbox_batch
  W->>M: Notification email, identifiers only in the subject
  W->>DB: mark_outbox as sent, or failed with a retry time
  opt Inbound mail enabled, an owner step
    M->>S: support copy posted by the Email Worker, filed as a website-form enquiry
  end
```

### 2. Relay answer and hand-off to a person

Relay answers only from retrieved Vitalos content, shows citations, and hands the conversation to staff below a confidence floor (ADR-035 to ADR-038).

```mermaid
sequenceDiagram
  autonumber
  actor V as Visitor
  participant WG as Relay widget
  participant W as Website Relay API
  participant DB as Postgres relay schema
  participant E as relay-embed
  participant L as DeepSeek
  participant S as Super Admin
  actor A as Staff
  Note over V,W: With the Askbridge site key set, the Askbridge widget replaces Relay on the site
  V->>WG: Ask a question
  WG->>W: POST message with the visitor token
  W->>DB: Rate limit and daily token cap
  W->>E: Embed the question
  W->>DB: match_chunks, full-text and vector search
  W->>W: Redact personal data from the prompt
  W->>L: Answer only from the retrieved sources
  L-->>W: Streamed tokens
  W-->>WG: Streamed answer with citations
  W->>DB: Store message, citations, confidence and usage
  alt Low confidence, or the visitor asks for a person
    W->>DB: Open a hand-off
    W->>S: Signed webhook, hand-off requested
    S-->>A: In-app notification and email
    A->>S: Reply in the Relay inbox
    S->>W: Signed admin API, post the reply
    W->>DB: Store the staff message
    W-->>WG: Realtime Broadcast ping
    WG->>W: Fetch new messages
  end
```

### 3. Publishing Insights and the content tick

The Super Admin owns Insights and Careers. The website caches signed reads and is told when to revalidate (ADR-039, ADR-040, ADR-042).

```mermaid
sequenceDiagram
  autonumber
  actor Ed as Editor
  participant S as Super Admin
  participant DB as Super Admin Postgres
  participant W as Website
  participant CF as Content tick Worker
  actor V as Visitor
  Ed->>S: Publish or schedule an Insights post
  S->>DB: Change, revision, audit row and SyncEvent in one transaction
  S->>W: On commit, signed POST /api/content/revalidate
  W->>W: Revalidate tags, then warm the affected paths
  W->>S: Signed reads of the content API
  V->>W: Open the post
  W-->>V: Cached page, 600 second TTL
  loop Every minute
    CF->>W: GET /api/content/cron/tick with the shared secret
    alt Scheduled work is due
      W->>S: Signed POST /api/content/v1/tick
      S->>DB: Claim due rows with skip locked, publish or close
    else Nothing is due
      W-->>CF: Return without calling the Super Admin
    end
  end
```

### 4. AI & Data brief assist

Every model call goes through the `apps.aicore` gateway, which enforces the kill switch and the per-run, daily and monthly caps (ADR-052, ADR-055).

```mermaid
sequenceDiagram
  autonumber
  actor V as Visitor
  participant W as Website AI and Data brief
  participant S as Super Admin brief-assist
  participant G as aicore gateway
  participant P as Anthropic
  V->>W: Answer the guided brief questions
  W->>S: Signed POST /api/ai-data/brief-assist/ with a hashed visitor reference
  S->>S: Signature, feature switch, body checks and rate limits
  S->>G: Ask for a suggestion
  G->>G: Versioned prompt, kill switch, per-run, daily and monthly caps
  G->>P: Messages API call
  P-->>G: Response
  G->>G: Validate against the schema, record ModelExecution and cost
  G-->>S: Suggestion, or unavailable
  S-->>W: Follow-up questions and a draft brief
  W-->>V: Suggestions, or the checklist when AI is unavailable
  Note over S,G: Stores metadata and hashes only, never the visitor's words
```

### 5. Super Admin deploy

A merge to `main` deploys the exact commit that CI tested, after guards and a fresh encrypted backup.

```mermaid
sequenceDiagram
  autonumber
  participant PR as Pull request
  participant CI as Super Admin CI
  participant D as Super Admin deploy
  participant G as ghcr.io
  participant B as Backup workflow
  participant R as Cloud Run
  PR->>CI: Merge to main with Super Admin changes
  CI-->>D: workflow_run completed, success
  D->>R: Read the commit running now, through OIDC
  D->>D: Every CI job green, destructive-migration guard over the whole range
  D->>G: Build and push the image tagged with the commit
  D->>B: Dispatch the backup and wait
  B-->>D: Encrypted dump stored
  D->>R: Run the release job, migrations
  D->>R: Deploy the new revision
  D->>R: Check /healthz/ and the running image
  Note over D,R: Rollback is a printed command that a person runs
```

## Security

### Trust boundaries

```mermaid
flowchart LR
  subgraph internet["Untrusted: public internet"]
    visitor(["Visitors"]):::person
    clientu(["Client users"]):::person
    staffu(["Staff"]):::person
  end
  subgraph edgezone["Edge controls"]
    csp["CSP and security headers,<br/>noindex outside production"]:::sec
    turn["Turnstile, honeypots<br/>and rate limits"]:::sec
    edgew["Cloudflare edge Worker<br/>shared-secret header"]:::sec
  end
  subgraph webzone["Vercel: website"]
    web["Website server code<br/>server-only secrets"]:::web
  end
  subgraph adminzone["Cloud Run: Super Admin"]
    auth["Password, TOTP, lockout,<br/>roles and classifications"]:::sec
    admin["Super Admin and portal"]:::web
  end
  subgraph datazone["Restricted: data stores"]
    wpg[("Website Postgres<br/>RLS on, no anon grants")]:::db
    adb[("Super Admin Postgres<br/>separate database")]:::db
    r2[("R2 private buckets")]:::db
  end
  subgraph processors["Processors"]
    llm["DeepSeek: redacted input<br/>Anthropic: capped gateway"]:::ext
    pay["Stripe<br/>verified webhooks"]:::ext
  end
  visitor --> csp --> web
  visitor --> turn --> web
  clientu --> edgew
  staffu --> edgew
  edgew --> auth --> admin
  web <-->|"HMAC, scoped keys,<br/>300 s window"| admin
  web -- "secret key, definer functions" --> wpg
  admin --> adb
  admin -- "short-lived signed URLs" --> r2
  web --> llm
  admin --> llm
  admin <--> pay
classDef person fill:#081a2a,stroke:#081a2a,color:#ffffff
classDef web fill:#dce4ff,stroke:#2457ff,color:#081a2a
classDef db fill:#fff6e0,stroke:#9a6700,color:#081a2a
classDef ext fill:#f1f3f5,stroke:#536273,color:#26333f,stroke-dasharray:4 3
classDef sec fill:#fdecea,stroke:#c9372c,color:#081a2a
```

### Authentication

| Who                   | How                                                                                                                                                                             |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Website visitors      | No accounts. Forms use Turnstile, honeypots and salted rate limits. Relay visitors hold a random token whose hash is stored.                                                    |
| Staff (Super Admin)   | Email and password, lockout after repeated failures (django-axes), TOTP required for SuperAdmin and for anyone who enrols a device, 8-hour sessions with HttpOnly cookies       |
| Client users (portal) | Invitations to an organisation membership; the portal host serves only portal URLs, and host-only cookies keep admin and portal sessions apart (ADR-056)                        |
| Machine to machine    | HMAC-SHA256 over timestamp, method, path, identity and body hash, with a key list per scope and a 300-second window (Relay admin API, Relay webhook, content API, brief assist) |
| Super Admin read API  | Bearer API tokens stored as a hash and a prefix, with expiry and revocation                                                                                                     |
| CI to Google Cloud    | Workload Identity Federation (OIDC) bound to this repository's `production` environment; no stored cloud keys                                                                   |

### Authorisation

- Super Admin roles are SuperAdmin, ServiceLead and Viewer. Every decision goes through `apps/accounts/roles.py`. Records carry a classification (Public, Internal, Confidential, Restricted) that limits who can see them.
- Product access is a separate permission per product (for example, opening the Askbridge admin), and each redirect is audited (ADR-044).
- Portal users see only their own organisation's published records through scoped selectors. Internal notes are never shown to customers.
- The website has no user roles. Its database grants nothing to `anon` or `authenticated`; only server code with the secret key calls the `SECURITY DEFINER` functions.

### Secrets

| Where                           | Holds                                                                    |
| ------------------------------- | ------------------------------------------------------------------------ |
| Vercel environment variables    | Website server secrets: database key, signing keys, email provider key   |
| GitHub `production` environment | Super Admin deploy values and the Relay ingest credentials               |
| GitHub `backup` environment     | Read-only backup connection and the backup passphrase                    |
| Google Secret Manager           | Super Admin runtime secrets; only the runtime service account reads them |
| Cloudflare Worker secrets       | Tick and inbound mail Worker secrets, set with `wrangler secret put`     |

`@vitalos/config` is server-only and validates every variable at build time. CI scans the client bundle for secrets, gitleaks scans every pull request, and a tracked-file pattern scan runs in `quality` and weekly. Names are documented in `.env.example`; values are never committed (`docs/security/secret-management.md`).

### Data protection

- Personal data is kept to what each feature needs. IP addresses are stored only as HMACs; analytics events are a closed, non-personal taxonomy.
- Retention: enquiries 24 months; Relay data by the nightly purge; job applications six months after the decision, as a dry run until a person switches enforcement on.
- Relay redacts personal data before every model call; the model sees only the redacted copy. The AI & Data gateway checks limits before each call, validates output against a schema and never logs prompts or outputs. Brief assist stores metadata and hashes of visitor input, never the words. Simulated or synthetic data is labelled.
- Logs carry identifiers, counts and error codes only; credential and personal-data keys are redacted.
- Production data is never copied to preview or local environments. The Super Admin database is backed up nightly as an encrypted dump.

### Browser and edge controls

- CSP with no third-party script origins except Turnstile, and the Askbridge origin only when its key is set; `frame-ancestors 'none'`; `nosniff`, a strict referrer policy and a restrictive permissions policy (ADR-020, ADR-045).
- Non-production responses carry `X-Robots-Tag: noindex`, failing closed for unknown environments.
- Client request IDs are accepted only in a strict format; otherwise a new one is generated.

### Main risks

Kept at design level because this repository is public. The full threat model is `docs/security/threat-model.md`.

| Risk                                       | Mitigation in place                                                                         | Open                                                                                             |
| ------------------------------------------ | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Leaked signing key between the two apps    | Per-scope key lists, rotation without downtime, 300-second replay window                    | Keys are rotated by hand                                                                         |
| Model provider receives personal data      | Relay redacts before each call; AI & Data has caps, a kill switch and metadata-only storage | Pattern-based redaction cannot catch everything; AI & Data relies on input limits, not redaction |
| Single Super Admin instance on a free plan | Scale to zero with one instance; nightly encrypted backups; pre-migration backup            | No high availability; the free-plan database is the only copy apart from the dumps               |
| Supply-chain compromise                    | Pinned actions, Dependabot, `pnpm audit`, pip-audit, bandit, CodeQL                         | Advisories are tracked in `docs/security/dependency-advisories.md`                               |
| Inbound mail spoofing                      | Signed Worker posts; form headers trusted only from Vitalos addresses (ADR-046)             | The Email Worker is not deployed yet                                                             |
