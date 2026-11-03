# Data model

Snapshot: 3 Nov 2026, commit `2096148`. Back to the [architecture index](README.md).

The platform has two databases with one owner each. Nothing is shared by writing to the other system's store.

| Store                         | Owner                          | Holds                                                                                                | Defined in                                                                 |
| ----------------------------- | ------------------------------ | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Website PostgreSQL (Supabase) | `apps/web` server code         | 17 tables: enquiries, outbox and rate limits in `public`; 14 Relay tables in `relay`                 | 8 SQL migrations in `supabase/migrations`, pgTAP tests in `supabase/tests` |
| Super Admin PostgreSQL        | `superadmin/` (Django)         | 102 models across 17 Django apps, plus history tables from `django-simple-history`                   | 42 Django migrations in `superadmin/apps/*/migrations`                     |
| Repository                    | Editors, through pull requests | Editorial content for the public site (ADR-028)                                                      | `packages/cms/src/repo`                                                    |
| R2 object storage             | Super Admin                    | Enquiry attachments, CVs (private bucket), portal files, content media; metadata stays in PostgreSQL | `superadmin/config/settings`                                               |

Diagrams show the primary key, foreign keys, the main constraint columns and two to four meaningful columns per table. Website types are PostgreSQL types; Super Admin types are Django field kinds.

## Website database: enquiries

```mermaid
erDiagram
  ENQUIRIES ||--o{ NOTIFICATION_OUTBOX : "notifies through"
  ENQUIRIES {
    uuid id PK
    text name
    text email
    text intent
    text status
    uuid idempotency_key UK
    text ip_hash "HMAC, never the raw IP"
    timestamptz consent_at
    text privacy_notice_version
    timestamptz received_at
    timestamptz retention_until "received_at plus 24 months"
  }
  NOTIFICATION_OUTBOX {
    uuid id PK
    uuid enquiry_id FK
    text kind "one row per enquiry and kind"
    text event_type
    text state
    int attempts
    timestamptz available_at
    jsonb payload "identifiers only"
  }
  RATE_LIMIT_BUCKETS {
    text key PK "salted hash"
    timestamptz window_start PK
    int hits
  }
```

- RLS is on for every table, and `anon` and `authenticated` have no privileges. Only server code with the Supabase secret key writes, through `SECURITY DEFINER` functions: `submit_enquiry`, `find_enquiry_reference`, `rate_limit_consume`, `claim_outbox_batch`, `mark_outbox` and `purge_expired_enquiries` (ADR-006, ADR-019).
- The enquiry and its outbox row are written in one transaction. A replayed idempotency key returns the original reference and writes nothing. Delivery is at least once, with one outbox row per enquiry and kind.
- The client IP is stored only as an HMAC under a server-side salt. Rate-limit keys are salted hashes. The outbox payload carries identifiers only; personal data is read from the enquiry at send time.
- Retention: a trigger sets `retention_until` to 24 months after receipt; a daily Vercel Cron calls `/api/internal/retention/purge`.

## Website database: Relay

```mermaid
erDiagram
  CONVERSATIONS ||--o{ MESSAGES : "contains"
  CONVERSATIONS ||--o{ HANDOFFS : "escalates"
  CONVERSATIONS ||--o{ RESUME_TOKENS : "resumed by"
  CONVERSATIONS |o--o{ EMAIL_OUTBOX : "emails"
  CONVERSATIONS |o--o{ KB_GAPS : "example for"
  MESSAGES |o--o{ HANDOFFS : "triggers"
  KB_DOCUMENTS ||--o{ KB_CHUNKS : "split into"
  CONVERSATIONS {
    uuid id PK
    text visitor_token_hash
    text channel_key UK
    conversation_status status
    citext contact_email
    timestamptz consent_at
    text ip_hash
    int ai_turns
    timestamptz last_message_at
  }
  MESSAGES {
    uuid id PK
    uuid conversation_id FK
    sender_type sender_type
    text body
    text body_redacted
    jsonb citations
    real confidence
    int tokens_in
    int tokens_out
  }
  HANDOFFS {
    uuid id PK
    uuid conversation_id FK
    uuid message_id FK
    handoff_trigger trigger
    timestamptz requested_at
    timestamptz joined_at
    timestamptz resolved_at
  }
  RESUME_TOKENS {
    text token_hash PK
    uuid conversation_id FK
    timestamptz expires_at
  }
  KB_DOCUMENTS {
    uuid id PK
    kb_source source
    text source_ref UK
    text title
    text type
    text checksum
    kb_status status
  }
  KB_CHUNKS {
    uuid id PK
    uuid document_id FK
    int ix
    tsvector fts
    vector embedding "384 dimensions"
  }
  KB_GAPS {
    uuid id PK
    text question_norm UK
    int count
    uuid example_conversation_id FK
    text status
  }
  EMAIL_OUTBOX {
    uuid id PK
    uuid conversation_id FK
    text provider
    text status
  }
```

