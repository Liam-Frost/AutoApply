# AutoApply 部署与使用教程

这份文档基于当前仓库的真实实现编写，覆盖本地部署、初始化、CLI 使用、Vue Web 界面和常见问题。

## 1. 当前可部署能力

当前项目已经支持：

- Greenhouse / Lever ATS 抓取
- LinkedIn 搜索与外部 ATS 链接发现
- 按岗位生成定制简历与 Cover Letter
- 从 `qa_bank` 加载问答模板
- Greenhouse / Lever 表单自动填写
- 申请记录追踪、统计分析、CSV 导出、Vue Web 界面

当前“直接投递”已实现的平台：

- Greenhouse
- Lever

## 2. 部署前准备

需要先安装：

- Python `3.12+`
- `uv`
- PostgreSQL `16+`
- PostgreSQL `pgvector` 扩展
- Playwright 使用的 Chromium
- 至少一种 PDF 转换方案：
  - Microsoft Word + `docx2pdf`
  - LibreOffice
- 至少一个本地 LLM CLI：Claude Code CLI 或 Codex CLI
- 如果你希望启用自动 fallback，建议两个都安装
- 只有在你需要本地重建前端资源时，才需要 Node.js 和 npm

## 3. 克隆与安装

```bash
git clone https://github.com/Liam-Frost/AutoApply.git
cd AutoApply
uv sync
uv run playwright install chromium
```

## 3.2 前端构建

仓库已经提交了 `src/web/static/spa` 下的构建产物。
只有在你修改 `frontend/` 里的源码时，才需要重新构建：

```bash
cd frontend
npm install
npm run build
cd ..
```

## 3.1 安装并认证 LLM CLI

AutoApply 当前不直接走 SDK，而是调用本地 CLI。
所以运行 AutoApply 的机器上，至少要安装一个：

```bash
npm install -g @anthropic-ai/claude-code
npm install -g @openai/codex
```

安装之后，还需要分别完成各自 CLI 的本地登录/认证流程，然后再依赖 LLM 解析或生成能力。

推荐做法：

- 两个 CLI 都安装
- 选一个作为 primary provider
- 另一个作为 fallback provider

安装完成后，CLI 一般可直接使用：

```bash
autoapply --help
```

如果当前 shell 没有把虚拟环境脚本目录加入 PATH，建议直接用：

```bash
uv run autoapply --help
```

## 4. 数据库准备

先创建 PostgreSQL 用户和数据库。

示例 SQL：

```sql
CREATE USER autoapply WITH PASSWORD 'change-me';
CREATE DATABASE autoapply OWNER autoapply;
\c autoapply
CREATE EXTENSION IF NOT EXISTS vector;
```

## 5. 环境变量配置

复制示例配置：

```bash
cp config/.env.example .env
```

编辑 `.env`，至少填写数据库连接：

```env
AUTOAPPLY_DB_HOST=localhost
AUTOAPPLY_DB_PORT=5432
AUTOAPPLY_DB_NAME=autoapply
AUTOAPPLY_DB_USER=autoapply
AUTOAPPLY_DB_PASSWORD=change-me
AUTOAPPLY_LOG_LEVEL=INFO
```

说明：

- `config/settings.yaml` 提供默认值
- `.env` 会覆盖默认值
- 系统环境变量优先级最高
- LLM provider 的优先级配置保存在 `config/settings.yaml`

## 6. 执行数据库迁移

```bash
uv run alembic upgrade head
```

也可以直接交给 `autoapply init` 去验证数据库并执行迁移。

## 7. 首次初始化

### 方式 A：交互式初始化

```bash
uv run autoapply init
```

### 方式 A1：初始化时显式指定 LLM 优先级

```bash
uv run autoapply init --llm-primary claude-cli --llm-fallback codex-cli
```

或者：

```bash
uv run autoapply init --llm-primary codex-cli --llm-fallback claude-cli
```

### 方式 B：导入已有的结构化 profile

```bash
uv run autoapply init --profile data/profile/profile.yaml
```

### 方式 C：从现有简历生成 profile

```bash
uv run autoapply init --resume "/path/to/resume.pdf"
```

常用参数：

```bash
uv run autoapply init --skip-db
uv run autoapply init --skip-llm
```

`init` 当前会执行：

- 检查 `config/settings.yaml` 和 `.env`
- 测试数据库连接
- 执行 Alembic 迁移
- 导入或创建 `data/profile/profile.yaml`
- 检查 LLM CLI 是否可用
- 当你传入 `--llm-primary` / `--llm-fallback` 时，把主备 LLM 设置写入配置文件

### 7.1 LLM provider 优先级

当前配置在 `config/settings.yaml` 中：

```yaml
llm:
  provider: claude-cli
  primary_provider: claude-cli
  fallback_provider: codex-cli
  allow_fallback: true
```

含义：

- `primary_provider`：优先调用的 CLI
- `fallback_provider`：主 CLI 失败后尝试的 CLI
- `allow_fallback`：是否允许自动切换到备用 CLI

## 7.2 LLM fallback 机制

