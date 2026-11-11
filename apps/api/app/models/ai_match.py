
from pydantic import BaseModel, ConfigDict, Field

from app.core.ai_models import AISource


class AiMatchScore(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    score: int = Field(ge=0, le=100)


class AiMatchMetadata(AiMatchScore):
    """Suitability score and provenance shared by calculation, storage and API responses."""

    version: str
    profile_hash: str = Field(alias="profileHash")
    vacancy_hash: str = Field(alias="vacancyHash")
    model: str
    backend: AISource
    prompt_version: str = Field(alias="promptVersion")
    cache_key: str = Field(alias="cacheKey")
    source: AISource
    updated_at: str = Field(alias="updatedAt")
    provider_error: str | None = Field(default=None, alias="providerError", max_length=240)
    revision: str | None = None
    fingerprint: str | None = None
