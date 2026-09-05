# CURRENT TASK

**Status: NOT STARTED**

Nothing has been implemented yet. The repository contains documentation only.

Stack is settled: **Django 5 + SQLite** (ADR-001, ADR-002, both Accepted).

---

## T-01 — Project scaffold and database connection

### Objective

Stand up a running Django project with a working SQLite connection and a custom user model,
and prove it with a health page. Every other task is blocked on this.

### Context

`DealFlow360/` was empty before this documentation was written — no source, no manifest, no
migrations, no tests. This is a greenfield start.

**The one thing that must not be got wrong.** `AUTH_USER_MODEL` has to be set in
`settings.py` *before the first migration runs*. Changing Django's user model after
migrations exist means deleting the database and every migration and starting again. So
create the `core` app and its custom `User` model **first**, then run `migrate` — never the
other way round. This is the single most expensive mistake available in this task.

SQLite needs no setup, which removes the database-provisioning risk entirely. Delete
`db.sqlite3` and re-run `migrate` any time it gets into a bad state.

**T-00 runs in parallel.** The open ADRs — ADR-005 above all — block the critical path.
CLAUDE.md's "Resolving open decisions" section authorises closing them; do that alongside
this task rather than after it.

### Acceptance criteria

- [ ] `python manage.py runserver` serves a page.
- [ ] `core` app exists with a custom `User` model carrying a `role` field
      (`REP | MANAGER | FINANCE | ADMIN`), and `AUTH_USER_MODEL` points at it.
- [ ] `python manage.py migrate` applies cleanly against a fresh `db.sqlite3`.
- [ ] A `/health/` page renders a value read **from the database**, proving the round trip.
- [ ] `python manage.py createsuperuser` works and `/admin/` loads.
- [ ] `.gitignore` excludes `db.sqlite3`, `__pycache__/`, `.venv/`, `.env`.
- [ ] `requirements.txt` pins Django and htmx-related deps (there should be very few).
- [ ] `README.md` records the exact setup commands, runnable from a clean clone.
- [ ] **All four team members** have cloned, installed and run it successfully.

### Expected files / modules

```
manage.py
requirements.txt                 django, and very little else
.gitignore, .env.example
config/settings.py               AUTH_USER_MODEL set here, SQLite default
config/urls.py, config/wsgi.py
core/__init__.py, core/apps.py
core/models/__init__.py          package, split by domain later (see ARCHITECTURE.md)
core/models/parties.py           custom User only, for now
core/admin.py                    register User
core/views.py, core/urls.py      health view
core/templates/core/base.html    Tailwind CDN, dark theme shell
core/templates/core/health.html
README.md
```

Nothing else. No services, no auth views, no quotation models, no portal app — those belong
to their own tasks. Do not scaffold empty modules "for later".

### Dependencies

None. This is the first task.

### Verification plan

1. Delete `db.sqlite3`, `.venv` and `__pycache__`. Clone fresh into a scratch directory.
2. Follow only what README.md says. If a step is missing, README.md is wrong — fix it.
3. Load `/health/` and confirm the value came from the database, not a hardcoded constant.
4. Load `/admin/`, log in as the superuser, confirm the custom User model appears with its
   `role` field.
5. Have a second team member repeat steps 1–4 on their own machine.
6. Commit and push. Confirm the evaluator (`kais-odoo`, `hackathon-odoo`) is already a
   collaborator on the repository.

### Then what

T-02 (full schema) and T-03 (seed) follow immediately and unblock all four parallel tracks.

Two coordination rules from hour one:

- **One person runs `makemigrations` per wave.** Two people generating migrations for the
  same app in parallel produces a conflict that breaks `migrate` for everybody.
- **T-03 is the highest-leverage early task.** Every track needs data to build against, and
  the seeded stock (Main Warehouse 4, East Depot 10, demo order of 6) is what makes the
  warehouse split actually trigger during the demo.
