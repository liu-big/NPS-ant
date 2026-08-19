from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_int_list(value: str | list[int] | None) -> list[int]:
    if value is None:
        return []
    if isinstance(value, list):
        return [int(v) for v in value]
    parts = [p.strip() for p in str(value).split(",") if p.strip()]
    return [int(p) for p in parts]


def _parse_str_list(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [p.strip() for p in str(value).split(",") if p.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    nps_base_url: str = Field(default="http://127.0.0.1:8080", alias="NPS_BASE_URL")
    nps_auth_key: str = Field(default="", alias="NPS_AUTH_KEY")
    nps_public_host: str = Field(default="127.0.0.1", alias="NPS_PUBLIC_HOST")
    nps_public_hosts: str = Field(default="", alias="NPS_PUBLIC_HOSTS")

    portal_username: str = Field(default="admin", alias="PORTAL_USERNAME")
    portal_password: str = Field(default="admin123", alias="PORTAL_PASSWORD")

    allowed_remark_prefix: str = Field(default="", alias="ALLOWED_REMARK_PREFIX")
    mask_client_ip: bool = Field(default=True, alias="MASK_CLIENT_IP")

    jwt_secret: str = Field(default="change-me-in-production", alias="JWT_SECRET")
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24

    data_dir: str = Field(default="./data", alias="DATA_DIR")
    default_ssh_user: str = Field(default="ant", alias="DEFAULT_SSH_USER")
    cleanup_interval_seconds: int = Field(default=60, alias="CLEANUP_INTERVAL_SECONDS")
    audit_log_retention_days: int = Field(
        default=90,
        alias="AUDIT_LOG_RETENTION_DAYS",
        description="0=关闭自动清理；>0 时定期删除更早的审计日志",
    )

    auto_port_start: int = Field(default=1, alias="AUTO_PORT_START")
    auto_port_end: int = Field(default=65535, alias="AUTO_PORT_END")
    auto_port_blocklist: str = Field(
        default="8080,8088,18000,18022",
        alias="AUTO_PORT_BLOCKLIST",
    )
    auto_port_socket_check: bool = Field(default=False, alias="AUTO_PORT_SOCKET_CHECK")

    user_ttl_min_minutes: int = Field(default=5, alias="USER_TTL_MIN_MINUTES")
    user_ttl_max_minutes: int = Field(default=1440, alias="USER_TTL_MAX_MINUTES")
    user_ttl_default_minutes: int = Field(default=720, alias="USER_TTL_DEFAULT_MINUTES")

    allow_custom_target_host: bool = Field(default=True, alias="ALLOW_CUSTOM_TARGET_HOST")
    target_host_whitelist: str = Field(default="127.0.0.1,localhost", alias="TARGET_HOST_WHITELIST")

    max_running_mappings_per_user: int = Field(default=5, alias="MAX_RUNNING_MAPPINGS_PER_USER")
    max_running_mappings_total: int = Field(default=200, alias="MAX_RUNNING_MAPPINGS_TOTAL")

    @field_validator("auto_port_blocklist", mode="before")
    @classmethod
    def _coerce_blocklist(cls, v: object) -> str:
        if isinstance(v, list):
            return ",".join(str(x) for x in v)
        return str(v) if v is not None else ""

    def get_public_hosts(self) -> list[str]:
        hosts = _parse_str_list(self.nps_public_hosts)
        if not hosts and self.nps_public_host:
            hosts = [self.nps_public_host.strip()]
        return [h for h in hosts if h]

    def get_auto_port_blocklist(self) -> set[int]:
        return set(_parse_int_list(self.auto_port_blocklist))

    def get_target_host_whitelist(self) -> set[str]:
        return {h.lower() for h in _parse_str_list(self.target_host_whitelist)}

    def get_auto_port_range(self) -> tuple[int, int]:
        start, end = self.auto_port_start, self.auto_port_end
        if start > end:
            raise ValueError(f"自动端口区间配置无效: {start}-{end}")
        return start, end

    def is_port_in_auto_range(self, port: int | None) -> bool:
        if port is None or int(port) <= 0:
            return False
        start, end = self.get_auto_port_range()
        return start <= int(port) <= end

    def get_user_ttl_options(self) -> list[dict[str, int | str | None]]:
        presets: list[tuple[int | None, str]] = [
            (5, "5 分钟"),
            (30, "30 分钟"),
            (60, "1 小时"),
            (120, "2 小时"),
            (360, "6 小时"),
            (720, "12 小时"),
            (1440, "1 天"),
            (None, "永久"),
        ]
        options = []
        for minutes, label in presets:
            if minutes is None:
                options.append({"minutes": None, "label": label})
            elif self.user_ttl_min_minutes <= minutes <= self.user_ttl_max_minutes:
                options.append({"minutes": minutes, "label": label})
        return options


@lru_cache
def get_settings() -> Settings:
    return Settings()
