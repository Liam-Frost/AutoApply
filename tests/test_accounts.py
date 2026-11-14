"""Who creates the account: the agent on sites the user has never applied on, the user where one probably exists."""


def _job(s, company, ats, tenant, url="", status=None):
    from autoapply.models import Application, Job

    j = Job(source="t", source_id=f"{company}-{tenant}-{status}", company=company, title="x", ats=ats, tenant=tenant, apply_url=url, status="scored")
    s.add(j)
    s.flush()
    if status:
        s.add(Application(job_id=j.id, status=status))
    return j


def test_register_policy(app_env):
    from autoapply import auth, db
    from autoapply.ats.base import JobRef

    with db.session() as s:
        _job(s, "Ciena Corporation", "workday", "ciena", status="confirmed")  # applied here before
        _job(s, "Ciena Corporation", "workday", "ciena")
        _job(s, "TMX", "workday", "tmx")
        _job(s, "Bombardier", "generic", "jobs.bombardier.com", url="https://jobs.bombardier.com/job/1")
    ciena = JobRef("workday", "ciena", "1", "https://ciena.wd5.myworkdayjobs.com/x", "ciena.wd5.myworkdayjobs.com")
    tmx = JobRef("workday", "tmx", "2", "https://tmx.wd3.myworkdayjobs.com/x", "tmx.wd3.myworkdayjobs.com")
    bomb = JobRef("generic", "jobs.bombardier.com", "", "https://jobs.bombardier.com/job/1", "jobs.bombardier.com")

    ok, why = auth.may_register(ciena)
    assert not ok and "Ciena" in why  # an account probably exists: the user signs in once
    assert auth.may_register(tmx) == (True, "")  # never applied: the agent registers
    assert auth.may_register(bomb) == (True, "")

    auth.allow_register(ciena.tenant_key)  # "I have no account there"
    assert auth.may_register(ciena) == (True, "")

    db.set_setting("register.per_ats", {"workday": False})
    assert auth.may_register(tmx)[0] is False
    db.set_setting("register.per_ats", {})
    db.set_setting("register.auto", False)
    assert auth.may_register(bomb)[0] is False

    db.set_setting("register.auto", True)
    auth.upsert_account(tmx.tenant_key, status="needs_human", error="account already exists")
    assert auth.may_register(tmx)[0] is False  # sign-up said the e-mail is taken


def test_confirmation_wording():
    from autoapply.executor import DONE_RE, DONE_URL

    for t in ("Thanks for applying!", "Thank you for your application", "Your application has been received.", "Application submitted", "We have received your submission",
              "Application was sent"):
        assert DONE_RE.search(t), t
    for t in ("Submit application", "Apply now", "Thanks to our team"):
        assert not DONE_RE.search(t), t
    assert DONE_URL.search("https://x.applytojob.com/apply/abc/confirmation") and DONE_URL.search("https://x.com/thank-you?id=1")
    assert not DONE_URL.search("https://x.com/apply/complete-your-profile-form")
