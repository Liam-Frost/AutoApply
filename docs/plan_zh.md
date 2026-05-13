# AutoApply — 完整项目计划

本文档是端到端的权威项目计划：AutoApply 是什么、用什么搭的、已经完成了什么、
还有什么要做到 Phase 18（v1 商业化就绪核心）。

它和 `README.md`、`docs/PROJECT_MANAGEMENT.md`、`docs/AGENT_ARCHITECTURE.md`、
`docs/DECISIONS.md` 有意存在重叠。当几份文档相互冲突时，权威来源如下：

| 主题 | 权威来源 |
|---|---|
| 每个子阶段的范围、ETA、验收 | `docs/PROJECT_MANAGEMENT.md` |
| 每个设计选择 / 否决的原因 | `docs/DECISIONS.md` |
| Agent harness 内部细节 | `docs/AGENT_ARCHITECTURE.md` |
| 用户面向的部署 | `docs/DEPLOYMENT.md` |
| 本文 | 战略 + 历史 + 路线图汇总 |

最近更新：**2026-05-12（路线图 v2）**。

---

## 1. 目标

构建端到端的求职自动化系统，覆盖七层能力：岗位获取与过滤、申请人记忆、
简历与求职信定制、快速问题作答、文档处理、表单填写自动化、跟踪与分析。

自 2026-05-12 v2 重规划起保留了商业化野心：多租户、Redis 缓存、分布式锁、
按租户配额、Postgres RLS 全部已纳入路线图，即使目前还没有 SaaS 业务层规划。

## 2. 设计原则

1. **状态机驱动。** 每次申请都是一个状态机 —— 可中断、可恢复、可审计。
2. **块状简历生成。** 不做整篇 LLM 重写。从打标签的 bullet pool 选条目，
   可选地做轻量级 lexical rewrite，并由 fact-drift guard 兜底。
3. **DOCX-first 渲染。** LLM 产出结构化 IR；最终 DOCX/PDF 由确定性渲染器负责。
4. **每次提交都人工确认。** 默认在提交前暂停；`--auto-submit` 是可选的逃生口
   且仍要经过 gate queue。
5. **完整审计轨迹。** 截图、DOM 快照、文件版本、QA 应答全部持久化。
   Phase 13 进一步引入按内容哈希的 JD 快照，永远可以追溯某封信 / 某份简历
   是基于哪个 JD 版本生成的。
6. **LLM provider 抽象。** `src/providers/` 之外没有任何 subprocess- 或 REST-
   专属代码。所有调用点统一走 `generate_text()`。
7. **不做自主 agent。** Agent loop 是受限的：只能看到 orchestrator 显式允许的
   工具，只产出 proposal，不直接提交。

## 3. 技术栈

| 层 | 技术 | 选择理由 |
|---|---|---|
| 语言 / 运行时 | Python 3.12+，`uv` | 标准的 async + typing 基线 |
| 后端 | FastAPI + Click CLI（`autoapply`） | 同一份代码同时服务 Web + CLI |
| 前端 | Vue 3 + Vue Router + Vite + Tailwind v3 + shadcn-vue + reka-ui | 见 D015 |
| 浏览器自动化 | Playwright（Python，async） | 完整 DOM 访问 + LinkedIn 持久化登录上下文 |
| LLM provider | OpenAI / Anthropic / Gemini（REST via `httpx`）**或** Claude Code CLI / Codex CLI（subprocess），全部在 `ProviderRegistry` 后面 | 见 D016 |
| Agent harness | 自研，位于 `src/agent/` —— bounded ReAct loop、allow-listed `ToolRegistry`、文件后端 HITL gate、JSON 磁盘 trace store、fixture-driven eval | 见 D017（不用 LangChain / LangGraph） |
| 数据库（权威来源） | PostgreSQL + pgvector + alembic | 匹配用向量检索；alembic 管 schema migration |
| 缓存 / 锁 / 队列（Phase 12+） | Redis 7+ | L2 缓存、分布式锁原语（`SET NX PX`）、任务队列基础设施；见 D018 |
| 调度器（Phase 14+） | APScheduler + Postgres `SQLAlchemyJobStore` + advisory lock | 见 D021（不用 Celery、不用 SQLite、不用 OS cron） |
| 文档处理 | python-docx + docx2pdf / LibreOffice | DOCX-first；PDF 为衍生物 |
| 配置 | YAML（`config/settings.yaml`、`config/filters.yaml`、`config/companies.yaml`）+ `.env` override | 默认 → 文件 → 环境变量；credential URL 编码 |
| 目标 ATS 平台 | Greenhouse / Lever / Ashby；LinkedIn 用于发现 | 前三家直接 apply；LinkedIn 用 Playwright 持久化上下文做认证 |

