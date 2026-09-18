# KLASSIO — Système d'Événements, de Règles et de Notifications
### Spécification V0.1 — Event Engine + Rule Engine + Notification Engine

Ce document est désormais la référence complète et autoritaire pour l'architecture événementielle de Klassio. Il **étend** [SYSTEME_IA.md](SYSTEME_IA.md) §8 (Event System) et §9 (Notification Engine), qui restent valides comme résumé côté IA mais renvoient ici pour le détail complet. Il s'appuie sur [FINANCE.md](FINANCE.md) (le Financial Core reste la seule source de vérité financière — l'Event Store n'en est jamais un substitut, section 5.4), [SECURITE.md](SECURITE.md) (permissions, multi-tenant, audit) et [IMPORT.md](IMPORT.md) (les événements `import.*` déjà nommés là-bas sont repris dans la taxonomie ci-dessous).

## 0. État réel du projet

Aucun changement depuis les documents précédents : pas de backend, pas de bus d'événements, pas de queue. Tout ce document est `📋 PLANIFIÉ`, sauf le catalogue de référence codifié en Annexe A. Légende identique aux quatre documents précédents : `✅ IMPLÉMENTÉ` · `🟡 PARTIEL` · `📋 PLANIFIÉ` · `⛔ NON IMPLÉMENTÉ` · `🔌 FOURNISSEUR EXTERNE`.

---

## 1. Vision

Ce n'est pas un système qui envoie des notifications. C'est le **système nerveux** de la plateforme : chaque fait métier important devient un événement structuré, que des règles déterministes interprètent pour déclencher des conséquences — notification, mise à jour de dashboard, workflow, contexte pour l'IA — sans que les modules métier aient besoin de se connaître entre eux.

## 2. Objectifs

Découpler les modules métier (ils émettent des faits, sans savoir qui les consomme) ; rendre la plateforme réactive sans la rendre fragile ; donner à l'IA un contexte structuré plutôt qu'un accès brut aux données ; garantir qu'aucune panne d'un service secondaire (SMS, WhatsApp, IA) ne remette jamais en cause une opération financière déjà validée.

## 3. Principes non négociables

1. Un événement décrit un fait **réellement produit** — jamais une intention.
2. Un événement n'est créé qu'après validation complète du fait métier (le paiement est confirmé *avant* que `payment.confirmed` existe, jamais l'inverse).
3. Le Financial Core reste l'unique source de vérité financière (`FINANCE.md` §1) — l'Event Store n'en est qu'un journal de faits, pas un second registre.
4. Une notification ne modifie jamais directement une donnée financière.
5. L'IA n'a jamais d'accès libre à la base de données (`SYSTEME_IA.md` §2, §6).
6. L'IA n'est jamais l'autorité financière ou sécuritaire, même face à un événement critique.
7. Les permissions sont toujours imposées par le backend, appliquées à la résolution d'audience comme à toute API (`SECURITE.md`).
8. Chaque événement est isolé par tenant, et par année scolaire lorsque pertinent.
9. Les événements critiques sont traçables de bout en bout (section 24).
10. Tout traitement déclenché par un événement est idempotent.
11. Un retry ne crée jamais de doublon financier.
12. Les notifications sont découplées des transactions critiques — jamais sur le chemin synchrone d'une opération financière.
13. Une panne du fournisseur SMS/WhatsApp/email ne doit **jamais** annuler ou retarder un paiement déjà confirmé.
14. Les événements sont versionnés (section 14).
15. Les événements sont observables (section 20).
16. Un événement important peut être rejoué de façon contrôlée, sans rejouer ce qui a déjà réussi (section 11.4).
17. Les boucles événementielles sont activement empêchées (section 10.2).
18. Les données sensibles respectent des règles de confidentialité selon le canal (section 7.9).
19. Les règles métier critiques restent déterministes — jamais remplacées par un modèle de langage (section 6.2).
20. Le système reste indépendant d'un fournisseur unique (bus, notification, IA).
21. Un même événement peut alimenter plusieurs consommateurs indépendants.
22. L'utilisateur (ou l'administrateur) peut toujours comprendre pourquoi une notification a été produite (section 24).
23. Une notification critique est traçable jusqu'à sa cause exacte.
24. Le système peut dire *"en attente"* plutôt que prétendre à tort qu'un traitement a réussi.
25. L'architecture est pensée pour 1 établissement comme pour 10 000.

---

## 4. Terminologie

| Terme | Définition | Exemple |
|---|---|---|
| **Action** | Quelqu'un ou quelque chose fait quelque chose | Un parent effectue un paiement |
| **Événement** | Le système constate qu'un fait métier s'est produit, déjà validé | `payment.confirmed` |
| **Règle** | Le système décide, de façon déterministe, ce qui doit en découler | `SI payment.confirmed ET montant ≥ 500 ALORS notifier le directeur` |
| **Notification** | Le système communique un fait à un utilisateur précis | *"Le paiement de 250 $ pour Jean Dupont a été confirmé"* |
| **Insight IA** | L'IA interprète un ou plusieurs événements pour produire une explication ou une recommandation | *"18 paiements confirmés aujourd'hui, pour 4 820 $, soit 12 % de plus qu'hier"* |

