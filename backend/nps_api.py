import asyncio
import hashlib
import re
import time
from typing import Any

import httpx

from config import Settings


def mask_ip(ip: str, enabled: bool = True) -> str:
    if not ip or not enabled:
        return ip or ""
    ip = ip.strip()
    if ":" in ip and not re.match(r"^\d+\.\d+\.\d+\.\d+$", ip):
        return ip
    parts = ip.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.xxx.xxx"
    return ip


def _normalize_flow(value: Any) -> str:
    if value is None:
        return "0B"
    if isinstance(value, str) and value.strip():
        return value
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if num <= 0:
        return "0B"
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while num >= 1024 and idx < len(units) - 1:
        num /= 1024
        idx += 1
    return f"{num:.2f}{units[idx]}"


def _extract_client_flows(client: dict[str, Any]) -> tuple[str, str, str]:
    flow = client.get("Flow") or {}
    rate_obj = client.get("Rate") or {}

    inlet = flow.get("InletFlow") if isinstance(flow, dict) else None
    export = flow.get("ExportFlow") if isinstance(flow, dict) else None
    rate = rate_obj.get("NowRate") if isinstance(rate_obj, dict) else rate_obj

    inlet = inlet if inlet is not None else client.get("InletFlow") or client.get("inlet_flow")
    export = export if export is not None else client.get("ExportFlow") or client.get("export_flow")
    rate = rate if rate is not None else client.get("Rate") or client.get("rate") or "0B/S"

    inlet_text = _normalize_flow(inlet)
    export_text = _normalize_flow(export)
    rate_text = _normalize_flow(rate)
    if not str(rate_text).endswith("/S"):
        rate_text = f"{rate_text}/S"
    return inlet_text, export_text, rate_text


def _client_is_online(client: dict[str, Any]) -> bool:
    if client.get("IsConnect") is True:
        return True
    status = str(client.get("status", "")).lower()
    if status in {"online", "true", "1"}:
        return True
    if client.get("IsConnect") in (1, "1"):
        return True
    return False


def _client_status(client: dict[str, Any]) -> str:
    return "online" if _client_is_online(client) else "offline"


def _matches_prefix(remark: str, prefix: str) -> bool:
    if not prefix:
        return True
    return remark.startswith(prefix)


def _extract_client_addr(client: dict[str, Any]) -> str:
    for key in ("Addr", "addr", "Ip", "ip", "ClientAddr", "client_addr"):
        value = client.get(key)
        if value:
            return str(value)
    return ""


def _extract_tunnel_client_id(tunnel: dict[str, Any]) -> int:
    for key in ("ClientId", "client_id"):
        value = tunnel.get(key)
        if value is not None:
            return int(value)
    client = tunnel.get("Client") or tunnel.get("client")
    if isinstance(client, dict):
        cid = client.get("Id") or client.get("id")
        if cid is not None:
            return int(cid)
    return 0


def _extract_tunnel_target(tunnel: dict[str, Any]) -> str:
    target = tunnel.get("Target") or tunnel.get("target")
    if isinstance(target, dict):
        return str(target.get("TargetStr") or target.get("target_str") or "")
    if target:
        return str(target)
    for key in ("TargetStr", "target_str", "TargetAddr", "target_addr"):
        value = tunnel.get(key)
        if value:
            return str(value)
    return ""


def _extract_tunnel_server_port(tunnel: dict[str, Any]) -> int:
    for key in ("Port", "port", "ServerPort", "server_port"):
        value = tunnel.get(key)
        if value is not None and str(value).strip() != "":
            port = int(value)
            if port > 0:
                return port
    return 0


def _tunnel_matches(
    tunnel: dict[str, Any],
    *,
    client_id: int,
    remark: str,
    server_port: int,
    target: str,
) -> bool:
    if _extract_tunnel_client_id(tunnel) != client_id:
        return False
    if str(tunnel.get("Remark") or tunnel.get("remark") or "") != remark:
        return False
    if _extract_tunnel_server_port(tunnel) != server_port:
        return False
    if _extract_tunnel_target(tunnel) != target:
        return False
    return True


def _tunnel_status(tunnel: dict[str, Any]) -> str:
    status = tunnel.get("Status")
    if status is True or str(status).lower() in {"true", "1", "running", "open", "开放"}:
        return "running"
    run_status = str(tunnel.get("RunStatus", "")).lower()
    if run_status in {"true", "1", "running", "open", "开放"}:
        return "running"
    return "stopped"