## 4. 代码布局（实际情况，不是设想）

```
src/
├── core/                # Config loader、DB session、ORM models、状态机
├── agent/               # 自研 agent harness
│   ├── tools/           #   tool ABC + builtin / browser / profile tools
│   ├── core/            #   bounded ReAct loop + cost telemetry
│   ├── gate/            #   文件后端 HITL approval queue
│   ├── trace/           #   JSON 磁盘 trace store
│   └── eval/            #   fixture-driven eval runner + scorers
├── providers/           # LLM provider 抽象
│   ├── base.py          #   LLMProvider ABC + ProviderKind + AuthType
│   ├── openai.py / anthropic.py / gemini.py   # 通过 httpx 的 REST adapter
│   ├── claude_cli.py / codex.py               # Subprocess adapter
│   ├── api_base.py      #   共享 REST helper
│   ├── store.py         #   凭据存储（0600 文件 + OS keyring fallback）
│   └── registry.py      #   primary / fallback 分发到 generate_text
├── intake/              # 岗位抓取与 schema
│   ├── greenhouse.py / lever.py / linkedin.py # 适配器
│   ├── schema.py        #   RawJob / JobRequirements / 雇佣类型分类器
│   ├── jd_parser.py     #   LLM-assisted 解析 + 正则 fallback
│   ├── batch.py / search.py / storage.py
│   ├── filters.py       #   YAML-driven filter profile
│   └── search_cache.py  #   文件 JSON 缓存（Phase 13.8 将移除）
├── matching/            # 过滤与打分
│   ├── rules.py         #   硬规则（授权、经验、教育……）
│   ├── semantic.py      #   Embedding + TF 相似度打分
│   └── scorer.py        #   复合打分器 + 质量乘子
├── memory/              # 申请人记忆
│   ├── profile.py       #   identity / education / skills / experiences / projects
│   ├── bullet_pool.py   #   带标签的 bullet，含使用计数
│   ├── story_bank.py    #   STAR 故事 + 主题标签
│   ├── qa_bank.py       #   问题模式 + 标准答案 + 变体
│   └── resume_importer.py # PDF/DOCX → Claude CLI → 结构化 YAML
├── generation/          # 简历 + 求职信 + QA
│   ├── ir.py            #   简历 / 求职信 IR
│   ├── resume_builder.py
│   ├── cover_letter.py
│   ├── fitting.py       #   模板容量 fitting
│   ├── validator.py     #   产物校验（页数、长度）
│   └── qa_responder.py  #   分类器 + 多级 fallback
├── execution/           # 浏览器自动化 + 表单填写 + 提交
│   ├── browser.py       #   Playwright 包装
│   ├── form_filler.py   #   确定性填写器（默认路径）
│   ├── agent_form_filler.py # Phase 9 agent orchestrator
│   ├── file_uploader.py
│   └── ats/             #   按 ATS 的适配器（greenhouse / lever / ashby / generic / base）
├── documents/           # DOCX + PDF + 页数 + 模板
├── tracker/             # CRM：applications 表 + analytics + CSV export
├── application/         # CLI 与 Web 共用的应用层服务
├── cli/                 # Click 命令树（autoapply、init、search、apply、status、provider、web、eval、……）
├── web/                 # FastAPI app factory + JSON API + SPA static mount
└── utils/               # llm.generate_text bridge、rate limiter、logger
```

