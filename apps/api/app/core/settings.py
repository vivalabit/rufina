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
    bundesverwaltung_jobs_base_url: str = (
        "https://jobs.admin.ch/?lang=de&f=verwaltungseinheit:36497&intranet=1"
    )
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
    ubs_students_graduates_jobs_base_url: str = (
        "https://jobs.ubs.com/TGnewUI/Search/home/HomeWithPreLoad?"
        "partnerid=25008&siteid=5131&PageType=searchResults&"
        "SearchType=linkquery&LinkID=15232"
        "#keyWordSearch=&locationSearch=Switzerland"
    )
    ubs_students_graduates_jobs_api_url: str = (
        "https://jobs.ubs.com/TgNewUI/Search/Ajax/ProcessSortAndShowMoreJobs"
    )
    ubs_students_graduates_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    ubs_students_graduates_jobs_max_pages: int = Field(default=10, ge=1, le=100)
    ubs_students_graduates_jobs_detail_workers: int = Field(
        default=8,
        ge=1,
        le=20,
    )
    abb_switzerland_jobs_base_url: str = (
        "https://careers.abb/global/en/search-results?"
        "rk=l-abb-switzerland-careers&sortBy=Most%20relevant"
    )
    abb_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    abb_switzerland_jobs_max_pages: int = Field(default=100, ge=1, le=500)
    abb_switzerland_jobs_max_catalog_passes: int = Field(default=3, ge=1, le=20)
    abb_switzerland_jobs_page_workers: int = Field(default=10, ge=1, le=20)
    abb_switzerland_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    huawei_switzerland_jobs_base_url: str = "https://careers.huaweirc.ch/jobs"
    huawei_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    huawei_switzerland_jobs_detail_workers: int = Field(
        default=8,
        ge=1,
        le=20,
    )
    bdo_switzerland_jobs_base_url: str = (
        "https://www.bdo.ch/en-gb/careers/open-jobs"
    )
    bdo_switzerland_jobs_api_url: str = (
        "https://api.jobportal.abaservices.ch/api/extern/v1/job-portal/"
        "3505fa5b-0c08-49ef-852b-1a20eab2630e/publications"
    )
    bdo_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    endress_hauser_switzerland_jobs_base_url: str = (
        "https://careers.endress.com/Switzerland/content/search/?locale=en_US&"
        "currentPage=1&pageSize=20&addresses%2Fcountry=Switzerland&"
        "orderBy=datePosted&isDesc=true"
    )
    endress_hauser_switzerland_jobs_api_url: str = (
        "https://production.api.recruiting-solutions.org/search"
    )
    endress_hauser_switzerland_jobs_customer_id: str = "eh-prod"
    endress_hauser_switzerland_jobs_api_key: str = (
        "pk_eh-prod_jOlkBMdFBQyRACdPXssVQNAFmWJNbaNarAjCPCXrprNXxKZdIGEsSYHHT"
        "ThgplaXCvIDHKCibUgkuzwiyqDiBazfQsNnrQRx"
    )
    endress_hauser_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    endress_hauser_switzerland_jobs_max_pages: int = Field(
        default=100,
        ge=1,
        le=500,
    )
    microsoft_switzerland_jobs_base_url: str = (
        "https://apply.careers.microsoft.com/careers?start=0&"
        "location=Switzerland%2C+Z%C3%BCrich%2C+Z%C3%BCrich&"
        "pid=1970393556942270&sort_by=distance&filter_distance=160&"
        "filter_include_remote=1&filter_include_relocation=0"
    )
    microsoft_switzerland_jobs_api_url: str = (
        "https://apply.careers.microsoft.com/api/pcsx/search"
    )
    microsoft_switzerland_jobs_detail_api_url: str = (
        "https://apply.careers.microsoft.com/api/pcsx/position_details"
    )
    microsoft_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    microsoft_switzerland_jobs_max_pages: int = Field(
        default=100,
        ge=1,
        le=500,
    )
    microsoft_switzerland_jobs_detail_workers: int = Field(
        default=8,
        ge=1,
        le=20,
    )
    sap_switzerland_jobs_base_url: str = (
        "https://jobs.sap.com/go/SAP-Jobs-in-Switzerland/915101/"
    )
    sap_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    sap_switzerland_jobs_max_pages: int = Field(default=20, ge=1, le=100)
    sap_switzerland_jobs_max_catalog_passes: int = Field(default=3, ge=1, le=20)
    sap_switzerland_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    s_peers_jobs_base_url: str = (
        "https://s-peers.com/karriere-jobs/stellenausschreibungen/"
    )
    s_peers_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    s_peers_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    mobiliar_jobs_base_url: str = "https://jobs.mobiliar.ch/go/Jobs/506974/"
    mobiliar_jobs_api_url: str = (
        "https://jobs.mobiliar.ch/services/recruiting/v1/jobs"
    )
    mobiliar_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    mobiliar_jobs_max_pages: int = Field(default=20, ge=1, le=100)
    mobiliar_jobs_max_catalog_passes: int = Field(default=5, ge=1, le=20)
    mobiliar_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    emmi_jobs_base_url: str = (
        "https://group.emmi.com/che/de/arbeiten-bei-emmi/offene-stellen"
    )
    emmi_jobs_api_url: str = (
        "https://ohws.prospective.ch/public/v1/medium/1003228/jobs"
    )
    emmi_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    emmi_jobs_max_pages: int = Field(default=50, ge=1, le=200)
    emmi_jobs_max_catalog_passes: int = Field(default=3, ge=1, le=20)
    sulzer_switzerland_jobs_base_url: str = (
        "https://sulzer.wd502.myworkdayjobs.com/SulzerJobs?"
        "locationcountry=187134fccb084a0ea9b4b95f23890dbe"
    )
    sulzer_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    sulzer_switzerland_jobs_max_pages: int = Field(default=100, ge=1, le=500)
    sulzer_switzerland_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    siegfried_jobs_base_url: str = (
        "https://siegfried.wd103.myworkdayjobs.com/external"
    )
    siegfried_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    siegfried_jobs_max_pages: int = Field(default=100, ge=1, le=500)
    siegfried_jobs_max_catalog_passes: int = Field(default=3, ge=1, le=20)
    siegfried_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    switch_jobs_base_url: str = (
        "https://recruitingapp-2563.umantis.com/Jobs/1?lang=ger"
    )
    switch_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    switch_jobs_max_pages: int = Field(default=50, ge=1, le=200)
    switch_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    huber_suhner_switzerland_jobs_base_url: str = (
        "https://recruiting.hubersuhner.com/Jobs/All"
    )
    huber_suhner_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    huber_suhner_switzerland_jobs_max_pages: int = Field(
        default=20,
        ge=1,
        le=100,
    )
    huber_suhner_switzerland_jobs_detail_workers: int = Field(
        default=8,
        ge=1,
        le=20,
    )
    stadler_it_switzerland_jobs_base_url: str = (
        "https://www.stadlerrail.com/de/karriere/offene-stellen"
        "?10=1077445&25=1098730&"
    )
    stadler_it_switzerland_jobs_catalog_url: str = (
        "https://ohws.prospective.ch/public/v1/careercenter/1000470/"
    )
    stadler_it_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    stadler_it_switzerland_jobs_max_pages: int = Field(
        default=20,
        ge=1,
        le=100,
    )
    stadler_it_switzerland_jobs_max_catalog_passes: int = Field(
        default=3,
        ge=1,
        le=20,
    )
    stadler_it_switzerland_jobs_detail_workers: int = Field(
        default=8,
        ge=1,
        le=20,
    )
    ebp_switzerland_jobs_base_url: str = (
        "https://www.ebp.global/ch-de/karriere/offene-stellen/stellenangebote"
    )
    ebp_switzerland_jobs_catalog_url: str = (
        "https://jobs.ebp.ch/?lang=de&filter_30=64650&filter_10=42976"
    )
    ebp_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    ebp_switzerland_jobs_detail_workers: int = Field(
        default=8,
        ge=1,
        le=20,
    )
    ruag_switzerland_jobs_base_url: str = (
        "https://www.ruag.ch/en/working-us/job-portal"
    )
    ruag_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    ruag_switzerland_jobs_max_pages: int = Field(default=20, ge=1, le=100)
    ruag_switzerland_jobs_max_catalog_passes: int = Field(
        default=3,
        ge=1,
        le=20,
    )
    ruag_switzerland_jobs_detail_workers: int = Field(
        default=8,
        ge=1,
        le=20,
    )
    cyberlink_jobs_base_url: str = "https://www.cyberlink.ch/de/cyberlink/jobs"
    cyberlink_jobs_catalog_url: str = "https://cyberlink.digitalent.cloud/"
    cyberlink_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    cyberlink_jobs_detail_workers: int = Field(default=4, ge=1, le=20)
    ergon_jobs_base_url: str = (
        "https://www.ergon.ch/de/karriere/jobs?showAllJobs=true"
    )
    ergon_jobs_api_url: str = "https://apply.ergon.ch/api/offers/"
    ergon_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    ergon_jobs_max_jobs: int = Field(default=500, ge=1, le=5000)
    logobject_jobs_base_url: str = "https://logobject.com/karriere"
    logobject_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    logobject_jobs_max_jobs: int = Field(default=500, ge=1, le=5000)
    logobject_jobs_detail_workers: int = Field(default=4, ge=1, le=8)
    ti8m_switzerland_jobs_base_url: str = "https://www.ti8m.com/en/career#job"
    ti8m_switzerland_jobs_catalog_url: str = "https://career.ti8m.com/?lang=en"
    ti8m_switzerland_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    ti8m_switzerland_jobs_max_jobs: int = Field(default=500, ge=1, le=5000)
    ti8m_switzerland_jobs_detail_workers: int = Field(default=8, ge=1, le=8)
    novartis_switzerland_jobs_base_url: str = (
        "https://www.novartis.com/careers/career-search?search_api_fulltext="
        "&country%5B%5D=LOC_CH&field_job_posted_date=All&op=Submit"
    )
    novartis_switzerland_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    novartis_switzerland_jobs_max_pages: int = Field(default=50, ge=1, le=200)
    novartis_switzerland_jobs_max_catalog_passes: int = Field(default=3, ge=1, le=20)
    novartis_switzerland_jobs_detail_workers: int = Field(default=8, ge=1, le=8)
    pictet_switzerland_jobs_base_url: str = (
        "https://career012.successfactors.eu/career?company=banquepict"
        "&career_ns=job_listing_summary&navBarLevel=JOB_SEARCH"
    )
    pictet_switzerland_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    pictet_switzerland_jobs_max_jobs: int = Field(default=1000, ge=1, le=5000)
    pictet_switzerland_jobs_max_catalog_passes: int = Field(default=3, ge=1, le=20)
    pictet_switzerland_jobs_detail_workers: int = Field(default=8, ge=1, le=8)
    swiss_re_jobs_base_url: str = (
        "https://www.swissre.com/careers/switzerland-careers.html"
    )
    swiss_re_jobs_search_url: str = "https://careers.swissre.com/search/"
    swiss_re_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    swiss_re_jobs_max_pages: int = Field(default=20, ge=1, le=100)
    swiss_re_jobs_max_catalog_passes: int = Field(default=3, ge=1, le=20)
    swiss_re_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    baloise_jobs_base_url: str = "https://www.baloise.com/de/CH/jobs.html"
    baloise_jobs_catalog_url: str = (
        "https://www.baloise.com/baloise-com/jobs/de/CH/main/"
        "jobSearchWidget/jobSearchWidget.json"
    )
    baloise_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    baloise_jobs_max_jobs: int = Field(default=1000, ge=1, le=5000)
    baloise_jobs_detail_workers: int = Field(default=8, ge=1, le=8)
    elca_jobs_base_url: str = (
        "https://iaaras.fa.ocs.oraclecloud.com/"
        "hcmUI/CandidateExperience/en/sites/CX_1/jobs"
    )
    elca_jobs_api_url: str = (
        "https://iaaras.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest"
    )
    elca_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    elca_jobs_max_pages: int = Field(default=50, ge=1, le=200)
    elca_jobs_max_catalog_passes: int = Field(default=3, ge=1, le=20)
    elca_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    aveniq_jobs_base_url: str = "https://aveniq.recruitee.com/"
    aveniq_jobs_api_url: str = "https://aveniq.recruitee.com/api/offers/"
    aveniq_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    aveniq_jobs_max_jobs: int = Field(default=1000, ge=1, le=5000)
    mimacom_jobs_base_url: str = "https://www.mimacom.com/jobs"
    mimacom_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    mimacom_jobs_max_jobs: int = Field(default=500, ge=1, le=5000)
    mimacom_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    unit8_switzerland_jobs_base_url: str = "https://unit8.com/career/"
    unit8_switzerland_jobs_api_url: str = (
        "https://apply.workable.com/api/v1/widget/accounts/unit8"
    )
    unit8_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    unit8_switzerland_jobs_max_jobs: int = Field(default=500, ge=1, le=5000)
    unit8_switzerland_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    axpo_switzerland_jobs_base_url: str = (
        "https://careers.axpo.com/jobs?"
        "split_view=true&query=&country=Switzerland"
    )
    axpo_switzerland_jobs_feed_url: str = "https://careers.axpo.com/jobs.json"
    axpo_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    axpo_switzerland_jobs_max_pages: int = Field(default=50, ge=1, le=200)
    axpo_switzerland_jobs_max_jobs: int = Field(default=1000, ge=1, le=5000)
    ringier_jobs_base_url: str = "https://career.ringier.ch/en/career"
    ringier_jobs_api_url: str = (
        "https://career.ringier.ch/api/jobs-ringier-en.json"
    )
    ringier_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    ringier_jobs_max_jobs: int = Field(default=500, ge=1, le=5000)
    msd_jobs_base_url: str = (
        "https://jobs.msd.com/gb/en/search-results?"
        "rk=page-targeted-jobs-page172-prod-DZJ1ve"
    )
    msd_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    msd_jobs_max_pages: int = Field(default=100, ge=1, le=500)
    msd_jobs_max_catalog_passes: int = Field(default=3, ge=1, le=20)
    msd_jobs_page_workers: int = Field(default=4, ge=1, le=20)
    msd_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    srg_ssr_jobs_base_url: str = "https://www.srgssr.ch/en/jobs-career/jobs"
    srg_ssr_jobs_catalog_url: str = (
        "https://ohws.prospective.ch/public/v1/careercenter/1000936/"
        "?sub=1&srg=1&filter_10=1124107&lang=en"
    )
    srg_ssr_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    srg_ssr_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    ibm_jobs_base_url: str = (
        "https://www.ibm.com/de-de/careers/search?"
        "field_keyword_05[0]=Switzerland"
    )
    ibm_jobs_api_url: str = (
        "https://www-api.ibm.com/search/api/v1/ibmcom/appid/careers/"
        "responseFormat/json"
    )
    ibm_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    ibm_jobs_max_pages: int = Field(default=100, ge=1, le=500)
    ibm_jobs_max_catalog_passes: int = Field(default=3, ge=1, le=20)
    google_jobs_base_url: str = (
        "https://www.google.com/about/careers/applications/jobs/results/"
        "?location=Zurich%2C%20Switzerland"
    )
    google_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    google_jobs_max_pages: int = Field(default=100, ge=1, le=500)
    google_jobs_max_catalog_passes: int = Field(default=3, ge=1, le=20)
    google_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    buhler_switzerland_jobs_base_url: str = (
        "https://jobs.buhlergroup.com/?lang=de"
    )
    buhler_switzerland_jobs_api_url: str = (
        "https://ohws.prospective.ch/public/v1/medium/1008005/jobs"
    )
    buhler_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    buhler_switzerland_jobs_max_pages: int = Field(default=100, ge=1, le=500)
    buhler_switzerland_jobs_max_catalog_passes: int = Field(
        default=3,
        ge=1,
        le=20,
    )
    oracle_switzerland_jobs_base_url: str = (
        "https://careers.oracle.com/en/sites/jobsearch/jobs?"
        "lastSelectedFacet=locations&location=Switzerland&"
        "locationId=300000000106764&locationLevel=country&mode=location&"
        "selectedLocationsFacet=300000000106764"
    )
    oracle_switzerland_jobs_api_url: str = (
        "https://eeho.fa.us2.oraclecloud.com/hcmRestApi/resources/latest"
    )
    oracle_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    oracle_switzerland_jobs_max_pages: int = Field(default=100, ge=1, le=500)
    oracle_switzerland_jobs_max_catalog_passes: int = Field(
        default=3,
        ge=1,
        le=20,
    )
    oracle_switzerland_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    adnovum_jobs_base_url: str = "https://careers.adnovum.com/search/"
    adnovum_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    adnovum_jobs_max_pages: int = Field(default=20, ge=1, le=100)
    adnovum_jobs_max_catalog_passes: int = Field(default=3, ge=1, le=20)
    adnovum_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    ey_switzerland_jobs_base_url: str = (
        "https://careers.ey.com/ey/search/?createNewAlert=false&q=&locationsearch="
        "&optionsFacetsDD_country=CH&optionsFacetsDD_customfield1="
    )
    ey_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    ey_switzerland_jobs_max_pages: int = Field(default=20, ge=1, le=100)
    ey_switzerland_jobs_max_catalog_passes: int = Field(default=3, ge=1, le=20)
    ey_switzerland_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    eth_zurich_jobs_base_url: str = "https://jobs.ethz.ch/"
    eth_zurich_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    eth_zurich_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    siemens_switzerland_jobs_base_url: str = (
        "https://jobs.siemens.com/de_DE/externaljobs/SearchJobs/"
        "?42386=%5B812129%5D&42386_format=17546&listFilterMode=1"
        "&folderRecordsPerPage=6"
    )
    siemens_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    siemens_switzerland_jobs_max_pages: int = Field(default=50, ge=1, le=200)
    siemens_switzerland_jobs_max_catalog_passes: int = Field(
        default=3,
        ge=1,
        le=20,
    )
    siemens_switzerland_jobs_detail_workers: int = Field(
        default=8,
        ge=1,
        le=20,
    )
    kpmg_switzerland_jobs_base_url: str = (
        "https://kpmg.com/ch/de/karriere/offene-stellen.html"
    )
    kpmg_switzerland_jobs_api_url: str = (
        "https://ohws.prospective.ch/public/v1/medium/1693/jobs"
    )
    kpmg_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    kpmg_switzerland_jobs_max_pages: int = Field(default=50, ge=1, le=200)
    kpmg_switzerland_jobs_max_catalog_passes: int = Field(
        default=3,
        ge=1,
        le=20,
    )
    swissgrid_jobs_base_url: str = (
        "https://www.swissgrid.ch/en/home/career/jobs.html"
    )
    swissgrid_jobs_api_url: str = (
        "https://www.swissgrid.ch/.rest/cloud/component-data"
        "?path=%2Fswissgrid%2Fen%2Fhome%2Fcareer%2Fjobs%2Fmain%2F"
        "joblist_transferred_11"
    )
    swissgrid_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    swissgrid_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    suva_jobs_base_url: str = (
        "https://jobs.suva.ch/search/?q=&searchResultView=LIST&pageNumber=0"
        "&facetFilters=%7B%7D&sortBy=&markerViewed=&carouselIndex="
    )
    suva_jobs_api_url: str = (
        "https://jobs.suva.ch/services/recruiting/v1/jobs"
    )
    suva_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    suva_jobs_max_pages: int = Field(default=50, ge=1, le=200)
    suva_jobs_max_catalog_passes: int = Field(default=3, ge=1, le=20)
    suva_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    ao_foundation_jobs_base_url: str = (
        "https://careers.aofoundation.org/search/locale=en_US"
    )
    ao_foundation_jobs_page_url: str = (
        "https://careers.aofoundation.org/tile-search-results/"
    )
    ao_foundation_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    ao_foundation_jobs_max_pages: int = Field(default=50, ge=1, le=200)
    ao_foundation_jobs_max_catalog_passes: int = Field(default=3, ge=1, le=20)
    ao_foundation_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    skyguide_jobs_base_url: str = "https://jobs.skyguide.ch/search?locale=en_US"
    skyguide_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    skyguide_jobs_max_pages: int = Field(default=50, ge=1, le=200)
    skyguide_jobs_max_catalog_passes: int = Field(default=3, ge=1, le=20)
    skyguide_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    roche_switzerland_jobs_base_url: str = (
        "https://careers.roche.com/global/en/search-results"
    )
    roche_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    roche_switzerland_jobs_max_pages: int = Field(default=100, ge=1, le=500)
    roche_switzerland_jobs_max_catalog_passes: int = Field(
        default=3,
        ge=1,
        le=20,
    )
    roche_switzerland_jobs_page_workers: int = Field(default=6, ge=1, le=20)
    roche_switzerland_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    logitech_switzerland_jobs_base_url: str = (
        "https://logitech.wd5.myworkdayjobs.com/Logitech?"
        "locationCountry=187134fccb084a0ea9b4b95f23890dbe"
    )
    logitech_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    logitech_switzerland_jobs_max_pages: int = Field(default=100, ge=1, le=500)
    logitech_switzerland_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    swatch_group_jobs_base_url: str = (
        "https://www.swatchgroup.com/en/job-finder?jf_country=40&domain=59"
        "&position=All&contract=All&time=All"
    )
    swatch_group_jobs_timeout_seconds: float = Field(default=45.0, ge=1, le=120)
    swatch_group_jobs_max_pages: int = Field(default=50, ge=1, le=200)
    swatch_group_jobs_detail_workers: int = Field(default=6, ge=1, le=20)
    amazon_switzerland_jobs_base_url: str = (
        "https://www.amazon.jobs/content/en/locations/switzerland/zurich"
    )
    amazon_switzerland_jobs_api_url: str = (
        "https://www.amazon.jobs/en/search.json"
    )
    amazon_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    amazon_switzerland_jobs_max_pages: int = Field(default=100, ge=1, le=500)
    amazon_switzerland_jobs_max_catalog_passes: int = Field(
        default=3,
        ge=1,
        le=20,
    )
    cognizant_switzerland_jobs_base_url: str = (
        "https://careers.cognizant.com/global-en/jobs/?keyword="
        "&location=Switzerland&lat=&lng=&cname=Switzerland&ccode=CH"
        "&origin=global"
    )
    cognizant_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    cognizant_switzerland_jobs_max_pages: int = Field(
        default=100,
        ge=1,
        le=500,
    )
    cognizant_switzerland_jobs_max_catalog_passes: int = Field(
        default=3,
        ge=1,
        le=20,
    )
    cognizant_switzerland_jobs_detail_workers: int = Field(
        default=8,
        ge=1,
        le=20,
    )
    fisba_jobs_base_url: str = "https://www.fisba.com/en/current-vacancies"
    fisba_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    fisba_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    gritec_jobs_base_url: str = "https://www.gritec.ch/en/career"
    gritec_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    gritec_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    helbling_jobs_base_url: str = "https://helbling.ch/de/karriere/jobs"
    helbling_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    helbling_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    maerki_baumann_jobs_base_url: str = (
        "https://www.maerki-baumann.ch/de/unsere-bank/stellenangebote"
    )
    maerki_baumann_jobs_api_url: str = (
        "https://odm.ostendis.com/ojp/data/v55/jobs/"
        "58c324307ff846428a19a2f36b7f9994/DE"
        "?domain=www.maerki-baumann.ch"
    )
    maerki_baumann_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    maerki_baumann_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    electrosuisse_jobs_base_url: str = (
        "https://www.electrosuisse.ch/de/karriere/offene-stellen/"
    )
    electrosuisse_jobs_api_url: str = (
        "https://odm.ostendis.com/ojp/data/v55/jobs/"
        "3bydei12tjzhiw5j4mqa85cfj4bjoud2/DE"
        "?domain=www.electrosuisse.ch"
    )
    electrosuisse_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    electrosuisse_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    bachem_jobs_base_url: str = (
        "https://careers.bachem.com/search/?createNewAlert=false&q="
        "&optionsFacetsDD_department=&optionsFacetsDD_shifttype="
        "&optionsFacetsDD_location=&optionsFacetsDD_country=CH"
        "&optionsFacetsDD_customfield1="
    )
    bachem_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    bachem_jobs_max_pages: int = Field(default=20, ge=1, le=200)
    bachem_jobs_max_catalog_passes: int = Field(default=3, ge=1, le=20)
    bachem_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    georg_fischer_switzerland_jobs_base_url: str = (
        "https://georgfischer.wd103.myworkdayjobs.com/GeorgFischer_Careers?"
        "locationCountry=187134fccb084a0ea9b4b95f23890dbe"
    )
    georg_fischer_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    georg_fischer_switzerland_jobs_max_pages: int = Field(
        default=100,
        ge=1,
        le=500,
    )
    georg_fischer_switzerland_jobs_detail_workers: int = Field(
        default=8,
        ge=1,
        le=20,
    )
    also_jobs_base_url: str = (
        "https://www.also.com/ec/cms5/en_6000/6000/company/career/"
        "open-positions/index.jsp"
    )
    also_jobs_api_url: str = (
        "https://www.also.com/ec/cms5/en_6000/6000/company/career/"
        "open-positions/jobs_json_4.json"
    )
    also_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    also_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    bedag_jobs_base_url: str = (
        "https://www.bedag.ch/de/jobs-und-karriere/offene-stellen/"
    )
    bedag_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    bedag_jobs_detail_workers: int = Field(default=8, ge=1, le=20)
    nexplore_jobs_base_url: str = "https://www.nexplore.ch/jobs"
    nexplore_jobs_api_url: str = "https://cms.nexplore.ch/api/jobs"
    nexplore_jobs_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    ntt_global_data_centers_switzerland_jobs_base_url: str = (
        "https://nttglobaldatacenters.wd501.myworkdayjobs.com/en-US/External/jobs?"
        "locations=0416448655001000c28517e560890000"
    )
    ntt_global_data_centers_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    ntt_global_data_centers_switzerland_jobs_max_pages: int = Field(
        default=100,
        ge=1,
        le=500,
    )
    ntt_global_data_centers_switzerland_jobs_detail_workers: int = Field(
        default=8,
        ge=1,
        le=20,
    )
    teradata_switzerland_jobs_base_url: str = "https://careers.teradata.com/jobs"
    teradata_switzerland_jobs_api_url: str = "https://careers.teradata.com/graphql"
    teradata_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    teradata_switzerland_jobs_max_pages: int = Field(
        default=100,
        ge=1,
        le=500,
    )
    swiss_life_switzerland_jobs_base_url: str = (
        "https://www.swisslife.ch/de/ueber-uns/karriere/jobs.html#"
    )
    swiss_life_switzerland_jobs_catalog_url: str = (
        "https://ohws.prospective.ch/public/v1/careercenter/1005584/"
    )
    swiss_life_switzerland_jobs_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
    )
    swiss_life_switzerland_jobs_max_pages: int = Field(
        default=20,
        ge=1,
        le=200,
    )
    swiss_life_switzerland_jobs_detail_workers: int = Field(
        default=8,
        ge=1,
        le=20,
    )
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
