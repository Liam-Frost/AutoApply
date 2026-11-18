"""Who creates the account: the agent on sites the user has never applied on, the user where one probably exists."""


def _job(s, company, ats, tenant, url="", status=None):
    from autoapply.models import Application, Job

    j = Job(source="t", source_id=f"{company}-{tenant}-{status}", company=company, title="x", ats=ats, tenant=tenant, apply_url=url, status="scored")
    s.add(j)
    s.flush()
    if status:
        s.add(Application(job_id=j.id, status=status))
    return j

