# Direct Company Parsers: Context and Implementation Guide

This document is the starting point for developing parsers for official company
career pages. It can be given to an AI in a new chat to quickly restore the
relevant architectural context.

## What Is a Direct Company?

A Direct Company is a vacancy source connected to an employer's official career
page without using Bright Data. When selected, its parser scans the entire
available company vacancy catalog. Common search fields and `results_limit` do
not currently restrict these scans: all vacancies are collected first, after
which the shared pipeline keeps only new vacancies and optionally filters them
with AI.

The current human-readable list of companies and career pages is stored in
[`docs/direct-companies.md`](direct-companies.md). The backend runtime source of
truth is `DIRECT_COMPANY_PARSERS` in
[`apps/api/app/core/vacancy_sources.py`](../apps/api/app/core/vacancy_sources.py).
The frontend catalog containing company names and logos is in
[`apps/web/src/lib/direct-company-catalog.ts`](../apps/web/src/lib/direct-company-catalog.ts).
These two catalogs and the documentation must remain synchronized when a source
is added.


## Stack

- Python 3.12, FastAPI, and Pydantic on the backend;
- `httpx` for HTTP/API requests and parallel detail-page loading;
- `scrapling` (`Fetcher` and `Selector`) for HTML and CSS selectors;
- SQLAlchemy and PostgreSQL for known vacancies, screening results, and matches;
- OpenAI API or Codex through OpenClaw for AI screening and AI matching;
- Next.js, React, and TypeScript for source selection and vacancy display;
- local SVG logos in `apps/web/public/company-logos/`;
- pytest for the backend and Vitest with Testing Library for the frontend.

## Data Flow

1. The user selects companies in the UI. Their IDs are sent as regular vacancy
   sources, for example `sources: ["swisscom", "galaxus"]`.
2. `create_vacancy_search_runner()` adds dynamically created Direct Company
   parsers to the LinkedIn, Indeed, and jobs.ch parsers.
3. `create_direct_company_parsers()` imports each class from its `parser_path`
   and passes values from `Settings` according to its `settings_map`.
4. Each parser returns a `ParserSearchResponse` containing `ParsedJob` records.
5. `VacancySearchRunner` merges the results and deduplicates them by canonical
   URL or `title + company + location`. A failure in one company is recorded in
   `source_errors` without discarding successful results from other sources.
6. `prepare_new_job_candidates()` compares vacancies with `StoredJobRecord`
   entries by stable job ID, canonical URL, and identity. Known vacancies are
   not processed further.
7. When screening is enabled, only new candidates are sent to AI in batches.
   Decisions are cached by vacancy hash, configuration hash, model, and prompt
   version. Only vacancies with a `keep` decision are persisted; `reject`,
   `uncertain`, and screening errors are not added. External AI processing
   requires current user consent.
8. Persisted new vacancies can additionally receive an AI match against the
   candidate profile when `aiAnalysisEnabled` is enabled. This is a separate
   stage that runs after screening.
9. A stored vacancy ID begins with `<source-id>-`. The frontend uses this prefix
   to find the company in its catalog and display the correct logo.

The main orchestration code is located in:

- [`apps/api/app/services/vacancy_search.py`](../apps/api/app/services/vacancy_search.py);
- [`apps/api/app/services/job_search_execution.py`](../apps/api/app/services/job_search_execution.py);
- [`apps/api/app/services/parsers/companies/__init__.py`](../apps/api/app/services/parsers/companies/__init__.py).

## Parser Contract

Create each parser in `apps/api/app/services/parsers/companies/<id>.py`. Start
from an existing parser for the same ATS or integration type instead of copying
an unrelated company: Swisscom is the Workday JSON API example, Galaxus is the
HTML plus JSON-LD/detail-page example, and SBB discovers an internal JSON
endpoint from HTML.

The minimum class contract is:

```python
class ExampleJobsParser:
    parser_id = "example"

    def __init__(self, *, base_url: str, timeout_seconds: float, ...):
        ...

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        jobs = [...]  # Collect the complete catalog.
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=f"Scanned {len(jobs)} Example vacancies",
        )
```

Normalize every vacancy into `ParsedJob` from
[`apps/api/app/models/parsers.py`](../apps/api/app/models/parsers.py). The most
important fields are:

