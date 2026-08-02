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
