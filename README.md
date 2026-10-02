# Klassio — SaaS de gestion scolaire

Plateforme de gestion financière et administrative pour établissements scolaires. *La clarté derrière chaque établissement.*

## Démarrer — pour un développeur qui découvre Klassio

Tout ce qui suit a été rejoué sur un clone vierge du dépôt GitHub, le
01/10/2026 (macOS, Python 3.9). **Rien ne demande une clé, un compte ou un accès
à la production** : le dépôt n'en contient aucun, et l'environnement de
développement n'en a pas besoin.

### L'architecture en une minute

| | En développement | En production |
|---|---|---|
| **Un seul serveur** — Flask, `backend/app.py` : il sert les pages **et** l'API | `http://localhost:5001` | Render (`render.yaml`, `Procfile`) |
| **Pages** — HTML et JavaScript, **sans étape de build** | servies par ce même serveur | idem |
| **Base** | SQLite, un fichier local (`backend/klassio_demo.db`) | PostgreSQL |
| **E-mail** | capturé, rien ne part | Brevo |

> Il n'y a **plus** de second serveur de pages sur le port 4173 (retiré le
> 29/09) : ce montage faisait échouer les testeurs — appels perdus, « serveur
> injoignable », 504 derrière un proxy. Tout passe par `http://localhost:5001`.

Le frontend est servi tel qu'il est dans le dépôt : ni bundle ni source map. Le
schéma vit dans `backend/schema.sql` (`schema_postgres.sql` en est **généré**) ;
les migrations sont additives (`db._migrate()`) et s'appliquent à chaque
démarrage.

### Pas à pas — macOS et Linux

```bash
git clone https://github.com/Yversplayer/klassio-saas.git
cd klassio-saas
./installer.sh              # Python, dépendances, configuration, école fictive — ~2 min
./demarrer.sh --testeur     # lance Klassio ; Ctrl-C pour l'arrêter
```

Ouvrez **http://localhost:5001** (le site) ou **http://localhost:5001/app/connexion.html**.

- `./demarrer.sh --reseau --testeur` : accessible aussi depuis un téléphone sur
  le même Wi-Fi (l'adresse s'affiche au démarrage).
- `./installer.sh --recreer` : remet l'école fictive à zéro.

### Pas à pas — Windows

```bat
git clone https://github.com/Yversplayer/klassio-saas.git
cd klassio-saas
python -m venv backend_venv
backend_venv\Scripts\activate
pip install -r requirements-dev.txt
copy backend\.env.example backend\.env
python backend\tools\demo.py
set KLASSIO_CONTOURNER_ABONNEMENT=1
python backend\app.py
```

Puis **http://localhost:5001**. (PowerShell : `$env:KLASSIO_CONTOURNER_ABONNEMENT="1"` au lieu de `set`.)

### Le mode testeur — pourquoi `--testeur`

Il n'existe **pas de mode gratuit** : une école créée par « Créer mon espace »
dépose ses fichiers Excel, choisit son offre, et ne s'ouvre qu'une fois son
premier paiement déclaré (ouverture provisoire de 72 h) puis confirmé par la
plateforme. Le mode testeur (`KLASSIO_CONTOURNER_ABONNEMENT=1`) lève ces
blocages pour tester le reste du logiciel : l'étape « Votre offre » affiche
alors « Entrer sans payer (testeur) ». C'est un réglage du **serveur**, refusé
si la base visée n'est pas sur votre machine. Lancez sans `--testeur` pour
éprouver le vrai parcours payant (voir plus bas).

Au démarrage, le serveur écrit la base qu'il utilise. Vérifiez que c'est
`backend/klassio_demo.db` : c'est la preuve que vous êtes sur les données
fictives.

### Les tests automatiques

```bash
backend_venv/bin/python -m unittest discover -s backend/tests -t backend    # ~3 min, SQLite
backend_venv/bin/python backend/tools/pg_tests.py                            # la même suite sur un vrai PostgreSQL 16
```

