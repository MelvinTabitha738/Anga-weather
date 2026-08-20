#!/usr/bin/env bash
# Render build step. Any failure here must fail the deploy, hence errexit.
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --no-input

# Migrations and the gazetteer seed are both idempotent, so running them on
# every deploy is safe and keeps a fresh environment self-provisioning.
python manage.py migrate --no-input
python manage.py seed_locations