这里有两层 fallback：

### CLI 层 fallback

- 如果 `primary_provider` 调用失败、超时或未安装
- 且 `allow_fallback` 已开启
- AutoApply 会自动尝试 `fallback_provider`

这个逻辑是双向的：

- Codex -> Claude Code CLI
- Claude Code CLI -> Codex

### 功能层 fallback

即使两个 CLI 都失败，系统里也有若干降级路径：

- JD 解析 -> 正则规则 fallback
- Cover Letter 生成 -> 模板 fallback
- 简历 bullet rewrite -> 保留原 bullet
- QA 生成 -> 模板答案或人工复核 fallback
- 高风险问题 -> 强制人工复核

## 8. 需要维护的核心文件

通常需要编辑这些文件：

- `data/profile/profile.yaml`
- `config/settings.yaml`
- `config/filters.yaml`
- `config/companies.yaml`

建议：

- 在 `profile.yaml` 中填写身份信息、教育、经历、项目、技能、`story_bank`、`qa_bank`
- 在 `companies.yaml` 中维护要抓取的 ATS 公司 slug
- 在 `filters.yaml` 中维护筛选条件

## 9. 搜索岗位

### 搜索 ATS 岗位

```bash
uv run autoapply search --profile default --score
```

### 只查某个 ATS 或某家公司

```bash
uv run autoapply search --ats greenhouse --company stripe --score
```

### 搜索 LinkedIn

```bash
uv run autoapply search \
  --source linkedin \
  --keyword "software engineer intern" \
  --location "United States" \
  --time-filter week \
  --max-pages 3
```

### 合并搜索

```bash
uv run autoapply search --source all --keyword "backend intern" --score
```

说明：

- 第一次使用 LinkedIn 时，通常需要人工登录一次
- LinkedIn 搜索结果会尽量提取外部 ATS 链接
- 打分功能依赖可用的 `data/profile/profile.yaml`

## 10. 投递岗位

### 按 ATS URL 投递单个岗位

```bash
uv run autoapply apply --url https://boards.greenhouse.io/company/jobs/123
```

### 仅生成材料，不打开浏览器

```bash
uv run autoapply apply --url https://jobs.lever.co/company/abc123/apply --dry-run
```

### 按数据库中的岗位 ID 投递

```bash
uv run autoapply apply --job-id <uuid>
```

### 批量投递高分岗位

```bash
uv run autoapply apply --batch --top-n 5 --profile default
```

### 自动提交而不是停在人工复核

```bash
uv run autoapply apply --url <ats-url> --auto-submit
```

当前 `apply` 流程已经会：

- 根据 URL 检测 ATS 类型
- 尽量从数据库或 ATS API 获取真实岗位信息
- 为当前岗位生成专属简历和 Cover Letter
- 从 `qa_bank` 生成问答映射
- 创建 Application tracking 记录
- 用 Playwright 填表
- 把截图和状态同步回 tracking

## 11. Web 控制台

启动 Web 面板：

```bash
uv run autoapply web --host 127.0.0.1 --port 8000
```

浏览器访问：

```text
http://127.0.0.1:8000
```

主要页面：

- `/` 仪表盘
- `/jobs` 搜索岗位并触发 apply
- `/applications` 查看申请记录并更新 outcome
- `/profile` 查看 profile 和上传简历
- `/settings` 修改 LLM 主备优先级和 fallback 配置

部署后如果要改 LLM 优先级，除了手动编辑 YAML，也可以直接打开 `/settings`。

## 12. Tracking 与导出

查看命令行统计：

```bash
uv run autoapply status
```

导出 CSV：

```bash
uv run autoapply status --export-csv report.csv
```

筛选近期申请：

```bash
uv run autoapply status --company Stripe --status SUBMITTED --outcome interview
```

## 13. 推荐部署方式

### 个人开发机 / 本地工作站

- 使用 `uv run autoapply web --reload`
- PostgreSQL 本地部署
- Playwright 与 LibreOffice 安装在同一台机器上

### 单台 Linux 服务器 / 虚拟机

- 安装 Python、PostgreSQL、LibreOffice、Chromium
- 在同一台服务器上安装并认证 Claude Code CLI 和/或 Codex CLI
- PostgreSQL 可本地部署，也可用托管数据库
- Web 界面建议放在反向代理后面
- CLI 可人工执行，也可配合调度器

服务器启动示例：

```bash
uv run autoapply web --host 0.0.0.0 --port 8000 --no-open
```

## 14. Linux 生产环境部署

这一节给出一个适合当前项目实际结构的生产部署方式，重点是当前的 Vue Web 界面：

- Linux 服务器
- `systemd` 常驻托管
- Nginx 反向代理
- Web 服务只监听内网地址

建议约定：

- 运行用户：`autoapply`
- 项目目录：`/opt/autoapply`
- Web 监听：`127.0.0.1:8000`
- 外部访问：Nginx 提供 `80/443`

### 14.1 安装系统依赖

Ubuntu / Debian 示例：

