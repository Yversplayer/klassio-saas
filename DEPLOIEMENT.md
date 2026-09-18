# KLASSIO — audit de mise en production et procédure de déploiement

Dernière mise à jour : 2026-09-12 (après la préparation aux tests de charge).

Ce document remplace `CURSOR_CODE_REVIEW_PROMPT.md`, `EMERGANT_NEXT_STEPS.md`
et `PRODUCTION_READY.md`, supprimés depuis. L'audit qu'ils demandaient a été
fait, puis un second passage complet — le release gate — a repris l'ensemble,
y compris les corrections du premier. Ce qui suit en donne le résultat, ce qui
a été corrigé, et ce qui reste à faire — par qui.

---

## 1. Ce qui a été corrigé

Les 65 tests d'origine sont intacts. 98 tests ont été ajoutés, soit
**163 tests verts sur SQLite _et_ sur un vrai PostgreSQL 16** — ce second point
était jusqu'ici la case non cochée du projet ; voir §3.2.

Une seule ligne d'un test existant a été touchée : `test_lots.py` préparait son
montage avec `INSERT OR IGNORE`, du SQLite pur, qui faisait tomber le test dès
qu'on l'exécutait contre PostgreSQL. Passé en `ON CONFLICT DO NOTHING`, la forme
déjà employée partout dans le backend. Aucune assertion n'a bougé.

### 1.1 Le déploiement était impossible en l'état

| Manquait | Créé | Pourquoi c'était bloquant |
|---|---|---|
| `requirements.txt` (racine) | ✔ | Heroku ne détecte même pas une application Python sans lui |
| `Procfile` | ✔ | Sans lui, Heroku ne sait pas quoi lancer |
| `runtime.txt` | ✔ | Sans version épinglée, la plateforme choisit à votre place |
| Application du schéma au déploiement | `backend/tools/release.py` | voir ci-dessous |

`backend/tools/release.py` est joué par la ligne `release:` du `Procfile`, avant
chaque bascule de version. Il est indispensable : Gunicorn importe `app:app`
directement et ne passe donc **jamais** par le bloc `if __name__ == "__main__"`
de `backend/app.py`, le seul endroit où `db.init_db()` était appelé. Sans cette
étape, aucune migration additive n'aurait jamais été appliquée en production —
et le défaut serait resté silencieux jusqu'à la première colonne manquante.

`requirements.txt` ne contient que les cinq paquets réellement importés par
`backend/*.py`, pas un `pip freeze` du venv de développement : celui-ci embarque
numpy, scipy, pillow et requests, qu'aucune ligne du backend n'importe.

### 1.2 Deux défauts qui ne se déclenchent qu'en PostgreSQL

