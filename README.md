# Klassio — SaaS de gestion scolaire

Plateforme de gestion financière et administrative pour établissements scolaires. *La clarté derrière chaque établissement.*

## Démarrage rapide

**1. Backend (API réelle — Flask + SQLite)**

```bash
cd backend
python3 -m venv ../backend_venv
source ../backend_venv/bin/activate
pip install -r requirements.txt
python3 app.py
```
Démarre sur `http://localhost:5001`. Voir [backend/README.md](backend/README.md) pour le détail (schéma, tests, choix de stack).

**2. Frontend (statique — aucun build requis)**

```bash
python3 -m http.server 4173
```
Ouvrir `http://localhost:4173`. Le frontend appelle l'API sur `http://localhost:5001` (voir `assets/js/app.js`, constante `API_BASE`).

**3. Tests backend**

```bash
cd backend
source ../backend_venv/bin/activate
python3 -m unittest tests.test_api -v
```

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

Non implémenté (documenté comme tel, jamais simulé) : envoi automatique d'OTP par SMS/WhatsApp (nécessite un fournisseur externe non connecté — la sécurité de l'invitation repose sur le token à usage unique), rattachement classe↔professeur (le dashboard professeur voit tout l'établissement, pas seulement « ses » classes), Store parent, pricing par palier d'élèves, Command Bar/IA réelle, rôles Caissier/Responsable financier, compte Élève (retiré intentionnellement — voir point 2 de la refonte), états de paiement avancés (remboursements, échecs).

## Documents de référence (`docs/`)

| Document | Contenu |
|---|---|
| `OBJECTIFS_ET_FONCTIONNALITES.md` | Vision produit d'origine |
| `SYSTEME_IA.md` | Conception de la couche IA (ambiante, jamais un chatbot) |
| `SECURITE.md` | Architecture de sécurité complète |
| `FINANCE.md` | Conception du Financial Core |
| `IMPORT.md` | Conception du moteur d'import (non implémenté) |
| `EVENEMENTS.md` | Event Engine / Rule Engine / Notification Engine |
| `MULTI_TENANT.md` | Architecture d'isolation entre établissements |
| `DASHBOARDS_RECHERCHE.md` | Dashboards et Command Bar |
| `AUDIT_STRATEGIQUE.md` | Recadrage stratégique après la phase de conception |
| `RAPPORT_SIMULATION.md` | **Rapport de test grandeur nature réel** (2 844 élèves, 2 écoles) — mesures de performance, résultat de l'isolation multi-tenant, problèmes trouvés et corrigés |

## Identité

Nom : **Klassio** · Palette : crème chaude, vert forêt, lime, or doux · Typographie : Plus Jakarta Sans + Fraunces.
