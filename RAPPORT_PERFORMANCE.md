# KLASSIO — audit de performance et de scalabilité

Mesures du 2026-09-13. Aucune ligne de Klassio n'a été modifiée pour cet audit :
tout ce qui suit décrit le produit tel qu'il est aujourd'hui.

---

## 1. Résumé exécutif

**Klassio tient la charge. Une seule route ne tient pas le volume — et c'est
celle dont un professeur se sert tous les matins.**

Sur PostgreSQL, avec 5 établissements peuplés (10 000 élèves, 800 000 lignes
d'appel), l'application encaisse **450 utilisateurs simultanés sans une seule
erreur applicative**, absorbe un pic ×30 en cinq secondes et revient à la
normale immédiatement. L'isolation entre établissements n'a jamais cédé : zéro
fuite sur plusieurs dizaines de milliers de tentatives croisées, à tous les
niveaux de charge.

Mais deux routes contiennent des sous-requêtes qui **omettent `tenant_id`**, la
colonne de tête de leurs index. Elles ne peuvent donc utiliser aucun index et
balayent toute la table `attendance` — laquelle grossit d'environ 10 000 lignes
par jour de classe et par tranche de 10 000 élèves.

Conséquence mesurée, pas extrapolée :

| Jours d'appel écoulés | `/api/classes/:id/students` |
|---|---|
| 20 (mi-octobre) | 8 s |
| 40 (mi-novembre) | 14 s |
| 80 (janvier) | **29 s à un seul utilisateur, > 60 s dès 10 utilisateurs** |

À partir de janvier environ, la liste des élèves d'une classe cesse de
répondre. C'est le point de rupture réel de Klassio, et il n'a rien à voir avec
le nombre d'utilisateurs : il vient du temps qui passe.

Le correctif est petit et son effet est mesuré : **2 418×** sur cette route.
Il n'a pas été appliqué — §7.

---

## 2. Conditions de mesure

Ce qui suit conditionne la lecture des chiffres absolus.

| | |
|---|---|
| Machine | portable 4 cœurs, 8 Go, **partagée** avec VS Code, Cursor et un navigateur |
| Charge machine au repos | 7,0 (élevée, imposée par les applications de l'utilisateur) |
| Serveur | Gunicorn 2 workers × 4 fils, configuration du `Procfile` |
| Générateur de charge | k6 v2.2.0, **sur la même machine** — il consomme donc les mêmes cœurs |
| Bases | SQLite 500 Mo, et PostgreSQL 16 local (le moteur de production visé) |
| Jeu de données | 5 écoles, 10 000 élèves, 800 000 présences, 120 000 notes, 6 031 paiements et reçus, 10 000 notifications, 1 000 incidents |

**Les débits absolus sont donc pessimistes** et ne préjugent pas de ce que
donnera un dyno dédié. Ce qui est transférable, et sur quoi repose ce rapport :
les **rapports** entre configurations, la **forme** des courbes, et les
**plans d'exécution SQL**, qui ne dépendent d'aucune machine.

Reproductibilité : `backend/tools/seed_echelle.py` régénère le jeu de données,
`tools/k6/audit.js` rejoue les scénarios, `tools/k6/resultats/campagne.json`
conserve les 42 paliers mesurés.

---

## 3. Tableau des performances

Profil « sain » (voir §5 pour le profil complet), PostgreSQL, 800 000 présences.

| Écoles | VU | req/s | méd | p90 | p95 | p99 | max | échec | 5xx | fuites | CPU |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 3 | 5 | 19,9 | 10 ms | 38 ms | 46 ms | 146 ms | 427 ms | 0 % | 0 | 0 | 18 % |
| 3 | 20 | 85,9 | 14 ms | 61 ms | 86 ms | 169 ms | 337 ms | 0 % | 0 | 0 | 76 % |
| 3 | 40 | 116,5 | 94 ms | 240 ms | 295 ms | 447 ms | 767 ms | 0 % | 0 | 0 | 140 % |
| 3 | 80 | 116,0 | 416 ms | 783 ms | 854 ms | 965 ms | 1 293 ms | 0 % | 0 | 0 | 142 % |
| 3 | 120 | 112,2 | 720 ms | 1 122 ms | 1 252 ms | 1 491 ms | 2 130 ms | 0 % | 0 | 0 | 144 % |
| 4 | 20 | 84,9 | 14 ms | 58 ms | 83 ms | 181 ms | 332 ms | 0 % | 0 | 0 | 75 % |
| 4 | 40 | 114,8 | 98 ms | 247 ms | 297 ms | 440 ms | 629 ms | 0 % | 0 | 0 | 142 % |
| 4 | 80 | 114,7 | 380 ms | 752 ms | 852 ms | 1 087 ms | 1 439 ms | 0 % | 0 | 0 | 146 % |
| 4 | 120 | 111,8 | 593 ms | 1 426 ms | 1 634 ms | 2 015 ms | 2 876 ms | 0 % | 0 | 0 | 143 % |
| 5 | 20 | 83,8 | 15 ms | 65 ms | 96 ms | 167 ms | 295 ms | 0 % | 0 | 0 | 84 % |
| 5 | 40 | 113,2 | 99 ms | 246 ms | 299 ms | 433 ms | 676 ms | 0 % | 0 | 0 | 140 % |
| 5 | 80 | 86,1 | 474 ms | 1 169 ms | 1 325 ms | 1 622 ms | 2 118 ms | 0 % | 0 | 0 | 146 % |
| 5 | 120 | 75,3 | 1 091 ms | 1 673 ms | 1 879 ms | 2 703 ms | 3 302 ms | 0 % | 0 | 0 | 133 % |
| 5 | 200 | 72,3 | 1 793 ms | — | 3 984 ms | 4 856 ms | 5 608 ms | 0,02 % | 0 | 0 | — |
| 5 | 300 | 75,8 | 2 722 ms | — | 6 429 ms | 7 463 ms | 8 001 ms | 0,49 % | 0 | 0 | — |
| 5 | 450 | 77,0 | 3 776 ms | — | 10 241 ms | 12 126 ms | 13 096 ms | 0,04 % | 0 | 0 | — |

Les rares échecs au-delà de 200 VU sont des `connection reset by peer` sur la
file d'attente TCP — la limite d'acceptation du système, pas une faute de
Klassio. **Aucune erreur applicative (5xx) n'a été produite à aucun palier.**

### Écritures

`POST /api/classes/:id/attendance`, appel d'une classe de 30 élèves :

| VU | médiane | p95 | max | 5xx |
|---|---|---|---|---|
| 5 | 41 ms | 93 ms | 107 ms | 0 |
| 10 | 42 ms | 120 ms | 133 ms | 0 |
| 20 | 97 ms | 240 ms | 382 ms | 0 |
| 40 | 374 ms | 845 ms | 1 472 ms | 0 |
| 60 | 723 ms | 1 252 ms | 1 410 ms | 0 |

Les écritures ne sont pas un goulot d'étranglement.

### Test de pic — 5 → 150 utilisateurs en 5 secondes

| Phase | médiane | p95 |
|---|---|---|
| Avant (5 VU) | 72 ms | 104 ms |
| Pendant (150 VU) | 2,32 s | 2,70 s |
| Après retour à 5 VU | **50 ms** | 54 ms |

2 064 requêtes sur 2 064 servies, **0 % d'erreur**. Le système encaisse le choc
et récupère intégralement — plus vite qu'avant le pic, cache chaud aidant.

---

## 4. Classement des endpoints

5 écoles, 800 000 présences, PostgreSQL.

### Zone stable (20 VU) — où se situe le coût réel

| Endpoint | médiane | p95 |
|---|---|---|
| `GET /api/discipline/today` | 222 ms | 469 ms |
| `GET /api/reports/summary` | 169 ms | 385 ms |
| `GET /api/dashboard` | 132 ms | 346 ms |
| `GET /api/students?q=` | 100 ms | 243 ms |
| `GET /api/students` (2 000 élèves) | 108 ms | 210 ms |
| `GET /api/students/:id` | 72 ms | 191 ms |
| `GET /api/students/:id/bulletin` | 39 ms | 189 ms |
| `GET /api/classes/:id/grades` | 57 ms | 161 ms |
| `GET /api/discipline/overview` | 58 ms | 144 ms |
| `GET /api/receipts` | 29 ms | 93 ms |
| `GET /api/notifications` | 10 ms | 75 ms |

### Zone dégradée (80 VU) — signature du goulot

Tous les endpoints convergent vers 550–1 050 ms de médiane, quel que soit leur
coût propre. **Quand tout dégrade uniformément, le facteur limitant est
partagé** — ici le nombre de workers, pas une requête particulière.

Seul `POST /api/auth/login` reste à 212 ms aux deux paliers : son coût est du
processeur pur (PBKDF2, 200 000 itérations — une protection voulue), et il
n'est pas mis en file d'attente dans nos scénarios.

---

## 5. Goulots d'étranglement

### 5.1 Le goulot principal : deux requêtes sans `tenant_id`

`/api/classes/:id/students` (api_school.py) contient trois sous-requêtes
corrélées **par élève** :

```sql
(SELECT COUNT(*) FROM attendance x WHERE x.student_id = s.id AND x.status = 'absent')
(SELECT COUNT(*) FROM attendance x WHERE x.student_id = s.id AND x.status = 'excused')
(SELECT COUNT(*) FROM attendance x WHERE x.student_id = s.id AND x.status = 'late')
```

L'index disponible est `idx_attendance_student(tenant_id, student_id, date)`.
La colonne de tête, `tenant_id`, est absente du filtre : **l'index est
inutilisable**.

Plans d'exécution PostgreSQL, mesurés sur 800 000 lignes :

| | plan | blocs lus | durée |
|---|---|---|---|
| Telle qu'écrite | `Parallel Seq Scan` | 26 618 | 81 ms |
| Avec `tenant_id` | `Bitmap Heap Scan` (index) | 84 | 0,59 ms |

81 ms × 3 sous-requêtes × 48 élèves ≈ 11,7 s — ce qui correspond à la mesure.

`/api/classes` souffre du même défaut, avec deux sous-requêtes par classe sur
`attendance`, filtrées sur `class_id` et `date` sans `tenant_id`.

**Le défaut est indépendant du moteur** : SQLite fait un `SCAN` là où
PostgreSQL fait un `Seq Scan`. Aucun des deux ne peut faire mieux avec cette
écriture.

### 5.2 Effet du volume — mesuré, pas extrapolé

SQLite, à un utilisateur, en faisant croître l'historique d'appel :

| Jours | Présences | `/api/classes` | `/api/classes/:id/students` | `/api/students` | `/api/dashboard` |
|---|---|---|---|---|---|
| 20 | 200 000 | 3,8 s | 8,0 s | 83 ms | 92 ms |
| 40 | 400 000 | 6,9 s | 13,9 s | 82 ms | 107 ms |
| 80 | 800 000 | **13,4 s** | **29,3 s** | 84 ms | 141 ms |

Croissance strictement linéaire pour les deux routes fautives. **Les routes
correctement indexées ne bougent pas** : `/api/students` renvoie 2 000 élèves
en 83 ms quel que soit le volume d'appel. Ce n'est donc pas un problème
d'architecture générale, mais deux requêtes précises.

### 5.3 Effet sous charge réelle

Profil complet (avec les deux routes), PostgreSQL, 5 écoles :

| VU | `/api/classes/:id/students` médiane | Débit global |
|---|---|---|
| 5 | 54,3 s | 7,1 req/s |
| 10 | > 60 s (délai dépassé) | 24,3 req/s |
| 20 | > 60 s (délai dépassé) | 18,6 req/s |

À comparer aux **84 req/s** du profil sain dans les mêmes conditions. Cette
seule route divise le débit du système par quatre à douze, et monopolise des
workers pendant une minute chacun.

### 5.4 Ce qui n'est PAS le goulot — vérifié

- **Le pool de connexions.** 14 connexions actives sur 100 disponibles. Le
  faire varier de 2 à 20 ne change rien de significatif (63–82 req/s, dans le
  bruit de la machine).
- **La mémoire.** 106–125 Mo côté serveur, stable sur toute la campagne, sans
  dérive après des dizaines de milliers de requêtes.
- **Les écritures.** Voir §3.
- **Le nombre d'établissements.** Voir §6.

### 5.5 SQLite n'est pas un moteur de production — confirmé par la mesure

À volume identique (800 000 présences) :

| Endpoint | SQLite | PostgreSQL | Écart |
|---|---|---|---|
| `/api/discipline/overview` | 199 ms | 13 ms | 15× |
| `/api/classes` | 13 412 ms | 215 ms | **62×** |
| `/api/reports/summary` | 214 ms | 56 ms | 3,8× |
| `/api/dashboard` | 141 ms | 42 ms | 3,4× |
| `/api/students` | 84 ms | 44 ms | 1,9× |
| `/api/classes/:id/students` | 29 259 ms | 21 819 ms | 1,3× |

Et sous charge, SQLite produit de vraies erreurs applicatives que PostgreSQL
ne produit jamais : **93 `database is locked` et 60 `disk I/O error`** au cours
de la campagne SQLite, contre **zéro** sur PostgreSQL. La cause est la
sérialisation des écritures — chaque refus d'autorisation écrit une ligne
d'audit, ce qui verrouille toute la base sous SQLite.

La décision déjà prise de viser PostgreSQL est donc confirmée par la mesure.

---

## 6. Scalabilité : de 3 à 5 établissements

| Écoles | Débit maximal | Palier atteint | Comportement au-delà |
|---|---|---|---|
| 3 | 116,5 req/s | 40 VU | plateau jusqu'à 120 VU |
| 4 | 114,8 req/s | 40 VU | plateau jusqu'à 120 VU |
| 5 | 113,2 req/s | 40 VU | décroissance : 86 req/s à 80 VU, 75 à 120 |

**Passer de 3 à 4 établissements ne coûte rien** (−1,5 %). Passer à 5 ne coûte
rien non plus au palier de saturation (−1,2 % à 40 VU), mais le débit décroît
ensuite plus tôt : les jeux de travail de cinq écoles ne tiennent plus
simultanément dans les 8 Go de la machine, et le cache commence à manquer.

Autrement dit : **le nombre d'établissements n'est pas un facteur limitant de
l'architecture**, c'est un facteur de mémoire. Le multi-tenant de Klassio
partitionne correctement — chaque requête reste bornée à son locataire.

---

## 7. Point de rupture

La frontière demandée, mesurée sur PostgreSQL, 5 écoles :

| Zone | Charge | Médiane | p95 | Erreurs |
|---|---|---|---|---|
| **STABLE** | ≤ 20 VU | 10–15 ms | < 100 ms | 0 |
| **DÉGRADATION** | 40 – 120 VU | 99 ms → 1,1 s | 300 ms → 1,9 s | 0 |
| **SATURATION** | 200 – 450 VU | 1,8 s → 3,8 s | 4 s → 10 s | ≤ 0,5 % |
| **ÉCHEC** | *jamais atteint* | — | — | — |

**Klassio ne casse pas.** Même à 450 utilisateurs simultanés — bien au-delà de
ce que cinq écoles produiraient — il met en file d'attente au lieu de
s'effondrer, sans une seule erreur applicative. Le débit se stabilise autour de
75 req/s et la latence croît linéairement avec la profondeur de file. C'est le
comportement sain qu'on attend d'un système correctement construit.

La limite pratique n'est donc pas un effondrement mais un **seuil
d'utilisabilité** : au-delà d'environ **40 utilisateurs simultanés par
instance** sur cette machine, le p95 dépasse 300 ms et continue de croître.

**Le vrai point de rupture de Klassio n'est pas la charge : c'est le temps.**
Vers 80 jours de classe — janvier pour une rentrée en septembre —
`/api/classes/:id/students` dépasse le délai de 30 secondes de Gunicorn et du
routeur Heroku. La route cesse alors de fonctionner, quel que soit le nombre
d'utilisateurs.

---

## 8. Isolation multi-tenant sous charge

Vérifiée en continu pendant **toute** la campagne, à tous les paliers jusqu'à
450 VU : chaque itération de chaque utilisateur virtuel tente d'atteindre le
dossier d'un élève, une classe et une recherche d'une **autre** école.

**Zéro fuite.** Plusieurs dizaines de milliers de tentatives croisées, toutes
refusées par 404. Contrôle exhaustif complémentaire : les 20 combinaisons
directeur × école étrangère renvoient 404, et chaque directeur accède bien à
ses propres données.

La performance n'a jamais été obtenue au détriment de l'isolation.

> Deux fausses alertes ont été produites en cours d'audit par la sonde
> elle-même — d'abord parce qu'elle ne retrouvait pas sa session dans les
> données recopiées par k6 et interrogeait sa propre école, ensuite parce
> qu'elle comparait des patronymes que le générateur produit à l'identique dans
> toutes les écoles. Les deux ont été vérifiées en direct, réfutées, et la
> sonde corrigée pour comparer des identifiants. Aucune fuite réelle n'a été
> observée à aucun moment.

---

## 9. Recommandations — par priorité, non appliquées

### P1 — Ajouter `tenant_id` aux sous-requêtes (effet mesuré : 2 418×)

`backend/api_school.py`, route `class_students` : les trois sous-requêtes
`attendance` et celle sur `incidents` doivent filtrer sur `x.tenant_id =
s.tenant_id`. Idem dans `backend/app.py`, route `list_classes`, pour les deux
sous-requêtes `attendance` (`a.tenant_id = c.tenant_id`).

Mesuré sur la requête complète, 48 élèves, 800 000 présences :

| | durée |
|---|---|
| Telle qu'écrite | 29 875 ms |
| Avec `tenant_id` | **12,4 ms** |

C'est un changement de quelques caractères, sans effet sur le résultat renvoyé
— le filtre est redondant du point de vue métier, puisque les élèves d'une
classe appartiennent déjà au locataire. Il n'est indispensable qu'au
planificateur.

**À faire avant toute mise en production.** Sans lui, chaque école cessera de
pouvoir consulter ses classes vers le milieu de l'année.

### P2 — Un garde-fou contre la réapparition du défaut

Le défaut est invisible en développement : la base de travail contient 249
lignes d'appel, où un balayage complet coûte moins qu'un index. Il n'apparaît
qu'en volume. Deux protections complémentaires :

- un test qui vérifie le PLAN d'exécution des requêtes sensibles (`SEARCH` /
  `Index Scan` attendu, jamais `SCAN` / `Seq Scan`) ;
- l'exécution périodique de `seed_echelle.py` + `audit.js` en intégration
  continue, avec un seuil sur les routes concernées.

### P3 — Revoir les agrégats du tableau de bord

`/api/dashboard` exécute 28 requêtes, dont plusieurs `COUNT(*)` sans `LIMIT`
sur des tables qui grossissent toute l'année. Il tient aujourd'hui (132 ms à
20 VU) mais sa croissance est réelle : 92 → 141 ms quand l'historique
quadruple. À surveiller, à traiter si le produit vise des établissements
beaucoup plus grands.

### P4 — Dimensionnement

Le CPU plafonne à ~145 % pour deux workers, la mémoire à 125 Mo. Sur un dyno
dédié, `WEB_CONCURRENCY` peut monter sans risque — les compteurs
anti-force-brute sont désormais partagés en base. Le pool PostgreSQL n'a pas
besoin d'être augmenté : 14 connexions suffisent.

---

## 10. Ce qui n'a pas été vérifié

**NON VÉRIFIÉ — le comportement sur Supabase depuis un dyno européen.** Les
mesures PostgreSQL ont été faites sur une instance locale, sans latence réseau.
Le pooler Supabase en mode transaction peut se comporter différemment.
→ Rejouer `audit.js` depuis l'hébergement réel une fois celui-ci en place.

**NON VÉRIFIÉ — un test d'endurance (soak).** La campagne la plus longue a duré
60 secondes par palier. Une fuite de mémoire lente ou une dérive de cache ne
serait pas visible. La mémoire est restée plate sur l'ensemble de la campagne,
ce qui est rassurant mais ne remplace pas plusieurs heures de charge continue.
→ Un palier de 2 h à 20 VU, à faire en staging.

**NON VÉRIFIÉ — la concurrence réelle sur les écritures financières sous charge
k6.** L'idempotence des paiements a été vérifiée séparément (300 paiements
concurrents, aucun double comptage), mais pas dans le même run que la charge de
lecture.

**MESURÉ AVEC RÉSERVE — les débits absolus.** Machine partagée avec
l'environnement de travail de l'utilisateur, k6 sur les mêmes cœurs. Les
rapports et les plans d'exécution sont fiables ; les req/s ne sont pas une
prévision de production.
