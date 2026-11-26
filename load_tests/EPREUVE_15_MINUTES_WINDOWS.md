# Epreuve commune de 15 minutes — premier essai a 2 000 candidats

Ce scenario utilise toujours une API et un MongoDB temporaires, prives, sur
127.0.0.1, sans configuration ni donnees de production et avec les emails
bloques. Il ne lance aucun service permanent et ne modifie pas IIS.

## Protocole

- Controle fonctionnel accelere : un candidat distinct, quelques secondes,
  avec acces, lecture du brouillon, sauvegardes et soumission.
- Preparation du vrai creneau : le test fictif est configure pour **15 minutes**,
  avec une ouverture alignee sur une minute du serveur. L'API temporaire est
  redemarree apres configuration du creneau pour renouveler le cache chauffe
  par le controle initial. Les metadonnees 15 minutes sont confirmees par HTTP
  avant toute charge. Une attente de 60 a 120 secondes laisse a JMeter le temps
  de preparer ses utilisateurs.
- Entree des 2 000 candidats sur 60 secondes a partir de cette ouverture.
  Metadonnees, verification email/telephone et questions sont charges.
- Lecture du brouillon initial puis sauvegarde initiale.
- Sessions actives jusqu'a la fin **commune** du creneau. Le candidat qui entre
  a la fin de la montee dispose donc d'environ 14 minutes, comme dans la logique
  actuelle du backend qui utilise une heure de fin commune.
- Sauvegardes forcees toutes les 90 secondes, comme dans le frontend.
  Hypothese d'activite : une reponse modifiee toutes les 30 secondes, sauvegardee
  apres le delai de 1,2 seconde du frontend. Une sauvegarde forcee qui contient
  deja le changement evite un second envoi du meme changement immediatement apres.
  Les temporisations manquees ne sont pas rejouees en rafale si le serveur ralentit.
- A la fin commune, soumissions etalees sur 10 secondes. Les reponses envoyees
  sont exactement les dernieres reponses sauvegardees par chaque candidat.
  L'appel secondaire update-status du frontend est aussi effectue apres le POST.

Les nouveaux brouillons s'arretent **10 secondes avant la cloture** (delai de
reponse frontend de 8 secondes + marge de 2 secondes). Les sessions restent
presentes jusqu'a la fin des 15 minutes et les soumissions partent toujours a
la vraie echeance. Aucune reponse 403 n'est acceptee ou masquee. Cette reserve
est un choix du protocole de mesure ; le frontend actuel peut encore avoir une
sauvegarde en transit a la cloture. Les changements de reponse dans ces dix
dernieres secondes ne sont pas simules par ce profil.

L'essai precedent a 1 000 candidats a rencontre un brouillon refuse a la
cloture avec 403 "Test non accessible" apres pres de 28 000 sauvegardes. Ce
cas doit rester dans le bilan comme cas limite de fin de creneau. Il ne valide
ni les soumissions finales ni une perte de donnees. Il est distinct des
timeouts de sauvegarde observes pendant l'arrivee des 2 000 candidats.

Les reponses evoluent entre les sauvegardes. Le fichier JTL conserve leur
version attendue pour chaque candidat. A la fin, le lanceur verifie que les
resultats et les sessions submitted contiennent bien cette derniere version,
sans candidat manquant, inattendu ou en double.

Les delais de reponse sont ceux du frontend pour les brouillons (8 s), l'acces
(15 s), le contenu et la soumission (20 s), et le statut final (10 s).
Le scenario ne retente pas automatiquement les requetes : la premiere erreur
est visible et arrete la charge. Il ne simule pas toutes les fonctions navigateur
(localStorage, anti-triche, perte reseau, reprise apres panne ou affichage Next.js).

## Lancer depuis PowerShell

```powershell
Set-Location 'C:\ODC-Charge\backend'
& '.\.venv\Scripts\python.exe' load_tests\jmeter_isolated.py `
  --mongod 'C:\ODC-Charge\MongoDB\mongodb-win32-x86_64-windows-8.0.34\bin\mongod.exe' `
  --jmeter 'C:\ODC-Charge\apache-jmeter-5.6.3\bin\jmeter.bat' `
  --scenario exam15 --levels 2000 --threads 16
