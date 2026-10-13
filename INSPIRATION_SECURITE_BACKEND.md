# Inspiration — sécurité et backend à la manière de Klassio

> **À l'agent qui lit ce fichier.** Ce document décrit l'architecture de
> sécurité et de backend de Klassio (SaaS de gestion scolaire multi-école,
> en production, audité et attaqué en conditions réelles). Il sert de
> **cahier des exigences** pour un AUTRE projet. Applique ces principes en
> les adaptant à la pile du projet ; ne copie pas le code de Klassio.
> Chaque règle ci-dessous existe parce qu'un bug réel a été trouvé sans elle.
> Si une règle ne s'applique pas au projet, dis-le explicitement plutôt que
> de l'ignorer en silence.
>
> Code de référence (public) : https://github.com/Yversplayer/klassio-saas
> (`backend/security.py`, `backend/db.py`, `backend/school.py`, `backend/tests/`).

---

## 1. Principes non négociables

1. **Le serveur décide de tout.** Rôle, organisation (tenant), périmètre et
   permissions viennent de la SESSION côté serveur. Jamais d'un corps de
   requête, d'un paramètre d'URL ou du navigateur.
2. **Le navigateur envoie des critères, pas des résultats.** Exemple : pour
   publier à une audience, le client envoie « classes A et B » ; le serveur
   repart des données réelles et recalcule les destinataires. Un compteur
   annoncé par le client (« 60 lignes, 0 erreur ») n'est jamais cru : il est
   relu depuis l'état serveur.
3. **Aucun faux succès.** L'interface n'affiche « réussi » qu'après une vraie
   réponse du serveur. Pas de `setTimeout` qui simule une progression.
4. **Fermé par défaut.** Toute nouvelle route, table ou connexion est refusée
   tant qu'on ne l'a pas explicitement autorisée.
5. **Ne présente jamais une simulation comme une fonction.** Si l'e-mail est
   en mode capture, il n'est pas « envoyé ». Si le paiement est déclaratif, il
   n'est pas « payé en ligne ».

## 2. Multi-organisation (multi-tenant)

- Chaque table métier porte `tenant_id`. Il n'est **jamais** fourni par le
  client ; il vient de la session.
- Toute requête filtre sur `tenant_id`, **y compris dans les sous-requêtes**
  (un bug réel venait d'une sous-requête non filtrée).
- Une ressource d'une autre organisation répond **404**, jamais `200 []` :
  un tableau vide affirme déjà « cette ressource existe ».
- **Défense en profondeur dans la base (PostgreSQL)** : Row Level Security
  activée sur chaque table à `tenant_id`, l'application se connecte avec un
  rôle SANS `BYPASSRLS` et non propriétaire des tables ; le tenant courant est
  posé par connexion (`set_config('app.tenant', …)`). Une connexion dont le
  contexte n'est pas posé ne voit RIEN. Les opérations inter-organisations
  (administration de la plateforme) passent par une connexion explicitement
  « globale », rare et auditée.
- **Test de balayage automatique** : un test appelle CHAQUE route paramétrée
  avec les identifiants d'une autre organisation et exige 404. Toute nouvelle
  route paramétrée doit y être déclarée, sinon elle sort du filet en silence.

## 3. Périmètres et permissions

- Un module unique est la **source de vérité des périmètres** (qui voit quels
  objets : direction = tout, responsable = son cycle, enseignant = ses
  classes, parent = ses enfants). Aucune route ne réimplémente sa propre règle.
- Permissions par rôle déclarées dans une table centrale ;
  `require_permission("x.y")` sur chaque route sensible.
- Les permissions optionnelles (ex. « les enseignants voient les finances »)
  sont des réglages de l'organisation, **vérifiés côté serveur à chaque
  requête**, jamais un simple masquage dans l'interface.

## 4. Authentification et sessions

- **Mots de passe** : PBKDF2-HMAC-SHA256 avec sel aléatoire et au moins
  200 000 itérations (ou Argon2/bcrypt) ; comparaison en temps constant
  (`hmac.compare_digest`).
- **Jetons** (session, invitation, réinitialisation) : aléatoires
  (`secrets.token_urlsafe`), et seule leur **empreinte SHA-256** est stockée
  en base. Une fuite de la base ne donne aucune session utilisable.
- **Session dans un cookie** `HttpOnly; Secure; SameSite=Strict` — jamais dans
  `localStorage`, jamais dans le JavaScript.
- **CSRF** : un second cookie lisible (dérivé du jeton avec un préfixe
  distinct, jamais égal à l'empreinte de session) que le client renvoie dans
  l'en-tête `X-CSRF-Token` pour toute méthode mutante (POST/PUT/PATCH/DELETE).
  Refus audité si absent ou faux.
- Expiration des sessions + purge ; révocation de toutes les sessions d'un
  compte à la désactivation ou au changement de mot de passe.
- **Invitations à usage unique** consommées de façon ATOMIQUE (un bug réel :
  la même invitation consommée deux fois en parallèle).
- **Limitation de débit** par compte ET par adresse IP sur connexion,
  inscription, réinitialisation, invitations, formulaire public. Derrière un
  proxy, ne croire l'IP transmise que si le proxy prouve son identité (secret
  partagé), sinon tout le monde a l'IP du proxy.
- **Administration de la plateforme séparée** : comptes distincts des
  utilisateurs, créés uniquement par un outil en ligne de commande, connexion
  avec TOTP obligatoire (un code ne sert qu'une fois : mémoriser le dernier
  pas utilisé), cookies et CSRF propres.

## 5. En-têtes et navigateur

- `Content-Security-Policy` stricte : `script-src 'self'` (aucun script en
  ligne, aucun CDN ; héberger les bibliothèques soi-même).
- `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`, `Strict-Transport-Security` en HTTPS ;
  redirection HTTP → HTTPS.
- **Tout contenu venant de la base est échappé** avant insertion dans le DOM
  (une XSS stockée a été exploitée puis corrigée : ne jamais retirer un
  échappement).
- Fichiers téléversés : liste blanche de types, taille maximale, formats
  « actifs » refusés (HTML, SVG, scripts, exécutables) ; n'afficher dans le
  navigateur que PDF et images, télécharger le reste.
- Une erreur 500 ne renvoie jamais de chemin de fichier ni de requête SQL.

## 6. Validation des entrées

- Un module de validation central : types, longueurs maximales, formats
  (dates, devises, heures), énumérations. Toute route le traverse.
- Le corps JSON doit être un objet ; tout champ inattendu est ignoré, jamais
  utilisé pour décider d'un droit.

## 7. Argent et données critiques

- **Idempotence** : toute opération financière porte une
  `idempotency_key`, avec contrainte `UNIQUE(tenant_id, idempotency_key)`
  (une contrainte globale permettait de bloquer une autre organisation).
- **États explicites** (CREATED, PENDING, CONFIRMED, FAILED, UNKNOWN…) ;
  `UNKNOWN ≠ FAILED`. Transitions atomiques : un webhook rejoué ne doit
  jamais confirmer deux fois (bug réel).
- **Un reçu n'existe qu'après la confirmation réelle** d'un paiement, numéro
  unique par organisation.
- **L'historique ne s'écrase pas** : une donnée officielle corrigée crée une
  nouvelle VERSION (l'ancienne passe `is_current = 0`, datée, rattachée à
  l'opération qui l'a remplacée). Rien n'est supprimé. Une nouvelle période
  ne modifie jamais les précédentes.
- **Importer ≠ publier** : l'import d'un fichier ne rend rien visible ; la
  publication est une décision séparée, avec son audience.
- Une opération en lot est **entièrement vérifiée avant la première
  écriture**.

## 8. Journal d'audit

- Table d'audit immuable : qui, quand, quelle action, quelle ressource, état
  avant/après, succès ou refus. Les refus d'autorisation et de CSRF y sont
  inscrits.
- Aucun utilisateur ordinaire ne peut la modifier ou la supprimer.

## 9. IA dans le produit

- L'IA est en **lecture seule par architecture** : son module ne contient
  aucune écriture en base et n'expose que des fonctions de lecture filtrées
  par le module de périmètres. Pas un filtre de mots-clés : l'absence de
  l'outil.
- Les demandes d'écriture sont refusées avant tout appel au modèle.
- Avec un fournisseur externe : n'envoyer que le strict nécessaire, noms
  masqués ; le modèle choisit dans un catalogue FERMÉ (sortie structurée),
  l'application répond avec ses propres données ; toute panne, refus ou
  dépassement de plafond rend la réponse déterministe d'origine.

## 10. Secrets et configuration

- Tous les secrets en variables d'environnement, saisis par le propriétaire
  dans l'hébergeur ; jamais dans le dépôt, jamais affichés.
- Un fichier `.env.example` documente chaque variable avec `[SECRET]` ou
  `[PUBLIC]`.
- Un test parcourt le dépôt et échoue s'il trouve un motif de clé (clés
  Anthropic, OpenAI, AWS, GitHub, JWT, clés privées, fichiers `.env`, bases).
