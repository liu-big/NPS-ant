# Agent 开发上下文 — NPS 远程调试门户

> **读者**：Cursor / 其他 AI Agent。人类运维见 [README.md](./README.md)、[DEPLOY.md](./DEPLOY.md)。

---

## 0. 当前版本（v3 端口映射）

单一业务模式：**用户自助申请 TCP 端口映射**，无设备 ACL、无 ssh/web/gdb 分池、无旧版「端口会话」。

```
用户登录 → /port-mapping/apply
  → GET /my/clients/search?keyword=
  → POST /my/port-mappings { client_id, target_port, target_host?, ttl_minutes? }
  → 获得 public_host:public_port + connect_text
  → DELETE /my/port-mappings/{id} 或到期自动释放
```

内部 NPS 隧道 `service` 固定为 `tcp`。连接命令由 **target_port** 推导（见 `build_mapping_connect_text`）。

---

## 1. 项目是什么

**NPS 远程调试门户**（`f:\ant\web`）：面向客户的 Web 门户，**不是** NPS 管理后台替代品。

| 能做 | 不能做 |
|------|--------|
| 用户搜索 NPS 客户端并申请临时端口映射 | 暴露 NPS `auth_key`、客户端 vkey |
| 自动分配公网端口、到期/释放回收隧道 | 用户自选公网端口 |
| 管理员 RBAC、用户管理、全站映射监控 | 前端直连 NPS API |
| SQLite 持久化 + 审计日志 | 修改 NPS 上非本门户创建的永久隧道 |

**对外端口**：Docker Compose 默认 `8088`（`PORTAL_PORT`）。

**技术栈**：FastAPI + Vue3 + Element Plus + SQLite + Nginx + Docker Compose。

**仓库**：https://github.com/liu-big/NPS-ant

---

## 2. 架构

```
浏览器 (Vue3)
    │  /api/* + JWT (localStorage: portal_token, portal_user)
    ▼
FastAPI (backend/main.py)
    │  tunnel_service / database / auth
    ▼
NpsClient (backend/nps_api.py)  ──HTTP POST──►  NPS Web API
    │
    ▼
SQLite  {DATA_DIR}/portal.db   (Docker: /app/data, 卷 portal-data)
```

**安全边界**

- `NPS_AUTH_KEY`、`NPS_BASE_URL` 只在后端 `.env`
- 前端 `src/api/*` 只请求同源 `/api`
- `MASK_CLIENT_IP` 控制管理端设备列表是否脱敏客户端 IP

---

## 3. 关键文件

| 文件 | 职责 |
|------|------|
| `backend/main.py` | 全部 HTTP 路由；lifespan 启动清理 + 后台过期任务 |
| `backend/tunnel_service.py` | `create_port_mapping`、`release_portal_tunnel`、`allocate_auto_public_endpoint`、`search_mapping_clients` |
| `backend/nps_api.py` | NPS HTTP 客户端、备注前缀过滤、`add_and_start_tunnel`（**必须显式 port**） |
| `backend/database.py` | SQLite schema、映射 CRUD、审计日志、`mark_invalid_tunnel_sessions` |
| `backend/config.py` | `Settings`、自动端口池、用户 TTL |
| `backend/schemas.py` | Pydantic 模型 |
| `backend/auth.py` | JWT、bcrypt |
| `frontend/src/router/index.js` | RBAC；admin→`/dashboard`，user→`/port-mapping/apply` |
| `frontend/src/views/user/PortMappingApply.vue` | 搜索客户端 + 申请表单 |
| `frontend/src/views/user/MyPortMappings.vue` | 运行中 / 历史 |
| `frontend/src/views/admin/AdminPortMappings.vue` | 管理端映射列表 |
| `frontend/src/views/admin/AdminUsers.vue` | 用户管理 |
| `frontend/src/views/admin/AdminDevices.vue` | NPS 设备只读列表 |
| `frontend/src/views/admin/AdminAuditLogs.vue` | 审计日志 |
| `.env.example` | 环境变量模板 |

**已删除的遗留功能**（勿再引用）：设备 ACL、`/my/tunnels`、`/admin/device-acl`、ssh/web/gdb 分池、`AdminDeviceAcl.vue`、`DeviceSearch.vue`、`MyTunnels.vue` 等。

