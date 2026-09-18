# KLASSIO — Sécurité, Permissions et Protection
### Spécification V0.1 — architecture de sécurité de niveau production

Ce document complète [OBJECTIFS_ET_FONCTIONNALITES.md](OBJECTIFS_ET_FONCTIONNALITES.md) (vision produit) et [SYSTEME_IA.md](SYSTEME_IA.md) (système IA). Il ne les remplace pas — le Permission Layer, l'isolation multi-tenant et la sécurité IA déjà spécifiés dans `SYSTEME_IA.md` (sections 6, 12) sont l'autorité pour tout ce qui touche l'IA ; ce document les référence plutôt que de les dupliquer, et couvre tout le reste : authentification, RBAC, sécurité financière, secrets, incidents, sauvegardes.

## 0. État réel du projet — à lire avant tout le reste

Conformément au principe *"ne pas faire semblant"* : **le projet actuel est un prototype frontend statique (HTML/CSS/JS, sans build), sans backend, sans base de données, sans authentification réelle.** Fichiers existants : [index.html](../index.html) (landing), [app/inscription.html](../app/inscription.html), [app/connexion.html](../app/connexion.html), [app/dashboard.html](../app/dashboard.html), servis par un simple serveur de fichiers statiques pour la prévisualisation.

**Conséquence directe :** aucune des protections décrites dans ce document n'est aujourd'hui appliquée par un serveur, parce qu'il n'y a pas encore de serveur applicatif. Ce qui existe dans le prototype (menus qui changent selon un rôle stocké en `localStorage`, formulaires) est **une simulation d'interface**, pas une frontière de sécurité — exactement le piège décrit au point 18 de votre brief. Chaque section ci-dessous porte une étiquette de statut honnête :

`✅ IMPLÉMENTÉ` · `🟡 PARTIEL` · `📋 PLANIFIÉ (spécifié, pas codé)` · `⛔ NON IMPLÉMENTÉ` · `🔌 NÉCESSITE UN FOURNISSEUR EXTERNE`

Sur ce projet, à ce stade, la très grande majorité du contenu est `📋 PLANIFIÉ` — c'est attendu et normal : la philosophie du projet (voir `SYSTEME_IA.md` et `OBJECTIFS_ET_FONCTIONNALITES.md`) est de concevoir avant de coder. Ce document *est* le travail de conception demandé. La section 21 (Roadmap) et l'Annexe C donnent l'état précis, protection par protection.

**Ce que ce tour de travail ajoute concrètement au code** (le reste est spécification) :
- [assets/js/permissions.js](../assets/js/permissions.js) — catalogue de permissions granulaires (section 8), destiné à devenir la source de vérité du futur backend, pas une enforcement réelle aujourd'hui.
- Un commentaire de garde-fou ajouté dans [assets/js/app.js](../assets/js/app.js) rappelant que `ROLE_MENUS` est une commodité d'affichage, pas une permission.

---

## 1. Principes non négociables

Repris de votre brief, unifiés avec ceux déjà posés dans `SYSTEME_IA.md` §Principes absolus :

1. Le frontend n'est **jamais** une frontière de sécurité — il adapte l'affichage, il ne protège rien.
2. Le backend est l'autorité finale sur toute décision de sécurité.
3. Un établissement ne peut jamais accéder aux données d'un autre établissement.
4. Les permissions sont vérifiées côté serveur, à chaque requête, jamais mises en cache comme acquises.
5. Les opérations critiques sont protégées par plusieurs couches indépendantes (defense in depth).
6. Les transactions financières ne sont jamais supprimées arbitrairement — correction par écriture compensatoire.
7. L'IA ne possède jamais un accès libre à la base de données (`SYSTEME_IA.md` §2, §6).
8. L'IA respecte exactement les permissions de l'utilisateur réel, jamais celles qu'un prompt prétend avoir (`SYSTEME_IA.md` §6, §12).
9. Les comptes bancaires et Mobile Money sont des ressources critiques à protection renforcée.
10. Une modification critique doit être authentifiée, autorisée et tracée.
11. Les secrets ne sont jamais exposés au frontend, dans Git, ou dans les logs.
12. Les webhooks sont non fiables jusqu'à vérification complète de leur signature et de leur contenu.
13. Chaque donnée financière a une source de vérité unique.
14. Les actions critiques sont idempotentes lorsque c'est pertinent.
15. Le système fonctionne en **deny by default**.
16. Toute opération sensible doit pouvoir être auditée : qui, quoi, quand, avant/après, résultat.
17. Une erreur réseau n'est jamais automatiquement un échec financier — état `UNKNOWN` explicite (section 8.3).
18. Une compromission d'un compte ou d'un composant ne doit jamais automatiquement compromettre tout le système.
19. La sécurité est indépendante de l'interface graphique — elle doit tenir même si le frontend est entièrement recréé.
20. La sécurité se conçoit maintenant, elle ne s'ajoute pas à la fin.

