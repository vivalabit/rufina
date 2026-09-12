from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AiMatchScore(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    score: int = Field(ge=0, le=100)


class AiMatchMetadata(AiMatchScore):
    """Suitability score and provenance shared by calculation, storage and API responses."""

    version: str
    profile_hash: str = Field(alias="profileHash")
    vacancy_hash: str = Field(alias="vacancyHash")
    model: str
    backend: Literal["openclaw_codex", "openai_api", "local"]
    prompt_version: str = Field(alias="promptVersion")
    cache_key: str = Field(alias="cacheKey")
    source: Literal["openclaw_codex", "openai_api", "local"]
    updated_at: str = Field(alias="updatedAt")
    provider_error: str | None = Field(default=None, alias="providerError", max_length=240)
    revision: str | None = None
    fingerprint: str | None = None