L'ordre est toujours le même et ne s'inverse jamais : **Action → Événement → Règle → (Notification | Workflow | Contexte IA)**. L'IA ne se place jamais avant la Règle dans cette chaîne pour une décision déterministe — elle reçoit le résultat, pas l'inverse.

---

## 5. Architecture globale

Le schéma proposé dans le brief est globalement juste ; deux corrections : (a) l'IA ne doit pas recevoir les événements bruts en parallèle du Rule Engine — elle reçoit un contexte déjà filtré et priorisé par un **AI Context Engine** situé après le Rule Engine (section 16), jamais directement câblée sur le bus ; (b) l'Audit doit consommer le bus indépendamment de la Notification Engine, pas en aval d'elle — un événement doit être audité même si aucune notification n'en découle.

```
                 MODULES MÉTIER (Financial Core, Import Engine, Security Engine…)
                                       │  (après succès de l'opération, jamais avant)
                                       ▼
                              EVENT PRODUCER
                          (transactional outbox — section 13)
                                       │
                                       ▼
                               EVENT STORE
                        (journal append-only, source de vérité DES FAITS,
                         jamais de la finance — section 5.4)
                                       │
                                       ▼
                             EVENT BUS / QUEUE
                                       │
        ┌───────────────┬─────────────┼─────────────┬───────────────┐
        ▼               ▼             ▼              ▼               ▼
   RULE ENGINE   WORKFLOW ENGINE  AI CONTEXT      AUDIT ENGINE   ANALYTICS
        │               │          ENGINE              │               │
        ▼               ▼             ▼                ▼               ▼
  NOTIFICATION    BUSINESS ACTIONS  AI LAYER      JOURNAL D'AUDIT   RAPPORTS
    ENGINE          (via Business    (insights,     (immuable,
        │            Logic, jamais   recommandations) SECURITE.md §11)
        ▼            directement en
  CHANNEL LAYER      base)
  ┌──┼──┬───┐
  ▼  ▼  ▼   ▼
In-App Push SMS/WhatsApp/Email
```

Le **Dashboard temps réel** (section 18) et le **Scheduler** (section 15.2) sont deux producteurs/consommateurs supplémentaires du même bus, pas des cas à part.

---

## 6. Event Engine

### 6.1 Modèle d'événement

Le modèle proposé dans le brief est solide ; on ajoute `severity`, `processing_status` et `retry_count` qui manquaient à l'exemple donné, et on distingue clairement `occurred_at` (quand le fait s'est produit) de `recorded_at` (quand il a été persisté) — utile en cas de rejeu ou de latence d'ingestion :

```
{
  "event_id": "evt_...",
  "event_type": "payment.confirmed",
  "version": 1,
  "occurred_at": "2026-09-08T10:15:00Z",
  "recorded_at": "2026-09-08T10:15:00.412Z",
  "tenant_id": "school_...",
  "academic_year_id": "ay_2025_2026",
  "actor": { "type": "system|user|scheduler", "id": "..." },
  "entity": { "type": "payment", "id": "pay_..." },
  "correlation_id": "corr_...",   // relie tous les événements d'une même opération métier
  "causation_id": "evt_precedent", // l'événement qui a directement causé celui-ci
  "source": "financial-core",
  "severity": "normal|high|critical",
  "processing_status": "pending|processing|processed|failed|dead_letter",
  "retry_count": 0,
  "metadata": { "ip": "...", "request_id": "..." },
  "payload": { "student_id": "...", "amount": 250, "currency": "USD", "payment_method": "mobile_money" }
}
```

`correlation_id` regroupe tous les événements d'une même opération métier (ex. `payment.confirmed` → `obligation.updated` → `receipt.generated` partagent le même) ; `causation_id` pointe précisément vers l'événement qui a déclenché celui-ci — ensemble, ils rendent la chaîne de la section 8 entièrement traçable.

### 6.2 Taxonomie d'événements

Extensible et versionnée par domaine (extrait représentatif, pas exhaustif — la liste complète que vous avez fournie est adoptée telle quelle comme point de départ) :

| Domaine | Exemples |
|---|---|
| Étudiants | `student.created` · `student.enrolled` · `student.class_changed` · `student.archived` |
| Responsables | `guardian.added` · `guardian.updated` · `guardian.contact_verified` |
| Classes | `class.created` · `student.assigned_to_class` |
| Import | `import.started` · `import.mapping_completed` · `import.completed` · `import.requires_review` (repris de `IMPORT.md` §15.1) |
| Obligations | `obligation.created` · `obligation.overdue` · `obligation.fully_paid` |
| Échéances | `installment.due_soon` · `installment.overdue` · `installment.extended` |
| Paiements | `payment.created` · `payment.confirmed` · `payment.failed` · `payment.unknown` · `payment.reconciled` · `payment.refunded` |
| Remboursements | `refund.requested` · `refund.approved` · `refund.completed` |
| Trésorerie | `treasury.transfer_completed` · `treasury.balance_threshold_reached` |
| Caisse | `cash_session.closed` · `cash_variance.detected` |
| Mobile Money | `mobile_money.payment_confirmed` · `mobile_money.settlement_received` |
| Dépenses | `expense.submitted` · `expense.approved` · `expense.paid` |
| Fournisseurs | `supplier.invoice_due` · `supplier.paid` |
| Salaires | `payroll.approved` · `payroll.paid` |
| Stock | `inventory.stock_low` · `inventory.stock_out` |
| Documents | `document.generated` · `document.expired` |
| Sécurité | `security.login_failed` · `security.settlement_destination_changed` · `security.suspicious_activity` |
| IA | `ai.insight_generated` · `ai.anomaly_detected` · `ai.action_requested` |

