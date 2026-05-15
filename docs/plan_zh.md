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

最近更新：**2026-05-14（路线图 v3.1）**。v3.1 在 v3 基础上做了四处校准：
(a) Phase 14 任务队列改用 Celery（不再自建 task model + queue transport + worker runtime；见 D025），APScheduler 也随之退场，由 Celery Beat 承担 cron trigger；
(b) Phase 14 前插入 13.9 子阶段，给所有 Phase 11 及以前的遗留表做一次性 `tenant_id` retrofit migration，把 D020 的"纪律"变成 schema 强制（见 D026）；
(c) HITL gate 后端从单进程文件 JSON 迁到 Celery 任务态 / Postgres 持久化层，避免 Phase 14 多 worker 与 Phase 17 review queue 各自再造（并入 14.x，见 D026）；
(d) Phase 15.3 LaTeX 范围澄清：`src/documents/latex_engine.py` 已存在，Phase 15 不是"从零搭 LaTeX"，而是"加模板包规范 + manifest + adapter"。

---

## 1. 目标

构建端到端的求职自动化系统，覆盖七层能力：岗位获取与过滤、申请人记忆、
简历与求职信定制、快速问题作答、文档处理、表单填写自动化、跟踪与分析。

自 2026-05-12 v2 重规划起保留了商业化野心，并在 2026-05-14 v3 更新中
进一步明确：多租户、Redis 缓存 / 队列传输、分布式锁、按租户配额、
Postgres RLS、后台 worker 模型全部已纳入路线图，即使目前还没有 SaaS 业务层规划。

## 2. 设计原则

1. **状态机驱动。** 每次申请都是一个状态机 —— 可中断、可恢复、可审计。
2. **基于证据的材料生成。** 不做整篇 LLM 重写。Agent 从 profile facts、
   story bank、带标签的 bullet pool 中选择证据，可选地做轻量级 lexical rewrite，
   并由 fact-drift guard 兜底。
3. **两条简历路径。** 需要保留用户原始风格时，patch 用户上传的可编辑源文件；
   从零生成新简历时，以 LaTeX-first 模板包为主。两条路径都要求 LLM 产出结构化
   IR 或 adapter proposal；最终文件由确定性 renderer 负责。
4. **每次提交都人工确认。** 默认在提交前暂停；`--auto-submit` 是可选的逃生口
   且仍要经过 gate queue。
5. **完整审计轨迹。** 截图、DOM 快照、文件版本、QA 应答全部持久化。
   Phase 13 进一步引入按内容哈希的 JD 快照，永远可以追溯某封信 / 某份简历
   是基于哪个 JD 版本生成的。
6. **LLM provider 抽象。** `src/providers/` 之外没有任何 subprocess- 或 REST-
   专属代码。所有调用点统一走 `generate_text()`。
7. **队列管理自动化。** 后台 task 负责调度、重试、幂等和 worker 生命周期。
   Agent 只在单个有边界的 task 内运行并返回结构化结果，不负责 queue ack/nack
   或全局编排。

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
| 任务队列 / 调度（Phase 14+） | Celery 5.x + Redis broker + Redis result backend + Celery Beat（cron trigger） | 见 D025（替换原计划的"自建 queue + APScheduler"），D023 关于 agent/queue 职责切分的原则保留 |
| 文档处理 | python-docx + LaTeX toolchain + docx2pdf / LibreOffice | 原始简历走 DOCX patch；新生成简历走 LaTeX-first；PDF 为衍生物 |
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

再加 `applications.job_snapshot_id` 外键，把每个生成产物钉到具体
JD 版本上。Phase 12+ 所有新表都带 `tenant_id`（Phase 18 之前默认 `"default"`），
Phase 13.9 还会给所有遗留表（`jobs`、`applications`、`applicant_profile`、
`bullet_pool`、`story_bank`、`qa_bank` 等）回填同样的列，见 D020 / D026。

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

## 8. 路线图（Phase 11 → 18） —— v3.1，2026-05-14 校准

v3 在 v1/v2 上修正了四个问题（保留如下）；v3.1 又对 v3 做了四处校准（见本节
开头版本说明）。

