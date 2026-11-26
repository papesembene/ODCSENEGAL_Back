# Pic de 3 000 candidatures en une minute

Pour refaire ce pic avec 50 000 dossiers deja presents puis une heure de charge,
suivre `CAMPAGNE_50000_ENDURANCE_WINDOWS.md`.

Ce scenario mesure les inscriptions, independamment des epreuves en ligne.
Il ouvre une campagne fictive uniquement dans la base temporaire et effectue
trois requetes par candidat : statut de campagne, unicite de l'email, candidature.
Il ne lance aucune requete de test, ne cree pas de groupe d'epreuve et n'utilise
aucune donnee ou configuration de production.

## Protocole propose

- 3 000 candidats fictifs **au total**, arrives progressivement sur 60 secondes,
  soit un rythme vise d'environ 50 nouvelles candidatures par seconde.
- Une seule inscription par candidat ; pas de boucle d'inscriptions infinie.
- Un controle a un candidat precede la mesure, avec une identite distincte.
- API temporaire a 32 threads et MongoDB temporaire sur le meme serveur.
- Objectif exploratoire annonce : p95 <= 3 secondes pour chacune des trois
  operations, aucune erreur HTTP ou assertion, compteurs et identites coherents.

Ce protocole ne correspond pas a 3 000 POST simultanes. Les anciens essais
d'inscription avaient une barriere liberant toutes les soumissions ensemble ;
leurs percentiles ne sont pas directement comparables. L'option burst reste
disponible pour un autre essai explicitement synchronise.

## Execution dans PowerShell

```powershell
Set-Location 'C:\ODC-Charge\backend'
& '.\.venv\Scripts\python.exe' load_tests\jmeter_isolated.py `
  --mongod 'C:\ODC-Charge\MongoDB\mongodb-win32-x86_64-windows-8.0.34\bin\mongod.exe' `
  --jmeter 'C:\ODC-Charge\apache-jmeter-5.6.3\bin\jmeter.bat' `
  --scenario registration --levels 3000 --threads 32 `
  --registration-arrival progressive --ramp 60 --max-p95-ms 3000
```

La limite de 3 000 est reservee au mode registration ; les epreuves restent
limitees a 2 000. Les protections CPU, premiere erreur, delai maximal et les
garanties d'isolation sont conservees.

## Donnees et emails

En cas de reussite, data_checks doit annoncer 3 000 candidats, emails et
numeros de piece distincts pour le palier. Le total en base et le nombre de
confirmations en file valent 3 001, en comptant le controle initial. Chaque
confirmation doit rester pending avec attempts=0 ; aucun worker n'est lance.
Le transport email et les connexions SMTP/externes de l'application temporaire
restent bloques.

Les candidats et la file sont supprimes avec la base temporaire apres arret
des processus crees. Le summary.json indique cleanup_complete. Les JTL,
journaux et rapports HTML sont conserves dans le dossier affiche sous Rapports.

Une reussite valide ce pic de debit sur une base initialement vide, pas les
50 000 candidatures d'une semaine. Un essai avec une base fictive deja remplie,
une charge soutenue, le frontend/IIS/HTTPS et un generateur distinct restent
necessaires pour extrapoler la capacite du site complet. Les livraisons
effectives d'emails ne sont pas mesurees.
