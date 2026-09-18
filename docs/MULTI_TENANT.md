# KLASSIO — Architecture Multi-Tenant et Isolation entre Établissements
### Spécification V0.1 — Multi-Tenant & School Isolation Architecture

Ce document devient la référence autoritaire et détaillée de l'isolation multi-tenant. Il **étend** [SECURITE.md](SECURITE.md) §3 (qui reste le résumé côté sécurité générale) et s'articule avec [FINANCE.md](FINANCE.md) (isolation financière), [SYSTEME_IA.md](SYSTEME_IA.md) (isolation IA), [EVENEMENTS.md](EVENEMENTS.md) (isolation événementielle) et [IMPORT.md](IMPORT.md) (import tenant-aware). Rien n'y est dupliqué — chaque section renvoie plutôt que de répéter.

## 0. État réel du projet

Sans changement : aucun backend, aucune base de données. Tout ce document est `📋 PLANIFIÉ`, à l'exception du catalogue de référence en Annexe A. Légende identique aux cinq documents précédents.

---

## 1. Vision

*Une plateforme. Plusieurs écoles. Zéro confusion.* Chaque directeur doit ressentir : *"Ceci est l'environnement de mon école"* — jamais *"je suis dans une énorme base où tout est mélangé"*. Derrière cette simplicité, l'isolation n'est pas une fonctionnalité parmi d'autres : c'est une **frontière de sécurité** qui traverse toute l'architecture, au même titre qu'un pare-feu entre deux entreprises totalement indépendantes qui partageraient, à leur insu, le même immeuble.

---

## 2. Terminologie

| Terme | Définition |
|---|---|
| **Tenant** | Un établissement scolaire — l'unité d'isolation fondamentale du système |
| **Organization** | Regroupement optionnel de plusieurs tenants sous une même entité administrative (groupe scolaire) — n'efface jamais l'isolation entre les tenants qu'elle regroupe |
| **Campus** | Site physique d'un même tenant (un établissement multi-bâtiments reste **un seul tenant**, le campus est une subdivision interne, pas une frontière de sécurité) |
| **Tenant Context** | L'ensemble {tenant_id, année scolaire active, permissions résolues} déterminé par le backend pour une requête donnée — jamais fourni par le client |
| **Membership** | Le lien vérifié entre un utilisateur et un ou plusieurs tenants, avec un rôle par tenant |
| **Platform Administrator** | Compte interne à l'équipe Klassio, structurellement distinct de tout rôle d'établissement (section 16) |

---

## 3. Modèle de tenant et hiérarchie

