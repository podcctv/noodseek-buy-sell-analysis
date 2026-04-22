# 项目规划（V1）

## 1. 范围与目标

构建一套可持续运行的 NodeSeek 交易帖分析系统，实现以下闭环：

1. RSS 采集交易分类帖子
2. AI 分类为求购/出售/无法判断
3. 结构化抽取品牌、产品、价格、溢价、趋势
4. 前端可视化汇总与热点分析
5. 人工训练与模型记忆
6. Docker 一键部署与更新

---

## 2. 功能拆解

### 2.1 采集层

- 定时任务拉取 `https://rss.nodeseek.com/`
- 去重策略：`guid` 优先，`link + published_at` 兜底
- 保存原始内容与拉取日志

### 2.2 分析层

#### A. 规则引擎（高置信）
- 求购关键词：收、求购、想买、蹲
- 出售关键词：出、出售、转让、清仓

#### B. LLM 引擎（中/低置信）
- 对未命中规则的帖子发起 LLM 分析
- 返回统一 JSON 结构并附 `confidence`

#### C. 结果路由
- `confidence >= threshold` -> 自动入库
- `confidence < threshold` 或 `unknown` -> 人工待处理池

### 2.3 训练层（记忆）

- **规则记忆**：人工可新增关键词规则
- **样本记忆**：历史标注样本相似匹配优先
- **提示记忆**：高质量样本作为 few-shot 提示

### 2.4 展示层

- 实时帖子页：最新帖子 + 分类结果
- 每小时汇总页：数量、占比、均价分布
- 热点分析页：日/周维度品牌热度、价格趋势
- 人工训练页：集中处理 unknown/低置信数据

---

## 3. LLM Provider 兼容设计

定义统一接口：

- `analyze_post(post_text, schema) -> AnalysisResult`

Provider 实现建议：

- `OpenAICompatibleProvider`（当前使用）
- `OpenAIProvider`（官方）
- 未来可扩展其他兼容厂商

通过环境变量切换，不改业务逻辑。

---

## 4. 数据模型（最小可用）

- `posts`
  - id, guid, link, title, content, author, published_at, fetched_at
- `analysis_results`
  - post_id, intent, brand, product, price, premium, trend, confidence, reason, model, created_at
- `manual_labels`
  - post_id, final_intent, final_brand, final_product, final_price, final_premium, final_trend, labeler, created_at
- `rules`
  - id, type(intent/brand/product/price), pattern, action, priority, enabled
- `hourly_stats` / `daily_stats`
  - bucket_time, total_posts, buy_count, sell_count, unknown_count, avg_price, avg_premium

---

## 5. Docker 与脚本交付

### 5.1 部署清单

- `deploy/docker-compose.yml`
- `deploy/install.sh`
- `deploy/update.sh`
- `deploy/backup.sh`
- `deploy/restore.sh`

### 5.2 一键脚本约定

- `install.sh`
  - 初始化 `.env`
  - 启动数据库与应用容器
  - 执行迁移
- `update.sh`
  - 拉取镜像/代码
  - 执行迁移
  - 重启服务

---

## 6. 迭代计划（4 周）

### 周 1：MVP
- RSS 拉取 + 入库 + 去重
- 规则分类 + LLM 调用
- 基础列表页

### 周 2：训练闭环
- unknown 池
- 人工标注页
- 标注回写与优先匹配

### 周 3：分析看板
- 每小时汇总
- 日/周热点分析
- 多维筛选与导出

### 周 4：稳定性与运维
- 告警、重试、审计日志
- 备份恢复
- 成本监控（token 用量）

---

## 7. 可用性增强（建议优先级）

1. 规则可视化管理（高）
2. 置信度阈值动态调节（高）
3. 高价值帖通知（高）
4. 价格异常告警（中）
5. 导出报表（中）
6. 审计与回滚（中）
7. 多租户/多数据源（低）

---

## 8. 验收标准（V1）

- 采集成功率 >= 99%
- 分类可用率（自动 + 人工）= 100%
- unknown 占比 2 周内下降（通过训练）
- 页面支持按小时查看汇总
- Docker 一键安装与更新可执行
