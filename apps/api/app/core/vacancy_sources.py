from dataclasses import dataclass

AGGREGATOR_SOURCE_IDS = ("linkedin", "indeed", "jobs_ch")


@dataclass(frozen=True)
class DirectCompanyParserDefinition:
    """Declarative registration for one official company career-page parser."""

    id: str
    name: str
    careers_url: str
    parser_path: str
    settings_map: tuple[tuple[str, str], ...] = ()
    full_catalog: bool = True


# Keep company-specific imports out of the central search runner. Adding a company
# only requires its parser module and one lightweight catalog registration here.
DIRECT_COMPANY_PARSERS = (
    DirectCompanyParserDefinition(
        id="sbb",
        name="SBB CFF FFS",
        careers_url=(
            "https://company.sbb.ch/de/jobs-karriere/jobs/offene-stellen.html?startItem=1"
        ),
        parser_path="app.services.parsers.companies.sbb:SbbJobsParser",
        settings_map=(
            ("base_url", "sbb_jobs_base_url"),
            ("timeout_seconds", "sbb_jobs_timeout_seconds"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="swisscom",
        name="Swisscom",
        careers_url=(
            "https://swisscom.wd103.myworkdayjobs.com/en-US/"
            "SwisscomExternalCareers"
        ),
        parser_path=(
            "app.services.parsers.companies.swisscom:SwisscomJobsParser"
        ),
        settings_map=(
            ("base_url", "swisscom_jobs_base_url"),
            ("timeout_seconds", "swisscom_jobs_timeout_seconds"),
            ("max_pages", "swisscom_jobs_max_pages"),
            ("detail_workers", "swisscom_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="galaxus",
        name="Galaxus",
        careers_url="https://jobs.migros.ch/de/unsere-unternehmen/galaxus/",
        parser_path="app.services.parsers.companies.galaxus:GalaxusJobsParser",
        settings_map=(
            ("base_url", "galaxus_jobs_base_url"),
            ("timeout_seconds", "galaxus_jobs_timeout_seconds"),
            ("detail_workers", "galaxus_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="migros_bank",
        name="Migros Bank",
        careers_url=(
            "https://jobs.migros.ch/de/unsere-unternehmen/"
            "migros-bank/offene-stellen"
        ),
        parser_path=(
            "app.services.parsers.companies.migros_bank:MigrosBankJobsParser"
        ),
        settings_map=(
            ("base_url", "migros_bank_jobs_base_url"),
            ("timeout_seconds", "migros_bank_jobs_timeout_seconds"),
            ("detail_workers", "migros_bank_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="die_post",
        name="Die Post",
        careers_url="https://job.post.ch/search?locale=en_US",
        parser_path="app.services.parsers.companies.die_post:DiePostJobsParser",
        settings_map=(
            ("base_url", "die_post_jobs_base_url"),
            ("timeout_seconds", "die_post_jobs_timeout_seconds"),
            ("max_pages", "die_post_jobs_max_pages"),
            ("max_catalog_passes", "die_post_jobs_max_catalog_passes"),
            ("detail_workers", "die_post_jobs_detail_workers"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="raiffeisen",
        name="Raiffeisen",
        careers_url="https://jobs.raiffeisen.ch/",
        parser_path=(
            "app.services.parsers.companies.raiffeisen:RaiffeisenJobsParser"
        ),
        settings_map=(
            ("base_url", "raiffeisen_jobs_base_url"),
            ("api_url", "raiffeisen_jobs_api_url"),
            ("timeout_seconds", "raiffeisen_jobs_timeout_seconds"),
            ("max_pages", "raiffeisen_jobs_max_pages"),
            ("max_catalog_passes", "raiffeisen_jobs_max_catalog_passes"),
        ),
    ),
    DirectCompanyParserDefinition(
        id="bundesverwaltung",
        name="Bundesverwaltung",
        careers_url="https://jobs.admin.ch/?lang=de",
        parser_path=(
            "app.services.parsers.companies.bundesverwaltung:"
            "BundesverwaltungJobsParser"
        ),
        settings_map=(
            ("base_url", "bundesverwaltung_jobs_base_url"),
            ("api_url", "bundesverwaltung_jobs_api_url"),
            ("timeout_seconds", "bundesverwaltung_jobs_timeout_seconds"),
            ("max_pages", "bundesverwaltung_jobs_max_pages"),
            (
                "max_catalog_passes",
                "bundesverwaltung_jobs_max_catalog_passes",
            ),
        ),
    ),
)

DIRECT_COMPANY_SOURCE_IDS = tuple(item.id for item in DIRECT_COMPANY_PARSERS)
SUPPORTED_VACANCY_SOURCE_IDS = (
    *AGGREGATOR_SOURCE_IDS,
    *DIRECT_COMPANY_SOURCE_IDS,
)


def direct_company_definition(source_id: str) -> DirectCompanyParserDefinition | None:
    return next(
        (item for item in DIRECT_COMPANY_PARSERS if item.id == source_id),
        None,
    )


def is_direct_company_source(source_id: str) -> bool:
    return source_id in DIRECT_COMPANY_SOURCE_IDS