v2/v3 重规划修正了 v1 草案的四个问题：

1. **PostgreSQL 是权威来源**，不是 SQLite。v1 草案写过 "L2 SQLite cache" 和
   "APScheduler + SQLite jobstore"，两处都错。本项目从来就跑在 Postgres +
   pgvector + alembic 上。（见 D021。）
2. **从 Phase 12 起引入 Redis** 作为缓存 / 锁 / 队列基础设施，为商业化部署
   保留通路。（见 D018。）
3. **自动化夜跑需要任务队列。** Phase 14 明确 Redis queue + Postgres task state +
   worker 边界，而不是把后台工作藏在 scheduler 细节里。（见 D023。）
4. **材料生成需要两种简历模式。** Phase 15 现在同时覆盖原始简历 patch 和
   LaTeX-first 生成，而不只是 Cover-letter Agent。（见 D024。）

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
- **13.9** **tenant_id retrofit migration**（Phase 14 开工前必须落地，见 D026）——
  alembic 新 migration 给所有 Phase 11 及以前的遗留表（`jobs`、`applications`、
  `applicant_profile`、`bullet_pool`、`qa_bank` —— `story_bank` 是 YAML，
  `template_packages` 是文件系统模板）加 `tenant_id TEXT NOT NULL DEFAULT 'default'` 列 +
  backfill 现有行；ORM models 同步加字段；现有 query 路径不强制改（保留无过滤的
  全局行为），但 Phase 14 开始所有新代码必须显式带 tenant 上下文。Phase 18 的
  auth middleware 上线后这层"默认 default"的兜底就被 RLS + 中间件取代。**已完成**
  （migration `d8a5c2f1e9b3`，commit `ae46a39`）。

### Phase 14: 任务队列 + 定时工作（~2.5 周，Celery） —— **已完成**

10 个子阶段全部在 `feat/phase-14` 分支上线（commits `83de0db` → `707d94e`）+
两轮 codex review 修复（`3de7084`）。验证基线：1161 passed / 1 skipped；
`ruff check` 干净；前端构建干净；migrations `e1b4f72c8a05`（tasks audit table）
+ `f2c5d83a91b6`（gate_queue）已应用到 dev DB。

改用 Celery 5.x（见 D025）。原计划自建的 task model + queue transport + worker
runtime 全部由 Celery 接管；AutoApply 只在它上面薄薄加一层"agent 边界 + HITL +
trace + tenant 上下文"的 wrapper。D023 关于"queue 拥有执行可靠性、agent 拥有
bounded 决策"的原则保留。

- **14.1** **Celery 接入 + 项目基础**。`celery_app = Celery("autoapply",
  broker=REDIS_URL, backend=REDIS_URL)`、`autoapplyCfg.task_acks_late = True`、
  `task_reject_on_worker_lost = True`、`worker_prefetch_multiplier = 1`（长任务模型，
  不要 prefetch）。task 路由：`search.*` / `materials.*` / `application.*` /
  `maintenance.*` 四个 queue。
- **14.2** **持久化 audit table**（Postgres，权威源）。Celery 的 result backend
  只是 transient，AutoApply 自己维护 `tasks` 表：`id`、`celery_task_id`、`tenant_id`、
  `kind`、`payload`、`idempotency_key`、`status`（`queued/running/waiting_human/
  succeeded/failed/cancelled`）、`attempts`、`parent_task_id`、`trace_id`、
  `created_at`、`finished_at`。Celery signals (`task_prerun` / `task_postrun` /
  `task_failure` / `task_retry`) 自动更新这张表。
- **14.3** **Custom `AutoApplyTask` base class**（Celery `Task` 子类）—— 提供：
  (a) 从 task headers 取 `tenant_id` 注入到 DB session 和 Redis namespace；
  (b) idempotency key 入口检查（已存在 succeeded 记录直接返回）；
  (c) `self.call_agent(...)` 包装：单次 task 内调一次 bounded agent，按结构化
  返回值 (`success` / `failed_retryable` / `failed_terminal` / `needs_human` /
  `needs_followup_task`) 决定 `raise self.retry()` 还是入 gate 还是 enqueue 子
  task；(d) 写 trace 记录。
