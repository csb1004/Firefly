from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    public_url: str
    discord_client_id: str
    discord_client_secret: str
    discord_redirect_uri: str
    session_secret: str
    special_user_id: int
    secure_cookies: bool
    static_dir: Path
    upload_dir: Path
    s3_endpoint_url: str
    s3_access_key_id: str
    s3_secret_access_key: str
    s3_bucket_name: str
    s3_region: str

    @property
    def discord_ready(self) -> bool:
        return bool(self.discord_client_id and self.discord_client_secret)

    @classmethod
    def from_env(cls) -> "Settings":
        public_url = os.getenv("CARD_SITE_URL", "http://localhost:8000").rstrip("/")
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:///./bandi_cards.db"),
            public_url=public_url,
            discord_client_id=os.getenv("DISCORD_CLIENT_ID", "").strip(),
            discord_client_secret=os.getenv("DISCORD_CLIENT_SECRET", "").strip(),
            discord_redirect_uri=os.getenv(
                "DISCORD_REDIRECT_URI", f"{public_url}/api/auth/discord/callback"
            ).strip(),
            session_secret=os.getenv("CARD_SESSION_SECRET", "development-only-change-me"),
            special_user_id=int(os.getenv("SPECIAL_USER_ID", "393724092022390784")),
            secure_cookies=_bool_env("CARD_SECURE_COOKIES", public_url.startswith("https://")),
            static_dir=Path(os.getenv("CARD_STATIC_DIR", BASE_DIR / "web" / "dist")),
            upload_dir=Path(os.getenv("CARD_UPLOAD_DIR", BASE_DIR / "data" / "card-images")),
            s3_endpoint_url=os.getenv("S3_ENDPOINT_URL", "").strip(),
            s3_access_key_id=os.getenv("S3_ACCESS_KEY_ID", "").strip(),
            s3_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY", "").strip(),
            s3_bucket_name=os.getenv("S3_BUCKET_NAME", "").strip(),
            s3_region=os.getenv("S3_REGION", "auto").strip(),
        )


settings = Settings.from_env()
