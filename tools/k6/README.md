# Tests de charge Klassio (K6)

Ne montez pas en charge sur un système dont le scénario de fumée échoue : vous
mesureriez la vitesse d'une panne.

**Une commande pour tout :** `k6 run tools/k6/complet.js` enchaîne les huit
scénarios fonctionnels et rend un seul verdict. Chaque scénario reste
exécutable seul — c'est la façon normale de travailler quand on corrige un
point précis.

### Fonctionnel — ce qui doit être vrai

| Scénario | Ce qu'il prouve | Seuil bloquant |
|---|---|---|
| `smoke.js` | chaque parcours critique renvoie les **bonnes données**, pas juste un 200 | `checks: rate==1.00` |
| `rbac.js` | chaque rôle voit ce qu'il doit voir, et rien d'autre — jeton absent, jeton forgé compris | `acces_non_autorises == 0` |
| `isolation.js` | deux établissements travaillent en même temps sans jamais se voir | `fuites == 0` |
| `invitations.js` | cycle de vie complet d'un accès : création, escalade refusée, usage unique, révocation immédiate | `acces_apres_revocation == 0` |
| `academique.js` | saisie ≠ proclamation, versions des notes, ce que le parent voit et quand | `notes_non_proclamees_vues == 0` |
| `regressions.js` | les défauts déjà corrigés ne sont pas revenus | `erreurs_500 == 0` |
| `concurrence.js` | ce qui se passe quand deux personnes agissent **en même temps** | `surpaiements == 0` |
| `ia.js` | l'assistant lit, n'écrit jamais, et ne fuit pas d'un établissement à l'autre | `ia_ecritures == 0` |
| `complet.js` | l'orchestrateur — les huit ci-dessus, dans l'ordre, un seul verdict | tous les précédents |

### Charge — jusqu'où ça tient

| Scénario | Ce qu'il mesure |
|---|---|
| `charge.js` | une matinée d'école : `-e PALIER=N` utilisateurs, `-e DUREE=S` de plateau |
| `pic.js` | l'à-coup : tout le monde arrive d'un coup |
| `finance.js` | des guichets simultanés ne comptent jamais un paiement deux fois |
| `recus.js` | sous concurrence, aucun paiement confirmé ne reste sans reçu |
| `paliers.sh` | balaie 1 → 5 → 10 → 25 → 50 → 100 VUs et dresse le tableau p50/p90/p95/p99 |

### La limitation anti-abus et les tests

Les routes publiques qui protègent un secret — acceptation d'invitation,
réinitialisation de mot de passe — sont plafonnées PAR ADRESSE IP. Depuis le
18/09, **seul un échec sur le secret consomme le budget** : une acceptation
réussie efface l'ardoise de l'adresse (même règle que la connexion).

Conséquence pour les tests : le seeder crée ses comptes de rôle en acceptant de
vraies invitations, et n'entame plus le compteur. Deux campagnes `complet.js`
enchaînées passent sans attendre — vérifié. Si un 429 apparaît malgré tout,
c'est qu'un scénario présente des jetons INVALIDES en rafale : regardez le
scénario avant de soupçonner la protection.

## Préparer l'environnement

Les scripts lisent `tools/k6/env.json`, produit par le seeder. **Jamais sur la
base de travail** : le script refuse de peupler `backend/klassio.db`.

```bash
# Base jetable + 2 établissements (2 000 et 500 élèves) + un compte par rôle
KLASSIO_DB_PATH=/tmp/klassio_charge.db \
  backend_venv/bin/python backend/tools/seed_charge.py \
  --eleves 2000 --base-url http://127.0.0.1:5010
```

Puis démarrez le serveur sur cette même base, en configuration de production :

```bash
KLASSIO_DB_PATH=/tmp/klassio_charge.db PORT=5010 \
  backend_venv/bin/gunicorn --chdir backend --workers 2 --threads 4 \
  --worker-class gthread --bind 127.0.0.1:5010 app:app
```

## Lancer

```bash
k6 run tools/k6/complet.js                 # toute la campagne fonctionnelle
k6 run tools/k6/smoke.js                   # ou un scénario à la fois
k6 run tools/k6/concurrence.js
k6 run -e PALIER=60 tools/k6/charge.js     # 60 utilisateurs simultanés
k6 run -e PALIER=60 -e DUREE=45 tools/k6/charge.js
tools/k6/paliers.sh 45                     # le balayage complet + le tableau
```

`finance.js` **écrit** : il enregistre de vrais paiements. Il vise
volontairement l'établissement `beta` et une base jetable.

## Lire les résultats

Les seuils viennent de mesures réelles sur SQLite en local, avec une marge pour
le réseau. Un seuil dépassé se comprend avant de se relever :

- `http_req_duration{name:login}` élevé est **normal** — le hachage de mot de
  passe fait 200 000 itérations PBKDF2, c'est une protection voulue.
- `klassio_liste_eleves` dépend surtout de la taille de l'établissement. La
  réponse est compressée (892 Ko → 126 Ko sur 2 340 élèves).
- Un `429` sous charge n'est pas une erreur : c'est la limitation anti-abus qui
  fonctionne. `charge.js` se connecte une fois par rôle dans `setup()` pour ne
  pas la déclencher — un scénario qui se reconnecte à chaque itération la
  déclenchera, à juste titre.

## Sans K6

`backend/tools/charge_locale.py` rejoue les mêmes scénarios en Python, sans
dépendance externe. Moins précis en métrologie, mais suffisant pour vérifier
qu'une régression n'est pas passée.

```bash
backend_venv/bin/python backend/tools/charge_locale.py --utilisateurs 30 --duree 30
```