Chaque type d'événement est décrit dans un **registre de schéma** (section 14.2) : payload attendu, version, producteur, consommateurs, classification de sécurité, pertinence IA, rétention.

### 6.3 Cycle de vie

```
CRÉÉ (par le producteur, après succès métier)
  → PERSISTÉ (Event Store, section 5.4)
  → PUBLIÉ (Event Bus)
  → EN TRAITEMENT (par chaque consommateur, indépendamment)
  → TRAITÉ | ÉCHOUÉ → RETRY → DEAD LETTER (section 11.3)
```

Chaque consommateur a son **propre** statut de traitement pour un même événement — un échec de la Notification Engine ne doit jamais affecter le statut "traité" côté Audit ou Analytics.

### 6.4 Event Store — jamais un second Financial Ledger

L'Event Store est un journal append-only des **faits survenus**, utile pour l'audit, le rejeu et l'analytics (`Event Analytics`, section 21). Le **Financial Ledger** (`FINANCE.md` §5) reste l'unique source de vérité pour "combien d'argent, où, à qui". Si les deux divergent, c'est toujours le Ledger qui a raison — l'Event Store peut être reconstruit à partir de lui, jamais l'inverse.

Statut : `📋 PLANIFIÉ`.

---

## 7. Rule Engine

### 7.1 Modèle de règle

```
Rule {
  id, tenant_id?, name, event_type, conditions[], actions[],
  priority, enabled, version, created_by, audit_trail
}
```

Exemples directement transposables :
```
WHEN payment.confirmed IF guardian exists THEN notify(guardian, template="payment.confirmed.parent")
WHEN payment.confirmed IF amount >= 500 THEN notify(director, template="payment.confirmed.director.large")
WHEN installment.overdue IF days_overdue >= 7 THEN notify(guardian, template="installment.reminder")
WHEN expense.created IF amount > approval_threshold THEN require_approval()
```

Les règles sont conditionnelles, composables, priorisées, activables/désactivables sans déploiement de code, versionnées, auditées à chaque modification, scopées par tenant (une école peut personnaliser ses seuils) et par rôle, et testables unitairement (section 22) — un moteur de règles sans mode test n'est pas fiable.

### 7.2 Rule Engine ≠ IA (distinction structurante)

| Nature | Exemple | Où |
|---|---|---|
| Déterministe (Business Logic) | *Paiement confirmé → mettre à jour le solde* | Financial Core |
| Rule Engine | *Paiement > 500 $ → notifier le directeur* | Rule Engine |
| IA | *"Les paiements de cette semaine sont anormalement faibles"* | AI Layer |

`Rules = automatisation déterministe. IA = interprétation, raisonnement, recommandation.` L'IA ne remplace jamais une règle financière ou sécuritaire — même une règle aussi simple que *"notifier si > 500 $"* reste dans le Rule Engine, jamais confiée à un prompt.

### 7.3 Exécution

À la réception d'un événement, le Rule Engine évalue toutes les règles actives correspondant à `event_type` (et au `tenant_id`), dans l'ordre de priorité, et déclenche les actions associées (notification, workflow, mise à jour de contexte IA) — chaque déclenchement est lui-même journalisé pour l'auditabilité (section 24).

Statut : `📋 PLANIFIÉ`.

---

## 8. Cas complet démontré : `payment.confirmed`

### 8.1 Chaîne de confirmation

```
Confirmation Orange Money → Webhook → Vérification serveur (SECURITE.md §9.4)
   → Financial Core (statut CONFIRMED, FINANCE.md §7.3) → Événement payment.confirmed
```

### 8.2 Ce que déclenche l'événement

```
payment.confirmed
   ├── Financial Core        → solde déjà mis à jour (c'est CE qui a produit l'événement, pas une conséquence)
   ├── Obligation Engine     → obligation.updated / installment_fully_paid éventuel
   ├── Receipt Service       → génération du reçu
   ├── Notification (parent) → "Paiement confirmé"
   ├── Notification (direction) → si règle applicable (ex. montant ≥ seuil)
   ├── Dossier élève         → historique financier mis à jour (vue agrégée, FINANCE.md §16.2)
   ├── Dashboard             → mise à jour temps réel (section 18)
   ├── Trésorerie            → mouvement de compte (déjà réel côté Financial Core)
   └── AI Context Engine     → événement disponible pour agrégation/insight (section 16)
```

### 8.3 Ce qui est synchrone / asynchrone / critique

| Étape | Synchrone ? | Doit réussir ? | Peut être rejoué ? | Idempotent ? |
|---|---|---|---|---|
| Vérification webhook + Financial Core → CONFIRMED | **Synchrone, bloquant** | Oui, absolument | N/A (déjà la source de vérité) | Oui (idempotency key, `FINANCE.md` §9.3) |
| Création de l'événement `payment.confirmed` (outbox) | Synchrone avec l'étape précédente (section 13) | Oui | — | Oui (event_id unique) |
| Mise à jour de l'obligation (`FINANCE.md`) | Asynchrone, quasi-immédiate | Oui, mais peut être retardée sans risque | Oui | Oui |
| Génération du reçu | Asynchrone | Non-bloquant pour la confirmation | Oui | Oui |
| Notifications (parent/directeur) | **Toujours asynchrone** | Non — un retry suffit | Oui | Oui (dedup sur `event_id + recipient + channel`) |
| Mise à jour dashboard temps réel | Asynchrone (push) | Non-bloquant | Oui | Oui |
| Contexte IA / insight | Asynchrone, souvent différé/agrégé | Non-bloquant | Oui | Oui |

