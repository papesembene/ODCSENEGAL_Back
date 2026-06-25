# Résultats des tests de charge locaux

Environnement:

- date: 25 juin 2026
- cible: `http://127.0.0.1:5000`
- serveur: Waitress, 150 threads
- scénario: lectures publiques non destructives

## Palier 10 utilisateurs

- durée: 30 secondes
- requêtes: 466
- erreurs: 0
- débit: 15,70 requêtes/seconde
- latence moyenne: 6 ms
- p95: 10 ms
- p99: 12 ms
- maximum: 34 ms

## Palier 50 utilisateurs

- durée: 3 minutes
- requêtes: 14 395
- erreurs: 0
- débit: 80,09 requêtes/seconde
- latence moyenne: 7 ms
- p95: 14 ms
- p99: 23 ms
- maximum: 69 ms

## Conclusion

Les paliers locaux de lecture sont validés. Ils ne remplacent pas un test
de préproduction depuis une machine distincte, notamment pour les
soumissions de candidatures, l'accès aux tests et l'envoi simultané de
résultats.
