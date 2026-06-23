# Agent 开发上下文 — NPS 远程调试门户

> **读者**：Cursor / 其他 AI Agent。人类运维见 [README.md](./README.md)、[DEPLOY.md](./DEPLOY.md)。

---

## v3 核心业务（端口映射）

用户申请（**不传**公网端口；`target_host` 可省略，默认 `127.0.0.1`）：

```json
POST /api/my/port-mappings
{
  "client_id": 7,
  "target_port": 22,
  "ttl_minutes": 720
}
```

`ttl_minutes: null` = 永久。内部 `service` 固定为 `tcp`；连接命令按 **目标端口** 生成（22 → ssh 命令）。

后端：`allocate_auto_public_endpoint()` → `nps.add_and_start_tunnel(port=显式)` → 反查校验 → DB `portal_tunnel_sessions`（`acl_id IS NULL` 为 v3 映射）。

列表 API：`GET /my/port-mappings?history=false`（运行中） / `history=true`（历史）。

### 关键 env

| 变量 | 说明 |
|------|------|
| `NPS_PUBLIC_HOSTS` | 可分配公网 IP 列表 |
| `AUTO_PORT_START/END` | 自动分配范围（默认 1–65535） |
| `AUTO_PORT_BLOCKLIST` | 禁分配端口 |
| `USER_TTL_DEFAULT_MINUTES` | 默认 720（12 小时） |
| `USER_TTL_MIN/MAX_MINUTES` | 用户 TTL 上下限；null=永久 |
| `MAX_RUNNING_MAPPINGS_PER_USER` | 默认 3 |
| `ALLOW_CUSTOM_TARGET_HOST` | false 时仅 `TARGET_HOST_WHITELIST` |

### API

| Method | Path |
|--------|------|
| GET | `/my/clients/search?keyword=` |
| POST/GET/DELETE | `/api/my/port-mappings` |
| GET/DELETE | `/api/admin/port-mappings` |

### 前端（当前入口）

- 用户：`PortMappingApply.vue`、`MyPortMappings.vue`
- 管理：`AdminPortMappings.vue`（已移除设备授权、端口会话(旧)菜单）
- 遗留页面未路由：`AdminDeviceAcl.vue`、`DeviceSearch.vue` 等

---

## 1. 项目是什么

**NPS 远程调试门户**（`f:\ant\web`）：面向**客户**的 Web 门户，不是 NPS 管理后台替代品。

| 能做 | 不能做 |
|------|--------|
| 管理员 RBAC、用户管理、设备 ACL 授权 | 暴露 NPS `auth_key`、客户端 vkey |
| 用户搜索已授权设备，申请 **临时** SSH/Web/GDB 端口 | 用户自选 TTL（由管理员在 ACL 绑定） |
| 自动分配端口池、到期/释放回收 NPS 隧道 | 前端直连 NPS API |
| SQLite 持久化 + 审计日志 | 修改 NPS 永久隧道（只管理 portal 创建的临时隧道） |

**对外端口**：Docker Compose 默认 `8088`（`PORTAL_PORT`）。

**技术栈**：FastAPI + Vue3 + Element Plus + SQLite + Nginx（前端静态）+ Docker Compose。

---

## 2. 架构（数据流）

```
浏览器 (Vue3)
    │  仅 /api/* + JWT
    ▼
FastAPI (backend/main.py)
    │  tunnel_service / database / auth
    ▼
NpsClient (backend/nps_api.py)  ──HTTP──►  NPS Web API (NPS_BASE_URL)
    │
    ▼
SQLite  portal.db  (DATA_DIR，Docker: /app/data)
```

**安全边界**：

- `NPS_AUTH_KEY`、`NPS_BASE_URL` 只在后端 `.env`，**禁止**写入前端或 API 响应。
- 前端 `src/api/*` 只请求同源 `/api`。
- 用户只能看到 ACL 授权范围内的 `client_id`；管理员看 NPS 设备列表（可脱敏 IP）。

---

