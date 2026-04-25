import os
from functools import lru_cache

from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "fnOS Media Agent"
    mteam_base_url: str = os.getenv("MTEAM_BASE_URL", "")
    mteam_api_key: str = os.getenv("MTEAM_API_KEY", "")
    qb_base_url: str = os.getenv("QB_BASE_URL", "")
    qb_username: str = os.getenv("QB_USERNAME", "")
    qb_password: str = os.getenv("QB_PASSWORD", "")
    database_path: str = os.getenv("DATABASE_PATH", "nas_media_agent.db")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