- **14.4** **HITL gate 后端迁到 DB**（取代单进程文件 JSON，见 D026）。新表
  `gate_queue(id, tenant_id, task_id, kind, payload, status, requested_at,
  decided_at, decision, reason)`；状态 `pending → approved → rejected`。
  Celery task 返回 `needs_human` 时只是把当前 task 状态转 `waiting_human`，
  *不* 阻塞 worker；用户审批后调 `/api/gate/{id}/approve` enqueue 一个 `resume`
  task 重新跑（用同一 idempotency key）。`src/agent/gate/queue.py` 旧 file-backend
  作为兼容层保留一个发布期，然后删除。
- **14.5** **Celery Beat 接入**（取代 APScheduler，APScheduler 完全退场）。
  Beat schedule 在 `src/tasks/beat.py` 声明：`daily_search`、`jd_health_check`
  （驱动 13.3 freshness 时间衰减）、`application_status_sync`、
  `linkedin_cookie_refresh`、`cache_eviction`。Beat 只 enqueue，永远不在 Beat 进程
  里跑业务。多实例 Beat 用 `celery-redbeat` 或 Postgres advisory lock 防双触发。
- **14.6** **Task kinds 实现**：`search.refresh`、`jobs.enrich`、
  `materials.generate`、`application.prepare`、`application.fill`、
  `application.submit`、`status.sync` 各自一个 Celery task；每个走 14.3 的
  `AutoApplyTask` 基类；payload schema 用 Pydantic 模型校验。
- **14.7** **CLI**：`autoapply worker --queues search,materials,apply --concurrency 4`
  （内部 `celery -A src.tasks worker ...`）；`autoapply beat`（启 Beat）；
  `autoapply tasks list/retry/cancel/inspect`（读 14.2 的 audit 表）；
  `autoapply schedule list/pause/run-now`（读 Beat schedule + enqueue 一次性 task）。
- **14.8** **Web UI** `/schedule` + `/tasks` + `/gate`：从 audit 表读 queue depth、
  在跑的 worker（通过 Celery inspect API）、失败原因、手动 retry/cancel；
  `/gate` 取代旧的 agent gate viewer。
- **14.9** **Trace 集成**：`AutoApplyTask.on_success/on_failure/on_retry` 自动写
  trace；child task header 带 `parent_trace_id`，trace viewer 可以从一个 task
  跳到它的 parent/children 链路。
- **14.10** **多实例安全**：Celery 自身保证 task 只被一个 worker 拿到；Beat 多实例
  用 redbeat 的 leader election；advisory lock 兜底（保留 D021 的多实例双触发
  防御原则）。

### Phase 15: Resume & Cover Letter Generation v2（~3 周） —— **已完成**

10 个子阶段全部在 `feat/phase-15` 分支上线（commits `4e95e98` → `439d2d7`）+
一轮 codex review P2 修复（`9b813a3`）。验证基线：1332 passed / 1 skipped；
`ruff check` 干净；migration `a3b9d52e7c41`（source_resumes）已应用到 dev DB。
实现 highlights：

* `src/generation/source_resume.py` —— 上传简历 ingest 管线（DOCX/LaTeX/PDF）
* `src/generation/docx_patch.py` —— 命名样式保留的 DOCX patch 模式
* `src/documents/latex_manifest.py` + `latex_renderer.py` —— manifest-adapter
  LaTeX 渲染（基于已存在的 `latex_engine.py`，不是从零搭）
* `src/generation/materials_router.py` —— patch_existing vs generate_from_template
  调度，每个产物绑定 job_snapshot_id / source_resume_id / template_package_id /
  trace_id
* `src/agent/tools/jd.py` —— jd_lookup agent tool
* `src/generation/agent_cover_letter.py` + `fact_drift.py` —— 五级 fallback
  ladder + 数字漂移阻断
