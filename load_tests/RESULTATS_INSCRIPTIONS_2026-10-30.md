# Première mesure locale des inscriptions — 30 octobre 2026

6 000 candidatures fictives traitées, soit 18 000 requêtes mesurées, sans erreur.
Un parcours supplémentaire a préchauffé les index : 6 001 candidatures et
6 001 confirmations email en attente ont été vérifiées dans la base jetable.
Aucun worker d'envoi n'a été démarré. L'API et MongoDB de test ont ensuite été
arrêtés et leurs données temporaires supprimées.

| Parcours simultanés | Candidats | Durée | Parcours/s | Soumission p95 | Erreurs HTTP |
|---|---:|---:|---:|---:|---:|
| 10 | 2 000 | 13,866 s | 144,24 | 36,74 ms | 0 |
| 25 | 2 000 | 14,078 s | 142,06 | 75,78 ms | 0 |
| 50 | 2 000 | 17,173 s | 116,46 | 186,85 ms | 0 |

Le p95 signifie que 95 % des requêtes de soumission mesurées ont répondu dans
ce délai. Ce n'est pas le délai du parcours complet, qui comporte trois requêtes.

Configuration : une API Waitress, 8 threads, pool MongoDB maximal de 50,
MongoDB local 8.0.16 avec cache WiredTiger de 256 Mio. Configuration applicative
de production avec paramètres temporaires dédiés, sessions fichiers et limitation
des requêtes conservée. Le jeu de candidatures grandit au fil des paliers.

Pics observés : CPU global 36 %, RSS API 76,02 Mio et MongoDB 172,71 Mio.
Les échantillons sont espacés de 250 ms ; les pics plus courts peuvent être manqués.
Le CPU propre à l'API peut dépasser 100 % car il est exprimé par cœur logique.

## Interprétation

L'enregistrement et la mise en file restent cohérents pour ces courtes rafales.
Le débit n'augmente pas avec la concurrence et la latence monte à 50 parcours :
ces chiffres ne justifient pas d'augmenter aveuglément les threads ou les connexions.
Ils ne permettent pas à eux seuls d'identifier le composant limitant.

Le générateur, l'API et MongoDB partagent la machine. IIS, TLS, le frontend,
la latence du MongoDB réel, Redis, la livraison des emails, les grandes collections
et l'endurance ne sont pas couverts. Cette mesure n'établit aucune capacité garantie
du serveur de production. La prochaine validation représentative doit utiliser une
préproduction séparée, un générateur distant, un volume de données réaliste et une
charge maintenue plusieurs minutes, avec surveillance de tous les composants.

## Reproduire

```powershell
.\.venv\Scripts\python.exe load_tests/registration_load.py `
  --mongod 'C:\chemin\vers\mongod.exe' `
  --levels 10,25,50 --count 2000 `
  --output load_tests/reports/registration-baseline.json
```

Rapport brut de cette exécution :
`load_tests/reports/registration-20261030-baseline.json` (local, ignoré par Git).
Il contient le commit applicatif, le SHA-256 du scénario, les percentiles par
endpoint, les codes HTTP, les compteurs d'intégrité et les mesures de ressources.

Validation du scénario : 3 tests sur l'isolation et le calcul des statistiques.
Suite locale sans services d'intégration activés : 168 tests recensés,
107 réussis et 61 ignorés. La mesure de charge utilise un vrai MongoDB temporaire.