---

## 4. 数据库（SQLite）

路径：`{DATA_DIR}/portal.db`

### `portal_users`

- `role`: `admin` | `user`
- `status`: `active` | `disabled`
- 首次 `init_schema` 时用 `PORTAL_USERNAME` / `PORTAL_PASSWORD` 创建 admin

### `portal_tunnel_sessions`

门户创建的 NPS 隧道映射记录。

| 字段 | 说明 |
|------|------|
| `user_id`, `client_id` | 所属用户与 NPS 客户端 |
| `public_host`, `public_port` | 分配给用户的公网入口 |
| `target_host`, `target_port` | 客户端侧目标（默认 127.0.0.1） |
| `service` | 固定 `tcp` |
| `ttl_minutes` | 申请时用户选择的时长；NULL = 永久 |
| `expire_at` | 到期时间 ISO；NULL = 永久 |
| `status` | `running` \| `expired` \| `deleted` \| `failed` \| `cleanup_failed` |
| `release_reason` | `user_released` \| `ttl_expired` \| `admin_force_release` 等 |

> 旧库可能仍存在 `portal_device_acl` 表与 `acl_id` 列，**当前代码不再读写**，可忽略。

### `portal_audit_logs`

记录 login/logout、用户 CRUD、`create_port_mapping`、`release_port_mapping`、`port_mapping_auto_expire` 等。

---

## 5. 端口映射流程

### 申请（`create_port_mapping`）

1. `validate_port_mapping_request` — 目标端口 1–65535、TTL 上下限、目标地址白名单
2. `validate_mapping_limits` — 单用户 / 全站运行中数量上限
3. `nps.get_device_light(client_id)` — 客户端须存在且通过备注前缀过滤
4. `allocate_auto_public_endpoint` — 在 `AUTO_PORT_START..END` 内扫描，排除 DB 占用、NPS 占用、blocklist
5. `nps.add_and_start_tunnel(..., port=str(public_port), expected_port=public_port)` — **必须显式 port**
6. `db.create_tunnel_session` + 审计

### 释放

- 用户：`DELETE /my/port-mappings/{id}` → `release_portal_tunnel` → NPS stop/delete → `status=deleted`
- 管理员：`DELETE /admin/port-mappings/{id}` → `release_reason=admin_force_release`
- 后台：`cleanup_expired_sessions` 处理 `expire_at` 已过的 `running` 记录

### 列表筛选

- `history=false` → `status=running` only
- `history=true` → `status != running`（可再加 `status` query 筛选）

---

## 6. 连接命令（`build_mapping_connect_text`）

按 **target_port**（非 service 类型）：

| target_port | connect_text |
|-------------|--------------|
| 22 | `ssh {DEFAULT_SSH_USER}@{host} -p {port}` |
| 80, 8000, 8080 | `http://{host}:{port}` |
| 443 | `https://{host}:{port}` |
| 2345 | `target remote {host}:{port}` |
| 其他 | `{host}:{port}` |

---

## 7. NPS 客户端过滤

`ALLOWED_REMARK_PREFIX`（`nps_api.filter_clients`）：

- **空字符串**：不过滤，显示全部客户端
- **非空**（如 `auto-`）：仅 `remark.startswith(prefix)` 的客户端可见

`search_mapping_clients`：若 NPS 中存在匹配 keyword 的客户端但被前缀过滤，抛出带说明的 `ValueError`（API 返回 400）。

管理端与用户端搜索共用同一过滤规则。

---

## 8. API 路由

Base: `/api`

### 公共

| Method | Path | Auth |
|--------|------|------|
| GET | `/health` | 否 |
| POST | `/login` | 否 |
| GET | `/me` | JWT |
| POST | `/logout` | JWT |
| GET | `/config` | JWT |

`/config` 返回：`user_ttl_options`、`auto_port_range`、`allowed_remark_prefix`、`default_ssh_user` 等。

### Admin（role=admin）

