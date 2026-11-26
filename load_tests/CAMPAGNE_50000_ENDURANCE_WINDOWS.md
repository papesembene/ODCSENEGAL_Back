# Campagne : 50 000 dossiers, pic de 3 000, puis une heure reguliere

## Protocole

Le lanceur cree une nouvelle API et une nouvelle instance MongoDB privees,
sur 127.0.0.1. Aucun fichier .env, compte, base ou service de production n'est
utilise. Il n'existe aucun parametre d'URL distante dans ce protocole.

1. Precharger **50 000 candidatures fictives** directement dans la base jetable.
   Les documents passent la validation du modele Candidature et les index du
   modele sont crees. Le prechargement ne passe pas par le service d'envoi de
   confirmation et doit laisser zero email en file.
2. Verifier un parcours avec un candidat supplementaire distinct.
3. Mesurer **3 000 nouvelles inscriptions sur 60 secondes**, arrivees progressives.
4. Si le pic respecte les controles, mesurer **une nouvelle inscription par
   seconde pendant une heure**, soit 3 600 nouveaux candidats distincts.

Le rythme d'une inscription par seconde est une hypothese exploratoire,
environ douze fois la moyenne de 50 000 candidatures reparties uniformement
sur sept jours. Ce n'est pas une prevision du trafic reel. Le pic reprend
les 50 inscriptions/seconde de l'essai precedent, avec une base deja remplie.

En cas de reussite, le total final est **56 601 candidats** : 50 000 precharges,
un controle, 3 000 au pic et 3 600 pendant l'heure. Il doit y avoir **6 601
confirmations non traitees** dans la file temporaire, aucune pour le prechargement.
Le nombre de candidatures prechargees doit rester egal a 50 000 a chaque phase.

Le test regulier utilise au plus 32 clients JMeter qui effectuent des parcours
successifs avec de nouvelles identites. Il ne cree pas 3 600 threads gardes
ouverts pendant une heure. Les dates d'arrivee sont planifiees et le debit
observe est rapporte. La duree entre premiere et derniere arrivee doit rester
dans une tolerance de 5 % (ou 2 secondes pour les validations tres courtes).

## Commande PowerShell

```powershell
Set-Location 'C:\ODC-Charge\backend'
& '.\.venv\Scripts\python.exe' load_tests\jmeter_isolated.py `
  --mongod 'C:\ODC-Charge\MongoDB\mongodb-win32-x86_64-windows-8.0.34\bin\mongod.exe' `
  --jmeter 'C:\ODC-Charge\apache-jmeter-5.6.3\bin\jmeter.bat' `
  --scenario registration --levels 3000 --threads 32 `
  --registration-arrival progressive --ramp 60 --max-p95-ms 3000 `
  --preload-candidates 50000 --endurance-seconds 3600 --endurance-rate 1
```

Prevoir environ une heure et quelques minutes, preparation et rapports compris.
La console annonce le debut et la fin du prechargement, puis les phases.
Pendant l'endurance, un compteur s'affiche toutes les 30 secondes. Ne lancer
aucun autre test de charge en parallele. Ctrl+C interrompt les phases suivantes
et arrete les processus temporaires ; les rapports restent disponibles.

## Criteres et protections

- Zero erreur HTTP ou assertion ; une seule inscription par identite attendue.
- p95 <= 3 secondes sur statut de campagne, unicite et POST de candidature.
- Pendant l'endurance, le meme objectif est aussi verifie dans chaque tranche
  de cinq minutes afin qu'un percentile global ne masque pas une degradation.
- Nombre exact de nouveaux emails et numeros de piece distincts en base.
- Total des confirmations coherent ; toutes pending et attempts=0.
- Aucun worker email lance ; transport email, SMTP et connexions externes
  de l'application temporaire bloques.
- CPU global > 85 % pendant environ une seconde : arret. Premiere erreur : arret.
- Chaque execution JMeter est bornee ; avec l'heure demandee, limite a 3 900 s.
- Nombre de dossiers precharges <= 75 000 et nouvelles candidatures mesurees
  <= 10 000 par lancement. Prechargement/endurance reserves aux candidatures.

## Rapports

Le dossier affiche sous Rapports contient :

- summary.json : phases, verdicts, debit observe, integrite et nettoyage ;
- resources.csv : horodatage UTC et phase, CPU et RSS de l'API, MongoDB et JMeter,
  CPU global et pourcentage de memoire systeme, echantillonnes environ toutes
  les 250 ms. Le fichier est conserve aussi si la mesure echoue ;
- les JTL, JMX, journaux et rapports HTML de chaque phase ;
- preload.json : volume et collection de prechargement, sans donnees reelles.

Le JSON de l'endurance contient les cinq_minute_buckets sous la cle
five_minute_buckets. La console n'affiche que leur nombre pour rester lisible.
Le champ users de cette phase correspond aux clients simultanes (32) et
journeys aux nouveaux candidats (3 600). Les compteurs de candidatures sont
verifies avec journeys. A la fin, cleanup_complete doit etre true.

## Limites

Il s'agit d'un jeu synthetique : un referentiel Dev Web, champs textes courts,
format de formulaire fixe, dates reparties sur sept jours. Ce n'est pas une
copie statistique de toutes les candidatures reelles ni une reconstitution de
sept jours d'utilisation. Les envois effectifs d'emails, uploads, frontend,
IIS, HTTPS, reseaux candidats et integrations externes restent exclus.

Le cache WiredTiger du MongoDB temporaire reste fixe a 256 Mo, comme dans les
essais precedents. JMeter partage la machine avec l'API : utiliser les traces
separees pour comprendre les pics avant d'attribuer une saturation a l'application.
Une repetition depuis un autre generateur et via l'entree web de recette sera
necessaire pour extrapoler a la production.

La validation locale du lanceur utilise bien les 50 000 documents mais reduit
le pic et la duree reguliere ; elle ne remplace pas l'heure de mesure Windows.