**Ce qui ne doit jamais bloquer la confirmation financière** : tout ce qui est en dessous du Financial Core dans ce tableau. Une panne totale de la Notification Engine ou du fournisseur IA n'empêche jamais `payment.confirmed` d'exister et d'être vrai.

Statut : `📋 PLANIFIÉ`.

---

## 9. Cas complet démontré : changement de destination de règlement

```
Modification du compte Mobile Money de règlement
   → security.settlement_destination_changed  (severity: CRITICAL)
   → Rule Engine (règle non désactivable pour cet événement)
        ├── Notification direction — immédiate, multicanal (section 7.5, jamais throttlée)
        ├── Security monitoring (SECURITE.md §15)
        ├── Audit — écriture immuable
        └── AI Context Engine → analyse contextuelle disponible
```

**L'IA peut expliquer, jamais décider.** Si une action de type *"bloquer le compte"* est nécessaire, elle appartient exclusivement au Security Engine (`SECURITE.md` §9.5, workflow d'approbation à deux personnes) — l'IA peut au mieux **proposer** de vérifier, jamais exécuter ni recommander une décision présentée comme automatique.

Statut : `📋 PLANIFIÉ`.

---

## 10. Enchaînement d'événements et prévention des boucles

### 10.1 Event chaining

```
PaymentConfirmed → ObligationUpdated → InstallmentFullyPaid → ReceiptGenerated → NotificationSent → DashboardUpdated
```

Chaque maillon est un événement à part entière, avec son propre `causation_id` pointant vers le précédent — la chaîne entière est reconstructible a posteriori (section 24).

### 10.2 Prévention des boucles

Règle structurante : **un événement de notification (`notification.sent`, `notification.processed`) n'est jamais lui-même une cause valable pour re-déclencher un événement métier** — le Rule Engine n'autorise pas les règles dont l'action reproduit le type d'événement déclencheur ou l'un de ses ancêtres dans la chaîne de `causation_id` (détection de cycle explicite, pas seulement une convention). Une limite de profondeur de chaîne (ex. 10 maillons) déclenche une alerte plutôt qu'une boucle silencieuse.

Statut : `📋 PLANIFIÉ`.

---

## 11. Idempotence, retries, dead-letter, replay

### 11.1 Idempotence

Chaque consommateur retient les `event_id` déjà traités (table `EventProcessing`, section 22) — un événement reçu deux fois (livraison "at-least-once", normale dans un bus distribué) ne produit jamais deux notifications, deux crédits ou deux reçus. Contraintes d'unicité en base : `(event_id, consumer_id)`.

### 11.2 Retry et backoff

```
Échec → retry (backoff exponentiel) → échec → retry → ... → après N tentatives → Dead Letter Queue
```

Le Financial Core n'est **jamais** retenté par ce mécanisme — il a déjà réussi avant que l'événement n'existe (section 8.3). Seuls les consommateurs en aval (notification, IA, analytics) sont retentés.

### 11.3 Dead Letter Queue

```
Événement → échec persistant → DLQ → monitoring/alerte → investigation humaine → replay manuel sécurisé ou abandon documenté
```

### 11.4 Replay contrôlé

Un replay cible un **consommateur précis**, jamais l'événement entier rejoué "en aveugle" contre tous les consommateurs — exemple : si la Notification Engine était hors service, on rejoue uniquement `payment.confirmed → Notification Consumer`, jamais `→ Financial Core` (qui a déjà traité l'événement à l'origine et refuserait de toute façon via l'idempotence).

Statut : `📋 PLANIFIÉ`.

---

## 12. Synchrone vs asynchrone — matrice générale

| Synchrone (bloquant) | Asynchrone (découplé) |
|---|---|
| Validation financière | Notifications (tous canaux) |
| Autorisation / permission | Génération d'insight IA |
| Écriture critique du Financial Core | Email, SMS, WhatsApp |
| Vérification webhook | Analytics, agrégation |
| Détection de doublon avant écriture | Génération de documents non urgents |
| | Mise à jour dashboard temps réel |
| | Digests périodiques |

Principe : si une panne du composant peut légitimement retarder l'action sans compromettre l'intégrité, il est asynchrone.

---

## 13. Cohérence des données — Transactional Outbox

