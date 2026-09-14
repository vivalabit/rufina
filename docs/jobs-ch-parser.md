# jobs.ch search

The jobs.ch source reads public search pages and structured vacancy details. It
does not require a Bright Data key. Keywords containing `OR` are searched
separately, in parallel; duplicate vacancy IDs are removed before detail requests.
Results from the terms are interleaved so one broad term does not consume the
entire result limit.

The result limit counts vacancies after date validation, detail enrichment, and
URL deduplication. If a candidate is excluded, the parser first uses remaining
rows on the downloaded pages, then continues pagination. Freshness uses the
initial publication date when valid, falling back to the detail/listing date.
The reference time is fixed at the beginning of the search.

## Filters

| Filter | Behavior |
| --- | --- |
| Keywords, location | Sent to jobs.ch |
| Date posted | Sent to jobs.ch and checked locally |
| Experience level | Applied by the application's screening stage; combined with search and global vacancy rules |
| Remote, job type | Not supported by this parser; disabled in the jobs.ch configuration UI |
| Country | No separate country restriction; use a jobs.ch location. `Any` and `Switzerland` retain the existing search behavior |

Saved unsupported filters remain visible and produce a warning. The direct
`/parsers/jobs_ch/search` endpoint returns parsed candidates without application
screening, so its experience-level parameter is also reported as unsupported.

## Partial results and limits

Temporary HTTP failures receive bounded retries. `Retry-After` is respected;
when the requested wait is too long for a short retry or the remaining search
budget, the request is reported as incomplete. Missing vacancies (404) are not
retried. The source runner does not restart the entire jobs.ch search after its
internal retry budget is exhausted.

The parser retains listing data if details cannot be loaded, and reports missing
structured details, failed queries/pages, repeated pages, and safety limits in
`ParserSearchResponse.warnings`. A changed search-page structure is an error,
not a successful empty search. The application retains warnings in the search
run and displays incomplete searches with `partial` status. Unsupported filter
notices alone do not mark an otherwise successful run partial.

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `JOBS_CH_TIMEOUT_SECONDS` | 30 | Timeout for an HTTP operation |
| `JOBS_CH_MAX_PAGES` | 50 | Maximum pages per keyword |
| `JOBS_CH_DETAIL_WORKERS` | 6 | Concurrent search/detail requests |
| `JOBS_CH_DEADLINE_SECONDS` | 150 | Search budget; queued work and retries respect the remaining time |
| `JOBS_CH_MAX_RETRIES` | 2 | Additional attempts per transiently failed request |

An already executing HTTP operation is governed by its timeout. These limits do
not include subsequent application screening or AI Match.

## Repeated screening

For a global rolling age filter, the application rechecks the vacancy's age
before consulting cached AI decisions. A fixed ISO publication date permits
reuse of the stable role/technology decision across runs. The window length and
other criteria, vacancy content, model, and prompt version remain part of cache
identity. Relative or unknown dates and explicitly supplied absolute cutoffs
retain their exact date-dependent identity. Time-dependent deterministic age
decisions are kept separate from stable AI decisions.

Existing vacancies and their import provenance are not rewritten by these
changes. New imports record the actual source-specific screening policy.
