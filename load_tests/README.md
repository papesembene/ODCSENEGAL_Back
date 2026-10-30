# Tests de charge locaux

## Inscriptions : scénario Windows autonome et isolé

`registration_load.py` démarre son propre MongoDB et sa propre API Waitress,
sur deux ports loopback libres et dans un dossier temporaire. Il ne propose
aucune cible distante et n'utilise aucun fichier `.env` du projet. Les secrets,
les paramètres email, Redis, APM et proxy du processus appelant ne sont pas
transmis à l'API de test. Il faut fournir un exécutable `mongod` déjà installé.

Depuis le backend, dans PowerShell :

```powershell
.\.venv\Scripts\python.exe load_tests/registration_load.py `
  --mongod 'C:\chemin\vers\mongod.exe' `
  --levels 10,25,50 --count 2000 `
  --output load_tests/reports/inscriptions.json
```

Chaque parcours lit l'ouverture de campagne, vérifie l'unicité de l'email,
puis soumet une nouvelle candidature fictive. Les index sont préchauffés
par un parcours avant la mesure. La concurrence est le nombre de parcours
en cours, pas un nombre d'inscriptions par seconde. Chaque palier traite
`--count` nouveaux candidats ; le maximum est 100 parcours simultanés et
2 000 candidats par palier. Les valeurs par défaut sont 8 threads Waitress
et un pool MongoDB maximal de 50 connexions.

Le rapport JSON contient les p50/p95/p99 par endpoint, les codes HTTP,
les erreurs, le débit des parcours et des échantillons CPU/RSS toutes les
250 ms. Le CPU d'un processus peut dépasser 100 % lorsqu'il utilise plusieurs
cœurs. Le RSS additionne les processus enfants, sans déduire les pages partagées.
Le script vérifie aussi le nombre de candidatures et de confirmations en file.

Aucun worker email n'est démarré et aucune livraison d'email n'est mesurée.
À la fin, les processus créés et leurs enfants sont arrêtés, puis le répertoire
temporaire contenant la base et les sessions est supprimé. Les rapports restent
dans `load_tests/reports` (ignorés par Git). En cas d'échec, un journal des
processus de test est conservé à côté du rapport.

Le scénario arrête les paliers suivants si une requête échoue, si les compteurs
divergent, si le p95 des soumissions dépasse `--max-p95-ms` (1 500 ms par défaut),
ou si un échantillon de CPU global dépasse 85 %. Ces seuils sont des critères
d'arrêt de cette mesure exploratoire, pas une garantie de capacité.

Cette mesure locale ne couvre pas IIS, TLS, le frontend, le réseau des candidats,
les envois effectifs d'emails, Redis, une grosse base historique ou une charge
soutenue pendant des heures. Le générateur, l'API et MongoDB partagent la même
machine : le débit ne constitue donc pas une capacité garantie de production.

La commande n'exige aucune modification ni aucun redéploiement du backend publié.

Ces scénarios permettent de tester progressivement le backend sans attendre
la production. Le scénario historique cible uniquement des lectures publiques.
Le scénario `online_test_locustfile.py` cible le parcours critique des tests
en ligne.

## 0. Préparer les candidats

Pour les tests en ligne, préparer un CSV de candidats déjà affectés au test:

```csv
name,email,phone
Moussa Ba,moussa@example.com,771234567
Awa Diop,awa@example.com,771234568
```

Ou générer le CSV automatiquement à partir d'un test déjà lié à un groupe:

```bash
cd /home/mr-sem-s/Documents/odcsenegal/backend

.venv/bin/python load_tests/export_test_candidates.py "ID_DU_TEST" \
  --output load_tests/candidats-test.csv
```

Pour créer un jeu de charge jetable complet en local/préprod:

```bash
cd /home/mr-sem-s/Documents/odcsenegal/backend

.venv/bin/python load_tests/seed_online_test_load_data.py \
  --reset \
  --count 500 \
  --formation "Dev Web" \
  --output load_tests/candidats-load.csv
