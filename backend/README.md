# Klassio — Backend

API réelle (Flask + SQLite) derrière le frontend existant. Voir [docs/AUDIT_STRATEGIQUE.md](../docs/AUDIT_STRATEGIQUE.md) pour le contexte de la décision de stack, et le rapport de finalisation backend (dans la conversation) pour l'état précis module par module.

## Lancer en local

```bash
python3 -m venv ../backend_venv
source ../backend_venv/bin/activate
pip install -r requirements.txt
python3 app.py    # démarre sur http://localhost:5001, initialise klassio.db si absent
```

Le frontend (`python3 -m http.server 4173` à la racine du projet) appelle `http://localhost:5001/api` en dur (`assets/js/app.js`, constante `API_BASE`) — à rendre configurable avant un déploiement réel (voir dette technique).

## Lancer les tests

```bash
source ../backend_venv/bin/activate
python3 -m unittest tests.test_api -v
```

Utilise `klassio_test.db`, jamais la base de développement `klassio.db`.

## Pourquoi Python + Flask + SQLite

Décision prise faute de Node/npm et de PostgreSQL disponibles sur la machine de développement (voir `docs/AUDIT_STRATEGIQUE.md`), et confirmée pragmatique : réel, testé, sans dépendance à une installation système nécessitant des privilèges administrateur. **Limite connue** : SQLite ne supporte pas la Row-Level Security décrite dans `docs/MULTI_TENANT.md` §8 — l'isolation multi-tenant ici repose uniquement sur la couche applicative (chaque requête filtre explicitement par `tenant_id` résolu côté serveur), pas sur un second filet de sécurité au niveau base de données. Une migration vers PostgreSQL est nécessaire avant un déploiement réel avec des données sensibles de plusieurs écoles — c'est la dette technique la plus importante de cette version.

## Fichiers

- `schema.sql` — schéma complet, commenté avec renvois vers les documents de conception.
- `db.py` — connexion SQLite.
- `security.py` — mots de passe, sessions, résolution du tenant, RBAC, audit.
- `financial.py` — Financial Core (obligations, paiements, calcul de solde jamais stocké brut).
- `events.py`, `notifications.py` — Event Engine et Notification Engine (version MVP mono-processus, pas de queue distribuée).
- `app.py` — toutes les routes API.
- `tests/test_api.py` — tests d'intégration, dont l'isolation multi-tenant et l'idempotence des paiements.
