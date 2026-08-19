# NPS 远程调试门户

面向客户的 **NPS 端口映射门户**：用户自助搜索 NPS 客户端、申请临时公网端口，映射到客户端上的目标地址；管理员管理用户、查看设备与全站映射，全程可审计。

客户使用本门户，**无需**登录 NPS 后台，也**看不到**验证密钥（vkey）、`auth_key` 等敏感信息。

**仓库**：https://github.com/liu-big/NPS-ant

---
<img width="1491" height="1055" alt="image" src="https://github.com/user-attachments/assets/01ed6e94-fc29-4a0c-b0d2-0d4b843d6500" />

## 功能概览

| 角色 | 能力 |
|------|------|
| **用户** | 搜索 NPS 客户端 → 填写目标端口与使用时长 → 获得公网 IP:端口与连接命令 |
| **管理员** | 概览统计、NPS 设备查看、用户管理、全站端口映射监控、审计日志 |

**核心能力**

- 用户自选使用时长（默认 12 小时，支持永久），后端强制上下限
- 公网端口从统一池自动分配（默认 `1–65535`，避开 blocklist）
- 目标地址可留空，默认映射到客户端本机 `127.0.0.1`
- 连接命令按**目标端口**生成（22 → SSH，8000/8080 → HTTP 等）
- 到期 / 释放后自动回收 NPS 隧道与端口
- 运行中 / 历史记录分开展示
- SQLite 持久化，Docker 卷保存数据

---

## 典型使用流程

```
管理员                          用户
  │                              │
  ├─ 创建普通用户                 │
  ├─ 交付门户账号                 │
  │                              ├─ 登录 → 申请映射
  │                              ├─ 搜索客户端（备注名 / ID）
  │                              ├─ 填写目标端口、使用时长
  │                              ├─ 获得 公网IP:端口 + 连接命令
  │                              └─ 到期或手动释放
  └─ 在「端口映射」中监控 / 强制释放
```

**连接命令示例**（目标端口 22 时）：

```bash
ssh ant@39.101.76.106 -p 27490
```

---

## 系统架构

```
浏览器 (Vue3 + Element Plus)
        │  /api/* + JWT
        ▼
FastAPI 后端
        ├── SQLite (portal.db)
        └── NpsClient ──► NPS Web API
```

- 前端只请求 `/api/*`，不接触 NPS
- `NPS_AUTH_KEY` 仅存在于后端 `.env`
- 数据目录：`./data`（Docker 内 `/app/data`，卷 `portal-data`）

---

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.12、FastAPI、SQLite、JWT |
| 前端 | Vue 3、Element Plus、Vite |
| 部署 | Docker Compose、Nginx |

---

## 快速开始

详见 **[DEPLOY.md](./DEPLOY.md)**（推荐首次部署阅读）。

```bash
git clone https://github.com/liu-big/NPS-ant.git
cd NPS-ant
cp .env.example .env    # 编辑 NPS 地址、密钥、公网 IP、管理员密码
docker compose up -d --build
```

访问：`http://服务器IP:8088`

默认管理员见 `.env` 中 `PORTAL_USERNAME` / `PORTAL_PASSWORD`（仅首次建库写入）。

---

## 页面说明

### 管理员

| 页面 | 路径 | 说明 |
|------|------|------|
| 概览 | `/dashboard` | 设备与活跃映射统计 |
| 设备管理 | `/admin/devices` | 查看 NPS 客户端（IP 可脱敏） |
| 用户管理 | `/admin/users` | 创建 / 禁用 / 重置密码 |
| 端口映射 | `/admin/port-mappings` | 运行中与历史记录 |
| 审计日志 | `/admin/audit-logs` | 操作追溯 |

### 用户

| 页面 | 路径 | 说明 |
|------|------|------|
| 申请映射 | `/port-mapping/apply` | 搜索设备并申请端口 |
| 我的映射 | `/my/port-mappings` | 运行中 / 历史、复制命令、释放 |

登录后：管理员 → `/dashboard`；普通用户 → `/port-mapping/apply`。

---

## 环境变量（摘要）

完整说明见 [`.env.example`](.env.example)。

