# Trois scenarios de pic ODC

Ces scenarios utilisent uniquement l'API et MongoDB temporaires du lanceur
isole. Aucun appel ne vise le site public. Les protections contre les emails,
les connexions externes, les erreurs et le CPU eleve restent actives.

| Scenario | Candidats mesures | Montee | Action mesuree | p95 cible |
|---|---:|---:|---|---:|
| connection | 1 000 | 60 s | Metadonnees, verification email/telephone, acces aux questions | <= 3 s pour toute la connexion |
| submission | 1 000 | 10 s | Une soumission finale par candidat prepare | <= 5 s pour le POST final |
| combined | 1 000 | 60 s | Connexion, questions, brouillon, soumission | <= 5 s pour le parcours complet |

La connexion est celle des candidats (email et telephone), pas une connexion
administrateur ni une authentification OAuth. Le test de soumission dispose
de sessions fictives deja commencees, preparees directement dans la base
jetable avant la mesure : il ne rajoute pas de requetes d'acces ou de brouillon
dans le pic mesure.

Les utilisateurs demarrent progressivement sur la duree indiquee. Aucune
barriere ne les retient jusqu'au dernier utilisateur et aucune pause fixe n'est
ajoutee. Ces essais different des anciens modes online et registration, qui
declenchent un pic synchronise. Les resultats ne se comparent pas directement.
1 000 departs sur 60 secondes ne signifient pas 1 000 requetes au meme instant.
Il n'y a pas de simulation de temps de reflexion ni d'epreuve longue.

## Lancer les trois essais

Apres copie des fichiers dans le backend de test, depuis PowerShell :

```powershell
Set-Location 'C:\ODC-Charge\backend'
& '.\.venv\Scripts\python.exe' load_tests\run_online_peaks.py `
  --mongod 'C:\ODC-Charge\MongoDB\mongodb-win32-x86_64-windows-8.0.34\bin\mongod.exe' `
  --jmeter 'C:\ODC-Charge\apache-jmeter-5.6.3\bin\jmeter.bat' `
  --users 1000 --threads 16
```

Les trois scenarios s'executent dans cet ordre, separement, chacun avec sa
propre API, base vide, candidats et rapports. Chaque scenario commence par un
controle avec un candidat supplementaire, exclu du palier mesure. Le palier
suivant utilise des identites distinctes de ce controle.

Un depassement du seul seuil de latence est rapporte comme un echec, puis la
suite passe au scenario independant suivant. Une erreur de requete, de
donnees, de preparation, de nettoyage ou une surcharge CPU arrete la suite.
Le seuil CPU global reste 85 % pendant environ une seconde ; chaque execution
JMeter est limitee a dix minutes. Ctrl+C interrompt la suite sans lancer un
autre scenario.

Pour un scenario seul, utiliser jmeter_isolated.py avec les memes chemins,
`--levels 1000 --threads 16` et `--scenario connection`, `--scenario submission`
ou `--scenario combined`. Les montees et seuils ci-dessus sont les valeurs
par defaut de ces trois modes.

## Verifications et rapports

- Connexion : exactement 1 000 verifications reussies pour 1 000 emails
  attendus distincts ; les assertions verifient aussi l'identite retournee.
  Aucune soumission n'est creee.
- Soumission et combine : exactement 1 000 resultats uniques pour les candidats
  du palier ; reponses conservees identiques au jeu envoye ; sessions passees
  a submitted avec leurs reponses intactes ; aucun doublon ni resultat d'un
  candidat inattendu. Les totaux cumules incluent aussi le candidat de controle,
  et les champs expected_stage_submissions / unique_stage_submissions isolent
  le palier de 1 000.
- Zero erreur HTTP ou assertion et zero email en file.
- Le controle de perte et de doublon porte sur l'etat de la base en fin de
  scenario. Il ne simule pas de panne ou de coupure reseau pendant la soumission.

Chaque scenario fournit summary.json, les JMX, les JTL, journaux et tableaux
de bord HTML. La suite fournit en plus suite-summary.json, avec les trois
verdicts, les chemins des rapports et l'etat du nettoyage. Le dossier final
est affiche dans la console sous `Bilan des trois scenarios:`.

Les JTL incluent l'email fictif de chaque echantillon pour verifier les acces
uniques. Les echantillons Connexion et Combine mesurent la transaction complete,
en plus des echantillons HTTP de chaque etape. Pour le verdict, utiliser le p95
de cette transaction complete, pas le percentile global melangeant ses etapes.

Le frontend, IIS, HTTPS, les historiques et le reseau des candidats restent
exclus. JMeter et l'application partagent la machine. Le test reste une mesure
du backend isole, pas une certification de capacite de production.

## Validation locale

Validation des trois modes avec JMeter 5.6.3 et un MongoDB temporaire : controle
a un utilisateur puis deux candidats par mode, aucune erreur et integrite
validee. Onze tests automatises couvrent les protections, la separation des
actions et des identites, les donnees, les seuils et la poursuite de la suite
uniquement apres un echec de latence. Le palier de 1 000 sur Windows reste a
executer et analyser.