Six more Relay tables stand alone: `kb_sync_runs` (ingest runs), `admin_presence` (staff availability), `settings` (one row of configuration), `usage_daily` (tokens, estimated cost and cap notices), `rate_limits` and `audit_log`.

- The `relay` schema has RLS on every table with no `anon` or `authenticated` policies. Only the website server, using the secret key, reads and writes it. Business rules live in `@vitalos/relay-core` (ADR-035).
- Retrieval is hybrid: a generated `tsvector` for full-text search and a 384-dimension `vector` for similarity, combined in `relay.match_chunks` (ADR-037).
- Knowledge is re-indexed by checksum from the repository, the Master FAQ and CMS content (`@vitalos/relay-knowledge`, the `Relay knowledge` workflow).
- `relay.purge_expired` runs nightly from `pg_cron`; `relay.forget_gap_examples` removes example questions from gaps. Retention periods are in `docs/relay/PRIVACY.md`.

## Super Admin: enquiries, AI & Data and billing

```mermaid
erDiagram
  USER ||--o{ API_TOKEN : "owns"
  USER |o--o{ ENQUIRY : "assigned"
  ENQUIRY ||--o{ MESSAGE : "thread"
  MESSAGE ||--o{ ATTACHMENT : "has"
  ENQUIRY }o--o{ TAG : "tagged"
  ENQUIRY ||--o{ ENQUIRY_NOTE : "notes"
  ENQUIRY |o--o| OPPORTUNITY : "becomes"
  OPPORTUNITY ||--o{ STAGE_CHANGE : "history"
  OPPORTUNITY |o--o{ DRAFT : "AI drafts"
  OPPORTUNITY |o--o{ INVOICE : "billed by"
  INVOICE ||--o{ INVOICE_LINE : "lines"
  INVOICE ||--o{ PAYMENT : "paid by"
  USER {
    bigint id PK
    email email UK
    char full_name
    bool is_primary_owner
  }
  API_TOKEN {
    bigint id PK
    bigint user_id FK
    char prefix
    char key_hash "hash only"
    datetime expires_at
    datetime revoked_at
  }
  ENQUIRY {
    bigint id PK
    int number
    char source
    char status
    char priority
    bigint assignee_id FK
    datetime sla_due_at
    datetime anonymised_at
  }
  MESSAGE {
    bigint id PK
    bigint enquiry_id FK
    char direction
    char message_id_header
    text html_body_sanitised
    char delivery_status
  }
  ATTACHMENT {
    bigint id PK
    bigint message_id FK
    char storage_key
    char sha256
    char refused_reason
  }
  OPPORTUNITY {
    bigint id PK
    bigint enquiry_id FK
    char stage
    char offer
    char budget_band
    decimal estimated_value
  }
  DRAFT {
    bigint id PK
    bigint opportunity_id FK
    char kind
    char state
    int version
    uuid execution_id
    bool simulated
  }
  INVOICE {
    bigint id PK
    bigint opportunity_id FK
    char number
    char status
    bigint total_pence
    bigint balance_due_pence
    char stripe_payment_link_id
  }
  PAYMENT {
    bigint id PK
    bigint invoice_id FK
    bigint amount_pence
    char method
    char status
    char stripe_checkout_session_id
  }
```

