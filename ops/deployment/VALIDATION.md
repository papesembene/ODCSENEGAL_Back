# Bilan de preparation, 21 octobre 2026

## Changements

- Images frontend Next standalone et backend non-root; compose de production
  avec Redis, API, frontend, worker email et proxy HTTP local.
- Validation explicite de la base, des secrets et des origines en production;
  aucun seed automatique autorise dans cet environnement.
- Budget des connexions Mongo et des threads configurable; compteurs de
  limitation et sessions partages entre API via Redis.
- Ecritures atomiques des brouillons et sessions pour ne pas rouvrir un test
  soumis; deplacement d'un candidat a reprogrammer par mise a jour atomique.
- Score recalcule cote serveur a partir du test en base: les scores, seuils,
  metadonnees et notes manuelles envoyes par le candidat ne sont pas fiables.
  Les questions du candidat sont retournees sans bonnes reponses, apres controle
  de son identite et de son groupe. Les corriges restent reserves a l'administration.
- Invitations de groupe en file Mongo durable, dedupliquees et traitees hors
  requete HTTP; echecs temporaires retentes, echecs permanents visibles.
- Transport email commun: choix explicite Brevo, SendGrid ou relais SMTP.
- Notifications de resultats reellement mises en file, avec destinataires lus
  en base, selection bornee a 500 resultats et suivi des echecs. Les anciens
  succes simules et la liste fictive de destinataires sont retires.
- Resultats administratifs pagines en base (20 par defaut, maximum 100), filtres
  par referentiel et statut avant pagination, ordre stable et index dedies.
  Les reponses et historiques d'infractions ne sont charges qu'a l'ouverture.
  Statistiques globales et graphiques calcules par aggregation Mongo; export CSV
  complet des resultats filtres, emis par lots et protege contre les formules.
- Restrictions jury appliquees aussi aux API administratives, pas seulement aux
  menus; lecture et suppression des infractions reservees aux administrateurs.
- Enregistrement des infractions controle par l'identite candidat, compteurs et
  historique modifies atomiquement; aucun rattachement a un resultat fourni par
  le navigateur. L'anti-triche respecte l'URL API configuree, y compris le port 5001.
- Nouvelle confirmation possible apres expiration pour un resultat deja enregistre,
  sans modifier ses reponses; les premieres soumissions hors delai restent refusees.
- Dates relues en base pour autoriser l'acces, sans se fier au cache d'un autre
  worker. L'invalidation immediate du cache de metadonnees est locale au processus;
  les autres processus peuvent afficher l'ancienne date pendant au plus cinq minutes,
  sans autoriser une entree interdite.
- Remplacement de Flask-MongoEngine par une liaison directe a MongoEngine,
  sans changement de collection ni migration des donnees.
- Dependances de securite actualisees: Flask, Werkzeug, PyJWT, PyMongo, Next,
  exports PDF/Excel et dependances transitives compatibles.

## Verification

Validation locale: 144 tests backend (y compris integrations MongoDB et Redis),
15 tests unitaires frontend, deux scenarios de test en ligne, 12 controles de
pages (mobile/desktop), un parcours admin de pagination/notification/export et 156 contrats de styles clair/sombre. Les images Docker
et le compose sont verifies localement, sans acces aux serveurs Sonatel.

Les tests d'integration utilisent exclusivement des bases locales jetables
`odc_*_test_<uuid>` et des cles Redis avec un prefixe unique. Ils ne modifient
pas `odcdb` et ne contactent pas le serveur de production.

Parcours couverts: identifiants PBKDF2 existants, nouveaux mots de passe,
connexion admin/JWT, CORS, restrictions jury/creneaux, doubles soumissions,
autosave concurrent, etats terminaux de session, deduplication des invitations,
reprise d'un worker interrompu, echecs SMTP et limites Redis partagees.
Les nouveaux controles couvrent aussi 40 infractions concurrentes sans perte,
l'absence de melange d'infractions entre candidats, les notifications avec echec
fournisseur puis reprise et la confirmation tardive d'une soumission existante.
Un jeu de 225 resultats jetables couvre les pages, noms historiques de referentiel,
statuts, projections d'infractions et exports. Le navigateur verifie la selection
par page, le changement de taille, le regroupement pagine, l'export complet filtre
et la nouvelle tentative apres indisponibilite du serveur.
La regle provisoire existante pour une reponse libre non vide est conservee;
la note finale de ces reponses reste a verifier par l'equipe pedagogique.

