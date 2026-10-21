from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "FindIt AI API"

    # Core
    database_url: str = "postgresql+psycopg://findit:findit@localhost:5432/findit"
    secret_key: str = "change-me-in-production"
    access_token_minutes: int = 60 * 24
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    public_base_url: str = "http://localhost:8000"

    # Image storage
    storage_backend: str = "local"  # local | s3
    upload_dir: str = "uploads"
    max_upload_mb: int = 5
    s3_bucket: str = ""
    s3_region: str = ""
    s3_public_base_url: str = ""

    # Matching
    embedding_backend: str = "demo"  # demo | real
    clip_model: str = "clip-ViT-B-32"
    text_model: str = "all-MiniLM-L6-v2"
    image_weight: float = 0.6
    text_weight: float = 0.4
    # Cosine similarities are rescaled as (sim - floor) / (1 - floor), clamped to [0, 1].
    # Raw CLIP image-image cosine rarely drops below ~0.5, so tune the floors for `real`.
    image_sim_floor: float = 0.3
    text_sim_floor: float = 0.0
    min_match_score: float = 30.0
    match_window_days: int = 30
    match_radius_km: float = 5.0

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
