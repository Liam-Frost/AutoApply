"""Phase 14.6 task definitions land here.

This module is intentionally empty during 14.1 -- it exists so the
``include=["src.tasks.tasks"]`` line in :mod:`src.tasks.app` resolves
without ImportError. Each subsequent sub-phase appends a task to this
module:

    * 14.6 task kinds: search.refresh, jobs.enrich, materials.generate,
      application.prepare, application.fill, application.submit,
      status.sync

Workers running ``celery -A src.tasks worker -Q <queue>`` will pick up
new tasks here without configuration changes.
"""
