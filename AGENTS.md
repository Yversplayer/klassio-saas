# AGENTS.md — à lire avant de toucher à Klassio

Ce fichier s'adresse à tout agent IA qui intervient sur ce dépôt.

Klassio est un SaaS de gestion scolaire multi-établissement pour la RDC,
destiné à un pilote dans une vraie école. Il manipule des dossiers d'élèves,
des résultats officiels et de l'argent. Une partie du code a été auditée,
exploitée puis corrigée : ce qui ressemble à une lourdeur y est souvent une
protection payée par un bug réel.

**Lis `REPRISE.md` avant toute chose.** Il contient l'état du projet et le
détail des défauts déjà trouvés et corrigés. Ne redécouvre pas ce qui y est
écrit ; ne rouvre pas ce qui y est marqué comme décidé.

> ### 🔒 La page d'accueil est FIGÉE
>
> `index.html`, `assets/js/main.js` et les blocs « landing » de
> `assets/css/style.css` sont **terminés et validés**. Ils ne sont plus
> ouverts aux améliorations spontanées : pas de refonte, pas de « nettoyage »,
> pas de retouche du hero ni des effets de défilement.
> **Lis `LANDING_FIGEE.md` avant d'y écrire une seule ligne** — il dit ce qui
> reste permis (corriger un vrai défaut, une régression) et les sept décisions
> à ne pas défaire.
> La suite du travail, c'est **la démo** (`demo.html`), pas la landing — et
> elle, elle est ouverte : voir §3.

---

## 1. Ce qui est protégé — les garanties, pas les fichiers

Tu peux modifier n'importe quel fichier. Tu ne peux **pas** affaiblir les
garanties ci-dessous. Chacune a coûté un bug reproduit en conditions réelles.

### Isolation entre établissements

Chaque table métier porte `tenant_id`, et il n'est **jamais** fourni par le
client. Toute requête le filtre. Une ressource d'un autre établissement répond
**404**, jamais `200 []` — un tableau vide affirme « cette ressource existe, elle
est vide », ce qui est déjà une information.

Un balayage automatique (`backend/tests/test_release_gate.py`) appelle chaque
route paramétrée avec les identifiants d'une autre école. **Si tu ajoutes une
route paramétrée, ajoute son paramètre à `TABLE_PAR_PARAMETRE`** et assure-toi
qu'une donnée de test existe, sinon ta route sort silencieusement du filet.

### L'autorisation est côté serveur, toujours

Le rôle, l'établissement, le périmètre et les permissions viennent de la
session. Jamais d'un corps de requête, jamais d'un paramètre, jamais du
navigateur. `backend/school.py` est la source de vérité des périmètres :
Direction, DD, professeur, parent. Ne contourne pas ce module.

### Le navigateur ne décide de rien

Deux exemples à ne pas défaire :

- **Audience de proclamation** : le client envoie des CRITÈRES (classes,
  niveaux, élèves) ; le serveur repart des élèves réels et recalcule. Un
  identifiant d'un autre établissement, une classe étrangère ou un
  identifiant inventé ne produisent aucun destinataire.
- **Confirmation d'import** : les compteurs (lignes rapprochées, erreurs,
  version) sont relus depuis la session serveur. Un navigateur qui annonce
  « 60 rapprochés, 0 erreur » sur un fichier qui en compte 58 et 2 ne change
  rien.

### L'historique ne s'écrase pas

Un résultat officiel corrigé crée une **version** : l'ancienne passe en
`is_current = 0`, datée, rattachée à l'import qui l'a remplacée. Rien n'est
supprimé. Une nouvelle année scolaire ne modifie jamais les précédentes.

### Aucun faux succès

Le frontend n'affiche « réussi » qu'après une réponse réelle du serveur. Il
n'existe aucun `setTimeout` qui simule une progression ou une réussite. Si une
opération dure 200 ms, l'interface va vite ; si elle dure 5 s, le chargement
reste affiché.

### Import ≠ publication

Importer des résultats ne les publie pas. La proclamation est une décision
distincte, avec son audience. Ne fusionne jamais les deux.

### L'IA est en lecture seule

`backend/ai_assistant.py` ne contient aucun `INSERT`, `UPDATE` ni `DELETE`, et
ne doit jamais en contenir. La lecture seule y est architecturale, pas un filtre
de mots-clés.

---

## 2. Les tests

**Ne supprime jamais un test et ne l'affaiblis jamais pour faire passer la
suite.** Si un test échoue, c'est le code qui est en cause jusqu'à preuve du
contraire.