Le second démarre un PostgreSQL local et jetable, sans Docker, sans droits
administrateur et sans réseau, puis le détruit. Les deux doivent être verts.
(Windows : `backend_venv\Scripts\python` au lieu de `backend_venv/bin/python`.)

### Les comptes de démonstration

`demo.py` crée une école **fictive** : 300 élèves, leurs notes, leurs présences,
leurs incidents et leurs paiements. Son nom se termine par **« DÉMONSTRATION »**
et s'affiche en tête de chaque écran. Les données sont reproductibles (graine
fixe) : deux développeurs obtiennent exactement les mêmes élèves.

Mot de passe commun : `ChargeKlassio2026!`

| Rôle | Identifiant | Ce qu'il doit voir |
|---|---|---|
| Direction | `direction@ecole1.charge.test` | tout l'établissement : 300 élèves, finances, rapports |
| Directeur des disciplines | `discipline@ecole1.charge.test` | la discipline du jour, les absences, les appels non faits |
| Professeur | `prof0@ecole1.charge.test` | **ses** classes seulement — 6 sur 42 |
| Parent | `parent0@ecole1.charge.test` | **ses** enfants seulement — 3 sur 300 |

Ces comptes n'existent que sur votre machine. Leurs adresses appartiennent au
domaine `.test`, réservé : aucune n'existe réellement. Le mot de passe est
publié ici précisément parce qu'aucune base réelle ne peut le recevoir :
**les outils de démonstration refusent toute base PostgreSQL distante.**

Le plus instructif est d'essayer ce qui doit être **refusé** : les rapports en
tant que parent, le dossier d'un enfant qui n'est pas le sien, l'équipe en tant
que professeur. Le refus vient du serveur, pas d'un bouton masqué — il tient
même en appelant l'API à la main.

`python backend/tools/demo.py --recreer` reconstruit la base à l'identique. Il
refuse d'effacer un fichier qui contiendrait un seul compte hors du domaine
fictif.

Le compte **Direction** a aussi l'accès **Plateforme** (rubrique Plateforme de
la barre latérale) : c'est lui qui confirme ou rejette les paiements déclarés.

### Tester Klassio de fond en comble

Une heure suffit pour tout voir. Cochez au fur et à mesure ; ce qui doit être
**refusé** compte autant que ce qui doit marcher.

**1. Le site et la démo** — http://localhost:5001
- [ ] La landing défile jusqu'au pied de page (rideau « Prêt à commencer ? »), sur ordinateur puis en format téléphone.
- [ ] Tarifs : quatre offres ; « Choisir École » ouvre l'inscription avec École présélectionnée.
- [ ] La démo (`/demo.html`) : l'appel, le portail, le dossier en coupe, le mur d'écrans, puis la visite interactive.

**2. Chaque rôle, avec les comptes ci-dessus**
- [ ] Direction : élèves, classes, présences, résultats (import Excel, proclamation, bulletins PDF), finances, reçus, rapports, exports, équipe et invitations, assistant.
- [ ] Directeur des disciplines : « Aujourd'hui », pointage au portail, incidents, convocations, registres.
- [ ] Professeur : ses classes seulement, l'appel, le cahier de communication, livres et devoirs.
- [ ] Parent : ses enfants seulement, présences, résultats proclamés, frais et reçus, boutique, justifier une absence.
- [ ] **Refusé** : les rapports en parent, le dossier d'un enfant qui n'est pas le sien, l'équipe en professeur — même en appelant l'API à la main.

