import asyncio
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware

from auth import (
    authenticate_user,
    client_ip,
    create_access_token,
    get_current_user,
    require_admin,
    user_public,
)
from config import Settings, get_settings
from database import Database, get_db, init_db
from nps_api import NpsClient
from schemas import (
    AuditLogCleanupRequest,
    AuditLogCleanupResponse,
    AuditLogListResponse,
    AuditLogResponse,
    DashboardSummary,
    DeviceSummary,
    HealthResponse,
    LoginRequest,
    LoginResponse,
    ResetPasswordRequest,
    ClientSearchItem,
    PortMappingCreateRequest,
    PortMappingResponse,
    UserCreateRequest,
    UserPublic,
    UserUpdateRequest,
)
from tunnel_service import (
    PortAllocationError,
    PortValidationError,
    cleanup_expired_sessions,
    cleanup_invalid_tunnel_sessions,
    create_port_mapping,
    mapping_to_response,
    search_mapping_clients,
    release_portal_tunnel,
)


def get_nps_client(request: Request) -> NpsClient:
    return request.app.state.nps_client


def _parse_flow_to_bytes(flow: str) -> float:
    if not flow:
        return 0.0
    flow = flow.strip().upper()
    match = re.match(r"^([\d.]+)\s*([KMGT]?B)(?:/S)?$", flow.replace(" ", ""))
    if not match:
        return 0.0
    value = float(match.group(1))
    unit = match.group(2)
    multipliers = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
    return value * multipliers.get(unit, 1)


def _format_bytes(total: float) -> str:
    if total <= 0:
        return "0B"
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while total >= 1024 and idx < len(units) - 1:
        total /= 1024
        idx += 1
    return f"{total:.2f}{units[idx]}"


async def _nps_devices(nps: NpsClient) -> list[dict[str, Any]]:
    try:
        return await nps.get_devices()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"无法连接 NPS: {exc}") from exc


def _audit(
    db: Database,
    user: dict[str, Any] | None,
    request: Request,
    action: str,
    target_type: str = "",
    target_id: str = "",
    detail: str = "",
) -> None:
    db.add_audit_log(
        user_id=user["id"] if user else None,
        username=user["username"] if user else "anonymous",
        role=user["role"] if user else "",
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        ip=client_ip(request),
    )


def _audit_log_cutoff(days: int) -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return cutoff.isoformat()


def cleanup_old_audit_logs(db: Database, settings: Settings) -> int:
    days = settings.audit_log_retention_days
    if days <= 0:
        return 0
    return db.delete_audit_logs_before(_audit_log_cutoff(days))