**Les violations de contrainte repartaient en 500.** `backend/app.py` enregistrait
son gestionnaire 409 sur `sqlite3.IntegrityError` uniquement. En mode Postgres,
la même violation (un email pris dans une course concurrente, une clé
d'idempotence rejouée) est une `psycopg.errors.IntegrityError` : elle échappait au
gestionnaire et ressortait en 500 avec le risque de trace associé. Les deux
classes sont maintenant enregistrées, via `db.integrity_errors()`.

**Aucun filet sous les exceptions imprévues.** Une exception non anticipée
renvoyait la page d'erreur de Werkzeug. Un gestionnaire générique renvoie
désormais `{"error": "Erreur interne du serveur."}` en 500 et écrit la trace
dans les logs du serveur, jamais dans la réponse. Les erreurs HTTP volontaires
(404, 405, 413) gardent leur comportement propre.

### 1.3 Le CORS était figé sur les origines de développement

`ALLOWED_ORIGINS` ne contenait que `localhost:4173` et `127.0.0.1:4173`. Le jour
où le frontend est servi depuis un domaine réel, tout appel navigateur aurait été
refusé, sans autre correctif possible qu'une modification du code. Les origines
supplémentaires se déclarent maintenant en variable d'environnement :

```
KLASSIO_ALLOWED_ORIGINS=https://app.klassio.com,https://klassio.com
```

Le joker `*` est refusé par construction, même s'il est écrit dans la variable.

### 1.4 Deux connexions PostgreSQL par requête, ouvertes puis jetées

C'est le poste de latence principal, et il ne disparaît pas avec l'hébergement
européen. Chaque requête HTTP authentifiée ouvre **deux** connexions : une dans
`security.require_auth` pour résoudre la session, une dans la route elle-même.
Chacune coûte une poignée de main TCP + TLS + authentification.

`backend/db.py` garde maintenant les connexions ouvertes entre les requêtes.
`close()` ne ferme plus la socket : il annule la transaction en cours — même
sémantique que `sqlite3.Connection.close()`, qui abandonne le travail non
validé — et rend la connexion à la réserve. Les 500 appels `conn.close()` du
backend n'ont pas changé de sens et n'ont pas été touchés.

Mesure réelle contre Supabase eu-west-1, depuis Kinshasa, cinq cycles
ouverture + `SELECT count(*) FROM students` + fermeture :

| | Total | Ouverture après la première |
|---|---|---|
| Sans réserve | 12,36 s | 1,8 – 2,1 s à chaque fois |
| Avec réserve | 5,61 s | 0,000 s |

2,2× plus rapide, et le facteur augmente avec le nombre de requêtes par page.
Une connexion au repos depuis plus de 60 s est vérifiée avant réutilisation :
le pooler Supabase coupe les connexions inactives, et la réserve ne doit jamais
servir une socket morte à un utilisateur. Taille réglable par
`KLASSIO_PG_POOL_SIZE` (5 par défaut). Sans effet en mode SQLite.

### 1.5 Cinq index manquants

Invisibles en développement — sur une base de démonstration, un parcours de
table complet coûte moins qu'un index. Sur 137 000 lignes, et surtout à travers
le réseau, ils comptent. Ajoutés dans `db._migrate()`, donc appliqués
automatiquement au prochain démarrage sur les deux moteurs.

| Index | Ce qu'il sert |
|---|---|
| `memberships(tenant_id, role, status)` | `UNIQUE(user_id, tenant_id)` n'aide pas une recherche par `tenant_id` seul — or c'est le filtre d'une douzaine de requêtes, dont le tableau de bord et chaque notification à la Direction |
| `guardians(user_id)` | `school.py` résout par là le périmètre d'un parent, à chaque requête d'un parent |
| `guardians(tenant_id)` | comptage des tuteurs du tableau de bord |
| `student_guardians(guardian_id)` | `UNIQUE(student_id, guardian_id)` couvre le sens élève → tuteurs, pas tuteur → élèves, qui est celui du portail parent |
| `sessions(user_id)` | révocation de toutes les sessions d'un compte au changement de mot de passe |

### 1.6 Quatre requêtes que PostgreSQL refuse, et le traducteur qui les cachait

Trouvées en exécutant réellement la suite contre PostgreSQL (§3.2) — aucune ne
pouvait apparaître autrement : SQLite les accepte toutes les quatre.

**`GROUP BY` incomplet.** SQLite tolère de sélectionner une colonne nue qui
n'est ni groupée ni agrégée. PostgreSQL ne l'accepte que si la colonne
appartient à la table dont la clé primaire est groupée. Quatre requêtes
groupaient sur `s.id` tout en sélectionnant `c.name`, qui vient de `classes` :

| Fichier | Route |
|---|---|
| `backend/api_school.py` | `/api/discipline/overview` |
| `backend/app.py` | tableau de bord du Directeur des disciplines |
| `backend/api_discipline.py` | alertes de discipline |
| `backend/ai_assistant.py` | élèves aux absences répétées |

Les colonnes manquantes ont été ajoutées au `GROUP BY` — écriture valable sur
les deux moteurs.

**Alias de sortie dans un `HAVING`.** `api_discipline.py` écrivait
`HAVING remaining <= ?`, où `remaining` est un alias de la clause `SELECT`.
SQLite l'accepte, PostgreSQL non (contrairement à `ORDER BY`, qui l'accepte
dans les deux). L'expression est maintenant répétée.

