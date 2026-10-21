#!/bin/sh
set -eu

if [ "${RUN_PREPROD_SEED:-false}" = "true" ]; then
  if [ "${FLASK_ENV:-development}" = "production" ]; then
    echo "Refus: les donnees de demonstration ne doivent pas etre inserees en production." >&2
    exit 1
  fi
  echo "RUN_PREPROD_SEED=true: insertion des données de préproduction..."
  if [ "${SEED_RESET_DEMO:-false}" = "true" ]; then
    python seed_preprod_demo.py --reset-demo
  else
    python seed_preprod_demo.py
  fi
  echo "Seed de préproduction terminé."
fi

exec "$@"
