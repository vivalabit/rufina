from typing import Any, Literal

from pydantic import BaseModel, Field

RemoteFilter = Literal["Any", "Remote only", "Hybrid", "On-site"]
ExperienceLevel = Literal["Any", "Entry level", "Associate", "Mid-Senior level", "Director"]
JobType = Literal["Any", "Full-time", "Part-time", "Contract", "Internship"]
DatePosted = Literal["Any time", "Past 24 hours", "Past week", "Past month"]
LinkedInDiscoveryExperienceLevel = Literal[
    "Entry level",
    "Internship",
    "Associate",
    "Mid-Senior level",
    "Director",
    "Executive",
]


class LinkedInDiscoveryQuery(BaseModel):
    keyword: str = Field(min_length=1, max_length=160)
    experience_levels: list[LinkedInDiscoveryExperienceLevel] = Field(
        default_factory=list,
        max_length=6,
    )
    job_type: JobType | None = None
    selective_search: bool = True


class LinkedInSearchRequest(BaseModel):
    keywords: str = Field(default="", max_length=2000)
    location: str = Field(default="", max_length=160)
    remote: RemoteFilter = "Any"
    experience_level: ExperienceLevel = "Any"
    job_type: JobType = "Any"
    date_posted: DatePosted = "Any time"
    results_limit: int = Field(default=100, ge=1, le=1000)
    country: str = Field(default="Any", max_length=80)
    deduplicate: bool = True
    linkedin_queries: list[LinkedInDiscoveryQuery] = Field(
        default_factory=list,
        max_length=80,
    )
    limit_per_input: int = Field(default=25, ge=1, le=1000)
    search_name: str = Field(default="", max_length=160)
    folder: str = Field(default="", max_length=120)


class IndeedSearchRequest(LinkedInSearchRequest):
    """Indeed supports the same user-facing search filters as LinkedIn."""


class JobsChSearchRequest(LinkedInSearchRequest):
    """Rufina search fields accepted by the jobs.ch source."""


class ParsedJob(BaseModel):
    source: str = "linkedin"
    title: str | None = None
    company: str | None = None
    location: str | None = None
    url: str | None = None
    apply_url: str | None = None
    posted_at: str | None = None
    employment_type: str | None = None
    seniority: str | None = None
    description: str | None = None
    salary: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    salary_unit: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ParserSearchResponse(BaseModel):
    parser: str
    status: Literal["completed", "queued", "running"]
    search_url: str
    jobs: list[ParsedJob] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    snapshot_id: str | None = None
    message: str | None = None