```bash
sudo apt update
sudo apt install -y python3 python3-venv postgresql libpq-dev libreoffice nginx curl
```

如果还没安装 `uv`：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 14.2 创建专用运行用户

```bash
sudo useradd --system --create-home --home-dir /opt/autoapply --shell /bin/bash autoapply
```

### 14.3 部署代码

```bash
sudo -u autoapply git clone https://github.com/Liam-Frost/AutoApply.git /opt/autoapply
cd /opt/autoapply
sudo -u autoapply /opt/autoapply/.local/bin/uv sync
sudo -u autoapply /opt/autoapply/.local/bin/uv run playwright install chromium
```

如果你在服务器上改动了 `frontend/` 源码，启动前先重建前端：

```bash
cd /opt/autoapply/frontend
sudo -u autoapply npm install
sudo -u autoapply npm run build
```

如果你机器上的 `uv` 不在 `/opt/autoapply/.local/bin/uv`，请替换成实际路径。

### 14.4 配置环境变量与数据库

```bash
cd /opt/autoapply
sudo -u autoapply cp config/.env.example .env
sudo -u autoapply editor .env
sudo -u autoapply /opt/autoapply/.local/bin/uv run alembic upgrade head
```

至少需要正确填写 `.env` 中的数据库配置。

### 14.5 先手工跑通一次 Web

```bash
sudo -u autoapply /opt/autoapply/.local/bin/uv run autoapply web --host 127.0.0.1 --port 8000 --no-open
```

先确认服务器本机上 `http://127.0.0.1:8000` 能访问，再继续配置 `systemd` 和 Nginx。

## 15. systemd 服务配置

创建 `/etc/systemd/system/autoapply-web.service`：

```ini
[Unit]
Description=AutoApply Web Dashboard
After=network.target

[Service]
Type=simple
User=autoapply
Group=autoapply
WorkingDirectory=/opt/autoapply
Environment=HOME=/opt/autoapply
ExecStart=/opt/autoapply/.local/bin/uv run autoapply web --host 127.0.0.1 --port 8000 --no-open
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

如果 `uv` 在别的位置，请修改 `ExecStart`。

启用并启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable autoapply-web
sudo systemctl start autoapply-web
sudo systemctl status autoapply-web
```

查看日志：

```bash
sudo journalctl -u autoapply-web -f
```

## 16. Nginx 反向代理

创建 `/etc/nginx/sites-available/autoapply`：

```nginx
server {
    listen 80;
    server_name autoapply.example.com;

    client_max_body_size 20m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

启用站点：

```bash
sudo ln -s /etc/nginx/sites-available/autoapply /etc/nginx/sites-enabled/autoapply
sudo nginx -t
sudo systemctl reload nginx
```

### 16.1 启用 HTTPS

如果是公网访问，建议加上 TLS：

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d autoapply.example.com
```

## 17. 生产环境注意事项

- Web 服务建议只绑定 `127.0.0.1`，对外访问交给 Nginx
- 数据库密码只放在 `.env` 或系统环境变量里
- 服务进程使用独立的非 root 用户运行
- `logs/`、`data/output/`、`data/.linkedin_session/` 需要对运行用户可写
- 被配置为 primary / fallback 的 LLM CLI 也必须对同一个运行用户可用且已认证
- 如果服务器上要跑 LinkedIn 搜索，第一次登录通常仍需要人工完成
- 基于 Playwright 的自动投递更适合受控内部环境，不建议直接做成开放式公网多租户服务

## 18. 运行注意事项

- 当前直接投递主要支持 Greenhouse 和 Lever
- LinkedIn 主要用于搜索和发现外部 ATS 链接
- PDF 转换依赖 Word/docx2pdf 或 LibreOffice
- LLM CLI 不可用时，系统会尽量降级，但解析和生成质量会下降
- 默认流程是人工复核后再提交，`--auto-submit` 是可选行为

## 19. 常见问题

### `autoapply` 命令找不到

先尝试：

```bash
uv run autoapply --help
```

必要时重新执行：

```bash
uv sync
```

### 数据库连接失败

检查：

- PostgreSQL 是否已经启动
- `.env` 中数据库配置是否正确
- 数据库和用户是否已创建
- `pgvector` 是否可创建

### Web 启动失败

执行：

```bash
uv sync
uv run autoapply web
```

### 浏览器自动化失败

先安装 Playwright 浏览器：

```bash
uv run playwright install chromium
```

然后尝试非 headless：

```bash
uv run autoapply apply --url <ats-url> --no-headless
```

### 没有生成 PDF

需要安装下面任一方案：

- Microsoft Word + `docx2pdf`
- LibreOffice

### LinkedIn 登录问题

- 第一次建议使用 `--no-headless`
- 手动完成登录后，会复用 `data/.linkedin_session`

## 20. 部署完成后的检查清单

```bash
uv run ruff check .
uv run pytest -q
uv run autoapply --help
uv run autoapply status
uv run autoapply web --no-open
```

当前预期基线：

- 测试通过
- CLI 正常加载
- Web 面板可启动
- 初始化后 tracking 可正常工作