Le risque à éliminer : `Financial Core = confirmed` mais `Event = perdu` (ou l'inverse). Solution retenue : **Transactional Outbox Pattern** — l'écriture métier (ex. `Payment.status = CONFIRMED`) et l'insertion de l'événement dans une table `outbox` se font dans **la même transaction base de données**. Un processus séparé (relay) lit la table outbox et publie sur l'Event Bus, avec retry jusqu'à confirmation de publication — jamais de double écriture non transactionnelle entre "sauver l'état" et "publier l'événement".

Statut : `📋 PLANIFIÉ`.

---

## 14. Versioning et registre de schéma

### 14.1 Versioning

`payment.confirmed` v1 → v2 : les consommateurs existants continuent de fonctionner avec v1 tant qu'ils ne migrent pas explicitement (versions coexistantes plutôt que migration forcée) ; un champ ajouté est rétrocompatible, un champ retiré ou renommé exige une nouvelle version majeure et une période de double publication (v1 et v2 émis en parallèle) le temps que tous les consommateurs migrent.

### 14.2 Registre de schéma

```
payment.confirmed
  Producteur: Financial Core
  Consommateurs: Receipt Service, Notification Engine, Treasury, Analytics, AI Context Engine
  Classification: Financier
  Pertinence IA: Medium (High si montant inhabituel — section 16.3)
  Rétention: 7 ans (aligné sur la rétention financière, à confirmer légalement — FINANCE.md §4)
```

Chaque type d'événement de la taxonomie (section 6.2) a une entrée dans ce registre avant d'être utilisable en production — pas de type d'événement "sauvage" créé sans déclaration.

Statut : `📋 PLANIFIÉ`.

---

## 15. Workflow Engine et Scheduler

### 15.1 Workflows longs

```
ExpenseCreated → (montant > seuil) → ApprovalRequired → DirectorNotification
   → DirectorApproves → ExpenseApproved → PaymentRequired → TreasuryPayment → ExpensePaid
```

Chaque transition est elle-même un événement — un workflow est une **séquence de règles** avec état persistant (`WorkflowExecution`, section 22), pas un script isolé du reste du système.

### 15.2 Événements temporels

```
Scheduler → évaluation des échéances (J-7, J-3, J-1, J, J+3, J+7, J+30) → installment.due_soon / installment.overdue → Rule Engine → Notification
```

Le Scheduler est un **producteur d'événements** comme un autre — il ne contourne jamais le Rule Engine pour notifier directement.

Statut : `📋 PLANIFIÉ`.

---

## 16. IA et événements

### 16.1 Ce que l'IA reçoit — jamais le flux brut

```
Events → Rule Engine (filtrage déterministe) → AI Context Engine (agrégation + pertinence) → AI Layer
```

L'IA ne reçoit jamais `SELECT * FROM events` — elle reçoit un contexte déjà construit, cohérent avec `SYSTEME_IA.md` §5 (Context Engine) et §7 (outils contrôlés).

### 16.2 Agrégation d'événements

Au lieu de 18 `payment.confirmed` bruts envoyés un par un, l'AI Context Engine agrège sur une fenêtre (ex. la journée) :
```
{ event_type_summary: "payment.confirmed", count: 18, total_amount: 4820, currency: "USD", vs_yesterday: "+12%" }
```
L'IA produit alors : *"La collecte est en hausse aujourd'hui : 4 820 $ encaissés, soit 12 % de plus qu'hier."* — jamais 18 appels séparés au modèle pour 18 paiements individuels (maîtrise du coût, section 21.2).

### 16.3 Score de pertinence IA

```
student.updated                        → pertinence FAIBLE (pas envoyé à l'IA)
payment.confirmed                      → pertinence MOYENNE (agrégé, section 16.2)
anomalie de paiement                   → pertinence HAUTE (envoyé immédiatement)
security.settlement_destination_changed → pertinence CRITIQUE (envoyé immédiatement, section 9)
```

Ce score, défini dans le registre de schéma (section 14.2), décide qui va à l'IA, ce qui reste purement déterministe, et évite de surcharger le modèle avec du bruit — cohérent avec le principe de coût de `SYSTEME_IA.md` §19.

### 16.4 IA proactive

À l'ouverture du dashboard, le briefing (`SYSTEME_IA.md` §10.5) est justement alimenté par cette agrégation d'événements de la nuit/journée précédente — ce document en précise la mécanique technique, `SYSTEME_IA.md` en garde la spécification UX (pas de duplication).

### 16.5 Compréhension du contexte de navigation

Quand le directeur ouvre `Finance`, le Context Engine (`SYSTEME_IA.md` §5) sait que le périmètre pertinent est recettes/paiements/obligations/trésorerie ; ouvrir `Classe 6e A` réduit ce périmètre aux événements de cette classe. C'est la même mécanique de résolution de contexte que celle déjà décrite pour la recherche en langage naturel — les événements en sont simplement la source de données sous-jacente.

Statut : `📋 PLANIFIÉ`.

---

## 17. Notification Engine

### 17.1 Indépendance des canaux

```
NotificationService → ChannelAdapter → PushProvider | EmailProvider | SMSProvider | WhatsAppProvider
```

Aucun verrouillage à un fournisseur unique — chaque adapter respecte une interface commune (`send(recipient, template, payload) → DeliveryStatus`), remplaçable sans toucher au reste du moteur.

### 17.2 Résolution d'audience — jamais l'inverse

```
Event → Audience Resolver → Permission Engine → Notification
```

Jamais `Notification → qui a le droit de la recevoir ?` a posteriori. L'audience est déterminée en amont, par les mêmes règles de permission que le reste du système (`SECURITE.md` §6-8) : un parent ne reçoit que ce qui concerne son enfant, un enseignant ne reçoit jamais de détail financier sensible, le directeur reçoit davantage. Le même événement `payment.confirmed` produit donc des messages différents pour chaque destinataire résolu :

| Rôle | Contenu |
|---|---|
| Parent | *"Le paiement de 250 $ pour Jean Dupont a été confirmé. Échéance : Septembre. Solde restant : 0 $."* |
| Directeur | *"Jean Dupont — 6e A — 250 $ — Orange Money — Échéance Septembre"* |
| Élève | *"Le paiement de votre dossier financier a été confirmé."* |
| Enseignant | Aucune notification (hors périmètre pédagogique) |

### 17.3 Notifications contextuelles

Le même flux d'événements produit une lecture différente selon l'écran consulté (mécanique commune avec le Context Engine, section 16.5) : vue `Finance` → agrégat de la journée ; vue `Classe 6e A` → activité financière de la classe ; vue `Dossier élève` → dernière activité individuelle. Ce n'est pas trois systèmes différents — c'est le même Event Store interrogé avec un filtre de contexte différent.

### 17.4 Priorité

```
LOW      — information générale, jamais poussée activement
NORMAL   — activité courante (ex. payment.confirmed) — groupable, différable
HIGH     — événement important (ex. payment.failed, anomalie) — poussé rapidement, peu groupable
CRITICAL — action immédiate requise (ex. settlement_destination_changed, compte compromis) — jamais groupée, jamais throttlée, multicanal
```

### 17.5 Notifications intelligentes — anti-spam

Grouping (10 paiements en 2 minutes → *"10 nouveaux paiements reçus, total 2 430 $"* pour le directeur, **mais chaque parent reçoit son propre paiement individuellement** — le regroupement est décidé par audience, pas globalement) ; déduplication (même événement, même destinataire, même canal → une seule notification) ; throttling et cooldown par type d'événement et par utilisateur ; les notifications `CRITICAL` échappent à tous ces mécanismes par construction (section 17.4).

**Fatigue de notification (§46 du brief) :** si un même fait a déjà été notifié par push, éviter par défaut de le renvoyer par SMS puis WhatsApp pour rien — sauf pour les événements de sévérité `HIGH`/`CRITICAL`, où la redondance multicanal est un choix délibéré, pas un bug.

### 17.6 Templates et internationalisation

```
payment.confirmed.parent · payment.confirmed.director · installment.overdue.parent · inventory.stock_low.manager
```

Templates externalisés (jamais codés en dur dans le backend), avec variables, formatage de montant/devise/date selon la locale, versionnés comme les événements (section 14.1). Langues minimales prévues : français, anglais — extensible.

### 17.7 Notification Center

```
[CRITICAL] Destination de règlement modifiée
[HIGH]     Anomalie financière détectée               [Examiner]
[NORMAL]   12 nouveaux paiements reçus
[NORMAL]   Import Excel terminé                        [Voir le rapport]
[INFO]     Nouveau document disponible
```

Gère lu/non lu, priorité, horodatage, catégorie, événement source (traçabilité, section 24), action associée, expiration, regroupement, archivage, préférences (section 17.8).

**Toute action déclenchée depuis une notification repasse par le circuit complet** : `Notification → Backend → vérification de permission → règles métier → action → nouvel événement`. Jamais d'action directe déclenchée depuis le client au clic sur un bouton de notification (cohérent avec `SECURITE.md` §14.2, le frontend n'est jamais une frontière de sécurité).