- Enquiries arrive from inbound mail (Email Worker or Resend), classified as person, form relay or automated (ADR-046). Message HTML is stored raw and sanitised separately.
- An enquiry can become an AI & Data `Opportunity`. AI work is a `Draft` with evidence and versions, and nothing is sent automatically (ADR-055). Every model call is metered as a standalone `ModelExecution` row (workflow, provider, model, tokens, cost in GBP, outcome).
- Billing amounts are integers in pence. Payment links and checkout sessions come from Stripe; Stripe webhooks are verified before a `Payment` is recorded (ADR-053).
- API tokens are stored as a hash with a prefix, and can expire or be revoked.

## Super Admin: client portal

```mermaid
erDiagram
  ORGANISATION ||--o{ MEMBERSHIP : "has"
  USER ||--o{ MEMBERSHIP : "holds"
  ORGANISATION ||--o{ CHALLENGE : "raises"
  OPPORTUNITY |o--o| CHALLENGE : "shared as"
  CHALLENGE ||--o{ BRIEF_VERSION : "versions"
  CHALLENGE ||--o{ PROJECT : "delivered by"
  PROJECT ||--o{ MILESTONE : "plans"
  PROJECT ||--o{ DELIVERABLE : "produces"
  MILESTONE |o--o{ DELIVERABLE : "groups"
  DELIVERABLE ||--o{ DELIVERABLE_VERSION : "versions"
  DELIVERABLE_VERSION ||--o{ APPROVAL : "approved by"
  FILE ||--o{ FILE_VERSION : "versions"
  FILE_VERSION |o--o{ DELIVERABLE_VERSION : "attached to"
  PROJECT ||--o{ CHANGE_REQUEST : "changes"
  ORGANISATION {
    bigint id PK
    slug slug UK
    bool is_synthetic
    bool is_active
  }
  MEMBERSHIP {
    bigint id PK
    bigint organisation_id FK
    bigint user_id FK
    char role
    datetime revoked_at
  }
  CHALLENGE {
    bigint id PK
    bigint organisation_id FK
    bigint opportunity_id FK
    char journey_stage
    datetime shared_at
  }
  BRIEF_VERSION {
    bigint id PK
    bigint challenge_id FK
    int number
    char status
    datetime agreed_at
  }
  PROJECT {
    bigint id PK
    bigint challenge_id FK
    char status
    date target_date
    datetime published_at
  }
  MILESTONE {
    bigint id PK
    bigint project_id FK
    char status
    date target_date
  }
  DELIVERABLE {
    bigint id PK
    bigint project_id FK
    bigint milestone_id FK
    datetime published_at
  }
  DELIVERABLE_VERSION {
    bigint id PK
    bigint deliverable_id FK
    bigint file_version_id FK
    int number
    bool requires_approval
    bool is_contractual
  }
  APPROVAL {
    bigint id PK
    bigint version_id FK
    bigint user_id FK
    char decision
    text statement
  }
  FILE {
    bigint id PK
    char visibility
    bool uploaded_by_customer
  }
  FILE_VERSION {
    bigint id PK
    bigint file_id FK
    char storage_key
    char sha256
    char upload_status
  }
  CHANGE_REQUEST {
    bigint id PK
    bigint project_id FK
    char status
    char affects
  }
```

The portal also has `Invitation`, `BriefReview`, `ProjectItem`, `ChangeReview`, `InformationRequest`, `InformationResponse`, `Thread`, `Message`, `Update`, `ManagedService`, `ServiceStatusReport`, `Event`, `Notification`, `NotificationPreference`, `EmailDelivery`, `PushSubscription` and `PushDelivery`.

- Every customer-facing record has an explicit publication state. Internal-only fields (`internal_notes`) are never rendered to customers, searched, emailed, exported or given to the AI (ADR-056).
- Approvals are tied to one deliverable version and keep the approver's name, email, role and statement. Approvals, organisations and audit records are decision evidence and are not deleted by cascade.
- Files keep their metadata and SHA-256 in PostgreSQL; the bytes live in private object storage.