Commandes de verification (Redis de test sur un port local dedie):

```bash
TEST_LOCAL_MONGO=1 TEST_REDIS_URL=redis://127.0.0.1:PORT/0 PYTHONWARNINGS=ignore .venv/bin/python -m unittest discover -s tests
pip-audit -r requirements.txt
```

Frontend, depuis son depot:

```bash
npm ci
node --test tests/*.test.mjs
npm run build
npm audit
```

Les regressions du navigateur (API simulee, aucun vrai candidat) se lancent
contre un frontend local deja demarre sur `127.0.0.1:3101`:

```bash
npx playwright install chromium
npm run test:online
npm run test:styles
npm run test:portal
npm run test:admin
```

Pour un autre port, fournir `ODC_BROWSER_BASE_URL`. Apres `npm run build`,
`ODC_BROWSER_START_SERVER=1 npm run test:online` demarre puis arrete lui-meme
un serveur de production local. Le workflow GitHub execute aussi ces tests.
Ils verifient notamment l'autosave pendant le chronometre, la soumission a
expiration et la conservation des reponses apres une coupure reseau.

L'installation est unifiee sur npm et `package-lock.json`. L'ancien verrou
pnpm est retire pour eviter que Vercel choisisse une autre resolution.

## Alertes et limites restantes

L'audit Python apres actualisation ne remonte aucune vulnerabilite connue
dans les dependances resolues. Ce resultat ne vaut pas audit de securite
complet de l'application.

La migration Tailwind 4.3.3 et tailwind-merge 3.7.0 retire les cinq alertes
elevees restantes de la chaine Tailwind 3. L'audit npm ne remonte aucune
vulnerabilite connue dans le verrou actuel; cela ne remplace pas un audit
complet de l'application. La palette sRGB, les bordures, ombres, largeurs et
espacements des formulaires sont conserves explicitement et couverts par des
contrats captures avant migration. Les sources CSS restent limitees aux
repertoires du projet, sans analyse automatique des documents ou donnees.

Attention a la compatibilite navigateur: Tailwind 4 necessite Safari 16.4+,
Chrome 111+ ou Firefox 128+. Ce perimetre doit etre valide avec l'equipe avant
la mise en production, notamment pour les anciens telephones des candidats.

Les essais navigateur utilisent une API simulee; ils ne remplacent pas la recette
avec Mongo et un fournisseur email reels. Les controles backend utilisent Mongo
et Redis locaux, mais le transport email y est simule pour ne contacter personne.

La vue groupee des resultats regroupe la page visible, ce qui est indique dans
l'interface. Les statistiques du tableau de bord restent globales et l'export
reste complet pour les filtres choisis. Une selection d'envoi concerne la page
visible et est remise a zero apres un changement de page ou de filtre.
La pagination utilise un offset indexe: la latence des pages tres eloignees reste
a mesurer pendant les tests de charge. Aucun chiffre de capacite n'est garanti.

Les essais automatises et Docker locaux ne prouvent pas une capacite nationale.
Il reste a valider avec l'infrastructure l'adresse HTTPS, le certificat, le
reseau Mongo, la configuration email et les quotas, la restauration des sauvegardes,
les ressources et une charge progressive sur un environnement representatif.
Les certificats et identifiants precedemment partages doivent etre proteges;
les mots de passe et cles exposes doivent etre renouveles.

La recette Windows reste necessaire: voir `WINDOWS_TEST.md`. Conserver la base
`odcdb_test` sur 27018, l'API sur 5001 et le frontend sur 3001. Le worker email
doit etre lance separement pour vider la file. Aucun ancien service n'est modifie.

Le worker est deduplique en base et ses travaux sont reserves atomiquement.
Une interruption apres acceptation du fournisseur mais avant confirmation
Mongo peut cependant provoquer une seconde livraison externe. Cette limite
est documentee, et aucun mot de passe temporaire n'est stocke dans l'outbox.