## 3. 关键文件地图

| 文件 | 职责 |
|------|------|
| `backend/main.py` | 全部 HTTP 路由；启动时清理异常会话；后台过期清理任务 |
| `backend/tunnel_service.py` | 端口池分配、ACL/TTL 校验、创建/释放会话、`connect_text` 生成 |
| `backend/nps_api.py` | NPS HTTP 客户端、缓存、IP 脱敏、`add_and_start_tunnel`（**必须传显式 port**） |
| `backend/database.py` | SQLite schema、迁移、ACL 状态、审计日志 CRUD、无效会话标记 |
| `backend/config.py` | `Settings`、端口池 env、TTL 默认值 |
| `backend/schemas.py` | Pydantic 请求/响应模型 |
| `backend/auth.py` | JWT、bcrypt、`get_current_user` |
| `frontend/src/router/index.js` | RBAC 路由；admin → `/dashboard`，user → `/search` |
| `frontend/src/views/admin/AdminDeviceAcl.vue` | 设备授权 UI（TTL + 授权截止） |
| `frontend/src/views/user/DeviceSearch.vue` | 用户申请端口（无 TTL 选择） |
| `frontend/src/views/user/MyTunnels.vue` | 我的端口筛选/释放 |
| `frontend/src/utils/portPool.js` | 前端端口池展示校验 |
| `.env.example` | 环境变量模板（勿提交真实 `.env`） |

**遗留未路由页面**（勿当作入口）：`frontend/src/views/Devices.vue`、`DeviceDetail.vue`（v1 只读原型）。

---

## 4. 数据库表（SQLite）

路径：`{DATA_DIR}/portal.db`

### `portal_users`

- `role`: `admin` | `user`
- `status`: `active` | `disabled`
- 默认 admin 在首次 init 时由 `PORTAL_USERNAME` / `PORTAL_PASSWORD` 创建

### `portal_device_acl`（核心授权）

| 字段 | 说明 |
|------|------|
| `user_id` + `client_id` | UNIQUE，一用户一设备一条授权 |
| `access_code` | `DEV-XXXX-XXXX`，供用户搜索 |
| `ttl_key` | 相对有效期 preset key，**默认空字符串** |
| `access_expire_at` | 绝对截止时间（ISO），可选 |
| `status` | `active` → `in_use` → `completed` |

### `portal_tunnel_sessions`

- 门户创建的**临时** NPS 隧道会话
- `acl_id` 关联授权；`public_port` 必须在对应 service 端口池内
- `expire_at` NULL = 永久（仅 admin 或 `permanent` TTL）
- `status`: `running` | `expired` | `deleted`

### `portal_audit_logs`

- 记录 login/logout、用户 CRUD、ACL 绑定/解除/重新分配、隧道 create/release 等

---

## 5. ACL 生命周期（必读）

```
管理员绑定 ACL (status=active)
        │
        ▼
用户 POST /my/tunnels 成功 → mark_acl_in_use (in_use)
        │
        ├── 用户 DELETE /my/tunnels → release → complete_device_acl (completed)
        ├── 后台 cleanup 到期 → 同上
        └── 管理员 DELETE /admin/device-acl → revoke（释放隧道 + 删 ACL）
        
completed 后：
  - 用户无法再次申请，直到管理员 POST .../reassign（重置为 active）
```

**申请前校验**（`tunnel_service.check_acl_can_apply`）：

1. `access_expire_at` 若已过期 → 拒绝
2. `status == completed` → 拒绝（需重新分配）
3. `status == in_use` → 拒绝（需先释放）
4. `status != active` → 拒绝

**禁止**：用户通过重复申请重置计时器——释放/到期会将 ACL 置为 `completed`。

---

## 6. 有效期规则（TTL vs 授权截止）

配置在 **管理员绑定 ACL** 时，**用户申请时不传 TTL**。

