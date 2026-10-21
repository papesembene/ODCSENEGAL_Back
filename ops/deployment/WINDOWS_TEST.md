# Verification de la nouvelle version sur Windows

Ce guide concerne uniquement `C:\Orange Digital Center\odc-test`.
Ne pas modifier `odcdeploye`, l'API historique sur 5000 ni sa base.
Ces instructions sont preparees depuis Linux; leur execution sur votre serveur
Windows reste a verifier avec vous. Ce n'est pas le deploiement de production.

## Avant la mise a jour

Noter les commits frontend/backend actuellement testes et conserver une copie
privee des fichiers `.env` et `.env.local`, hors des depots. Ne pas publier ces
fichiers. Faire une sauvegarde Mongo si les donnees de test doivent etre gardees.

Dans chaque depot, `git status --short` doit etre controle avant tout pull.
Ne pas ecraser des modifications locales ou faire de `reset --hard`.
Apres publication et validation du code seulement, utiliser `git pull --ff-only`.

Pre-requis: Node 22+, Python 3.12 et le service `ODCTestMongo` actif. La base
de test reste `odcdb_test` sur `127.0.0.1:27018`; ne jamais remplacer cette URI
par celle de l'ancienne production.

```powershell
Get-Service ODCTestMongo
Test-NetConnection 127.0.0.1 -Port 27018
```

## API de test

Arreter seulement le processus de la nouvelle API dans son terminal (Ctrl+C).
Dans le dossier backend de test, installer les dependances:

```powershell
Set-Location "C:\Orange Digital Center\odc-test\backend"
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Le `.env` de CE dossier doit conserver au minimum ces valeurs locales:

```dotenv
MONGO_URI=mongodb://127.0.0.1:27018/odcdb_test
MONGO_DBNAME=odcdb_test
FLASK_ENV=development
HOST=127.0.0.1
PORT=5001
FRONTEND_URL=http://localhost:3001
CORS_ALLOWED_ORIGINS=http://localhost:3001
SESSION_TYPE=filesystem
REDIS_URL=
EMAIL_DELIVERY_MODE=queued
```

Ne pas supprimer les autres valeurs requises, notamment les secrets applicatifs
et les parametres email. Aucun secret ne doit etre copie dans Git.
Le frontend sera consulte dans le navigateur du serveur Windows via localhost;
pour un acces distant, les URL et origines doivent etre adaptees ensemble.

```powershell
.\.venv\Scripts\python.exe run.py
```

## Worker email

Ouvrir un DEUXIEME terminal dans le meme backend, avec le meme `.env`:

```powershell
Set-Location "C:\Orange Digital Center\odc-test\backend"
.\.venv\Scripts\python.exe email_worker.py
```

Sans ce processus, les emails en file restent en attente: les invitations de
groupe en mode queued ET les notifications de resultats utilisent cette file.
Le suivi distingue attente, acceptation par le fournisseur et echec. Il ne
garantit pas l'arrivee dans la boite principale du destinataire.
Les emails de jury et autres parcours existants gardent leur transport actuel.
Verifier l'expediteur autorise, les quotas et l'IP de sortie dans Brevo.

## Frontend de test

Arreter seulement le frontend de test, puis dans un TROISIEME terminal:

```powershell
Set-Location "C:\Orange Digital Center\odc-test\frontend"
npm ci
```

Dans `.env.local`, garder `NEXT_PUBLIC_API_URL=http://localhost:5001`.
Cette valeur est integree au build: changer le fichier seul ne suffit pas.

```powershell
npm run build
npm run start -- -p 3001
```

Ouvrir `http://localhost:3001`. `npm run dev -- -p 3001` reste possible pour
le travail de developpement, mais ne sert pas a mesurer la capacite en production.
Ne jamais lancer build et dev simultanement dans le meme dossier `.next`.

## Parcours de verification

1. Connexion super admin, puis connexion jury avec un compte de test existant.
2. Candidature de test, groupe, invitation et lien du candidat.
3. Connexion candidat, reponses, brouillon et soumission normale.
4. Coupure de la nouvelle API pendant la soumission, redemarrage et nouvelle
   tentative: aucune perte de reponses ni double resultat.
5. Un resultat enregistre reste confirmable apres l'echeance; une premiere
   soumission hors delai conserve son brouillon et n'invente pas un resultat.
6. Filtreur limite au creneau courant, validateur autorise selon ses affectations;
   aucune modification de la section d'un autre jury.
7. Infractions de chaque candidat distinctes, notification des resultats et suivi
   du worker; ne selectionner que des adresses de test dont on a l'autorisation.
8. Resultats admin: passer aux pages suivantes, filtrer par referentiel et statut,
   verifier les totaux globaux et exporter les resultats filtres (pas seulement
   la page visible). La selection est limitee a la page en cours.

La charge doit ensuite etre testee progressivement sur l'environnement cible,
avec accord de l'infrastructure. Ces parcours ne prouvent pas une capacite nationale.
