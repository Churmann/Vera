from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    off_user_agent: str = "VeraApp/1.0"
    off_request_timeout: float = 8.0
    off_cache_ttl: int = 300
    # Retry a rate-limited (HTTP 429) OFF request this many times, with exponential
    # backoff starting at off_retry_backoff seconds, before surfacing the error.
    off_max_retries: int = 3
    off_retry_backoff: float = 0.5

    model_config = {"env_file": ".env"}
