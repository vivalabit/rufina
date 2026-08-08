from __future__ import annotations

import httpx

from app.models.parsers import LinkedInSearchRequest, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.galaxus import (
    GALAXUS_HEADERS,
    GalaxusJobsParser,
    GalaxusParseError,
    deduplicate_galaxus_jobs,
    parse_listing_html,
)

MIGROS_BANK_CAREERS_URL = (
    "https://jobs.migros.ch/de/unsere-unternehmen/migros-bank"
)
MIGROS_BANK_JOBS_URL = f"{MIGROS_BANK_CAREERS_URL}/offene-stellen"


class MigrosBankJobsParser(GalaxusJobsParser):
    """Collect all Migros Bank jobs from the shared Migros Jobs platform."""

    parser_id = "migros_bank"

    def __init__(
        self,
        *,
        base_url: str = MIGROS_BANK_JOBS_URL,
        timeout_seconds: float = 30.0,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            detail_workers=detail_workers,
            transport=transport,
        )

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers=GALAXUS_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.base_url)
                response.raise_for_status()
                records = parse_listing_html(
                    response.text,
                    page_url=str(response.url),
                    company_slug="migros-bank",
                    company_name="Migros Bank",
                )
                self.enrich_records(client, records)
        except GalaxusParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError(
                "Migros Bank vacancy request failed"
            ) from exc
        except Exception as exc:
            raise DirectCompanyRequestError(
                "Migros Bank vacancy parsing failed"
            ) from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_galaxus_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=f"Scanned {len(jobs)} Migros Bank vacancies from one page",
        )