---

## 2. Zero Trust

Aucune requête n'est fiable par défaut, même authentifiée. Chaque requête vers une ressource sensible doit revérifier : identité → session valide → tenant → rôle → permission → **la ressource précise demandée appartient bien à ce tenant/cet utilisateur** → contexte (heure, montant, statut) → niveau de risque éventuel.

Concrètement, ceci élimine une catégorie entière de bugs de sécurité : *"l'utilisateur est connecté donc on lui fait confiance"* n'est jamais une justification suffisante dans le code backend à venir. Chaque contrôleur/route doit répéter la vérification, même si un middleware l'a déjà fait plus haut — la redondance est voulue (defense in depth, principe 5).

Statut : `📋 PLANIFIÉ` — s'applique dès la conception du premier endpoint backend.

---

## 3. Multi-tenant security

Reprend et détaille `SYSTEME_IA.md` §12.4. Chaque établissement est un tenant totalement isolé.

**Défense en profondeur à trois niveaux indépendants** (une seule couche ne suffit jamais) :

| Niveau | Mécanisme | Ce qu'il empêche |
|---|---|---|
| Application | Middleware d'autorisation qui injecte le `tenant_id` **depuis la session serveur**, jamais depuis une requête client | Un utilisateur qui modifie un `school_id` dans le frontend |
| Requête | Toute requête vers la base est automatiquement scopée par tenant (tenant-scoped query builder / repository pattern) | Un développeur qui oublie un `WHERE tenant_id = ?` dans une nouvelle route |
| Base de données | Row-Level Security (RLS) si le SGBD le permet (ex. PostgreSQL), sinon contraintes strictes + vérification systématique | Une faille applicative qui contournerait les deux couches précédentes |

**Ne jamais faire confiance à :** un `school_id`/`tenant_id` envoyé par le frontend, un paramètre d'URL, un champ de formulaire, un identifiant "deviné". Le tenant de la session vient uniquement de l'authentification serveur.

Statut : `📋 PLANIFIÉ`.

---

## 4. Architecture d'authentification

### 4.1 Méthodes
Email/mot de passe (MVP) ; téléphone si nécessaire pour les marchés où c'est l'identifiant naturel des parents ; vérification d'email et de téléphone à l'inscription ; réinitialisation de mot de passe par lien à usage unique et expirant.

### 4.2 Mots de passe
Hash uniquement avec un algorithme adapté (Argon2id recommandé, bcrypt acceptable), jamais de chiffrement réversible, jamais de stockage en clair même temporairement dans les logs.

### 4.3 Sessions et tokens
- Access token de courte durée + refresh token de plus longue durée, avec **rotation** du refresh token à chaque utilisation.
- Révocation possible côté serveur (liste de révocation ou session store), y compris révocation globale ("déconnecter tous mes appareils").
- Invalidation automatique de toutes les sessions actives après un changement de mot de passe.
- Cookies de session (si utilisés) : `HttpOnly`, `Secure`, `SameSite=Strict` ou `Lax` selon le flux ; jamais de token sensible lisible par du JavaScript côté client.
- Détection de connexion depuis un appareil ou une localisation inhabituelle → alerte (section 15).

### 4.4 Limitation des tentatives
Rate limiting spécifique sur login, reset password, vérification OTP (section 22) — verrouillage progressif, pas un blocage définitif silencieux qui gênerait un utilisateur légitime.

Statut : `📋 PLANIFIÉ` — aucun de ces mécanismes n'existe encore, il n'y a pas de backend d'authentification.

---

## 5. MFA / authentification renforcée

**Obligatoire pour :** Directeur, Administration, Responsable financier, tout rôle avec accès à la trésorerie ou aux comptes de règlement, Super Administrateur.

