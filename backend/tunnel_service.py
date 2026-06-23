import random
from datetime import datetime, timedelta, timezone
import socket
from typing import Any

from config import ALLOWED_MAPPING_SERVICES, Settings
from database import Database
from nps_api import NpsClient

DEFAULT_TARGET_HOST = "127.0.0.1"
MAPPING_SERVICE = "tcp"

SERVICE_TARGETS = {
    "ssh": ("127.0.0.1", 22),
    "web": ("127.0.0.1", 8000),
    "gdb": ("127.0.0.1", 2345),
    "temp": ("127.0.0.1", 8080),
}

TTL_PRESETS: dict[str, int | None] = {
    "5min": 5,
    "1d": 1440,
    "3d": 4320,
    "1w": 10080,
    "1month": 43200,
    "permanent": None,
}

TTL_LABELS = {
    "5min": "5 分钟（测试）",
    "1d": "1 天",
    "3d": "3 天",
    "1w": "1 周",
    "1month": "1 个月",
    "permanent": "永久",
}


class PortValidationError(ValueError):
    """Raised when public_port is missing or outside the configured pool."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class PortAllocationError(RuntimeError):
    """Raised when no port is available in the service pool."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def get_port_range(settings: Settings, service: str) -> tuple[int, int]:
    return settings.get_port_range(service)


def is_port_in_range(settings: Settings, service: str, port: int | None) -> bool:
    if port is None or int(port) <= 0:
        return False
    start, end = get_port_range(settings, service)
    return start <= int(port) <= end


def validate_port_in_range(settings: Settings, service: str, port: int) -> None:
    if not port or int(port) <= 0:
        raise PortValidationError("未获取到有效公网端口", status_code=502)
    start, end = get_port_range(settings, service)
    if port < start or port > end:
        raise PortValidationError(
            f"{service} 端口 {port} 不在允许区间 {start}-{end}",
            status_code=400,
        )


def ttl_label_for_key(key: str | None) -> str:
    if not key or not str(key).strip():
        return "未设置"
    return TTL_LABELS.get(key, key)


def format_acl_datetime_display(value: str | None) -> str | None:
    """Format ACL datetime for UI (China local, UTC+8)."""
    if not value or not str(value).strip():
        return None
    try:
        dt = _parse_acl_datetime(value)
    except (ValueError, TypeError):
        return str(value)
    cn = dt.astimezone(timezone(timedelta(hours=8)))
    return cn.strftime("%Y-%m-%d %H:%M:%S")


def format_remaining_until(
    deadline: datetime,
    *,
    now: datetime | None = None,
) -> str:
    """Human-readable remaining time until deadline (no TTL preset snapping)."""
    now = now or datetime.now(timezone.utc)
    total_seconds = int((deadline - now).total_seconds())
    if total_seconds <= 0:
        return "已过期"
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days} 天")
    if hours:
        parts.append(f"{hours} 小时")
    if minutes:
        parts.append(f"{minutes} 分钟")
    if seconds and not days and not hours:
        parts.append(f"{seconds} 秒")
    return "剩余 " + " ".join(parts)


def ttl_label_for_acl(
    ttl_key: str | None,
    access_expire_at: str | None = None,
) -> str:
    """Display label for ACL duration; derives remaining time when only access_expire_at is set."""
    key = normalize_ttl_key(ttl_key)
    if key:
        return ttl_label_for_key(key)
    if not access_expire_at or not str(access_expire_at).strip():
        return "未设置"
    try:
        deadline = _parse_acl_datetime(access_expire_at)
    except (ValueError, TypeError):
        return "未设置"
    return format_remaining_until(deadline)


def normalize_ttl_key(key: str | None) -> str | None:
    if key is None:
        return None
    value = str(key).strip()
    return value or None


def _parse_acl_datetime(value: str) -> datetime:
    """Parse admin/UI datetime; naive values are treated as UTC+8 (China local)."""
    s = str(value).strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
    return dt.astimezone(timezone.utc)


def validate_acl_access_expire_at(access_expire_at: str | None) -> None:
    if not access_expire_at:
        return
    if _parse_acl_datetime(access_expire_at) <= datetime.now(timezone.utc):
        raise ValueError("授权截止时间必须晚于当前时间")