**Une apostrophe dans un commentaire SQL cassait la traduction.** Trouvé en
corrigeant les requêtes ci-dessus. `sql_dialect.to_pyformat()` suit l'état
« dans une chaîne / hors d'une chaîne » pour ne pas traduire un `?` qui
appartient à du texte. Il ne connaissait pas les commentaires : une apostrophe
dans un `-- PostgreSQL n'accepte pas…` lui faisait croire qu'une chaîne
s'ouvrait, et **plus aucun `?` situé après n'était traduit** — PostgreSQL
recevait des `?` littéraux et rejetait la requête. En français, un commentaire
sans apostrophe est l'exception. Le traducteur saute maintenant `--` et
`/* */`, en continuant d'y doubler les `%`.

Six tests couvrent ce piège, dont un filet global qui parcourt toutes les
requêtes du backend et vérifie qu'aucun marqueur ne survit à la traduction.

### 1.7 Trois recherches qui cessaient de trouver, sans erreur

Même origine que le §1.6, trouvées de la même façon. **SQLite ignore la casse
dans un `LIKE` sur de l'ASCII ; PostgreSQL en tient compte.** Trois recherches
comparaient donc la saisie de l'utilisateur à la valeur stockée sans
normaliser :

- l'assistant, quand on lui demande les élèves d'une classe ;
- l'assistant, quand on cherche un élève par son nom ;
- la recherche de reçus (numéro, nom, identifiant élève).

Aucune n'aurait levé d'erreur : elles auraient simplement renvoyé une liste
vide dès que la casse ne correspondait pas exactement. `LOWER()` est maintenant
appliqué des deux côtés — la forme déjà utilisée ailleurs dans le backend.

Une quatrième route, `/api/messages/threads`, échouait entièrement : elle
triait par `ORDER BY (last_at IS NULL), …`, or PostgreSQL accepte un alias de
sortie seul mais jamais à l'intérieur d'une expression. Remplacé par
`NULLS LAST`, qui dit la même chose sur les deux moteurs.

### 1.8 La limitation anti-force-brute interdisait de dépasser un worker

Les compteurs de tentatives vivaient dans un dictionnaire en mémoire de
processus. Cela fonctionne — à condition de ne jamais lancer plus d'un worker.
Avec `gunicorn -w 4`, chaque worker tient ses propres compteurs : un attaquant
obtient quatre fois la limite, vingt essais de mot de passe par fenêtre au lieu
de cinq. La protection s'affaiblissait exactement au moment où l'on monte en
charge, et rien ne l'aurait signalé.

Les tentatives sont maintenant enregistrées dans la table `rate_limit_attempts`.
La fenêtre reste glissante — chaque tentative est conservée, pas un compteur par
tranche — donc le comportement observable est inchangé à un worker. Les
tentatives trop vieilles sont balayées au fil de l'eau, plus un balayage global
amorti à une fois par minute pour que la table ne grossisse pas indéfiniment.

Coût : deux ou trois requêtes, uniquement sur les sept routes publiques.
Bénéfice : la limite ne dépend plus du nombre de workers, et elle survit au
redémarrage d'un dyno. Aucun Redis, aucun service supplémentaire.

Vérifié bout en bout, deux workers Gunicorn, même adresse e-mail :

```
tentative 1..5 -> 401     (refus de mot de passe, normal)
tentative 6, 7 -> 429     (Trop de tentatives)
```

Avant le correctif, la même séquence aurait laissé passer dix essais.

### 1.9 La clé publiable était écrite en clair dans un document

`EMERGANT_NEXT_STEPS.md` contenait la valeur complète de `SUPABASE_ANON_KEY` et
la forme de la chaîne de connexion. Cette clé est publiable par nature — elle
est conçue pour être visible dans un navigateur — mais elle n'a rien à faire
dans un fichier destiné à être versionné et transmis. Remplacée par une
indication de l'endroit où la lire.