### 17.8 Préférences utilisateur

Configurable par type de notification et par canal (in-app / push / email / SMS), avec fréquence, horaires de silence (*quiet hours*), regroupement. **Ne peuvent jamais être totalement désactivées** : les notifications `CRITICAL` de sécurité (compte compromis, changement de destination de règlement) et les confirmations de paiement du parent concerné — parce que les désactiver créerait un risque de sécurité ou une contestation financière ("je n'ai jamais été informé de ce paiement").

### 17.9 Confidentialité par canal

Un écran verrouillé affichant *"Votre paiement de 3 500 $..."* dans l'aperçu d'une notification push est une fuite d'information. Règle : les canaux à aperçu public (push, écran verrouillé, SMS visible sans déverrouillage) reçoivent un contenu **minimisé** (*"Un paiement a été confirmé — ouvrez l'app pour le détail"*), le détail complet n'apparaissant que dans l'application authentifiée ou un canal jugé privé (email, WhatsApp après ouverture).

Statut : `📋 PLANIFIÉ`.

---

## 18. Intégration dashboard et temps réel

```
payment.confirmed → Dashboard Event → Revenus +250, Impayés −250, Paiements +1
```

Pas de rafraîchissement manuel nécessaire. Choix technique : **Server-Sent Events** pour la mise à jour du dashboard (flux unidirectionnel serveur → client, suffisant pour ce besoin, plus simple à opérer que WebSockets à cette échelle) ; **WebSockets** réservés à un futur besoin bidirectionnel réel (ex. un futur chat, hors périmètre actuel — cohérent avec `SYSTEME_IA.md` §1.1, pas de chat prévu) ; **polling** en repli uniquement pour les clients/réseaux qui ne supportent pas SSE.

Statut : `📋 PLANIFIÉ`.

---

## 19. Digests