def validate_acl_duration_config(ttl_key: str | None, access_expire_at: str | None) -> None:
    has_ttl = bool(normalize_ttl_key(ttl_key))
    has_deadline = bool(access_expire_at and str(access_expire_at).strip())
    if not has_ttl and not has_deadline:
        raise ValueError("请填写「调试有效期」或「授权截止」至少一项")
    if has_ttl and normalize_ttl_key(ttl_key) not in TTL_PRESETS:
        raise ValueError("无效的调试有效期选项")
    if has_deadline:
        validate_acl_access_expire_at(access_expire_at)


def check_acl_access_valid(acl: dict[str, Any]) -> None:
    expire = acl.get("access_expire_at")
    if not expire:
        return
    at = _parse_acl_datetime(expire)
    if at <= datetime.now(timezone.utc):
        raise PermissionError("设备授权已过期，请联系管理员续期")


def check_acl_can_apply(acl: dict[str, Any]) -> None:
    """Ensure ACL is in a state that allows creating a new tunnel."""
    check_acl_access_valid(acl)
    status = (acl.get("status") or "active").lower()
    if status == "completed":
        raise PermissionError("授权已结束，请联系管理员重新分配")
    if status == "in_use":
        raise PermissionError("该授权已有运行中的调试端口，请先在「我的调试端口」释放或等待到期")
    if status != "active":
        raise PermissionError("授权不可用，请联系管理员")


def acl_can_apply(acl: dict[str, Any]) -> bool:
    try:
        check_acl_can_apply(acl)
        return True
    except PermissionError:
        return False


def is_acl_access_valid(acl: dict[str, Any]) -> bool:
    try:
        check_acl_access_valid(acl)
        return True
    except PermissionError:
        return False


def resolve_acl_tunnel_expire_at(settings: Settings, acl: dict[str, Any]) -> str | None:
    """Session expiry: access_expire_at (absolute) overrides ttl_key (relative)."""
    access_deadline = acl.get("access_expire_at")
    if access_deadline:
        deadline_dt = _parse_acl_datetime(access_deadline)
        if deadline_dt <= datetime.now(timezone.utc):
            raise PermissionError("设备授权已过期，请联系管理员续期")
        return deadline_dt.isoformat()

    ttl_key = normalize_ttl_key(acl.get("ttl_key"))
    if not ttl_key:
        raise ValueError("授权未配置调试有效期，请填写授权截止或联系管理员")
    return resolve_expire_at(settings, ttl_key=ttl_key, is_admin=True)


def get_allowed_ttl_options(settings: Settings, is_admin: bool = False) -> list[dict[str, Any]]:
    max_minutes = settings.max_tunnel_ttl_minutes
    options = []
    for key, minutes in TTL_PRESETS.items():
        if key == "permanent":
            if max_minutes == 0 or is_admin:
                options.append({"key": key, "label": TTL_LABELS[key], "minutes": None})
            continue
        if minutes is not None and (max_minutes == 0 or minutes <= max_minutes):
            options.append({"key": key, "label": TTL_LABELS[key], "minutes": minutes})
    return options


def resolve_expire_at(
    settings: Settings,
    *,
    ttl_key: str | None = None,
    ttl_minutes: int | None = None,
    is_admin: bool = False,
) -> str | None:
    minutes: int | None
    if ttl_key:
        if ttl_key not in TTL_PRESETS:
            raise ValueError("无效的 TTL 选项")
        if ttl_key == "permanent":
            if settings.max_tunnel_ttl_minutes != 0 and not is_admin:
                raise ValueError("不允许创建永久隧道")
            return None
        minutes = TTL_PRESETS[ttl_key]
    elif ttl_minutes is not None:
        if ttl_minutes <= 0:
            raise ValueError("TTL 必须大于 0")
        minutes = ttl_minutes
    else:
        minutes = settings.default_tunnel_ttl_minutes

    if minutes is None:
        return None
    if settings.max_tunnel_ttl_minutes > 0 and minutes > settings.max_tunnel_ttl_minutes:
        raise ValueError(f"TTL 不能超过 {settings.max_tunnel_ttl_minutes} 分钟")
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def build_connect_text(
    service: str,
    public_host: str,
    public_port: int,
    settings: Settings,
    *,
    require_pool: bool = True,
    target_port: int | None = None,
) -> str:
    if require_pool and not is_port_in_auto_or_service_range(settings, service, public_port):
        return ""
    if target_port is not None:
        return build_mapping_connect_text(
            settings,
            public_host=public_host,
            public_port=public_port,
            target_port=int(target_port),
            service=service,
        )
    if service == "ssh":
        return f"ssh {settings.default_ssh_user}@{public_host} -p {public_port}"
    if service == "web":
        return f"http://{public_host}:{public_port}"
    if service == "gdb":
        return f"target remote {public_host}:{public_port}"
    return f"{public_host}:{public_port}"