**3. Une nouvelle école, en mode testeur** (`./demarrer.sh --testeur`)
- [ ] « Créer mon espace » → importer `docs/exemples/Complexe_Scolaire_La_Reference_export.xlsx` (2 371 élèves **fictifs**, générés par script) → « Votre offre » propose Complexe (l'effectif dépasse 1 000) → « Entrer sans payer (testeur) ».
- [ ] Inviter un professeur et un parent (le lien d'invitation s'affiche à l'écran — aucun e-mail ne part en développement), se connecter avec eux.
- [ ] Partout où l'on crée un mot de passe : « Proposer un mot de passe » donne une phrase de passe (quatre mots et un nombre), « Copier », « Un autre », « Afficher / Masquer ».

**4. Le vrai parcours payant** (`./demarrer.sh`, **sans** `--testeur`)
- [ ] Créer une école : l'espace est **fermé** (toute page renvoie vers Abonnement).
- [ ] Choisir une offre → une facture apparaît → déclarer une référence de paiement : l'espace **s'ouvre** (72 h), bandeau « Paiement en cours de vérification ».
- [ ] Se connecter en Direction de l'école fictive → Plateforme → **confirmer** le paiement : l'école reste ouverte. Ou **annuler** la facture : elle se referme, et une nouvelle déclaration ne la rouvre plus.

**Repartir de zéro** : `./installer.sh --recreer` (l'école fictive), et supprimez
les écoles de test créées à la main en recréant la base de la même façon.

Un défaut ? Notez la page, le rôle, ce que vous attendiez, ce qui s'est passé,
et le contenu de `/tmp/klassio.log` (macOS/Linux) au même moment.

### Variables d'environnement

Elles sont toutes documentées dans `backend/.env.example` : rôle, valeur de
développement, et si elles sont requises en production ou secrètes. Klassio
n'en lit **aucune autre**. En développement, le modèle copié tel quel suffit ;
les valeurs secrètes (`DATABASE_URL`, `EMAIL_API_KEY`) restent vides.

### Services externes

| Service | Variable | Nature | Requis en local ? | Requis en production ? | En local, à la place |
|---|---|---|---|---|---|
| PostgreSQL (Render, Supabase…) | `DATABASE_URL` | secret | non | oui | SQLite ; PostgreSQL jetable pour les tests |
| E-mail (Brevo) | `EMAIL_API_KEY` | secret | non | oui, pour envoyer | `EMAIL_MODE=capture` : rien ne part |
| Supabase, API REST | `SUPABASE_*` | publiques et secrète | non | non | — Klassio ne s'en sert pas |
| Polices Google Fonts | — | public | chargées par le navigateur | — | sans réseau, polices du système |

**Ne sont pas construits** — et le dépôt ne simule rien : SMS, paiement et
Mobile Money (« mobile money » est un mode de paiement **déclaré** à la main,
avec sa référence), stockage dans le nuage, OAuth, modèle d'IA externe
(l'assistant fonctionne par règles locales), supervision, statistiques de
visite, webhooks entrants.

### Les tests, par catégorie

| Catégorie | Commande | Ce qu'il faut |
|---|---|---|
| Unitaires et intégration | `python -m unittest discover -s backend/tests -t backend` | rien — tout est local |
| La même suite sur PostgreSQL | `python backend/tools/pg_tests.py` | rien — PostgreSQL jetable embarqué |
| Charge et concurrence | voir `tools/k6/README.md` | k6 installé, base jetable |
| Contre une vraie base | `pg_tests.py --supabase`, `tools/pg_check.py` | la chaîne de connexion **du propriétaire** — jamais nécessaire pour développer |

Quatre fichiers de tests disent l'essentiel de ce que le projet protège :

| Fichier | Ce qu'il prouve |
|---|---|
| `backend/tests/test_release_gate.py` | chaque route, appelée avec les identifiants d'une **autre** école, est refusée |
| `backend/tests/test_plans.py` | aucune requête ne balaie une table qui grossit — le défaut qui aurait bloqué Klassio en janvier |
| `backend/tests/test_depot_public.py` | ce dépôt ne contient aucun secret, aucune base, aucun jeton |
| `backend/tests/test_garde_fous_locaux.py` | un poste de développement ne peut ni peupler ni effacer une vraie base |

### Problèmes connus

- **Le port 5001 doit être libre.** Les pages appellent l'API à cette adresse, et
  leur politique de sécurité (CSP) n'en autorise pas d'autre.
- **« Mot de passe oublié » ne peut pas aboutir en local** : aucun e-mail ne
  part, et seul le fait qu'un message a été émis est enregistré, pas son
  contenu. Utilisez les comptes de démonstration.
- **Une invitation** produit un lien à copier ou à partager par WhatsApp : c'est
  le mécanisme réel, il fonctionne en local.
- **Windows** : les commandes sont données, elles n'ont pas été rejouées.
- **Python** : vérifié en 3.9 ; la production tourne en 3.11 (`runtime.txt`).

Pour aller plus loin : `AGENTS.md` (les règles du projet et pourquoi elles
existent), `REPRISE.md` (l'état et les défauts déjà corrigés),
`RAPPORT_PERFORMANCE.md`.

## Structure du projet

```
index.html, app/*.html        Frontend (landing, inscription, dashboard, écrans de gestion)
assets/css/, assets/js/       Design system + logique frontend
backend/                      API Flask réelle (auth, multi-tenant, RBAC, Financial Core, événements, notifications)
docs/                         Documents de conception et rapports (voir ci-dessous)
```

## État réel du projet — à lire avant tout

Ce projet a délibérément été construit en documentant honnêtement ce qui est réel vs planifié à chaque étape. **Ne pas supposer qu'une fonctionnalité existe parce qu'elle est décrite dans `docs/` — chaque document précise son propre état.**

Fonctionnel et testé : authentification, isolation multi-tenant, RBAC, Financial Core (obligations/paiements/soldes toujours dérivés), notifications groupées, audit log, recherche/filtre client sur la liste d'élèves.

**Onboarding et rôles (refonte)** : le directeur crée seul son espace (plus de sélecteur de rôle libre à l'inscription — professeur/parent/élève ont été retirés du flux public). Il peut ensuite :
- **importer un fichier Excel/CSV réel** (`backend/ingestion.py` + `POST /api/onboarding/analyze-import` puis `/confirm-import`) : détection de colonnes par motifs, détection de doublons et d'anomalies financières, aperçu complet, rien n'est écrit avant confirmation explicite ;
- **inviter professeurs et parents** (`app/invitations.html`, table `invitations`) : lien à usage unique, expirant sous 7 jours, révocable, le rôle est toujours déterminé par l'invitation et jamais par un choix du client. Le parent accepte via `app/invitation.html`, qui affiche uniquement l'établissement et le(s) enfant(s) associés à cette invitation précise — jamais une recherche libre. Partage du lien par copie ou WhatsApp (lien `wa.me` prérempli — pas d'envoi automatique, aucun fournisseur SMS/WhatsApp n'est connecté).

Non implémenté (documenté comme tel, jamais simulé — la liste qui fait foi est `AGENTS.md` §9) : envoi automatique d'OTP par SMS/WhatsApp (nécessite un fournisseur externe non connecté — la sécurité de l'invitation repose sur le token à usage unique), Command Bar/IA réelle, rôles Caissier/Responsable financier, compte Élève (retiré intentionnellement — voir point 2 de la refonte), états de paiement avancés (remboursements, échecs).

## Documents de référence (`docs/`)

| Document | Contenu |
|---|---|
| `OBJECTIFS_ET_FONCTIONNALITES.md` | Vision produit d'origine |
| `SYSTEME_IA.md` | Conception de la couche IA (ambiante, jamais un chatbot) |
| `SECURITE.md` | Architecture de sécurité complète |
| `FINANCE.md` | Conception du Financial Core |
| `IMPORT.md` | Conception du moteur d'import |
| `EVENEMENTS.md` | Event Engine / Rule Engine / Notification Engine |
| `MULTI_TENANT.md` | Architecture d'isolation entre établissements |
| `DASHBOARDS_RECHERCHE.md` | Dashboards et Command Bar |
| `AUDIT_STRATEGIQUE.md` | Recadrage stratégique après la phase de conception |
| `RAPPORT_SIMULATION.md` | **Rapport de test grandeur nature réel** (2 844 élèves, 2 écoles) — mesures de performance, résultat de l'isolation multi-tenant, problèmes trouvés et corrigés |

## Identité

Nom : **Klassio** · Palette : crème chaude, vert forêt, lime, or doux · Typographie : Plus Jakarta Sans + Fraunces.