```
Directeur — Résumé quotidien
42 paiements · 8 420 $ encaissés · 3 paiements échoués · 12 échéances demain
2 dépenses en attente d'approbation · 1 anomalie détectée
```
```
Parent — Résumé hebdomadaire
2 paiements effectués · 0 échéance en retard · 1 document disponible
```

Un digest est une **agrégation programmée** des événements de la période, filtrée par audience (section 17.2) — même mécanique que le briefing IA (section 16.4) mais purement factuelle, sans reformulation, pour les utilisateurs qui préfèrent un résumé brut à une narration.

Statut : `📋 PLANIFIÉ`.

---

## 20. Observabilité

Métriques attendues : volume d'événements par type/tenant, taux d'échec par consommateur, latence de traitement, taille de la Dead Letter Queue, taux de livraison par canal de notification, disponibilité par fournisseur (SMS/email/push/WhatsApp), nombre de retries. Logs structurés par `event_id`/`correlation_id` pour permettre une trace de bout en bout. Alerting sur : DLQ qui grossit, fournisseur de notification en panne, latence anormale du bus, volume d'événements de sécurité inhabituel (recoupe `SECURITE.md` §15).

Statut : `📋 PLANIFIÉ`.

---

## 21. Performance, scalabilité, coûts

### 21.1 Scalabilité

Conçu pour croître de 1 établissement à plusieurs milliers sans réécriture : partitionnement du bus par `tenant_id` (un pic d'événements d'un établissement ne dégrade pas les autres — cohérent avec le rate limiting de `SECURITE.md` §16), traitement par workers horizontalement scalables, batching pour les consommateurs à fort volume (analytics, digests), backpressure pour ne jamais laisser un consommateur lent bloquer le producteur, politique de rétention explicite de l'Event Store (les événements anciens migrent vers un stockage froid, jamais supprimés silencieusement s'ils ont une valeur d'audit).

### 21.2 Maîtrise des coûts (IA en particulier)

L'agrégation (section 16.2) est la principale protection contre un coût IA incontrôlé — un modèle n'est jamais appelé événement par événement pour un flux à fort volume. Cohérent avec `SYSTEME_IA.md` §19 (sélection de modèle par coût, budgets de tokens).

Statut : `📋 PLANIFIÉ`.

---

## 22. Modèles de données

```
Event · EventType · EventConsumer · EventProcessing
Rule · RuleCondition · RuleAction
Notification · NotificationTemplate · NotificationDelivery · NotificationPreference · NotificationGroup
EventSubscription · AIEventContext
Digest
Workflow · WorkflowExecution
```

Relations clés : `Event 1—N EventProcessing` (un statut de traitement par consommateur) ; `Rule 1—N RuleAction` ; `Notification 1—1 NotificationDelivery par canal tenté` ; `Notification N—1 Event` (traçabilité, section 24) ; `WorkflowExecution N—N Event` (chaque transition est un événement).

Codifié en référence dans [assets/js/event-model.js](../assets/js/event-model.js) (créé dans ce tour de travail), même esprit que les trois catalogues précédents.

Statut : `✅ IMPLÉMENTÉ` en tant que référence codifiée · `⛔ NON APPLIQUÉ`.

---

## 23. API — interfaces internes indicatives

```
POST /events                    GET /events/:id            GET /events
POST /events/:id/replay
POST /rules                     PUT /rules/:id             POST /rules/:id/test
GET  /notifications             POST /notifications/:id/read   POST /notifications/:id/action
GET  /notification-preferences  PUT /notification-preferences
```

À privilégier comme contrat de service interne (producteur/consommateur découplés par le bus) plutôt qu'une API REST exhaustive exposée telle quelle — à adapter à l'architecture backend réelle une fois choisie.

Statut : `📋 PLANIFIÉ`.

---

## 24. Auditabilité

Chaque notification importante se retrace intégralement :

```
Notification N123 ← déclenchée par payment.confirmed (EV987)
                  ← via la règle RULE_PAYMENT_CONFIRM_PARENT_V2
                  → destinataire: Parent #456 · canal: WhatsApp · statut: Delivered
```

Cette chaîne `Notification → Rule → Event → Action métier → Acteur` s'appuie sur `correlation_id`/`causation_id` (section 6.1) et rejoint le modèle d'audit déjà posé dans `SECURITE.md` §11 et `FINANCE.md` §17 — un seul système d'audit pour toute la plateforme, pas un troisième journal spécifique aux événements.

---

## 25. Multi-tenant, permissions, sécurité

Isolation stricte par `tenant_id` (et `academic_year_id` lorsque pertinent) à la création, à la persistance et à la consommation de l'événement — un événement de l'école A ne peut jamais déclencher une notification, une action ou un accès IA dans l'école B (cohérent avec `SECURITE.md` §3). Les événements de sécurité (`security.*`) suivent le même bus mais avec une classification et une priorité toujours `HIGH` minimum (section 17.4), et les actions critiques qui en découlent restent la responsabilité exclusive du Security Engine (`SECURITE.md`), jamais du Rule Engine seul pour les décisions de blocage.

Statut : `📋 PLANIFIÉ`.

---

## 26. UI d'administration

Trois vues internes, réservées aux rôles techniques/direction habilités, sans complexité inutile :

- **Event Monitor** : liste des événements avec type, horodatage, source, entité, statut de traitement par consommateur.
- **Rule Monitor** : règles actives, ce qu'elles déclenchent, dernière exécution.
- **Notification Monitor** : envoyé / délivré / échoué / en attente / en retry, par canal.

