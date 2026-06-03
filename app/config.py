from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    off_user_agent: str = "VeraApp/1.0"
    off_request_timeout: float = 8.0
    off_cache_ttl: int = 300
    default_weight_nutrition: float = 0.5
    default_weight_additives: float = 0.3
    default_weight_nova: float = 0.2

    model_config = {"env_file": ".env"}