```

Le lancement dure environ 17 a 20 minutes si les protections ne l'arretent pas.
Une progression est affichee toutes les 30 secondes : temps jusqu'a la fin,
acces, sauvegardes periodiques et soumissions. Il est normal que les soumissions
restent a zero pendant l'epreuve.

La limite d'execution de chaque processus JMeter est portee a 30 minutes pour
ce mode. Le controle a un candidat est accelere et **ne remplace pas** les
15 minutes du palier de 2 000. Ctrl+C interrompt et nettoie les processus du
lanceur. Ne pas fermer brutalement la session ou eteindre le serveur.

## Criteres

- Zero erreur HTTP ou assertion ; chaque acces et soumission attendus une fois.
- p95 de la connexion complete <= 3 s.
- p95 des sauvegardes initiales et periodiques <= 3 s.
- p95 de la soumission finale <= 5 s.
- Reponses identiques entre derniere sauvegarde attendue, resultat et session.
- Un minimum de sauvegardes periodiques par candidat est exige, calcule a
  partir de la duree disponible et des 90 secondes : neuf pour ce protocole.
  L'hypothese de changements toutes les 30 secondes produit normalement plus
  de sauvegardes ; les minimum et maximum observes sont dans data_checks.
- Aucun email en file pour ce scenario ; aucun transport email disponible.
- CPU global > 85 % pendant environ une seconde : arret de la charge.

Les schemas de reponses sont verifies en cours de route et les compteurs et
versions stockees sont verifies avant suppression de la base temporaire.
Le JSON final indique cleanup_complete. Les rapports et JTL restent sur disque.
Les percentiles ne comprennent pas le temps d'attente des utilisateurs ni les
15 minutes de reflexion ; ils mesurent les operations HTTP et la connexion.

## Limites d'interpretation

Pour ce premier essai, JMeter, l'API et MongoDB partagent le serveur. La charge
du generateur et la limite de connexions Waitress peuvent influencer les temps.
Ce protocole ne certifie pas la capacite du site de production. Il exclut
frontend, IIS, HTTPS, vrais reseaux et integrations externes.

Le jeu comporte 2 001 candidats fictifs (dont le controle), un test de trois
questions et les reponses simulees. Il n'est pas encore precharge avec les
50 000 candidatures de campagne. Les frequence et taille reelles des reponses,
le volume historique, puis le chevauchement de deux creneaux devront etre
evalues ensuite. Un generateur sur une autre machine reste necessaire pour
une mesure de capacite plus representative.

Les options exam-seconds, answer-every et forced-save-every permettent de
valider rapidement le lanceur. Pour l'epreuve demandee, conserver leurs valeurs
par defaut : 900, 30 et 90. Ne pas prendre un essai accelere pour une validation
d'endurance de 15 minutes.
L'option draft-cutoff-seconds vaut 10 pour le protocole normal ; une valeur
reduite est utile uniquement pour la validation acceleree du lanceur.

## Correctif du cache de preparation

Le controle accelere utilise initialement le test fictif de 60 minutes du
seeder. Le cache des metadonnees conserve cette duree pendant 300 secondes.
Une modification directe de la base temporaire a 15 minutes ne renouvelle pas
ce cache. Le lanceur redemarre donc sa propre API apres la modification, met a
jour le suivi de son processus et confirme par HTTP la duree ainsi que les
date/heure attendues avant le palier reel. Il ne change pas le cache applicatif
de production et ne retire pas l'assertion de duree des scenarios JMeter.

Verification locale : cache reproduit a 60 minutes apres modification de la
base, puis metadonnees confirmees a 15 minutes apres redemarrage de l'API
temporaire ; nettoyage confirme. Seize tests automatises passent. L'essai
accelere a deux candidats a aussi confirme les sauvegardes repetees et la
conservation de la derniere version des reponses ; il ne certifie pas la
capacite de 2 000 candidats pendant quinze minutes sur Windows.