| Method | Path |
|--------|------|
| GET | `/admin/dashboard/summary` |
| GET | `/admin/devices` |
| GET/POST/PUT/DELETE | `/admin/users` |
| POST | `/admin/users/{id}/reset-password` |
| GET | `/admin/port-mappings`（`history`, `status`, `keyword`） |
| DELETE | `/admin/port-mappings/{id}` |
| GET | `/admin/audit-logs` |
| GET | `/admin/audit-logs/actions` |

### User（role=user）

| Method | Path |
|--------|------|
| GET | `/my/clients/search?keyword=` |
| GET/POST/DELETE | `/my/port-mappings` |

---

## 9. 前端路由

| 角色 | 路径 | 组件 |
|------|------|------|
| admin | `/dashboard` | Dashboard.vue |
| admin | `/admin/devices` | AdminDevices.vue |
| admin | `/admin/users` | AdminUsers.vue |
| admin | `/admin/port-mappings` | AdminPortMappings.vue |
| admin | `/admin/audit-logs` | AdminAuditLogs.vue |
| user | `/port-mapping/apply` | PortMappingApply.vue |
| user | `/my/port-mappings` | MyPortMappings.vue |
| 公共 | `/login` | Login.vue |

`Login.vue` 登录成功：admin → `/dashboard`，user → `/port-mapping/apply`。

---

## 10. 环境变量

见 [`.env.example`](./.env.example)。

**必填**：`NPS_BASE_URL`, `NPS_AUTH_KEY`, `NPS_PUBLIC_HOST`, `PORTAL_PASSWORD`, `JWT_SECRET`

**端口池**：`AUTO_PORT_START`, `AUTO_PORT_END`, `AUTO_PORT_BLOCKLIST`, `AUTO_PORT_SOCKET_CHECK`

**用户 TTL**：`USER_TTL_DEFAULT_MINUTES`（720）, `USER_TTL_MIN/MAX_MINUTES`

**限制**：`MAX_RUNNING_MAPPINGS_PER_USER`, `MAX_RUNNING_MAPPINGS_TOTAL`

**其他**：`ALLOWED_REMARK_PREFIX`, `DEFAULT_SSH_USER`, `CLEANUP_INTERVAL_SECONDS`, `MASK_CLIENT_IP`

修改 `.env` 后：`docker compose up -d --force-recreate backend` 或 `--build`。

---

## 11. NPS 对接要点

- NPS API 使用 **POST** 带 `auth_key`
- `NPS_BASE_URL` 无尾斜杠，如 `http://39.101.76.106:8080`
- 设备/隧道列表有内存缓存（`nps_api.py`）
- 隧道 remark 格式：`portal-map-{username}-c{client_id}`
- `bcrypt==4.2.1`（见 `requirements.txt`）

---

## 12. 开发命令

```bash
cd f:\ant\web
docker compose up -d --build
curl http://127.0.0.1:8088/api/health

# 本地
cd backend && uvicorn main:app --reload --port 8000
cd frontend && npm install && npm run dev
```

---

## 13. 修改代码约束

1. **最小 diff**，匹配现有风格
2. **不要**把 NPS 密钥、vkey 暴露到前端
3. **创建 NPS 隧道必须带显式 port**，并 `validate_auto_port` + NPS 回读校验
4. 用户申请映射 **必须**传 `client_id`（搜索选择），不传公网端口
5. `history=false` 的列表 API **必须**只返回 `running`
6. 新增 API 同步：`schemas.py`、`main.py`、`frontend/src/api/index.js`、相关 Vue 页面
7. **不要提交** `.env`

---

## 14. 故障速查

| 现象 | 方向 |
|------|------|
| NPS 502 | `NPS_BASE_URL`、`NPS_AUTH_KEY`、容器网络 |
| 搜不到客户端 | `ALLOWED_REMARK_PREFIX`、备注是否为空、管理端设备列表是否有 |
| `public_port=0` | `add_and_start_tunnel` 未传 port |
| 无可用端口 | 释放旧映射；检查 blocklist 与 NPS 占用 |
| 外网连不上 | 安全组、`allow_ports`、客户端是否在线 |
| 运行中数量错误 | 确认 `history=false` 使用 `status=running` 筛选 |
| bcrypt 报错 | `bcrypt==4.2.1` |

---

*最后更新：v3 自助端口映射（无 ACL / 无服务分池）。*