async def cleanup_loop(settings: Settings) -> None:
    db = init_db(settings)
    nps = NpsClient(settings)
    while True:
        try:
            await cleanup_expired_sessions(db, nps, settings)
        except Exception:
            pass
        try:
            deleted = cleanup_old_audit_logs(db, settings)
            if deleted:
                print(f"[portal] cleaned {deleted} audit log(s) older than {settings.audit_log_retention_days} days")
        except Exception:
            pass
        await asyncio.sleep(settings.cleanup_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    db = init_db(settings)
    db.init_schema(settings)
    nps = NpsClient(settings)
    app.state.nps_client = nps
    try:
        cleaned = await cleanup_invalid_tunnel_sessions(db, nps, settings)
        if cleaned:
            print(f"[portal] cleaned {cleaned} invalid tunnel session(s)")
    except Exception as exc:
        print(f"[portal] invalid session cleanup warning: {exc}")
    try:
        log_cleaned = cleanup_old_audit_logs(db, settings)
        if log_cleaned:
            print(f"[portal] cleaned {log_cleaned} audit log(s) on startup")
    except Exception as exc:
        print(f"[portal] audit log cleanup warning: {exc}")
    task = asyncio.create_task(cleanup_loop(settings))
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await app.state.nps_client.close()


app = FastAPI(title="NPS Remote Debug Portal API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthResponse)
async def health(settings: Annotated[Settings, Depends(get_settings)]):
    return HealthResponse(status="ok", nps_configured=bool(settings.nps_auth_key))


@app.get("/api/config")
async def portal_config(
    _: Annotated[dict[str, Any], Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return {
        "user_ttl_options": settings.get_user_ttl_options(),
        "default_ttl_minutes": settings.user_ttl_default_minutes,
        "user_ttl_min_minutes": settings.user_ttl_min_minutes,
        "user_ttl_max_minutes": settings.user_ttl_max_minutes,
        "allow_custom_target_host": settings.allow_custom_target_host,
        "target_host_whitelist": list(settings.get_target_host_whitelist()),
        "default_ssh_user": settings.default_ssh_user,
        "public_host": settings.nps_public_host,
        "public_hosts": settings.get_public_hosts(),
        "auto_port_range": {
            "start": settings.auto_port_start,
            "end": settings.auto_port_end,
        },
        "max_running_mappings_per_user": settings.max_running_mappings_per_user,
        "allowed_remark_prefix": settings.allowed_remark_prefix,
    }


@app.post("/api/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[Database, Depends(get_db)],
):
    user = authenticate_user(db, body.username, body.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    token = create_access_token(user, settings)
    _audit(db, user, request, "login")
    return LoginResponse(access_token=token, user=user_public(user))


@app.get("/api/me", response_model=UserPublic)
async def me(user: Annotated[dict[str, Any], Depends(get_current_user)]):
    return user_public(user)


@app.post("/api/logout")
async def logout(
    request: Request,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    db: Annotated[Database, Depends(get_db)],
):
    _audit(db, user, request, "logout")
    return {"status": "ok"}


@app.get("/api/admin/dashboard/summary", response_model=DashboardSummary)
async def admin_dashboard(
    _: Annotated[dict[str, Any], Depends(require_admin)],
    db: Annotated[Database, Depends(get_db)],
    nps: Annotated[NpsClient, Depends(get_nps_client)],
):
    devices = await _nps_devices(nps)
    online = sum(1 for d in devices if d["status"] == "online")
    sessions = [s for s in db.list_tunnel_sessions() if s["status"] == "running"]
    return DashboardSummary(
        total_devices=len(devices),
        online_devices=online,
        offline_devices=len(devices) - online,
        open_connections=sum(1 for d in devices if d["is_open"]),
        total_inlet_flow=_format_bytes(sum(_parse_flow_to_bytes(d["inlet_flow"]) for d in devices)),
        total_export_flow=_format_bytes(sum(_parse_flow_to_bytes(d["export_flow"]) for d in devices)),
        active_tunnel_sessions=len(sessions),
        total_users=len(db.list_users()),
    )


@app.get("/api/admin/devices", response_model=list[DeviceSummary])
async def admin_devices(
    _: Annotated[dict[str, Any], Depends(require_admin)],
    nps: Annotated[NpsClient, Depends(get_nps_client)],
):
    return await _nps_devices(nps)


@app.get("/api/admin/users", response_model=list[UserPublic])
async def admin_list_users(
    _: Annotated[dict[str, Any], Depends(require_admin)],
    db: Annotated[Database, Depends(get_db)],
):
    return [user_public(u) for u in db.list_users()]


@app.post("/api/admin/users", response_model=UserPublic)
async def admin_create_user(
    body: UserCreateRequest,
    request: Request,
    admin: Annotated[dict[str, Any], Depends(require_admin)],
    db: Annotated[Database, Depends(get_db)],
):
    if body.role not in {"admin", "user"}:
        raise HTTPException(status_code=400, detail="无效的角色")
    if db.get_user_by_username(body.username):
        raise HTTPException(status_code=400, detail="用户名已存在")
    user = db.create_user(body.username, body.password, body.role)
    _audit(db, admin, request, "create_user", "user", str(user["id"]), body.username)
    return user_public(user)


@app.put("/api/admin/users/{user_id}", response_model=UserPublic)
async def admin_update_user(
    user_id: int,
    body: UserUpdateRequest,
    request: Request,
    admin: Annotated[dict[str, Any], Depends(require_admin)],
    db: Annotated[Database, Depends(get_db)],
):
    if user_id == admin["id"] and body.status == "disabled":
        raise HTTPException(status_code=400, detail="不能禁用当前登录账号")
    user = db.update_user(user_id, **body.model_dump(exclude_unset=True))
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    _audit(db, admin, request, "update_user", "user", str(user_id))
    return user_public(user)


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(
    user_id: int,
    request: Request,
    admin: Annotated[dict[str, Any], Depends(require_admin)],
    db: Annotated[Database, Depends(get_db)],
):
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="不能删除当前登录账号")
    if not db.delete_user(user_id):
        raise HTTPException(status_code=404, detail="用户不存在")
    _audit(db, admin, request, "delete_user", "user", str(user_id))
    return {"status": "ok"}


@app.post("/api/admin/users/{user_id}/reset-password")
async def admin_reset_password(
    user_id: int,
    body: ResetPasswordRequest,
    request: Request,
    admin: Annotated[dict[str, Any], Depends(require_admin)],
    db: Annotated[Database, Depends(get_db)],
):
    if not db.reset_password(user_id, body.password):
        raise HTTPException(status_code=404, detail="用户不存在")
    _audit(db, admin, request, "reset_password", "user", str(user_id))
    return {"status": "ok"}


@app.get("/api/admin/port-mappings", response_model=list[PortMappingResponse])
async def admin_port_mappings(
    _: Annotated[dict[str, Any], Depends(require_admin)],
    db: Annotated[Database, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    status: str | None = Query(None),
    keyword: str | None = Query(None),
    history: bool = Query(False, description="true=仅历史（非运行中）"),
):
    if history:
        sessions = db.list_tunnel_sessions(
            include_deleted=True,
            status=status,
            keyword=keyword,
            exclude_statuses=["running"],
        )
    else:
        sessions = db.list_tunnel_sessions(
            include_deleted=True,
            status=status or "running",
            keyword=keyword,
        )
    return [mapping_to_response(s, settings) for s in sessions]


@app.delete("/api/admin/port-mappings/{session_id}")
async def admin_release_port_mapping(
    session_id: int,
    request: Request,
    admin: Annotated[dict[str, Any], Depends(require_admin)],
    db: Annotated[Database, Depends(get_db)],
    nps: Annotated[NpsClient, Depends(get_nps_client)],
):
    session = db.get_tunnel_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="映射不存在")
    if session["status"] in {"released", "expired", "deleted", "failed"}:
        raise HTTPException(status_code=400, detail="映射已结束")
    try:
        await release_portal_tunnel(
            db, nps, session, status="deleted", release_reason="admin_force_release"
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"释放失败: {exc}") from exc
    _audit(db, admin, request, "release_port_mapping", "port_mapping", str(session_id))
    return {"status": "ok"}


@app.get("/api/admin/audit-logs/actions")
async def admin_audit_log_actions(
    _: Annotated[dict[str, Any], Depends(require_admin)],
    db: Annotated[Database, Depends(get_db)],
):
    return {"actions": db.list_audit_log_actions()}


@app.get("/api/admin/audit-logs", response_model=AuditLogListResponse)
async def admin_audit_logs(
    _: Annotated[dict[str, Any], Depends(require_admin)],
    db: Annotated[Database, Depends(get_db)],
    username: str | None = Query(None),
    role: str | None = Query(None),
    action: str | None = Query(None),
    target_type: str | None = Query(None),
    keyword: str | None = Query(None),
    start_at: str | None = Query(None, description="ISO8601 起始时间"),
    end_at: str | None = Query(None, description="ISO8601 结束时间"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    return db.search_audit_logs(
        username=username,
        role=role,
        action=action,
        target_type=target_type,
        keyword=keyword,
        start_at=start_at,
        end_at=end_at,
        limit=limit,
        offset=offset,
    )


@app.post("/api/admin/audit-logs/cleanup", response_model=AuditLogCleanupResponse)
async def admin_cleanup_audit_logs(
    body: AuditLogCleanupRequest,
    request: Request,
    admin: Annotated[dict[str, Any], Depends(require_admin)],
    db: Annotated[Database, Depends(get_db)],
):
    cutoff_at = _audit_log_cutoff(body.older_than_days)
    deleted = db.delete_audit_logs_before(cutoff_at)
    _audit(
        db,
        admin,
        request,
        "cleanup_audit_logs",
        "",
        "",
        f"deleted={deleted} older_than_days={body.older_than_days}",
    )
    return AuditLogCleanupResponse(
        deleted=deleted,
        older_than_days=body.older_than_days,
        cutoff_at=cutoff_at,
    )


@app.get("/api/my/clients/search", response_model=list[ClientSearchItem])
async def my_search_clients(
    keyword: str = Query(..., min_length=1, description="设备备注名或客户端 ID"),
    user: Annotated[dict[str, Any], Depends(get_current_user)] = ...,
    nps: Annotated[NpsClient, Depends(get_nps_client)] = ...,
):
    if user["role"] == "admin":
        raise HTTPException(status_code=403, detail="请使用管理员设备管理页面")
    try:
        return await search_mapping_clients(nps, keyword.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/my/port-mappings", response_model=list[PortMappingResponse])
async def my_list_port_mappings(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    db: Annotated[Database, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    status: str | None = Query(None, description="running / expired / deleted / failed"),
    keyword: str | None = Query(None, description="客户端 / 目标 / 公网端口"),
    history: bool = Query(False, description="true=仅历史（非运行中）"),
):
    if history:
        sessions = db.list_tunnel_sessions(
            user_id=user["id"],
            include_deleted=True,
            status=status,
            keyword=keyword,
            exclude_statuses=["running"],
        )
    else:
        sessions = db.list_tunnel_sessions(
            user_id=user["id"],
            include_deleted=True,
            status=status or "running",
            keyword=keyword,
        )
    return [mapping_to_response(s, settings) for s in sessions]


@app.post("/api/my/port-mappings", response_model=PortMappingResponse)
async def my_create_port_mapping(
    body: PortMappingCreateRequest,
    request: Request,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    db: Annotated[Database, Depends(get_db)],
    nps: Annotated[NpsClient, Depends(get_nps_client)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    if user["role"] == "admin":
        raise HTTPException(status_code=403, detail="管理员请使用普通用户账号申请端口映射")
    try:
        session = await create_port_mapping(
            db,
            nps,
            settings,
            user,
            client_id=body.client_id,
            target_host=body.target_host,
            target_port=body.target_port,
            ttl_minutes=body.ttl_minutes,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PortValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except PortAllocationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"创建映射失败: {exc}") from exc
    _audit(
        db,
        user,
        request,
        "create_port_mapping",
        "port_mapping",
        str(session["id"]),
        f"client={body.client_id} {body.target_host or '127.0.0.1'}:{body.target_port} ttl={body.ttl_minutes or 'permanent'} port={session['public_port']}",
    )
    return session


@app.delete("/api/my/port-mappings/{session_id}")
async def my_release_port_mapping(
    session_id: int,
    request: Request,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    db: Annotated[Database, Depends(get_db)],
    nps: Annotated[NpsClient, Depends(get_nps_client)],
):
    session = db.get_tunnel_session(session_id)
    if not session or session["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="映射不存在或无权操作")
    if session["status"] in {"released", "expired", "deleted", "failed"}:
        raise HTTPException(status_code=400, detail="映射已结束")
    try:
        await release_portal_tunnel(
            db, nps, session, status="deleted", release_reason="user_released"
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"释放失败: {exc}") from exc
    _audit(db, user, request, "release_port_mapping", "port_mapping", str(session_id))
    return {"status": "ok"}