`src/` 下有 5 个早期占位的空目录仍然存在：`src/applicant/`、`src/cover_letter/`、
`src/filter/`、`src/resume/`、`src/scraper/`，下次清理时建议删掉。

## 5. 数据模型（当前）

当前 Postgres schema 见 `migrations/versions/`（alembic）。核心表：

```sql
jobs (
  id UUID PRIMARY KEY,
  source TEXT,                       -- greenhouse / lever / ashby / linkedin
  source_id TEXT,                    -- 各源的 job id；(source, company, source_id) 是去重键
  company TEXT NOT NULL,
  title TEXT NOT NULL,
  location TEXT,
  employment_type TEXT,              -- intern / fulltime / coop
  seniority TEXT,
  description TEXT,
  description_embedding vector(1536),
  requirements JSONB,
  visa_sponsorship BOOLEAN,
  ats_type TEXT,
  application_url TEXT,
  raw_data JSONB,
  discovered_at TIMESTAMPTZ DEFAULT NOW(),
  expires_at TIMESTAMPTZ
);

applications (
  id UUID PRIMARY KEY,
  job_id UUID REFERENCES jobs(id),
  status TEXT NOT NULL DEFAULT 'DISCOVERED',
  match_score FLOAT,
  resume_version TEXT,
  cover_letter_version TEXT,
  qa_responses JSONB,
  screenshot_paths JSONB,
  error_log TEXT,
  state_history JSONB,
  fields_filled INT, fields_total INT,
  files_uploaded JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  submitted_at TIMESTAMPTZ,
  outcome TEXT,                      -- pending / rejected / oa / interview / offer
  outcome_updated_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ
);

applicant_profile (
  id UUID PRIMARY KEY,
  section TEXT NOT NULL,             -- identity / education / skills / experience / projects
  content JSONB NOT NULL,
  content_embedding vector(1536),
  tags TEXT[],
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

bullet_pool (
  id UUID PRIMARY KEY,
  category TEXT,
  source_entity TEXT,
  text TEXT NOT NULL,
  text_embedding vector(1536),
  tags TEXT[],
  used_count INT DEFAULT 0
);

qa_bank (
  id UUID PRIMARY KEY,
  question_pattern TEXT,
  question_type TEXT,
  canonical_answer TEXT,
  variants JSONB,
  confidence TEXT DEFAULT 'high',
  needs_review BOOLEAN DEFAULT FALSE
);
```

申请状态机有 11 个状态：

```
DISCOVERED → QUALIFIED → MATERIALS_READY → FORM_OPENED
→ FIELDS_MAPPED → FILES_UPLOADED → QUESTIONS_ANSWERED
→ REVIEW_REQUIRED → SUBMITTED → FAILED → NEEDS_RETRY
```

Phase 13 会新增一组用于 **Job Index & Freshness Engine** 的表：

```sql
job_postings        -- 岗位实体（UNIQUE(source, source_job_id)）
job_snapshots       -- 内容版本，content_hash，不可变
search_queries      -- 归一化的搜索条件 + freshness 状态
search_results      -- search → posting 多对多（每次抓取）
refresh_tasks       -- 待抓取的优先级队列
```

再加 `application_records.job_snapshot_id` 外键，把每个生成产物钉到具体
JD 版本上。Phase 12+ 所有新表都带 `tenant_id`（Phase 18 之前默认 `"default"`），
见 D020。

## 6. 分层架构