```bash
# SQLite
backend_venv/bin/python -m unittest discover -s backend/tests -t backend

# PostgreSQL 16 réel, local, jetable (~1 min, sans Docker ni réseau)
backend_venv/bin/python backend/tools/pg_tests.py
```

Les deux doivent être verts avant de rendre la main.

Un test qui passe ne prouve rien tant qu'on ne l'a pas vu **échouer**. Deux fois
dans ce projet, un test écrit après coup passait alors que le correctif était
neutralisé — il ne testait rien. Quand tu ajoutes un test sur un comportement
critique, neutralise temporairement le code concerné, vérifie que le test tombe,
puis restaure.

---

## 3. La landing est figée ; la démo est le chantier en cours

`index.html`, `assets/js/main.js` et les blocs « landing » de `style.css` sont
figés : voir **`LANDING_FIGEE.md`**. On n'y corrige qu'un défaut constaté, avec
la correction la plus étroite possible, et on le dit.

**La démo, elle, est ouverte.** `demo.html`, `assets/js/page-demo.js` et
`assets/js/demo-data.js` sont le chantier en cours : parcours, animations,
données fictives et rendu sont retravaillés **avec le propriétaire du produit**.
L'ancienne consigne « ne change rien à la démo » est levée depuis le 16/09.

Deux garde-fous qui demeurent, parce qu'ils ne sont pas des questions de goût :

- **Les données de la démo restent fictives et annoncées comme telles.** Elle
  ne doit jamais afficher de données réelles d'un établissement, ni laisser
  croire qu'une opération a eu un effet.
- **La feuille de style est partagée.** Si tu modifies `assets/css/style.css`
  pour la démo, vérifie que tu ne touches pas une classe utilisée ailleurs —
  `.chip` a déjà été défini deux fois pour deux composants différents.

---

## 4. Travail visuel — ce qui est bienvenu, ce qui ne l'est pas

Améliorer le rendu est légitime et attendu. Trois limites.

**Ne remplace pas un état réel par une animation.** Les états de chargement,
d'erreur, de succès et de vide reflètent des réponses serveur. Embellis-les ;
ne les inverse pas, ne les raccourcis pas, n'en ajoute pas d'artificiels.

**Ne retire pas l'échappement.** Tout contenu venant de la base passe par
`UI.escapeHtml()`. Une faille XSS stockée a déjà été exploitée puis corrigée
dans ce projet. Retirer un `escapeHtml` la rouvre.

**Réutilise les composants existants.** `KlassioLoader` pour les opérations
longues, `.import-card` pour un dépôt de fichier, `data-table responsive` pour
un tableau, `UI.kpi / badge / emptyState / modal / toast` pour le reste. Ne crée
pas une seconde animation d'upload, une seconde grille, un second système de
notification.

Respecte aussi : thème clair **et** sombre, `prefers-reduced-motion`, et le
mobile à 375 px sans débordement horizontal. Le contraste du texte porteur
d'information doit atteindre 4,5:1 (AA) dans les deux thèmes.

---

## 5. Si tu trouves un vrai bug dans le code existant

Corrige-le. Ce fichier ne protège pas les défauts.

Mais suis la méthode, sans raccourci :

```
DÉTECTION → REPRODUCTION → CAUSE RACINE → CORRECTION
          → TEST CIBLÉ → SUITE COMPLÈTE → RECHERCHE DE RÉGRESSION
```

Le test ciblé doit échouer sans le correctif. Explique dans le code **pourquoi**
la protection existe, pas seulement ce qu'elle fait — les commentaires de ce
dépôt racontent le bug qu'ils empêchent, garde cette habitude.

---

## 6. Classer avant de corriger

Ce projet avance par jalons. Tout ce qui est perfectible n'est pas à corriger
maintenant. Classe, puis décide.

| | |
|---|---|
| 🔴 **P0/P1** | Sécurité, contournement d'autorisation, fuite entre établissements, perte ou corruption de données, erreur financière, résultat publié au mauvais destinataire, fonctionnalité centrale promise qui ne marche pas. **Bloque.** |
| 🟠 **P2** | Réel mais sans effet sur la sécurité, les données ou les permissions. **Documenter, ne pas bloquer.** |
| 🟠 **P2 — fenêtre qui se ferme** | Non bloquant, mais dont le coût de correction augmente nettement après le déploiement : schéma, migrations, tout ce qui touche l'historique. À signaler comme tel. |
| 🟢 **P3** | Esthétique, refactor facultatif, micro-optimisation, préférence d'architecture. **Backlog.** |

Avant de déclarer quoi que ce soit bloquant, tu dois pouvoir écrire : *« si on
continue malgré ça, voici précisément ce qui casse, et pourquoi le système
devient dangereux, faux ou inutilisable. »* Si tu ne peux pas, ce n'est pas
bloquant.

