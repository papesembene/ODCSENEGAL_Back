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

## Sites Et Residence

La collection `training_sites` gere les lieux de formation. Dakar, Thies,
Diamniadio / UAM et Tambacounda sont des valeurs initiales sans ecriture sur GET.
Chaque referentiel declare ses sites dans `siteIds`. Une publication exige
au moins un site. Les nouvelles affectations sont validees contre ce catalogue.
Un nouveau site ne recoit pas automatiquement toutes les formations.

Le candidat choisit d'abord son site, puis sa formation. Sa residence reste
une information de contact independante: un resident de Diourbel peut choisir
Dakar. Le serveur verifie site actif + formation publiee + affectation avant
toute ecriture. Les anciennes regles `applicationRegions` ne sont plus appliquees
ni converties en sites. Aucun dossier historique n'est reaffecte.

`GET /api/trainings` retourne `trainingSites` et `residenceLocations` en plus
des formations. Le dossier enregistre `training_site` (code stable) et
`training_site_name` (nom au moment de la candidature, derive du serveur).
Les anciens dossiers sans site restent non renseignes. Les filtres pagines
et exports acceptent `training_site` sans telecharger tous les candidats.

`POST /api/admin/training-sites` ajoute un site. PATCH et DELETE sur
`/api/admin/training-sites/<code>` exigent sa version. DELETE archive sans
supprimer les dossiers. Le super admin et l'admin Competences gerent les sites;
les membres du jury ont seulement acces en lecture. Deployer frontend et
backend ensemble: le nouveau formulaire envoie obligatoirement `training_site`.

Chaque site peut definir `applicationDeadline` au format `YYYY-MM-DDTHH:mm`,
interprete en heure de Dakar. Sans date, seule la cloture generale de la
campagne s'applique. L'API publique expose aussi `applicationOpen`; le formulaire
affiche l'echeance ou signale que le site est ferme. Le backend revalide cette
date au moment de l'envoi et refuse une candidature tardive, meme si la requete
contourne le formulaire.

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
