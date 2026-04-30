# AutoApply - 自动化求职 Agent 实施计划

## 背景

目标是构建一个完整的求职自动化系统（不是简单的投递脚本），涵盖 7 层能力：岗位获取筛选、候选人记忆、简历/CL 定制、问答自动回答、文件处理、浏览器自动化、申请追踪分析。

核心决策（基于调研报告 + 架构设计）：
- **自建框架**，不 fork 任何现有项目作为主干
- **Playwright + Python + PostgreSQL**，向量检索用 pgvector
- 借鉴：AIHawk（架构思路）、get_jobs（国内站点动作经验）、GodsScion（配置/QA/材料定制经验）
- 分阶段：先做"高命中半自动" → 限定条件自动提交 → 统计驱动优化

## 技术栈

| 层 | 技术 |
|---|---|
| 浏览器自动化 | Playwright (Python) |
| 后端 / Agent | Python 3.12+, asyncio |
| LLM | Claude Code CLI (`claude -p`) + Codex CLI — 通过 subprocess 调用，不走 API SDK |
| 数据库 | PostgreSQL + pgvector |
| 文档处理 | python-docx + docx 模板系统, docx2pdf / LibreOffice CLI |
| 任务队列 | asyncio 调度（MVP），后期可升级 Celery + Redis |
| 前端面板 | CLI + FastAPI 托管的 Vue 3 SPA |
| 包管理 | uv |
| 配置 | YAML |
| 目标平台 | 英文 ATS：Greenhouse / Lever / Ashby，LinkedIn 搜索发现（中文平台后期扩展） |

### LLM 调用方式

系统通过 `subprocess` 调用 Claude Code CLI 和 Codex CLI，而非直接调用 API：

```python
# src/utils/llm.py 核心接口
import subprocess, json

def claude_generate(prompt: str, system: str = "", max_tokens: int = 4096) -> str:
    """调用 Claude Code CLI 进行文本生成"""
    cmd = ["claude", "-p", prompt]
    if system:
        cmd.extend(["--system", system])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return result.stdout.strip()

def codex_generate(prompt: str) -> str:
    """调用 Codex CLI 进行文本生成"""
    cmd = ["codex", "--quiet", "--full-auto", prompt]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return result.stdout.strip()
```

优势：不需要管理 API key（CLI 自带认证），可以利用 CLI 的上下文能力。

## 项目结构

```
AutoApply/
├── src/
│   ├── core/                    # 核心 Agent 调度、状态机
│   │   ├── agent.py             # 主 Agent 编排
│   │   ├── state_machine.py     # 申请状态机
│   │   └── config.py            # 全局配置加载
│   ├── intake/                  # Layer 1: 岗位获取
│   │   ├── base.py              # 抓取器基类
│   │   ├── greenhouse.py        # Greenhouse ATS
│   │   ├── lever.py             # Lever ATS
│   │   ├── linkedin.py          # LinkedIn 搜索与 ATS 跳转发现
│   │   └── schema.py            # 统一岗位 schema
│   ├── matching/                # Layer 2: 匹配与筛选
│   │   ├── rules.py             # 硬规则过滤
│   │   ├── semantic.py          # 语义匹配（embedding）
│   │   └── scorer.py            # 综合评分
│   ├── memory/                  # Layer 3: 候选人记忆
│   │   ├── profile.py           # 身份/教育/技能
│   │   ├── story_bank.py        # 可复用故事库
│   │   ├── qa_bank.py           # 问答库
│   │   └── bullet_pool.py       # 简历 bullet 池
│   ├── generation/              # Layer 4: 简历/CL 生成
│   │   ├── ir.py                # 简历/Cover Letter 结构化 IR
│   │   ├── resume_builder.py    # 基于证据的简历组装
│   │   ├── cover_letter.py      # 受约束的 CL 生成
│   │   ├── fitting.py           # 基于模板容量的裁剪
│   │   ├── validator.py         # 生成材料校验
│   │   └── qa_responder.py      # Quick question 回答
│   ├── execution/               # Layer 5: 表单填写与提交
│   │   ├── browser.py           # Playwright 浏览器管理
│   │   ├── form_filler.py       # 表单字段识别与填写
│   │   ├── file_uploader.py     # 文件上传
│   │   └── ats/                 # 各 ATS 适配器
│   │       ├── base.py
│   │       ├── ashby.py
│   │       ├── greenhouse.py
│   │       └── lever.py
│   ├── documents/               # Layer 6: 文件处理
│   │   ├── docx_engine.py       # 从结构化 IR 渲染 DOCX
│   │   ├── pdf_converter.py     # Word → PDF
│   │   ├── page_count.py        # DOCX/PDF 页数统计
│   │   └── templates.py         # 模板 package 管理
│   ├── tracker/                 # Layer 7: 追踪与分析
│   │   ├── database.py          # 数据库操作
│   │   ├── analytics.py         # 统计分析
│   │   └── export.py            # 导出报告
│   └── utils/
│       ├── llm.py               # LLM 调用封装
│       ├── rate_limiter.py      # 限流与反检测
│       └── logger.py            # 日志与截图
├── data/
│   ├── profile/                 # 申请人资料 YAML
│   ├── templates/               # DOCX 模板 package
│   └── output/                  # 生成的简历/CL
├── frontend/                     # Vue SPA 源码和 Vite 构建配置
├── config/
│   ├── settings.yaml            # 全局设置
│   ├── filters.yaml             # 筛选规则
│   └── .env.example             # 环境变量模板
├── migrations/                  # 数据库迁移
├── tests/
├── pyproject.toml
└── README.md
```

