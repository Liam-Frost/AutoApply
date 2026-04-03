"""``autoapply init`` -- first-time setup wizard.

Steps:
1. Validate configuration (settings.yaml, .env)
2. Test database connection & run migrations
3. Import or create applicant profile
4. Verify LLM CLI availability
5. Summary of readiness
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

import click

from src.core.config import PROJECT_ROOT, load_config, get_db_url

logger = logging.getLogger("autoapply.cli.init")

PROFILE_DIR = PROJECT_ROOT / "data" / "profile"
SCHEMA_FILE = PROFILE_DIR / "schema.yaml"
PROFILE_FILE = PROFILE_DIR / "profile.yaml"


@click.command("init")
@click.option(
    "--profile",
    type=click.Path(exists=True, path_type=Path),
    help="Path to an existing profile YAML to import.",
)
@click.option(
    "--resume",
    type=click.Path(exists=True, path_type=Path),
    help="Path to a resume (.docx/.pdf) to parse into a profile.",
)
@click.option("--skip-db", is_flag=True, help="Skip database setup.")
@click.option("--skip-llm", is_flag=True, help="Skip LLM availability check.")
def init_cmd(
    profile: Path | None,
    resume: Path | None,
    skip_db: bool,
    skip_llm: bool,
) -> None:
    """Initialize AutoApply: database, profile, and configuration."""
    click.echo()
    click.secho("  AutoApply -- First-Time Setup", fg="cyan", bold=True)
    click.secho("  " + "=" * 35, fg="cyan")
    click.echo()

    checks_passed = 0
    checks_total = 0

    # Step 1: Configuration
    checks_total += 1
    click.secho("  [1/4] Checking configuration...", fg="yellow")
    config_ok, config = _check_config()
    if config_ok:
        click.secho("    [OK] settings.yaml loaded", fg="green")
        checks_passed += 1
    else:
        click.secho("    [FAIL] Configuration error (see above)", fg="red")
        if not click.confirm("    Continue anyway?", default=False):
            raise SystemExit(1)

    # Step 2: Database
    checks_total += 1
    if skip_db:
        click.secho("  [2/4] Database -- skipped", fg="yellow")
        checks_passed += 1
    else:
        click.secho("  [2/4] Setting up database...", fg="yellow")
        db_ok = _setup_database(config)
        if db_ok:
            checks_passed += 1
        else:
            if not click.confirm("    Continue without database?", default=False):
                raise SystemExit(1)

    # Step 3: Applicant Profile
    checks_total += 1
    click.secho("  [3/4] Setting up applicant profile...", fg="yellow")
    profile_ok = _setup_profile(
        profile_path=profile, resume_path=resume, config=config, skip_db=skip_db
    )
    if profile_ok:
        checks_passed += 1

    # Step 4: LLM CLI
    checks_total += 1
    if skip_llm:
        click.secho("  [4/4] LLM check -- skipped", fg="yellow")
        checks_passed += 1
    else:
        click.secho("  [4/4] Checking LLM CLI availability...", fg="yellow")
        llm_ok = _check_llm()
        if llm_ok:
            checks_passed += 1

    # Summary
    click.echo()
    if checks_passed == checks_total:
        click.secho(
            f"  [OK] All {checks_total} checks passed -- AutoApply is ready!",
            fg="green",
            bold=True,
        )
    else:
        click.secho(
            f"  {checks_passed}/{checks_total} checks passed -- some issues need attention.",
            fg="yellow",
            bold=True,
        )
    click.echo()
    click.echo("  Next steps:")
    click.echo("    autoapply search    -- Find matching jobs")
    click.echo("    autoapply apply     -- Run application pipeline")
    click.echo("    autoapply status    -- View tracking dashboard")
    click.echo()


def _check_config() -> tuple[bool, dict | None]:
    """Validate that settings.yaml loads correctly."""
    try:
        config = load_config()

        # Check required sections
        required = ["database", "logging"]
        missing = [s for s in required if s not in config]
        if missing:
            click.secho(f"    ! Missing config sections: {missing}", fg="yellow")

        # Check .env
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            click.secho("    [OK] .env file found", fg="green")
        else:
            click.secho("    ! No .env file -- using defaults from settings.yaml", fg="yellow")
            example = PROJECT_ROOT / "config" / ".env.example"
            if example.exists():
                click.echo(f"      Hint: cp {example} {env_path}")

        return True, config

    except Exception as e:
        click.secho(f"    [FAIL] Failed to load config: {e}", fg="red")
        return False, None


def _setup_database(config: dict | None) -> bool:
    """Test DB connection and run migrations."""
    if not config:
        click.secho("    [FAIL] No config available for database setup", fg="red")
        return False

    # Test connection
    try:
        from sqlalchemy import create_engine, text

        url = get_db_url(config)
        engine = create_engine(url)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            result.fetchone()
        click.secho("    [OK] Database connection successful", fg="green")
    except Exception as e:
        click.secho(f"    [FAIL] Database connection failed: {e}", fg="red")
        click.echo("      Check your database settings in config/settings.yaml or .env")
        return False

    # Run migrations
    try:
        click.echo("    Running migrations...")
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            click.secho("    [OK] Migrations complete", fg="green")
        else:
            stderr = result.stderr.strip()
            if "already exists" in stderr.lower() or "nothing to do" in stderr.lower():
                click.secho("    [OK] Database already up to date", fg="green")
            else:
                click.secho(f"    ! Migration warning: {stderr[:200]}", fg="yellow")
    except subprocess.TimeoutExpired:
        click.secho("    [FAIL] Migration timed out", fg="red")
        return False
    except FileNotFoundError:
        click.secho("    ! Alembic not found -- run: uv add alembic", fg="yellow")

    # Enable pgvector
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        click.secho("    [OK] pgvector extension enabled", fg="green")
    except Exception as e:
        click.secho(f"    ! pgvector setup: {e}", fg="yellow")

    return True


def _setup_profile(
    profile_path: Path | None,
    resume_path: Path | None,
    config: dict | None,
    skip_db: bool,
) -> bool:
    """Set up the applicant profile: import, parse from resume, or create template."""

    # Option 1: Import existing profile YAML
    if profile_path:
        return _import_profile_yaml(profile_path, config, skip_db)

    # Option 2: Parse from resume
    if resume_path:
        return _import_from_resume(resume_path, config, skip_db)

    # Option 3: Check if profile already exists
    if PROFILE_FILE.exists():
        click.secho(f"    [OK] Profile found: {PROFILE_FILE}", fg="green")
        # Validate it loads
        try:
            from src.memory.profile import load_profile_yaml

            data = load_profile_yaml(PROFILE_FILE)
            sections = [s for s in data if s not in ("story_bank", "qa_bank")]
            click.echo(f"      Sections: {', '.join(sections)}")
            return True
        except Exception as e:
            click.secho(f"    ! Profile loads but has issues: {e}", fg="yellow")
            return True

    # Option 4: Interactive -- ask user what to do
    click.echo("    No profile found. Choose how to set up:")
    click.echo("      [1] Import from resume (.docx/.pdf)")
    click.echo("      [2] Copy template to fill manually")
    click.echo("      [3] Skip for now")

    choice = click.prompt("    Choice", type=click.IntRange(1, 3), default=3)

    if choice == 1:
        path_str = click.prompt("    Resume file path", type=str)
        return _import_from_resume(Path(path_str), config, skip_db)
    elif choice == 2:
        return _create_template_profile()
    else:
        click.secho(
            "    ! Profile setup skipped -- run `autoapply init --profile <path>` later",
            fg="yellow",
        )
        return False


def _import_profile_yaml(path: Path, config: dict | None, skip_db: bool) -> bool:
    """Import and optionally ingest a profile YAML."""
    try:
        from src.memory.profile import load_profile_yaml, ingest_profile

        data = load_profile_yaml(path)

        # Copy to standard location
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        if path.resolve() != PROFILE_FILE.resolve():
            shutil.copy2(path, PROFILE_FILE)
            click.secho(f"    [OK] Profile copied to {PROFILE_FILE}", fg="green")

        # Ingest to DB if available
        if not skip_db and config:
            try:
                from src.core.database import get_session_factory

                SessionFactory = get_session_factory(config)
                with SessionFactory() as session:
                    records = ingest_profile(session, data)
                    click.secho(
                        f"    [OK] Profile ingested to DB ({len(records)} sections)",
                        fg="green",
                    )
            except Exception as e:
                click.secho(f"    ! DB ingestion skipped: {e}", fg="yellow")

        identity = data.get("identity", {})
        name = identity.get("full_name", "Unknown")
        click.secho(f"    [OK] Profile loaded: {name}", fg="green")
        return True

    except Exception as e:
        click.secho(f"    [FAIL] Profile import failed: {e}", fg="red")
        return False


def _import_from_resume(path: Path, config: dict | None, skip_db: bool) -> bool:
    """Parse a resume file into a structured profile."""
    if not path.exists():
        click.secho(f"    [FAIL] File not found: {path}", fg="red")
        return False

    click.echo(f"    Parsing {path.name} with Claude CLI...")
    try:
        from src.memory.resume_importer import import_resume

        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        data = import_resume(path, output_path=PROFILE_FILE)
        click.secho(f"    [OK] Resume parsed -> {PROFILE_FILE}", fg="green")

        # Show what was extracted
        identity = data.get("identity", {})
        click.echo(f"      Name: {identity.get('full_name', 'N/A')}")
        click.echo(f"      Email: {identity.get('email', 'N/A')}")
        edu = data.get("education", [])
        if edu:
            click.echo(f"      Education: {len(edu)} entries")
        exp = data.get("work_experiences", [])
        if exp:
            click.echo(f"      Experience: {len(exp)} entries")

        click.echo("      Review and edit the profile at:")
        click.echo(f"        {PROFILE_FILE}")

        # Ingest to DB
        if not skip_db and config:
            try:
                from src.memory.profile import ingest_profile
                from src.core.database import get_session_factory

                SessionFactory = get_session_factory(config)
                with SessionFactory() as session:
                    ingest_profile(session, data)
                    click.secho("    [OK] Profile ingested to DB", fg="green")
            except Exception as e:
                click.secho(f"    ! DB ingestion skipped: {e}", fg="yellow")

        return True

    except Exception as e:
        click.secho(f"    [FAIL] Resume parsing failed: {e}", fg="red")
        click.echo("      Hint: Ensure Claude CLI is installed and authenticated")
        return False


def _create_template_profile() -> bool:
    """Copy the schema file as a template for the user to fill in."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    if SCHEMA_FILE.exists():
        shutil.copy2(SCHEMA_FILE, PROFILE_FILE)
        click.secho(f"    [OK] Template created: {PROFILE_FILE}", fg="green")
        click.echo(
            "      Edit this file with your information, then run `autoapply init` again."
        )
        return True
    else:
        click.secho("    [FAIL] Schema template not found", fg="red")
        return False


def _check_llm() -> bool:
    """Check if Claude CLI and/or Codex CLI are available."""
    found_any = False

    # Check Claude CLI
    claude_path = shutil.which("claude")
    if claude_path:
        click.secho("    [OK] Claude CLI found", fg="green")
        found_any = True
    else:
        click.secho("    ! Claude CLI not found", fg="yellow")

    # Check Codex CLI
    codex_path = shutil.which("codex")
    if codex_path:
        click.secho("    [OK] Codex CLI found", fg="green")
        found_any = True
    else:
        click.secho("    ! Codex CLI not found", fg="yellow")

    if not found_any:
        click.secho(
            "    [FAIL] No LLM CLI available -- resume tailoring and QA will fail",
            fg="red",
        )
        click.echo("      Install: npm install -g @anthropic-ai/claude-code")
        return False

    return True
