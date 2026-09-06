#!/usr/bin/env bash
set -o errexit

# Render build command. Runs on every deploy.
#
# seed_demo is idempotent and rebuilds the exact docs/DEMO.md state, so a redeploy always
# comes back with the demo data intact. That is what makes SQLite on an ephemeral disk an
# acceptable trade here rather than a data-loss bug — see ADR-018.

pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate
python manage.py seed_demo