* `src/documents/template_adapter.py` —— 任意 LaTeX 模板 manifest 提案
* 三个 eval suite + 7 个 fixture
* `src/generation/gate_triggers.py` —— 仅持久化 grounding 变更触发 HITL gate
受益于 Phase 12（LLM 缓存）、Phase 13（snapshot 绑定）和 Phase 14（后台材料任务）。
- **15.1** Source-resume model：上传原件按 type、checksum、抽取结构、editability
  flag 存储。PDF 只承诺用于事实抽取，不承诺保格式编辑。
- **15.2** DOCX patch mode：局部修改 summary、bullets、skills 顺序、section 取舍，
  尽量保留原有 styles 和 DOCX 允许保留的布局结构。**降级路径**：当 patch 失败
  （style 找不到、IR 字段映射不上、修改后页数爆掉），自动降级到
  `generate_from_template` 路径，并在 UI / task 结果里告知用户原因，不要让用户
  以为 DOCX 100% 保真。
- **15.3** LaTeX template package 规范。注意 `src/documents/latex_engine.py`
  里编译/渲染原语已存在（Phase 8 期间随 DOCX 模板包一起做的），本子阶段做的是
  *规范化模板包结构*：`template.tex`、assets、`template.manifest.yaml`、sample IR、
  compile engine 选择（`pdflatex` / `xelatex` / `lualatex`）、容量 / 页数规则、
  command / field mapping、escape 规则白名单。重点不是写 renderer，是定义
  manifest schema + 适配器约定。
- **15.4** LaTeX-first resume generator：agent 产出结构化 resume IR；确定性
  renderer（复用已有 `latex_engine.py`）负责 escape、按 manifest 映射、编译、
  校验页数 / 容量。把 `resume_builder.py` 的 LaTeX 分支从"自定义 IR 直转"重构成
  "走 manifest 适配器"。
- **15.5** Materials router：`patch_existing` vs `generate_from_template`，两者都以
  `materials.generate` task 运行，并绑定 `job_snapshot_id`、source/template ID、
  profile version、trace ID。
- **15.6** 共享 `jd_lookup` 工具，供 resume 和 cover-letter agent 使用。
- **15.7** `AgentCoverLetter` orchestrator 输出带 evidence 引用的求职信 IR；现有
  fact-drift checker 作为 post-guard；agent 失败时降级到确定性路径。
- **15.8** Template adapter assistant：agent 可为任意新 LaTeX 模板提议 manifest，
  但持久化前必须 sample compile 通过并由用户确认。
- **15.9** Eval suite 覆盖 DOCX patch fixture、LaTeX template fixture、
  cover-letter fixture。
- **15.10** HITL gate 只在 agent 改 bullet / story bank 或持久化 template adapter
  时触发，不在普通生成时触发。

### Phase 16: Filter Agent + 可解释性（~1.5 周） —— **已完成**

4 个子阶段全部在 `feat/phase-16` 分支上线（commits `203becb` →
`9198a3b`）+ 一轮 codex review P2 修复（`5702da7`）。验证基线：
1398 passed / 1 skipped；`ruff check` 干净；前端 build 干净。

实现 highlights：

* `src/matching/rules.py` —— `RuleResult` 加入 `rule_id` / `verdict` /
  `evidence_excerpt`；每个 hard rule 都从 JD 抽取一段有界
  excerpt（~200 chars，trigger phrase 两侧各 ~80 chars 上下文，
  whitespace 折叠，超长加 ellipsis）
* `src/matching/scorer.py` —— `ScoreBreakdown.job_snapshot_id` +
  `disqualify_results` + `to_dict()`
* `src/agent/tools/score_breakdown.py` —— 只读 dotted-path tool，
  在 agent 实例化时绑定到单个 breakdown
* `src/matching/edge_case_agent.py` —— 只在 `0.4 <= score <= 0.6`
  且非 hard-rule 拒绝时触发；失败一律 fail-closed 走 fallback
  ladder（agent_error / agent_malformed / not_invoked）；
  **永远不会覆盖 hard rules**
* `src/application/matching.py` + `POST /api/matching/explain` ——
  按需重新打分接口，供 popover 调用