- `source` — exactly the same ID as `parser_id` and the registry ID;
- `title`, `company`, and `location` — used for fallback deduplication;
- `url` — a stable public URL and the primary identity for a new vacancy;
- `apply_url` — the direct application link when different from `url`;
- `description` — complete cleaned text for effective AI screening and matching;
- `posted_at`, `employment_type`, `seniority`, and salary fields when available;
- `raw` — the original record, pagination metadata, and detail-fetch diagnostics.

Expected behavior:

- do not truncate the complete catalog using `request.results_limit`;
- follow all real pagination and add a defensive `max_pages` limit when the
  external API determines the page count;
- deduplicate records inside the source when `request.deduplicate=True`;
- use reasonable timeouts, browser-like headers, and redirect handling;
- load detail pages concurrently with a limited `detail_workers` value;
- preserve the listing record when an individual detail page fails, when it is
  safe to do so, and store `detail_error` in `raw`;
- raise a subclass of `DirectCompanyRequestError` when the listing API is
  broken, the payload is unexpected, or parsing cannot safely continue;
- do not add company-specific imports or conditionals to the central runner.

## Adding a New Company

1. Inspect the official site. Prefer JSON APIs and JSON-LD over parsing the
   visual DOM. Identify pagination, total count, stable job ID, detail URL, and
   application URL.
2. Add base URL, timeout, `max_pages`, and/or `detail_workers` settings to
   [`apps/api/app/core/settings.py`](../apps/api/app/core/settings.py).
3. Create `<id>.py` using the parser contract above. The ID must be stable and
   lowercase, for example `example_company`.
4. Register the parser in `DIRECT_COMPANY_PARSERS` with its `id`, display
   `name`, public `careers_url`, `module:Class` `parser_path`, and constructor
   argument to Settings field mappings in `settings_map`.
5. Add the same company to `directCompanyCatalog`. The IDs must match exactly.
6. Store a compact official SVG at
   `apps/web/public/company-logos/<id>.svg`. Configure `logoSrc`, accessible
   `logoAlt`, and correct intrinsic `logoWidth` and `logoHeight`. Prefer a square
   symbol without a long wordmark for vacancy-list icons.
7. Add the company to [`docs/direct-companies.md`](direct-companies.md).
8. Create `apps/api/tests/test_<id>_parser.py` and update frontend tests when
   necessary.

## Minimum Test Coverage

Backend tests for a new source should verify that:

- every page and listing record is collected even with a small `results_limit`;
- the API payload or HTML is correctly normalized into `ParsedJob`;
- detail pages enrich the description, location, dates, and application URL;
- an individual detail-page failure preserves the basic vacancy when safe;
- a malformed listing payload becomes `DirectCompanyRequestError`;
- `max_pages` prevents silent catalog truncation;
- the parser is created through the shared runner;
- a stored vacancy receives `logo == "company"`, the correct department, and an
  ID with the source prefix.

Frontend tests should verify that the company is available in the Direct
Companies selector and that a vacancy with ID `<id>-...` displays the expected
logo and alt text.

Useful commands from the repository root:

```bash
cd apps/api && python -m pytest --quiet tests/test_<id>_parser.py
cd apps/api && python -m ruff check app/services/parsers/companies/<id>.py tests/test_<id>_parser.py
pnpm --filter @rufina/web typecheck
pnpm --filter @rufina/web test
git diff --check
```

After implementation, run one live smoke test against the official site. Check
the number of listing records, normalized jobs, available descriptions and
application URLs, and verify that pagination terminates. A live test does not
replace deterministic tests using `httpx.MockTransport` or fake responses.

## Files Usually Changed

```text
apps/api/app/core/settings.py
apps/api/app/core/vacancy_sources.py
apps/api/app/services/parsers/companies/<id>.py
apps/api/tests/test_<id>_parser.py
apps/web/src/lib/direct-company-catalog.ts
apps/web/public/company-logos/<id>.svg
apps/web/src/app/page.test.tsx
docs/direct-companies.md
```

Do not modify dependency locks or constraints if the parser only uses the
existing `httpx` and `scrapling` dependencies. Do not duplicate AI filtering
inside a parser: its responsibility is to collect and normalize vacancies
completely and reliably. New-only detection, screening, persistence, and
matching belong to the shared pipeline.
