# 快速部署指南

本文档帮助你在 **10 分钟内** 用 Docker Compose 部署 NPS 远程调试门户。

---

## 1. 前置条件

| 项目 | 要求 |
|------|------|
| 服务器 | Linux / Windows（已安装 Docker + Docker Compose） |
| NPS | 已运行，Web 管理端口可访问（如 `8080`） |
| 网络 | 云安全组 / 防火墙放行门户端口（默认 `8088`）及映射用公网端口段 |

在 NPS 中至少有一台客户端（记下 **客户端 ID** 与**备注名**）。客户端可先为离线状态，但**实际转发流量时需要在线**。

---

## 2. 获取代码

```bash
cd /opt   # 或任意目录
git clone https://github.com/liu-big/NPS-ant.git nps-portal
cd nps-portal
```

若无 Git，将项目目录上传到服务器后 `cd` 进入即可。

---

## 3. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，**至少修改以下项**：

```env
# NPS（必填）
NPS_BASE_URL=http://你的NPS公网IP:8080
NPS_AUTH_KEY=与nps.conf中auth_key完全一致
NPS_PUBLIC_HOST=你的公网IP
NPS_PUBLIC_HOSTS=你的公网IP

# 门户管理员（必填，首次启动写入数据库）
PORTAL_USERNAME=admin
PORTAL_PASSWORD=请改为强密码
JWT_SECRET=请改为随机长字符串

# 设备过滤：留空 = 显示 NPS 中全部客户端；填 auto- 则仅显示备注以 auto- 开头的客户端
ALLOWED_REMARK_PREFIX=

# 门户对外端口
PORTAL_PORT=8088
```

### 常用可选配置

```env
# 用户默认使用 12 小时，可选 5 分钟～1 天或永久
USER_TTL_DEFAULT_MINUTES=720
USER_TTL_MIN_MINUTES=5
USER_TTL_MAX_MINUTES=1440

# 公网端口池（默认全段，避开 blocklist）
AUTO_PORT_START=1
AUTO_PORT_END=65535
AUTO_PORT_BLOCKLIST=8080,8088,18000,18022

# 单用户最多 3 个运行中映射
MAX_RUNNING_MAPPINGS_PER_USER=5
MAX_RUNNING_MAPPINGS_TOTAL=200

# SSH 连接命令中的用户名（目标端口为 22 时）
DEFAULT_SSH_USER=ant

# 目标地址：留空 target_host 时默认 127.0.0.1
ALLOW_CUSTOM_TARGET_HOST=true
TARGET_HOST_WHITELIST=127.0.0.1,localhost
```

---

## 4. NPS 侧配置

### 4.1 `nps.conf`

确保 `allow_ports` 覆盖门户分配的端口范围，例如：

```ini
allow_ports=1-65535
```

或按需缩小范围，并与 `.env` 中 `AUTO_PORT_START/END` 一致。

### 4.2 客户端备注（可选）

若设置了 `ALLOWED_REMARK_PREFIX=auto-`，请在 NPS 中为客户端备注设为 `auto-xxx` 形式，否则门户搜索不到。

若 `ALLOWED_REMARK_PREFIX` **留空**，则所有客户端均可见（推荐测试环境）。

### 4.3 云安全组

放行：

- **TCP 8088**（门户 Web，或你设置的 `PORTAL_PORT`）
- **TCP 映射端口段**（与 `AUTO_PORT_START`–`AUTO_PORT_END` 一致）

---

## 5. 启动服务

```bash
docker compose up -d --build
```

首次构建约 1–3 分钟。查看状态：

```bash
docker compose ps
docker compose logs -f backend
```

健康检查：

```bash
curl http://127.0.0.1:8088/api/health
# 期望: {"status":"ok","nps_configured":true}
```

---

## 6. 首次登录

1. 浏览器打开：`http://服务器公网IP:8088`
2. 使用 `.env` 中的 `PORTAL_USERNAME` / `PORTAL_PASSWORD` 登录
3. **立即**在「用户管理」中修改管理员密码（`.env` 密码仅在建库时生效一次）

