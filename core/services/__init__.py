"""
The services layer — **all business logic lives here and nowhere else.**

Rules that hold across every module in this package (ARCHITECTURE.md, CLAUDE.md):

* **Plain Python.** Functions take model instances or plain data and return results.
  No `request`, no HTTP, no response objects, no template rendering. Anything that needs
  a request belongs in a view.
* **Configuration is read, never embedded.** Discount ceilings, approval bands, shipping
  weights and subscription plans are database rows. A threshold typed into a function is
  a bug, not a shortcut.
* **Money is `Decimal`, computed in Python.** SQLite has no decimal type and `Sum()` over
  a `DecimalField` can return a float and drift (ADR-002). Never aggregate money in the
  database.
* **Explained results, not bare numbers.** The approval screen has to show *why* a
  quotation was flagged, so `risk.py` returns a per-line breakdown alongside the score.
  The same principle applies to the split and the billing schedule.
* **Multi-row changes run inside `transaction.atomic()`.** Money, quantities and stock
  move together or not at all.
* **A service may call another service, but may not reach around it into another domain's
  models.** Pricing does not touch stock; fulfilment does not touch quotation pricing.

**Status: contract only.** Every function below is a signature and a docstring with a
`NotImplementedError` body. This file set exists so the interfaces are agreed before any
of them is written, and so the tasks that implement them cannot quietly disagree about
shapes. Each module names the task that fills it in.
"""
