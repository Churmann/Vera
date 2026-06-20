from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    off_user_agent: str = "VeraApp/1.0"
    off_request_timeout: float = 8.0
    off_cache_ttl: int = 300
    # Retry a rate-limited (HTTP 429) OFF request this many times, with exponential
    # backoff starting at off_retry_backoff seconds, before surfacing the error.
    off_max_retries: int = 3
    off_retry_backoff: float = 0.5
    # OFF write target + read host. "production" -> world.openfoodfacts.org,
    # "staging" -> world.openfoodfacts.net. Safe default is production so the live
    # app and the existing tests read real data; set OFF_ENVIRONMENT=staging in
    # .env to build/test product submission against staging first.
    off_environment: str = "production"
    # OFF account credentials (the username is the OFF *username*, NOT the email).
    # Secrets — provided via env only, never committed. Optional so the app still
    # boots for read-only browsing; the add route errors clearly if unset.
    off_username: str | None = None
    off_password: str | None = None

    # Photo-upload + pending-state tuning (all overridable via env).
    off_max_image_bytes: int = 12 * 1024 * 1024   # 12 MB per photo
    off_pending_window_seconds: int = 900          # 15 min: pending -> final cutoff
    off_image_lang: str = "en"                     # language code for selected images

    @property
    def is_staging(self) -> bool:
        return self.off_environment.strip().lower() == "staging"

    @property
    def off_product_host(self) -> str:
        return "world.openfoodfacts.net" if self.is_staging else "world.openfoodfacts.org"

    model_config = {"env_file": ".env"}