Termine tout rapport par :

```
🔴 BLOQUANTS
🟠 NON-BLOQUANTS
🟢 BACKLOG
🚦 DÉCISION : CONTINUER / CORRIGER PUIS CONTINUER / BLOQUÉ
```

---

## 7. Deux copies du projet

- `/Users/macbookpro/klassio-saas` — **copie principale**, tout se crée ici.
- `/Users/macbookpro/Desktop/klassio-saas` — miroir ouvert dans VS Code.

```bash
rsync -a --delete --exclude 'backend/klassio_test.db*' --exclude '.DS_Store' \
  --exclude '__pycache__' --exclude 'backend_venv' --exclude '.coverage' \
  --exclude 'tools/k6/env-echelle.json' --exclude 'tools/k6/env-pg.json' \
  /Users/macbookpro/klassio-saas/ /Users/macbookpro/Desktop/klassio-saas/
```

`--delete` efface du miroir ce qui n'existe pas dans la copie principale. **Un
fichier créé uniquement dans le miroir sera perdu** — c'est déjà arrivé.

---

## 8. Détails qui font perdre du temps si on les ignore

- **`schema_postgres.sql` est GÉNÉRÉ** depuis `schema.sql`. Ne l'édite pas à la
  main : `python backend/tools/pg_schema.py`. L'oublier fait échouer dix tests
  sous PostgreSQL sans raison apparente.
- **Les migrations sont additives** (`db._migrate`) : `ALTER TABLE ADD COLUMN`,
  jamais de suppression. Une seule reconstruction de table existe, documentée et
  vérifiée ligne à ligne.
- **`backend/klassio.db` est une base de DÉVELOPPEMENT**, périmée et remplie
  d'écoles d'essai. Ne t'y fie pas pour juger de l'état du produit.
- **Le moteur de production est PostgreSQL.** SQLite est un outil de
  développement : sous concurrence il produit de vraies erreurs que PostgreSQL
  ne produit pas.
- **Cache navigateur** : les pages référencent `style.css?v=…` et
  `page-*.js?v=…`. Si tu modifies un de ces fichiers, **incrémente la version
  dans les pages concernées**, sinon tes changements ne s'afficheront pas.
- **Le dépôt git existe** — `origin git@github.com:Yversplayer/klassio-saas.git`,
  branche `main`. Travaille par commits successifs plutôt que par un gros
  changement d'un bloc ; `git diff` et `git revert` sont tes filets. **Ne pousse
  pas sans qu'on te le demande** : le dépôt est public.
  Corollaire pour le miroir du §7 : il ne contient PAS `.git` (rsync l'exclut).
  Une modification faite uniquement dans le miroir n'est ni versionnée ni
  sauvegardée — elle sera écrasée au prochain rsync.

---

## 9. Ce qui n'est pas implémenté — ne le présente jamais comme fait

- **Aucune intégration Mobile Money ou bancaire réelle.** Le Financial Core est
  complet et testé ; l'adaptateur fournisseur n'existe pas.
- **8 états de paiement sur 10 sont inatteignables** (`PENDING`, `PROCESSING`,
  `FAILED`, `CANCELLED`, `EXPIRED`, `UNKNOWN`, `REFUNDED`, `REVERSED`). Le
  schéma les déclare, le code ne les produit pas. Ni remboursement, ni annulation.
- **Pas d'OTP** : aucun canal SMS n'existe.
- **L'email ne part pas.** `backend/mailer.py` est écrit et testé, mais
  `EMAIL_MODE=capture` par défaut : le message est rendu et enregistré, rien
  n'est envoyé. Invitations, réinitialisation de mot de passe et avis de
  résultats attendent un compte fournisseur et la vérification du domaine
  (SPF/DKIM). Ne présente pas un envoi capturé comme un envoi.
- **Pas de bulletins PDF.** L'API compose un bulletin complet en JSON
  (`school.bulletin()`, `GET /api/classes/<id>/bulletins`) ; l'artefact
  imprimable n'existe pas.
- **Pas de notifications de calendrier.**
- **Sauvegardes jamais restaurées** : RPO et RTO non établis.
- **Jamais déployé.**
- **Tarifs non tranchés.** `plans` et `api_billing` facturent 49 $ / 60 $+0,30 $
  par élève / 120 $+0,20 $ ; d'autres prix ont été évoqués sans décision. Le
  propriétaire n'a pas arbitré : **ne modifie aucun prix**.

Ne transforme pas une simulation en fonctionnalité dans un rapport.
