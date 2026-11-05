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

## Affectations Selon La Residence

Chaque referentiel porte une regle de residence complete, independante de son
nom et de son lieu physique de formation. `applicationRegionMode: "all"`
autorise tous les lieux proposes. `applicationRegionMode: "selected"`
n'autorise que `applicationRegions`, une liste non vide de regions/localites
connues. Une liste vide n'est jamais interpretee comme "tout autoriser" dans
le mode selectionne. Exemple: Developpement Web, mode `selected`, `["Dakar"]`.
Le super admin et l'admin Competences modifient cette regle dans le formulaire
du referentiel; aucun changement de code n'est necessaire.
Les ecritures d'une liste de lieux exigent son mode explicite: un ancien ecran
doit etre recharge plutot que reinterpreter des exceptions partielles.

Les anciennes exceptions partielles sont converties a la lecture en une liste
complete, sans elargir ni reduire les autorisations existantes. Le prochain
enregistrement conserve cette regle explicite. Aucun dossier candidat ni
historique n'est modifie. Les nouveaux referentiels sont ouverts a tous les
lieux par defaut; leur nom ne declenche plus d'affectation automatique.

`GET /api/trainings` fournit les lieux dans `regionalRules.residenceRegions`.
Le formulaire filtre l'offre et le serveur valide cette meme regle avant
toute nouvelle candidature. Modifier une description ou renommer un
referentiel ne remet pas ses autorisations a zero.

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
