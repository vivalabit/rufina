# Direct Companies

Implementation details and instructions for adding another source are in
[`direct-company-parsers.md`](direct-company-parsers.md).

Direct Companies are vacancy sources connected directly to an employer's
official career page. They do not require Bright Data or another external
vacancy-search API key.

## Supported Sources

| Company     | Career page                                                                                    | Integration                              |
| ----------- | ---------------------------------------------------------------------------------------------- | ---------------------------------------- |
| SBB CFF FFS | [Open vacancies](https://company.sbb.ch/de/jobs-karriere/jobs/offene-stellen.html?startItem=1) | SBB job-filter API                       |
| Swisscom    | [External careers](https://swisscom.wd103.myworkdayjobs.com/en-US/SwisscomExternalCareers)     | Workday API, paginated in batches of 20  |
| Galaxus     | [Career page](https://jobs.migros.ch/de/unsere-unternehmen/galaxus/)                           | Migros Jobs server-rendered vacancy page |
| Die Post    | [Job search](https://job.post.ch/search?locale=en_US)                                          | Multilingual recruiting API, 10 per page |

During a search, Rufina scans all vacancies exposed by the selected company
source. Every result is saved in the private `discovered_vacancies` inventory
before screening. Unchanged vacancies reuse screening decisions, while only
`keep` vacancies are materialized in the user-facing job list. After a
successful complete scan, inventory vacancies no longer present in the company
catalog are marked inactive; failed or partial scans never mark them missing.
