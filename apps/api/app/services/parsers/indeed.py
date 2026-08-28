from typing import Any
from urllib.parse import quote, urlencode

from app.models.parsers import IndeedSearchRequest, ParsedJob
from app.services.parsers.linkedin import LinkedInJobsParser, first_present

INDEED_JOBS_DATASET_ID = "gd_l4dx9j9sscpvs7no2"

REMOTE_FILTERS = {
    "Remote only": "0kf:attr(DSQF7);",
    "Hybrid": "0kf:attr(PAXZC);",
}

EXPERIENCE_LEVELS = {
    "Entry level": "entry_level",
    "Associate": "mid_level",
    "Mid-Senior level": "mid_level",
    "Director": "senior_level",
}

JOB_TYPES = {
    "Full-time": "fulltime",
    "Part-time": "parttime",
    "Contract": "contract",
    "Internship": "internship",
}

DATE_POSTED = {
    "Past 24 hours": "1",
    "Past week": "7",
    "Past month": "30",
}

COUNTRY_DOMAINS = {
    "United Kingdom": "uk.indeed.com",
    "Germany": "de.indeed.com",
    "Switzerland": "ch.indeed.com",
}


class IndeedJobsParser(LinkedInJobsParser):
    """Collect Indeed jobs through the Bright Data Web Scraper API."""

    parser_id = "indeed"

    def __init__(
        self,
        *,
        api_key: str | None,
        api_url: str,
        dataset_id: str = INDEED_JOBS_DATASET_ID,
        timeout_seconds: float = 65.0,
    ) -> None:
        super().__init__(
            api_key=api_key,
            api_url=api_url,
            dataset_id=dataset_id,
            timeout_seconds=timeout_seconds,
        )

    @staticmethod
    def build_search_url(request: IndeedSearchRequest) -> str:
        params: dict[str, str] = {}
        if request.keywords.strip():
            params["q"] = request.keywords.strip()
        if request.location.strip():
            params["l"] = request.location.strip()
        elif request.country != "Any":
            params["l"] = request.country
        if request.remote in REMOTE_FILTERS:
            params["sc"] = REMOTE_FILTERS[request.remote]
        if request.experience_level in EXPERIENCE_LEVELS:
            params["explvl"] = EXPERIENCE_LEVELS[request.experience_level]
        if request.job_type in JOB_TYPES:
            params["jt"] = JOB_TYPES[request.job_type]
        if request.date_posted in DATE_POSTED:
            params["fromage"] = DATE_POSTED[request.date_posted]

        domain = COUNTRY_DOMAINS.get(request.country, "www.indeed.com")
        query = urlencode(params)
        return f"https://{domain}/jobs?{query}" if query else f"https://{domain}/jobs"

    @staticmethod
    def build_search_input(request: IndeedSearchRequest, search_url: str) -> dict[str, Any]:
        return {"url": search_url}

    def build_trigger_params(self, request: IndeedSearchRequest) -> dict[str, Any]:
        del request
        return {
            "dataset_id": self.dataset_id,
            "type": "discover_new",
            "discover_by": "url",
            "format": "json",
            "include_errors": "true",
        }

    def build_trigger_payload(
        self,
        request: IndeedSearchRequest,
        search_url: str,
    ) -> list[dict[str, Any]]:
        return [self.build_search_input(request, search_url)]

    @staticmethod
    def normalize_job(record: dict[str, Any]) -> ParsedJob:
        job_id = first_present(record, "jobid", "job_id", "job_key", "jk")
        url = first_present(
            record,
            "url",
            "job_url",
            "job_posting_url",
            "indeed_job_url",
            "input_url",
        )
        if not url and job_id:
            url = f"https://www.indeed.com/viewjob?jk={quote(job_id, safe='')}"

        return ParsedJob(
            source="indeed",
            title=first_present(record, "job_title", "title", "name"),
            company=first_present(record, "company_name", "company", "company_title"),
            location=first_present(
                record,
                "location",
                "job_location",
                "formatted_location",
                "location_text",
            ),
            url=url,
            apply_url=first_present(
                record,
                "apply_url",
                "apply_link",
                "job_apply_url",
                "external_apply_link",
            )
            or url,
            posted_at=first_present(
                record,
                "date_posted_parsed",
                "date_posted",
                "posted_at",
                "job_posted_date",
            ),
            employment_type=first_present(
                record,
                "job_type",
                "employment_type",
                "job_employment_type",
            ),
            seniority=first_present(record, "experience_level", "seniority"),
            description=first_present(
                record,
                "description_text",
                "description",
                "job_description",
                "job_summary",
            ),
            raw=record,
        )
