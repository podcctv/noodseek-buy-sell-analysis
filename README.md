# NodeSeek Buy/Sell Analysis

一个面向 `https://rss.nodeseek.com/` 交易帖子的数据采集与 AI 分析系统。

## 项目目标

- 采集 NodeSeek 交易分类 RSS 帖子。
- 用 AI 将帖子归类为「求购 / 出售 / 无法判断」。
- 提取结构化维度：品牌、产品、价格、溢价、价格趋势。
- 展示每小时汇总与日/周热点分析。
- 提供人工训练页面，沉淀可复用的“记忆”能力。
- 全流程 Docker 化部署，并提供一键安装/更新脚本。

## 核心能力

1. **数据采集**
   - 定时拉取 RSS（建议每 5~10 分钟）
   - 按 `guid/link + 发布时间` 去重

2. **AI 分类与抽取**
   - 规则优先（关键词）+ LLM 兜底
   - 输出统一 JSON：
     - `intent`: `buy|sell|unknown`
     - `brand`
     - `product`
     - `price`
     - `premium`
     - `trend`
     - `confidence`

3. **可插拔 LLM Provider**
   - 当前支持：`https://llm.428048.xyz/v1/chat/completions`
   - 目标支持：任意 OpenAI 兼容 API（base_url + api_key + model）

4. **可视化与运营**
   - 实时帖子列表
   - 每小时汇总看板
   - 日/周热点分析
   - 无法判断池（人工标注）

5. **训练闭环与记忆**
   - 规则记忆：人工维护关键词/模式
   - 样本记忆：历史标注样本优先匹配
   - Prompt 记忆：高质量样本作为 few-shot

## 推荐架构

- `collector`：RSS 抓取与去重
- `analyzer`：规则 + LLM 分析 + 训练记忆
- `web`：API + 页面展示
- `db`：PostgreSQL
- （可选）`redis`：队列与缓存

## 目录规划（建议）

```txt
.
├── README.md
├── docs/
│   └── PROJECT_PLAN.md
├── deploy/
│   ├── docker-compose.yml
│   ├── install.sh
│   ├── update.sh
│   ├── backup.sh
│   └── restore.sh
├── services/
│   ├── collector/
│   ├── analyzer/
│   └── web/
└── db/
    └── migrations/
```

## 环境变量（草案）

```bash
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://llm.428048.xyz/v1
LLM_API_KEY=your_api_key
LLM_MODEL=your_model

DATABASE_URL=postgresql://user:pass@db:5432/nodeseek
REDIS_URL=redis://redis:6379/0

ANALYSIS_CONFIDENCE_THRESHOLD=0.70
RSS_POLL_INTERVAL_SECONDS=300
```


## 一键安装 / 升级（含脚本自升级）

> 先把 `REPO_SLUG` 改成你自己的仓库地址（例如 `alice/noodseek-buy-sell-analysis`）。

### 一键安装

```bash
curl -fsSL https://raw.githubusercontent.com/<REPO_SLUG>/main/deploy/install.sh -o /tmp/nodeseek-install.sh
chmod +x /tmp/nodeseek-install.sh
SCRIPT_PATH=/tmp/nodeseek-install.sh REPO_SLUG=<REPO_SLUG> bash /tmp/nodeseek-install.sh
```

### 一键升级（应用 + install.sh 自身）

```bash
REPO_SLUG=<REPO_SLUG> bash $HOME/noodseek-buy-sell-analysis/deploy/update.sh
```

升级逻辑：
- `update.sh` 会优先调用本地 `install.sh`。
- `install.sh` 会先检查远程同路径脚本版本，如有新版本会先替换自己再继续执行。
- 然后重新拉取 `deploy/docker-compose.yml` 与最新镜像并重启服务。

## Docker 镜像 GitHub Action 与直接拉取

仓库已补充工作流 `.github/workflows/docker-image.yml`：
- `push main` / `push tag(v*)` 自动构建并推送到 `ghcr.io/<owner>/<repo>`。
- PR 仅构建不推送。

你可以直接通过 GitHub Container Registry 拉取镜像：

```bash
docker pull ghcr.io/<owner>/<repo>:latest
# 或者指定 tag/commit SHA
docker pull ghcr.io/<owner>/<repo>:v1.0.0
```

## 开发路线

详见 [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md)。

## 后续建议

- 增加价格异常告警（阈值通知）
- 增加 Telegram/飞书机器人推送
- 增加导出 CSV/Excel
- 增加审计日志与操作回滚

## 新增：后端配置中心（Admin）

已提供 `services/web` 模块，用于在后端页面统一管理：

- 域名与隐私保护展示
- AI Provider 与模型参数
- 系统运行参数（阈值、轮询、时区）

详见：`services/web/README.md`。
