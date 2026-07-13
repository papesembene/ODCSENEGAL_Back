#!/bin/sh
set -eu

if [ "${RUN_PREPROD_SEED:-false}" = "true" ]; then
  echo "RUN_PREPROD_SEED=true: insertion des données de préproduction..."
  if [ "${SEED_RESET_DEMO:-false}" = "true" ]; then
    python seed_preprod_demo.py --reset-demo
  else
    python seed_preprod_demo.py
  fi
  echo "Seed de préproduction terminé."
fi

if [ "${RUN_DELETE_PREPROD_CANDIDATURE_CAMPAIGNS:-false}" = "true" ]; then
  echo "RUN_DELETE_PREPROD_CANDIDATURE_CAMPAIGNS=true: suppression des campagnes de candidature préprod..."
  python delete_preprod_candidature_campaigns.py
fi

exec gunicorn run:app --bind 0.0.0.0:${PORT:-5000} --workers ${WEB_CONCURRENCY:-1} --threads ${GUNICORN_THREADS:-8} --timeout ${GUNICORN_TIMEOUT:-120}