### Layer 1: 岗位获取（Intake）
Greenhouse / Lever / Ashby / LinkedIn 适配器；统一 `RawJob` schema；
LLM-assisted JD 解析 + 正则 fallback；按 `(source, company, source_id)` 去重。
Phase 13 会用 Job Index & Freshness Engine 替换当前文件 JSON 缓存。

### Layer 2: 匹配与过滤
三层打分：
1. **硬规则**（工作授权、经验上限 + 1 年宽限、教育、雇佣类型、垃圾岗 / 幽灵岗检测）
2. **语义**（description / responsibilities / requirements 上的 embedding 重合 + 在缺 embedding 时退化到 TF 相似度）
3. **风险**（签证、ghost reposting、JD 过稀、缺 apply URL）

复合打分：加权 must-have（70%）/ preferred（30%）技能重合 + 关键词相似度 + 规则加分 × 质量乘子。

Phase 16 加入 reason chain，并为边界分 `[0.4, 0.6]` 启用 edge-case agent。

### Layer 3: 申请人记忆
Profile YAML → DB ingestion，按 section 生成 embedding，bullet 带标签。
`qa_bank` 支持按地区 + 职位类型的变体，并对高风险问题（工作授权、签证、
薪资、入职日期）打 `needs_review`。简历导入器把 DOCX / PDF 转成结构化 YAML
（通过 Claude CLI）。

### Layer 4: 简历 / 求职信生成
结构化 IR + 块状装配。Bullet 按标签重合度从池中选出，可选地在 fact-drift
guard 保护下做轻量级 lexical rewrite（长度比例落在 `[0.3, 2.0]` 之外的会
被拒绝）。求职信生成被约束在四个 section（opening / evidence / 公司挂钩 /
close），250-400 词，不允许编造。快速问题作答按 QA-bank → 模板 → LLM → 标记
review 的级联策略。

Phase 15 把求职信生成升级成 agent（绑定到具体的 `job_snapshot_id`）。

### Layer 5: 表单填写与提交
每次申请是 11 状态的状态机。确定性的 `form_filler.py` 仍是默认路径；
`agent_form_filler.py`（Phase 9）是 agent 路径，按置信度和 HITL 队列把关。
ATS 适配器在 `src/execution/ats/`（Greenhouse / Lever / Ashby / generic）。
Rate limiter 执行随机延时、小时上限、按错误冷却。

### Layer 6: 文件流水线
模板包位于 `data/templates/<document_type>/<template_id>/`，包含 `template.docx`、
`manifest.json`、`style.lock.json` 和样例 IR payload。DOCX 渲染使用 manifest 里
的命名 Word style 加 block marker（`{{resume.sections}}`、`{{cover_letter.body}}`）。
PDF 输出优先 Word + `docx2pdf`，否则降级到 LibreOffice。文件命名是
`{type}_{company}_{role}_{date}.{ext}`；每份产物都有版本号。

### Layer 7: 分析 / CRM
跟踪表记录 source、company、role、date、platform、resume version、match score、
status、outcome、outcome 时间戳。Analytics dashboard 提供 pipeline / outcome /
platform / company 维度的拆分。CSV export 默认排除 `error_log`。

## 7. 已交付的阶段

测试数为各阶段收尾时的快照。当前基线（Phase 10 后）：
**680 通过，1 跳过**（`pytest -q`），`ruff check src/ tests/` clean，
`npm run build` clean。

| Phase | 范围 | 状态 | 测试快照 |
|---|---|---|---|
| 1 | 基础设施 + 申请人记忆 + 文档流水线 | 完成 | — |
| 2 | 岗位获取 + 智能过滤 | 完成 | 156 |
| 3 | 简历/求职信定制 + QA | 完成 | — |
| 4 | 浏览器自动化 + 表单填写 | 完成 | 156 |
| 5 | CLI + 跟踪 + 全流水线 | 完成 | 177 |
| 6 | LinkedIn 集成 | 完成 | 207 |
| 7 | Web GUI（FastAPI + Vue SPA） | 完成 | 228 |
| 8 | Materials 工作区 + DOCX 模板包 + 加固 | 完成 | 340 |
| Agent 8 | Agent Harness（工具 / loop / trace / eval / HITL gate） | 完成 | — |
| Agent 9 | 表单填写 Agent + 成本遥测 + 5-fixture eval | 完成 | 553 |
| 10 | LLM Provider 抽象（REST + subprocess + 凭据存储 + Settings UI） | 完成 | 669 |