---

### 1.10 Ce que le release gate a trouvé en plus

Second passage, mené comme un audit hostile sur l'ensemble du produit — y
compris sur les corrections du premier passage.

**Une image pouvait transporter du HTML (le plus grave).** La validation des
photos d'élève, logos, photos de couverture, documents et pièces jointes se
limitait à `startswith("data:image/")` et à une taille maximale. La chaîne

```
data:image/png;base64,AAA" onerror="…" x="
```

passait sans obstacle, et le frontend l'insérait telle quelle dans
`<img src="…">`. **Exploité pour de vrai pendant l'audit** : le guillemet
referme l'attribut, et un gestionnaire `onerror` est arrivé jusque dans le DOM
d'un navigateur — attributs `src`, `onerror`, `x`, `alt` constatés sur
l'élément. Le code n'a pas été exécuté, uniquement parce que les 28 pages
portent une Content-Security-Policy sans `unsafe-inline`. Une seule page
livrée sans cette CSP, ou un navigateur qui ne l'applique pas, et c'était un
XSS stocké complet, exploitable jusque sur le portail public.

Corrigé aux deux niveaux, parce qu'une seule barrière ne suffit pas :
`validation.DATA_URI_IMAGE` / `DATA_URI_FICHIER` imposent la forme complète
d'un data URI (plus aucun guillemet, espace ou chevron ne survit ; le SVG est
volontairement exclu, il peut contenir du script), et le frontend échappe
désormais ces valeurs avant de les insérer dans un attribut — ce qui neutralise
aussi les données déjà stockées. Vérifié dans le navigateur après correction :
seuls `src` et `alt` subsistent, les guillemets sont encodés en `&quot;`.

**L'import n'était pas atomique, malgré sa docstring.** La validation des
montants se faisait au fil de l'écriture. Reproduit : un fichier de quatre
lignes dont la dernière portait un montant négatif renvoyait bien une erreur
400 — après avoir écrit 3 élèves, 3 obligations, 3 paiements et 3 reçus.
L'école voyait « échec », corrigeait son fichier, relançait, et doublait tout
ce qui était déjà passé. Sur 2 340 élèves, une erreur en ligne 1 500 laissait
1 499 élèves fantômes. Une passe de validation parcourt maintenant l'intégralité
du fichier avant la première écriture, et nomme la ligne fautive.

**Cinq routes annonçaient un succès sans rien faire.** `DELETE /api/exams/…`,
`DELETE /api/schedule/…`, `DELETE /api/discipline/rules/…`,
`DELETE /api/documents/…`, `DELETE /api/classes/…/teachers/…` et
`POST /api/notifications/…/read` répondaient `{"ok": true}` pour une ressource
d'un autre établissement. Aucune donnée n'a jamais traversé — le filtre
`tenant_id` était bien présent dans le `WHERE` — mais le serveur mentait, et
l'interface affichait une suppression qui n'avait pas eu lieu. Le nombre de
lignes affectées est maintenant vérifié ; sinon, 404.

**Quatre routes renvoyaient 500 sur un champ manquant**, dont `/api/payments`
et `/api/obligations`. Une clé absente levait un `KeyError`. Sur la route de
paiement, `idempotency_key` était lue sans garde : elle est désormais
obligatoire et validée — sans elle, deux clics valent deux paiements.

**Deux `except Exception` déguisaient n'importe quelle panne.** Dans
`issue_receipt`, toute erreur était rejouée cinq fois puis remplacée par un
`RuntimeError` sans cause ; dans la création de période, toute erreur devenait
« ce libellé existe déjà ». Restreints aux seules violations de contrainte.

**Les jetons partaient en clair dans les journaux d'accès.**
`/api/invitations/lookup?token=…` et `/api/password-reset/lookup?token=…`
passent leur jeton en paramètre d'URL ; le format de journal par défaut de
Gunicorn écrit la ligne de requête complète. Toute personne ayant accès aux
logs de production pouvait donc reprendre une invitation ou une
réinitialisation de mot de passe. Le `Procfile` impose désormais un format qui
ne journalise que la méthode et le chemin. Vérifié : le jeton n'apparaît plus.

