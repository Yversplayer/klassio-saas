# Klassio — SaaS de gestion scolaire

Plateforme de gestion financière et administrative pour établissements scolaires. *La clarté derrière chaque établissement.*

## Démarrer — pour un développeur qui découvre Klassio

Tout ce qui suit a été rejoué sur un clone vierge, le 25/09/2026 (macOS,
Python 3.9). **Rien ne demande une clé, un compte ou un accès à la
production** : le dépôt n'en contient aucun, et l'environnement de développement
n'en a pas besoin.

### L'architecture en une minute

| | En développement | En production |
|---|---|---|
| **API** — Flask, `backend/app.py` | `http://localhost:5001` | Render (`render.yaml`, `Procfile`) |
| **Pages** — HTML et JavaScript, **sans étape de build** | `http://localhost:4173` | Vercel (`vercel.json`) |
| **Base** | SQLite, un fichier local | PostgreSQL |
| **E-mail** | capturé, rien ne part | Brevo |

Le frontend est servi tel qu'il est dans le dépôt : ni bundle ni source map, et
aucune variable d'environnement ne lui parvient. Il ne connaît qu'une adresse,
celle de l'API. Le schéma vit dans `backend/schema.sql` (`schema_postgres.sql`
en est **généré**) ; les migrations sont additives (`db._migrate()`) et
s'appliquent à chaque démarrage.

### Pas à pas

```bash
# 1. Cloner
git clone https://github.com/Yversplayer/klassio-saas.git
cd klassio-saas

# 2. Installer — l'application et les outils de test
python3 -m venv backend_venv
source backend_venv/bin/activate            # Windows : backend_venv\Scripts\activate
pip install -r requirements-dev.txt

# 3–4. Configurer — le modèle est déjà complet, il n'y a rien à remplir
cp backend/.env.example backend/.env        # Windows : copy backend\.env.example backend\.env

# 5–7. Créer la base, appliquer schéma et migrations, charger les données fictives
python backend/tools/demo.py

# 8. Lancer l'API — laissez ce terminal ouvert
python backend/app.py

# 9. Servir les pages — dans un SECOND terminal, à la racine du dépôt
python -m http.server 4173
```

**10.** Ouvrez **http://localhost:4173/app/connexion.html**.

**11.** Les tests :

```bash
python -m unittest discover -s backend/tests -t backend    # ~3 min, SQLite
python backend/tools/pg_tests.py                            # la même suite sur un vrai PostgreSQL 16
```

Le second démarre un PostgreSQL local et jetable, sans Docker, sans droits
administrateur et sans réseau, puis le détruit. Les deux doivent être verts.

Au démarrage, l'API écrit la base qu'elle utilise. Vérifiez que c'est
`backend/klassio_demo.db` : c'est la preuve que vous êtes sur les données
fictives.

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