def build_mapping_connect_text(
    settings: Settings,
    *,
    public_host: str,
    public_port: int,
    target_port: int,
    service: str = "tcp",
) -> str:
    """Generate connect command from target port (preferred) with service fallback."""
    tp = int(target_port)
    if tp == 22:
        return f"ssh {settings.default_ssh_user}@{public_host} -p {public_port}"
    if tp in (80, 8000, 8080):
        return f"http://{public_host}:{public_port}"
    if tp == 443:
        return f"https://{public_host}:{public_port}"
    if tp == 2345:
        return f"target remote {public_host}:{public_port}"
    service_key = (service or "").lower()
    if service_key == "ssh":
        return f"ssh {settings.default_ssh_user}@{public_host} -p {public_port}"
    if service_key == "web":
        return f"http://{public_host}:{public_port}"
    if service_key == "gdb":
        return f"target remote {public_host}:{public_port}"
    return f"{public_host}:{public_port}"


def is_port_in_auto_or_service_range(settings: Settings, service: str, port: int | None) -> bool:
    if port is None or int(port) <= 0:
        return False
    if settings.is_port_in_auto_range(port):
        return True
    service_key = (service or "").lower()
    if service_key in SERVICE_TARGETS:
        return is_port_in_range(settings, service_key, port)
    return False


MAPPING_STATUS_LABELS = {
    "running": "运行中",
    "expired": "已过期",
    "deleted": "已释放",
    "released": "已释放",
    "failed": "失败",
    "cleanup_failed": "清理失败",
}

RELEASE_REASON_LABELS = {
    "user_released": "用户释放",
    "ttl_expired": "到期释放",
    "admin_force_release": "管理员强制释放",
    "invalid_port": "端口异常",
    "nps_delete_failed": "NPS 删除失败",
}


def mapping_status_label(status: str) -> str:
    return MAPPING_STATUS_LABELS.get((status or "").lower(), status or "-")


def release_reason_label(reason: str | None) -> str:
    if not reason:
        return "-"
    return RELEASE_REASON_LABELS.get(reason, reason)


def is_custom_mapping(session: dict[str, Any]) -> bool:
    return session.get("acl_id") is None


def mapping_to_response(session: dict[str, Any], settings: Settings) -> dict[str, Any]:
    custom = is_custom_mapping(session)
    public_port = int(session["public_port"] or 0)
    service = session["service"]
    port_valid = is_port_in_auto_or_service_range(settings, service, public_port)
    if custom:
        start, end = settings.get_auto_port_range()
    else:
        start, end = get_port_range(settings, service)
    expire_at = session.get("expire_at")
    expire_display = format_acl_datetime_display(expire_at) if expire_at else "永久"
    remaining_label = None
    if expire_at and session.get("status") == "running":
        try:
            remaining_label = format_remaining_until(_parse_acl_datetime(expire_at))
        except (ValueError, TypeError):
            remaining_label = None
    elif not expire_at and session.get("status") == "running":
        remaining_label = "永久"
    status = session.get("status") or "running"
    ended_at = session.get("released_at") or session.get("deleted_at")
    return {
        "id": session["id"],
        "client_id": session["client_id"],
        "device_name": session.get("device_name", ""),
        "service": service,
        "nps_tunnel_id": session["nps_tunnel_id"],
        "public_host": session["public_host"],
        "public_port": public_port,
        "target_host": session["target_host"],
        "target_port": int(session["target_port"]),
        "ttl_minutes": session.get("ttl_minutes"),
        "status": status,
        "status_label": mapping_status_label(status),
        "created_at": session["created_at"],
        "created_at_display": format_acl_datetime_display(session.get("created_at")),
        "expire_at": expire_at,
        "expire_at_display": expire_display,
        "remaining_label": remaining_label,
        "deleted_at": session.get("deleted_at"),
        "released_at": session.get("released_at"),
        "ended_at_display": format_acl_datetime_display(ended_at) if ended_at else None,
        "release_reason": session.get("release_reason"),
        "release_reason_label": release_reason_label(session.get("release_reason")),
        "remark": session.get("remark", ""),
        "connect_text": build_connect_text(
            service,
            session["public_host"],
            public_port,
            settings,
            require_pool=False,
            target_port=int(session["target_port"]),
        ),
        "port_valid": port_valid,
        "port_range": {"start": start, "end": end},
        "username": session.get("username"),
    }


