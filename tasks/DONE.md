# Completed Tasks

Newest first. A task lands here only when it genuinely works end to end, per CLAUDE.md's
completion protocol.

---

## T-00 — Close the blocking open decisions

*Completed 05 Sep 2026. Ran in parallel with T-01.*

**Four ADRs closed. No P0 task is blocked by an open decision any more.**

| ADR | Decision, in one sentence |
|---|---|
| **ADR-005** blended risk score | The score is the total number of discount percentage points given away above ceiling across the whole quotation, where every line is measured against the stricter of its customer tier's ceiling and its category's. |
| **ADR-006** warehouse split | Fill each line from the cheapest warehouse first and spill into the next cheapest — except that a warehouse able to cover the whole line by itself ships it alone — and whatever is left becomes a backorder. Documented as a heuristic in the ADR, in SPEC BR-4 and on the screen. |
| **ADR-004** portal access | A signed, quotation-scoped `TimestampSigner` token at `/portal/<token>/`, copied from the internal screen: no customer accounts, no passwords, no email, no expiry; a bad token returns 403. |
| **ADR-010** stage machine | One `stage` enum, `SENT` a real stage reachable only from `APPROVED`, `REJECTED` terminal, return-for-revision a separate `ApprovalStep.status = RETURNED` sending the quote back to `DRAFT`, and portal status a display mapping over `stage` rather than a stored field. |

**ADR-007, ADR-008 and ADR-009 were deliberately left open.** All three block P1 tasks only
(T-21 deal health, T-20 proration, T-05/T-23 tax and reporting), and BACKLOG T-00 defers them
on purpose.

**The two specification tests were written before the formula**, per BACKLOG T-00 and
CLAUDE.md. `core/tests/test_risk.py` asserts both PDF §10 worked examples against the API
that ADR-005 fixes. They currently skip with the reason
`"core.services.risk not implemented yet — see T-09"`, so `manage.py test` stays green at
T-01 and turns red the moment T-09 gets the arithmetic wrong. The file says in its docstring
that it is the specification and must not be edited to match the implementation.

Both examples reproduce, and can be checked by hand:

- Example 1 — Hardware 12% against ceiling 15 → 0 over; Services 18% against `min(15, 10)` =
  10 → **8 over**. Score 8.00, flagged, and 8.00 is exactly the Finance boundary.
- Example 2 — 17/15, 13/10, 14/12 → 2 + 3 + 2 = **7.00**, flagged, Manager only.

**ApprovalChainRule rows for T-03 to seed** — configuration, not code:

| `score_min` | `score_max` | `requires_manager` | `requires_finance` |
|---|---|---|---|
| 0.00 | 0.00 | false | false |
| 0.01 | 7.99 | true | false |
| 8.00 | 9999.99 | true | true |

Inclusive both ends, tiling with no gap or overlap. A score matching no rule must fail
loudly rather than silently skip governance. The bands are exact because the score is
quantised to 0.01, so nothing can land between 7.99 and 8.00.

**Two contradictions surfaced by the decisions, both fixed rather than noted.**

1. **DEMO.md Flow B was one approval step short.** B3 had Beta Industries (Silver, ceiling
   10%) counter at 20% — 10 points over, which under the new bands pulls in Finance as well
   as the Manager — while B5 showed only the Manager approving and B6 then expected Confirm
   to work. Fixed by countering at **15%** instead: 5 points over, still automatic re-entry
   for AC-7, but inside the Manager-only band. Flow A already demonstrates the two-step
   chain. The 20%-plus-Finance variant is recorded in DEMO.md as a rehearsed alternative.
2. **DATA_MODEL.md's lifecycle diagram had a `DRAFT → SENT` edge.** ADR-010 forbids it — a
   rep could otherwise send a customer the portal link straight out of Draft and route
   around governance entirely, breaking invariants 2 and 5. The diagram was redrawn and the
   removal called out in the text rather than quietly patched.

Also cleaned up: `docs/ARCHITECTURE.md` still carried two `DECISION NEEDED` markers for
ADR-004 (portal mechanism, and whether to send email at all). Both now state the decision.

