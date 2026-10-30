# Emails sur la production Windows

Les invitations aux tests, les notifications de résultats et les confirmations
de candidature utilisent la file MongoDB `email_jobs`. La tâche
`ODC-TEST-PROD-EMAIL-WORKER` doit tourner pour que ces emails partent. L'API
seule ne suffit pas.

Le déploiement backend aligne et redémarre désormais ce worker automatiquement.
Il n'y a plus de deuxième commande à lancer après une release. Pour une
intervention email seule, ouvrir PowerShell **en administrateur** :

```powershell
& "C:\Orange Digital Center\odc-test\backend\ops\deployment\register-production-email-worker.ps1"
```

Il lit la release du service API NSSM publié par IIS, demande l'arrêt du worker
précédent avec une grâce de 60 secondes, vérifie les processus concernés et
relance la tâche sur la version publiée. Le worker démarre aussi après un redémarrage de
Windows et son lanceur le relance s'il s'arrête.

Vérifier l'état et le journal avec les chemins affichés par le script:

```powershell
Get-ScheduledTask -TaskName "ODC-TEST-PROD-EMAIL-WORKER" |
  Select-Object TaskName, State
. "C:\Orange Digital Center\ops\backend-recovery\BackendService.Common.ps1"
$api = Get-PublishedBackendNssmContext
Get-Content (Join-Path $api.Logs 'email-worker.stderr.log') -Tail 30
```

Une seule tâche worker est
prévue sur ce serveur. Le script n'envoie pas de mail de test; il traite les
messages réellement présents dans la file. Vérifier séparément la livraison
avec une adresse interne autorisée avant l'ouverture des inscriptions.