每个子阶段的发布记录见 `docs/CHANGELOG.md`。

## 8. 路线图（Phase 11 → 18） —— v2，重新规划于 2026-05-12

v2 重规划修正了 v1 草案的两个错误：

1. **PostgreSQL 是权威来源**，不是 SQLite。v1 草案写过 "L2 SQLite cache" 和
   "APScheduler + SQLite jobstore"，两处都错。本项目从来就跑在 Postgres +
   pgvector + alembic 上。（见 D021。）
2. **从 Phase 12 起引入 Redis** 作为缓存 / 锁 / 队列基础设施，为商业化部署
   保留通路。（见 D018。）

原先的 "JD scrape caching" 子阶段被升级为完整阶段（**Phase 13: Job Index &
Freshness Engine**），因为这个问题本质是内容版本化 + freshness 状态机 +
审计绑定，不是 KV 过期。（见 D019。）

新增 **Phase 18: Multi-Tenancy & Auth Hardening** 收尾 v1 商业化就绪核心；
Phase 12-17 所有表从第一天起就带 `tenant_id`。（见 D020。）

### Phase 11: 可靠性 & 收尾（~1 周）
加固 Phase 10 引入的 provider 层；交付老用户升级所需的 migrate 工具。
- **11.1** `generate_text` 中的 provider fallback 链（primary + 有序 fallback；
  quota / 网络 / auth 失败自动 failover；attempt 链记入 trace）。
- **11.2** `autoapply migrate` CLI：清理 codex-cli credential breadcrumb、
  重命名旧 settings key、检测过期凭据。
- **11.3** 文档同步 —— 把所有文档推到 Phase 10 完成态。
- **11.4** Provider health monitor：`/api/providers/health` 每 5 分钟探测；
  Settings 页 "Last verified" 显示真实遥测。

### Phase 12: 缓存基础设施（~1.5 周）
**首次引入 Redis。** 范围刻意收窄 —— 只做 LLM + embedding 响应缓存。
JD / 岗位内容缓存放到 Phase 13。
- **12.1** `src/cache/` 模块 —— L1 进程内 LRU + L2 Redis；namespace TTL
  （`llm:7d`、`embedding:30d`、`response:5m`）；统一 `get/set/invalidate` API；
  带版本号的 key。
- **12.2** Redis 基础设施 —— 连接池、健康检查、`REDIS_URL` 环境变量、
  `docker-compose.yml`、AOF 持久化、`autoapply redis ping/flush/info` CLI。
- **12.3** 分布式锁原语 —— `with cache.lock(key, ttl)`，基于 `SET NX PX`。
  Phase 13 force-refresh 会用。
- **12.4** LLM 响应缓存 —— `generate_text(cache=True)`；agent loop 默认 False，
  确定性 retrieval 默认 True；命中时累加省钱计数。
- **12.5** Embedding 缓存 —— `embed_text(cache=True)`，30 天 TTL。
- **12.6** Cache 检查 UI `/settings/cache`。
- **12.7** Cost dashboard 升级 —— Phase 9.4 聚合拆 "cached vs fresh" + $-saved 行。

### Phase 13: Job Index & Freshness Engine（~2 周）
用一套合规的 Job Intelligence Database 替换文件后端的
`src/intake/search_cache.py`。
- **13.1** Schema（alembic） —— `job_postings`、`job_snapshots`、`search_queries`、
  `search_results`、`refresh_tasks`；新增 `application_records.job_snapshot_id`
  外键；所有新表带 `tenant_id`。
