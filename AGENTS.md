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

> ### 🎨 REFONTE VISUELLE EN COURS — la landing est DÉGELÉE
>
> **Depuis le 22/09, le propriétaire a commandé une refonte visuelle de la
> landing et de la démo.** `index.html`, `assets/js/main.js`, `demo.html` et
> les blocs « landing » de `assets/css/style.css` sont donc **ouverts**.
> `LANDING_FIGEE.md` n'est plus une interdiction : c'est la **liste de ce que
> la refonte doit continuer d'honorer** — lis ses sept décisions du §3 et
> vérifie-les après ta refonte, une par une.
>
> **Deux choses ne se négocient pas :**
> 1. **L'entrée dans le « O » de KLASSIO est conservée.** C'est la signature
>    du produit, explicitement maintenue par le propriétaire.
> 2. **La refonte est VISUELLE.** Elle ne touche ni le backend, ni les routes,
>    ni les permissions, ni le schéma, ni les tests. Si tu crois devoir
>    modifier `backend/`, arrête-toi et dis-le.
>
> Le périmètre exact, les contraintes de pile et les pièges de cette refonte
> sont au **§10**. Lis-le avant d'écrire une ligne.

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

## 3. Landing et démo : le chantier visuel

`index.html`, `assets/js/main.js`, `demo.html`, `assets/js/page-demo.js`,
`assets/js/demo-data.js` et les blocs « landing » de `style.css` sont **le
chantier en cours**, retravaillés avec le propriétaire du produit. Voir §10
pour le périmètre et les contraintes.

`LANDING_FIGEE.md` reste à lire — non plus comme une interdiction, mais comme
la liste des sept décisions que la refonte doit continuer d'honorer. Vérifie-les
après coup, une par une, et dis dans ton rapport laquelle tu as dû faire évoluer
et pourquoi.

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
- ~~Pas de bulletins PDF.~~ **Ils existent depuis le 23/09** :
  `backend/pdf_bulletin.py` (PDF 1.4 écrit à la main, sans dépendance),
  `GET /api/students/<id>/bulletin.pdf` et `GET /api/classes/<id>/bulletins.pdf`,
  couverts par `tests/test_bulletin_pdf.py` — y compris le cas qui compte : un
  parent ne reçoit jamais une période non proclamée.
- **Pas de notifications de calendrier.**
- **Sauvegardes jamais restaurées** : RPO et RTO non établis.
- **Jamais déployé.**
- **Tarifs ARRÊTÉS le 01/10/2026 par le propriétaire** : Essentiel 99,90 $
  (≤ 300 élèves), École 149,90 $ (301–1 000), Complexe 249,90 $ (1 001–3 000),
  Réseau sur devis — par mois, toutes les fonctionnalités dans chaque offre.
  Ils vivent à DEUX endroits qui doivent rester identiques : `PLANS_2026_10`
  (backend/db.py, ce que le serveur facture) et la section `#tarifs` de la
  landing. **Ne modifie aucun prix sans le propriétaire.**
- **Pas de mode gratuit.** Une école naît fermée (`awaiting_plan`) ; elle dépose
  ses fichiers Excel, choisit son offre (obligatoire), et ne s'ouvre qu'à la
  confirmation de son premier paiement par la plateforme. Les testeurs lèvent
  ce blocage avec `./demarrer.sh --testeur` (`KLASSIO_CONTOURNER_ABONNEMENT=1`,
  réglage serveur, refusé sur une base distante) ; la suite de tests l'active
  dans `tests/__init__.py`, et `test_abonnement.py` éprouve la vraie règle.
  Aucun paiement n'est encaissé par Klassio : la Direction déclare sa
  référence, un administrateur de la plateforme confirme.

Ne transforme pas une simulation en fonctionnalité dans un rapport.

---

## 10. Le chantier visuel — périmètre et pièges

Le propriétaire a commandé, le 22/09, une refonte **visuelle** de la landing et
de la démo, inspirée de sites de studio créatif (MATTER, CAUSTIC), plus un
comportement de barre latérale révélée au survol dans l'application.

**Ce qui est demandé est l'IMAGE, pas le fond.** Le SaaS ne change pas :
mêmes routes, mêmes permissions, même schéma, mêmes tests.

### Ce qui est ouvert

`index.html` · `demo.html` · `assets/js/main.js` · `assets/js/page-demo.js` ·
`assets/js/demo-data.js` · les blocs landing/démo de `assets/css/style.css` ·
la barre latérale de l'application (`assets/js/admin.js`, `assets/css/style.css`).
La barre latérale révélée au survol **est faite** (`admin.js`), `aria-expanded`
compris : ne la refais pas, vérifie-la.

