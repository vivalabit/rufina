# Rufina

Personal AI assistant for job search workflows: profile setup, vacancy search, matching, document generation, application tracking, and future auto-apply automation.

## Database migrations

The API applies all pending Alembic migrations before it starts accepting
requests. A migration or database connection failure aborts startup.

### Docker volumes and personal resume templates

Personal resume templates are stored in PostgreSQL and are intentionally not
kept in Git. **Running `docker compose down -v` deletes the `postgres-data`
volume, including all personal resume templates and other database data.**
Use `docker compose down` without `-v` when the data should be preserved.

The Resume templates manager can export a personal template as one portable
JSON file and import it later. The export contains only the template name,
bundled base-template ID, and validated design tokens—never an owner ID or an
internal database ID. Keep exports outside the repository, for example in
Downloads or personal backup storage.

### Request identity and ownership

Application data is scoped by the authenticated owner identity supplied in the
`X-Rufina-Owner-Id` header. In non-local environments the header is required and
must be injected by a trusted authentication proxy; that proxy must strip any
client-supplied value before forwarding the request. Local development falls
back to `local-owner` for compatibility with the single-user setup. The legacy
`X-Tasko-Owner-Id` header remains accepted during the rename transition.

Applications, application events, confirmations, document templates, workspace
sources, documents, validation artifacts, pack jobs, and DOCX downloads are
filtered by this identity. New records receive the request owner automatically,
and legacy records are assigned to `local-owner` by the ownership migration.

Run migrations manually from the repository root with:

```bash
cd apps/api
alembic upgrade head
```

```bash
cd apps/api
alembic stamp 20260718_0001
alembic upgrade head
```

## Stack

- Frontend: Next.js, TypeScript, Tailwind CSS, shadcn/ui style components
- Backend: Python FastAPI
- Data: PostgreSQL, SQLAlchemy, pgvector later
- Queues: Celery, Redis
- AI: OpenAI API, LangChain, LangGraph later
- Automation: Playwright Python
- Storage: S3-compatible storage later

## Rufina OpenClaw agent

The AI Assistant uses its own isolated `rufina-assistant` agent instead of the
personal `main` agent. Set it up once before starting the API:

```bash
pnpm openclaw:setup
```

The setup is idempotent. It creates a separate workspace and agent state,
selects `openai/gpt-5.6-terra`, disables reasoning, caps answers at 1,200
tokens, and disables all external skills and tools. Rufina conversations and
memory are therefore kept separate from the personal assistant. On the first
run after the rename, the setup copies an existing `tasko-assistant` workspace
to `rufina-assistant` so its memory is preserved.

Docker Compose keeps OpenClaw's mutable SQLite plugin state in the dedicated
`openclaw-tasko-state` volume. On its first start, the API seeds that volume
from the host OpenClaw state and rebuilds the plugin-state index. This avoids
sharing a WAL database between macOS and the Linux container while preserving
the host configuration, Codex plugin registration, and provider credentials.

GPT-5.6 Terra requires OpenClaw 2026.7.1 or newer.
It runs through OpenClaw's native Codex harness while retaining the isolated
Rufina workspace, memory, token cap, and disabled tool policy.

Assistant responses use resumable SSE through `POST /assistant/chat/stream`.
Clients reconnect with the same `requestId` and last received `offset`; active
generation can be cancelled with `DELETE /assistant/chat/stream/{requestId}`.

Assistant requests have a bounded 32,000-character prompt and a 6,000-character
user-message limit. PostgreSQL keeps the complete conversation, while the model
receives a compact summary of older turns plus the latest 12 messages. Each
generation uses a fresh isolated OpenClaw session so hidden provider context
cannot grow without a bound. Temporary timeouts, rate limits, and network
failures are retried once with exponential backoff. Every run writes a
structured JSON log containing latency, model, token counts (provider-reported
when available, otherwise explicitly marked estimates), prompt size, and retry
count. Vacancy/profile/application text is passed through an untrusted-data
boundary that removes common prompt-injection instructions before generation.

The reliability budget can be adjusted with these API environment variables:

- `OPENCLAW_ASSISTANT_TIMEOUT_SECONDS`
- `OPENCLAW_ASSISTANT_MAX_ATTEMPTS`
- `OPENCLAW_ASSISTANT_RETRY_BACKOFF_SECONDS`
- `OPENCLAW_ASSISTANT_MAX_PROMPT_CHARS`
- `OPENCLAW_ASSISTANT_MAX_USER_MESSAGE_CHARS`
- `OPENCLAW_ASSISTANT_MAX_HISTORY_MESSAGES`
- `OPENCLAW_ASSISTANT_MAX_HISTORY_CHARS`

AI transport is selected with `AI_BACKEND`:

