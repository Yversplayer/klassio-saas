# KLASSIO — Moteur Financier Central (Financial Core)
### Spécification V0.1 — architecture financière de niveau production

Ce document complète [OBJECTIFS_ET_FONCTIONNALITES.md](OBJECTIFS_ET_FONCTIONNALITES.md) (vision produit, sections 9-17 déjà consacrées à la finance), [SYSTEME_IA.md](SYSTEME_IA.md) (IA, dont l'IA financière) et [SECURITE.md](SECURITE.md) (RBAC, audit, multi-tenant). Il ne duplique aucun des trois — il renvoie systématiquement plutôt que de répéter.

## 0. État réel du projet (inspection préalable, point 92 de votre brief)

Inspection effectuée avant d'écrire une ligne de ce document : le projet ne contient **aucun backend, aucune base de données, aucun module de paiement**. C'est un prototype frontend statique (HTML/CSS/JS sans build). Les seuls chiffres financiers existants sont des **valeurs d'affichage codées en dur** dans [assets/js/app.js](../assets/js/app.js) (`DASH_CONTENT`, ex. `"Encaissé ce mois": "18 420 $"`) et dans [index.html](../index.html) — ce sont des maquettes visuelles, pas des lectures d'un quelconque moteur financier. Aucune duplication ni incohérence de code à corriger : il n'y a simplement rien à refactoriser, tout reste à construire.

Ce document utilise la même légende de statut que `SECURITE.md` §Annexe C : `✅ IMPLÉMENTÉ` · `🟡 PARTIEL` · `📋 PLANIFIÉ` · `⛔ NON IMPLÉMENTÉ` · `🔌 FOURNISSEUR EXTERNE`. Par honnêteté (principe déjà posé dans `SECURITE.md`), presque tout ce document est `📋 PLANIFIÉ`. Ce qui est réellement ajouté au code dans ce tour de travail est listé en Annexe D.

**Distinction centrale à garder en tête (point 91) :** ce document sépare `ARCHITECTURE READY` (les fondations conçues pour supporter toute la vision) de `FEATURE IMPLEMENTED` (ce qui sera réellement codé, et quand). On ne construit pas un logiciel comptable complet au MVP.

---

## 1. Principes non négociables

1. Le Financial Core est **l'unique** source de vérité financière de l'établissement.
2. Un mouvement financier n'est jamais enregistré deux fois comme source officielle — il peut apparaître dans plusieurs vues (élève, classe, dashboard, rapports, IA), mais c'est toujours le même événement.
3. Le frontend ne décide jamais d'un résultat financier — il l'affiche.
4. Le backend vérifie et recalcule toute opération financière, jamais de confiance dans une valeur envoyée par le client.
5. Une transaction confirmée n'est jamais modifiée ou supprimée silencieusement.
6. Toute correction est traçable : `original + correction`, jamais une écrasure.
7. Paiements, dépenses, salaires et transferts alimentent **le même** moteur financier — pas cinq systèmes indépendants.
8. Banque, caisse et Mobile Money sont des canaux/comptes de trésorerie, pas des systèmes financiers séparés.
9. Les frais de paiement (processing fees) ne modifient jamais automatiquement la dette scolaire due par l'élève.
10. Une école ne voit jamais les finances d'une autre école (cf. `SECURITE.md` §3).
11. L'IA analyse et assiste ; elle ne devient jamais l'autorité financière (cf. `SYSTEME_IA.md` §Principes).
12. Les calculs financiers critiques sont déterministes et vérifiables — jamais estimés par un modèle de langage.
13. Toute opération financière importante est traçable (audit, cf. `SECURITE.md` §11).
14. Les opérations critiques peuvent nécessiter une approbation (workflow, section 19 ci-dessous).
15. Les paiements sont idempotents.
16. Un solde doit toujours pouvoir être expliqué jusqu'à son origine (section 17).
17. Créances et dettes sont distinctes des encaissements et décaissements réels.
18. Les actifs sont distingués des dépenses lorsque la nature de l'opération l'exige.
19. Un transfert entre comptes n'est jamais automatiquement un revenu ou une dépense.
20. Le système peut évoluer vers une comptabilité plus complète sans reconstruction totale (section 22).

---

## 2. Vision et principe central

Un seul Financial Core, jamais cinq systèmes indépendants :

```
                  FINANCIAL CORE
                       |
        ┌──────────────┼──────────────┐
        ↓              ↓              ↓
     REVENUS        DÉPENSES         PAIE
        ↓              ↓              ↓
     PAIEMENTS       ACHATS        EMPLOYÉS
        ↓              ↓              ↓
   MOBILE MONEY    FOURNISSEURS     SALAIRES
        ↓              ↓              ↓
      BANQUE          ACTIFS         PASSIFS
        ↓              ↓              ↓
      CAISSE          STOCK          DETTES
        └──────────────┼──────────────┘
                       ↓
                  TRÉSORERIE
                       ↓
                FINANCIAL LEDGER
                       ↓
                RAPPORTS / IA
```

Chaque module (facturation, paiements, paie, achats, stock) **écrit** dans le même Ledger et **lit** le même ensemble de comptes financiers — aucun module ne maintient son propre solde indépendant.

Statut : `📋 PLANIFIÉ` (architecture cible — rien n'est codé).

---

## 3. Modèle financier de l'établissement

Le système doit pouvoir répondre à cinq questions structurantes, séparées explicitement (jamais mélangées dans un seul nombre) :

| Question | Nature comptable | Exemples |
|---|---|---|
| Ce que l'école **possède** | Actifs | Caisse, banque, Mobile Money, matériel, bâtiments, véhicules, stock |
| Ce qu'elle **doit recevoir** | Créances | Frais scolaires impayés, factures clients |
| Ce qu'elle **doit payer** | Passifs / dettes | Salaires dus, factures fournisseurs, emprunts |
| Ce qu'elle **gagne** | Revenus | Frais scolaires, inscriptions, uniformes, transport, cantine, examens |
| Ce qu'elle **dépense** | Dépenses | Salaires payés, achats, maintenance, électricité, loyers |

Ces cinq catégories restent séparées dans le modèle de données (section 5, types de comptes) — jamais réduites à un seul "solde" agrégé qui masquerait leur nature.

Statut : `📋 PLANIFIÉ`.

---

## 4. Comptes financiers (Financial Account)

Abstraction interne, **distincte** d'un compte bancaire réel (un `FinancialAccount` de type `BANK` peut être *lié* à un compte bancaire réel, mais représente la réalité économique dans le système, pas le compte physique lui-même).

```
FinancialAccount {
  id, tenant_id, name, type, currency, balance (dérivé du ledger, jamais stocké comme vérité primaire),
  status, created_at, external_reference?  // ex. IBAN masqué, ID provider Mobile Money
}
```

**Types de comptes :**
```
ASSET · LIABILITY · EQUITY · REVENUE · EXPENSE
RECEIVABLE · PAYABLE
CASH · BANK · MOBILE_MONEY
INVENTORY · FIXED_ASSET
```

Comptes typiques d'un établissement (exemples, pas une liste figée) :
```
CASH_MAIN · BANK_USD · BANK_CDF · ORANGE_MONEY
STUDENT_RECEIVABLES · SUPPLIER_PAYABLES · SALARY_PAYABLES
INVENTORY · FIXED_ASSETS
```

**Important — séparation Financial Management / Statutory Accounting (votre point 5) :** ce catalogue de types sert la **gestion financière interne** (comprendre où va l'argent). Il ne prétend pas implémenter un plan comptable légal (OHADA ou autre référentiel national) tant que les règles fiscales/comptables précises du ou des pays ciblés n'ont pas été définies avec un expert-comptable local. Le modèle est conçu pour qu'une correspondance vers un plan comptable réglementaire puisse être ajoutée plus tard (mapping `FinancialAccount.type` → compte comptable légal) sans réécrire le Ledger.

Statut : `📋 PLANIFIÉ`.

---

## 5. Ledger Architecture — la source de vérité

Le **Financial Ledger** enregistre chaque mouvement, immuable :

```
LedgerEntry {
  transaction_id, tenant_id, date, currency, amount,
  source_account, destination_account, type, reference,
  description, status, created_by, approved_by?, created_at
}
```

**Aucune modification silencieuse.** Une correction = une nouvelle écriture (`ORIGINAL + REVERSAL/CORRECTION`), jamais un `UPDATE`/`DELETE` sur une écriture confirmée.

### 5.1 Logique de double entrée (conceptuelle)

Le moteur doit pouvoir représenter chaque mouvement comme un mouvement à deux jambes, même si l'utilisateur ne voit jamais cette mécanique :

| Événement | Compte A | Compte B |
|---|---|---|
| Parent paie 250 $ | `CASH/BANK/MOBILE_MONEY +250` | `STUDENT_RECEIVABLE -250` |
| Dépense fournisseur 1 000 $ | `EXPENSE +1000` | `BANK/CASH -1000` |
| Achat de matériel 1 000 $ | `ASSET +1000` | `BANK/PAYABLE -1000` |

L'utilisateur voit *"Paiement reçu : 250 $"* ; le Ledger gère la structure sous-jacente (principe UX, section 20).

### 5.2 Devises

Chaque transaction porte une devise explicite — **jamais** de montant sans devise supposée valide. Multi-devises dès la conception (ex. USD/CDF) :

```
FinancialTransaction {
  ..., original_amount, original_currency,
  converted_amount?, exchange_rate?, rate_date?, rate_source?
}
```

Aucun mélange automatique de devises sans règle explicite (ex. pas de compensation silencieuse USD ↔ CDF).

Statut : `📋 PLANIFIÉ`.

---

## 6. Billing Architecture — obligations, factures, échéances

### 6.1 Obligation financière

```
Receivable/Obligation {
  student_id, tenant_id, academic_year, category, amount, currency,
  due_date, status, payments[] (dérivé), remaining_balance (dérivé)
}
```

Une obligation de 1 200 $ peut être découpée en échéances (300 $ × 4) — chaque échéance est un objet suivi individuellement, pas juste une note textuelle.

### 6.2 Statuts — calculés, jamais déclarés par le frontend

```
DRAFT → ISSUED → PARTIALLY_PAID → PAID
                → OVERDUE
       → CANCELLED · WAIVED · REFUNDED
```

Le statut est **dérivé** de `TOTAL_DUE`, `TOTAL_PAID`, `REMAINING_BALANCE` calculés par le backend à partir des paiements réels — un frontend qui enverrait `status = PAID` est ignoré.

### 6.3 Paiements partiels et surpaiement

Le système maintient automatiquement `TOTAL_DUE / TOTAL_PAID / REMAINING_BALANCE` à chaque paiement. En cas de surpaiement (dette 250 $, paiement 300 $), les 50 $ excédentaires ne sont **jamais ignorés** — une politique explicite et configurable par établissement décide : crédit sur le compte de l'élève, affectation à une autre obligation, remboursement, ou solde à utiliser plus tard.

### 6.4 Remboursements

Un remboursement est une opération séparée, jamais une modification de la transaction d'origine :

```
Refund { original_transaction_id, amount, reason, requested_by,
         approved_by?, method, date, reference }
```

Remboursements importants → workflow d'approbation (section 19) ; jamais exécutés seuls par l'IA (`SYSTEME_IA.md` §11).

### 6.5 Réductions, bourses, prix variables

Une réduction est **enregistrée séparément**, jamais fusionnée dans le prix : `Original 1000 → Discount 200 → Final 800`, les trois valeurs conservées. Les prix peuvent varier par classe/niveau/année/élève (catalogue financier, section suivante) — toute modification de prix est auditée (cf. `SECURITE.md` §11).

### 6.6 Frais de transaction ≠ dette scolaire (principe non négociable)

Si l'école facture 250 $, l'élève doit 250 $, **point final**. Les frais du fournisseur de paiement sont modélisés séparément :

```
AMOUNT_DUE (250) · PAYMENT_AMOUNT (250) · PROCESSING_FEE (2) · NET_SETTLEMENT (248)
```

Le parent ne doit jamais voir sa dette scolaire "gonfler" à cause d'un fournisseur de paiement.

Statut : `📋 PLANIFIÉ`.

---

## 7. Payment Architecture

### 7.1 Canaux — un seul moteur derrière

```
CASH · BANK_TRANSFER · BANK_PAYMENT · MOBILE_MONEY · CARD · OTHER
```

Le canal change, le Financial Core reste identique — aucun canal n'a sa propre logique de solde.

### 7.2 Flux Mobile Money

```
PARENT → PAYMENT ORDER → PAYMENT PROVIDER → AUTORISATION → WEBHOOK
       → VÉRIFICATION SERVEUR → FINANCIAL TRANSACTION → LEDGER → REÇU → SOLDE MIS À JOUR
```

Le clic sur "Payer" n'est **jamais** une preuve de paiement — la transaction ne passe à `CONFIRMED` qu'après vérification serveur (cf. `SECURITE.md` §9.2).

### 7.3 États explicites

```
CREATED → PENDING → PROCESSING → CONFIRMED
                                → FAILED
                                → CANCELLED
                                → EXPIRED
                  → UNKNOWN (jamais réduit automatiquement à FAILED)
CONFIRMED → REFUNDED / REVERSED (jamais supprimé)
```

### 7.4 Idempotence

`transaction_id` + `provider_reference` + `idempotency_key`, contraintes d'unicité en base, déduplication de webhook : un webhook rejoué est ignoré, jamais recrédité (détail complet `SECURITE.md` §9.3-9.4).

### 7.5 Transactions inconnues / non rapprochées

Un paiement bancaire reçu sans référence correspondante entre en statut `UNRECONCILED` — mis en attente, jamais affecté arbitrairement à un élève. Recherche, affectation manuelle justifiée, ou classement en écart de rapprochement (section 9).

Statut : `📋 PLANIFIÉ`.

---

## 8. Treasury Architecture

### 8.1 Comptes bancaires

Plusieurs comptes par établissement, par devise. Informations sensibles protégées selon `SECURITE.md` §9.5, §12.

### 8.2 Caisse

```
CashRegister { opening_balance, cash_in, cash_out, expected_balance (dérivé), actual_balance, status }
```

À la clôture : `ACTUAL` comparé à `EXPECTED`. Un écart (ex. attendu 5 000 $, réel 4 850 $ → écart -150 $) est **signalé**, justifié, et enregistré comme événement (`CashDiscrepancyDetected`) — le système ne modifie jamais silencieusement le solde pour "faire coller les chiffres".

### 8.3 Transferts internes ≠ revenus

Un transfert Mobile Money → Banque (`Orange Money -10 000` / `Bank +10 000`) est un **transfert interne**, jamais un nouveau revenu. Le total de trésorerie de l'établissement reste inchangé — c'est un test d'intégrité explicite (section 24).

### 8.4 Séparation des fonds

Le système distingue : fonds disponibles, réservés, affectés, en attente de settlement, bloqués. Un paiement Mobile Money reçu mais pas encore réglé par le fournisseur n'est **pas** compté comme disponible tant que le settlement réel n'a pas eu lieu.

### 8.5 Trésorerie prévisionnelle

Projection à partir des salaires à venir, factures fournisseurs à échéance, et frais scolaires attendus — présentée explicitement comme une **estimation**, jamais un chiffre garanti (cohérent avec `SYSTEME_IA.md` §10.4 sur la prudence des formulations IA).

Statut : `📋 PLANIFIÉ`.

---

## 9. Rapprochement (Reconciliation)

Comparaison `SOLDE SYSTÈME` vs `RELEVÉ BANCAIRE` (ou export Mobile Money), avec classement automatique :

```
MATCHED · UNMATCHED · PARTIAL_MATCH · NEEDS_REVIEW
```

Le système identifie transactions correspondantes, manquantes, montants différents, doublons, dates incohérentes — mais ne "corrige" jamais automatiquement le Ledger sans validation humaine explicite.

Statut : `📋 PLANIFIÉ`.

---

## 10. Payroll Architecture

### 10.1 Employés

```
Employee { profile, function, contract, salary, currency, frequency, payment_date, status, history }
```

Couvre enseignants, administration, personnel de nettoyage, sécurité, chauffeurs.

### 10.2 Cycle de paie

```
PAYROLL PERIOD → EMPLOYEES → SALARY CALCULATION → ADJUSTMENTS
              → REVIEW → APPROVAL → PAYMENT → LEDGER → FICHE DE PAIE
```

Aucun utilisateur ne modifie silencieusement le montant final calculé — toute correction passe par un ajustement tracé (section 10.3).

### 10.3 Composants de salaire (architecture extensible, règles locales non inventées)

```
BASE_SALARY · BONUS · ALLOWANCE · DEDUCTION · ADVANCE · ABSENCE · OTHER_ADJUSTMENT
```

Impôts, cotisations et retenues légales sont **préparés architecturalement** (champ extensible) mais pas implémentés tant que les règles fiscales/sociales du pays cible n'ont pas été validées — cohérent avec la séparation Financial Management / Statutory Accounting (section 4).

### 10.4 Avances sur salaire

Une avance (ex. 100 $ sur un salaire de 500 $) est une véritable opération financière liée à l'employé et à la période, déduite au calcul du salaire net, jamais un simple ajustement manuel du chiffre final.

### 10.5 Paiement des salaires

Canaux identiques aux paiements parents (banque, Mobile Money, cash) → même Ledger. Statuts : `DRAFT → CALCULATED → APPROVED → PROCESSING → PAID / FAILED / CANCELLED`.

Statut : `📋 PLANIFIÉ` — module V2 selon la roadmap (section 26), architecture posée dès maintenant.

---

## 11. Purchase & Supplier Architecture

### 11.1 Workflow d'achat

```
PURCHASE REQUEST → DEVIS/FOURNISSEUR → APPROBATION → BON DE COMMANDE
                 → RÉCEPTION → FACTURE → PAYABLE → PAIEMENT → LEDGER
```

### 11.2 Fournisseurs

```
Supplier { identité, contacts, historique, produits/services, factures, montants dus, paiements, contrats, documents }
```

### 11.3 Dettes fournisseurs

```
Invoice 5 000 $ − Paid 2 000 $ = Payable (dette) 3 000 $
```

Le montant restant devient une dette fournisseur suivie dans le temps, avec sa propre échéance.

Statut : `📋 PLANIFIÉ` — V1/V2 selon roadmap.

---

## 12. Actifs, passifs, créances, dettes

### 12.1 Actifs

```
Asset { asset_id, name, category, purchase_date, purchase_value, current_value,
        location, responsible, status, supplier, document }
```

Cycle de vie : `PURCHASED → ACTIVE → MAINTENANCE → TRANSFERRED → DAMAGED → LOST → SOLD → DISPOSED`, historique conservé intégralement. L'amortissement (méthode, durée, valeur résiduelle) est préparé architecturalement, jamais imposé sans validation des règles comptables applicables (section 4).

### 12.2 Passifs

```
Liability { montant_initial, montant_payé, montant_restant, échéance, statut, contrepartie, documents }
```

Dettes fournisseurs, salaires dus, emprunts, avances. Les emprunts/prêts (principal, intérêts, échéances) sont préparés architecturalement, non prioritaires pour le MVP.

### 12.3 Créances (élèves) et aging

```
TOTAL_SCHOOL_FEES − PAID = OUTSTANDING
```

Analyse par ancienneté (aging) :
```
CURRENT · 1–30 JOURS · 31–60 JOURS · 61–90 JOURS · 90+ JOURS
```

Permet au directeur de localiser précisément où se trouvent les problèmes de recouvrement (par classe, par élève, par période).

Statut : `📋 PLANIFIÉ` — créances/aging priorisées MVP/V1 (proches du cœur "frais scolaires" déjà central au produit) ; actifs/passifs/emprunts en V2.

---

## 13. Budget Architecture

```
Budget { catégorie, montant_annuel, période }
BudgetLine { budget_id, dépenses_réelles (dérivé du Ledger) }
```

Comparaison continue `BUDGET vs ACTUAL`. Alerte de seuil configurable (ex. *"Le budget maintenance atteint 85 %"*) — le calcul du pourcentage est déterministe (Business Logic), seule sa mise en mots peut être confiée à l'IA (`SYSTEME_IA.md` §10.4).

Statut : `📋 PLANIFIÉ` — V1/V2.

---

## 14. Intégration Stock ↔ Finance

```
Achat 100 uniformes à 10 $  →  Inventory +1000 $  /  Cash/Payable −1000 $
Vente de 20 uniformes       →  Inventory −(20×coût)  ;  Revenue enregistré séparément
```

`PURCHASE_COST` et `SALES_REVENUE` ne sont **jamais** mélangés dans un seul mouvement — deux écritures distinctes dans le Ledger, reliées par l'article vendu.

Statut : `📋 PLANIFIÉ` — V1/V2, dépend du module Stock déjà esquissé dans `OBJECTIFS_ET_FONCTIONNALITES.md` §17.

---

## 15. Catalogue financier et règles de facturation

Centralise tout ce que l'école facture : frais scolaires, uniformes (par pièce), fournitures, transport, cantine, examens, certificats, carte scolaire, autres services. Chaque élément : prix, devise, catégorie, stock éventuel, période, niveau/classe applicable, statut, règles de prix.

**Prix variables** : un même article peut avoir un prix par niveau (`Primaire 18 $` / `Secondaire 22 $`) voire un prix individuel pour un élève donné — toute modification de prix est auditée (`SECURITE.md` §11). Règles de facturation prévues : prix par classe/niveau/année, réduction, exemption, remise, bourse, frais individuels, pénalité si l'établissement le décide, frais exceptionnels — toutes explicites, jamais implicites dans le code.

Statut : `📋 PLANIFIÉ` — cœur du MVP (rejoint `OBJECTIFS_ET_FONCTIONNALITES.md` §10).

---

## 16. Dashboard financier, vues agrégées et rapports

### 16.1 Dashboard directeur

Revenus (jour/semaine/mois/année), dépenses, trésorerie (caisse/banque/Mobile Money/total), créances (total, retard, évolution), dettes (fournisseurs, salaires, autres), résultat opérationnel (`REVENUS − DÉPENSES`), budget vs actual.

**Règle non négociable (point 71 de votre brief) :** le dashboard, le profil élève, la vue classe, les rapports et l'IA **lisent tous le Financial Core** — aucun ne recalcule un solde de façon indépendante. *(Note d'inspection : les chiffres actuellement affichés dans le prototype — `18 420 $`, `3 260 $`, `42 900 $` dans `app.js`/`index.html` — sont des valeurs de maquette statiques ; quand le Financial Core existera, ces mêmes emplacements devront être remplacés par une lecture réelle, jamais par un calcul frontend.)*

### 16.2 Vues agrégées — pas de duplication

```
Établissement → Classe → Élève → Obligation → Paiement
```

Chaque niveau est une **agrégation** du même Ledger, jamais une copie de données stockée séparément. Exemple classe :
```
6e A — 45 élèves — Total dû 20 000 $ — Payé 16 500 $ — Impayé 3 500 $ — Recouvrement 82,5 %
```

Permission : le parent voit ce qui le concerne, l'enseignant n'a **pas** automatiquement accès aux données financières détaillées des familles (cf. `SECURITE.md` §7).

### 16.3 Rapports et exports

Revenus, dépenses, paiements, impayés, caisse, banque, Mobile Money, fournisseurs, salaires, achats, stocks, actifs, passifs, budget, trésorerie. Exports PDF/CSV/Excel avec permissions strictes et audit systématique (`SECURITE.md` §16, §51 de votre brief sécurité).

Statut : `📋 PLANIFIÉ`.

---

## 17. Explicabilité (Explainability) et audit financier

Tout montant doit être cliquable jusqu'à son origine :

```
TOTAL DÉPENSES → Catégorie → Fournisseur → Facture → Paiement → Transaction bancaire
```

Chaque écriture du Ledger porte assez d'information pour répondre à : *pourquoi le compte bancaire est-il passé de 20 000 $ à 17 450 $ ?* → décomposition en mouvements individuels (`-1500 fournisseur`, `-500 salaire`, `-550 dépense`...).

**Audit financier** (complète `SECURITE.md` §11) : `QUI · QUOI · QUAND · OÙ · COMBIEN · POURQUOI · AVANT · APRÈS · RÉFÉRENCE · STATUT` pour chaque opération importante.

**AI Explainability** : si l'IA affirme *"les dépenses ont augmenté de 18 %"*, elle doit pouvoir décomposer (`+12 % fournitures, +8 % maintenance, -2 % transport`) à partir de données réelles du Ledger — jamais inventer une justification (`SYSTEME_IA.md` §10.4, principe de prudence).

Statut : `📋 PLANIFIÉ`.

---

## 18. IA Financière — renvoi et spécificités

L'essentiel (architecture, permission layer, niveaux d'action READ/PROPOSE/EXECUTE, sécurité, prompt injection) est déjà dans `SYSTEME_IA.md` — notamment §10.2 à §10.9. Ce qui est **spécifique à la finance** et à préciser ici :

| Capacité | Exemple |
|---|---|
| Analyse | *« Les revenus ont-ils augmenté ce mois-ci ? »* |
| Explication | *« Pourquoi la trésorerie baisse-t-elle ? »* (section 17) |
| Détection d'anomalie | *« Une dépense inhabituelle de 4 500 $ vient d'apparaître »* — l'IA **signale**, elle ne conclut jamais seule à la fraude (cf. `SYSTEME_IA.md` §10.8) |
| Prévision | *« Si les dépenses continuent au même rythme, la trésorerie pourrait atteindre X »* — toujours présenté comme une estimation |
| Alerte budgétaire | *« Le budget maintenance atteint 85 % »* (section 13) |
| Copilot financier | *« Avons-nous assez de trésorerie pour payer les salaires ? »*, *« Quel fournisseur doit-on payer cette semaine ? »* |

Tous ces outils IA (`get_receivables`, `get_cash_position`, `get_top_expenses`…) sont des fonctions contrôlées et scopées par permission, exactement comme le catalogue déjà défini dans `SYSTEME_IA.md` §7 — jamais une requête arbitraire sur la base.

Statut : `📋 PLANIFIÉ` — dépend d'abord de l'existence du Financial Core lui-même (rien à analyser sans données réelles).

---

## 19. Sécurité financière — renvoi et spécificités

L'ensemble de `SECURITE.md` s'applique intégralement au Financial Core (RBAC, MFA, step-up auth, isolation multi-tenant, audit, idempotence, gestion des secrets — voir en particulier `SECURITE.md` §9 "Sécurité financière", déjà largement aligné avec ce document). Deux ajouts spécifiques :

### 19.1 Workflows d'approbation financiers

```
DRAFT → SUBMITTED → REVIEW → APPROVED → EXECUTED
```

Sur : grosse dépense, remboursement, achat, salaire, transfert bancaire, changement de compte de règlement. Séparation des responsabilités : celui qui demande n'est jamais celui qui approuve (`SECURITE.md` §6.3).

### 19.2 Limites financières par utilisateur

```
Caissier: payment_limit = 500 $ (configurable par établissement)
Finance:  expense_limit = 5 000 $
```

Au-delà : approbation obligatoire. Contrôlé exclusivement côté backend (jamais une limite affichée/masquée seulement côté interface).

Statut : `📋 PLANIFIÉ`.

---

## 20. Multi-tenant, années scolaires, clôture

Toute donnée financière est liée au tenant — une école A ne voit jamais le solde, les paiements, fournisseurs, salaires, comptes bancaires ou actifs d'une école B (`SECURITE.md` §3).

Les finances sont liées à l'année scolaire (`2025-2026`, `2026-2027`...). Un changement d'année **n'efface jamais l'historique**. Clôture financière prévue architecturalement :

```
OPEN → REVIEW → RECONCILIATION → CLOSE
```

Après clôture, certaines opérations deviennent restreintes ; toute correction post-clôture passe par un ajustement explicite, jamais une réouverture silencieuse.

Statut : `📋 PLANIFIÉ`.

---

## 21. Architecture technique

```
                    FINANCIAL CORE
                          |
       ┌──────────────────┼──────────────────┐
       ↓                  ↓                  ↓
   FACTURATION         PAIEMENTS           DÉPENSES
       ↓                  ↓                  ↓
   CRÉANCES         FOURNISSEURS PAIEMENT   DETTES
       ↓                  ↓                  ↓
       └──────────────────┼──────────────────┘
                          ↓
                       LEDGER
                          ↓
                      TRÉSORERIE
                          ↓
       ┌──────────────────┼──────────────────┐
       ↓                  ↓                  ↓
     BANQUE             CAISSE          MOBILE MONEY
                          |
       ┌──────────────────┼──────────────────┐
       ↓                  ↓                  ↓
      PAIE              ACHATS            ACTIFS
       ↓                  ↓                  ↓
   EMPLOYÉS          FOURNISSEURS         STOCK
                          |
                          ↓
                  RAPPORTS FINANCIERS
                          |
                          ↓
                    ANALYSE IA
```

Cohérent avec l'architecture de sécurité (`SECURITE.md` §28, où le Financial Core n'est qu'un client du même Policy Engine) et l'architecture IA (`SYSTEME_IA.md` §2-3).

---

## 22. Modèles de données (Domain Model)

Entités principales (noms indicatifs, à adapter à la stack retenue) :

```
FinancialAccount · LedgerEntry · FinancialTransaction
Invoice · InvoiceLine · Receivable
Payment · PaymentAllocation · Refund
Expense · ExpenseLine · Payable
Supplier · PurchaseOrder · PurchaseOrderLine
Employee · PayrollPeriod · Payroll · SalaryPayment
BankAccount · CashRegister · MobileMoneyAccount · Transfer
Budget · BudgetLine
Asset · AssetTransaction
InventoryTransaction
FinancialAdjustment · Reconciliation
FinancialDocument
```

### 22.1 Relations principales

```
School → AcademicYear → Student → FinancialProfile → Receivable → Payment → PaymentAllocation → Ledger
School → Supplier → Invoice → Payable → Payment → Ledger
School → Employee → Payroll → SalaryPayment → Ledger
```

Toutes convergent vers le même `LedgerEntry` — aucune branche ne maintient un solde parallèle.

Ce catalogue est désormais codifié en tant que référence dans [assets/js/financial-model.js](../assets/js/financial-model.js) (créé dans ce tour de travail) — documentation des formes de données, **pas de logique fonctionnelle**, exactement dans le même esprit que `permissions.js` pour la sécurité.

Statut : `✅ IMPLÉMENTÉ` en tant que référence codifiée · `⛔ NON APPLIQUÉ` (pas de base de données pour l'incarner).

---

## 23. API — endpoints indicatifs

```
POST /financial/obligations           GET /financial/obligations/:id
POST /payments                        GET /payments/:id
POST /payments/:id/refund
POST /expenses                        POST /expenses/:id/approve
POST /purchases                       POST /purchases/:id/approve
POST /payroll/run                     POST /payroll/:id/approve
POST /treasury/transfers
GET  /financial/dashboard
GET  /financial/reconciliation
```

À adapter à l'architecture backend réelle une fois choisie (section 26) — donné ici comme contrat conceptuel, pas comme spécification figée.

Statut : `📋 PLANIFIÉ`.

---

## 24. Règles métier et invariants

Les règles financières vivent dans le backend/domain layer, jamais uniquement dans le frontend (`if payment > balance` côté client n'est jamais une protection, cf. `SECURITE.md` §14.2).

**Invariants à vérifier en continu (tests de cohérence, section 25) :**

```
TOTAL_ALLOCATED_PAYMENTS ≤ TOTAL_VALID_PAYMENT
ACCOUNT_BALANCE = OPENING_BALANCE + INFLOWS − OUTFLOWS   (selon la nature du compte)
```

Le Financial Core empêche structurellement : solde négatif non autorisé, double paiement, double remboursement, paiement supérieur à l'obligation sans politique explicite (section 6.3), transaction sans tenant, transaction sans devise, suppression d'une transaction confirmée, modification silencieuse, incohérence de solde. Concurrence (deux paiements simultanés sur la même dette, deux webhooks identiques, deux modifications d'une même configuration) gérée par transactions DB atomiques, contraintes d'unicité, idempotence — jamais par un simple espoir que "ça n'arrivera pas".

Statut : `📋 PLANIFIÉ`.

---

## 25. Tests financiers

Scénarios attendus, à automatiser dès que le Financial Core existe :

| # | Scénario | Résultat attendu |
|---|---|---|
| 1 | Paiement normal 250 $ | Dette diminuée de 250 $ |
| 2 | Paiement partiel 250 $ sur dette 500 $ | Solde restant 250 $, statut `PARTIALLY_PAID` |
| 3 | Paiement final complétant le solde | Statut `PAID` |
| 4 | Double paiement simultané (deux requêtes concurrentes) | Une seule opération appliquée, pas de double crédit |
| 5 | Double webhook (même transaction) | Deuxième webhook ignoré (idempotence) |
| 6 | Remboursement 500 $ → 200 $ | Transaction d'origine intacte + `Refund` séparé |
| 7 | Surpaiement (dette 250 $, paiement 300 $) | Politique de surpaiement appliquée, rien perdu |
| 8 | Échec de paiement | Statut `FAILED`, aucun crédit financier |
| 9 | Transaction `UNKNOWN` (coupure réseau) | Aucune perte d'information, vérification différée |
| 10 | Transfert Orange Money → Banque | Trésorerie totale inchangée, pas de faux revenu |
| 11 | Dépense → Cash/Banque | Écriture correcte au Ledger |
| 12 | Salaire → dette salariale → banque | Chaîne complète tracée |
| 13 | Achat de stock → Inventory → Payable | Cohérence stock/finance (section 14) |
| 14 | Achat → Actif immobilisé | Distinction dépense/actif respectée |
| 15 | Facture fournisseur partiellement payée | Dette fournisseur correcte |
| 16 | Écart de caisse (attendu ≠ réel) | Écart signalé, jamais corrigé silencieusement |
| 17 | Multi-tenant | École A ne voit jamais les données de l'école B |

**Tests de cohérence** additionnels sur les invariants de la section 24, à exécuter en continu (pas seulement à la livraison).

Statut : `📋 PLANIFIÉ`.

---

## 26. Roadmap

Cross-référencé avec `OBJECTIFS_ET_FONCTIONNALITES.md` §29-31 (déjà posé) — ce document précise le **comment**, pas seulement le **quoi**.

### MVP
Élèves & obligations, catalogue de frais, échéances, facturation, paiements (cash + un canal électronique), paiements partiels, reçus, caisse, un compte bancaire, Financial Core + Ledger de base, dashboard directeur simple, audit de base, permissions (RBAC de `SECURITE.md`).

### V1
Mobile Money complet + webhooks, rapprochement bancaire, fournisseurs, dépenses, achats, budget, notifications financières, rapports avancés, créances/aging.

### V2
Payroll avancé, actifs, passifs/emprunts, intégration stock-finance complète, trésorerie prévisionnelle, IA financière avancée (anomalies, prévisions, copilot).

### Plus tard
Comptabilité réglementaire (mapping vers un plan comptable légal), fiscalité locale, intégrations bancaires avancées, multi-pays, consolidation multi-établissements, prévisions financières avancées.

**Rappel du garde-fou (point 91) :** chaque étape ci-dessus n'active que les *fonctionnalités*, jamais toute l'*architecture* d'un coup — celle-ci (ce document) est conçue pour la vision complète dès maintenant, mais le code n'implémente que ce que l'étape courante exige réellement.

---

## Annexe A — Modèles de données (détail des champs clés déjà donné section 22)

Voir [assets/js/financial-model.js](../assets/js/financial-model.js) pour la version codifiée.

## Annexe B — Principes non négociables

Voir section 1 — à ne jamais contredire dans une décision d'implémentation future.

## Annexe C — Légende de statut

Identique à `SECURITE.md` Annexe C : `✅ IMPLÉMENTÉ` · `🟡 PARTIEL` · `📋 PLANIFIÉ` · `⛔ NON IMPLÉMENTÉ` · `🔌 FOURNISSEUR EXTERNE`.

## Annexe D — Ce que ce tour de travail a réellement ajouté au code

- Ce document.
- [assets/js/financial-model.js](../assets/js/financial-model.js) — catalogue codifié des entités du domaine financier (section 22), en pur JSDoc/commentaires, **aucune logique exécutable** — ne calcule rien, ne stocke rien, ne remplace aucun affichage existant du prototype. Sert de référence pour le futur backend, exactement comme `permissions.js` pour la sécurité.
- Aucune autre modification du code existant : les valeurs financières déjà affichées dans le prototype (`app.js`, `index.html`) restent des maquettes statiques inchangées — les remplacer par de vraies lectures du Financial Core n'a de sens qu'une fois ce dernier construit (section 16.1).