### Ce qui reste interdit

Tout `backend/`. Toute route. Toute permission. Tout schéma. Tout test.
Si une idée visuelle exige un changement serveur, **arrête-toi et demande**.

### Cinq pièges qui feront échouer la refonte si on les ignore

**1. LA PILE EST VANILLA. Il n'y a ni React, ni npm, ni bundler.**
Pas de `package.json`, pas de `node_modules`, pas de TypeScript, pas de
Tailwind, pas de shadcn, pas de Next.js, pas de framer-motion. Le frontend
est du JavaScript de navigateur servi en fichiers statiques.
Les composants de référence fournis par le propriétaire sont écrits en
React/Tailwind : ils sont une **référence d'intention visuelle**, pas du code
à copier. **Porte l'effet en vanilla. N'introduis pas de chaîne de build.**
Transformer ce projet en application React est hors de question : le backend
Flask sert ces fichiers tels quels, et 29 pages en dépendent.

**2. LA CSP BLOQUE LES CDN.** Chaque page porte
`script-src 'self'` : un `<script src="https://cdn...">` (Three.js, GSAP,
Tailwind CDN) **ne se charge pas**, silencieusement, et la page paraît
simplement cassée. Deux issues, dans cet ordre de préférence :
obtenir l'effet sans la bibliothèque (CSS, Canvas 2D, WebGL natif), ou
**héberger le fichier dans `assets/vendor/`** et l'appeler en `'self'`.
Ne relâche pas la CSP pour faire entrer un CDN.

**3. LA FEUILLE DE STYLE EST PARTAGÉE.** `assets/css/style.css` (3 588 lignes)
sert la landing, la démo **et l'application**. Une classe renommée ou un
sélecteur trop large casse un écran métier à l'autre bout du produit — `.chip`
a déjà été défini deux fois pour deux composants différents. Préfixe tes
nouvelles classes, et vérifie les écrans de l'application après coup.

**4. LA BARRE LATÉRALE RÉVÉLÉE AU SURVOL DOIT RESTER ATTEIGNABLE.**
« Apparaît quand la souris va à gauche, disparaît quand elle en sort » n'existe
pas sur un écran tactile et pas au clavier. Le bouton menu doit continuer de
l'ouvrir, la navigation au clavier doit continuer d'y entrer et d'en sortir,
`aria-expanded` doit dire la vérité, et `prefers-reduced-motion` doit désactiver
l'animation. Une barre de navigation qu'un utilisateur au clavier ne peut plus
atteindre n'est pas un raffinement, c'est une régression d'accessibilité.

**5. KINSHASA, PAS UN MACBOOK.** Les latences réelles ont été mesurées et sont
documentées dans `RAPPORT_PERFORMANCE.md`. Une scène WebGL avec post-traitement
et bloom sur un téléphone d'entrée de gamme ou une connexion lente n'est pas un
détail de confort : c'est une landing qui ne s'affiche pas. Prévois un repli
réel — pas un écran noir — et respecte `prefers-reduced-motion`, le mobile à
375 px et le contraste AA (4,5:1) dans les deux thèmes.

### Ce qui existe déjà — ne le recrée pas

`cgu.html`, `confidentialite.html`, `mentions.html`, `securite.html`,
`aide.html`, `faq.html`, `contact.html`, `a-propos.html`, `robots.txt` et
`sitemap.xml` **existent** (FAQ, Contact et À propos sont, depuis le 30/09,
des sections de la landing : leurs pages redirigent). Une demande de « créer une page CGU » est déjà
satisfaite : relis-la, améliore-la, ne la duplique pas.

Existent aussi, depuis : **favicon** (`favicon.ico`, déclaré dans toutes les
pages), **Open Graph et Twitter Card** (`assets/og-klassio.png`, 1200×630), et
**page 404** (`404.html`). Ne les refais pas — vérifié le 30/09.

### La couche cinématique (30/09) — où elle vit, et ses trois règles

La landing, la démo et les pages publiques portent désormais une couche
cinématique : scènes pilotées par le défilement, ordinateur et téléphone en
3D CSS, photographies d'écoles de Kinshasa. **Elle ne vit pas dans
`style.css`** :

