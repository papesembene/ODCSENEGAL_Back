# Catalogue des referentiels

La collection `trainings` contient les informations gerees par le super admin
et l'admin Competences. Les membres du jury peuvent lire le catalogue, pas le
modifier. Le CM ne gere pas les referentiels.

- `code` et `value` sont immuables. `title` est modifiable; ses anciennes
  valeurs restent des alias pour les recherches historiques.
- Les sept formations existantes sont des valeurs initiales, sans ecriture
  sur un GET. Une premiere modification cree leur document versionne.
- `draft` prepare un referentiel, `published` le propose sur le portail,
  `archived` le retire des nouveaux parcours sans effacer les anciens dossiers.
- La publication d'un referentiel n'ouvre pas les candidatures: leur campagne
  conserve ses dates et ses regles d'ouverture.
- Les criteres et questions d'entretien restent configures par campagne,
  suivant les droits existants. Un nouveau referentiel n'herite pas des
  criteres metier de Developpement Web.

## API

`GET /api/trainings` expose seulement les formations publiees.
`GET /api/admin/trainings` expose aussi brouillons et archives.
`POST /api/admin/trainings` cree une formation.
`PATCH /api/admin/trainings/<code>` modifie les champs publics.
`DELETE /api/admin/trainings/<code>` archive; il ne supprime aucune donnee.
PATCH et DELETE exigent la `version` lue; un conflit renvoie HTTP 409.
`POST /api/admin/trainings/media` importe un fichier `image` valide.

Les lectures utilisent un cache local de cinq secondes, invalide a l'ecriture.
Les lectures administrateur forcent une actualisation. Les autres processus
voient les changements au prochain renouvellement du cache. Les images sont
stockees dans `app/static/uploads/trainings`, inclus dans le volume public des
deploiements Docker et exclu de Git et des images Docker.

## Verification

`python -m unittest tests.test_training_catalog`

Les tests de persistance sont optionnels: une instance MongoDB jetable doit
ecouter uniquement sur `127.0.0.1:27027`, puis executer
`TEST_TRAINING_MONGO=1 python -m unittest tests.test_training_catalog_integration`.
Le test cree et supprime sa propre base avec un nom aleatoire; il ne lit pas
l'URI de production.