```

La commande affiche ensuite le `Test ID` à utiliser dans Locust ou k6.
Les données créées sont préfixées `[LOAD]` ou utilisent le domaine
`@load.odc.local`.

Pour supprimer uniquement ces données jetables:

```bash
.venv/bin/python load_tests/seed_online_test_load_data.py --reset-only
```

Important:

- utiliser une base locale ou préprod isolée;
- ne jamais activer la soumission finale sur des candidats réels;
- prévoir au moins autant de candidats CSV que d'utilisateurs virtuels;
- commencer par le mode non destructif, puis augmenter la charge.

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

## 2. Parcours candidat test en ligne avec Locust

Par défaut, ce scénario lit les métadonnées publiques et vérifie l'accès. Il
ne soumet pas de résultats, donc il est utilisable sans polluer la base.

```bash
ODC_LOAD_TEST_ID="ID_DU_TEST" \
ODC_LOAD_CANDIDATES_CSV="/chemin/candidats.csv" \
.venv/bin/locust -f load_tests/online_test_locustfile.py \
  --headless --host http://127.0.0.1:5000 \
  -u 50 -r 5 -t 3m \
  --only-summary
```

Pour tester aussi les soumissions finales, utiliser une base de test isolée et
un CSV avec des candidats jetables qui n'ont pas encore soumis ce test:

```bash
ODC_LOAD_TEST_ID="ID_DU_TEST" \
ODC_LOAD_CANDIDATES_CSV="/chemin/candidats-test.csv" \
ODC_LOAD_SUBMIT_RESULTS=1 \
.venv/bin/locust -f load_tests/online_test_locustfile.py \
  --headless --host http://127.0.0.1:5000 \
  -u 100 -r 10 -t 5m \
  --only-summary
```

Seuils recommandés pour le parcours test en ligne:

- erreurs: 0 % sur `/verify-access` et `/results`
- aucune réponse HTTP 500
- `p95` vérification d'accès: moins de 800 ms en local
- `p95` soumission résultat: moins de 1500 ms en local
- aucun emballement CPU ou mémoire pendant le palier

Dernier contrôle local, le 29/07/2026:

- 50 utilisateurs avec soumission finale: 200 requêtes, 0 échec, `p95`
  global autour de 120 ms.
- 100 utilisateurs avec soumission finale: 400 requêtes, 0 échec, `p95`
  global autour de 250 ms.

## 3. Parcours candidat test en ligne avec k6

`k6` est recommandé pour une lecture rapide des seuils, des percentiles et des
erreurs. Le script `online_test_k6.js` simule le parcours candidat:

- lecture des métadonnées publiques du test;
- vérification email/téléphone;
- sauvegarde de brouillon de session;
- soumission finale uniquement si `ODC_LOAD_SUBMIT_RESULTS=1`.

Installation locale si `k6` n'est pas déjà installé:

```bash
sudo snap install k6
```

Palier 1, non destructif:

```bash
cd /home/mr-sem-s/Documents/odcsenegal/backend

ODC_LOAD_BASE_URL="http://127.0.0.1:5000" \
ODC_LOAD_TEST_ID="ID_DU_TEST" \
ODC_LOAD_CANDIDATES_CSV="load_tests/candidats-test.csv" \
ODC_LOAD_USERS=50 \
ODC_LOAD_DURATION="2m" \
k6 run load_tests/online_test_k6.js
```

Palier 2, non destructif:

```bash
ODC_LOAD_BASE_URL="http://127.0.0.1:5000" \
ODC_LOAD_TEST_ID="ID_DU_TEST" \
ODC_LOAD_CANDIDATES_CSV="load_tests/candidats-test.csv" \
ODC_LOAD_USERS=200 \
ODC_LOAD_DURATION="5m" \
k6 run load_tests/online_test_k6.js
```

Palier 3, soumission finale sur candidats jetables uniquement:

```bash
ODC_LOAD_BASE_URL="http://127.0.0.1:5000" \
ODC_LOAD_TEST_ID="ID_DU_TEST" \
ODC_LOAD_CANDIDATES_CSV="load_tests/candidats-jetables.csv" \
ODC_LOAD_USERS=200 \
ODC_LOAD_DURATION="5m" \
ODC_LOAD_SUBMIT_RESULTS=1 \
k6 run load_tests/online_test_k6.js
```

Seuils k6 configurés:

- moins de 1 % d'erreurs HTTP;
- `p95` métadonnées publiques: moins de 800 ms;
- `p95` vérification d'accès: moins de 1000 ms;
- `p95` sauvegarde brouillon: moins de 1200 ms;
- `p95` soumission finale: moins de 1500 ms.
