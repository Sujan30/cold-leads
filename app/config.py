import re

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str
    database_url: str

    linq_api_token: str
    linq_phone_number: str
    linq_webhook_signing_secret: str = ""

    ngrok_exposed_url: str = ""

    sendgrid_api_key: str = ""
    sendgrid_from_email: str = ""

    agents_phone: str = ""
    agents_name: str = "Jason"
    mode: str = "prod"  # "dev" auto-seeds a test lead on every startup

    cal_api_key: str = ""
    cal_secret: str = ""
    cal_username: str = ""
    cal_event_slug: str = "30min"
    cal_event_type_id: int = 0

    twenty_api_url: str = ""
    twenty_api_key: str = ""
    twenty_workspace_id: str = ""
    chat_viewer_base_url: str = "http://localhost:8000"

    @property
    def async_database_url(self) -> str:
        # asyncpg requires postgresql+asyncpg:// scheme
        # Strip sslmode/channel_binding — passed via connect_args instead
        # Remove -pooler from hostname: Neon's pooler (PgBouncer) caches type OIDs
        # which break after enum drops/recreates; direct connection avoids this.
        url = self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        url = url.replace("-pooler.", ".", 1)
        url = re.sub(r"(channel_binding|sslmode)=[^&]*&?", "", url)
        url = re.sub(r"[?&]$", "", url)
        url = re.sub(r"\?&", "?", url)
        return url


settings = Settings()