| 变量 | 说明 |
|------|------|
| `NPS_BASE_URL` | NPS 管理 API 地址（仅后端） |
| `NPS_AUTH_KEY` | 与 `nps.conf` 中 `auth_key` 一致 |
| `NPS_PUBLIC_HOST` / `NPS_PUBLIC_HOSTS` | 分配给用户连接的公网 IP |
| `PORTAL_USERNAME` / `PORTAL_PASSWORD` | 初始管理员（仅首次建库） |
| `JWT_SECRET` | JWT 签名密钥，生产必改 |
| `ALLOWED_REMARK_PREFIX` | NPS 设备备注前缀过滤；**留空 = 显示全部客户端** |
| `USER_TTL_DEFAULT_MINUTES` | 默认使用时长（720 = 12 小时） |
| `USER_TTL_MIN/MAX_MINUTES` | 用户可选时长范围 |
| `AUTO_PORT_START/END` | 公网端口分配范围（默认 1–65535） |
| `AUTO_PORT_BLOCKLIST` | 禁止分配的端口（NPS/门户等） |
| `MAX_RUNNING_MAPPINGS_PER_USER` | 单用户最大运行映射数 |
| `MAX_RUNNING_MAPPINGS_TOTAL` | 全站最大运行映射数 |
| `ALLOW_CUSTOM_TARGET_HOST` | 是否允许自定义目标地址 |
| `TARGET_HOST_WHITELIST` | 目标地址白名单（关闭自定义时生效） |
| `DEFAULT_SSH_USER` | 生成 SSH 连接命令的用户名（默认 `ant`） |
| `PORTAL_PORT` | 门户对外端口（默认 8088） |

---

## API 摘要

Base URL：`http://host:8088/api`  
认证：除 `/health`、`/login` 外需 `Authorization: Bearer <token>`。

### 公共

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/login` | 登录 |
| GET | `/config` | 门户配置（TTL 选项、端口范围、备注前缀等） |

### 用户

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/my/clients/search?keyword=` | 按备注名或客户端 ID 搜索 |
| GET | `/my/port-mappings?history=false` | 运行中映射 |
| GET | `/my/port-mappings?history=true` | 历史记录 |
| POST | `/my/port-mappings` | 申请映射 |
| DELETE | `/my/port-mappings/{id}` | 释放 |

**申请示例**

```json
POST /api/my/port-mappings
{
  "client_id": 7,
  "target_port": 22,
  "ttl_minutes": 720
}
```

`target_host` 可省略（默认 `127.0.0.1`）；`ttl_minutes` 为 `null` 表示永久。

### 管理员

| 方法 | 路径 |
|------|------|
| GET | `/admin/dashboard/summary` |
| GET | `/admin/devices` |
| GET/POST/PUT/DELETE | `/admin/users` |
| POST | `/admin/users/{id}/reset-password` |
| GET | `/admin/port-mappings?history=false\|true` |
| DELETE | `/admin/port-mappings/{id}` |
| GET | `/admin/audit-logs` |
| GET | `/admin/audit-logs/actions` |

---

## 项目结构

```
.
├── backend/
│   ├── main.py           # 路由入口
│   ├── tunnel_service.py # 映射创建/释放、端口分配
│   ├── nps_api.py        # NPS HTTP 客户端
│   ├── database.py       # SQLite
│   ├── config.py         # 环境变量
│   ├── auth.py           # JWT
│   └── schemas.py
├── frontend/
│   └── src/
│       ├── views/admin/  # AdminDevices, AdminUsers, AdminPortMappings, AdminAuditLogs
│       └── views/user/   # PortMappingApply, MyPortMappings
├── docker-compose.yml
├── .env.example
├── DEPLOY.md
├── AGENTS.md
└── README.md
```

---

## 运维命令

```bash
docker compose ps
docker compose logs -f backend
docker compose up -d --build
docker compose down          # 保留数据卷
docker compose down -v       # ⚠️ 删除数据库
```

数据卷 `portal-data` 保存 SQLite，**删除卷会丢失用户与映射记录**。

---

## 安全注意

1. 交付前修改 `PORTAL_PASSWORD`、`JWT_SECRET`
2. 勿将 `.env` 提交到 Git
3. 生产环境建议前置 HTTPS 反向代理
4. NPS `allow_ports` 与安全组需放行实际使用的公网端口段
5. 用户不能指定公网端口；TTL 由后端校验

---

## 相关文档

- [DEPLOY.md](./DEPLOY.md) — 快速部署（逐步操作）
- [AGENTS.md](./AGENTS.md) — 供 AI Agent 阅读的架构与开发说明
- [.env.example](./.env.example) — 环境变量模板

---

## 许可证

内部项目，按需使用。