- **13.2** 归一化层 —— `normalize_search_key()`、`normalize_job_content()`、
  `content_hash()`，hash 时排除不稳定字段（applicant_count、promoted 等）。
- **13.3** Freshness 状态机 `src/jobs/state.py` —— `new → active → stale → unknown
  → expired → archived`。
- **13.4** 搜索流程 —— 默认 cache-first；force-refresh 用 Phase 12 分布式锁
  包住 scrape；失败时保留旧缓存。
- **13.5** 内容版本化的详情 enrich —— scrape → normalize → hash → 当
  `content_hash` 变化时新建 `job_snapshot`；emit `job.content_changed` 事件。
- **13.6** Context-aware freshness —— `should_refresh(job, context)`，context ∈
  {`search_display: 72h`、`generate_materials: 24h`、`before_submit: 6h`}。
- **13.7** Web UI —— "Last updated 18h ago · Refresh"；刷新成功提示
  `N new / N expired / N updated`。
- **13.8** 把历史 `data/cache/linkedin_search/*.json` 迁到 `search_queries` +
  `search_results`；删掉文件缓存模块。

### Phase 14: 定时任务系统（~1.5 周）
- **14.1** APScheduler + Postgres `SQLAlchemyJobStore`（不是 SQLite，见 D021）；
  集成到 FastAPI lifespan；重启自动恢复。
- **14.2** RefreshTask worker —— 消费 Phase 13 的 `refresh_tasks`；优先级
  `critical / high / normal / low`；按源做并发限制。
- **14.3** 内建任务 —— `daily_search`、`jd_health_check`（推动 Phase 13 状态机）、
  `application_status_sync`、`linkedin_cookie_refresh`、`cache_eviction`。
- **14.4** CLI —— `autoapply schedule list / add / remove / pause / run-now / logs`。
- **14.5** Web UI `/schedule`。
- **14.6** 多实例安全 —— 每个 job 用 Postgres advisory lock，防止两个
  `autoapply web` 副本同一任务重复触发。
- **14.7** Trace 集成 —— 每次调度运行写一条 trace（复用 Phase 8.3 store）。

### Phase 15: Cover-letter Agent（~2 周）
原 "Phase 10" 计划。受益于 Phase 12（LLM 缓存）和 Phase 13（snapshot 绑定）。
- **15.1** `jd_lookup` 工具 —— 按 section 读取某个 `job_snapshot_id` 的 JD。
- **15.2** `AgentCoverLetter` orchestrator —— 输出带 evidence 引用的求职信 IR；
  现有 fact-drift checker 作为 post-guard；agent 失败时降级到确定性路径。
- **15.3** 生成前 freshness gate —— 若 `should_refresh(job,
  "generate_materials")`，先 enrich。
- **15.4** 绑定 `CoverLetterVersion.job_snapshot_id`。
- **15.5** Eval suite —— 5 个 fixture + `fact_drift_score`、`keyword_coverage`、
  `length_compliance` 三个 scorer。
- **15.6** HITL gate —— 只在 agent 改 bullet / story bank 时触发，不在
  生成 letter 本身。

### Phase 16: Filter Agent + 可解释性（~1.5 周）
不替换确定性 filter —— 在其之上加可解释层 + 仅对边界岗位调用 agent。
- **16.1** Filter reason chain 在 `src/matching/` —— 每个 reject 记
  `{rule_id, rule_name, reason, evidence_excerpt, job_snapshot_id}`。
- **16.2** Edge-case agent —— 只对 [0.4, 0.6] 分段调用；用 Phase 8 harness +
  新工具 `score_breakdown`。
- **16.3** Web UI "Why was this filtered?" 按钮。
- **16.4** Eval suite —— 10 个人工标注的边界岗位；agent 决策与人工一致率 ≥ 70%。