**Remaining risk.** The risk formula deliberately ignores line value and quantity — a
judge may ask why a 20% discount on a €5 item scores the same as one on a €5,000 item. The
honest answer, recorded in ADR-005, is that PDF §10's worked examples are stated purely in
percentage points with no prices, so a value-weighted score cannot reproduce them, and the
live margin indicator is the separate signal that carries value. Worth rehearsing before the
demo, because it is the most likely question about the product's core rule.

---

## T-01 — Project scaffold and database connection

*Completed 05 Sep 2026. Commit `385bfd1`.*

**What landed.** A running Django 5.2 project on SQLite with a custom `User` model and a
health page that proves the URL → view → ORM → SQLite → template round trip.

**Acceptance criteria — verified, not assumed.**

| Criterion | How it was verified |
|---|---|
| `runserver` serves a page | Server started on 127.0.0.1:8137; `GET /` → 302 → `/health/`, `GET /health/` → 200 |
| `core` app with custom `User` carrying `role`, `AUTH_USER_MODEL` set to it | `AUTH_USER_MODEL = "core.User"`; role choices `REP / MANAGER / FINANCE / ADMIN`; the health page prints the model label read from `User._meta` |
| `migrate` applies cleanly to a fresh `db.sqlite3` | `db.sqlite3` deleted, `makemigrations core` then `migrate` — 19 migrations applied, `core.0001_initial` among them, no conflicts |
| `/health/` renders a value read from the database | Live proof: created a second user through the ORM, the page's user count went 1 → 2 and a `FINANCE` role chip appeared; deleting the user returned it to 1. Also prints `sqlite_version()` from a real cursor and the applied-migration count from `django_migrations` |
| `createsuperuser` works and `/admin/` loads | Superuser `admin@dealflow.test` created (email is `USERNAME_FIELD`, there is no username); login succeeds, `/admin/` → 200, user changelist shows the Role column, add and change forms both render `id_role` |
| `.gitignore` excludes `db.sqlite3`, `__pycache__/`, `.venv/`, `.env` | `git status --ignored` confirms all four are ignored; `db.sqlite3` is absent from a fresh clone |
| `requirements.txt` pins Django and very little else | Two lines: `Django==5.2.17`, `python-dotenv==1.2.3`. HTMX and Tailwind are CDN script tags, not Python packages |
| `README.md` runnable from a clean clone | **Actually performed.** Cloned into a scratch directory, created a venv, installed from `requirements.txt`, migrated, created a superuser and ran the server on port 8138 following only the README. `/health/` → 200 showing 1 user and an `ADMIN` role, read from the clone's own fresh database |
| All four members have cloned and run it | **NOT verified — this one is on the team.** See Remaining risks below |

**Decisions taken inside the task.**

- **Email login, no username.** `USERNAME_FIELD = "email"` with `AbstractBaseUser` +
  `PermissionsMixin` and a custom manager, because DATA_MODEL.md gives `User` an email and
  a `name` and no username. `createsuperuser` therefore prompts for email and full name.
- **Python 3.13, not 3.10.** ARCHITECTURE.md recorded Python 3.10.12 on the dev machine;
  this machine has 3.13.5. Django 5.2 supports 3.10 through 3.13, so the code targets 3.10+
  and runs on either. Nothing in the project uses a 3.11+ language feature.
- **`python-dotenv` added as the second and only other dependency**, so `.env.example` is
  meaningful rather than decorative. Settings fall back to working defaults without a
  `.env`, so the app runs immediately after `migrate` with no configuration step.

**Bug found and fixed during verification.** The admin's `add_fieldsets` referenced
`usable_password`, which exists on Django 5.1+'s `AdminUserCreationForm` but not on
`UserCreationForm`. `/admin/core/user/add/` returned a 500 `FieldError` until the form was
switched. Worth noting because it is invisible to `manage.py check` — only loading the page
catches it.

**Remaining risks.**

- Only one machine has run this. The "all four members" criterion is genuinely unverified.
- Tailwind and HTMX load from CDNs, so the UI degrades to a minimal inline fallback with no
  network. Logged as **T-26a**; vendor them before the demo rehearsal.
- `/health/` is the only page. Nothing else is built yet, and nothing should be read into
  the scaffold beyond "the round trip works".
