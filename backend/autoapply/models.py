"""Database tables (see docs/REFACTOR_PLAN.md section 9)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# --- application status machine -------------------------------------------------
# job-level "decision" statuses mirror the columns of the old jobs.tsv so the
# table view keeps working; application.status tracks the pipeline.
JOB_STATUSES = ["new", "scored", "queued", "skipped", "offline"]
APP_STATUSES = [
    "recon",  # reconnaissance running
    "draft_ready",  # waiting for review
    "needs_input",  # unresolved questions
    "revising",  # agent applying user comments
    "approved",  # waiting for executor
    "executing",
    "drifted",  # live form differs from draft; delta needs review
    "needs_human",  # login / captcha / takeover
    "ready_to_submit",  # manual policy: filled to review page, user submits
    "submitted",  # evidence captured
    "confirmed",  # confirmation e-mail matched
    "assessment",
    "interview",
    "offer",
    "rejected",
    "failed",
    "withdrawn",
]


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("source", "source_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String)  # pdportal | greenhouse | lever | ashby | workday | manual
    source_id: Mapped[str] = mapped_column(String)
    company: Mapped[str] = mapped_column(String, default="")
    title: Mapped[str] = mapped_column(String, default="")
    direction: Mapped[str] = mapped_column(String, default="")
    term: Mapped[str] = mapped_column(String, default="")
    months: Mapped[str] = mapped_column(String, default="")
    salary: Mapped[str] = mapped_column(String, default="")
    work_type: Mapped[str] = mapped_column(String, default="")
    location: Mapped[str] = mapped_column(String, default="")
    deadline: Mapped[str] = mapped_column(String, default="")  # "YYYY-MM-DD HH:MM" local, as posted
    channel: Mapped[str] = mapped_column(String, default="")  # PD Portal | employer site
    apply_url: Mapped[str] = mapped_column(String, default="")
    ats: Mapped[str] = mapped_column(String, default="")
    tenant: Mapped[str] = mapped_column(String, default="")
    docs_required: Mapped[str] = mapped_column(String, default="")
    jd_text: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    brief: Mapped[str] = mapped_column(Text, default="")  # detailed Markdown overview written when the job is scored
    duplicate_of: Mapped[int | None] = mapped_column(Integer, nullable=True)  # id of the job this is another listing of (see discover.link_duplicates)
    posted: Mapped[str] = mapped_column(String, default="")  # YYYY-MM-DD when the source says
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # set when the posting's story is over (see discover.archive_old)
    status: Mapped[str] = mapped_column(String, default="new")
    online: Mapped[int] = mapped_column(Integer, default=1)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_reason: Mapped[str] = mapped_column(Text, default="")
    exclusion: Mapped[str] = mapped_column(String, default="")  # hard-exclusion rule hit, if any
    note: Mapped[str] = mapped_column(Text, default="")
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=now)

    application: Mapped["Application | None"] = relationship(back_populates="job", uselist=False)


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True)
    status: Mapped[str] = mapped_column(String, default="recon")
    channel: Mapped[str] = mapped_column(String, default="")
    auto_approved: Mapped[int] = mapped_column(Integer, default=0)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # {text, url, screenshot, mail_id}
    last_event: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[str] = mapped_column(Text, default="")  # human-readable history line
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    job: Mapped[Job] = relationship(back_populates="application")
    drafts: Mapped[list["Draft"]] = relationship(back_populates="application", order_by="Draft.version")


class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # FormSchema
    answers: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    unresolved: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    materials: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    plan: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # execution steps
    notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    review_status: Mapped[str] = mapped_column(String, default="pending")  # pending|approved|rejected|superseded
    auto_approve_check: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    application: Mapped[Application] = relationship(back_populates="drafts")
    comments: Mapped[list["DraftComment"]] = relationship(back_populates="draft")


class DraftComment(Base):
    __tablename__ = "draft_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id"))
    comment: Mapped[str] = mapped_column(Text)
    result: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    draft: Mapped[Draft] = relationship(back_populates="comments")


class Account(Base):
    __tablename__ = "accounts"

    tenant_key: Mapped[str] = mapped_column(String, primary_key=True)  # e.g. workday:altera.wd1
    ats: Mapped[str] = mapped_column(String, default="")
    host: Mapped[str] = mapped_column(String, default="")
    login_email: Mapped[str] = mapped_column(String, default="")
    has_password: Mapped[int] = mapped_column(Integer, default=0)  # the password itself is in the OS keyring
    status: Mapped[str] = mapped_column(String, default="unknown")  # ok|pending|locked|needs_human|unknown
    created_by: Mapped[str] = mapped_column(String, default="")  # agent|takeover|manual|chrome_csv
    last_login_ok: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AnswerCache(Base):
    __tablename__ = "answer_cache"
    __table_args__ = (UniqueConstraint("ats", "question_key", "options_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ats: Mapped[str] = mapped_column(String)
    question_key: Mapped[str] = mapped_column(String)  # normalised question text
    options_hash: Mapped[str] = mapped_column(String, default="")
    answer: Mapped[Any] = mapped_column(JSON)
    basis: Mapped[str] = mapped_column(Text, default="")
    sensitive: Mapped[int] = mapped_column(Integer, default=0)
    confirmed_by_user: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class MailEvent(Base):
    __tablename__ = "mail_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[str] = mapped_column(String, unique=True)
    sender: Mapped[str] = mapped_column(String, default="")
    subject: Mapped[str] = mapped_column(String, default="")
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    category: Mapped[str] = mapped_column(String, default="")  # confirmation|rejection|interview|assessment|info_request|other
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id"), nullable=True)
    company_guess: Mapped[str] = mapped_column(String, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String)  # discover|score|recon|revise|execute|mail|canary|profile_init
    status: Mapped[str] = mapped_column(String, default="queued")  # queued|running|done|failed|waiting_human|cancelled
    ref: Mapped[str] = mapped_column(String, default="")  # e.g. "job:12", "draft:4"
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[int] = mapped_column(Integer, default=100)  # lower runs first
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    stages: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)  # [{stage, at}] the task went through (None on tasks from before this was kept)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String)  # recon|execute|agent
    ref: Mapped[str] = mapped_column(String, default="")
    ats: Mapped[str] = mapped_column(String, default="")
    ok: Mapped[int] = mapped_column(Integer, default=0)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    spans: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)      # where the time went (timing.py)
    site: Mapped[str | None] = mapped_column(String, nullable=True)                       # the site the form is on (a plan and notes are per site)
    learned: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)                # what the program had learned that was in force (learned.py)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    human_interventions: Mapped[int] = mapped_column(Integer, default=0)
    dir: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class LLMRequest(Base):
    """One request to an AI service: who asked, what it used, what it cost (see metering.py)."""

    __tablename__ = "llm_requests"
    __table_args__ = (Index("ix_llm_requests_started", "started_at"), Index("ix_llm_requests_task", "task_id"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String)                      # ours, unique per row
    call_id: Mapped[str] = mapped_column(String, default="")             # one llm.text / json / agent: its requests and retries share it
    attempt: Mapped[int] = mapped_column(Integer, default=0)             # 0 = the service in use; 1.. = a backup tried after it failed
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider: Mapped[str] = mapped_column(String, default="")
    model: Mapped[str] = mapped_column(String, default="")
    billing: Mapped[str] = mapped_column(String, default="unknown")      # subscription | metered | local | unknown
    kind: Mapped[str] = mapped_column(String, default="")                # text | json | agent
    feature: Mapped[str] = mapped_column(String, default="")             # which part of the program asked (metering.FEATURES)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)   # the workflow execution
    workflow: Mapped[str] = mapped_column(String, default="")            # that task's kind
    ref: Mapped[str] = mapped_column(String, default="")
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    application_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, default="ok")            # ok | error | refused | timeout | rate_limited | unavailable | unknown
    error_type: Mapped[str] = mapped_column(String, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    turns: Mapped[int] = mapped_column(Integer, default=1)               # model turns inside this request (subscription command lines run several)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)        # prompt tokens neither read from nor written to a cache
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)       # reasoning included
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)    # part of output_tokens
    detail: Mapped[str] = mapped_column(String, default="full")          # full | no_cache_split | none (the service reported no usage)
    cost_micros: Mapped[int | None] = mapped_column(Integer, nullable=True)         # millionths of `currency`; None = cannot be told
    currency: Mapped[str] = mapped_column(String, default="USD")
    cost_source: Mapped[str] = mapped_column(String, default="")         # provider (the service reported it) | list_price | user_price | ""
    pricing_version: Mapped[str] = mapped_column(String, default="")
    provider_request_id: Mapped[str] = mapped_column(String, default="")
    raw: Mapped[Any] = mapped_column(JSON, nullable=True)                # the usage exactly as the service reported it
    source: Mapped[str] = mapped_column(String, default="live")          # live | legacy (a per-task total from before requests were recorded)


class ApplicationEvent(Base):
    """Every change of an application's status, with the time. The status alone only says where an application is now;
    this says where it has been (an interview before a rejection)."""

    __tablename__ = "application_events"
    __table_args__ = (Index("ix_application_events_app", "application_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"))
    at: Mapped[datetime] = mapped_column(DateTime, default=now)
    old: Mapped[str] = mapped_column(String, default="")
    new: Mapped[str] = mapped_column(String, default="")


class Contact(Base):
    """Someone the user knows at an employer (referrals, conversations, follow-ups). The user's own notes; never contacted by the program."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    company: Mapped[str] = mapped_column(String, default="")
    role: Mapped[str] = mapped_column(String, default="")
    relation: Mapped[str] = mapped_column(String, default="")
    how: Mapped[str] = mapped_column(String, default="")       # e-mail, LinkedIn link ...
    status: Mapped[str] = mapped_column(String, default="none")  # none|asked|referred|talked|declined
    follow_up: Mapped[str] = mapped_column(String, default="")  # YYYY-MM-DD
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Todo(Base):
    __tablename__ = "todos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String)  # login|captcha|takeover|answer|drift|failed|mail_unmatched|driver_patch
    ref: Mapped[str] = mapped_column(String, default="")
    title: Mapped[str] = mapped_column(String, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="open")  # open|done|dismissed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String)  # task_started|todo|status_update|task_result
    text: Mapped[str] = mapped_column(Text)
    ref: Mapped[str] = mapped_column(String, default="")
    sent: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ProfileVersion(Base):
    __tablename__ = "profile_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc: Mapped[str] = mapped_column(String, default="profile")  # profile|scoring
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String, default="user")  # user|agent|init
    note: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Document(Base):
    """Uploaded or generated files: résumés, transcripts, cover letters."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String)  # resume_site|resume_portal|transcript|cover_letter|cl_template|cl_example|source|other
    name: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)
    active: Mapped[int] = mapped_column(Integer, default=1)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class DriverStat(Base):
    __tablename__ = "driver_stats"

    ats: Mapped[str] = mapped_column(String, primary_key=True)
    recon_ok: Mapped[int] = mapped_column(Integer, default=0)
    recon_fail: Mapped[int] = mapped_column(Integer, default=0)
    exec_ok: Mapped[int] = mapped_column(Integer, default=0)
    exec_fail: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_submits: Mapped[int] = mapped_column(Integer, default=0)
