# Preparation du deploiement Sonatel

## Ce qui est fourni

`compose.production.yml` lance le frontend Next en mode production, l'API
Waitress, Redis et un worker email independant. Les deux applications
s'executent sans compte root. MongoDB reste un service d'infrastructure distinct.
Le monitoring technique existant est facultatif et n'est pas lance ici.

Le seul port publie est `127.0.0.1:8085`, sur le serveur Docker. Aucun port MongoDB,
Redis, API ou frontend n'est ouvert publiquement. Ce compose cible Linux avec
Docker Engine et Compose v2+, pas l'ancien dossier de production Windows.
Pour la recette Windows deja en place, suivre `WINDOWS_TEST.md` sans Docker.

## Avant de lancer

1. Faire confirmer par l'equipe infrastructure le serveur cible, les ressources,
   Docker, les droits, les sauvegardes et la connexion au serveur MongoDB.
2. Garder l'ancien service et sa base en place. Utiliser une base de test dediee
   pour la recette; la nouvelle base annuelle de production doit etre validee.
   Ne pas reimporter les anciens candidats sans decision metier et sauvegarde.
3. Cloner les deux depots cote a cote sous les noms `backend` et `frontend`, en
   choisissant les commits valides. Ne pas modifier les variables de l'ancien service.
4. Faire fournir un nom HTTPS de recette. Identifier le point d'entree TLS
   (IIS, Nginx ou equipement reseau), y installer le certificat fourni avec les
   droits necessaires, puis rediriger vers le port local 8085. Coordonner cette
   operation avec l'infrastructure. Si le proxy est sur une autre machine,
   adapter l'ecoute et le pare-feu avec elle, sans exposer HTTP a Internet.

Le meme gateway accepte le domaine portail et le domaine API si l'infrastructure
utilise deux noms. Tous deux doivent pointer vers lui. Les redirections OAuth
Google/LinkedIn sont a confirmer selon les fonctions activees.

## Configuration

Creer hors Git `/etc/odc/new.env` a partir de `.env.production.example`, avec des
droits `600`. Renseigner les vraies valeurs, sans les envoyer dans une discussion.
Generer **deux secrets distincts** avec `openssl rand -hex 32`. Les anciens secrets
partages dans des messages doivent etre renouveles avant ouverture publique.

`MONGO_URI` et `MONGO_DBNAME` doivent viser la meme base. Utiliser un utilisateur
dedie autorise uniquement sur cette base, pas le compte administrateur MongoDB.
Les donnees persistantes sont les volumes d'uploads, Redis et la base MongoDB.

Choisir explicitement `EMAIL_PROVIDER=brevo`, `brevo_smtp`, `sendgrid` ou `smtp`.
Pour le relais de l'ancienne version, recuperer uniquement sa configuration email
autorisee: serveur, port, TLS/SSL, expediteur et identifiants. Avec Brevo HTTP,
utiliser une cle API (pas une cle `xsmtpsib`) et autoriser l'IP sortante du serveur.
La presence des variables ne prouve pas que le fournisseur acceptera l'envoi.

Verifier separement les integrations optionnelles utilisees dans l'ancien
portail (Google/LinkedIn, chatbot). Le chatbot actuel lit une cle Gemini cote
navigateur; ce modele de deploiement n'injecte volontairement aucune cle IA
publique. Si cette fonction est utilisee, prevoir un appel cote serveur et
sa recette avant de l'activer, plutot que copier une cle dans `NEXT_PUBLIC_*`.

Les `NEXT_PUBLIC_*` sont integrees a l'image frontend a la construction: apres un
changement d'adresse API, reconstruire l'image. Aucune cle email dans le frontend.
`npm ci` et `package-lock.json` sont utilises pour la construction Docker.

Depuis le dossier `backend`:

```bash
export ODC_ENV_FILE=/etc/odc/new.env
docker compose --env-file "$ODC_ENV_FILE" -f compose.production.yml config --quiet
docker compose --env-file "$ODC_ENV_FILE" -f compose.production.yml build
docker compose --env-file "$ODC_ENV_FILE" -f compose.production.yml up -d redis
docker compose --env-file "$ODC_ENV_FILE" -f compose.production.yml run --rm api python preflight.py
```

Le preflight verifie les configurations et les connexions sans ecrire de donnees
ni envoyer de mail. Puis creer les index declares, une seule fois avant ouverture:

```bash
docker compose --env-file "$ODC_ENV_FILE" -f compose.production.yml run --rm api python ensure_critical_indexes.py
docker compose --env-file "$ODC_ENV_FILE" -f compose.production.yml up -d
docker compose --env-file "$ODC_ENV_FILE" -f compose.production.yml ps
docker compose --env-file "$ODC_ENV_FILE" -f compose.production.yml logs --tail=100 api email-worker gateway
curl --fail http://127.0.0.1:8085/health
```

Une erreur de creation d'index unique peut signaler des doublons existants:
ne pas supprimer de documents ou d'index automatiquement pour la contourner.
Ne jamais lancer les scripts de seed ou de charge sur les vraies donnees.

## Invitations et reprise apres incident

En production, un envoi de groupe cree des travaux durables dans MongoDB et
repond `202`: **pris en charge**, pas deja livre. Le worker accepte au maximum
un envoi par seconde par defaut. Adapter `EMAIL_SEND_INTERVAL_SECONDS` au quota
du fournisseur; multiplier les workers multiplie aussi le debit total.
50000 invitations a un envoi/seconde prennent environ 14 heures: preparer les
groupes en avance ou faire augmenter le quota, pas les lancer au dernier moment.

Le suivi est dans la fenetre d'invitations du groupe. Les envois acceptes ne sont
pas reemis lors d'un second clic; seuls les echecs peuvent etre relances. Les
erreurs temporaires sont retentees avec delai et limite. Un groupe annule,
modifie ou termine ne doit plus declencher ses anciens travaux. Les mots de
passe temporaires ne sont jamais stockes dans cette file.

La livraison externe est **au moins une fois**, pas exactement une fois: si le
processus s'arrete apres acceptation du fournisseur mais avant confirmation en
base, une reprise peut renvoyer l'invitation. Aucun mail accepte ne garantit une
reception en boite principale. Tester avec un destinataire autorise en recette.

Les notifications des resultats utilisent le meme worker et la meme limite de
debit. Depuis Resultats, selectionner au maximum 500 lignes puis "Notifier la
selection". Le suivi reste dans le dialogue; les echecs seuls peuvent etre
relances. Les destinataires et scores sont lus en base, pas fournis librement
par le navigateur. Ces messages ne changent aucune decision finale d'admission.

## Tests obligatoires avant bascule

- Candidature, connexion admin/jury, permissions par role et creneau.
- Test candidat: connexion, brouillon, reconnexion, expiration, soumission.
- Couper l'API pendant la soumission, la redemarrer puis reessayer: un resultat.
- Invitations: destinataire reel, echec fournisseur et reprise du worker.
- Upload d'image puis recreation des conteneurs: le fichier reste accessible.
- Verifier HTTPS, CORS, liens email et absence d'URL localhost dans le navigateur.
- Executer une charge progressive sur la recette dimensionnee comme la cible,
  avec donnees jetables et accord infrastructure. Le compose ne garantit pas
  a lui seul des milliers de connexions simultanees.

Pour plusieurs API, les sessions et limites sont partagees via Redis. Le budget
Mongo total vaut environ `replicas API x MONGO_MAX_POOL_SIZE + workers x 10`.
Augmenter les replicas seulement apres mesures CPU/RAM, latences p95/p99,
connexions Mongo, taux d'erreur et temps de sauvegarde. Conserver une seule
instance frontend tant que le cache et les constructions Next multi-instance
ne sont pas coordonnes. Ne pas saturer le serveur avec un nombre de threads
arbitrairement eleve.

Le proxy TLS doit **ecraser**, et non faire confiance aux en-tetes fournis par
le client: `Host`, `X-Forwarded-For`, `X-Forwarded-Proto`. L'API n'est joignable
que sur le reseau Docker. `/metrics` est bloque sur le gateway public.

## Bascule et retour arriere

Valider d'abord la recette, puis convenir d'une fenetre sans test en cours.
Sauvegarder MongoDB et les volumes d'uploads, et tester leur restauration.
Conserver les anciens binaires/images et la configuration hors Git. Rediriger
ensuite le proxy vers la nouvelle version avec l'equipe infrastructure.
Le frontend et le backend doivent etre publies ensemble: le contenu candidat
utilise maintenant un endpoint controle distinct du detail administratif.

En cas d'incident, revenir a l'ancien routage selon le plan valide. Les donnees
recues entre-temps dans la nouvelle base ne se retrouvent pas automatiquement
dans l'ancienne: prevoir leur reconciliation. Ne pas supprimer les volumes,
la nouvelle base ou les anciens services pour revenir en arriere.
