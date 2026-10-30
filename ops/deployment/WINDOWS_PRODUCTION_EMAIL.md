# Emails sur la production Windows

Les invitations aux tests, les notifications de résultats et les confirmations
de candidature utilisent la file MongoDB `email_jobs`. La tâche
`ODC-TEST-PROD-EMAIL-WORKER` doit tourner pour que ces emails partent. L'API
seule ne suffit pas.

Après chaque release backend, ouvrir PowerShell **en administrateur** sur le
serveur et lancer le script depuis le dépôt `odc-test`:

```powershell
& "C:\Orange Digital Center\odc-test\backend\ops\deployment\register-production-email-worker.ps1"
```

Il lit la release du service API NSSM publié par IIS. En l'absence de service
NSSM, il utilise le lanceur de la tâche historique `ODC-TEST-PROD-API`.
Il crée ou actualise la tâche du worker, puis la démarre. Le worker démarre aussi après un redémarrage de
Windows et son lanceur le relance s'il s'arrête.

Vérifier l'état et le journal avec les chemins affichés par le script:

```powershell
Get-ScheduledTask -TaskName "ODC-TEST-PROD-EMAIL-WORKER" |
  Select-Object TaskName, State
Get-Content "C:\Orange Digital Center\_odc-prod-release-<release>\backend\email-worker-production.log" -Tail 30
```

Remplacer `<release>` par le nom de release ciblée. Une seule tâche worker est
prévue sur ce serveur. Le script n'envoie pas de mail de test; il traite les
messages réellement présents dans la file. Vérifier séparément la livraison
avec une adresse interne autorisée avant l'ouverture des inscriptions.