## Super Admin: Insights, Careers and content sync

```mermaid
erDiagram
  POST ||--o{ POST_REVISION : "revisions"
  POST }o--o{ AUTHOR : "written by"
  POST }o--o{ TOPIC : "filed under"
  POST ||--o{ EDITORIAL_CHECK : "checked by"
  ROLE ||--o{ ROLE_REVISION : "revisions"
  ROLE ||--o{ APPLICATION : "receives"
  ROLE ||--o{ UPLOAD_TICKET : "issues"
  APPLICATION ||--o{ APPLICATION_EVENT : "audit trail"
  POST {
    uuid id PK
    char slug UK
    char status
    char format
    datetime publish_at
    char published_hash
  }
  POST_REVISION {
    bigint id PK
    bigint post_id FK
    json snapshot
    char revision_hash
  }
  ROLE {
    uuid id PK
    char slug UK
    char status
    datetime opens_at
    datetime closes_at
  }
  ROLE_REVISION {
    bigint id PK
    uuid role_id FK
    json snapshot
  }
  APPLICATION {
    uuid id PK
    uuid role_id FK
    char stage
    char cv_path "private bucket key"
    datetime consent_at
    char ip_hash
    datetime decided_at
  }
  UPLOAD_TICKET {
    uuid id PK
    uuid role_id FK
    char token_hash
    datetime expires_at
    datetime consumed_at
  }
  APPLICATION_EVENT {
    bigint id PK
    uuid application_id FK
    char type
    datetime at
  }
  SYNC_EVENT {
    uuid id PK
    char entity
    char action
    json tags
    datetime delivered_at
    int attempts
  }
  SLUG_REDIRECT {
    bigint id PK
    char entity
    char from_slug
    uuid to_id
  }
  MEDIA_ASSET {
    uuid id PK
    char key
    char purpose
    char alt
  }
```

- Insights and Careers are managed in the Super Admin and served to the website through the signed content API (ADR-039, ADR-040). Each publish writes a revision and a `SyncEvent` outbox row in the same transaction as the change.
- CVs never pass through the website: the browser uploads to a pre-signed URL issued against an `UploadTicket`. Applications are deleted six months after the decision; the job runs as a dry run until retention is switched on by a person (ADR-041).

## Super Admin: company architecture

```mermaid
erDiagram
  SERVICE_LINE ||--o{ PRACTICE : "groups"
  PRACTICE ||--o{ SOLUTION : "offers"
  SOLUTION ||--o{ OFFER : "packages"
  SERVICE_LINE }o--o{ TEAM_MEMBER : "staffed by"
  USER |o--o| TEAM_MEMBER : "is"
  SERVICE_LINE ||--o{ PROJECT : "runs"
  TEAM_MEMBER |o--o{ PROJECT : "leads"
  SERVICE_LINE ||--o{ KPI : "measured by"
  KPI ||--o{ KPI_VALUE : "values"
  SERVICE_LINE |o--o{ DECISION : "records"
  USER |o--o{ SERVICE_LINE : "owns"
  COMPANY {
    bigint id PK
    char name
    char classification
  }
  SERVICE_LINE {
    bigint id PK
    slug slug UK
    bigint owner_id FK
    char classification
    bool is_archived
  }
  PRACTICE {
    bigint id PK
    bigint service_line_id FK
  }
  SOLUTION {
    bigint id PK
    bigint practice_id FK
  }
  OFFER {
    bigint id PK
    bigint solution_id FK
  }
  TEAM_MEMBER {
    bigint id PK
    bigint user_id FK
    char role_title
  }
  PROJECT {
    bigint id PK
    bigint service_line_id FK
    bigint lead_id FK
    char status
    char classification
  }
  KPI {
    bigint id PK
    bigint service_line_id FK
    decimal target
    bool is_headline
  }
  KPI_VALUE {
    bigint id PK
    bigint kpi_id FK
    date date
    decimal value
  }
  DECISION {
    bigint id PK
    bigint service_line_id FK
    date date
  }
  USER {
    bigint id PK
    email email UK
  }
```

