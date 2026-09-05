# CURRENT TASK

**Status: NOT STARTED**

Done so far — see `tasks/DONE.md`: T-00 (four blocking ADRs closed), T-01 (scaffold),
T-02 + T-03 (full schema and seed, one migration wave), and the services integration
contract.

The database rebuilds from scratch with `migrate` + `seed_demo` in seconds, and the seeded
Acme quotation scores exactly the 8.00 ADR-005 predicts. No P0 task is blocked by an open
decision.

---

## T-04 — Internal auth and role-based access

### Objective

FR-01. Signup, login, logout, session, and four roles enforced **server-side on every
action**.

### Context

`core.User` already exists with `role` (`REP | MANAGER | FINANCE | ADMIN`), email as
`USERNAME_FIELD`, and Django's password hashers. `seed_demo` creates eight accounts, all
with the password `dealflow360`; only the ADMIN accounts are `is_staff`/`is_superuser`
today.

What is missing is everything a human uses: there is no login page, no signup page, no
logout, and no way to check a role before an action.

**The part that is actually scored.** PDF §6 lists role-based access under industry-ready
system thinking, and T-04's acceptance says a Rep attempting an approval is refused **by
the server**, not by a hidden button. Build the check first and the button second.

`SESSION_COOKIE_HTTPONLY`, `SESSION_COOKIE_SAMESITE` and `CSRF_COOKIE_SAMESITE` are already
set in `config/settings.py` from T-01.

### Scope

- Login, logout and signup views in `core/`, using `django.contrib.auth` — do not
  hand-roll authentication.
- A role-checking decorator or mixin that views use, e.g. `@require_roles(Role.MANAGER,
  Role.FINANCE)`, returning 403 rather than redirecting to login when the user is
  authenticated but wrong-roled. Those are different failures and should not look alike.
- Django forms for every input, since ARCHITECTURE.md makes forms the place where Odoo's
  "validate user input robustly" must-have is satisfied.
- Templates extending `core/templates/core/base.html`, matching the dark theme.

Signup assigns a role. Decide and record whether self-signup may create a MANAGER or
FINANCE account, or whether it only creates REPs — an unauthenticated visitor granting
themselves approval rights would make the whole governance story hollow. There is no ADR
for this; add one if the answer is not obvious.

### Acceptance criteria

- [ ] Signup and login work with hashed passwords; logout ends the session.
- [ ] Session cookie is httpOnly and sameSite (already set — confirm, do not re-set).
- [ ] Role is read from the User row and checked server-side on every protected action.
- [ ] A Rep POSTing directly to an approval URL is refused **by the server**, with a 403,
      and a test asserts it.
- [ ] Invalid input is rejected with a visible message, not a stack trace or a silent
      no-op.
- [ ] The seeded accounts all log in.
- [ ] `manage.py test` still passes.

### Out of scope

The approval screen itself (T-13) and the workspace (T-11). This task builds the gate, not
the rooms behind it. Do not register config models in admin here — that is T-05/T-06/T-07.

### Verification plan

1. Log in as each of the four seeded roles.
2. `curl -X POST` an approval endpoint as a Rep session and confirm a 403 — not a redirect,
   not a 200.
3. Submit each form empty and confirm a visible field error.
4. Confirm logout actually clears the session by re-requesting a protected page.

### Then what

T-05, T-06 and T-07 register the configuration models in Django admin. Those three
together are what make **AC-1 demonstrable** — a discount tier, a warehouse and a
subscription plan created through a screen and still there on reload. The rows exist and
persist today, but nothing can edit them yet.
