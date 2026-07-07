# Tests de charge locaux

Ces scénarios permettent de tester progressivement le backend sans attendre
la production. Le scénario historique cible uniquement des lectures publiques.
Le scénario `online_test_locustfile.py` cible le parcours critique des tests
en ligne.

## 1. Lectures publiques non destructives

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

## 2. Parcours candidat test en ligne

Préparer un fichier CSV de candidats déjà affectés au test:

```csv
name,email,phone
Moussa Ba,moussa@example.com,771234567
Awa Diop,awa@example.com,771234568
```

Par défaut, ce scénario lit les métadonnées publiques et vérifie l'accès. Il
ne soumet pas de résultats, donc il est utilisable sans polluer la base.

```bash
ODC_LOAD_TEST_ID="ID_DU_TEST" \
ODC_LOAD_CANDIDATES_CSV="/chemin/candidats.csv" \
.venv/bin/locust -f load_tests/online_test_locustfile.py \
  --headless --host http://127.0.0.1:5000 \
  -u 50 -r 5 -t 3m
```

Pour tester aussi les soumissions finales, utiliser une base de test isolée et
un CSV avec des candidats jetables qui n'ont pas encore soumis ce test:

```bash
ODC_LOAD_TEST_ID="ID_DU_TEST" \
ODC_LOAD_CANDIDATES_CSV="/chemin/candidats-test.csv" \
ODC_LOAD_SUBMIT_RESULTS=1 \
.venv/bin/locust -f load_tests/online_test_locustfile.py \
  --headless --host http://127.0.0.1:5000 \
  -u 100 -r 10 -t 5m
```

Seuils recommandés pour le parcours test en ligne:

- erreurs: 0 % sur `/verify-access` et `/results`
- aucune réponse HTTP 500
- `p95` vérification d'accès: moins de 800 ms en local
- `p95` soumission résultat: moins de 1500 ms en local
- aucun emballement CPU ou mémoire pendant le palier