**Méthodes à prévoir :** TOTP (application d'authentification) en priorité, codes de récupération à usage unique, WebAuthn/passkeys si la cible d'utilisateurs le permet (plus adapté à un directeur d'établissement qu'à un parent sur téléphone bas de gamme — à valider par établissement).

### 5.1 Step-up authentication

Certaines actions exigent une confirmation d'identité **même en session déjà active** :

| Action | Déclenche un step-up |
|---|---|
| Changement de compte bancaire ou Mobile Money | Oui, systématique |
| Remboursement au-delà d'un seuil configurable | Oui |
| Suppression d'une donnée critique | Oui |
| Modification de permissions ou ajout d'un administrateur | Oui |
| Export massif de données | Oui |
| Modification d'une configuration de sécurité (MFA, règles de mot de passe) | Oui |

Le message reste simple pour l'utilisateur (section 18) : *« Confirmez votre identité pour effectuer cette opération. »*

Statut : `📋 PLANIFIÉ` · MFA lui-même est souvent `🔌 NÉCESSITE UN FOURNISSEUR` (bibliothèque TOTP standard, ou service tiers pour SMS/WhatsApp OTP).

---

## 6. RBAC + permissions granulaires

**Ne jamais coder `role === "admin"`.** Chaque action du système correspond à une permission nommée, indépendante du rôle — le rôle n'est qu'un ensemble de permissions par défaut, modifiable.

Le catalogue complet est désormais codifié dans [assets/js/permissions.js](../assets/js/permissions.js) (créé dans ce tour de travail) — extrait :

```
students.read · students.create · students.update · students.delete
payments.read · payments.create · payments.cancel · payments.refund
finance.read · finance.manage
expenses.read · expenses.create · expenses.approve
treasury.read · treasury.transfer
bank_accounts.read · bank_accounts.manage
mobile_money.read · mobile_money.manage
users.read · users.create · users.update · users.delete
roles.read · roles.manage
reports.read · reports.export
audit.read
settings.read · settings.manage
ai.use
```

### 6.1 Permissions par ressource (pas seulement par action)

Une permission ne répond pas seulement à *"peut-il modifier un paiement ?"* mais à *"peut-il modifier CE paiement-là ?"*. Chaque vérification de permission doit inclure la résolution de la ressource : appartenance au tenant de l'utilisateur, classe/élève autorisé pour un professeur, montant sous un seuil pour un caissier, statut compatible avec l'action demandée.

### 6.2 Permissions contextuelles

Les permissions peuvent dépendre de : établissement, année scolaire, classe, rôle, ressource, **montant**, statut, heure, niveau de risque. Exemple directement issu du brief : un caissier peut enregistrer un paiement jusqu'à 500 $, mais un remboursement au-delà nécessite une approbation (section 7).

### 6.3 Séparation des responsabilités (workflow d'approbation)

*"Celui qui demande une opération critique ne doit pas être celui qui l'approuve."*

```
CAISSIER            RESPONSABLE FINANCIER          SYSTÈME
demande               approuve/rejette              exécute + audite
remboursement 1500$ → ────────────────────────→   si approuvé uniquement
```

Modèle de données indicatif : `ApprovalRequest { id, tenant_id, requested_by, action, payload, status: pending|approved|rejected, approved_by?, decided_at?, reason? }`.

Statut : `📋 PLANIFIÉ` (le catalogue de permissions est `✅ IMPLÉMENTÉ` en tant que fichier de référence — pas encore appliqué, puisqu'il n'y a rien à appliquer côté serveur).

---

## 7. Rôles du système

Rappel synthétique (détail complet dans la matrice, section 8) :

| Rôle | Portée |
|---|---|
| Super Administrateur | Plateforme entière, tous tenants — accès extrêmement restreint et audité (section 20) |
| Directeur / School Admin | Établissement entier — mais pas automatiquement tous les privilèges techniques (ex. pas forcément `roles.manage` par défaut) |
| Responsable financier | Fonctions financières, avec seuils et approbations sur les opérations critiques |
| Caissier | Paiements autorisés uniquement — jamais suppression, jamais comptes de règlement |
| Enseignant | Ses classes et élèves autorisés — jamais de données financières détaillées |
| Parent | Ses enfants uniquement |
| Élève | Son propre dossier uniquement |

Le rôle attribue un **ensemble de permissions par défaut** (section 6) — il reste possible de retirer ou ajouter une permission ponctuelle sans changer de rôle (ex. un caissier avec `payments.refund` jusqu'à un seuil précis, sans lui donner tout le rôle Responsable financier).

---

## 8. Matrice de permissions

Matrice de référence — colonnes = rôles, lignes = actions. `✔` accès direct, `✔*` accès avec restriction/approbation (voir note), `—` refusé.

| Action | Super Admin | Directeur | Finance | Caissier | Enseignant | Parent | Élève |
|---|---|---|---|---|---|---|---|
| Voir élèves | ✔* (audité) | ✔ | ✔ | — | ✔* (ses classes) | ✔* (ses enfants) | ✔* (lui-même) |
| Modifier élèves | ✔* (audité) | ✔ | — | — | — | — | — |
| Voir paiements | ✔* (audité) | ✔ | ✔ | ✔* (ceux qu'il enregistre) | — | ✔* (ses enfants) | ✔* (lui-même) |
| Créer un paiement | — | ✔ | ✔ | ✔* (≤ seuil) | — | — | — |
| Annuler un paiement | — | ✔ | ✔ | — | — | — | — |
| Rembourser | — | ✔* (approbation si > seuil) | ✔* (approbation si > seuil) | — | — | — | — |
| Voir trésorerie | ✔* (audité) | ✔ | ✔ | — | — | — | — |
| Modifier compte bancaire | — | ✔* (step-up + double validation) | — | — | — | — | — |
| Modifier Mobile Money | — | ✔* (step-up + double validation) | — | — | — | — | — |
| Gérer utilisateurs | ✔* (audité) | ✔ | — | — | — | — | — |
| Gérer permissions/rôles | ✔* (audité) | ✔* (step-up) | — | — | — | — | — |
| Exporter des données | ✔* (audité) | ✔* (limité et audité) | ✔* (financier uniquement) | — | — | — | — |
| Voir l'audit | ✔ | ✔* (son établissement) | — | — | — | — | — |
| Utiliser l'IA (`ai.use`) | ✔* (audité, portée globale interdite) | ✔ | ✔ | ✔* (lecture limitée) | ✔* (lecture limitée) | ✔* (ses enfants) | ✔* (lui-même) |

**Le tableau ci-dessus n'est pas théorique** : il doit être transcrit tel quel dans `assets/js/permissions.js` en tant que définition `ROLE_DEFAULT_PERMISSIONS`, qui deviendra la donnée de départ (seed) du futur moteur RBAC backend. Aucun rôle, y compris Super Admin, n'a de règle spéciale "bypass" codée en dur — le Super Admin a des permissions *larges mais explicites*, jamais un accès qui court-circuite la vérification (principe 18).

Statut : `✅ IMPLÉMENTÉ` en tant que référence codifiée · `⛔ NON APPLIQUÉ` (pas de backend pour l'appliquer).

---

## 9. Sécurité financière

### 9.1 Le frontend ne décide jamais

Montant final, statut d'un paiement, compte bénéficiaire, confirmation — toujours recalculés et vérifiés côté serveur. Si le frontend envoie `amount: 1` pour une dette de `250`, le serveur rejette : la source de vérité du montant dû est le dossier financier de l'élève, jamais l'entrée utilisateur brute.

### 9.2 États de transaction explicites

```
CREATED → PENDING → PROCESSING → CONFIRMED
                                → FAILED
                                → CANCELLED
                                → EXPIRED
                  → UNKNOWN (jamais traité automatiquement comme FAILED)
CONFIRMED → REFUNDED / REVERSED (jamais supprimé)
```

`UNKNOWN` est un état à part entière : une coupure réseau pendant l'appel au fournisseur Mobile Money ne doit **jamais** être interprétée par défaut comme un échec (l'argent a peut-être été débité) ni comme un succès — le système doit vérifier activement l'état réel auprès du fournisseur avant de trancher (principe 17).

### 9.3 Idempotence et unicité

Chaque opération financière porte : `transaction_id` interne, `order_id`, `idempotency_key` (fournie par le client pour éviter un double clic → double paiement), `provider_reference`, `audit_id`. Une requête rejouée avec la même `idempotency_key` renvoie le résultat déjà obtenu, jamais une deuxième exécution.

### 9.4 Webhooks (Mobile Money / banque)

Pour chaque webhook entrant : vérifier la signature cryptographique, vérifier l'origine, vérifier le timestamp (fenêtre de validité courte, anti-replay), vérifier que la transaction référencée existe et est dans un état compatible, vérifier montant/devise/tenant, traiter de façon idempotente, journaliser systématiquement — y compris les webhooks rejetés (ils sont un signal de sécurité en soi).

### 9.5 Protection des comptes de règlement — zone la plus critique

Un attaquant qui compromet un compte administrateur **ne doit pas pouvoir**, d'un simple changement de champ, rediriger les paiements de l'école vers son propre compte Mobile Money ou bancaire. Toute modification de destination financière exige, cumulativement :

1. MFA (déjà actif sur le compte, section 5) ;
2. permission spécifique `bank_accounts.manage` / `mobile_money.manage` (pas incluse dans un rôle large par défaut) ;
3. step-up authentication (section 5.1) ;
4. approbation d'un second utilisateur habilité (section 6.3) ;
5. délai de sécurité avant activation effective, si pertinent pour l'établissement ;
6. notification immédiate à tous les administrateurs de l'établissement, sur un canal distinct de celui utilisé pour la modification ;
7. journalisation complète (avant/après) ;
8. capacité de rollback vers la configuration précédente ;
9. vérification côté fournisseur du nouveau compte quand une API le permet.

### 9.6 Concurrence et race conditions

Deux caissiers qui enregistrent "simultanément" le même paiement, deux webhooks pour la même transaction, deux modifications concurrentes d'une même configuration : résolu par transactions base de données atomiques, contraintes d'unicité (ex. unique sur `provider_reference`), verrous optimistes ou pessimistes selon le cas, et l'idempotence de la section 9.3. Objectif : **aucun double paiement, aucun double remboursement, aucune corruption de solde**, même sous forte concurrence.

Statut : `📋 PLANIFIÉ` — le moteur financier n'existe pas encore dans le code (cohérent avec `OBJECTIFS_ET_FONCTIONNALITES.md` §29, le MVP financier n'a pas commencé).

---

## 10. Sécurité de l'IA — renvoi

L'intégralité de la sécurité IA (permission layer, tool calling contrôlé, prompt injection, isolation multi-tenant appliquée à l'IA, journalisation des actions IA) est déjà spécifiée en détail dans `SYSTEME_IA.md` §6, §10.9 (niveaux d'action), §11 (validation humaine), §12 (sécurité complète). Rien n'est dupliqué ici. Un seul ajout côté matrice : la permission `ai.use` (section 6, 8) confirme que l'IA n'est jamais un chemin de contournement — elle est soumise exactement au même Permission Layer que n'importe quelle route API classique.

---

## 11. Audit et traçabilité

Journal général (distinct du journal IA `AIAuditLog` de `SYSTEME_IA.md` Annexe A, même infrastructure) :

```
AuditLog {
  id, tenant_id, actor_id, actor_role, action, resource_type, resource_id,
  timestamp, status: success|denied|error,
  ip, user_agent, before?, after?, reason?, request_id
}
```

**Exemples concrets attendus dans ce journal :** *"Yvon a modifié le prix de l'uniforme"*, *"Admin X a créé une dépense"*, *"Caissier Y a enregistré un paiement de 250 $"*, *"Admin Z a tenté d'accéder à une autre école — refusé"*, *"Compte Mobile Money modifié — approuvé par deux administrateurs"*.

**Immutabilité :** les logs critiques ne sont jamais supprimables par un utilisateur normal — seule une politique de rétention légale, appliquée par un processus système, peut les purger après expiration. Une tentative d'accès refusée (`status: denied`) est journalisée **au même titre** qu'une action réussie — c'est souvent le signal de sécurité le plus utile.

**Immutabilité financière (principe 6) :** jamais de `DELETE` sur une transaction — toujours `transaction originale + correction + reversal + trace d'audit`, pour que l'historique reste reconstituable intégralement.

Statut : `📋 PLANIFIÉ`.

---

## 12. Gestion des secrets

Ne doivent **jamais** apparaître dans : le frontend, le JavaScript public, Git, un `.env` commité, les logs, une réponse API. Concerné : clés API de paiement (Mobile Money, banque), clés API des fournisseurs IA (`SYSTEME_IA.md` §13), secrets de webhook, identifiants de base de données, secret de signature JWT, clés de chiffrement, secrets OAuth.

**Pratiques attendues :** un gestionnaire de secrets dédié dès que l'hébergement est choisi (ex. secret manager du cloud retenu, ou Vault) plutôt que des variables d'environnement en clair au-delà du strict développement local ; rotation régulière programmée, en particulier après le départ d'un employé ayant eu accès à des clés de production ; scan automatique pour empêcher qu'un secret ne parte dans un commit Git.

Statut : `📋 PLANIFIÉ` · souvent `🔌 NÉCESSITE UN FOURNISSEUR EXTERNE` (le secret manager lui-même).

---

## 13. Sécurité de la base de données

La sécurité n'est pas que dans le code applicatif — la base doit refuser certaines incohérences même en cas de bug applicatif : clés étrangères, contraintes d'unicité (ex. un `provider_reference` ne peut exister deux fois), contraintes de vérification (`CHECK`, ex. un montant ne peut être négatif sur une obligation), transactions ACID pour toute écriture financière composite, index adaptés aux requêtes scopées par tenant, Row-Level Security si le SGBD le permet (section 3).

Statut : `📋 PLANIFIÉ`.

---

## 14. Sécurité des API

Chaque endpoint applique, dans cet ordre : authentification → autorisation (permission + tenant + ressource précise) → validation stricte des entrées → rate limiting → journalisation.

### 14.1 IDOR / BOLA (Broken Object Level Authorization)

Le cas cité en exemple — un parent change `/student/123` en `/student/124` dans l'URL — doit être bloqué par le backend indépendamment de ce que montre l'interface, sur **toutes** les ressources : élèves, parents, paiements, factures, dépenses, documents, rapports, classes, établissements, utilisateurs, comptes bancaires, transactions, stock. Règle simple à appliquer systématiquement : *charger la ressource, vérifier qu'elle appartient au tenant et à l'utilisateur avant même de regarder ce qu'il demande d'en faire.*

### 14.2 Frontend vs backend

Le frontend peut masquer un bouton "Supprimer paiement" pour un caissier — cela reste un confort d'affichage. L'API doit indépendamment refuser `DELETE /payments/123` à ce même caissier, que le bouton ait existé ou non côté client.

### 14.3 Injections et web classiques

XSS, CSRF, injection SQL/NoSQL/commande : requêtes paramétrées systématiques (jamais de concaténation de chaînes vers une requête), échappement en sortie, Content-Security-Policy, headers de sécurité (section 14.4), validation stricte de toute entrée y compris dans la recherche, les exports et les imports.

### 14.4 Headers de sécurité

`Content-Security-Policy`, `Strict-Transport-Security` (HSTS), `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy`, protection anti-clickjacking (`X-Frame-Options` ou équivalent CSP `frame-ancestors`).

Statut : `📋 PLANIFIÉ`.

---

## 15. Détection d'activité suspecte et alertes

Événements à surveiller, avec un niveau de sévérité (`INFO · LOW · MEDIUM · HIGH · CRITICAL`) : tentatives de connexion répétées, connexion depuis un nouvel appareil/localisation inhabituelle, changement de mot de passe ou de MFA, changement de permission ou création d'administrateur, changement de compte bancaire/Mobile Money (toujours `CRITICAL`), export massif, volume anormal de requêtes API, rafale d'opérations financières, tentative d'accès à un autre établissement (toujours `HIGH` minimum).

Statut : `📋 PLANIFIÉ`.

---

## 16. Rate limiting

Limites dédiées (configurables, pas de valeur unique codée en dur) pour : login, réinitialisation de mot de passe, vérification OTP, endpoints API généraux, recherche, exports, imports Excel, génération de rapport, actions financières, tout endpoint marqué sensible. Objectif double : empêcher l'abus **et** ne jamais pénaliser un établissement légitime à fort usage — d'où des limites par tenant et non uniquement globales.

Statut : `📋 PLANIFIÉ`.

---

## 17. Sécurité des fichiers (upload, Excel, documents)

### 17.1 Upload / import Excel

Un fichier uploadé n'est **jamais** fiable par défaut : limite de taille, whitelist de types/extensions, validation du MIME réel (pas seulement l'extension déclarée), stockage isolé du reste de l'application, traitement dans un environnement qui ne peut pas exécuter de contenu actif, protection contre les formules Excel dangereuses (ex. liens externes, macros — à rejeter systématiquement pour un import de données), détection de fichiers anormaux (taille disproportionnée par rapport au contenu, structure incohérente).

Le contenu du fichier est toujours traité comme **donnée à analyser**, jamais comme instruction — y compris pour l'IA qui propose le mapping (`SYSTEME_IA.md` §12.2 et §10.7).

### 17.2 Documents (reçus, factures, certificats, justificatifs)

Accès uniquement authentifié et vérifié par tenant/permission ; si le stockage est un service objet (S3-like), utiliser des URLs temporaires signées plutôt que des liens publics permanents ; audit de chaque consultation d'un document sensible ; expiration des liens de partage si la fonctionnalité existe.

Statut : `📋 PLANIFIÉ`.

---

## 18. Sécurité des notifications

Une notification ne doit jamais transporter plus d'information sensible que nécessaire — en particulier par SMS, canal le moins sécurisé : pas de détail financier complet, pas de donnée personnelle excessive, jamais rien qui permettrait à un tiers interceptant le SMS de prendre le contrôle d'un compte (ex. jamais un lien de réinitialisation de mot de passe par SMS non protégé). Les préférences et permissions de l'utilisateur sont toujours respectées (cohérent avec `SYSTEME_IA.md` §9 sur l'anti-spam).