## 数据模型（PostgreSQL + pgvector）

### 核心表

```sql
-- 统一岗位 schema
CREATE TABLE jobs (
    id UUID PRIMARY KEY,
    source TEXT,               -- greenhouse/lever/workday/company_site
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
    employment_type TEXT,      -- intern/fulltime/coop
    seniority TEXT,
    description TEXT,
    description_embedding vector(1536),
    requirements JSONB,        -- {must_have_skills, preferred_skills, education, experience_years}
    visa_sponsorship BOOLEAN,
    ats_type TEXT,
    application_url TEXT,
    raw_data JSONB,
    discovered_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);

-- 申请记录（状态机）
CREATE TABLE applications (
    id UUID PRIMARY KEY,
    job_id UUID REFERENCES jobs(id),
    status TEXT NOT NULL DEFAULT 'DISCOVERED',
    -- DISCOVERED -> QUALIFIED -> MATERIALS_READY -> FORM_OPENED
    -- -> FIELDS_MAPPED -> FILES_UPLOADED -> QUESTIONS_ANSWERED
    -- -> REVIEW_REQUIRED -> SUBMITTED -> FAILED -> NEEDS_RETRY
    match_score FLOAT,
    resume_version TEXT,       -- 文件路径
    cover_letter_version TEXT,
    qa_responses JSONB,
    screenshot_paths JSONB,
    error_log TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    submitted_at TIMESTAMPTZ,
    outcome TEXT               -- pending/rejected/oa/interview/offer
);

-- 申请人资料（结构化）
CREATE TABLE applicant_profile (
    id UUID PRIMARY KEY,
    section TEXT NOT NULL,     -- identity/education/skills/experience/projects
    content JSONB NOT NULL,
    content_embedding vector(1536),
    tags TEXT[],
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Bullet 池
CREATE TABLE bullet_pool (
    id UUID PRIMARY KEY,
    category TEXT,             -- experience/project/achievement
    source_entity TEXT,        -- 来源公司/项目
    text TEXT NOT NULL,
    text_embedding vector(1536),
    tags TEXT[],               -- backend/frontend/ml/leadership/etc
    used_count INT DEFAULT 0
);

-- QA 知识库
CREATE TABLE qa_bank (
    id UUID PRIMARY KEY,
    question_pattern TEXT,
    question_type TEXT,        -- authorization/sponsorship/experience_years/salary/why_company/why_role/custom
    canonical_answer TEXT,
    variants JSONB,            -- {by_geography, by_role_type}
    confidence TEXT DEFAULT 'high',
    needs_review BOOLEAN DEFAULT FALSE
);
```

## 系统分层架构

### Layer 1: 岗位获取层 (Job Intake)

负责抓取、聚合、标准化 JD。

- 输入来源：Greenhouse / Lever / Ashby / LinkedIn / 公司 careers page
- 输出统一 schema：company, title, location, employment_type, seniority, skills, visa, ATS type, application URL, quick questions, deadline

核心原则：先标准化，不是"看到岗位就投"。

