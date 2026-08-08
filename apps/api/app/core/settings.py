from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    app_env: str = "local"
    database_url: str = "postgresql+psycopg://tasko:tasko@localhost:5432/tasko"
    redis_url: str = "redis://localhost:6379/0"
    ai_backend_mode: Literal["openclaw_codex", "openai_api"] = Field(
        default="openclaw_codex",
        validation_alias=AliasChoices("AI_BACKEND", "AI_BACKEND_MODE"),
    )
    openai_api_key: str = ""
    openai_api_base_url: str = "https://api.openai.com/v1"
    openai_api_model: str = "gpt-5.6-terra"
    openai_api_reasoning_effort: Literal[
        "none", "low", "medium", "high", "xhigh", "max"
    ] = "medium"
    openai_api_timeout_seconds: int = Field(default=120, ge=10, le=600)
    openai_api_max_attempts: int = Field(default=2, ge=1, le=4)
    openai_api_retry_backoff_seconds: float = Field(default=0.8, ge=0, le=10)
    openclaw_resume_import_enabled: bool = True
    openclaw_command: str = "openclaw"
    openclaw_agent_id: str = "rufina-assistant"
    openclaw_resume_import_thinking: str = "high"
    openclaw_resume_import_timeout_seconds: int = 120
    openclaw_resume_tailoring_enabled: bool = True
    openclaw_resume_tailoring_model: str = "openai/gpt-5.6-terra"
    openclaw_resume_tailoring_thinking: str = "high"
    openclaw_resume_tailoring_timeout_seconds: int = Field(
        default=120,
        ge=10,
        le=600,
    )
    openclaw_ai_match_enabled: bool = True
    openclaw_ai_match_model: str = "openai/gpt-5.6-terra"
    # The default OpenClaw matching model does not expose reasoning levels.
    # Passing "low" makes OpenClaw reject the request before generation starts.
    openclaw_ai_match_thinking: str = "off"
    openclaw_ai_match_timeout_seconds: int = 120
    openclaw_ai_match_max_jobs: int = 1
    openclaw_ai_match_max_attempts: int = Field(default=2, ge=1, le=4)
    ai_match_model: str | None = Field(default=None, min_length=1, max_length=256)
    ai_match_reasoning: Literal[
        "off", "none", "low", "medium", "high", "xhigh", "max"
    ] | None = None
    ai_match_batch_size: int | None = Field(default=None, ge=1, le=100)
    ai_match_timeout_seconds: int | None = Field(default=None, ge=10, le=600)
    ai_match_max_attempts: int | None = Field(default=None, ge=1, le=4)
    job_screening_model: str = Field(
        default="openai/gpt-5.6-luna",
        min_length=1,
        max_length=256,
    )
    job_screening_reasoning: Literal[
        "off", "none", "low", "medium", "high", "xhigh", "max"
    ] = "off"
    job_screening_batch_size: int = Field(default=10, ge=1, le=100)
    job_screening_timeout_seconds: int = Field(default=60, ge=10, le=600)
    job_screening_max_attempts: int = Field(default=2, ge=1, le=4)
    job_screening_max_description_chars: int = Field(
        default=12_000,
        ge=1_000,
        le=200_000,
    )
    openclaw_assistant_enabled: bool = True
    openclaw_assistant_agent_id: str = "rufina-assistant"
    openclaw_assistant_model: str = "openai/gpt-5.6-terra"
    ai_provider_name: str = "OpenAI"
    ai_consent_version: str = "2026-07-18.v2"
    storage_cleanup_interval_seconds: int = Field(default=300, ge=1, le=86_400)
    openclaw_assistant_thinking: str = "off"
    openclaw_assistant_timeout_seconds: int = Field(default=120, ge=10, le=600)
    openclaw_assistant_max_attempts: int = Field(default=2, ge=1, le=4)
    openclaw_assistant_retry_backoff_seconds: float = Field(default=0.8, ge=0, le=10)
    openclaw_assistant_max_prompt_chars: int = Field(default=48_000, ge=4_000, le=200_000)
    openclaw_assistant_max_user_message_chars: int = Field(default=6_000, ge=200, le=12_000)
    openclaw_assistant_max_history_messages: int = Field(default=12, ge=0, le=100)
    openclaw_assistant_max_history_chars: int = Field(default=8_000, ge=0, le=100_000)
    brightdata_api_key: str | None = None
    brightdata_api_url: str = "https://api.brightdata.com/datasets/v3"
    brightdata_linkedin_jobs_dataset_id: str = "gd_lpfll7v5hcqtkxl6l"
    brightdata_indeed_jobs_dataset_id: str = "gd_l4dx9j9sscpvs7no2"
    brightdata_snapshot_poll_interval_seconds: float = Field(
        default=1.0,
        ge=0.1,
        le=30,
    )
    brightdata_snapshot_poll_timeout_seconds: float = Field(
        default=30.0,
        ge=0,
        le=600,
    )
    jobs_ch_base_url: str = "https://www.jobs.ch"
    jobs_ch_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    jobs_ch_max_pages: int = Field(default=50, ge=1, le=100)
    jobs_ch_detail_workers: int = Field(default=6, ge=1, le=20)
    sbb_jobs_base_url: str = (
        "https://company.sbb.ch/de/jobs-karriere/jobs/"
        "offene-stellen.html"
    )
    sbb_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    swisscom_jobs_base_url: str = (
        "https://swisscom.wd103.myworkdayjobs.com/en-US/"
        "SwisscomExternalCareers"
    )
    swisscom_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    swisscom_jobs_max_pages: int = Field(default=100, ge=1, le=500)
    swisscom_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    galaxus_jobs_base_url: str = (
        "https://jobs.migros.ch/de/unsere-unternehmen/galaxus/offene-stellen"
    )
    galaxus_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    galaxus_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    migros_bank_jobs_base_url: str = (
        "https://jobs.migros.ch/de/unsere-unternehmen/migros-bank/offene-stellen"
    )
    migros_bank_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    migros_bank_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    die_post_jobs_base_url: str = "https://job.post.ch/search?locale=en_US"
    die_post_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    die_post_jobs_max_pages: int = Field(default=100, ge=1, le=500)
    die_post_jobs_max_catalog_passes: int = Field(default=6, ge=1, le=20)
    die_post_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    raiffeisen_jobs_base_url: str = "https://jobs.raiffeisen.ch/"
    raiffeisen_jobs_api_url: str = (
        "https://ohws.prospective.ch/public/v1/medium/1950/jobs"
    )
    raiffeisen_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    raiffeisen_jobs_max_pages: int = Field(default=100, ge=1, le=500)
    raiffeisen_jobs_max_catalog_passes: int = Field(default=3, ge=1, le=20)
    bundesverwaltung_jobs_base_url: str = "https://jobs.admin.ch/?lang=de"
    bundesverwaltung_jobs_api_url: str = (
        "https://ohws.prospective.ch/public/v1/medium/1000624/jobs"
    )
    bundesverwaltung_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    bundesverwaltung_jobs_max_pages: int = Field(default=100, ge=1, le=500)
    bundesverwaltung_jobs_max_catalog_passes: int = Field(
        default=3,
        ge=1,
        le=20,
    )
    axa_schweiz_jobs_base_url: str = (
        "https://careers.axa.com/careers-home/jobs?country=Switzerland&page=1"
    )
    axa_schweiz_jobs_api_url: str = "https://careers.axa.com/api/jobs"
    axa_schweiz_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    axa_schweiz_jobs_max_pages: int = Field(default=100, ge=1, le=500)
    axa_schweiz_jobs_max_catalog_passes: int = Field(
        default=3,
        ge=1,
        le=20,
    )
    sunrise_jobs_base_url: str = (
        "https://careers.sunrise.ch/gb/en/search-results"
    )
    sunrise_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    sunrise_jobs_max_pages: int = Field(default=100, ge=1, le=500)
    sunrise_jobs_max_catalog_passes: int = Field(default=3, ge=1, le=20)
    sunrise_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    iss_jobs_base_url: str = (
        "https://www.ch.issworld.com/de-ch/karriere/offene-stellen"
    )
    iss_jobs_api_url: str = "https://live.solique.ch/ISS/de/ajax/"
    iss_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    iss_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    accenture_jobs_base_url: str = (
        "https://www.accenture.com/ch-en/careers/jobsearch"
    )
    accenture_jobs_api_url: str = (
        "https://www.accenture.com/api/accenture/elastic/findjobs"
    )
    accenture_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    accenture_jobs_max_pages: int = Field(default=100, ge=1, le=500)
    csem_jobs_base_url: str = "https://www.csem.ch/en/jobs/"
    csem_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    csem_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    deloitte_jobs_base_url: str = "https://apply.deloitte.ch/CHCareers/"
    deloitte_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    deloitte_jobs_max_pages: int = Field(default=100, ge=1, le=500)
    deloitte_jobs_max_catalog_passes: int = Field(default=3, ge=1, le=20)
    deloitte_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    zuercher_kantonalbank_jobs_base_url: str = (
        "https://apply.refline.ch/792841/search.html"
    )
    zuercher_kantonalbank_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    zuercher_kantonalbank_jobs_detail_workers: int = Field(
        default=8,
        ge=1,
        le=20,
    )
    flughafen_zuerich_jobs_base_url: str = (
        "https://www.flughafen-zuerich.ch/de/unternehmen/jobs/karriere/stellenangebote"
    )
    flughafen_zuerich_jobs_api_url: str = (
        "https://www.flughafen-zuerich.ch/api/jobs/jobs?"
        "sc_site=dxp-portal&sc_lang=de&"
        "sc_itemid=%7b264461F0-4A00-4CF0-8B38-D24541D30C92%7d"
    )
    flughafen_zuerich_jobs_api_key: str = (
        "{3DCC43C7-A5C3-4A72-8CA5-A343CFD63F34}"
    )
    flughafen_zuerich_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    flughafen_zuerich_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    job_search_poll_interval_seconds: float = Field(default=30.0, ge=1, le=300)
    resume_template_preview_max_payload_bytes: int = Field(
        default=8_192,
        ge=512,
        le=65_536,
    )
    resume_template_preview_rate_limit: int = Field(
        default=10,
        ge=1,
        le=100,
    )
    resume_template_preview_rate_window_seconds: int = Field(
        default=60,
        ge=1,
        le=3_600,
    )
    resume_template_thumbnail_rate_limit: int = Field(
        default=60,
        ge=1,
        le=500,
    )
    resume_template_thumbnail_rate_window_seconds: int = Field(
        default=60,
        ge=1,
        le=3_600,
    )
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:3001"]
    cors_origin_regex: str = (
        r"^http://(localhost|127\.0\.0\.1|0\.0\.0\.0|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
        r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}):300[01]$"
    )

    def ai_reasoning_for(self, openclaw_reasoning: str) -> str:
        return (
            self.openai_api_reasoning_effort
            if self.ai_backend_mode == "openai_api"
            else openclaw_reasoning
        )

    def ai_timeout_for(self, openclaw_timeout_seconds: int) -> int:
        return (
            self.openai_api_timeout_seconds
            if self.ai_backend_mode == "openai_api"
            else openclaw_timeout_seconds
        )

    def ai_max_attempts_for(self, openclaw_max_attempts: int) -> int:
        return (
            self.openai_api_max_attempts
            if self.ai_backend_mode == "openai_api"
            else openclaw_max_attempts
        )

    def ai_retry_backoff_for(self, openclaw_retry_backoff_seconds: float) -> float:
        return (
            self.openai_api_retry_backoff_seconds
            if self.ai_backend_mode == "openai_api"
            else openclaw_retry_backoff_seconds
        )

    def normalize_reasoning_for_backend(self, reasoning: str) -> str:
        if reasoning == "none":
            return "off"
        return reasoning

    def ai_match_model_value(self) -> str:
        if self.ai_match_model:
            return self.ai_match_model
        return (
            self.openai_api_model
            if self.ai_backend_mode == "openai_api"
            else self.openclaw_ai_match_model
        )

    def ai_match_reasoning_value(self) -> str:
        reasoning = self.ai_match_reasoning or self.ai_reasoning_for(
            self.openclaw_ai_match_thinking
        )
        return self.normalize_reasoning_for_backend(reasoning)

    def ai_match_batch_size_value(self) -> int:
        return self.ai_match_batch_size or self.openclaw_ai_match_max_jobs

    def ai_match_timeout_seconds_value(self) -> int:
        return self.ai_match_timeout_seconds or self.ai_timeout_for(
            self.openclaw_ai_match_timeout_seconds
        )

    def ai_match_max_attempts_value(self) -> int:
        return self.ai_match_max_attempts or self.ai_max_attempts_for(
            self.openclaw_ai_match_max_attempts
        )

    @model_validator(mode="after")
    def require_openai_key_for_direct_backend(self) -> "Settings":
        if self.ai_backend_mode == "openai_api" and not self.openai_api_key.strip():
            raise ValueError("OPENAI_API_KEY is required when AI_BACKEND=openai_api")
        return self

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