- Les réglages de test (ex. contourner un abonnement) sont refusés sur une
  base distante.

## 11. Base de données

- Moteur de production : PostgreSQL. Si SQLite sert au développement, la
  suite de tests tourne AUSSI sur un PostgreSQL réel jetable (les deux
  moteurs ne se comportent pas pareil sous concurrence).
- Migrations **additives** (`ADD COLUMN`), jamais de suppression ; schéma
  appliqué avant le démarrage du serveur (le déploiement échoue plutôt que
  d'exposer une API sans son schéma).
- Sauvegardes : à prévoir ET à **restaurer pour de vrai** au moins une fois.

## 12. Tests — la méthode

- Deux suites vertes avant chaque livraison (SQLite et PostgreSQL).
- **Un test qui n'a jamais échoué ne prouve rien.** Pour chaque garde-fou
  critique : neutraliser temporairement le code, vérifier que le test tombe,
  restaurer. (Deux fois, un test écrit après coup passait alors que le
  correctif était neutralisé.)
- Ne jamais supprimer ni affaiblir un test pour faire passer la suite.
- Méthode face à un bug : détection → reproduction → cause racine →
  correction → test ciblé (vu échouer) → suite complète → recherche de
  régression. Le commentaire dans le code raconte le bug qu'il empêche.
- Classer avant de corriger : P0/P1 (sécurité, fuite, perte de données,
  argent) bloque ; P2 se documente ; P3 va au backlog.

## 13. Déploiement

- Pages statiques derrière un proxy (ex. Cloudflare Worker) qui force HTTPS
  et relaie `/api` vers l'API avec un secret partagé ; le navigateur ne voit
  qu'une origine (pas de CORS à ouvrir).
- Serveur WSGI de production (gunicorn), jamais le serveur de développement.
- Le serveur d'API au plus près de sa base (chaque requête SQL paie la
  distance serveur ↔ base ; l'utilisateur ne paie la sienne qu'une fois par
  page).

---

### Mode d'emploi pour un nouveau projet

Demande à l'agent : « Lis INSPIRATION_SECURITE_BACKEND.md et applique-le à ce
projet. Commence par une liste : pour chaque section, ce qui s'applique, ce
qui ne s'applique pas et pourquoi, puis l'ordre de mise en place. »
