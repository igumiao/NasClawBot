from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "fnOS Media Agent"


def get_settings() -> Settings:
    return Settings()
