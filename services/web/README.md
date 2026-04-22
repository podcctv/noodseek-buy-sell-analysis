# Web Admin（配置中心 + 实时看板）

本模块提供后端配置页面与前端实时看板，支持：

- 配置中心密码登录保护（默认密码 `123456`，首次登录强制改密）
- 域名配置支持隐私保护展示（脱敏）
- AI 配置（provider/base_url/path/method/auth/headers/api_key/model/timeout）
- 系统配置（置信度阈值、RSS 拉取间隔、时区）
- 实时 RSS 抓取 + AI 分类 + 进度展示

## 启动

```bash
cd services/web
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

访问：

- 首页看板：`http://127.0.0.1:8080/`
- 登录页：`http://127.0.0.1:8080/admin/login`
- 配置页：`http://127.0.0.1:8080/admin/settings`

## API

- `GET /api/v1/config`：读取当前配置
- `GET /api/v1/dashboard`：读取实时帖子 + 指标 + 热词
- `GET /api/v1/progress`：读取抓取/AI 处理进度
- `POST /api/v1/poll-now`：立即触发一次抓取与分析
- `POST /admin/login`：登录配置中心
- `POST /admin/change-password`：首次登录修改密码
- `POST /admin/settings/domain`：更新域名配置
- `POST /admin/settings/ai`：更新 AI 配置
- `POST /admin/settings/system`：更新系统配置
