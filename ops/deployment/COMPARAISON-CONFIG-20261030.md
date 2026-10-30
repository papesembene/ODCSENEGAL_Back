# Configuration du backend verifiee le 30 octobre 2026

Le backend publie est `odc-test/backend`, execute par la tache Windows
`ODC-TEST-PROD-API`. Son lanceur est
`_odc-prod-release-20261026/start-api-production.ps1`. IIS transmet les requetes
API a `127.0.0.1:5002`. Le lanceur impose `FLASK_ENV=production`,
`HOST=127.0.0.1`, `PORT=5002` et `ODC_ENV_FILE=odc-test/backend/.env.production`.
Le port 5001 du fichier ne remplace donc pas le port impose par le lanceur.

| Point | Ancienne version odcdeploye | Version publiee odc-test / decision |
| --- | --- | --- |
| MongoDB | URI historique | Meme URI; base explicite odcdb conservee |
| Candidatures | Collection historique | candidatures_2026 conservee, campagne 2026 |
| Pool par processus | Maximum 250, minimum 20 | Maximum 50, minimum 0, reglables; conserver avant mesure de charge |
| Configuration | .env et valeurs par defaut | .env.production explicite, validation des secrets et de la base |
| Sessions | Fichiers | Fichiers conserves pour cette API unique; Redis requis si plusieurs instances |
| Emails | Identifiants SendGrid presents | Memes identifiants SendGrid, file durable et worker distinct conserves |
| Origines navigateur | Configuration historique | Origine HTTPS explicite du portail |
| OAuth | Callbacks HTTP sur IP et port 5000 | Valeurs heritees identiques; a aligner avec les inscriptions Google/LinkedIn avant modification |

## Correction appliquee

Un seul fichier d'environnement est charge au demarrage de l'API et du worker.
Le fichier indique par ODC_ENV_FILE ne recoit plus de valeurs complementaires
du .env de developpement. Un fichier explicite absent bloque le demarrage.
La lecture UTF-8 avec BOM est prise en charge, car .env.production contient un
BOM Windows. Les variables imposees par le service gardent la priorite.
Le .env local, les donnees, les secrets et l'ancienne version restent inchanges.

## Verification

- 15 tests reussis: production_runtime, email_transport, observability.
- preflight.py avec ODC_ENV_FILE de production: validation et ping MongoDB OK;
  configuration SendGrid presente. Aucun email de test envoye.
- Tache API rechargee; /health local sain, environnement production et MongoDB up.
- Worker email constate Running; reception effective des emails non testee.

Les callbacks OAuth restent un point de recette: changer seulement les URL du
backend sans verifier les URL autorisees chez les fournisseurs peut casser la
connexion. Aucune capacite de milliers de candidats n'est deduite de ces controles.