def session_to_response(session: dict[str, Any], settings: Settings) -> dict[str, Any]:
    return mapping_to_response(session, settings)


async def collect_blocked_ports(db: Database, nps: NpsClient) -> set[int]:
    blocked = set(db.list_reserved_public_ports())
    blocked.update(await nps.get_used_server_ports())
    return blocked


async def allocate_public_port(
    db: Database,
    nps: NpsClient,
    settings: Settings,
    service: str,
) -> int:
    service_key = service.lower()
    if service_key not in SERVICE_TARGETS:
        raise ValueError("不支持的服务类型")
    start, end = get_port_range(settings, service_key)
    blocked = await collect_blocked_ports(db, nps)
    for port in range(start, end + 1):
        if port not in blocked:
            return port
    raise PortAllocationError(f"{service_key} 端口池已满（{start}-{end}），无可用端口")


async def create_portal_tunnel(
    db: Database,
    nps: NpsClient,
    settings: Settings,
    user: dict[str, Any],
    client_id: int,
    service: str,
    *,
    device_name: str = "",
    remark: str = "",
) -> dict[str, Any]:
    service_key = service.lower()
    if service_key not in SERVICE_TARGETS:
        raise ValueError("不支持的服务类型")
    acl = db.get_acl_for_user_client(user["id"], client_id)
    if user["role"] != "admin" and not acl:
        raise PermissionError("无权访问该设备")
    if user["role"] != "admin":
        check_acl_can_apply(acl)  # type: ignore[arg-type]
        if db.list_running_sessions_for_user_client(user["id"], client_id):
            raise PermissionError("该设备已有运行中的调试端口")

    expire_at = resolve_acl_tunnel_expire_at(settings, acl) if acl else resolve_expire_at(
        settings, is_admin=user["role"] == "admin"
    )
    target_host, target_port = SERVICE_TARGETS[service_key]
    target = f"{target_host}:{target_port}"
    tunnel_remark = remark or f"portal-{service_key}-{user['username']}-c{client_id}"

    public_port = await allocate_public_port(db, nps, settings, service_key)
    validate_port_in_range(settings, service_key, public_port)

    tunnel_info = await nps.add_and_start_tunnel(
        client_id=client_id,
        target=target,
        remark=tunnel_remark,
        mode="tcp",
        port=str(public_port),
        service=service_key,
        expected_port=public_port,
    )

    nps_tunnel_id = int(tunnel_info["id"])
    assigned_port = int(tunnel_info["server_port"])
    validate_port_in_range(settings, service_key, assigned_port)

    session = db.create_tunnel_session(
        user_id=user["id"],
        client_id=client_id,
        acl_id=acl["id"] if acl else None,
        device_name=device_name or (acl["device_name"] if acl else ""),
        service=service_key,
        nps_tunnel_id=nps_tunnel_id,
        public_host=settings.nps_public_host,
        public_port=assigned_port,
        target_host=target_host,
        target_port=target_port,
        expire_at=expire_at,
        remark=str(tunnel_info.get("remark") or tunnel_remark),
    )
    if acl:
        db.mark_acl_in_use(int(acl["id"]))
    return session_to_response(session, settings)


def _complete_acl_for_session(db: Database, session: dict[str, Any]) -> None:
    acl_id = session.get("acl_id")
    db.complete_device_acl(
        int(session["user_id"]),
        int(session["client_id"]),
        int(acl_id) if acl_id else None,
    )


async def release_portal_tunnel(
    db: Database,
    nps: NpsClient,
    session: dict[str, Any],
    *,
    status: str = "deleted",
    release_reason: str = "",
) -> None:
    if session["status"] in {"released", "expired", "deleted", "failed", "cleanup_failed"}:
        return
    nps_id = session.get("nps_tunnel_id")
    if nps_id:
        try:
            await nps.stop_tunnel(int(nps_id))
        except Exception:
            pass
        try:
            await nps.delete_tunnel(int(nps_id))
        except Exception as exc:
            if session["status"] == "running":
                db.mark_tunnel_deleted(session["id"], status="failed", release_reason="nps_delete_failed")
                raise exc
    if session.get("acl_id") and status == "deleted":
        final_status = "released"
    else:
        final_status = status
    reason = release_reason or (
        "user_released" if final_status in {"deleted", "released"} else final_status
    )
    db.mark_tunnel_deleted(session["id"], status=final_status, release_reason=reason)
    if final_status in {"released", "expired"} and session.get("acl_id"):
        _complete_acl_for_session(db, session)