### Layer 2: 匹配与筛选层 (Matching & Filtering)

三层评分机制：

1. **规则层（硬过滤）**：地区、岗位类型、签证、学历、经验年限
2. **语义层**：JD embedding vs profile embedding（课程/项目/技术栈/行业匹配）
3. **风险层**：staffing spam / fake job / repost / ghost job 过滤

精准筛选比批量投递更有价值 —— 别把 250 次机会浪费在错误的岗位上。

### Layer 3: 候选人记忆层 (Applicant Memory)

结构化资料库，不是把一份简历丢给 LLM：

- `identity_profile` — 基本身份信息
- `education_records` — 教育经历
- `course_records` — 课程与成绩
- `work_experiences` — 工作经历
- `projects` — 项目详情
- `skills` — 技能清单
- `story_bank` — 按主题存可复用故事（为什么选这个方向/公司、技术难题、冲突处理、ownership/impact）
- `qa_bank` — 常见 quick questions 结构化模板（每个答案有 canonical answer + 变体 + 置信度 + 是否需人工审核）

### Layer 4: 简历 / Cover Letter 生成层

**简历**：结构化 IR + Block-based assembly，不做全文 LLM 重写
- 每个 bullet 带标签，并能追溯到 profile 中的真实证据
- JD 来了 → 提取关键词 → 检索证据 → 选最匹配的 bullets → 可选轻量 lexical rewrite → 基于模板容量裁剪 → 校验

**Cover Letter**：受结构约束的 IR 生成
- opening: role + reason
- middle: 2-3 个最匹配的证据点
- company tie-in: 为什么这家公司
- close: availability / interest

**Quick Questions**：分类 → qa_bank 精确匹配 → 模板变体 → LLM 生成（按置信度递降），高风险问题标记人工审核。

### Layer 5: 表单填写与提交层 (Application Execution)

每次投递拆成状态机：

```
DISCOVERED → QUALIFIED → MATERIALS_READY → FORM_OPENED
→ FIELDS_MAPPED → FILES_UPLOADED → QUESTIONS_ANSWERED
→ REVIEW_REQUIRED → SUBMITTED → FAILED → NEEDS_RETRY
```

每一步：截图、保存 DOM/字段映射、记录错误、可从中间恢复。

### Layer 6: 文件处理层 (File Pipeline)

- 模板 package：`template.docx` + `manifest.json` + `style.lock.json` + 示例 JSON
- 使用 `{{resume.sections}}` 和 `{{cover_letter.body}}` 等 block marker
- Word 样式由模板 manifest 中的命名 style 管理
- DOCX-first 渲染，统一导出 PDF
- 生成材料校验和页数统计
- 文件版本号系统：`resume_{company}_{role}_{date}.pdf`
- 记录每次申请用了哪个版本

### Layer 7: 追踪与分析层 (Analytics / CRM)

从第一天就做，不要后补：
- 记录：source, company, role, date, platform, resume version, match score, status, outcome
- 分析：哪种岗位命中率高、哪个平台质量高、哪套关键词更有效、哪种简历版本转化更高

## 分阶段实施

### Phase 1: 基础设施 + 候选人记忆（第 1-2 周）

**目标**：项目骨架跑通，申请人资料完整入库

1. 项目初始化
   - pyproject.toml + uv 依赖管理
   - PostgreSQL + pgvector 环境配置
   - 数据库迁移工具（alembic）
   - 基本配置加载（YAML）
   - LLM CLI 封装层（claude -p / codex）
   - 日志系统

2. 候选人记忆层
   - 定义 profile YAML schema
   - **简历导入器**：解析现有 Word/PDF 简历 → 结构化 YAML → 入库（用 Claude CLI 辅助解析）
   - profile 加载与入库
   - bullet_pool 管理（带 tags）
   - story_bank 和 qa_bank
   - Embedding 生成与存储

3. 文档处理层
   - Word 模板系统（python-docx）
   - Block-based 简历组装引擎
   - Word → PDF 转换
   - 文件命名与版本管理

### Phase 2: 岗位获取 + 智能筛选（第 3-4 周）

**目标**：能自动抓取岗位并精准评分

4. 岗位获取层
   - 统一 Job schema
   - Greenhouse + Lever 抓取器
   - JD 解析与结构化（LLM 辅助）
   - 去重与新鲜度管理