| 配置 | 会话 `expire_at` |
|------|------------------|
| 仅 `access_expire_at` | 该绝对时刻（**优先**） |
| 仅 `ttl_key` | 申请时刻 + preset 分钟数 |
| 两者都有 | **以 `access_expire_at` 为准** |
| 两者都空 | 绑定 API 校验失败 |

**TTL presets**（`tunnel_service.TTL_PRESETS`）：

| key | 分钟 |
|-----|------|
| `5min` | 5（测试） |
| `1d` | 1440 |
| `3d` | 4320 |
| `1w` | 10080 |
| `1month` | 43200 |
| `permanent` | NULL（永久） |

**时区**：`_parse_acl_datetime` 将**无时区**的 datetime 视为 **UTC+8（中国本地）**，再转 UTC 存储比较。

**UI 默认**：`ttl_key` 下拉默认为**空**（非 `1d`）；至少填 TTL 或授权截止之一。

---

## 7. 端口池与 NPS 隧道创建

### 默认范围（每类 500 端口，可通过 `.env` 覆盖）

| service | 默认范围 | 目标 |
|---------|----------|------|
| ssh | 18023–18522 | 127.0.0.1:22 |
| web | 18523–19022 | 127.0.0.1:8000 |
| gdb | 19023–19522 | 127.0.0.1:2345 |
| temp | 19523–20022 | 127.0.0.1:8080 |

**保留**：`18022` 手动应急 SSH；**永不分配** `0` 或 `18000`。

### 分配流程（`allocate_public_port`）

1. 取 service 对应 `[start, end]`
2. `blocked` = DB 已占用端口 ∪ NPS 已用 `server_port`
3. 线性扫描第一个空闲端口
4. `nps.add_and_start_tunnel(..., port=str(public_port), expected_port=public_port)`
5. **反查 NPS** 确认 `server_port == expected_port`，否则抛错并清理

### 常见坑：`public_port = 0`

- **原因**：创建 NPS 隧道时未传 `port` 参数
- **修复**：必须显式传 port；创建后 validate + NPS 反查
- **启动清理**：`database.mark_invalid_tunnel_sessions` 标记越界/0 端口会话

**运维**：NPS `nps.conf` 的 `allow_ports` 需覆盖 `18023-20022`；云安全组同步放行。

---

## 8. API 路由一览

Base: `/api`（以下省略前缀）

### 公共

| Method | Path | Auth |
|--------|------|------|
| GET | `/health` | 否 |
| POST | `/login` | 否 |
| GET | `/me` | JWT |
| POST | `/logout` | JWT |
| GET | `/config` | JWT（TTL 选项、端口池、服务类型） |

### Admin（role=admin）

| Method | Path |
|--------|------|
| GET | `/admin/dashboard/summary` |
| GET | `/admin/devices` |
| GET/POST/PUT/DELETE | `/admin/users` |
| POST | `/admin/users/{id}/reset-password` |
| GET/POST | `/admin/device-acl` |
| POST | `/admin/device-acl/{id}/reassign` |
| DELETE | `/admin/device-acl/{id}` |
| GET/DELETE | `/admin/port-mappings` |
| GET | `/admin/audit-logs`（query: action, username, date range, page） |
| GET | `/admin/audit-logs/actions` |

### User（role=user）

| Method | Path | 备注 |
|--------|------|------|
| GET | `/my/devices/search?keyword=` | 精确匹配名称/ID/访问码 |
| GET | `/my/devices/{client_id}` | 需在 ACL 内 |
| GET | `/my/tunnels` | 筛选: `service`, `status`, `keyword` |
| POST | `/my/tunnels` | body: `{ client_id, service }`，**无 ttl** |
| DELETE | `/my/tunnels/{session_id}` | 释放并完成 ACL |

**注意**：v1 路径 `/api/devices`、`/api/dashboard/summary` **已废弃**，现均为 `/api/admin/*`。

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

JWT / 用户：`localStorage` 键 `portal_token`、`portal_user`。

---

## 10. 环境变量（Agent 常改）