async def revoke_device_acl(
    db: Database,
    nps: NpsClient,
    acl_id: int,
) -> None:
    acl = db.get_acl_by_id(acl_id)
    if not acl:
        return
    for session in db.list_running_sessions_for_user_client(int(acl["user_id"]), int(acl["client_id"])):
        await release_portal_tunnel(db, nps, session, status="released")
    db.delete_device_acl(acl_id)


async def cleanup_invalid_tunnel_sessions(
    db: Database,
    nps: NpsClient,
    settings: Settings,
) -> int:
    """Mark invalid local sessions and attempt NPS tunnel deletion."""
    affected = db.mark_invalid_tunnel_sessions(settings)
    cleaned = 0
    for session in affected:
        if session.get("status") == "running":
            _complete_acl_for_session(db, session)
        nps_id = session.get("nps_tunnel_id")
        if nps_id:
            try:
                await nps.stop_tunnel(int(nps_id))
            except Exception:
                pass
            try:
                await nps.delete_tunnel(int(nps_id))
            except Exception:
                pass
        cleaned += 1
    return cleaned


async def cleanup_expired_sessions(db: Database, nps: NpsClient, settings: Settings) -> int:
    expired = db.list_expired_active_sessions()
    count = 0
    for session in expired:
        try:
            await release_portal_tunnel(db, nps, session, status="expired", release_reason="ttl_expired")
            db.add_audit_log(
                user_id=session["user_id"],
                username="system",
                role="system",
                action="port_mapping_auto_expire",
                target_type="port_mapping",
                target_id=str(session["id"]),
                detail=f"client_id={session['client_id']} port={session['public_port']}",
            )
            count += 1
        except Exception as exc:
            db.mark_tunnel_deleted(session["id"], status="cleanup_failed")
            db.add_audit_log(
                user_id=session["user_id"],
                username="system",
                role="system",
                action="tunnel_cleanup_failed",
                target_type="tunnel_session",
                target_id=str(session["id"]),
                detail=str(exc),
            )
    return count


def is_socket_port_in_use(port: int, host: str = "0.0.0.0") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return False
        except OSError:
            return True


def resolve_target_host(settings: Settings, target_host: str | None) -> str:
    host = (target_host or "").strip()
    if not host:
        host = DEFAULT_TARGET_HOST
    if settings.allow_custom_target_host:
        return host
    allowed = settings.get_target_host_whitelist()
    if host.lower() not in allowed:
        raise PermissionError(f"目标地址不在白名单内，允许: {', '.join(sorted(allowed))}")
    return host


def validate_target_host(settings: Settings, target_host: str | None) -> None:
    resolve_target_host(settings, target_host)


def validate_user_ttl_minutes(settings: Settings, ttl_minutes: int | None) -> None:
    if ttl_minutes is None:
        return
    if ttl_minutes < settings.user_ttl_min_minutes:
        raise ValueError(f"使用时长不能少于 {settings.user_ttl_min_minutes} 分钟")
    if ttl_minutes > settings.user_ttl_max_minutes:
        raise ValueError(f"使用时长不能超过 {settings.user_ttl_max_minutes} 分钟")


def resolve_mapping_expire_at(ttl_minutes: int | None) -> str | None:
    if ttl_minutes is None:
        return None
    return (datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)).isoformat()


def validate_mapping_limits(db: Database, settings: Settings, user_id: int) -> None:
    user_count = db.count_running_mappings(user_id)
    if user_count >= settings.max_running_mappings_per_user:
        raise PermissionError(
            f"已达到个人最大运行映射数（{settings.max_running_mappings_per_user}）"
        )
    total = db.count_running_mappings()
    if total >= settings.max_running_mappings_total:
        raise PortAllocationError(
            f"系统运行映射已达上限（{settings.max_running_mappings_total}）",
            status_code=409,
        )


def validate_port_mapping_request(
    settings: Settings,
    *,
    target_host: str | None,
    target_port: int,
    ttl_minutes: int | None,
) -> str:
    if target_port < 1 or target_port > 65535:
        raise ValueError("目标端口必须在 1-65535 之间")
    validate_target_host(settings, target_host)
    validate_user_ttl_minutes(settings, ttl_minutes)
    return MAPPING_SERVICE


