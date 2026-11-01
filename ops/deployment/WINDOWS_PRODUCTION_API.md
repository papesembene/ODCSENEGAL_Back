# API de production Windows / IIS

IIS publie l'un des services automatiques `ODC-PROD-API` ou
`ODC-PROD-API-SECONDARY`. Le chemin et le port changent selon les déploiements ;
`Get-PublishedBackendNssmContext` les lit dans la configuration réelle.
La configuration privée reste `odc-test/backend/.env.production`.
Le frontend est déployé indépendamment.

La tâche historique `ODC-TEST-PROD-API` est désactivée. Ne pas la réactiver
pour dépanner le service. Le worker email reste une tâche séparée et utilise
le même backend. Aucun message de test n'a été envoyé.

## Vérification et reprise

Dans PowerShell administrateur :

```powershell
. 'C:\Orange Digital Center\ops\backend-recovery\BackendService.Common.ps1'
$api = Get-PublishedBackendNssmContext
$api | Select-Object Name, Backend, Port
Get-Service -Name $api.Name
Test-BackendHealth -Port $api.Port
Get-ScheduledTaskInfo -TaskName ODC-TEST-PROD-API-WATCHDOG |
    Select-Object LastRunTime, LastTaskResult, NextRunTime
Get-Content 'C:\Orange Digital Center\ops\backend-recovery\state\watchdog.log' -Tail 20
curl.exe --fail --max-time 15 https://api.orangedigitalcenter.sn/health
curl.exe --fail --max-time 15 https://orangedigitalcenter.sn/api/health
```

Le contrôle HTTP s'exécute chaque minute et au démarrage. Il ne redémarre
pas une API qui répond et signale une dépendance MongoDB indisponible.
Il refuse d'intervenir sur un processus dont le service ne possède pas le port.

## Déploiements suivants

Enregistrer les changements du backend dans Git, vérifier les tests, puis
exécuter cette seule commande dans PowerShell administrateur :

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Orange Digital Center\deploy-backend-production.ps1"
```

Le script prépare une release et un environnement Python
séparés, conserve les uploads, valide le service candidat, puis bascule IIS.
Il alterne entre `ODC-PROD-API` et `ODC-PROD-API-SECONDARY`.

Le worker email est automatiquement aligné et redémarré sur la release publiée.
Les nouveaux workers terminent leur travail courant lorsqu'un arrêt est demandé.
Une grâce de 60 secondes est prévue avant l'arrêt d'un ancien processus vérifié.
Si une interruption survient pendant un envoi, la file peut retenter un travail
après expiration de son verrou ; la livraison n'est pas garantie exactement une fois.
L'ancienne API dispose d'un drainage borné à 120 secondes avant arrêt du service
non publié. Une connexion encore active après ce délai peut être interrompue.

Après réussite, le nettoyage conserve la release active et la précédente de
chaque composant, trois configurations de déploiement et trois configurations
de watchdog. Trois configurations de tentatives incomplètes sont également
conservées pour le diagnostic. Les releases gérées d'essais échoués et non
référencées sont retirées au prochain nettoyage après réussite.
Un service, une tâche (même désactivée), un processus ou une jonction
encore référent empêche la suppression. Les dossiers historiques non gérés et
les anciennes sauvegardes de données ne sont pas effacés automatiquement.
Les scripts complets sont suivis dans `ops/deployment/Deploy-*Production.ps1` ;
les deux commandes à la racine du workspace sont de petits lanceurs.

Une tâche `ODC-PROD-DATA-BACKUP` effectue séparément une sauvegarde locale à
02:30 UTC chaque jour et conserve sept copies réussies (plus deux tentatives
incomplètes au maximum). Elle inclut MongoDB,
les uploads canoniques et le fichier privé de configuration de l'API. Les copies
sont dans `archives/donnees-quotidiennes`, accessibles uniquement à SYSTEM et
aux administrateurs. L'export MongoDB est un dump logique en ligne sans oplog,
pas un instantané transactionnel global. Les CRC gzip/ZIP et les SHA-256 sont
vérifiés/enregistrés ; un véritable exercice de restauration reste distinct.
Les sauvegardes partagent le disque du serveur : aucune copie hors serveur
n'est configurée tant qu'une destination externe n'a pas été fournie.

Pour contrôler cette automatisation :

```powershell
Get-ScheduledTaskInfo -TaskName ODC-PROD-DATA-BACKUP |
    Select-Object LastRunTime, LastTaskResult, NextRunTime
```

Le résultat attendu après exécution est `0`. La sauvegarde et les déploiements
partagent un verrou ; une sauvegarde différée retente après 15 minutes.

## Migration et retour arrière

`Migrate-BackendToNssm.ps1` effectue la migration initiale de la tâche
historique vérifiée vers NSSM. Ne pas le relancer après une migration réussie.
La migration n'installe pas de dépendances et ne déplace aucune donnée MongoDB.

Sauvegarde de la migration réussie :
`C:\Orange Digital Center\ops\backend-recovery\backups\migration-20261030T194519583`.
Elle contient les deux configurations IIS, la définition de la tâche historique
et les informations de ports/processus. Les sauvegardes des tentatives précédentes
sont conservées également.

Pour revenir à la tâche historique, vérifier d'abord que son ancien port 5002
est libre ou possède toujours son processus attendu. Réactiver et démarrer la
tâche uniquement si nécessaire, puis confirmer sa santé locale. Remettre ensuite
uniquement les cibles des deux règles API sur 5002, en préservant les autres
réglages IIS. Vérifier les deux accès publics avant d'arrêter le service retiré.
Le watchdog NSSM doit être désactivé lors de ce retour à la tâche historique.

Les guides historiques décrivant une API publiée par tâche Windows, les anciennes
commandes annuelles et le bilan de charge de juin ont été retirés du workspace
car ils ne décrivent plus le fonctionnement actuel. L'historique Git conserve
les documents qui étaient suivis. Le schéma MongoDB, la checklist de vérification
et la roadmap ont été retirés du workspace.
Ce document est la référence pour l'exploitation de l'API NSSM.