- `openclaw_codex` (default) preserves the existing isolated OpenClaw CLI flow.
- `openai_api` sends the same prompts through the OpenAI Responses API. Set
  `OPENAI_API_KEY`; optionally override `OPENAI_API_BASE_URL` and
  `OPENAI_API_MODEL`. Direct API reasoning and reliability are configured with
  `OPENAI_API_REASONING_EFFORT`, `OPENAI_API_TIMEOUT_SECONDS`,
  `OPENAI_API_MAX_ATTEMPTS`, and `OPENAI_API_RETRY_BACKOFF_SECONDS`.

These values can also be changed from the Settings screen. Settings updates are
partial, and the OpenAI API key is returned to the browser only as configured
state plus a masked preview.

Vacancy screening has an independent, lower-cost model budget configured with
`JOB_SCREENING_MODEL`, `JOB_SCREENING_REASONING`,
`JOB_SCREENING_BATCH_SIZE`, `JOB_SCREENING_TIMEOUT_SECONDS`,
`JOB_SCREENING_MAX_ATTEMPTS`, and `JOB_SCREENING_MAX_DESCRIPTION_CHARS`.
Changing these values does not change the model used for the full AI Match.

Both modes return the same internal result contract: text, structured data,
model, backend, token usage, latency, and session/response ID.

Assistant history is stored in PostgreSQL in normalized `conversations` and
`messages` tables. `GET /assistant/conversations` returns active conversations;
pass `archived=true` for the archive. Conversation context, title, timestamps,
messages, and the isolated OpenClaw session key are persisted across browsers.
The frontend imports the legacy `localStorage` history once, without
overwriting conversations that already exist on the server.

Assistant responses can be saved as editable cover letters or tailored
resumes. Documents, vacancy-specific variants, immutable content versions, and
application attachments are stored in PostgreSQL through `/documents`.
`GET /documents/{id}/download` returns the stored rendered `.docx` for the
current or a selected historical version. If that rendered artifact is no
longer available, the API returns `410 Gone`; it never reconstructs a DOCX from
the stored generation payload.

### Document storage and AI disclosure

DOCX templates are deduplicated per document type by the SHA-256 digest of the
uploaded bytes. Before storage, Rufina rejects unsafe ZIP paths, encrypted or
symlinked entries, malformed XML, DTDs/entities, and packages that exceed the
entry-count, uncompressed-size, XML-size, or XML-element limits.

Source templates and AI-generated files have independent retention. Deleting a
source template removes its original bytes and extracted text but keeps any
already-generated DOCX files downloadable. Deleting a document removes all of
its versions, attachments, validation/provenance records, and generated DOCX
files. Source templates remain until explicitly deleted. AI results use the
owner-selected retention period (1–365 days) and are deleted after the last AI
activity reaches that TTL.

Temporary pack jobs and validation artifacts are removed by a background API
task, independently of endpoint traffic. The cleanup runs on startup and every
`STORAGE_CLEANUP_INTERVAL_SECONDS` seconds (default: 300). Deleting an owning
application or template also removes dependent temporary records through
database-level cascading foreign keys.

AI consent is authoritative on the API, not in browser storage. `PUT
/privacy/ai-consent` records the current consent version, a server timestamp,
and the owner's retention period. Assistant, AI matching, and resume-import AI
routes return `403 ai_consent_required` unless that stored version matches the
deployment's `AI_CONSENT_VERSION`. `PUT /privacy/ai-retention` changes the TTL;
`DELETE /privacy/ai-data` removes retained AI results immediately; and `DELETE
/privacy/ai-consent` revokes consent and deletes AI results by default.
Conversations, generated documents, assistant action records, match data, and
temporary generation artifacts are covered; source templates and manually
confirmed candidate facts are preserved. Provider-side processing and
retention remain governed by the provider configured for the deployment.

OpenClaw can propose a small allowlist of Rufina actions: application notes and
next steps, interview events, documents, and individual profile fields. These
proposals are stored with the assistant message and rendered as previews. No
mutation runs during generation; FastAPI executes an idempotent action only
after the user clicks Apply.

## Workspace Docker E2E

Install the browser-test dependency and Chromium once:

```bash
python3 -m pip install -r tests/e2e/requirements.txt
python3 -m playwright install chromium
```

Run the complete workspace scenario from the repository root:

```bash
pnpm test:e2e:workspace
```

The runner creates an isolated Docker Compose project with PostgreSQL, Redis,
the API, and the Next.js frontend. A real headless Chromium session migrates
legacy browser data, completes confirmations and server-side AI consent,
generates a CV, cover letter, and atomic pack, verifies validation and Unicode
download filenames, exercises an API outage and retry, then restarts PostgreSQL
and verifies persisted downloads. AI output is supplied by a deterministic
OpenClaw test double, including one transient pack-generation failure so the
retry path is covered without an external model call. Containers and volumes
are removed after the run; API, web, PostgreSQL, and Redis ports can be
overridden with `API_PORT`, `WEB_PORT`, `POSTGRES_PORT`, and `REDIS_PORT`.