async def collect_blocked_ports_auto(
    db: Database,
    nps: NpsClient,
    settings: Settings,
) -> set[int]:
    blocked = set(db.list_reserved_public_ports())
    blocked.update(await nps.get_used_server_ports())
    blocked.update(settings.get_auto_port_blocklist())
    return blocked


def validate_auto_port(settings: Settings, port: int) -> None:
    if not port or int(port) <= 0:
        raise PortValidationError("未获取到有效公网端口", status_code=502)
    if port in settings.get_auto_port_blocklist():
        raise PortValidationError(f"端口 {port} 在禁止分配列表中", status_code=400)
    start, end = settings.get_auto_port_range()
    if port < start or port > end:
        raise PortValidationError(
            f"端口 {port} 不在允许区间 {start}-{end}",
            status_code=400,
        )


async def allocate_auto_public_endpoint(
    db: Database,
    nps: NpsClient,
    settings: Settings,
) -> tuple[str, int]:
    hosts = settings.get_public_hosts()
    if not hosts:
        raise PortAllocationError("未配置公网 IP（NPS_PUBLIC_HOST / NPS_PUBLIC_HOSTS）")
    public_host = hosts[0]
    start, end = settings.get_auto_port_range()
    blocked = await collect_blocked_ports_auto(db, nps, settings)
    span = end - start + 1
    offset_start = random.randint(0, span - 1) if span > 0 else 0
    for i in range(span):
        port = start + (offset_start + i) % span
        if port in blocked:
            continue
        if settings.auto_port_socket_check and is_socket_port_in_use(port):
            blocked.add(port)
            continue
        return public_host, port
    raise PortAllocationError("当前无可用公网端口，请稍后再试", status_code=409)


async def create_port_mapping(
    db: Database,
    nps: NpsClient,
    settings: Settings,
    user: dict[str, Any],
    *,
    client_id: int,
    target_host: str | None,
    target_port: int,
    ttl_minutes: int | None,
) -> dict[str, Any]:
    service_key = validate_port_mapping_request(
        settings,
        target_host=target_host,
        target_port=target_port,
        ttl_minutes=ttl_minutes,
    )
    validate_mapping_limits(db, settings, int(user["id"]))

    if client_id <= 0:
        raise ValueError("请选择客户端设备")
    device = await nps.get_device_light(client_id)
    if not device:
        raise ValueError("客户端设备不存在或无权访问（请检查备注前缀过滤）")

    resolved_host = resolve_target_host(settings, target_host)
    device_remark = str(device.get("remark") or "")
    expire_at = resolve_mapping_expire_at(ttl_minutes)
    target = f"{resolved_host}:{int(target_port)}"
    tunnel_remark = f"portal-map-{user['username']}-c{client_id}"

    public_host, public_port = await allocate_auto_public_endpoint(db, nps, settings)
    validate_auto_port(settings, public_port)

    tunnel_info = await nps.add_and_start_tunnel(
        client_id=client_id,
        target=target,
        remark=tunnel_remark,
        mode="tcp",
        port=str(public_port),
        service=service_key,
        expected_port=public_port,
    )

    nps_tunnel_id = int(tunnel_info["id"])
    assigned_port = int(tunnel_info["server_port"])
    validate_auto_port(settings, assigned_port)

    session = db.create_tunnel_session(
        user_id=user["id"],
        client_id=client_id,
        acl_id=None,
        device_name=device_remark,
        service=service_key,
        nps_tunnel_id=nps_tunnel_id,
        public_host=public_host,
        public_port=assigned_port,
        target_host=resolved_host,
        target_port=int(target_port),
        expire_at=expire_at,
        remark=str(tunnel_info.get("remark") or tunnel_remark),
        ttl_minutes=ttl_minutes,
    )
    return mapping_to_response(session, settings)


async def search_mapping_clients(
    nps: NpsClient,
    keyword: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search NPS clients by remark name or client id (respects remark prefix filter)."""
    kw = keyword.strip().lower()
    if not kw:
        return []
    devices = await nps.get_devices(include_tunnels=False)
    results: list[dict[str, Any]] = []
    for device in devices:
        remark = str(device.get("remark") or "")
        cid = int(device.get("id") or 0)
        if not cid:
            continue
        if kw == str(cid) or kw in remark.lower():
            results.append(
            {
                "client_id": cid,
                "remark": remark,
                "device_name": remark,
                "status": device.get("status") or "offline",
                "version": device.get("version") or "",
            }
        )
        if len(results) >= limit:
            break
    return results