- These models inherit `GovernedModel`: created and updated by, a classification (Public, Internal, Confidential, Restricted), archive instead of delete, and full history (ADR-026).
- `Practice`, `Solution` and `Offer` share the abstract `Offering` base.

## Table inventory

### Website database (17 tables)

| Schema   | Tables                                                                                                                                                                                                    |
| -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `public` | `enquiries`, `notification_outbox`, `rate_limit_buckets`                                                                                                                                                  |
| `relay`  | `conversations`, `messages`, `handoffs`, `resume_tokens`, `kb_documents`, `kb_chunks`, `kb_gaps`, `kb_sync_runs`, `admin_presence`, `settings`, `usage_daily`, `rate_limits`, `audit_log`, `email_outbox` |

### Super Admin database (102 models)

| App                   | Models                                                                                                                                                                                                                                                                                                                                                                                                    |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `accounts` (2)        | User, ApiToken                                                                                                                                                                                                                                                                                                                                                                                            |
| `aicore` (2)          | ModelExecution, AiSettings                                                                                                                                                                                                                                                                                                                                                                                |
| `aidata` (9)          | PipelineSettings, Opportunity, OpportunityNote, StageChange, OfferPrice, BudgetSettings, CostEntry, Draft, BriefAssistEvent                                                                                                                                                                                                                                                                               |
| `architecture` (10)   | Company, ServiceLine, Practice, Solution, Offer, TeamMember, Project, KPI, KPIValue, Decision                                                                                                                                                                                                                                                                                                             |
| `audit` (1)           | AuditEvent                                                                                                                                                                                                                                                                                                                                                                                                |
| `billing` (4)         | BillingSettings, Invoice, InvoiceLine, Payment                                                                                                                                                                                                                                                                                                                                                            |
| `careers` (8)         | Role, RoleRevision, Application, ApplicationNote, ApplicationEvent, CareersSettings, UploadTicket, CareersAlertEmail                                                                                                                                                                                                                                                                                      |
| `content_sync` (6)    | SyncEvent, SlugRedirect, SiteSettings, SiteSection, TickState, MediaAsset                                                                                                                                                                                                                                                                                                                                 |
| `email_templates` (3) | EmailTemplate, EmailTemplateVersion, EmailSuppression                                                                                                                                                                                                                                                                                                                                                     |
| `enquiries` (9)       | Tag, Enquiry, Message, Attachment, EnquiryNote, CannedResponse, InboxSettings, NotificationPreference, OutboundNotification                                                                                                                                                                                                                                                                               |
| `insights` (8)        | Author, Topic, Post, PostAuthor, PostTopic, PostRelated, PostRevision, EditorialCheck                                                                                                                                                                                                                                                                                                                     |
| `notifications` (1)   | Notification                                                                                                                                                                                                                                                                                                                                                                                              |
| `outreach` (2)        | OutreachSettings, Contact                                                                                                                                                                                                                                                                                                                                                                                 |
| `portal` (29)         | Organisation, Membership, Invitation, Challenge, BriefVersion, BriefReview, Project, ProjectItem, Milestone, Deliverable, DeliverableVersion, Approval, ChangeRequest, ChangeReview, InformationRequest, InformationResponse, Thread, Message, Update, File, FileVersion, ManagedService, ServiceStatusReport, Event, Notification, NotificationPreference, EmailDelivery, PushSubscription, PushDelivery |
| `products` (1)        | ProductAccess                                                                                                                                                                                                                                                                                                                                                                                             |
| `recon_demo` (2)      | ReconRun, ReviewItem                                                                                                                                                                                                                                                                                                                                                                                      |
| `relay` (5)           | RelayNotification, RelayPreference, RelayAlertLog, RelayInboundEvent, RelayInboxState                                                                                                                                                                                                                                                                                                                     |

`core` holds the abstract `GovernedModel`; `api` and `mailer` have no models.
