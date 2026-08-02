# Direct Companies

Direct Companies are vacancy sources connected directly to an employer's
official career page. They do not require Bright Data or another external
vacancy-search API key.

## Supported Sources

| Company | Career page | Integration |
| --- | --- | --- |
| SBB CFF FFS | [Open vacancies](https://company.sbb.ch/de/jobs-karriere/jobs/offene-stellen.html?startItem=1) | SBB job-filter API |
| Swisscom | [External careers](https://swisscom.wd103.myworkdayjobs.com/en-US/SwisscomExternalCareers) | Workday API, paginated in batches of 20 |

During a search, Rufina scans all vacancies exposed by the selected company
source. Already known vacancies are skipped; only new vacancies proceed to the
configured AI screening and matching pipeline.
