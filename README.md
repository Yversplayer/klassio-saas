# Klassio — SaaS de gestion scolaire

Plateforme de gestion financière et administrative pour établissements scolaires. *La clarté derrière chaque établissement.*

## Tester Klassio

En deux temps : d'abord **comme un programmeur** — le code tient-il ? — puis
**comme un utilisateur** — le produit fait-il ce qu'il promet ? Toutes les
commandes se lancent depuis la racine du dépôt. Vérifié le 25/09/2026 sur un
clone vierge, avec Python 3.9.

### 1. Installer — une seule commande

```bash
python3 -m venv backend_venv
source backend_venv/bin/activate        # Windows : backend_venv\Scripts\activate
pip install -r requirements-dev.txt     # l'application ET les outils de test
```

### 2. Comme un programmeur

```bash
python -m unittest discover -s backend/tests -t backend    # 456 tests, SQLite, ~3 min
python backend/tools/pg_tests.py                            # la même suite sur un vrai PostgreSQL 16
```

Le second lance un PostgreSQL local, jetable, sans Docker ni réseau, puis le
détruit. Les deux doivent être verts.

Trois fichiers de tests disent l'essentiel de ce que le projet protège :

| Fichier | Ce qu'il prouve |
|---|---|
| `backend/tests/test_release_gate.py` | chaque route paramétrée, appelée avec les identifiants d'une **autre** école, est refusée |
| `backend/tests/test_plans.py` | aucune requête ne balaie une table qui grossit — le défaut qui aurait rendu Klassio inutilisable en janvier |
| `backend/tests/test_depot_public.py` | ce dépôt public ne contient aucun secret, aucune base, aucun jeton |

Pour aller plus loin : `AGENTS.md` (les règles du projet et pourquoi elles
existent), `REPRISE.md` (l'état et les défauts déjà corrigés),
`RAPPORT_PERFORMANCE.md` et `tools/k6/README.md` (charge, concurrence, isolation
sous charge).

### 3. Comme un utilisateur

Une base de démonstration **jetable** : un établissement fictif de 300 élèves,
avec notes, présences, incidents et paiements. Elle n'est jamais écrite dans
`backend/klassio.db` — l'outil refuse de toucher cette base.

```bash
export KLASSIO_DB_PATH=/tmp/klassio_demo.db
python backend/tools/seed_echelle.py --ecoles 1 --eleves 300 --jours 10 --sortie /tmp/klassio_comptes.json
python backend/app.py                   # API sur http://localhost:5001 — laissez tourner
```

Sous Windows (PowerShell), remplacez les deux premières lignes par
`$env:KLASSIO_DB_PATH="$env:TEMP\klassio_demo.db"` et
`--sortie "$env:TEMP\klassio_comptes.json"`.

Au démarrage, l'API affiche la base qu'elle utilise : vérifiez que c'est bien
`klassio_demo.db`. Puis, **dans un second terminal**, à la racine du dépôt :

```bash
python3 -m http.server 4173
```

Ouvrez **http://localhost:4173/app/connexion.html**. Mot de passe commun :
`ChargeKlassio2026!`

| Rôle | Identifiant | Ce qu'il doit voir |
|---|---|---|
| Direction | `direction@ecole1.charge.test` | tout l'établissement : 300 élèves, finances, rapports |
| Directeur des disciplines | `discipline@ecole1.charge.test` | la discipline du jour, les absences, les appels non faits |
| Professeur | `prof0@ecole1.charge.test` | **ses** classes seulement — 6 sur 42 |
| Parent | `parent0@ecole1.charge.test` | **ses** enfants seulement — 3 sur 300 |

Le plus instructif est d'essayer ce qui doit être **refusé** : ouvrir les
rapports en tant que parent, le dossier d'un enfant qui n'est pas le sien,
l'équipe en tant que professeur. Le refus vient du serveur, pas d'un bouton
masqué — il tient même en appelant l'API à la main.

Toutes les données sont fictives. Aucun e-mail ne part (`EMAIL_MODE=capture`) :
une invitation produit un lien à copier ou à partager par WhatsApp.

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

Non implémenté (documenté comme tel, jamais simulé — la liste qui fait foi est `AGENTS.md` §9) : envoi automatique d'OTP par SMS/WhatsApp (nécessite un fournisseur externe non connecté — la sécurité de l'invitation repose sur le token à usage unique), Store parent, pricing par palier d'élèves, Command Bar/IA réelle, rôles Caissier/Responsable financier, compte Élève (retiré intentionnellement — voir point 2 de la refonte), états de paiement avancés (remboursements, échecs).

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
