"""Phase 17 orchestration package.

The Phase 14 task queue ships individual task kinds (``search.refresh``,
``materials.generate``, ``application.prepare``, ...). This package
threads them into end-to-end flows -- the canonical example is the
plan run that produces a fresh review queue every time a user's Plan
ticks.

Modules:
    plan_run -- the 'one Plan tick produces a fresh review queue' use
                case (Phase 17.1). Never auto-submits.
"""