| Fichier | Rôle |
|---|---|
| `assets/css/cine.css` | tout le visuel, classes préfixées `kx-`. L'application ne charge pas ce fichier : rien ici ne peut l'atteindre. |
| `assets/js/cine.js` | le moteur : écrit `--p` (progression) et `data-beat` (étape) sur chaque `[data-kx-scene]`. Chargé AVANT `main.js`. |
| `assets/cine/*.webp` | 24 photos générées (Higgsfield, projet « Klassio — site cinématique »), 960 et 1600 px, miniature floue dans le bloc `LQIP` de `cine.css`. Sources PNG hors dépôt (`.gitignore`). Politique : adultes de face, élèves de dos ou au loin, aucun drapeau, aucun texte lisible. |
| `assets/css/vitrine.css` | la grammaire de la landing (sur-titres dorés, serif, cartes photo, bande vert forêt, pied de page en rideau). Préfixe `kx-`. Landing et démo seulement. |
| `assets/css/demo-cine.css` | le récit de la démo (salle de classe, portail, dossier en coupe, mur d'écrans). Préfixe `kd-`. `demo.html` seulement. |
| `assets/js/entree.js` | dans `<head>` de la landing : saute l'accueil animé si on arrive par une ancre ou si on l'a déjà vu dans la session, et saute NET à l'ancre (sinon `scroll-behavior: smooth` faisait défiler 22 000 px de scènes). |
| `assets/js/contact.js` | le formulaire de contact, désormais dans la landing (`#contact`). Pas de script en ligne : la CSP le bloquerait. |

**Règle du propriétaire (01/10) : le site et la démo montrent TOUT le logiciel,
et RIEN d'autre.** Chaque fonction de `app/` doit y apparaître sous son
meilleur jour ; aucune fonction absente du logiciel ne doit y figurer (la
saisie des notes par les professeurs a été retirée pour cette raison : les
résultats entrent par l'import). Seule tolérance : Mobile Money, présenté tel
qu'il est — le parent annonce, l'école confirme. L'inventaire vit dans la
section `#fonctions` de la landing (32 fonctions, six familles) et dans le mur
d'écrans de la démo (24 écrans) : une fonction ajoutée au logiciel s'ajoute
aux deux.

**Fusion du 30/09.** À propos, FAQ et Contact sont des sections de la landing
(`#a-propos`, `#faq`, `#contact`) ; `a-propos.html`, `faq.html` et
`contact.html` ne sont plus que des redirections (`noindex`), sorties du
sitemap. Le Centre d'aide et les pages légales restent des pages. La barre
publique (`public.js`) pointe vers les ancres et n'a **pas d'onglet
« Démo »** : on y entre par UN bouton, à droite — le propriétaire l'a demandé
deux fois. Curseur personnalisé et aimantation des boutons : **retirés**, à
sa demande ; ne pas les remettre.

**La démo** (`demo.html`, à modifier directement) s'ouvre sur un récit en quatre scènes,
puis la visite interactive (`.demo-shell`, inchangée). L'appel utilise les
séquences de `cine.js` (`data-kx-seq` : un élève et sa ligne sur le
téléphone partagent un `data-kx-i`). Les destinataires montrés sont ceux de
`notifications.on_attendance_recorded`, et les périmètres du dossier en coupe
ceux de `school.student_dossier` : si l'un change, la démo doit changer.

1. **Une scène n'est animée que si `cine.js` lui ajoute `.kx-live`.** Sans
   script ou en mouvement réduit, elle s'affiche à plat, tout en place.
   N'écris jamais d'état caché hors de `.kx-live`.
2. **Les écrans des appareils sont du HTML, pas des captures**, avec des
   données fictives annoncées comme telles à côté de chaque scène. Un écran
   ne montre jamais une fonction qui n'existe pas (§9) — le reçu dit
   « confirmé par la caisse », pas « payé en ligne ».
3. **Aucune vidéo.** Le plan gratuit Higgsfield ne la permet pas, et le
   piège 5 l'aurait interdite de toute façon. Le mouvement vient du
   défilement ; les photos sont en chargement différé, posées sur une
   miniature floue de ~1 Ko, et masquées en économie de données.

Pour l'intérieur du « O » : la photo du crépuscule est à opacité 0 au repos
et ne monte qu'avec la plongée (`--portal-p`, exposé par `main.js`). Au
repos, `.portal-reveal` EST le trou de la lettre — une photo visible dès la
première image ferait lire « KLASSI » suivi d'un disque sombre.

### Analytics et cookies — ne décide pas seul

Klassio manipule des dossiers d'enfants scolarisés. Brancher un outil
d'analytics tiers, même « respectueux de la vie privée », envoie du trafic vers
un tiers et oblige à relâcher la CSP. **C'est une décision du propriétaire, pas
un défaut à corriger.** Propose, chiffre le coût en CSP et en confidentialité,
et attends la réponse. Même chose pour le bandeau de consentement : sans outil
de tracking, un bandeau de consentement n'a rien à consentir.