---

## 7. 交付给客户

### 管理员操作

1. **用户管理** → 创建普通用户（`role=user`）
2. 将门户地址与账号交给客户

### 客户操作

1. 登录 → 自动进入 **申请映射**
2. 搜索设备备注名或客户端 ID（如 `9` 或 `auto-ubuntu-dev-02`）
3. 选择客户端 → 填写目标端口（目标地址可留空，默认本机 `127.0.0.1`）
4. 选择使用时长（默认 12 小时，可选永久）→ 申请
5. 复制连接命令使用；用完可在 **我的映射** 中释放

---

## 8. 验证清单

| 步骤 | 操作 | 预期 |
|------|------|------|
| 1 | 访问 `/api/health` | `nps_configured: true` |
| 2 | 管理员登录 | 进入概览页 |
| 3 | 设备管理 | 能看到 NPS 客户端列表 |
| 4 | 创建普通用户并登录 | 进入申请映射页 |
| 5 | 搜索客户端并申请映射 | 返回公网端口与连接命令 |
| 6 | NPS 后台 | 出现对应临时隧道 |
| 7 | 用户释放 | 隧道删除，记录进入历史 |
| 8 | 等待到期 | 自动释放（非永久映射） |

---

## 9. 常见问题

### 无法连接 NPS（502）

- 检查 `NPS_BASE_URL` 是否可从容器内访问
- 确认 `NPS_AUTH_KEY` 与 `nps.conf` 完全一致
- 在服务器上：`curl http://NPS地址:8080`

### 搜索不到设备

- 确认客户端在 NPS 中存在（管理端「设备管理」是否能看到）
- 检查 `ALLOWED_REMARK_PREFIX`：
  - 若配置了前缀（如 `auto-`），客户端备注必须以该前缀开头，或**留空前缀**以显示全部
  - 备注为空的客户端在配置了 `auto-` 时会被过滤
- 搜索时输入**客户端 ID**（如 `9`）或备注名中的关键字
- 客户端**离线**不影响搜索，但映射后需在线才能转发

### 申请映射失败「无可用公网端口」

- 端口池已满或 NPS 占用过多；释放旧映射后重试
- 检查 `AUTO_PORT_BLOCKLIST` 是否过宽

### 映射成功但外网连不上

- 云安全组 / 防火墙是否放行该 **公网端口**
- NPS `allow_ports` 是否包含该端口
- NPS 客户端是否**在线**

### 管理端「运行中」数量不对

- 确认已部署最新代码（`history=false` 时仅返回 `status=running` 的记录）
- 刷新页面或重启 backend

### 修改 `.env` 后不生效

```bash
docker compose up -d --force-recreate backend
```

管理员密码改 `.env` **不会**更新已有账号，请在「用户管理」中重置。

### 忘记管理员密码

```bash
docker compose exec backend python -c "
from database import init_db
from config import get_settings
s = get_settings()
db = init_db(s)
user = db.get_user_by_username('admin')
db.reset_password(user['id'], '你的新密码')
print('done')
"
```

---

## 10. 升级与备份

### 升级

```bash
git pull
docker compose up -d --build
```

### 备份数据

SQLite 位于 Docker 卷 `portal-data`，路径容器内 `/app/data/portal.db`。

```bash
docker compose exec backend cat /app/data/portal.db > portal.db.backup
```

### 停止服务

```bash
docker compose down          # 保留数据卷
docker compose down -v       # ⚠️ 删除数据卷，会清空数据库
```

---

## 11. 本地开发（可选）

不依赖 Docker 时：

```bash
# 后端（项目根目录需有 .env）
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# 前端（另开终端）
cd frontend
npm install
npm run dev
```

前端开发服务器通过 Vite 代理访问后端。

---

## 12. 相关文档

- [README.md](./README.md) — 项目说明与 API 摘要
- [AGENTS.md](./AGENTS.md) — 开发架构说明
- [.env.example](./.env.example) — 完整环境变量