**La page Rapports mettait 811 ms.** Mesuré sur l'établissement de simulation
(2 340 élèves, 2 534 paiements). 95 % du temps venait d'une seule boucle qui
convertissait chaque horodatage un par un — `fromtimestamp()` puis `strftime()`
consultent la base de fuseaux du système à chaque appel, environ 200 µs
l'unité dans un worker Gunicorn forké. Le regroupement se fait maintenant par
bornes de mois calculées une seule fois : **811 ms → 73 ms**, résultat
identique au centime.

**Le logo pesait 1,2 Mo pour être affiché en 30 pixels.** 1 254 × 1 254 px,
téléchargé par chaque visiteur, sur des connexions congolaises. Réduit à
256 × 256 (25 Ko, soit 4× la plus grande taille d'affichage). L'original est
conservé sous `assets/logo-source.png`.

**Un balayage automatique d'isolation a été ajouté.**
`backend/tests/test_release_gate.py` énumère les routes paramétrées depuis
`app.url_map`, remplace chaque identifiant par celui d'un autre établissement
et exige un refus — 57 des 61 routes couvertes, 3 des 4 restantes étant les
routes plateforme, vérifiées séparément (403 pour tout rôle non-administrateur
de plateforme). Une route ajoutée demain sans contrôle de périmètre fera
échouer ce test sans que personne n'ait à y penser.

### 1.11 Préparation aux tests sérieux — ce que cette phase a encore trouvé

**La confirmation d'un import n'était liée à aucune analyse.**
`/api/onboarding/confirm-import` acceptait la liste d'enregistrements envoyée
par le client : un aperçu de 100 élèves pouvait être confirmé par 500 lignes
différentes, et rien ne le signalait. Une table `import_sessions` conserve
désormais l'analyse côté serveur ; la confirmation rejoue exactement ce qui a
été montré, refuse une session inconnue, expirée ou déjà confirmée, et résiste
à deux clics simultanés (le passage à `confirmed` sert de verrou). Vérifié :
50 enregistrements falsifiés envoyés avec une session valide sont ignorés.

**Un fichier « Nom | Prénom » importait tous les élèves sans prénom.** Le motif
de détection du nom complet est `nom`, qui capture aussi un en-tête valant
simplement « Nom ». La colonne Prénom était détectée, affichée dans l'aperçu de
mapping… puis jamais lue. C'est la forme la plus courante d'un listing
scolaire. Une colonne prénom dédiée fait maintenant foi ; le cas « Nom complet »
du fichier d'exemple passe par le chemin d'origine, inchangé.

**Le rang d'un bulletin ne correspondait pas à la moyenne imprimée dessus.**
Le rang se calculait par `AVG(score / max_score)` sur toutes les notes à plat —
donc pondéré par le NOMBRE de notes — alors que la moyenne affichée est la
moyenne des moyennes par matière. Reproduit : deux élèves affichant tous deux
12,0 sortaient 1er et 2e. Et deux moyennes égales donnaient deux rangs
différents, décidés par l'ordre de la base. Le classement se fait maintenant sur
la même règle que la moyenne affichée, avec ex æquo (1, 1, 3).

**Aucune compression des réponses.** Ni Flask ni le routeur Heroku ne
compressent. La liste d'élèves d'un établissement de 2 340 élèves pesait 892 Ko
de JSON — à chaque ouverture de la page, sur des connexions mobiles
congolaises. Compression gzip ajoutée : **892 Ko → 126 Ko** (×7), classes ×8,9.
Coût mesuré : 15,7 ms de processeur pour 6,1 s de transfert économisé sur un
lien à 1 Mbit/s. Les réponses courtes et les erreurs ne sont pas touchées.

**Une écriture en base sur chaque lecture.** `require_permission` journalisait
chaque vérification, y compris réussie. Sur la base de simulation, 15 817 des
43 818 lignes d'audit étaient des « permission_check … success » contre 2 refus
— et `/api/audit-logs` ne renvoyant que les 100 dernières, les actions réelles
d'un établissement étaient noyées. Les refus restent toujours journalisés, les
écritures aussi ; les lectures réussies ne le sont plus. Mesuré dos à dos sous
30 utilisateurs : **+57 % de débit**, latences médianes divisées par deux.

**Les sessions expirées ne disparaissaient jamais.** Elles n'étaient effacées
que si quelqu'un présentait leur jeton — ce qui n'arrive pas. Relevé sur la base
de développement : 16 jetons d'avant le passage au hachage y dormaient encore,
en clair (tous expirés, donc inexploitables). La phase `release` purge
désormais les sessions périmées, et jamais une session valide.

**6 896 paiements confirmés sans reçu dans la base de développement.**
Enquête faite : tous sont antérieurs au premier reçu jamais émis — le mécanisme
a été ajouté le 10 septembre et est correct depuis, zéro orphelin après cette
date. Un seul chemin de code écrit `CONFIRMED`, et il émet toujours le reçu.
`backend/tools/reparer_recus.py` permet de rattraper ces anciens paiements
(strictement additif, simulation par défaut) ; la base de travail n'a pas été
modifiée sans votre accord.

**Outils livrés pour la phase de tests sérieux :**

| Outil | Rôle |
|---|---|
| `backend/tools/seed_charge.py` | Deux établissements peuplés (2 000 et 500 élèves), un compte par rôle, `tools/k6/env.json` |
| `tools/k6/{smoke,charge,isolation,finance}.js` | Quatre scénarios K6, avec seuils issus de mesures réelles |
| `backend/tools/charge_locale.py` | Les mêmes scénarios en Python, sans dépendance externe |
| `backend/tools/verifier_invariants.py` | 26 invariants de données, sortie non nulle si l'un est violé |
| `backend/tools/reparer_recus.py` | Émet les reçus manquants d'anciens paiements |

## 2. Ce qui a été vérifié et qui va bien

Les points de l'audit demandé qui n'ont appelé aucune correction.

**Injection SQL : aucune.** Les vingt appels `conn.execute(f"…")` ont été relus
un par un. Sans exception, la partie interpolée est construite par le code —
noms de colonnes écrits en dur, et listes de `?` générées à partir de la
longueur d'une liste. Aucune valeur venue du client n'entre dans une chaîne SQL.

**Isolation entre établissements : solide.** Le `tenant_id` vient exclusivement
de la table `sessions`, résolu par `security.resolve_session()`. Un `tenant_id`
envoyé par le client est ignoré. `resolve_session` revérifie l'appartenance
active à chaque requête : révoquer un compte invalide immédiatement ses sessions
en cours, sans attendre leur expiration.

**Mots de passe et jetons.** PBKDF2-HMAC-SHA256, 200 000 itérations, sel
aléatoire par mot de passe, comparaison en temps constant. Les jetons de session
et d'invitation ne sont stockés que sous forme de hash SHA-256 : une fuite du
fichier de base ne suffit pas à usurper une session. Sessions à 12 h.

**Limitation de débit : présente sur les sept routes publiques** (connexion,
création d'établissement, recherche et acceptation d'invitation, portail,
recherche et application de réinitialisation). Voir la réserve en §3.

**En-têtes de sécurité** : `X-Content-Type-Options`, `X-Frame-Options`,
`Referrer-Policy` sur toutes les réponses. **Taille de requête** plafonnée à
10 Mo avec un 413 propre.

**`/api/health` existe déjà** et répond sans authentification.

**Aucun secret en dur.** Tout passe par `config.get()`, qui lit l'environnement
d'abord, `backend/.env` ensuite. `backend/.env` est bien dans `.gitignore`.

**Aucune dépendance au disque.** Photos, logos, documents et pièces jointes sont
stockés en base, pas sur le système de fichiers. Le disque éphémère d'Heroku
n'est donc pas un problème.

**Aucun travail de fond.** Pas de Celery, pas de RQ, pas de tâche asynchrone :
la ligne `worker` proposée dans l'ancien `PRODUCTION_READY.md` n'a pas lieu
d'être et n'a pas été reprise.

**Arrêt gracieux : rien à écrire.** Gunicorn gère SIGTERM, et l'application ne
détient aucun état à sauvegarder. Vérifié : arrêt en 1 s, code de sortie 0.

---

## 3. Ce qui reste, et qui doit le faire

### 3.1 Le nombre de workers n'est plus une contrainte

Cette section disait, plus tôt dans la journée, qu'il fallait s'en tenir à un
seul worker à cause des compteurs anti-force-brute en mémoire. Ce n'est plus le
cas : ils sont en base (§1.8). Le `Procfile` démarre deux workers de quatre fils
et lit `WEB_CONCURRENCY` si la plateforme la fournit :

```
web: gunicorn --chdir backend --workers ${WEB_CONCURRENCY:-2} --threads 4 …
```

Monter le nombre de workers ne demande donc plus qu'un `heroku config:set
WEB_CONCURRENCY=4`, sans rien affaiblir. La borne réelle est la mémoire du dyno,
pas la sécurité.

### 3.2 La suite tourne maintenant contre un vrai PostgreSQL, ici

C'était la case ouverte depuis le début : les tests ne s'exécutaient que sur
SQLite, et la conclusion précédente était qu'il fallait attendre un hébergement
européen pour faire mieux. C'était faux — ce qu'il fallait, ce n'était pas
l'Europe, c'était *un* PostgreSQL. Un local fait exactement le même travail.

`backend/tools/pg_tests.py` démarre un **PostgreSQL 16 réel sur cette machine**,
dans un dossier temporaire détruit à la fin. Pas de Docker, pas de droits
administrateur, pas de réseau : les binaires arrivent dans une roue pip de
10 Mo (`pgserver`, dans `requirements-dev.txt`).

```bash
backend_venv/bin/pip install -r requirements-dev.txt
python backend/tools/pg_tests.py                    # 92 tests, ~30 s
python backend/tools/pg_tests.py tests.test_school  # un seul module
```

**92 tests verts en 28 secondes.** À comparer aux 696 secondes qu'avaient
demandées 12 tests contre Supabase depuis Kinshasa — la campagne complète
tournait en heures, et c'est ce qui la rendait impraticable. Elle est
maintenant plus rapide que sur SQLite.

C'est aussi ce qui a mis au jour les huit défauts des §1.6 et §1.7 : aucun
n'était visible autrement, puisque SQLite les accepte tous.

Reste un second mode, pour la vérification finale seulement :

```bash
python backend/tools/pg_tests.py --supabase
```

Il joue la suite contre la vraie base, dans un schéma `klassio_test` séparé
recréé vide puis supprimé — deux schémas ne partagent aucune table, les 137 000
lignes du schéma `public` ne sont jamais approchées. C'est le seul mode qui
exerce le pooler Supabase en mode transaction, la configuration réelle de
production. Lent depuis Kinshasa ; immédiat depuis un dyno européen. À jouer une
fois avant la bascule, pas à chaque modification.

### 3.3 Pour Emergant — le déploiement

Rien dans ce qui précède ne suppose un accès Heroku. Tout ce qui suit en
suppose un.

```bash
# Le dépôt n'est pas encore versionné : aucun .git à la racine.
cd /Users/macbookpro/klassio-saas
git init
git add .
git status          # vérifier que backend/.env et backend/*.db sont bien exclus
git commit -m "Klassio — prêt pour le déploiement"

heroku create klassio-prod --region eu
heroku config:set \
  KLASSIO_DB_BACKEND=postgres \
  KLASSIO_ALLOWED_ORIGINS=https://<domaine-du-frontend> \
  SUPABASE_URL=https://<ref>.supabase.co \
  SUPABASE_ANON_KEY=<Supabase → Project Settings → API> \
  SUPABASE_DB_URL=<Supabase → Connect → pooler, port 6543>
git push heroku main    # la phase `release` applique le schéma toute seule

heroku logs -t
curl https://klassio-prod.herokuapp.com/api/health   # doit répondre {"status":"ok"}
```

Puis vérifier une connexion réelle, le tableau de bord, la liste des classes et
un dossier d'élève, avec un compte du locataire de test.

### 3.4 Après le déploiement

- Sauvegardes Supabase : vérifier qu'elles sont actives et tester une
  restauration avant d'en avoir besoin.
- Logs : Heroku ne les conserve que très peu de temps. Un drain vers Papertrail
  ou équivalent, sinon le premier incident sera analysé sans rien.
- Supervision : un simple appel périodique à `/api/health` couvre l'essentiel.

---

## 4. Corrections aux consignes précédentes

Trois instructions des anciens documents étaient fausses et auraient coûté du
temps à qui les aurait suivies.

**« Ne pas oublier FLASK_SECRET_KEY — Flask crashe sans lui en production » :
faux.** Klassio n'utilise jamais la session par cookie de Flask ; il gère ses
propres sessions en base, avec un jeton Bearer. `app.secret_key` n'est lu nulle
part, et aucune route ne le déclenche. La variable a été retirée de la
procédure : configurer un secret dont rien ne se sert donne une fausse
impression de sécurité. Idem pour `JWT_SECRET` — il n'y a pas de JWT dans
Klassio.

**`pip freeze > requirements.txt` : à ne pas faire.** Le venv contient numpy,
scipy, pillow et requests, qu'aucun fichier du backend n'importe. Le
`requirements.txt` livré est écrit à la main à partir des imports réels.

**`web: … -w 4 …` : ne pouvait pas fonctionner tel quel.** Les compteurs
anti-force-brute étaient en mémoire de processus ; quatre workers auraient
quadruplé la limite. Le défaut a été corrigé à la source (§1.8), donc plusieurs
workers sont maintenant légitimes — mais l'ordre comptait : d'abord partager les
compteurs, ensuite seulement multiplier les workers.

---

## 5. Fichiers

| Fichier | Rôle |
|---|---|
| `Procfile` | Phase `release` (schéma) et processus `web` (Gunicorn) |
| `requirements.txt` | Cinq dépendances d'exécution, épinglées |
| `runtime.txt` | Version de Python |
| `backend/tools/release.py` | Applique schéma et migrations au déploiement |
| `backend/tools/pg_tests.py` | Suite contre PostgreSQL : local embarqué, ou Supabase en schéma isolé |
| `requirements-dev.txt` | `pgserver` — PostgreSQL 16 embarqué, tests seulement |
| `backend/tests/test_production.py` | 15 tests sur les défauts de déploiement |
| `backend/tests/test_sql_dialect.py` | +6 tests sur les commentaires SQL (§1.6) |
| `backend/.env.example` | Toutes les variables, commentées |
| `tools/supabase.sh` | `etat`, `verifier`, `mot-de-passe` |

## 6. Variables d'environnement

| Variable | Défaut | Rôle |
|---|---|---|
| `KLASSIO_DB_BACKEND` | `sqlite` | `sqlite` ou `postgres` |
| `SUPABASE_DB_URL` | — | Chaîne du pooler, obligatoire en mode postgres |
| `SUPABASE_URL` | — | URL du projet |
| `SUPABASE_ANON_KEY` | — | Clé publiable |
| `KLASSIO_ALLOWED_ORIGINS` | vide | Origines CORS en plus du développement, séparées par des virgules |
| `KLASSIO_PG_POOL_SIZE` | `5` | Connexions gardées ouvertes entre les requêtes |
| `KLASSIO_PG_SCHEMA` | `public` | Schéma PostgreSQL ; utilisé par `pg_tests.py` |