## 27. UX — complexité derrière, simplicité devant

Un parent ne voit jamais *Event Engine*, *Rule Engine*, *Queue*, *Consumer*, *Webhook* — il voit *"Paiement confirmé"*. Le directeur a plus de visibilité (*"18 paiements confirmés aujourd'hui"*), sans jamais descendre à la mécanique événementielle sauf s'il a un rôle technique habilité (section 26). Même hiérarchie que déjà établie pour l'IA (`SYSTEME_IA.md` §15) et le dashboard (`FINANCE.md` §16, `OBJECTIFS_ET_FONCTIONNALITES.md`).

---

## 28. Tests

Paiement (`confirmed/failed/pending/duplicate/refund/reversal/unknown`), notifications (fournisseur indisponible, doublon, mauvais destinataire, mauvais tenant, mauvais rôle), événements (doublon, désordonné, manquant, rejoué, incompatibilité de version), sécurité (consommateur non autorisé, événement inter-tenant, événement forgé, payload altéré), IA (mauvais contexte, fuite de permission, prompt injection via payload d'événement, payload malveillant — cohérent avec `SYSTEME_IA.md` §21).

---

## 29. Cas limites (edge cases)

| Cas | Comportement attendu |
|---|---|
| Paiement confirmé mais notification impossible | Financial Core reste `CONFIRMED` ; notification en retry, jamais un rollback financier (section 8.3) |
| Événement traité deux fois | Idempotence côté consommateur, aucun doublon (section 11.1) |
| Événement reçu dans le mauvais ordre | Le Rule Engine se fie à `occurred_at`/`causation_id`, pas à l'ordre de réception réseau |
| Paiement confirmé puis immédiatement remboursé | Deux événements distincts, chaîne complète conservée, jamais une fusion qui efface le premier |
| Parent avec plusieurs enfants | Résolution d'audience par obligation, pas par parent — une notification par enfant concerné |
| Étudiant transféré de classe pendant qu'une notification était en file | La notification référence l'état au moment de l'événement (payload figé), pas l'état courant |
| Changement d'année scolaire | Événements et obligations restent séparés par année (`FINANCE.md` §20) |
| Compte parent désactivé | Notification supprimée de la file pour ce destinataire, journalisée comme "non livrée — compte inactif" |
| Téléphone changé entre l'événement et l'envoi | Le canal SMS utilise la donnée de contact **au moment de l'envoi**, pas celle capturée dans le payload |
| Fournisseur SMS/WhatsApp indisponible | Retry + fallback canal si configuré, jamais de blocage du reste du système |
| Email invalide / utilisateur sans canal | Notification journalisée comme non livrable, visible dans le Notification Center in-app au minimum |
| Événement très ancien rejoué par erreur | Fenêtre de validité de replay + confirmation explicite requise pour un rejeu hors fenêtre normale |
| Règle désactivée après création de l'événement, avant traitement | La règle active **au moment du traitement** s'applique, avec le comportement documenté par établissement (à définir explicitement, pas laissé implicite) |
| Panne base de données pendant le traitement | Le Transactional Outbox garantit qu'aucun événement n'est perdu (section 13) ; reprise au retour du service |
| Queue saturée | Backpressure, priorité aux événements `CRITICAL`/`HIGH` (section 21.1) |
| Fournisseur IA indisponible | Le Context Engine reste disponible, l'insight est simplement différé — jamais bloquant pour un événement métier |
| Tenant supprimé | Ses événements en file sont purgés/archivés selon la politique de rétention, jamais traités pour un autre tenant |
| Obligation annulée après un paiement déjà confirmé | Traité comme une correction explicite (`FinancialAdjustment`, `FINANCE.md` §5), jamais une suppression rétroactive de l'événement d'origine |
| Paiement non identifié | Reste `UNRECONCILED` (`FINANCE.md` §7.5) — aucun événement `payment.confirmed` tant que l'affectation n'est pas validée |

---

## 30. Roadmap

### MVP
Modèle d'événement + Event Store minimal, taxonomie de base (paiements, obligations, import), Rule Engine simple (conditions + notification), Transactional Outbox, idempotence, notifications in-app uniquement, audit de base.

### V1
Notification multicanal complète (push, email, SMS), grouping/dedup/priorité, préférences utilisateur, digests, Dead Letter Queue + replay contrôlé, dashboard temps réel (SSE), AI Context Engine avec agrégation.

### V2
Workflow Engine complet, versioning d'événements avec registre de schéma formel, event chaining avancé avec détection de cycle automatisée, observabilité complète (métriques/traces), UI d'administration (Event/Rule/Notification Monitor).

### Plus tard
Analytics événementiel avancé, scoring de pertinence IA affiné par apprentissage des retours utilisateurs, multi-région pour la scalabilité à très grande échelle.

---

## Annexe A — Ce que ce tour de travail a ajouté au code

[assets/js/event-model.js](../assets/js/event-model.js) — catalogue codifié (types d'événements par domaine, niveaux de priorité, statuts de traitement, formes d'entités), pure référence sans logique exécutable, non chargé par aucune page, même esprit que `permissions.js`, `financial-model.js`, `import-model.js`.

## Annexe B — Légende de statut

Identique aux documents précédents.