Statut : `📋 PLANIFIÉ`.

---

## 19. Sécurité des changements de configuration

Toute modification de configuration sensible (règles de sécurité, seuils d'approbation, intégrations de paiement, paramètres MFA de l'établissement) suit le même schéma que les comptes de règlement (section 9.5) à un niveau adapté à sa criticité : permission dédiée, audit systématique, notification aux administrateurs concernés, capacité de rollback.

Statut : `📋 PLANIFIÉ`.

---

## 20. Super Administrateur vs Administrateur d'établissement

**Ne jamais confondre les deux.** `SCHOOL_ADMIN` (Directeur) est strictement limité à son établissement — aucun accès implicite aux autres tenants, même en lecture.

`SUPER_ADMIN` (interne à l'équipe Klassio) est un rôle à part, distinct de tous les rôles d'établissement :
- MFA obligatoire, sans exception ;
- session renforcée (durée plus courte, re-authentification plus fréquente) ;
- **toute** consultation de donnée d'un établissement par un Super Admin est auditée et visible — pas d'accès "discret" aux données financières d'une école ;
- certaines opérations Super Admin nécessitent une approbation (ex. accès direct aux données financières d'un tenant pour du support) ;
- accès temporaire et justifié plutôt que permanent, lorsque c'est réalisable (accès "just-in-time").

Statut : `📋 PLANIFIÉ`.

---

## 21. Réponse aux incidents

Plan en cas de compromission détectée : détecter → alerter les responsables → isoler le compte/composant affecté → révoquer les sessions concernées → révoquer les secrets compromis → bloquer les actions suspectes en cours → préserver les logs (ne jamais les purger pendant une investigation) → analyser la cause → corriger → restaurer si nécessaire (section 22) → vérifier que la correction tient → notifier les parties concernées si une obligation légale l'exige → documenter l'incident pour capitaliser dessus.

Statut : `📋 PLANIFIÉ` — un plan écrit peut et doit exister avant même le premier utilisateur réel ; ce n'est pas seulement du code, c'est aussi une procédure pour l'équipe.

---

## 22. Sauvegardes et reprise après sinistre

**Backups :** fréquence adaptée à la criticité des données (financier = plus fréquent), chiffrées, stockées séparément de l'environnement de production, politique de rétention définie, **restauration testée régulièrement** — une sauvegarde jamais restaurée pour test n'est pas une sauvegarde fiable.

**Disaster Recovery :** définir un RPO (perte de données maximale acceptable) et un RTO (temps de restauration maximal acceptable) explicites avant que ce soit un problème réel ; procédures écrites pour : corruption de base de données, compromission, ransomware, panne du fournisseur cloud, perte d'une région.

Statut : `📋 PLANIFIÉ` · `🔌 NÉCESSITE UN FOURNISSEUR EXTERNE` pour l'infrastructure de sauvegarde elle-même.

---

## 23. Environnements

Séparation stricte `development` / `staging` / `production`. Les secrets de production ne circulent jamais en développement. Les données réelles d'un établissement ne sont jamais copiées librement vers un environnement de test — si des données de test réalistes sont nécessaires, elles sont anonymisées/synthétiques.

Statut : `📋 PLANIFIÉ` (aucun environnement de déploiement n'existe encore).

---

## 24. Sécurité des dépendances

Scan de dépendances, mises à jour régulières, lockfiles commités, détection de CVE connues, audit périodique des packages utilisés, suppression de toute dépendance non utilisée. Une bibliothèque n'est ajoutée que si elle est nécessaire, maintenue et dont la surface de risque a été considérée — pas "parce qu'elle est populaire".

Statut : `📋 PLANIFIÉ` (le prototype actuel n'a d'ailleurs aucune dépendance externe — HTML/CSS/JS pur, ce qui minimise déjà cette surface pour l'instant).

---

## 25. Security Center (interne, pour administrateurs autorisés)

Concept d'écran interne — cohérent avec la philosophie *"complexité derrière, simplicité devant"* déjà posée pour le reste du produit et pour l'IA (`SYSTEME_IA.md` §15) : sessions actives, appareils connus, dernières connexions, événements suspects récents, état du MFA, permissions et administrateurs de l'établissement, intégrations et clés actives (sans jamais afficher la valeur d'un secret), événements financiers critiques récents, historique des changements de configuration.

**Ce Security Center n'est pas un tableau de bord anxiogène.** Il suit le même design system que le reste de Klassio (lime en accent, cartes calmes, pas de rouge criard sauf pour une alerte réellement critique) — la sécurité doit rassurer, pas inquiéter.

Statut : `📋 PLANIFIÉ` (aucun écran construit à ce stade — l'effort de ce tour a porté sur la spécification et le catalogue de permissions).

---

## 26. UX de la sécurité

Cohérent avec la voix déjà établie du produit (jamais un ton "erreur système") :

| Au lieu de… | Klassio dit… |
|---|---|
| `ERROR 403 RBAC POLICY VIOLATION` | *« Vous n'avez pas l'autorisation d'effectuer cette action. »* |
| Blocage silencieux d'une action critique | *« Cette opération nécessite une validation supplémentaire. »* |
| `500 Internal Server Error` sur un paiement en `UNKNOWN` | *« Nous vérifions ce paiement, vous serez informé dès confirmation. »* (jamais présenté comme un échec avant vérification réelle) |

Statut : `📋 PLANIFIÉ` (les écrans d'erreur n'existent pas encore dans le prototype, qui ne gère aujourd'hui aucun cas d'erreur réel).

---

## 27. Tests de sécurité

Reprise directe des tests attendus, à automatiser dès que le backend existe :

| # | Scénario | Résultat attendu |
|---|---|---|
| 1 | Parent A tente d'accéder à l'élève B (pas le sien) | `403` |
| 2 | Établissement A tente d'accéder à une ressource de l'établissement B | Refusé, quelle que soit la méthode (API directe, IA, export) |
| 3 | Caissier tente de modifier un compte bancaire | Refusé |
| 4 | Le frontend envoie un montant de paiement modifié | Le serveur recalcule et rejette l'écart |
| 5 | Faux webhook (signature invalide) | Rejeté et journalisé |
| 6 | Webhook reçu deux fois (même transaction) | Une seule transaction enregistrée (idempotence) |
| 7 | L'IA reçoit une demande de données hors permission | Refusé par le Permission Layer, pas par l'IA elle-même |
| 8 | Modification d'un identifiant dans l'URL pour accéder à une autre ressource (IDOR) | Refusé |

**Stratégie plus large :** tests unitaires sur chaque vérification de permission, tests d'intégration sur les workflows d'approbation (section 6.3), tests end-to-end sur les parcours critiques (paiement, remboursement, changement de compte de règlement), corpus dédié de tentatives de prompt injection (`SYSTEME_IA.md` §21), et préparation de l'architecture pour un audit de sécurité externe / pentest une fois un premier backend réel déployé (fuzzing d'autorisation, tests d'authentification, tests d'isolation multi-tenant, tests de sécurité des paiements).

Statut : `📋 PLANIFIÉ`.

---

## 28. Architecture globale

```
                    UTILISATEUR
                         ↓
                 AUTHENTIFICATION
                         ↓
               SÉCURITÉ DE SESSION
                         ↓
             CONTEXTE DE TENANT (établissement)
                         ↓
             RÔLE / PERMISSIONS (RBAC + contextuel)
                         ↓
               POLICY ENGINE (deny by default)
                         ↓
             BUSINESS LOGIC LAYER (règles métier)
                         ↓
        ┌────────────────┼─────────────────┐
        ↓                ↓                  ↓
    FINANCE          ÉLÈVES             STOCK / CATALOGUE
        ↓                ↓                  ↓
        └────────────────┼─────────────────┘
                         ↓
                    BASE DE DONNÉES (contraintes + RLS)
                         ↓
                  SYSTÈME D'AUDIT (immuable)
```

**Protections transversales, actives à chaque étage :** chiffrement (transit + repos), monitoring, rate limiting, journalisation, sauvegardes, gestion des secrets, alerting, plan de réponse aux incidents.

Cette architecture est cohérente avec celle déjà posée pour l'IA dans `SYSTEME_IA.md` §2-3 — l'IA n'est qu'un client de plus du même Policy Engine et de la même Business Logic, jamais un chemin parallèle.

---

## 29. Feuille de route d'implémentation

### Maintenant (fait dans ce tour de travail)
- Ce document de spécification.
- Catalogue de permissions codifié — [assets/js/permissions.js](../assets/js/permissions.js).
- Garde-fou documenté dans le code existant précisant que le filtrage de menu côté client n'est pas une sécurité.

### MVP (avec le premier backend réel)
- Authentification (email/mot de passe, hash Argon2id, sessions avec rotation).
- RBAC appliqué à *tous* les endpoints dès le premier jour (principe non négociable — pas de dette de sécurité, cf. `SYSTEME_IA.md` §22 qui pose la même exigence côté IA).
- Isolation multi-tenant aux trois niveaux (section 3) dès la première requête.
- Audit de base sur les actions sensibles (section 11).
- Protection IDOR/BOLA systématique (section 14.1).
- États de transaction explicites + idempotence (section 9.2-9.3).

### V1
- MFA pour les rôles sensibles + step-up authentication (sections 5-5.1).
- Workflow d'approbation (séparation des responsabilités, section 6.3).
- Webhook security complète (section 9.4).
- Rate limiting complet (section 16).
- Détection d'activité suspecte de base (section 15).
- Sécurité des uploads/Excel (section 17.1).

### V2+
- Security Center (section 25).
- Accès Super Admin "just-in-time" avec approbation (section 20).
- Détection d'anomalie financière avancée (rejoint `SYSTEME_IA.md` §10.8).
- Pentest externe formalisé (section 27).

### Plus tard
- Passkeys/WebAuthn.
- Programme de bug bounty une fois une base d'utilisateurs réelle établie.

---

## Annexe A — Modèles de données indicatifs (complète `SYSTEME_IA.md` Annexe A)

```
User              { id, tenant_id, email, phone?, password_hash, mfa_enabled,
                    mfa_secret?, status, created_at }
Role              { id, tenant_id?, name, is_system_role }
Permission        { id, key }                      # ex. "payments.refund"
RolePermission    { role_id, permission_id }
UserPermission    { user_id, permission_id, scope?, expires_at? }  # exceptions ponctuelles
ApprovalRequest   { id, tenant_id, requested_by, action, payload,
                    status: pending|approved|rejected, approved_by?, decided_at?, reason? }
AuditLog          { id, tenant_id, actor_id, actor_role, action, resource_type,
                    resource_id, timestamp, status, ip, user_agent, before?, after?,
                    reason?, request_id }
Session           { id, user_id, device_info, ip, created_at, expires_at, revoked_at? }
SecurityAlert     { id, tenant_id, user_id?, type, severity, details, created_at,
                    status: open|reviewed|resolved }
```

## Annexe B — Principes non négociables (rappel condensé)

Voir section 1. À conserver dans toute documentation d'architecture future — ces règles priment sur toute décision d'implémentation ponctuelle.

## Annexe C — Légende de statut

| Étiquette | Signification |
|---|---|
| ✅ IMPLÉMENTÉ | Existe réellement dans le code actuel et fonctionne |
| 🟡 PARTIEL | Partiellement codé, incomplet ou non appliqué partout |
| 📋 PLANIFIÉ | Spécifié dans ce document, pas encore codé |
| ⛔ NON IMPLÉMENTÉ | Ni codé ni encore spécifié en détail |
| 🔌 NÉCESSITE UN FOURNISSEUR EXTERNE | Dépend d'un service tiers (secret manager, SMS/OTP, hébergement, stockage objet…) à choisir |

À ce stade du projet, l'écrasante majorité des protections listées ici sont `📋 PLANIFIÉ`, ce qui est cohérent : il n'existe pas encore de backend. Ce document est la spécification qui guidera sa construction — pas une déclaration que le système est déjà sécurisé.
