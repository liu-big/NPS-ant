from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_PORT_RANGES: dict[str, tuple[int, int]] = {
    "ssh": (18023, 18522),
    "web": (18523, 19022),
    "gdb": (19023, 19522),
    "temp": (19523, 20022),
}

ALLOWED_MAPPING_SERVICES = ("ssh", "web", "gdb", "tcp")


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
    default_nps_client_id: int = Field(default=0, alias="DEFAULT_NPS_CLIENT_ID")

    portal_username: str = Field(default="admin", alias="PORTAL_USERNAME")
    portal_password: str = Field(default="admin123", alias="PORTAL_PASSWORD")

    allowed_remark_prefix: str = Field(default="", alias="ALLOWED_REMARK_PREFIX")
    mask_client_ip: bool = Field(default=True, alias="MASK_CLIENT_IP")

    jwt_secret: str = Field(default="change-me-in-production", alias="JWT_SECRET")
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24

    data_dir: str = Field(default="./data", alias="DATA_DIR")
    default_tunnel_ttl_minutes: int = Field(default=1440, alias="DEFAULT_TUNNEL_TTL_MINUTES")
    max_tunnel_ttl_minutes: int = Field(default=43200, alias="MAX_TUNNEL_TTL_MINUTES")
    enable_custom_target_port: bool = Field(default=False, alias="ENABLE_CUSTOM_TARGET_PORT")
    default_ssh_user: str = Field(default="ant", alias="DEFAULT_SSH_USER")
    cleanup_interval_seconds: int = Field(default=60, alias="CLEANUP_INTERVAL_SECONDS")

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

    max_running_mappings_per_user: int = Field(default=3, alias="MAX_RUNNING_MAPPINGS_PER_USER")
    max_running_mappings_total: int = Field(default=200, alias="MAX_RUNNING_MAPPINGS_TOTAL")

    ssh_port_start: int = Field(default=DEFAULT_PORT_RANGES["ssh"][0], alias="SSH_PORT_START")
    ssh_port_end: int = Field(default=DEFAULT_PORT_RANGES["ssh"][1], alias="SSH_PORT_END")
    web_port_start: int = Field(default=DEFAULT_PORT_RANGES["web"][0], alias="WEB_PORT_START")
    web_port_end: int = Field(default=DEFAULT_PORT_RANGES["web"][1], alias="WEB_PORT_END")
    gdb_port_start: int = Field(default=DEFAULT_PORT_RANGES["gdb"][0], alias="GDB_PORT_START")
    gdb_port_end: int = Field(default=DEFAULT_PORT_RANGES["gdb"][1], alias="GDB_PORT_END")
    temp_port_start: int = Field(default=DEFAULT_PORT_RANGES["temp"][0], alias="TEMP_PORT_START")
    temp_port_end: int = Field(default=DEFAULT_PORT_RANGES["temp"][1], alias="TEMP_PORT_END")

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

    def get_port_range(self, service: str) -> tuple[int, int]:
        key = (service or "ssh").lower()
        mapping = {
            "ssh": (self.ssh_port_start, self.ssh_port_end),
            "web": (self.web_port_start, self.web_port_end),
            "gdb": (self.gdb_port_start, self.gdb_port_end),
            "temp": (self.temp_port_start, self.temp_port_end),
            "tcp": self.get_auto_port_range(),
        }
        if key not in mapping:
            raise ValueError(f"不支持的服务类型: {service}")
        start, end = mapping[key]
        if start > end:
            raise ValueError(f"{service} 端口区间配置无效: {start}-{end}")
        return start, end

    def get_port_ranges(self) -> dict[str, dict[str, int]]:
        auto_start, auto_end = self.get_auto_port_range()
        return {
            "auto": {"start": auto_start, "end": auto_end},
            **{
                service: {"start": start, "end": end}
                for service in DEFAULT_PORT_RANGES
                for start, end in [self.get_port_range(service)]
            },
        }

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
