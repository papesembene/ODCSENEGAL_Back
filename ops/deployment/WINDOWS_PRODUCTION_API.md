# API de production Windows / IIS

État vérifié le 30 octobre 2026 : service automatique `ODC-PROD-API`,
API sur `127.0.0.1:5003`, code dans `odc-test/backend`. La configuration
privée reste `odc-test/backend/.env.production`. Les deux règles IIS API
pointent vers ce service. Le frontend reste sur le port 3005.

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
exécuter `C:\Orange Digital Center\deploy-backend-production.ps1` en
administrateur. Le script prépare une release et un environnement Python
séparés, conserve les uploads, valide le service candidat, puis bascule IIS.
Il alterne entre `ODC-PROD-API` et `ODC-PROD-API-SECONDARY`.

Si une mise à jour concerne le worker email, utiliser ensuite
`register-production-email-worker.ps1`. Il lit désormais la release NSSM
publiée plutôt que la tâche API historique.

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

Les anciens guides de configuration et résultats de charge ont été déplacés
dans `C:\Orange Digital Center\_documents_archives_20261030`. L'historique Git
conserve leurs anciennes versions. Les instructions historiques qui décrivent
une API encore publiée par tâche Windows sont dépassées par ce document.