### Phase 17: 夜跑闭环 + Review Queue（~2 周）
集成阶段。把 Phase 14（调度器）+ Phase 13（job-index / freshness）+
Phase 12（缓存）+ Phase 9 / 15（agent）串成 "睡一觉，醒来看 review queue" 的
完整流程。
- **17.1** `nightly_run` orchestrator —— search（cache-first，stale 自动刷新）→
  filter（带 16 的可解释性）→ top-N → form-filler（Phase 9）+ cover-letter
  （Phase 15）→ 入队。**永不自动提交。**
- **17.2** Review queue 模型 —— `review_queue(id, tenant_id, job_id,
  job_snapshot_id, materials_path, status, ...)`；状态机
  `pending → approved → submitted` 或 `pending → rejected`。
- **17.3** `/review` kanban UI。
- **17.4** 批量操作 —— 多选 approve、按 company / keyword 批量 reject。
- **17.5** 提交前硬 gate —— 重跑 `should_refresh(job, "before_submit")`；
  > 6h stale 则先刷新；岗位已 expired 完全阻止提交。
- **17.6** 早间 digest（08:00）。
- **17.7** `autoapply pause-nightly` kill switch。

### Phase 18: 多租户 & Auth 加固（~2 周）
激活 Phase 12-17 散布的商业化就绪工作。SaaS 业务层（计费、注册流、营销页）
**不在范围内** —— 本阶段只让现有系统能安全托管多个隔离用户。
- **18.1** `tenants` + `users` 表；现有数据迁到 `tenant_id="default"`。
- **18.2** FastAPI auth 中间件 —— 每个请求推导 `current_tenant_id`；所有 query /
  Redis namespace / cache key / refresh-task selector 自动按它过滤。
- **18.3** Postgres Row-Level Security policy（DB 层兜底）。
- **18.4** 按租户的 Redis namespace —— `tenant:{id}:llm:...`。
- **18.5** 按租户的配额（LLM token、scrape 速率、存储）。超限返回 429。
- **18.6** Audit log 表 —— `audit_events`（提交、设置变更、凭据操作、手动调度
  触发）。append-only。
- **18.7** 按租户的凭据存储。

### 时间表

| Phase | 范围 | 工时 | 累计 |
|---|---|---|---|
| 11 | 可靠性 & 收尾 | 1 周 | 1 周 |
| 12 | 缓存基础设施（Redis） | 1.5 周 | 2.5 周 |
| 13 | Job Index & Freshness Engine | 2 周 | 4.5 周 |
| 14 | 定时任务系统 | 1.5 周 | 6 周 |
| 15 | Cover-letter Agent | 2 周 | 8 周 |
| 16 | Filter Agent + 可解释性 | 1.5 周 | 9.5 周 |
| 17 | 夜跑闭环 + Review Queue | 2 周 | 11.5 周 |
| 18 | 多租户 & Auth 加固 | 2 周 | 13.5 周 |

约 3 个月推到 v1.0 商业化就绪核心（不含 SaaS 业务层）。

## 9. 横切质量基线

Phase 11 起强制执行：

- **测试** —— 任何 PR 都不能让套件低于当前 680 个通过。
- **Lint** —— `ruff check src/ tests/` 保持 clean。
- **每个子阶段 codex review** —— commit 前跑 `codex review --uncommitted`；
  P1 finding 阻止合并。
- **成本上限** —— 任何 eval suite 把总成本推到 $1.00 / 100 case 之上都要
  显式给理由。
- **文档同步** —— `docs/PROJECT_MANAGEMENT.md` + `docs/CHANGELOG.md` 在每个
  Phase 收尾时更新，不要攒一批。
- **多租户卫生**（Phase 12+） —— 每张新表带 `tenant_id`；每个新 Redis key
  带前缀；每个新后台任务接收 tenant 上下文。零例外，否则 Phase 18 变成重写。