5. 匹配筛选层
   - 硬规则过滤
   - 语义匹配
   - 综合评分
   - 低质量岗位过滤

### Phase 3: 简历/CL 定制 + QA 回答（第 5-6 周）

**目标**：针对每个岗位自动生成定制材料

6. 简历生成：JD 关键词提取 → bullet 选择 → rewrite → 事实检查 → docx + pdf
7. Cover Letter 生成：结构约束 + LLM 受控生成
8. Quick Question 回答：分类 → 匹配 → 生成 → 人工审核标记

### Phase 4: 浏览器自动化 + 表单填写（第 7-8 周）

**目标**：能自动填写表单、上传文件，停在提交前等人工确认

9. Playwright 浏览器管理 + 申请状态机 + ATS 适配器
10. 反检测：随机间隔、并发限制、频率控制、冷却机制

### Phase 5: 追踪分析 + 全流程串联（第 9-10 周）

**目标**：完整闭环，半自动投递可用

11. 申请追踪与统计分析
12. Agent 主循环编排 + CLI 交互界面

### Phase 6: LinkedIn 集成（已完成）

**目标**：发现 LinkedIn 岗位、补全详情，并解析外部 ATS 链接，接入已有投递流程。

13. 基于 Playwright persistent context 的 LinkedIn 登录会话管理
14. LinkedIn 搜索 URL 构建、翻页、岗位卡提取、缓存和去重
15. 详情页 enrichment 与 Apply 按钮跳转解析
16. `--source linkedin`、搜索 profile、Web 搜索集成

### Phase 7: Web GUI（已完成）

**目标**：提供面向人的操作控制台。

17. FastAPI JSON API + Vue 3 SPA，构建产物由 `src/web/static/spa` 托管
18. Dashboard、Jobs、Applications、Profile、Settings 页面
19. 搜索 profile、LLM provider 设置、LinkedIn 会话管理、搜索缓存控制

### Phase 8: Materials 工作台 + 模板 package（已完成）

**目标**：把申请材料生成做成可复核、可下载的主流程。

20. `/materials` 工作台，支持搜索结果岗位或手动粘贴 JD
21. 申请人 profile 选择、简历/Cover Letter 模板选择、DOCX/PDF 格式选择
22. Preview、校验状态、生成版本、artifact 下载
23. Template Library 上传和 package 校验
24. template ID、artifact path、上传大小、profile ID、LinkedIn cache/enrichment、parser heuristics 等安全和稳定性修复

## 关键设计原则

1. **状态机驱动**：每次申请都是状态机，可中断、可恢复、可审计
2. **Block-based 简历**：不做全文 LLM 重写，从 bullet pool 选择 + 轻量改写
3. **DOCX-first 渲染**：LLM/内容规划只生成结构化 IR，最终 DOCX/PDF 由 deterministic renderer 输出
4. **人工确认点**：默认在提交前暂停，只有满足条件才开放自动提交
5. **全程审计**：截图、DOM 快照、文件版本、QA 响应全部记录

## 风控策略

- 减少无差别批量提交，保留人工确认点
- 优先做 ATS / company site 的结构化表单流
- 做好失败回滚、日志、限流和任务调度
- 自动化重点放在"整理资料、改材料、填表、追踪"，而不是单纯追求提交数

## 验证方式

- Phase 1: 加载 profile YAML → 入库 → 生成一份定制 Word 简历 + PDF
- Phase 2: 从 Greenhouse 抓取岗位 → 评分排序 → 输出 top-N 推荐列表
- Phase 3: 给定 JD → 自动选 bullets → 生成定制简历 + CL + 回答 quick questions
- Phase 4: 对 Greenhouse 岗位 → 自动填表 → 上传文件 → 截图（不提交）
- Phase 5: 跑完整流程 10 个岗位 → 查看追踪面板 → 分析报告
- Phase 6: LinkedIn 搜索 → 外部 ATS 链接解析 → 接入现有 apply/material 流程
- Phase 7: `autoapply web` → Vue SPA 搜索/追踪/settings 流程
- Phase 8: `/jobs` → `/materials?jobId=...` → DOCX/PDF 生成、preview、校验、下载

当前基线：`uv run python -m pytest` 通过，340 个测试通过、1 个 LinkedIn smoke 测试跳过；`uv run ruff check .` 和 `npm run build` 通过。