Un établissement multi-sites, ou primaire+secondaire sous une même direction, reste **un seul tenant** — le multi-site est un problème d'organisation interne (campus, niveaux), pas d'isolation. Un **groupe scolaire** (plusieurs établissements juridiquement/administrativement distincts, même s'ils partagent un même propriétaire) est en revanche modélisé comme plusieurs tenants reliés par une `Organization` :

```
Organization (optionnelle — groupe scolaire)
   ↓
Tenant / School  ← frontière de sécurité, unité d'isolation
   ↓
Campus (subdivision interne, pas une frontière de sécurité)
   ↓
AcademicYear
   ↓
Level → Class → Student
```

Un utilisateur "directeur de groupe" obtient un **membership explicite sur chaque tenant** de l'organisation, jamais un accès implicite à tous les tenants du groupe parce qu'il existe une `Organization` commune (section 12). L'`Organization` sert à l'agrégation de rapports (avec permission dédiée, section 20) — jamais de raccourci d'accès aux données.

Statut : `📋 PLANIFIÉ`.

---

## 4. Identité du tenant et des entités

- `tenant_id` : identifiant interne opaque (ex. `TEN_01H...`), **jamais dérivé** du nom, de l'adresse, du téléphone ou du nom du directeur. Deux écoles nommées `Complexe Scolaire Les Élites` restent deux tenants strictement distincts.
- Toute entité métier (élève, parent, paiement, classe, facture, obligation, événement, notification) porte `tenant_id` en plus de son identifiant local.
- **Un `student_id` n'est jamais unique globalement par convention implicite** — son unicité réelle est `(tenant_id, student_id)`. `STU_001` chez le tenant A et `STU_001` chez le tenant B sont deux élèves différents, jamais rapprochés.
- Un matricule scolaire (`identifiant externe` choisi par l'école) est unique **dans le tenant**, jamais globalement — deux écoles peuvent parfaitement utiliser la même numérotation.

**Règle absolue (section 9 du brief) :** `GET student WHERE name = "Jean Dupont"` n'est jamais une requête valide en soi — elle doit toujours être contextualisée par `tenant_id`. Deux élèves nommés Jean Dupont dans deux tenants différents ne sont **jamais** fusionnés ou rapprochés automatiquement (cohérent avec `IMPORT.md` §9, la détection de doublons est déjà scopée par tenant côté import). Même règle pour parent, enseignant, classe, paiement, obligation, facture, transaction, document, fournisseur.

Statut : `📋 PLANIFIÉ`.

---

## 5. Shared vs isolated database — comparaison

| Critère | A — DB partagée / schéma partagé + `tenant_id` + RLS | B — DB partagée / schéma par école | C — DB dédiée par école |
|---|---|---|---|
| Sécurité/isolation | Forte si RLS bien implémentée (défense en profondeur, section 8) | Forte nativement, mais dépend de la rigueur du routing de schéma | Maximale — isolation physique totale |
| Coût | Faible, une seule infrastructure | Moyen à élevé (gestion de N schémas) | Élevé, croît linéairement avec le nombre d'écoles |
| Performance | Bonne, mutualisation des ressources ; risque de "noisy neighbor" (section 23) sans quotas | Bonne, mais connexions/migrations coûteuses à grande échelle | Excellente par tenant, isolée des autres |
| Scalabilité (10 → 10 000 écoles) | Excellente — c'est le cas d'usage type des SaaS multi-tenant à grande échelle | Mauvaise au-delà de quelques centaines (limite de schémas/connexions par instance) | Mauvaise en nombre d'écoles, bonne en charge par école |
| Maintenance / migrations | Une seule migration à exécuter | Une migration **par schéma** — risque d'incohérence si une échoue | Une migration par base — même risque, à plus grande échelle opérationnelle |
| Backups / restauration | Nécessite une stratégie de restauration ciblée par tenant (section 19) | Restauration par schéma plus simple à isoler | Restauration triviale par tenant, coûteuse en volume total |
| Monitoring | Nécessite un tenant_id dans chaque métrique/log | Similaire | Isolation naturelle des métriques par base |
| Développement | Le plus simple — un seul schéma à maintenir | Complexité de routing de schéma dans le code | Complexité de routing de connexion dans le code |
| Analytics / reporting global | Trivial (une seule base à interroger, avec permission dédiée) | Nécessite une agrégation cross-schéma | Nécessite une agrégation cross-bases (ETL) |
| Disaster recovery | Standard, un seul plan à opérer | Plus complexe (N schémas à restaurer cohéremment) | Plan par base, opérationnellement lourd à grande échelle |
| Onboarding d'une école | Instantané (une ligne dans `Tenant Registry`) | Création de schéma + migration | Provisioning d'une base entière |
| Suppression d'une école | Purge ciblée par `tenant_id` (section 19) | Suppression de schéma, propre | Suppression de base, propre mais lourde à automatiser en masse |
| Export des données d'une école | Requête filtrée par `tenant_id` | Export de schéma | Export de base complète |
| Déplacement d'une école (vers dédié) | Nécessite un outil de migration dédié (section 46) mais reste réalisable proprement | Migration de schéma vers base dédiée, plus proche techniquement | Déjà dédiée — non applicable |
| Conformité / résidence des données | Possible avec des contraintes (région unique) | Idem | Permet une résidence par pays/région si nécessaire |
| Croissance future | Excellente, standard de l'industrie (Salesforce, la majorité des SaaS B2B) | Ne scale pas au-delà de quelques centaines de tenants | Réservé aux tenants à très fort volume ou exigence spécifique |

**Verdict de l'analyse (pas une supposition de départ) :** l'option B (schéma par école) cumule les inconvénients opérationnels de C (migrations, connexions à multiplier) sans son bénéfice principal (isolation physique) — elle est **écartée**. Le vrai choix est entre A (à grande échelle, standard du marché) et un usage ciblé de C pour des cas particuliers (section 6).

---

## 6. Architecture recommandée

**Option A — base de données partagée, schéma partagé, isolation stricte par `tenant_id` renforcée par Row-Level Security — comme fondation pour la totalité des tenants au MVP et pour l'immense majorité à long terme.** Justification : meilleur compromis coût/scalabilité/maintenabilité pour un produit qui vise 1 → 10 000 écoles, et la sécurité n'est pas sacrifiée si la défense en profondeur (section 9) est appliquée dès le premier jour — la RLS au niveau base de données comble précisément le risque qu'une erreur applicative expose tout.

**Architecture hybride préparée dès maintenant, activée plus tard (réponse à la question 74 du brief) :** un `Tenant Registry` (section 21) enregistre pour chaque tenant son `deployment_mode` (`shared` par défaut, `dedicated` en option). Au MVP, 100 % des tenants sont `shared` et le registre pointe toujours vers la même base — mais la couche d'accès aux données est écrite dès le départ pour résoudre la connexion **via le registre**, jamais en dur. Cela permet, plus tard, de migrer un établissement à très fort volume ou à exigence de résidence particulière vers une base dédiée (section 46) **sans réécrire les repositories** — seul le registre change. C'est un investissement d'architecture minime au MVP (une indirection) pour une option réelle plus tard, ce qui correspond exactement à la distinction "architecture prête" vs "fonctionnalité activée" déjà posée dans `FINANCE.md` §0 et `IMPORT.md` §0.

**Choix de moteur :** PostgreSQL, spécifiquement pour son support natif de Row-Level Security (section 8), déterminant pour cette architecture.

Statut : `📋 PLANIFIÉ` (décision d'architecture, aucune base n'existe encore).

---

## 7. Tenant Resolution et Tenant Context

```
Authentification → Identité utilisateur → Memberships (tenants + rôle par tenant)
   → Tenant sélectionné (explicite si multi-tenant, section 12) → Validation serveur du membership
   → Tenant Context { tenant_id, academic_year_id, role, permissions résolues }
   → Autorisation → Business Logic
```

**Le frontend n'est jamais la source du tenant autorisé** (`SECURITE.md` §14.2) : un `tenant_id` dans une URL, un JSON, un paramètre de requête, le `localStorage` ou un cookie n'est **jamais** utilisé tel quel — le backend détermine seul le tenant à partir de l'identité authentifiée et de ses memberships vérifiés en base à chaque requête sensible.

### 7.1 Utilisateur multi-tenant (directeur de groupe)

```
User → Memberships [ {tenant: A, role: director}, {tenant: B, role: director} ]
```

Le changement de tenant actif est **explicite** (action utilisateur claire, jamais déduite d'un paramètre), **vérifié côté serveur** contre les memberships réels, et **audité** (`security.tenant_context_switched`, cohérent avec `EVENEMENTS.md` §6.2) — jamais un simple changement de variable côté client.

Statut : `📋 PLANIFIÉ`.

---

## 8. Isolation au niveau base de données — Row-Level Security

Ne jamais se reposer uniquement sur `WHERE tenant_id = ?` dans le code applicatif — une seule requête oubliée expose potentiellement toutes les écoles. Avec PostgreSQL :

```sql
ALTER TABLE students ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON students
  USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
```

Le backend positionne `app.current_tenant_id` **une fois par requête/transaction**, à partir du Tenant Context déjà résolu et vérifié (section 7) — jamais à partir d'une valeur fournie par le client. Une politique RLS équivalente est appliquée à **chaque table tenant-scoped** (section 10.3), sans exception ni raccourci pour les tables "sensibles mais rarement interrogées" — c'est justement celles-là que RLS protège le mieux en cas d'oubli de développeur.

Statut : `📋 PLANIFIÉ`.

---

## 9. Défense en profondeur

Le schéma du brief est juste, réordonné légèrement pour refléter l'ordre réel d'exécution d'une requête :

```
1. Authentification            — qui est cet utilisateur ?
2. Résolution du tenant         — pour quelle école cette requête s'exécute-t-elle ? (section 7)
3. Autorisation                 — a-t-il le droit, dans ce tenant, pour ce rôle ? (SECURITE.md §6-8)
4. Scoping applicatif            — chaque requête au repository est automatiquement filtrée (section 13)
5. Contraintes base de données   — clés étrangères composites, contraintes d'unicité (section 10.4)
6. Row-Level Security            — dernier filet, appliqué même si 1-4 ont une faille (section 8)
7. Audit                         — chaque accès (accordé ou refusé) est journalisé (SECURITE.md §11)
8. Monitoring/alerting           — un motif d'accès cross-tenant tenté déclenche une alerte (section 24)
```

Une erreur dans une seule couche ne suffit jamais à exposer une autre école — c'est le test de la section 17.

Statut : `📋 PLANIFIÉ`.

---

## 10. Modèle de données tenant-aware

### 10.1 Vue d'ensemble

```
Tenant
 ├── TenantSettings · TenantUsers (memberships)
 ├── AcademicYear → Level → Class → Student → Guardian
 ├── FinancialAccount → Obligation → Payment (FINANCE.md §22)
 ├── Expense · TreasuryAccount · Inventory (FINANCE.md, tenant-scoped)
 ├── Document
 ├── Event · Rule · Notification (EVENEMENTS.md §22, tenant-scoped)
 ├── AIContext (SYSTEME_IA.md, tenant + user scoped, section 13)
 └── AuditLog
```

### 10.2 Relations et incohérences interdites

```
School → AcademicYear → Class → Student → FinancialAccount → Obligation → Payment
```

Un `Payment` référençant un `Student` d'un **autre** tenant est une incohérence interdite structurellement, pas seulement par convention applicative (section 10.4).

### 10.3 Tables tenant-scoped vs globales

| Tenant-scoped (portent `tenant_id`) | Globales (jamais de `tenant_id`) |
|---|---|
| Student, Guardian, Class, AcademicYear | User (l'identité globale — ses *memberships* sont tenant-scoped, pas l'utilisateur lui-même) |
| Obligation, Payment, Expense, TreasuryAccount, Asset | Event (au sens infra — mais son **payload** porte `tenant_id`, cohérent avec `EVENEMENTS.md` §6.1) |
| Event (métier), Rule, Notification, NotificationTemplate (sauf override global, section 22) | PaymentProviderConfig (le catalogue de fournisseurs disponibles est global, la configuration d'un compte marchand par école est tenant-scoped) |
| Document, ImportJob (`IMPORT.md` §23) | TenantRegistry lui-même (décrit les tenants, n'appartient à aucun) |
| AuditLog, AIContext | PlatformAdministrator (section 16) |

### 10.4 Contraintes composites

Pour empêcher structurellement `Payment(tenant A) → Student(tenant B)` même si les deux identifiants existent : les clés étrangères sensibles utilisent la paire `(tenant_id, entity_id)` plutôt que `entity_id` seul.

```sql
-- Student : unicité locale au tenant
ALTER TABLE students ADD CONSTRAINT uq_student UNIQUE (tenant_id, id);

-- Payment : la FK composite garantit que tenant_id concorde des deux côtés
ALTER TABLE payments ADD CONSTRAINT fk_payment_student
  FOREIGN KEY (tenant_id, student_id) REFERENCES students (tenant_id, id);
```

Si `payments.tenant_id` ne correspond pas au `tenant_id` réel de `students`, l'insertion échoue **au niveau base de données**, indépendamment de tout bug applicatif — c'est la protection la plus forte possible contre une incohérence cross-tenant.

### 10.5 Matrice des contraintes d'unicité

| Portée | Exemples |
|---|---|
| **Globale** | `user_id`, `event_id`, `payment_provider_transaction_id` (l'ID externe d'un fournisseur de paiement est unique au monde, pas par école) |
| **Tenant-scoped** | `student_number` (matricule), `class_code`, `invoice_number`, tout identifiant "métier" choisi par l'établissement |

Statut : `📋 PLANIFIÉ`.

---

## 11. Isolation financière et paiements

### 11.1 Financial Core et tenant

Chaque `Obligation`, `Payment`, `Refund`, `Expense`, `TreasuryAccount`, `BankAccount`, `CashRegister`, `Supplier`, `Payroll`, `LedgerEntry` (`FINANCE.md` §22) porte `tenant_id` — sans exception. Un dashboard d'école A ne peut structurellement pas afficher un revenu d'école B, sauf pour un rôle explicitement autorisé à une vue agrégée d'`Organization` (section 3, avec permission dédiée).

### 11.2 Comptes de règlement par fournisseur

```
Tenant A → Orange Merchant Account A → Settlement destination A
Tenant B → Orange Merchant Account B → Settlement destination B
```

Le mapping `tenant_id → provider_account_id` est une donnée de configuration protégée au même niveau que les secrets (`SECURITE.md` §12) — jamais dérivée d'un paramètre de requête. Toute modification de ce mapping suit exactement le protocole déjà défini pour un changement de destination de règlement (`FINANCE.md` §9.5, `SECURITE.md` §9.5) : MFA, step-up, double validation, notification immédiate, audit.

### 11.3 Isolation des webhooks — ne jamais faire confiance au tenant fourni par le client

Un webhook Orange Money ne porte pas nécessairement un `tenant_id` Klassio explicite. Résolution du tenant par recoupement, **jamais par un champ envoyé tel quel** :

```
Webhook reçu
   → identification du compte marchand/provider destinataire (configuration connue côté Klassio)
   → résolution tenant_id à partir du mapping compte marchand → tenant (section 11.2)
   → vérification de la référence de transaction interne (émise par Klassio au moment du paiement, donc déjà tenant-scoped)
   → vérification signature + montant + devise attendus (SECURITE.md §9.4)
   → si tout concorde → Financial Core (tenant confirmé) → Event payment.confirmed (tenant_id résolu, jamais deviné)
```

Si la résolution échoue à un seul de ces points, le webhook est rejeté et journalisé — **jamais traité "au mieux" avec un tenant supposé**.

Statut : `📋 PLANIFIÉ`.

---

## 12. Isolation événementielle et notifications

Renvoi complet à `EVENEMENTS.md` §25 pour les principes ; précisions propres à ce document :

- **Routing tenant-aware du bus** : chaque événement porte `tenant_id` dans son enveloppe (pas seulement dans le payload) ; les abonnements de consommateurs peuvent être filtrés par tenant lorsque pertinent (ex. un webhook client externe à une seule école), et un consommateur générique (Rule Engine, Notification Engine) doit systématiquement propager le `tenant_id` de l'événement source à toute action qu'il déclenche — jamais le perdre en route.
- **Notification** : liée à `tenant_id + recipient_id + event_id` — un Parent A et un Parent B homonymes ne peuvent structurellement jamais recevoir la notification de l'autre, la résolution d'audience (`EVENEMENTS.md` §17.2) résout un `recipient_id` réel, jamais un nom.

Statut : `📋 PLANIFIÉ`.

---

## 13. Isolation IA

### 13.1 Contexte IA — jamais un accès direct

```
User → Tenant Context → Permission Layer → Context Builder → Données autorisées (scopées tenant) → IA
```

Jamais `User → IA → Database`. Repris et renforcé de `SYSTEME_IA.md` §6 : le Permission Layer résout le `tenant_id` **avant** que le Context Builder n'assemble quoi que ce soit pour le modèle — l'IA ne "sait" jamais qu'un autre tenant existe, elle ne reçoit simplement jamais ses données.

### 13.2 Mémoire IA

Toute mémoire de conversation ou de contexte (`SYSTEME_IA.md` §5) est scopée `tenant_id + user_id` — il n'existe **jamais** de mémoire globale contenant des informations d'une école que l'IA pourrait réutiliser pour une autre, même par accident d'agrégation.

### 13.3 RAG / base vectorielle (si retenue plus tard)

Si une base vectorielle est introduite (embeddings de documents pour recherche sémantique) : chaque vecteur porte un `tenant_id` en métadonnée, et **toute requête de similarité applique un filtre tenant strict avant** le calcul de similarité, jamais après (un filtrage a posteriori sur les résultats les plus proches risquerait de rater le vrai résultat du bon tenant si un résultat d'un autre tenant est numériquement plus proche). Suppression et ré-indexation d'un tenant doivent pouvoir cibler exactement son namespace/collection sans toucher aux autres. Prévention de fuite : un test dédié (section 17) vérifie qu'une requête sémantique du tenant A ne peut jamais faire remonter un document du tenant B, même par similarité élevée.

Statut : `📋 PLANIFIÉ` · base vectorielle elle-même `🔌 FOURNISSEUR EXTERNE` si retenue.

---

## 14. Isolation des fichiers

```
tenant/{tenant_id}/imports/...
tenant/{tenant_id}/receipts/...
tenant/{tenant_id}/documents/...
```

**Connaître le chemin ne suffit jamais à y accéder** (cohérent avec `SECURITE.md` §17.2) : chaque lecture de fichier passe par une vérification de permission + tenant côté backend, et l'accès direct (URL signée) n'est émis qu'après cette vérification, avec une expiration courte — jamais un chemin prévisible et durablement valide.

Statut : `📋 PLANIFIÉ`.

---

## 15. Isolation de la recherche et du cache

### 15.1 Recherche

Toute recherche (`SYSTEME_IA.md` §10.3) applique le filtre tenant **avant** le filtre de permission fine, jamais après un classement global par pertinence — un résultat d'un autre tenant ne doit même pas apparaître un instant avant d'être filtré. Si un moteur de recherche dédié est introduit plus tard (Elasticsearch/OpenSearch), chaque document indexé porte `tenant_id`, et chaque requête l'inclut systématiquement dans le filtre, jamais en option.

### 15.2 Cache

```
tenant:A:student:123   ≠   tenant:B:student:123
```

Une clé de cache sans préfixe tenant (`student:123`) est un bug de sécurité potentiel dès qu'un identifiant local peut coïncider entre deux tenants (section 4). Règle appliquée à Redis, cache applicatif, CDN (pour les assets/documents servis par URL), et sessions.

Statut : `📋 PLANIFIÉ`.

---

## 16. Rôles plateforme vs école

Renvoi et extension de `SECURITE.md` §20 :

| Rôle | Portée | Particularité |
|---|---|---|
| School User (tout rôle d'établissement) | Un ou plusieurs tenants via memberships explicites | Jamais d'accès implicite hors de ses memberships |
| Platform Administrator | Plateforme entière | Structurellement un type de compte distinct — **ne peut jamais être confondu avec un directeur d'école**, même par erreur de configuration (types de compte incompatibles au niveau du modèle de données, pas seulement du rôle) |
| Support | Accès temporaire, ciblé | Section 16.1 |

### 16.1 Accès support — break-glass contrôlé

```
Support demande accès → tenant sélectionné explicitement → justification enregistrée
   → approbation (selon sensibilité) → accès limité dans le temps → toute action auditée
   → expiration automatique, pas de révocation manuelle oubliée
```

Le support ne dispose jamais d'un accès permanent et invisible à toutes les écoles — chaque accès est un événement à part entière (`security.support_access_granted`), visible dans l'audit du tenant concerné, pas seulement côté plateforme (le directeur doit pouvoir voir que son école a été consultée par le support).

Statut : `📋 PLANIFIÉ`.

---

## 17. Tests d'isolation cross-tenant

Matrice systématique, sur **chaque** type de ressource (élèves, parents, classes, paiements, obligations, dépenses, trésorerie, documents, événements, notifications, IA, recherche, exports, imports, jobs, cache, webhooks) :

```
A → A = ALLOW      B → A = DENY       C → A = DENY
A → B = DENY       B → B = ALLOW      C → B = DENY
A → C = DENY       B → C = DENY       C → C = ALLOW
```

**Tests IDOR/BOLA explicites** : `GET /students/STU_123` (tenant A) avec un ID substitué appartenant au tenant B → refus, quel que soit le rôle de l'utilisateur A. **Tests d'énumération** : les réponses d'erreur ne distinguent jamais *"cette ressource n'existe pas"* de *"cette ressource existe mais appartient à un autre tenant"* — toujours la même réponse (`404` ou `403` selon la politique choisie, mais uniforme), pour ne jamais révéler l'existence d'un autre tenant ou de ses ressources.

### 17.1 Chaos testing

Contexte tenant manquant, corrompu, ou erroné ; session périmée ; membership expiré ; tenant supprimé ; mauvais routage de base de données (si architecture hybride, section 6) ; retry de queue dupliquant un événement ; — dans **tous** les cas, le système doit échouer fermé (section 27) : refuser plutôt que de deviner un tenant par défaut.

Statut : `📋 PLANIFIÉ`.

---

## 18. Suppression, backup, export, migration

### 18.1 Suppression d'un tenant

```
Soft delete → période de rétention définie → export final proposé → purge définitive (ou legal hold si applicable)
```

Une école supprimée ne doit laisser **aucune** référence incohérente ailleurs — ses données financières historiques suivent les mêmes règles de rétention/immutabilité que `FINANCE.md` (jamais un `DELETE` brutal sur des transactions).

### 18.2 Backup et restauration ciblée

Une sauvegarde base entière ne se restaure jamais "en bloc" pour un seul tenant sans écraser les autres. Stratégies réalistes : Point-in-Time Recovery de la base entière **vers un environnement séparé**, puis extraction ciblée par `tenant_id` depuis cet environnement restauré ; en parallèle, un export logique périodique par tenant (déjà nécessaire pour la portabilité, section 18.3) sert de sauvegarde ciblée indépendante, plus rapide à restaurer isolément qu'un PITR complet.

### 18.3 Export des données d'une école

Filtré strictement par `tenant_id` : élèves, parents, finances, paiements, obligations, documents, événements, audit selon les règles applicables — jamais une autre école, même partiellement.

### 18.4 Migration vers une base dédiée

Rendue possible par le `Tenant Registry` (section 21) : export complet du tenant (section 18.3) → provisioning d'une base dédiée → import avec **conservation stricte des identifiants** (les `tenant_id`/`entity_id` ne changent jamais, seul le `deployment_mode` et la route de connexion changent) → bascule du registre → vérification post-migration (cohérent avec `IMPORT.md` §21.1) → ancienne copie conservée un temps avant purge.

Statut : `📋 PLANIFIÉ`.

---

## 19. Tenant Registry et configuration

```
TenantRegistry { tenant_id, tenant_name, status, deployment_mode, database_cluster,
                 database_identifier, region, plan, created_at }
```

`deployment_mode: shared | dedicated` — au MVP, toujours `shared`, mais le champ existe dès le premier jour (section 6).

### 19.1 Configuration par tenant

```
TenantSettings { currency, timezone, academic_calendar, grading_system, fee_structure,
                 payment_providers, notification_preferences, branding }
```

**La configuration n'est jamais du code.** Une école n'obtient jamais d'exécution de code personnalisée — ses spécificités passent exclusivement par configuration, feature flags (section 19.2), règles (`EVENEMENTS.md` §7, scopées tenant) et permissions. Un `NotificationTemplate` peut avoir un override par tenant (branding), avec une hiérarchie `template global → override tenant`, jamais un template arbitraire injecté sans passer par ce mécanisme contrôlé.

### 19.2 Feature flags tenant-aware

```
FeatureFlag { tenant_id, feature_key, enabled }
```

Ex. `mobile_money: enabled` pour A, `disabled` pour B ; `ai_advanced: enabled` pour A seulement. Résolu au moment de la construction du Tenant Context (section 7), jamais recalculé de façon incohérente entre deux composants du système.

### 19.3 IA : connaissance globale vs contexte par tenant vs préférence utilisateur

| Niveau | Exemple | Portée |
|---|---|---|
| Connaissance globale de l'IA | Comprendre le français, le concept de "frais scolaires" | Ne contient jamais de donnée d'un tenant précis |
| Contexte tenant-spécifique | Les chiffres financiers, élèves, classes de l'école A | Jamais partagé avec un autre tenant (section 13) |
| Préférence utilisateur | Heure préférée du briefing (08h vs 17h) | Scopée utilisateur, indépendante des données d'un autre tenant |

Statut : `📋 PLANIFIÉ`.

---

## 20. Rate limiting et noisy neighbor

Quotas définis à plusieurs niveaux simultanément : IP, utilisateur, **tenant**, clé API, fournisseur externe. Une école qui déclenche accidentellement 100 000 notifications ne doit jamais pouvoir saturer la plateforme pour les autres — quotas par tenant sur les files de notification, limites de burst par tenant sur les API, pools de connexions base de données dimensionnés pour survivre à un pic isolé (cohérent avec `EVENEMENTS.md` §21.1, partitionnement du bus par tenant). Le "noisy neighbor" est traité comme un problème de capacité **et** de sécurité — un tenant anormalement bruyant est aussi un signal à surveiller (section 24).

Statut : `📋 PLANIFIÉ`.

---

## 21. Threat model spécifique au multi-tenant

| Menace | Vecteur | Impact | Prévention | Détection |
|---|---|---|---|---|
| IDOR / BOLA | ID de ressource substitué dans une requête | Fuite de données d'un autre établissement | Vérification systématique tenant+ressource (section 9, couche 3-4) | Test automatisé (section 17), alerte sur refus répétés |
| Manipulation du `tenant_id` | Valeur modifiée en URL/JSON/cookie/local storage | Accès non autorisé | Tenant résolu uniquement côté serveur (section 7) | Journalisation des tentatives, incohérence détectable |
| Injection SQL | Entrée non validée | Contournement du filtre applicatif | Requêtes paramétrées + RLS en dernier filet (section 8) | Monitoring des requêtes anormales |
| Autorisation cassée | Permission mal vérifiée pour une action | Action non autorisée exécutée | RBAC strict (`SECURITE.md` §6-8) | Audit systématique |
| Empoisonnement de cache | Clé de cache non préfixée par tenant | Donnée d'un tenant servie à un autre | Préfixage systématique (section 15.2) | Tests de non-régression dédiés |
| Événement cross-tenant | Consommateur qui perd le `tenant_id` en route | Notification/action pour le mauvais tenant | Propagation obligatoire du contexte (section 25) | Validation de cohérence à chaque étape de la chaîne d'événements |
| Fuite via IA/RAG | Contexte mal filtré, recherche vectorielle inter-tenant | Fuite de données confidentielles | Filtrage avant similarité (section 13.3) | Tests de fuite dédiés |
| Confusion de fichier | Chemin de stockage deviné | Accès à un document d'un autre tenant | Vérification permission avant toute URL signée (section 14) | Logs d'accès aux fichiers |
| Confusion webhook | Paiement d'un tenant crédité à un autre | Erreur financière grave | Résolution par compte marchand, jamais par champ client (section 11.3) | Réconciliation, alerte sur webhook non résolu |
| Routage de connexion erroné (architecture hybride) | Bascule de registre incorrecte | Requête exécutée sur la mauvaise base | Tests de routage systématiques, vérification au démarrage de connexion | Alerte sur toute requête sans tenant résolu explicitement |
| Abus d'accès support | Accès break-glass non expiré ou détourné | Accès non autorisé prolongé | Expiration automatique, audit visible côté tenant (section 16.1) | Revue périodique des accès support actifs |
| Compromission d'un admin plateforme | Compte Super Admin volé | Accès potentiel à tous les tenants | MFA obligatoire, séparation stricte des types de compte (section 16) | Audit de toute consultation cross-tenant |
| Menace interne | Employé Klassio consultant des données sans justification | Violation de confidentialité | Accès justifié et temporaire uniquement (section 16.1) | Aucune consultation silencieuse possible par construction |

---

## 22. Invariants de sécurité

```
1. Toute entité métier appartient à exactement un tenant.
2. Un utilisateur n'accède qu'aux tenants pour lesquels il a un membership valide et vérifié côté serveur.
3. Un paiement ne peut jamais appartenir à un élève d'un autre tenant (contrainte DB, section 10.4).
4. Un événement n'est jamais consommé en dehors de son tenant d'origine.
5. Le contexte IA ne contient jamais de donnée d'un tenant non autorisé.
6. Un webhook n'est traité qu'après résolution certaine de son tenant (jamais supposé).
7. Une clé de cache identifie toujours son tenant.
8. Un worker ou un job planifié conserve son tenant_id du début à la fin de son exécution.
9. Une suppression de tenant ne laisse aucune référence orpheline ailleurs.
10. Le frontend ne détermine jamais le tenant autorisé — seule la résolution serveur fait foi.
```

---

## 23. Conventions de développement et query builder tenant-safe

Toute table tenant-scoped porte `tenant_id, created_at, updated_at` (et `created_by`/`updated_by` si pertinent) — décidé explicitement table par table (section 10.3), jamais par défaut implicite. **Aucun accès direct** à une table tenant-scoped n'est autorisé dans le code métier — uniquement via une abstraction de repository qui **exige** un `TenantContext` en paramètre et l'applique automatiquement à chaque requête :

```
StudentRepository.find(tenantContext, id)   // TenantContext obligatoire, pas optionnel
```

Un développeur ne peut structurellement pas écrire une requête tenant-scoped sans fournir de contexte — l'erreur de compilation/exécution est préférable à l'oubli silencieux. Cohérent avec le principe `DENY BY DEFAULT` déjà posé dans `SECURITE.md` §50 : un développeur qui oublie une permission ou un tenant provoque un refus, jamais un accès large par défaut.

Statut : `📋 PLANIFIÉ`.

---

## 24. Propagation du contexte tenant

```
Requête HTTP → Application → Service → Base de données
     → Événement (tenant_id dans l'enveloppe, EVENEMENTS.md §6.1)
     → Queue → Worker (reçoit le tenant_id depuis l'événement, jamais redéduit)
     → Notification → IA (Context Builder, section 13.1)
```

Le `tenant_id` ne se "redevine" jamais à une étape intermédiaire — il est porté explicitement de bout en bout. `correlation_id`/`causation_id` (`EVENEMENTS.md` §6.1) permettent, lors d'un audit, de retracer une opération complète et de vérifier a posteriori qu'aucun maillon de la chaîne n'a changé de tenant en cours de route — un changement de `tenant_id` au milieu d'une chaîne de corrélation est en soi une anomalie détectable et alertable (section 21).

Statut : `📋 PLANIFIÉ`.

---

## 25. Observabilité et incident response spécifiques au multi-tenant

Chaque log, métrique et trace porte `tenant_id` — permettant de répondre indépendamment à *"erreurs de l'école A"*, *"erreurs de l'école B"*, *"erreurs plateforme globales"*, sans jamais exposer les détails d'une école à une autre dans une vue de monitoring partagée (les tableaux de bord d'observabilité eux-mêmes respectent une isolation d'affichage, y compris pour l'équipe technique, sauf rôle explicitement habilité).

**Isolation pendant un incident de sécurité** ciblant un tenant précis : suspendre l'accès de ce tenant (sans affecter les autres, cohérent avec le partitionnement par tenant, section 20) → révoquer ses sessions et secrets propres (ex. ses clés de fournisseur de paiement) → préserver ses logs pour investigation → continuer à servir tous les autres tenants sans interruption → analyser → restaurer l'accès une fois résolu (repris et détaillé depuis `SECURITE.md` §21, avec la dimension "isoler un seul tenant sans affecter les autres" qui est spécifique à ce document).

Statut : `📋 PLANIFIÉ`.

---

## 26. Checklist d'audit avant production

```
□ RLS activée sur 100% des tables tenant-scoped, testée par des tentatives d'accès cross-tenant
□ Toute FK sensible utilise (tenant_id, entity_id) — section 10.4
□ Aucune route API n'accepte de tenant_id client sans revérification serveur
□ Tests IDOR/BOLA automatisés couvrant toutes les ressources (section 17)
□ Webhooks résolus par compte marchand, jamais par champ client (section 11.3)
□ Toutes les clés de cache préfixées par tenant (section 15.2)
□ IA : contexte vérifié comme filtré par tenant avant tout appel modèle (section 13.1)
□ RAG/vecteurs (si utilisés) : test de fuite cross-tenant explicite (section 13.3)
□ Fichiers : aucune URL de stockage prévisible/durable sans vérification (section 14)
□ Exports/imports : filtrage tenant vérifié à l'entrée et à la sortie (IMPORT.md, section 18.3)
□ Backups : procédure de restauration ciblée par tenant testée au moins une fois (section 18.2)
□ Support : accès break-glass avec expiration automatique vérifiée (section 16.1)
□ Comptes Platform Administrator structurellement distincts des comptes école (section 16)
□ Rate limiting par tenant actif (section 20)
□ Logs/métriques/traces portent tenant_id systématiquement (section 25)
```

---

## 27. Réponses directes (section 73 de votre brief)

1. **Architecture DB** : partagée, schéma partagé, isolation stricte par `tenant_id` + RLS (section 6).
2. **Pourquoi** : meilleur compromis coût/scalabilité pour 1 → 10 000 écoles, sans sacrifier la sécurité si la défense en profondeur (section 9) est appliquée dès le début.
3. **Garantir l'isolation** : 8 couches indépendantes (section 9), RLS comme dernier filet systématique.
4. **Éléments avec `tenant_id` obligatoire** : voir la liste de gauche, section 10.3.
5. **Tables globales** : `User` (identité), `EventType`/registre de schéma, `TenantRegistry`, catalogue de fournisseurs de paiement — voir section 10.3 (droite).
6. **Utilisateurs multi-écoles** : memberships explicites par tenant, changement de contexte audité (section 7.1).
7. **Groupe scolaire** : `Organization` optionnelle regroupant plusieurs tenants, jamais un raccourci d'accès (section 3).
8. **Paiements** : Financial Core tenant-scoped intégralement, mapping compte marchand → tenant protégé comme un secret (section 11).
9. **Webhooks** : résolution par compte marchand + référence interne, jamais par un `tenant_id` fourni par le fournisseur externe (section 11.3).
10. **Événements** : `tenant_id` dans l'enveloppe, propagation obligatoire à chaque maillon (sections 12, 24).
11. **IA** : Context Builder scopé tenant avant tout appel modèle, mémoire tenant+utilisateur scopée (section 13).
12. **Fichiers** : chemin structuré par tenant + vérification systématique avant accès (section 14).
13. **Cache** : clés systématiquement préfixées par tenant (section 15.2).
14. **Workers** : `tenant_id` porté dans le payload du job, jamais redéduit (section 24).
15. **Backups** : restauration ciblée via environnement séparé + export logique périodique par tenant (section 18.2).
16. **Support** : accès temporaire, justifié, audité, à expiration automatique (section 16.1).
17. **Tester l'isolation** : matrice systématique A/B/C sur toutes les ressources + chaos testing (section 17).
18. **Évoluer vers des DB dédiées** : `Tenant Registry` avec `deployment_mode`, préparé dès le MVP sans complexité additionnelle réelle (section 6, 18.4).

---

## 28. Roadmap

### MVP
Schéma partagé + `tenant_id` partout + RLS activée dès la première table, Tenant Context résolu côté serveur, FK composites sur les relations financières critiques, tests d'isolation de base (IDOR sur élèves/paiements), audit des accès refusés.

### V1
Tenant Registry complet (même si `deployment_mode` reste `shared` pour tous), feature flags par tenant, rate limiting par tenant, cache préfixé systématiquement, tests d'isolation étendus à toutes les ressources (section 17), accès support break-glass.

### V2
Isolation IA/RAG complète si une base vectorielle est introduite, `Organization`/groupe scolaire avec agrégation de rapports, export/migration outillés, checklist d'audit (section 26) formalisée en processus récurrent.

### Plus tard
Premiers tenants en `deployment_mode: dedicated` pour des cas réels (gros volume ou exigence de résidence), partitionnement géographique/régional, sharding si un jour un seul cluster partagé ne suffit plus en performance brute.

---

## Annexe A — Ce que ce tour de travail a ajouté au code

[assets/js/tenant-model.js](../assets/js/tenant-model.js) — catalogue codifié (hiérarchie tenant, statuts de deployment, formes d'entités clés), pure référence sans logique exécutable, non chargé par aucune page, même esprit que les quatre catalogues précédents.

## Annexe B — Légende de statut

Identique aux cinq documents précédents.
