# Direct Companies

Implementation details and instructions for adding another source are in
[`direct-company-parsers.md`](direct-company-parsers.md).

Direct Companies are vacancy sources connected directly to an employer's
official career page. They do not require Bright Data or another external
vacancy-search API key.

## Supported Sources

| Company          | Career page                                                                                    | Integration                              |
| ---------------- | ---------------------------------------------------------------------------------------------- | ---------------------------------------- |
| SBB CFF FFS      | [Open vacancies](https://company.sbb.ch/de/jobs-karriere/jobs/offene-stellen.html?startItem=1) | SBB job-filter API                       |
| Swisscom         | [External careers](https://swisscom.wd103.myworkdayjobs.com/en-US/SwisscomExternalCareers)     | Workday API, paginated in batches of 20  |
| Galaxus          | [Career page](https://jobs.migros.ch/de/unsere-unternehmen/galaxus/)                           | Migros Jobs server-rendered vacancy page |
| Migros Bank      | [Open vacancies](https://jobs.migros.ch/de/unsere-unternehmen/migros-bank/offene-stellen)      | Migros Jobs server-rendered vacancy page |
| Die Post         | [Job search](https://job.post.ch/search?locale=en_US)                                          | Multilingual recruiting API, 10 per page |
| Raiffeisen       | [Job search](https://jobs.raiffeisen.ch/)                                                      | Prospective JSON API, 96 per page        |
| Bundesverwaltung | [Stellenportal Bund](https://jobs.admin.ch/?lang=de)                                           | Prospective JSON API, 96 per page        |
| AXA Schweiz      | [Swiss vacancies](https://careers.axa.com/careers-home/jobs?country=Switzerland&page=1)        | iCIMS/Jibe JSON API, 100 per page        |
| Sunrise          | [Job openings](https://careers.sunrise.ch/gb/en/search-results)                                | Phenom server-rendered catalog, 10/page  |
| ISS Schweiz      | [Open positions](https://www.ch.issworld.com/de-ch/karriere/offene-stellen)                    | Solique full-catalog JSON API            |
| Accenture        | [Job search](https://www.accenture.com/ch-en/careers/jobsearch)                                | Accenture Elastic Jobs API, 100/page     |
| CSEM             | [Jobs](https://www.csem.ch/en/jobs/)                                                           | Server-rendered HTML and detail pages    |
| Deloitte         | [CH Careers](https://apply.deloitte.ch/CHCareers/)                                             | Avature server-rendered catalog, 6/page  |
| Zürcher Kantonalbank | [Open positions](https://apply.refline.ch/792841/search.html)                              | Refline full-catalog HTML table          |

During a search, Rufina scans all vacancies exposed by the selected company
source. Every result is saved in the private `discovered_vacancies` inventory
before screening. The common experience-level filter applies to Direct
Companies in the same way as LinkedIn, Indeed, and jobs.ch. Unchanged vacancies
reuse screening decisions, while only `keep` vacancies are materialized in the
user-facing job list. After a successful complete scan, inventory vacancies no
longer present in the company
catalog are marked inactive; failed or partial scans never mark them missing.