* `frontend/src/views/JobsView.vue` —— 每个被过滤掉的 job 卡片上
  加 Info 按钮 + Dialog popover（显示 rule 名、verdict chip、
  reason、evidence_excerpt、snapshot id）
* `tests/agent_evals/fixtures/filter_borderline/` —— 10 个 fixture
  覆盖完整决策矩阵（surface / reject / abstain × agent_ok /
  agent_malformed / agent_error / not_invoked）

（原 plan 保留在下方作为设计说明。）
不替换确定性 filter —— 在其之上加可解释层 + 仅对边界岗位调用 agent。
- **16.1** **`RuleVerdict` 数据结构演进**（这是 schema 改动，不是单纯"加一层"）。
  现状：`src/matching/scorer.py` 的 `ScoreBreakdown.disqualify_reasons` 只是
  `list[str]`，`RuleVerdict` 不带 `evidence_excerpt` / `rule_id` 结构。本子阶段
  要：(a) 把 `RuleVerdict` 改成 `{rule_id, rule_name, verdict, reason,
  evidence_excerpt}` 结构化；(b) 每条规则在 `src/matching/rules.py` 实现里返回
  时主动抽取相关 JD 片段当 `evidence_excerpt`；(c) `ScoreBreakdown` 顶层加
  `job_snapshot_id`，整个打分结果可以钉到具体 JD 版本上。16.3 的 UI 直接消费这
  份结构化输出。
- **16.2** Edge-case agent —— 只对 [0.4, 0.6] 分段调用；用 Phase 8 harness +
  新工具 `score_breakdown`。
- **16.3** Web UI "Why was this filtered?" 按钮。
- **16.4** Eval suite —— 10 个人工标注的边界岗位；agent 决策与人工一致率 ≥ 70%。

### Phase 17: 夜跑闭环 + Review Queue（~2 周）
集成阶段。把 Phase 14（任务队列 + 调度器）+ Phase 13（job-index / freshness）+
Phase 12（缓存）+ Phase 9 / 15（agent）串成 "睡一觉，醒来看 review queue" 的
完整流程。
- **17.1** `nightly_run` orchestrator —— search（cache-first，stale 自动刷新）→
  filter（带 16 的可解释性）→ top-N → 入队 `materials.generate` 和
  `application.prepare`；worker 在 task 级 retry/timeout policy 下运行 agent。
  **永不自动提交。**
- **17.2** Review queue 模型 —— `review_queue(id, tenant_id, job_id,
  job_snapshot_id, materials_path, status, ...)`；状态机
  `pending → approved → submitted` 或 `pending → rejected`。
- **17.3** `/review` kanban UI。
- **17.4** 批量操作 —— 多选 approve、按 company / keyword 批量 reject。
- **17.5** 提交前硬 gate —— 重跑 `should_refresh(job, "before_submit")`；
  > 6h stale 则先刷新；岗位已 expired 完全阻止提交。
- **17.6** 早间 digest（08:00）。
- **17.7** `autoapply pause-nightly` kill switch。

### Phase 18: 多租户 & Auth 加固（~2.5 周）
激活 Phase 12-17 散布的商业化就绪工作。SaaS 业务层（计费、注册流、营销页）
**不在范围内** —— 本阶段只让现有系统能安全托管多个隔离用户。

**诚实的范围说明**：13.9 已经把 schema 层的 `tenant_id` 列补齐了，所以
"加列 + backfill" 的部分确实不是重写。但下面这几块**实质是新建**，不是
"激活已有工作"：18.2 auth middleware（`src/web/` 目前完全没有 auth 层）、
18.4 Redis namespace 重构（现在 key 是 `{version}:{namespace}:{key}`，没有
tenant 前缀，需要全局改 wrapper）、18.7 凭据存储（`src/providers/store.py`
目前是单文件全局 JSON，需要按租户切目录 + keyring entry 重命名）。
真正"激活"的只有 18.1 / 18.3 / 18.5 / 18.6。

- **18.1** `tenants` + `users` 表；把 13.9 留下的 `tenant_id='default'` 行接到
  真实租户上。
