from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class UserInfo(BaseModel):
    id: int
    username: str
    role: str
    status: str
    created_at: str | None = None
    updated_at: str | None = None


UserPublic = UserInfo


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserInfo


class HealthResponse(BaseModel):
    status: str = "ok"
    nps_configured: bool


class DeviceSummary(BaseModel):
    id: int
    remark: str
    version: str
    client_addr: str
    inlet_flow: str
    export_flow: str
    rate: str
    status: str
    is_open: bool
    device_name: str | None = None
    access_code: str | None = None


class TunnelSummary(BaseModel):
    id: int
    client_id: int
    remark: str
    mode: str
    server_port: int
    target: str
    status: str
    client_status: str
    connect_text: str


class DashboardSummary(BaseModel):
    total_devices: int
    online_devices: int
    offline_devices: int
    open_connections: int
    total_inlet_flow: str = Field(description="Aggregated inlet flow display")
    total_export_flow: str = Field(description="Aggregated export flow display")
    active_tunnel_sessions: int = 0
    total_users: int = 0


class UserCreateRequest(BaseModel):
    username: str
    password: str
    role: str = "user"


class UserUpdateRequest(BaseModel):
    username: str | None = None
    role: str | None = None
    status: str | None = None


class ResetPasswordRequest(BaseModel):
    password: str


class DeviceAclCreateRequest(BaseModel):
    user_id: int
    client_id: int
    device_name: str = ""
    remark: str = ""
    access_code: str | None = None
    ttl_key: str | None = None
    access_expire_at: str | None = None


class DeviceAclReassignRequest(BaseModel):
    ttl_key: str | None = None
    access_expire_at: str | None = None


class DeviceAclResponse(BaseModel):
    id: int
    user_id: int
    client_id: int
    device_name: str
    remark: str
    access_code: str
    ttl_key: str = ""
    ttl_label: str = "未设置"
    access_expire_at: str | None = None
    access_expire_at_display: str | None = None
    status: str = "active"
    status_label: str = "待使用"
    released_at: str | None = None
    created_at: str
    username: str | None = None


class DeviceSearchResult(BaseModel):
    client_id: int
    remark: str
    device_name: str
    access_code: str
    ttl_key: str = ""
    ttl_label: str = "未设置"
    access_expire_at: str | None = None
    access_expire_at_display: str | None = None
    access_valid: bool = True
    acl_status: str = "active"
    acl_status_label: str = "待使用"
    can_apply: bool = True
    apply_hint: str = ""
    device: DeviceSummary | None = None
    services: list[str] = Field(default_factory=lambda: ["ssh", "web", "gdb"])


class CreateTunnelRequest(BaseModel):
    client_id: int
    service: str


class PortMappingCreateRequest(BaseModel):
    client_id: int = Field(ge=1)
    target_host: str | None = None
    target_port: int = Field(ge=1, le=65535)
    ttl_minutes: int | None = Field(default=720, description="None 表示永久")


class ClientSearchItem(BaseModel):
    client_id: int
    remark: str
    device_name: str = ""
    status: str
    version: str = ""


class PortMappingResponse(BaseModel):
    id: int
    client_id: int
    device_name: str = ""
    service: str
    nps_tunnel_id: int
    public_host: str
    public_port: int
    target_host: str
    target_port: int
    ttl_minutes: int | None = None
    status: str
    status_label: str = "运行中"
    created_at: str
    created_at_display: str | None = None
    expire_at: str | None
    expire_at_display: str | None = None
    remaining_label: str | None = None
    deleted_at: str | None = None
    released_at: str | None = None
    ended_at_display: str | None = None
    release_reason: str | None = None
    release_reason_label: str | None = None
    remark: str = ""
    connect_text: str
    port_valid: bool = True
    port_range: dict[str, int] | None = None
    username: str | None = None


TunnelSessionResponse = PortMappingResponse


class AuditLogResponse(BaseModel):
    id: int
    user_id: int | None
    username: str
    role: str
    action: str
    target_type: str
    target_id: str
    detail: str
    ip: str
    created_at: str


class AuditLogListResponse(BaseModel):
    items: list[AuditLogResponse]
    total: int


class TtlOption(BaseModel):
    key: str
    label: str
    minutes: int | None


class PortalConfigResponse(BaseModel):
    default_tunnel_ttl: str
    ttl_options: list[TtlOption]
    services: list[str]
    default_ssh_user: str
