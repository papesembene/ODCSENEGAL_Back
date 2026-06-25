# Tests de charge locaux

Ces scénarios sont non destructifs et ciblent uniquement des lectures.

## Paliers recommandés

Exécuter les paliers dans l'ordre et arrêter en cas d'erreurs HTTP 5xx,
d'utilisation mémoire anormale ou de latence qui augmente continuellement.

```bash
# Palier 1: validation légère
.venv/bin/locust -f load_tests/locustfile.py \
  --headless --host http://127.0.0.1:5000 \
  -u 10 -r 2 -t 1m

# Palier 2: charge modérée
.venv/bin/locust -f load_tests/locustfile.py \
  --headless --host http://127.0.0.1:5000 \
  -u 50 -r 5 -t 3m

# Palier 3: charge soutenue locale
.venv/bin/locust -f load_tests/locustfile.py \
  --headless --host http://127.0.0.1:5000 \
  -u 150 -r 10 -t 5m
```

Seuils de départ:

- erreurs: moins de 1 %
- aucune réponse HTTP 500
- `p95` des lectures: moins de 500 ms en local
- latence stable pendant toute la durée du palier

Un test de production représentatif doit être exécuté depuis une machine
distincte du serveur, sur un environnement de préproduction isolé.
