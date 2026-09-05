# DealFlow360

**An intelligent, self-governing sales operations platform.**

A B2B sales platform that goes beyond quote-to-invoice: it enforces pricing discipline
through multi-tier discount governance and automated approval routing, reacts to live
inventory by splitting fulfilment across warehouses, keeps one-time and recurring
subscription lines reconciled on a single order, and gives customers a living, negotiable
quotation in their own portal instead of a static PDF.

Built for the Odoo Hackathon 2026 by **Team 317** (solo build).

**Requires Python 3.10 or newer** — see Setup below.

---

## Status

**T-01 (project scaffold) — done.** What exists today is a running Django project, a custom
`User` model with a `role` field, a migrated SQLite database, the Django admin, and a
`/health/` page that proves the round trip.

The quotation builder, approval routing, warehouse split, billing and customer portal are
**not built yet**. See `tasks/BACKLOG.md` for the ordered plan and `tasks/CURRENT.md` for
the task in progress.

---

## Stack

| Layer | Choice |
|---|---|
| Framework | Django 5.2.17 |
| Database | SQLite — one local file, `db.sqlite3` (ADR-002) |
| Templates | Django templates + HTMX, Tailwind via CDN |
| Auth | `django.contrib.auth` with a custom `core.User` carrying `role` (ADR-003) |
| Tests | Django's built-in test runner |

Business logic lives in `core/services/` and nowhere else. See `docs/ARCHITECTURE.md`.

---

## Setup from a clean clone

Every command below is run from the repository root. There is no database server to
install and no Node toolchain to build — SQLite is a file and Tailwind/HTMX are CDN script
tags.

### 1. Clone

```bash
git clone https://github.com/manojk909/DealFlow360.git
cd DealFlow360
```

### 2. Create and activate a virtual environment

**Minimum Python version: 3.10.** Django 5.2 supports 3.10 through 3.13. Developed and
verified on **3.13.5**. Check yours before going further:

```bash
python --version
```

Anything below 3.10 will fail at `pip install`, not at runtime, so you will know immediately.

```bash
python -m venv .venv
```

```bash
# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# Windows Git Bash
source .venv/Scripts/activate

# macOS / Linux
source .venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4. Create the database

```bash
python manage.py migrate
```

This creates `db.sqlite3` in the repository root. It is gitignored — everyone builds their
own from migrations, and later from the seed script.

### 5. Load the demo data

```bash
python manage.py seed_demo
```

This is the fastest way to get a usable database. It creates the full demo dataset from
`docs/DEMO.md` — users, tiers, categories, discount ceilings, approval chain rules,
customers, ten products, subscription plans, two warehouses with stock, and five
quotations across the stages. It is idempotent: running it twice gives the same state.

It seeds eight accounts, all with the password **`dealflow360`**:

| Email | Role |
|---|---|
| `rep@dealflow.test` | Sales Rep |
| `manager@dealflow.test` | Sales Manager |
| `finance@dealflow.test` | Finance |
| `admin@dealflow.test` | Admin (superuser — this is the one that opens `/admin/`) |

`rep2@`, `manager2@`, `finance2@` and `admin2@` exist as a mid-demo fallback set.

**Or** create your own account instead:

```bash
python manage.py createsuperuser
```

You will be prompted for **email** (there is no username — `USERNAME_FIELD` is `email`),
**full name**, and a password.

### 6. Run it

```bash
python manage.py runserver
```

| URL | What it is |
|---|---|
| http://127.0.0.1:8000/health/ | Health page — every value on it is read from `db.sqlite3` |
| http://127.0.0.1:8000/admin/ | Backend configuration area (SPEC §4 A2–A7) |

`/` redirects to `/health/`.

### 7. Optional — environment overrides

Defaults work out of the box. To override the secret key, debug flag or allowed hosts:

```bash
cp .env.example .env
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

Paste the generated key into `.env` as `DJANGO_SECRET_KEY`.

---

## Running the tests

```bash
python manage.py test
```

---

## Resetting the database

SQLite is a single file, so a reset takes seconds:

```bash
rm db.sqlite3          # Windows PowerShell: Remove-Item db.sqlite3
python manage.py migrate
python manage.py seed_demo
```

`seed_demo` alone is usually enough — it wipes and rebuilds every demo row in one
transaction, so the file only needs deleting if the schema itself is in a bad state.
Accounts you created yourself are preserved across a reseed; only the demo rows are
replaced.

---

## Repository layout

```
config/                 settings.py, urls.py, wsgi.py
core/                   the internal application
  models/               split by domain: catalogue, parties, sales, inventory, billing
  management/commands/  seed_demo.py — rebuilds the exact docs/DEMO.md state
  templates/core/       base.html (dark theme shell) + health.html
  admin.py              backend configuration area registrations
  views.py, urls.py     health check for now; rep workspace lands in T-11
portal/                 customer-facing app, mounted at /portal/ — urls reserved,
                        views land in T-14 (token-scoped, no login, ADR-004)
docs/                   SPEC, ARCHITECTURE, DATA_MODEL, DEMO, DECISIONS
tasks/                  BACKLOG, CURRENT, DONE
manage.py
db.sqlite3              local, gitignored, rebuilt from migrations
```

---

## Conventions that matter

- **Never change `AUTH_USER_MODEL`.** It is set to `core.User` in `config/settings.py` and
  was set before the first migration ran. Changing it now means deleting the database and
  every migration. See ADR-003.
- **One person runs `makemigrations` per wave.** Two developers generating migrations for
  the same app in parallel breaks `migrate` for everybody. Announce a migration before
  pushing it.
- **Money is `Decimal`, computed in Python, inside `core/services/`.** SQLite has no
  decimal type and `Sum()` over a `DecimalField` can return a float and drift. See ADR-002.
- **Configuration is data, not code.** Discount ceilings, approval thresholds, warehouse
  shipping weights and subscription plans are database rows editable in the admin. A number
  typed into a view is a bug.

---

## Documentation

| File | What it holds |
|---|---|
| `CLAUDE.md` | Project identity and development principles |
| `docs/SPEC.md` | Structured product requirements (MUST / SHOULD / BONUS) |
| `docs/ARCHITECTURE.md` | Stack, layers, module boundaries |
| `docs/DATA_MODEL.md` | Entities, relationships, invariants |
| `docs/DEMO.md` | The five-minute demo this project must survive |
| `docs/DECISIONS.md` | ADR log |
| `tasks/BACKLOG.md` | All tasks, P0 / P1 / P2 |
