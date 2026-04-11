from __future__ import annotations

from typing import Any, Tuple, Type

from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, DotEnvSettingsSource, PydanticBaseSettingsSource

_SLUG_FIELDS = frozenset({"greenhouse_slugs", "lever_slugs", "ashby_slugs"})


class _CommaSepDotEnv(DotEnvSettingsSource):
    def prepare_field_value(
        self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool
    ) -> Any:
        if field_name in _SLUG_FIELDS and isinstance(value, str):
            return [s.strip() for s in value.split(",") if s.strip()]
        return super().prepare_field_value(field_name, field, value, value_is_complex)


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    discord_token: str
    discord_channel_id: int
    discord_guild_id: int | None = None  # set for instant slash command sync during dev

    greenhouse_slugs: list[str] = []
    lever_slugs: list[str] = []
    ashby_slugs: list[str] = []

    poll_interval_minutes: int = 10
    simplify_poll_interval_minutes: int = 30

    db_path: str = "jobs.db"

    meta_enabled: bool = False
    meta_poll_interval_minutes: int = 30

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            _CommaSepDotEnv(settings_cls),
            file_secret_settings,
        )


settings = Settings()  # type: ignore[call-arg]
