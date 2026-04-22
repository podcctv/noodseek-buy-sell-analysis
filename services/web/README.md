# Web Admin（配置中心）

本模块提供后端配置页面，满足以下需求：

- 配置中心密码登录保护（默认密码 `123456`，首次登录强制改密）
- 域名配置支持隐私保护展示（脱敏）
- AI 配置（provider/base_url/path/method/auth/headers/api_key/model/timeout）
- 系统配置（置信度阈值、RSS 拉取间隔、时区）

## 启动

```bash
cd services/web
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

访问：

- 登录页：`http://127.0.0.1:8080/admin/login`
- 配置页：`http://127.0.0.1:8080/admin/settings`

## API

- `GET /api/v1/config`：读取当前配置
- `POST /admin/login`：登录配置中心
- `POST /admin/change-password`：首次登录修改密码
- `POST /admin/settings/domain`：更新域名配置
- `POST /admin/settings/ai`：更新 AI 配置
- `POST /admin/settings/system`：更新系统配置