## 10. 验收清单（按 Phase 的 smoke）

| Phase | Smoke 命令 / 观察项 |
|---|---|
| 1 | 加载 profile YAML → 入库 → 生成一份定制 Word resume + PDF |
| 2 | 从 Greenhouse 抓岗位 → 打分排序 → top-N |
| 3 | 给定 JD → 自动选 bullet → 定制 resume + CL + 快速问题作答 |
| 4 | 给一个 Greenhouse 岗位 → 自动填表 → 上传文件 → 截图（不提交） |
| 5 | 10 条岗位跑全流水线 → 看跟踪 dashboard → 分析报告 |
| 6 | LinkedIn 搜索 → 外部 ATS 链接解析 → 接入现有 apply / material 流水线 |
| 7 | `autoapply web` → Vue SPA 搜索 / 跟踪 / 设置 |
| 8 | `/jobs` → `/materials?jobId=...` → DOCX/PDF 生成、预览、校验、下载 |
| Agent 8 | `autoapply eval --suite agent_smoke` → 全部 case 通过 |
| Agent 9 | `autoapply eval --suite form_filler --min-pass-rate 0.85` → 5/5 通过，估计成本 ≤ $0.25 |
| 10 | Settings 页 → 连接 / 测试 / 断开每个 provider；`autoapply provider test <name>` 报真实 auth 状态 |
| 11 | 中途 revoke primary provider → fallback 链生效 → eval 仍通过；`autoapply migrate` 清理遗留状态 |
| 12 | 同 batch 跑第二次 → LLM cache hit-rate > 80%、wall time < 20%、cost < 5%；Redis 重启后 L2 entry 恢复 |
| 13 | 同搜索条件二次访问 < 2s（无 HTTP）；岗位内容变了产生新 `job_snapshot`；revoke LinkedIn cookie → 旧缓存仍可展示 |
| 14 | 注册 `daily_search` `* * * * *` → 下次 tick 触发；重启进程，jobstore 恢复；两个 web 副本不重复触发 |
| 15 | Cover-letter eval 5/5 通过；cache-miss ≤ $0.08/封，cache-hit ≤ $0.02/封 |
| 16 | JobsView 任意被过滤的岗位 5 秒内看到 reason chain；100 个岗位 agent 成本 < $0.50 |
| 17 | 周一 23:00 调度夜跑 → 周二 08:00 review queue 已有 N 条预生成 application，每条 30 秒内可 approve |
| 18 | 两个 tenant 设了重叠 email / LinkedIn cookie → 互相读不到对方的 job / snapshot / application / credential / Redis key（直 SQL + 直 Redis CLI 验证）；超配额返回 429 |

## 11. 风险与未决问题

- **LinkedIn 限流 / 检测。** 通过持久化 context cookie、随机延时、控并发、
  以及 Phase 13 由分布式锁把关的 force-refresh 来缓解。激进的夜跑调度仍有实际
  风险。
- **LLM 成本漂移。** 通过 Phase 12 缓存 + Phase 11 fallback 链（廉价模型作为
  fallback 槽）+ $1 / 100 case 的 eval 上限来缓解。Phase 9.4 的成本遥测是早期
  预警。
- **当下仍是单实例假设。** Phase 14.6 + D018 铺了多实例工作；Phase 18 才真正
  做实。在此之前，**不要**对同一 Postgres / Redis 起两个 `autoapply web` 进程
  —— 数据层允许但没有 advisory lock，会引发重复提交。
- **Auto-submit 安全性。** `apply` 里有 `--auto-submit`，但仍走 HITL gate。
  我们还没看到能让我们按 vendor 摘掉 gate 的 eval 数据。
- **没有 SaaS 业务层。** Phase 18 是多租户托管基础设施，不是计费 / 注册 /
  营销。除非有商业 license 客户签约，否则这部分都在范围外。