见 [`.env.example`](./.env.example) 与 [README 环境变量](./README.md#环境变量说明)。

**必填**：`NPS_BASE_URL`, `NPS_AUTH_KEY`, `NPS_PUBLIC_HOST`, `PORTAL_PASSWORD`, `JWT_SECRET`

**端口池**：`SSH_PORT_START/END`, `WEB_*`, `GDB_*`, `TEMP_*`

**行为**：`CLEANUP_INTERVAL_SECONDS`（默认 60）、`MAX_TUNNEL_TTL_MINUTES`（默认 43200）、`DEFAULT_SSH_USER`（默认 `ant`）、`ALLOWED_REMARK_PREFIX`（如 `auto-`）

修改 `.env` 后需 `docker compose up -d --build` 或重启 backend。

---

## 11. NPS 对接要点

- NPS API 使用 **POST**（非 GET）带 `auth_key`
- `NPS_BASE_URL` 示例：`http://39.101.76.106:8080`（无尾斜杠）
- 设备列表/隧道列表有内存缓存（`nps_api.py`），注意 stale 数据场景
- 隧道 remark 建议带 `portal-` 前缀便于识别
- `bcrypt` 版本锁定 `4.2.1`（见 `requirements.txt`），避免 passlib 兼容问题

---

## 12. 开发 / 测试

```bash
# Docker 一键（推荐）
cd f:\ant\web
docker compose up -d --build

# 健康检查
curl http://127.0.0.1:8088/api/health

# 本地 backend（需 venv + .env）
cd backend && uvicorn main:app --reload --port 8000

# 本地 frontend
cd frontend && npm install && npm run dev
```

**测试路径建议**：

1. admin 登录 → 创建 user → 设备授权（填 TTL 或授权截止）
2. user 登录 → 搜索设备 → 申请 ssh → 检查 `public_port` 在池内、`connect_text` 正确
3. user 释放 → ACL 变 `completed` → 再次申请应失败
4. admin reassign → user 可再申请

---

## 13. 修改代码时的约束

1. **最小 diff**：只改任务相关文件，匹配现有命名与风格。
2. **不要**把 NPS 密钥、vkey 暴露到前端或日志。
3. **不要**让用户 API 接受 `ttl_key` / `ttl_minutes`（TTL 仅 ACL 绑定）。
4. **创建 NPS 隧道必须带显式 port**，并验证回读端口。
5. **释放/到期必须** `complete_device_acl`，防止无限复用授权。
6. **`access_expire_at` 优先于 `ttl_key`** 计算 session 过期时间。
7. ACL `ttl_key` 默认保持**空**，不要在 UI/DB  silently 默认成 `1d`。
8. 新增 API 需同步：`schemas.py`、`main.py`、前端 `api/`、必要时 `AdminDeviceAcl.vue` / user views。
9. **不要提交** `.env`（含真实密码与 auth_key）。

---

## 14. 故障速查

| 现象 | 方向 |
|------|------|
| NPS 404 | 检查 POST + URL；`NPS_BASE_URL` 是否可达 |
| `public_port=0` | 创建时未传 port；查 `add_and_start_tunnel` |
| 用户无法再次申请 | ACL 可能 `completed`，需 admin reassign |
| 授权未到期但申请失败 | 检查 `in_use` 是否有未释放会话 |
| 端口连不上 | NPS `allow_ports` + 云安全组 |
| bcrypt 报错 | 确认 `bcrypt==4.2.1` |
| 时间不对 | naive datetime 按 UTC+8 解析 |

详细步骤见 [README 常见问题排查](./README.md#常见问题排查)。

---

## 15. 相关对话上下文

若需了解近期功能演进（ACL 生命周期、端口池、access_expire_at 修复等），可检索 agent transcript：

`C:\Users\liu'jin\.cursor\projects\f-ant-web\agent-transcripts\784a9b09-e445-4c7e-8214-a8e7ac21de18\784a9b09-e445-4c7e-8214-a8e7ac21de18.jsonl`

---

*最后更新：与 README v2 远程调试门户功能对齐。*
