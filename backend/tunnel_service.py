import asyncio
import random
from datetime import datetime, timedelta, timezone
import socket
from typing import Any

from config import Settings
from database import Database
from nps_api import NpsClient

DEFAULT_TARGET_HOST = "127.0.0.1"
MAPPING_SERVICE = "tcp"


class PortValidationError(ValueError):
    """Raised when public_port is missing or outside the configured pool."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class PortAllocationError(RuntimeError):
    """Raised when no port is available in the configured range."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def format_datetime_display(value: str | None) -> str | None:
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


def _parse_acl_datetime(value: str) -> datetime:
    """Parse admin/UI datetime; naive values are treated as UTC+8 (China local)."""
    s = str(value).strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
    return dt.astimezone(timezone.utc)


def build_mapping_connect_text(
    settings: Settings,
    *,
    public_host: str,
    public_port: int,
    target_port: int,
) -> str:
    """Generate connect command from target port."""
    tp = int(target_port)
    if tp == 22:
        return f"ssh {settings.default_ssh_user}@{public_host} -p {public_port}"
    if tp in (80, 8000, 8080):
        return f"http://{public_host}:{public_port}"
    if tp == 443:
        return f"https://{public_host}:{public_port}"
    if tp == 2345:
        return f"target remote {public_host}:{public_port}"
    return f"{public_host}:{public_port}"


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


def mapping_to_response(session: dict[str, Any], settings: Settings) -> dict[str, Any]:
    public_port = int(session["public_port"] or 0)
    start, end = settings.get_auto_port_range()
    port_valid = settings.is_port_in_auto_range(public_port) and public_port not in settings.get_auto_port_blocklist()
    expire_at = session.get("expire_at")
    expire_display = format_datetime_display(expire_at) if expire_at else "永久"
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
        "service": session.get("service") or MAPPING_SERVICE,
        "nps_tunnel_id": session["nps_tunnel_id"],
        "public_host": session["public_host"],
        "public_port": public_port,
        "target_host": session["target_host"],
        "target_port": int(session["target_port"]),
        "ttl_minutes": session.get("ttl_minutes"),
        "status": status,
        "status_label": mapping_status_label(status),
        "created_at": session["created_at"],
        "created_at_display": format_datetime_display(session.get("created_at")),
        "expire_at": expire_at,
        "expire_at_display": expire_display,
        "remaining_label": remaining_label,
        "deleted_at": session.get("deleted_at"),
        "released_at": session.get("released_at"),
        "ended_at_display": format_datetime_display(ended_at) if ended_at else None,
        "release_reason": session.get("release_reason"),
        "release_reason_label": release_reason_label(session.get("release_reason")),
        "remark": session.get("remark", ""),
        "connect_text": build_mapping_connect_text(
            settings,
            public_host=session["public_host"],
            public_port=public_port,
            target_port=int(session["target_port"]),
        ),
        "port_valid": port_valid,
        "port_range": {"start": start, "end": end},
        "username": session.get("username"),
    }


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
    final_status = status
    reason = release_reason or (
        "user_released" if final_status == "deleted" else final_status
    )
    db.mark_tunnel_deleted(session["id"], status=final_status, release_reason=reason)


async def cleanup_invalid_tunnel_sessions(
    db: Database,
    nps: NpsClient,
    settings: Settings,
) -> int:
    """Mark invalid local sessions and attempt NPS tunnel deletion."""
    affected = db.mark_invalid_tunnel_sessions(settings)
    cleaned = 0
    for session in affected:
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
                target_type="port_mapping",
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
) -> None:
    if target_port < 1 or target_port > 65535:
        raise ValueError("目标端口必须在 1-65535 之间")
    validate_target_host(settings, target_host)
    validate_user_ttl_minutes(settings, ttl_minutes)


async def collect_blocked_ports_auto(
    db: Database,
    nps: NpsClient,
    settings: Settings,
    *,
    extra_blocked: set[int] | None = None,
) -> set[int]:
    blocked = set(db.list_reserved_public_ports())
    blocked.update(settings.get_auto_port_blocklist())
    if extra_blocked:
        blocked.update(extra_blocked)
    # NPS 链路不稳时全量扫隧道易超时；失败则降级为仅本地占用，创建冲突再换端口
    try:
        blocked.update(await asyncio.wait_for(nps.get_used_server_ports(), timeout=12.0))
    except Exception:
        pass
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
    *,
    extra_blocked: set[int] | None = None,
) -> tuple[str, int]:
    hosts = settings.get_public_hosts()
    if not hosts:
        raise PortAllocationError("未配置公网 IP（NPS_PUBLIC_HOST / NPS_PUBLIC_HOSTS）")
    public_host = hosts[0]
    start, end = settings.get_auto_port_range()
    blocked = await collect_blocked_ports_auto(db, nps, settings, extra_blocked=extra_blocked)
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
    validate_port_mapping_request(
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

    attempted_ports: set[int] = set()
    tunnel_info: dict[str, Any] | None = None
    public_host = ""
    last_exc: Exception | None = None
    for _ in range(5):
        public_host, public_port = await allocate_auto_public_endpoint(
            db, nps, settings, extra_blocked=attempted_ports
        )
        validate_auto_port(settings, public_port)
        attempted_ports.add(public_port)
        try:
            tunnel_info = await nps.add_and_start_tunnel(
                client_id=client_id,
                target=target,
                remark=tunnel_remark,
                mode="tcp",
                port=str(public_port),
                service=MAPPING_SERVICE,
                expected_port=public_port,
            )
            break
        except Exception as exc:
            last_exc = exc
            continue
    if tunnel_info is None:
        raise last_exc or RuntimeError("创建映射失败：多次尝试均未成功")

    nps_tunnel_id = int(tunnel_info["id"])
    assigned_port = int(tunnel_info["server_port"])
    validate_auto_port(settings, assigned_port)

    session = db.create_tunnel_session(
        user_id=user["id"],
        client_id=client_id,
        device_name=device_remark,
        service=MAPPING_SERVICE,
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
    if not results:
        hint = await nps.explain_prefix_filter(keyword)
        if hint:
            raise ValueError(hint)
    return results