- **18.2** **从零做** FastAPI auth middleware —— session/token 解析、
  `current_tenant_id` 注入到 `ContextVar`；ORM session 通过 SQLAlchemy event 自动
  在 query 上拼 `tenant_id = :current_tenant`；Celery task headers 自动带租户上
  下文（14.3 已经预留接口）。
- **18.3** Postgres Row-Level Security policy —— DB 层兜底，防 ORM 漏过滤。
- **18.4** **重构** Redis key 命名 —— 所有 namespace 前面加 `tenant:{id}:` 前缀；
  `src/cache/base.py` 的 key 构造改为强制注入租户上下文（无上下文则抛错而不是
  fall back 到 default）。
- **18.5** 按租户的配额（LLM token、scrape 速率、存储）。超限返回 429。
- **18.6** Audit log 表 —— `audit_events`（提交、设置变更、凭据操作、手动调度
  触发）。append-only。
- **18.7** **重构** 凭据存储 —— `src/providers/store.py` 从单文件全局 JSON 切到
  `data/tenants/{id}/credentials/`，keyring entry 命名加租户前缀；migrate 现有
  `data/providers/credentials.json` 到 `default` 租户。

### 时间表

| Phase | 范围 | 工时 | 累计 |
|---|---|---|---|
| 11 | 可靠性 & 收尾 | 1 周 | 1 周（已完成） |
| 12 | 缓存基础设施（Redis） | 1.5 周 | 2.5 周（已完成） |
| 13 | Job Index & Freshness Engine | 2 周 | 4.5 周（13.1-13.8 已完成） |
| 13.9 | tenant_id retrofit migration | 0.3 周 | 4.8 周 |
| 14 | 任务队列 + 定时工作（Celery） | 2.5 周 | 7.3 周 |
| 15 | Resume & Cover Letter Generation v2 | 3 周 | 10.3 周 |
| 16 | Filter Agent + 可解释性 | 1.5 周 | 11.8 周 |
| 17 | 夜跑闭环 + Review Queue | 2 周 | 13.8 周 |
| 18 | 多租户 & Auth 加固 | 2.5 周 | 16.3 周 |

约 3.5-4 个月推到 v1.0 商业化就绪核心（不含 SaaS 业务层）。Phase 14 比 v3 多
0.5 周用于 HITL gate 后端迁移；Phase 18 多 0.5 周承认 auth middleware / Redis
namespace / 凭据存储是新建而非"激活"。

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
| 13.9 | alembic upgrade → 所有遗留表带 `tenant_id='default'` 列；现有 query 路径不变（无回归） |
| 14 | `autoapply worker -Q materials` 起 Celery worker；入队 100 个混合 task → 按 queue 路由分发；杀 worker → `task_acks_late + task_reject_on_worker_lost` 自动重入队一次；Celery Beat 触发 `daily_search` 只 enqueue 不阻塞；agent 返回 `needs_human` 时 task 转 `waiting_human` 状态，worker 立即释放去拿下一个 task |
| 15 | DOCX patch 保留 named styles；三套 LaTeX 模板可从同一 IR 编译；cover-letter eval 5/5 通过；产物绑定 snapshot/source/template/trace ID |
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
- **当前任务执行仍偏同步。** Phase 14 落地前，耗时搜索、生成、申请任务仍可能
  阻塞 CLI/Web 流程，失败后的人工重试成本较高。
- **任意 LaTeX 不是零配置。** Phase 15 会接收任意模板，但必须先有
  manifest/adapter 且 sample compile 通过；全自动导入仍可能需要用户修正。
- **当下仍是单实例假设。** Phase 14 + D018/D023 铺了多实例工作；Phase 18 才真正
  做实。在此之前，**不要**对同一 Postgres / Redis 起两个 `autoapply web` 进程
  —— 数据层允许但没有 advisory lock，会引发重复提交。
- **Auto-submit 安全性。** `apply` 里有 `--auto-submit`，但仍走 HITL gate。
  我们还没看到能让我们按 vendor 摘掉 gate 的 eval 数据。
- **没有 SaaS 业务层。** Phase 18 是多租户托管基础设施，不是计费 / 注册 /
  营销。除非有商业 license 客户签约，否则这部分都在范围外。
