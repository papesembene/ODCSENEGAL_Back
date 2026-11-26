# JMeter sur le serveur Windows, avec donnees isolees

Pour une epreuve commune de 15 minutes avec sauvegardes repetees et soumissions
finales, suivre `EPREUVE_15_MINUTES_WINDOWS.md` (mode exam15).

Pour les trois protocoles connexion / soumission / combine avec leurs montees
et seuils propres, suivre `TROIS_PICS_WINDOWS.md`. Les scenarios historiques
ci-dessous conservent leur pic synchronise.

Le lanceur `jmeter_isolated.py` cree une nouvelle instance MongoDB, une base
vide et une API sur deux ports libres de `127.0.0.1`. Il ne lit ni `.env` ni
`.env.production`, n'accepte aucune URL cible et ne modifie ni IIS, ni les
services Windows, ni la base publiee. Ne pas changer la configuration du site
public pour pointer vers cette base.

Les secrets et cibles de production ne sont pas transmis aux processus de test.
Les confirmations sont mises dans la file **jetable**, aucun worker n'est lance,
le transport email est bloque, les connexions SMTP sont interdites et les
connexions sortantes non loopback sont refusees dans l'API et le seeder.
Les fichiers temporaires, sessions et donnees MongoDB sont supprimes apres
l'arret des processus crees par le lanceur, y compris en cas d'echec.
Les rapports restent sur disque. Ne pas lancer de worker dans cet environnement.

## Prerequis et execution

Utiliser une copie de travail separee du backend contenant ces fichiers,
avec son environnement Python et les dependances de `requirements.txt`.
Ne pas executer depuis une release active ni mettre a jour son environnement
Python. Le seeder `seed_online_test_load_data.py` et `registration_load.py`
doivent rester a cote du lanceur.

Il faut MongoDB (`mongod.exe`), Java et Apache JMeter deja installes.
Si Java n'est pas dans PATH, definir JAVA_HOME dans cette session.
Liens officiels : [JMeter](https://jmeter.apache.org/download_jmeter.cgi),
[execution CLI](https://jmeter.apache.org/usermanual/get-started.html).

Dans PowerShell, depuis cette copie du backend, adapter les chemins :

```powershell
.\.venv\Scripts\python.exe load_tests\jmeter_isolated.py `
  --mongod 'C:\Program Files\MongoDB\Server\8.0\bin\mongod.exe' `
  --jmeter 'C:\outils\apache-jmeter-5.6.3\bin\jmeter.bat' `
  --levels 500
```

Chaque lancement verifie d'abord les deux parcours avec un utilisateur.
Puis 500 utilisateurs s'inscrivent, une fois chacun. Ensuite 500 autres
candidats fictifs, prealablement crees et affectes a un test dedie, lisent les
metadonnees, verifient l'acces, chargent les questions, sauvegardent un brouillon
et soumettent leurs reponses. La montee prend 60 secondes par parcours.
Une barriere attend tous les utilisateurs avant les soumissions d'inscription,
et avant les verifications d'acces au test : ces operations partent alors
ensemble. Si un utilisateur n'arrive pas a la barriere, la limite de duree
du lanceur arrete l'execution au lieu de liberer un pic partiel.
Les connexions HTTP ne sont pas conservees entre les requetes : les lectures
prealables doivent liberer leurs connexions avant cette barriere. Cela evite
de remplir les emplacements Waitress avec des clients inactifs sous Windows.
Une erreur de requete ou de script JMeter interrompt desormais l'execution
des sa detection dans le fichier de resultats, sans attendre la barriere.
Ce scenario mesure donc aussi le cout de nouvelles connexions TCP locales.
Le seeder ne fait aucun appel aux endpoints d'invitation.

Ce sont des pics courts et bornes : 500 utilisateurs liberes ensemble
ne signifient pas 500 candidats actifs pendant une heure. Le scenario ne simule
pas encore une epreuve longue avec sauvegardes repetees. Les inscriptions
mesurees et les candidats du test sont deux jeux distincts.

Apres examen des rapports du premier lancement, utiliser eventuellement
`--levels 500,1000,1500`. Le plafond accepte est 2000 par palier.
Pour mesurer le parcours test en ligne independamment d'un echec de seuil
sur les inscriptions, ajouter `--scenario online` : seuls la verification
a un utilisateur et les paliers en ligne sont lances. Les candidats sont
crees directement dans la base temporaire par le seeder. Les seuils restent
identiques. `--scenario registration` permet l'operation inverse ; par defaut,
`--scenario both` conserve l'execution des deux parcours.
Le lanceur arrete la charge si le CPU global depasse 85 % pendant environ une
seconde. Aucun palier suivant n'est lance si une requete echoue, si le p95
d'un endpoint depasse 1500 ms, si les compteurs de documents divergent ou si
JMeter echoue. Chaque execution JMeter est limitee a 10 minutes.
Ces seuils exploratoires peuvent etre ajustes dans les arguments du lanceur.

## Lire les resultats

Le chemin final s'affiche sous `load_tests/reports/jmeter/<identifiant>/` :

- `summary.json` : reussite, erreurs, p50/p95/p99, compteurs et cause d'arret ;
- `*-html/index.html` : tableau de bord JMeter par parcours et palier ;
- `.jmx` : scenarios generes ; `.jtl` : mesures ; `.log` : journaux JMeter ;
- `processes.log` : journaux de l'API, de MongoDB et de la console JMeter.

Un resultat `queued_test_emails` non nul est attendu : ces messages restent
uniquement dans le MongoDB temporaire, puis disparaissent avec celui-ci.
Cela n'indique pas un envoi externe.

## Portee des mesures

Ce test mesure le backend de cette copie et un MongoDB vide, avec les index
crees par les modeles. Il ne mesure pas le frontend, IIS, TLS, le reseau des
candidats ou le volume historique de la base. Utiliser les memes commits et
les memes reglages API que la version publiee pour rapprocher la comparaison.
Sur Windows, Waitress limite ses connexions a 500 : des utilisateurs virtuels
supplementaires peuvent attendre une connexion.

JMeter, cette API, ce MongoDB et la production partagent le materiel du serveur.
La production peut donc ralentir malgre la separation des donnees. Faire les
essais dans une plage de faible activite et garder la possibilite d'interrompre
avec Ctrl+C. Le resultat ne constitue pas une capacite garantie du site public.
Un essai distant representatif reste necessaire pour une mesure complete.

## Verification du lanceur

Le 7 novembre 2026, verification locale sur macOS avec Java 17, JMeter 5.6.3
et MongoDB : controles a un utilisateur puis palier a deux utilisateurs,
24 requetes HTTP, aucune erreur, compteurs coherents et nettoyage termine.
Six tests automatises verifient aussi le refus des cibles de production,
le blocage du transport email/SMTP et des connexions externes, les scenarios
loopback bornes avec barriere et connexions liberees, le comptage des erreurs
et la detection d'un echec pendant l'attente des autres utilisateurs.
Le scenario en ligne independant est verifie sans requete d'inscription
et avec des candidats distincts entre paliers.
Cette verification ne valide ni l'execution Windows ni un palier de 500.