def _build_connect_text(tunnel: dict[str, Any], public_host: str) -> str:
    remark = str(tunnel.get("Remark") or tunnel.get("remark") or "").lower()
    port = _extract_tunnel_server_port(tunnel)
    if not port:
        return ""
    if "ssh" in remark:
        return f"ssh user@{public_host} -p {port}"
    if any(k in remark for k in ("web", "http", "https")):
        scheme = "https" if "https" in remark else "http"
        return f"{scheme}://{public_host}:{port}"
    if "gdb" in remark:
        return f"target remote {public_host}:{port}"
    mode = str(tunnel.get("Mode") or tunnel.get("mode") or "tcp").lower()
    if mode == "http":
        return f"http://{public_host}:{port}"
    return f"{public_host}:{port}"


class NpsClient:
    AUTH_CACHE_SECONDS = 15
    CLIENT_CACHE_SECONDS = 8

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.nps_base_url.rstrip("/")
        self._http: httpx.AsyncClient | None = None
        self._auth_cache: tuple[str, float] | None = None
        self._clients_cache: tuple[list[dict[str, Any]], float] | None = None
        self._request_lock = asyncio.Lock()

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(20.0, connect=5.0),
                follow_redirects=False,
                limits=httpx.Limits(max_connections=30, max_keepalive_connections=15),
            )
        return self._http

    async def close(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()
        self._http = None

    def invalidate_cache(self) -> None:
        self._clients_cache = None

    async def _get_timestamp(self, *, force_refresh: bool = False) -> str:
        now = time.time()
        if not force_refresh and self._auth_cache and self._auth_cache[1] > now:
            return self._auth_cache[0]

        try:
            http = await self._get_http()
            response = await http.post(f"{self.base_url}/auth/gettime")
            if response.status_code == 200:
                data = response.json()
                server_time = data.get("time") or data.get("Time")
                if server_time is not None:
                    ts = str(int(server_time))
                    self._auth_cache = (ts, now + self.AUTH_CACHE_SECONDS)
                    return ts
        except Exception:
            pass

        ts = str(int(time.time()))
        self._auth_cache = (ts, now + self.AUTH_CACHE_SECONDS)
        return ts

    async def _request(self, path: str, data: dict[str, Any] | None = None, *, retry: bool = True) -> Any:
        if not self.settings.nps_auth_key:
            raise RuntimeError("NPS_AUTH_KEY 未配置")

        async with self._request_lock:
            timestamp = await self._get_timestamp()
            digest = hashlib.md5(f"{self.settings.nps_auth_key}{timestamp}".encode()).hexdigest()
            form: dict[str, Any] = {
                "auth_key": digest,
                "timestamp": timestamp,
                "order": "asc",
                "offset": "0",
                "limit": "10000",
            }
            if data:
                form.update({k: v for k, v in data.items() if v is not None})

        http = await self._get_http()
        response = await http.post(f"{self.base_url}{path}", data=form)

        if response.status_code in (301, 302, 303, 307, 308):
            raise RuntimeError(
                f"NPS 返回重定向 ({response.status_code})，请检查 NPS_BASE_URL 是否正确，"
                f"以及 nps.conf 中 auth_key 是否已启用"
            )

        if retry and response.status_code in (401, 403):
            self._auth_cache = None
            return await self._request(path, data, retry=False)

        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(f"NPS 返回非 JSON 响应: {response.text[:200]}") from exc

        if isinstance(payload, dict):
            if payload.get("status") is False:
                msg = payload.get("msg") or payload.get("message") or "未知错误"
                raise RuntimeError(f"NPS API 错误: {msg}")
            if "rows" in payload:
                return payload
            if "data" in payload:
                return payload["data"]
        return payload

    async def get_clients_raw(self, *, use_cache: bool = True) -> list[dict[str, Any]]:
        now = time.time()
        if use_cache and self._clients_cache and self._clients_cache[1] > now:
            return self._clients_cache[0]

        data = await self._request("/client/list/")
        if isinstance(data, list):
            clients = data
        elif isinstance(data, dict):
            clients = data.get("rows") or data.get("list") or []
        else:
            clients = []

        self._clients_cache = (clients, now + self.CLIENT_CACHE_SECONDS)
        return clients

    async def get_tunnels_raw(self, client_id: int | None = None) -> list[dict[str, Any]]:
        if client_id is None:
            return []
        data = await self._request("/index/gettunnel/", {"client_id": client_id})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("rows") or data.get("list") or []
        return []

    async def get_tunnels_for_clients(self, client_ids: set[int]) -> list[dict[str, Any]]:
        if not client_ids:
            return []
        batches = await asyncio.gather(
            *[self.get_tunnels_raw(client_id=cid) for cid in sorted(client_ids)]
        )
        tunnels: list[dict[str, Any]] = []
        for batch in batches:
            tunnels.extend(batch)
        return tunnels

    def filter_clients(self, clients: list[dict[str, Any]]) -> list[dict[str, Any]]:
        prefix = self.settings.allowed_remark_prefix
        return [c for c in clients if _matches_prefix(str(c.get("Remark") or c.get("remark") or ""), prefix)]

    def filter_tunnels(self, tunnels: list[dict[str, Any]], allowed_client_ids: set[int]) -> list[dict[str, Any]]:
        prefix = self.settings.allowed_remark_prefix
        filtered = []
        for tunnel in tunnels:
            client_id = _extract_tunnel_client_id(tunnel)
            remark = str(tunnel.get("Remark") or tunnel.get("remark") or "")
            if client_id in allowed_client_ids and _matches_prefix(remark, prefix):
                filtered.append(tunnel)
        return filtered

    def _find_client(self, clients: list[dict[str, Any]], client_id: int) -> dict[str, Any] | None:
        return next((c for c in clients if int(c.get("Id") or c.get("id") or 0) == client_id), None)

    def sanitize_client(self, client: dict[str, Any], tunnels: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        client_id = int(client.get("Id") or client.get("id") or 0)
        remark = str(client.get("Remark") or client.get("remark") or "")
        addr = _extract_client_addr(client)
        masked_addr = mask_ip(addr, self.settings.mask_client_ip)

        client_tunnels = tunnels or []
        is_open = any(
            _tunnel_status(t) == "running"
            for t in client_tunnels
            if _extract_tunnel_client_id(t) == client_id
        )

        inlet_flow, export_flow, rate = _extract_client_flows(client)

        return {
            "id": client_id,
            "remark": remark,
            "version": str(client.get("Version") or client.get("version") or ""),
            "client_addr": masked_addr,
            "inlet_flow": inlet_flow,
            "export_flow": export_flow,
            "rate": rate,
            "status": _client_status(client),
            "is_open": is_open,
        }

    def sanitize_tunnel(self, tunnel: dict[str, Any], client_status: str = "offline") -> dict[str, Any]:
        tunnel_id = int(tunnel.get("Id") or tunnel.get("id") or 0)
        client_id = _extract_tunnel_client_id(tunnel)
        remark = str(tunnel.get("Remark") or tunnel.get("remark") or "")
        mode = str(tunnel.get("Mode") or tunnel.get("mode") or "tcp").lower()
        server_port = _extract_tunnel_server_port(tunnel)
        target = _extract_tunnel_target(tunnel)

        return {
            "id": tunnel_id,
            "client_id": client_id,
            "remark": remark,
            "mode": mode,
            "server_port": server_port,
            "target": target,
            "status": _tunnel_status(tunnel),
            "client_status": client_status,
            "connect_text": _build_connect_text(tunnel, self.settings.nps_public_host),
        }

    async def get_devices(self, *, include_tunnels: bool = True) -> list[dict[str, Any]]:
        clients = self.filter_clients(await self.get_clients_raw())
        if not include_tunnels:
            return [self.sanitize_client(c, []) for c in clients]

        allowed_ids = {int(c.get("Id") or c.get("id") or 0) for c in clients}
        filtered_tunnels = self.filter_tunnels(await self.get_tunnels_for_clients(allowed_ids), allowed_ids)
        return [self.sanitize_client(c, filtered_tunnels) for c in clients]

    async def get_device_light(self, client_id: int) -> dict[str, Any] | None:
        """Fast path: client info only, no tunnel fetch."""
        clients = self.filter_clients(await self.get_clients_raw())
        target = self._find_client(clients, client_id)
        if not target:
            return None
        return self.sanitize_client(target, [])

    async def get_device(self, client_id: int) -> dict[str, Any] | None:
        clients = self.filter_clients(await self.get_clients_raw())
        target = self._find_client(clients, client_id)
        if not target:
            return None
        tunnels = self.filter_tunnels(await self.get_tunnels_raw(client_id=client_id), {client_id})
        return self.sanitize_client(target, tunnels)

    async def get_device_tunnels(self, client_id: int) -> list[dict[str, Any]]:
        clients = self.filter_clients(await self.get_clients_raw())
        target = self._find_client(clients, client_id)
        if not target:
            return []
        client_status = _client_status(target)
        tunnels = await self.get_tunnels_raw(client_id=client_id)
        filtered = self.filter_tunnels(tunnels, {client_id})
        return [self.sanitize_tunnel(t, client_status) for t in filtered]

    async def add_tunnel(
        self,
        client_id: int,
        target: str,
        remark: str,
        mode: str = "tcp",
        port: str = "",
    ) -> Any:
        self.invalidate_cache()
        return await self._request(
            "/index/add/",
            {
                "type": mode,
                "remark": remark,
                "port": port,
                "target": target,
                "client_id": client_id,
            },
        )

    async def start_tunnel(self, tunnel_id: int) -> Any:
        return await self._request("/index/start/", {"id": tunnel_id})

    async def stop_tunnel(self, tunnel_id: int) -> None:
        self.invalidate_cache()
        await self._request("/index/stop/", {"id": tunnel_id})

    async def delete_tunnel(self, tunnel_id: int) -> None:
        self.invalidate_cache()
        await self._request("/index/del/", {"id": tunnel_id})

    async def get_one_tunnel(self, tunnel_id: int) -> dict[str, Any] | None:
        data = await self._request("/index/getonetunnel/", {"id": tunnel_id})
        if isinstance(data, dict) and (data.get("Id") or data.get("id")):
            return data
        return None

    async def get_used_server_ports(self) -> set[int]:
        clients = await self.get_clients_raw(use_cache=False)
        client_ids = [int(c.get("Id") or c.get("id") or 0) for c in clients]
        client_ids = [cid for cid in client_ids if cid > 0]
        if not client_ids:
            return set()

        batches = await asyncio.gather(*[self.get_tunnels_raw(client_id=cid) for cid in client_ids])
        used: set[int] = set()
        for batch in batches:
            for tunnel in batch:
                port = _extract_tunnel_server_port(tunnel)
                if port > 0:
                    used.add(port)
        return used

    async def _rollback_tunnel(self, tunnel_id: int) -> None:
        try:
            await self.stop_tunnel(tunnel_id)
        except Exception:
            pass
        try:
            await self.delete_tunnel(tunnel_id)
        except Exception:
            pass

    async def add_and_start_tunnel(
        self,
        client_id: int,
        target: str,
        remark: str,
        mode: str = "tcp",
        port: str = "",
        *,
        service: str = "tcp",
        expected_port: int | None = None,
    ) -> dict[str, Any]:
        if not port or int(port) <= 0:
            raise RuntimeError("创建隧道前必须指定有效公网端口")

        unique_remark = f"{remark}-{int(time.time())}"
        server_port = int(port)
        await self.add_tunnel(client_id, target, unique_remark, mode, str(server_port))

        tunnels = await self.get_tunnels_raw(client_id=client_id)
        tunnel = next((t for t in tunnels if str(t.get("Remark") or "") == unique_remark), None)
        if not tunnel:
            raise RuntimeError("NPS 隧道创建失败：无法在列表中找到新建隧道")

        tunnel_id = int(tunnel.get("Id") or tunnel.get("id") or 0)
        if tunnel_id <= 0:
            raise RuntimeError("NPS 隧道创建失败：无效隧道 ID")

        await self.start_tunnel(tunnel_id)

        tunnels_after = await self.get_tunnels_raw(client_id=client_id)
        verified = next(
            (
                t
                for t in tunnels_after
                if _tunnel_matches(
                    t,
                    client_id=client_id,
                    remark=unique_remark,
                    server_port=server_port,
                    target=target,
                )
            ),
            None,
        )

        if not verified:
            await self._rollback_tunnel(tunnel_id)
            raise RuntimeError(
                "NPS 隧道反查失败：client_id/remark/server_port/target 不匹配，已回滚"
            )

        assigned_port = _extract_tunnel_server_port(verified)
        if expected_port is not None and assigned_port != expected_port:
            await self._rollback_tunnel(tunnel_id)
            raise RuntimeError(f"NPS 分配端口 {assigned_port} 与预期 {expected_port} 不一致")

        if assigned_port <= 0:
            await self._rollback_tunnel(tunnel_id)
            raise RuntimeError("NPS 未分配有效公网端口")

        return {
            "id": tunnel_id,
            "server_port": assigned_port,
            "remark": str(verified.get("Remark") or unique_remark),
        }
