# KLASSIO — Moteur d'Import et de Bootstrap Automatique
### Spécification V0.1 — School Data Ingestion & Bootstrap Engine

Ce document complète [OBJECTIFS_ET_FONCTIONNALITES.md](OBJECTIFS_ET_FONCTIONNALITES.md) (§6, import intelligent déjà posé dans la vision produit), [SYSTEME_IA.md](SYSTEME_IA.md) (§10.7 Assistant Excel, §12.2 prompt injection), [SECURITE.md](SECURITE.md) (§17 sécurité des fichiers) et [FINANCE.md](FINANCE.md) (le Financial Core comme unique destination des données financières importées). Aucun de ces documents n'est dupliqué ici — ils sont référencés.

## 0. État réel du projet

Inspection effectuée avant d'écrire ce document : toujours aucun backend, aucun parseur de fichier, aucun moteur d'IA connecté. Le seul artefact existant touchant l'import est un **mockup visuel** dans [app/inscription.html](../app/inscription.html) (étape 3, bouton *"Importer un fichier existant"*) — un aperçu illustratif à 5 étapes (`Envoi → Analyse → Mapping → Validation → Espace créé`) sans logique réelle, construit lors d'une session précédente pour incarner visuellement l'idée. Ce document en est le prolongement conceptuel complet : le pipeline réel (section 4) compte 20 étapes ; les 5 étapes déjà à l'écran en sont un résumé grand public, pas une simplification technique à corriger — un directeur n'a pas besoin de voir 20 étapes, il a besoin de comprendre que le système regarde, comprend, vérifie, puis construit.

Légende de statut (identique à `SECURITE.md`/`FINANCE.md`) : `✅ IMPLÉMENTÉ` · `🟡 PARTIEL` · `📋 PLANIFIÉ` · `⛔ NON IMPLÉMENTÉ` · `🔌 FOURNISSEUR EXTERNE`. Comme pour les deux documents précédents, l'écrasante majorité de ce qui suit est `📋 PLANIFIÉ` — il n'y a pas encore de backend pour l'exécuter.

---

## 1. Principes non négociables

1. L'import n'écrit jamais directement en base sans validation humaine sur les points ambigus.
2. L'IA propose, elle ne décide jamais seule.
3. Les règles métier restent déterministes — jamais déléguées à un modèle de langage.
4. Les données originales sont préservées (`RAW` vs `NORMALIZED`, section 8).
5. Toute donnée importée a une provenance retraçable (section 15.3).
6. Les données financières passent obligatoirement par le Financial Core (`FINANCE.md`) — aucune logique financière parallèle pour les imports.
7. Aucun montant, aucune date, aucune référence n'est inventée.
8. Aucune fusion automatique de deux élèves en cas d'ambiguïté importante.
9. Isolation totale entre établissements (`SECURITE.md` §3).
10. Un import est traçable et, dans la mesure du possible, réversible.
11. Toute erreur est visible avant l'import final — jamais découverte après coup.
12. Le système sait dire *"je ne sais pas"* plutôt que de deviner à tort.
13. La confiance de l'IA est mesurable, jamais implicite.
14. Un import successif met à jour sans écraser aveuglément (section 13).
15. Une erreur d'import ne corrompt jamais silencieusement le Financial Core.
16. L'objectif est de reconstruire la **structure logique** de l'établissement, pas seulement d'insérer des lignes.
17. L'utilisateur comprend ce qui va être créé avant de confirmer.

---

## 2. Vision : de l'upload à la compréhension

Ce que ce moteur n'est **pas** :

```
Upload Excel → read rows → insert database
```

Ce qu'il est :

```
RAW DATA → COMPRÉHENSION → INTERPRÉTATION → NORMALISATION → VALIDATION → CONTRÔLE → IMPORT
```

Chaque établissement organise ses fichiers différemment (`NOM COMPLET / CLASSE / CONTACT PARENT / FRAIS ANNUELS...` chez l'un, `Élève / Classe / Téléphone / Montant à payer...` chez un autre) — le moteur doit comprendre l'**intention** derrière chaque colonne, pas exiger un format unique.

---

## 3. Le concept de "matière première de l'établissement"

L'import n'est pas une liste de lignes à insérer — c'est la matière première qui permet de **construire** l'environnement complet :

```
students.xlsx
     ↓
ÉTABLISSEMENT → ANNÉE SCOLAIRE → NIVEAUX → CLASSES → ÉLÈVES
              → RESPONSABLES → DOSSIERS FINANCIERS → OBLIGATIONS
              → PAIEMENTS → SOLDES
```

Objectif ressenti par le directeur : *"Le système a compris mon école"* — jamais *"je dois configurer une base de données"*.

---

## 4. Pipeline complet

```
DOCUMENT → UPLOAD → FILE ANALYSIS → STRUCTURE DETECTION → AI UNDERSTANDING
         → COLUMN/FIELD MAPPING → DATA NORMALIZATION → VALIDATION
         → DUPLICATE DETECTION → BUSINESS RULE VALIDATION → ANOMALY DETECTION
         → PREVIEW → USER CONFIRMATION → IMPORT → RELATIONSHIP BUILDING
         → FINANCIAL RECONSTRUCTION → ENVIRONMENT CREATION
         → POST-IMPORT VERIFICATION → AUDIT
```

| Étape | Rôle | Détaillée en |
|---|---|---|
| File analysis / structure detection | Comprendre feuilles, colonnes, types, formats | Section 7 |
| AI understanding / column mapping | Proposer une correspondance colonne → champ Klassio, avec confiance | Section 7, `SYSTEME_IA.md` §10.7 |
| Data normalization | Uniformiser classes, noms, téléphones, devises, années | Section 8 |
| Validation | Structure, données, relations, finance, sécurité | Section 12 |
| Duplicate detection | Exact / fort / possible, avec ou sans identifiant | Section 9 |
| Anomaly detection | Incohérences financières et structurelles | Section 11 |
| Preview / dry run | Simulation sans écriture, résumé compréhensible | Section 13 |
| User confirmation | Rien n'est définitif avant ce point | Section 13-14 |
| Import / relationship building / financial reconstruction | Écriture réelle, via le Financial Core pour tout ce qui est financier | Section 10, 16 |
| Environment creation | Le dashboard du directeur devient immédiatement opérationnel | Section 15.4 |
| Post-import verification / audit | Vérification et traçabilité complète | Section 15, 23 |

---

## 5. Expérience utilisateur cible

```
1. Importez les données de votre établissement.          [Importer un fichier]
2. Analyse : « Nous avons trouvé 1 284 élèves, 32 classes, 1 107 responsables… »
3. Explication de ce qui a été compris (chiffres clés)
4. Signalement : doublons potentiels, classes non reconnues, numéros incomplets…
5. L'utilisateur corrige ou accepte
6. « Voici ce qui sera créé » (résumé complet, section 13)
7. Confirmation : [Créer mon établissement]
```

Le mockup déjà construit dans `app/inscription.html` incarne visuellement les étapes 1, 2 et 7 pour un directeur qui découvre le produit — les étapes 3 à 6 (le cœur du travail de compréhension et de correction) restent à construire une fois le moteur réel disponible ; elles n'ont pas de sens à simuler sans données réelles à analyser.

---

## 6. Multi-fichiers et matching inter-fichiers

Le système accepte plusieurs fichiers représentant des parties différentes du même établissement (`students.xlsx` + `payments.xlsx` + `parents.xlsx` + `classes.xlsx` + `inventory.xlsx`) et les relie :

```
students.xlsx  +  payments.xlsx  →  MATCH  →  Student + FinancialProfile unifiés
```

Le rapprochement suit la même logique que le matching intra-fichier (section 9) : identifiant fiable en priorité, sinon combinaison contrôlée de champs avec score de confiance.

---

## 7. Reconnaissance de structure et mapping assisté par IA

Analyse de : noms de feuilles, colonnes, types de données, valeurs, formats, répétitions, relations potentielles, identifiants, montants, dates, catégories. L'IA propose un mapping avec un **niveau de confiance explicite** — jamais une certitude implicite :

```
"Classe"      → Class.name              confiance 99%
"Contact"     → Guardian.phone          confiance 94%
"Versement 1" → Payment installment     confiance 86%
```

**Explication des décisions IA (obligatoire, pas cosmétique)** : *« Nous pensons que "VERS 1" correspond à la première échéance parce que cette colonne contient des montants monétaires et apparaît à côté de "TOTAL FRAIS". »* — l'utilisateur doit pouvoir comprendre le raisonnement, pas seulement accepter un pourcentage.

**Architecture (renvoi `SYSTEME_IA.md` §2, §6, §10.7) :** `FILE → PARSER → NORMALIZATION → AI MAPPING → VALIDATION ENGINE → BUSINESS RULES → PREVIEW → USER CONFIRMATION → IMPORT SERVICE → DATABASE`. L'IA n'a jamais d'accès direct à la base — elle ne fait que proposer un mapping consommé ensuite par le Validation Engine (section 12), déterministe.

Statut : `📋 PLANIFIÉ`.

---

## 8. Normalisation — sans destruction des données originales

Principe central : conserver systématiquement `RAW_VALUE` et `NORMALIZED_VALUE` séparément — jamais un remplacement qui efface l'original.

```
RAW: "6ème-A" / "6e A" / "6 A" / "6EME-A"   →   NORMALIZED: "6e A"
```

Mais **aucune fusion automatique** de deux valeurs simplement parce qu'elles se ressemblent — règles + contexte + similarité + IA, et confirmation humaine si ambigu (cohérent avec le Confidence Engine, section 14).

| Donnée | Règles de normalisation | Jamais |
|---|---|---|
| Noms d'élèves | Nom/postnom/prénom, casse, espaces, caractères spéciaux | Deviner une orthographe |
| Téléphones | Formats `+243...` / `243...` / `08...` selon config établissement | Inventer un numéro |
| Emails | Casse, espaces, format | Corriger un domaine à la place de l'utilisateur |
| Classes | Détection niveau + section (`6e` + `A`) | Fusionner deux classes proches sans confirmation |
| Année scolaire | `2025-2026` / `2025/2026` → forme unique | Créer deux années identiques sous des formats différents |
| Devises | `$` / `USD` / `US$` / `CDF` / `FC` / `FCFA` | Supposer une devise par défaut si ambigu — toujours "devise à confirmer" |

Statut : `📋 PLANIFIÉ`.

---

## 9. Détection de doublons et matching

| Type | Définition | Action |
|---|---|---|
| Exact duplicate | Même identifiant | Fusion automatique possible |
| Strong duplicate | Même nom + date de naissance + classe + responsable | Proposition de fusion, confirmation rapide |
| Possible duplicate | Noms très similaires, infos partiellement partagées | Vérification humaine obligatoire |

Exemple de garde-fou explicite : `MUKENDI JEAN` et `MUKENDI  JEAN` (espace en trop) peuvent être la même personne ; `MUKENDI JEAN` et `MUKENDI JEAN-PIERRE` **ne doivent jamais** être fusionnés automatiquement.

**Matching entre fichiers/imports :**
- Avec identifiant fiable (matricule, ID interne) : utilisé en priorité comme clé de rapprochement.
- Sans identifiant : combinaison contrôlée `nom + classe + responsable + téléphone + date de naissance`, avec score de confiance (ex. `98%`) — en dessous du seuil, vérification requise (section 14).

Statut : `📋 PLANIFIÉ`.

---

## 10. Reconstruction financière — obligatoirement via le Financial Core

Si le fichier indique `Frais annuels 1000 $ / Payé 650 $ / Reste 350 $`, le système ne se contente pas d'importer `balance = 350` : il **reconstruit la structure** dès que les données le permettent :

```
OBLIGATION 1000 $  →  PAYMENTS 650 $  →  BALANCE 350 $ (dérivé, jamais stocké seul)
```

Échéances (`Tranche 1..4`) reconstruites en `Installment` avec montant, date si disponible, statut. Paiements historiques (`Septembre 200 / Octobre 150...`) recréés comme transactions individuelles lorsque l'information est suffisamment fiable — chacune porte date (si disponible), montant, étudiant, référence (si disponible), méthode (si disponible), **source = import**, statut d'import.

**Ne jamais inventer (principe absolu) :** si le fichier ne donne pas de date, de méthode, de référence ou de devise, le système ne les invente pas — il marque le paiement `historical imported payment / date unknown` ou déclenche une demande de correction, selon la règle configurée. Toute cette reconstruction passe par les entités déjà définies dans `FINANCE.md` §6 (`Receivable`), §7 (`Payment`) — **aucune logique financière parallèle spécifique à l'import**.

Statut : `📋 PLANIFIÉ`.

---

## 11. Détection d'anomalies

Exemples : `Paid > Total Due`, `Balance < 0`, paiement négatif, paiement dupliqué, paiement sans élève identifiable, obligation sans élève, devise inconnue, classe inconnue, élève dans plusieurs classes.

Chaque anomalie porte une sévérité :
```
INFO · WARNING · ERROR · CRITICAL
```

Cohérent avec `SYSTEME_IA.md` §10.8 : l'IA **signale**, jamais n'affirme une fraude sans preuve humaine.

Statut : `📋 PLANIFIÉ`.

---

## 12. Validation Engine

Vérifie, avant tout import réel :

| Dimension | Contrôles |
|---|---|
| Structure | Colonnes, types, feuilles reconnues |
| Données | Valeurs, formats, champs obligatoires présents |
| Relations | Élève → classe, élève → responsable, paiement → élève, paiement → obligation |
| Finance | Montants, devises, soldes, cohérence des paiements (renvoi `FINANCE.md` §24, invariants) |
| Sécurité | Fichier, contenu, taille, permissions (renvoi `SECURITE.md` §17.1) |

**Aucune relation orpheline créée silencieusement** (section 57 de votre brief) : chaque relation est vérifiée avant l'écriture finale.

Statut : `📋 PLANIFIÉ`.

---

## 13. Preview et Dry Run

Avant toute écriture définitive, un résumé humainement lisible :

```
RÉSUMÉ D'IMPORT
1 284 élèves · 32 classes · 1 107 responsables · 3 842 informations financières

18 doublons possibles · 7 classes non reconnues · 12 téléphones incomplets · 5 élèves sans classe

CE QUI SERA CRÉÉ
École: 1 · Année scolaire: 1 · Niveaux: 4 · Classes: 32
Élèves: 1 284 · Responsables: 1 107 · Dossiers financiers: 1 284 · Obligations: …
```

Mode **Dry Run** : simule l'import complet sans toucher la base — répond exactement à *"si j'importe ce fichier, voici ce qui sera créé"*, avant tout engagement. Boutons de sortie : `Retour · Corriger · Importer`.

Statut : `📋 PLANIFIÉ`.

---

## 14. Confidence Engine et Human-in-the-loop

```
95–100 %  → automatique
85–94 %   → proposition + validation rapide
60–84 %   → validation obligatoire
< 60 %    → pas d'interprétation automatique
```

Seuils **configurables par établissement**. Le système doit savoir dire *"je ne suis pas suffisamment certain"* plutôt que de mal importer — exemple : *"Cette colonne peut représenter le montant payé ou le montant restant. Confirmation requise."* avec des boutons de choix explicites, jamais une case cochée par défaut qui inciterait à accepter sans lire.

Statut : `📋 PLANIFIÉ`.

---

## 15. Import Job — cycle de vie et traçabilité

### 15.1 États

```
UPLOADED → ANALYZING → MAPPING → VALIDATING → READY
        → IMPORTING → COMPLETED / PARTIAL / FAILED / ROLLED_BACK
```

### 15.2 Journal d'import

Chaque `ImportJob` conserve : fichier source, utilisateur, date, taille, nombre de lignes, mapping utilisé, résultats, erreurs, avertissements, objets créés/modifiés — exactement comme un `AuditLog` financier (`SECURITE.md` §11, `FINANCE.md` §17), spécialisé pour l'import.

### 15.3 Provenance des données

```
Élève → créé par Import #IMP-2026-00042 → source: students.xlsx → feuille: Liste élèves → ligne: 284
```

Répond à *"d'où vient cette donnée ?"* et *"quel import a créé cet élève ?"* — essentiel pour le debugging et l'audit, jamais optionnel pour les données financières.

### 15.4 Conservation du fichier original

Référence sécurisée conservée quand c'est légalement et techniquement approprié — jamais rendue publiquement accessible (mêmes règles que les documents financiers, `SECURITE.md` §17.2).

Statut : `📋 PLANIFIÉ`.

---

## 16. Exécution — batch, atomicité, rollback

### 16.1 Volumétrie

Conçu pour 500 à 10 000+ élèves — jamais pour seulement 100 lignes en test. Traitement par lots, file d'attente en tâche de fond, suivi de progression réel (jamais une fausse barre de progression), reprise après échec partiel.

### 16.2 Atomicité et rollback

```
START → VALIDATE → IMPORT → VERIFY → COMMIT
```

Erreur critique → `ROLLBACK` lorsque techniquement possible — jamais un établissement à moitié créé sans contrôle. Rollback d'un import déjà confirmé : identifier précisément les objets créés/modifiés par cet import ; **si des données importées ont ensuite servi à de nouvelles opérations financières, ne pas les supprimer aveuglément** — le rollback doit être une opération financière compensatoire (cohérent avec `FINANCE.md` §5, jamais un `DELETE`).

### 16.3 Import partiel

Si 1 266 élèves sur 1 284 sont valides, ils peuvent être importés pendant que les 18 problématiques restent en attente de correction — **sauf** si cela créerait une incohérence relationnelle (ex. un paiement référence un élève encore en attente).

Statut : `📋 PLANIFIÉ`.

---

## 17. Imports de mise à jour (upsert contrôlé)

L'import n'est pas réservé au premier onboarding — un fichier mensuel (`payments_september.xlsx`) doit être reconnu comme une mise à jour, pas recréer les élèves existants.

```
CREATE · UPDATE · SKIP · REVIEW
```

Exemple : téléphone changé → `UPDATE` proposé ; nom complètement différent → `REVIEW` obligatoire, jamais un écrasement silencieux. **Conflit détecté** (ex. numéro différent entre système et Excel) → l'utilisateur choisit explicitely `Conserver l'existant / Utiliser l'importé / Vérifier manuellement`.

**Règle absolue sur la donnée financière (renvoi `FINANCE.md` §1, §5) :** un nouvel import ne doit **jamais** écraser silencieusement l'historique de paiement, les soldes, les remboursements ou les transactions existantes — toute mise à jour financière passe par le Financial Core, jamais par une écriture directe de l'import.

Statut : `📋 PLANIFIÉ`.

---

## 18. Formats de fichiers

Priorité : `XLSX`, `CSV`. Ensuite, éventuellement : `ODS`, `PDF`, `DOCX`. Pour les documents non structurés (PDF/scan) :

```
DOCUMENT → OCR/PARSING → EXTRACTION → CONFIANCE → VALIDATION
```

Un PDF complexe n'est **jamais** traité comme un Excel structuré — stratégie dédiée, confiance généralement plus basse, validation humaine plus fréquente. IA multimodale (texte + tableaux + structure de feuilles, éventuellement images) étudiée si le fournisseur IA le permet (`SYSTEME_IA.md` §13), mais toujours soumise aux mêmes règles de validation — jamais un raccourci de confiance.

Statut : `📋 PLANIFIÉ` · OCR/multimodal `🔌 FOURNISSEUR EXTERNE` si retenu.

---

## 19. Mapping réutilisable et templates

Si un établissement réutilise toujours le même format (`students_2026.xlsx`, `students_2027.xlsx`), le mapping validé une première fois peut être mémorisé et reconnu automatiquement au prochain import — accélère considérablement les imports récurrents. Des templates standards (élèves, paiements, inventaire, employés) peuvent être proposés, **sans jamais obliger** une école à les utiliser si son propre fichier reste interprétable.

Statut : `📋 PLANIFIÉ`.

---

## 20. Sécurité de l'import

Application intégrale de `SECURITE.md`, en particulier §17.1 (upload/Excel) et §3 (isolation multi-tenant) — pas de règle spéciale pour l'import. Permissions dédiées, cohérentes avec le catalogue `permissions.js` :

```
imports.create · imports.review · imports.execute · imports.rollback · imports.read
```

**Prompt injection (renvoi `SYSTEME_IA.md` §12.2) :** une cellule contenant `"Ignore previous instructions..."` reste une **valeur de cellule**, jamais une instruction pour l'IA — le contenu du fichier est toujours traité comme donnée à analyser, séparé strictement des instructions système du moteur de mapping.

**Confidentialité et rétention :** stockage sécurisé, accès limité et audité, isolation tenant stricte (un fichier importé n'est jamais visible par un autre établissement), durée de conservation distincte pour le fichier original vs les logs vs les données extraites — à définir explicitement par établissement plutôt que supposée indéfinie.

Statut : `📋 PLANIFIÉ`.

---

## 21. Post-import : vérification, rapport, qualité des données

### 21.1 Vérification post-import

Recompte indépendant après écriture : nombre de classes, élèves, responsables, obligations, paiements, soldes, relations, doublons résiduels, erreurs — pour confirmer que ce qui a été **réellement créé** correspond à ce qui avait été **annoncé** en preview (section 13).

### 21.2 Rapport final

```
IMPORT TERMINÉ
Élèves créés: 1 284 · Classes créées: 32 · Responsables créés: 1 107
Dossiers financiers: 1 284 · Obligations: 3 201 · Paiements historiques: 5 842
Avertissements: 18 · Erreurs: 0
```

### 21.3 Score de qualité des données

```
QUALITÉ DES DONNÉES: 92 %
```

Basé sur : complétude, doublons résiduels, erreurs, cohérence relationnelle, validité des téléphones/emails, cohérence financière — **toujours explicable** (ex. *"5 % de téléphones responsables manquants, 2 % de doublons candidats, 1 % de données financières incomplètes"*), jamais un chiffre arbitraire sans détail (cohérent avec `SYSTEME_IA.md` §10.4, principe de prudence des formulations IA).

Statut : `📋 PLANIFIÉ`.

---

## 22. Architecture technique

```
                    UPLOAD DE FICHIER
                          ↓
                   SÉCURITÉ FICHIER
                          ↓
                    PARSEUR FICHIER
                          ↓
                ANALYSEUR DE STRUCTURE
                          ↓
                    NORMALISATION
                          ↓
                MOTEUR DE MAPPING IA
                          ↓
                MOTEUR DE VALIDATION
                          ↓
                MOTEUR DE DOUBLONS
                          ↓
              MOTEUR DE RÈGLES MÉTIER
                          ↓
                MOTEUR D'ANOMALIES
                          ↓
                       PREVIEW
                          ↓
              CONFIRMATION HUMAINE
                          ↓
              ORCHESTRATEUR D'IMPORT
                          ↓
       ┌─────────────────┼─────────────────┐
       ↓                 ↓                 ↓
     ÉLÈVES           FINANCE            CLASSES
       ↓                 ↓                 ↓
  RESPONSABLES       OBLIGATIONS        STRUCTURE
       ↓                 ↓                 ↓
       └─────────────────┼─────────────────┘
                          ↓
                     BASE DE DONNÉES
                          ↓
                VÉRIFICATION POST-IMPORT
                          ↓
                        AUDIT
```

La branche `FINANCE` de cet orchestrateur **est** le Financial Core de `FINANCE.md` — pas une copie, pas un moteur parallèle.

---

## 23. Modèles de données

```
ImportJob · ImportFile · ImportSheet · ImportColumn · ImportMapping
ImportRecord · ImportError · ImportWarning · ImportConflict
ImportPreview · ImportResult · ImportRollback
DataSource · DataProvenance
```

Codifié en référence dans [assets/js/import-model.js](../assets/js/import-model.js) (créé dans ce tour de travail), même esprit que `permissions.js` et `financial-model.js` — catalogue de formes de données et d'états, aucune logique exécutable.

Statut : `✅ IMPLÉMENTÉ` en tant que référence codifiée · `⛔ NON APPLIQUÉ`.

---

## 24. API — endpoints indicatifs

```
POST /imports                    POST /imports/:id/analyze
POST /imports/:id/map            POST /imports/:id/validate
GET  /imports/:id/preview        POST /imports/:id/confirm
POST /imports/:id/rollback       GET  /imports/:id/report
```

À adapter à l'architecture backend réelle une fois choisie — contrat conceptuel, pas figé.

Statut : `📋 PLANIFIÉ`.

---

## 25. Tests

### 25.1 Tests fonctionnels

Excel simple (100 élèves), Excel complexe (10 feuilles), colonnes inconnues ou en langue étrangère, noms/classes hétérogènes, doublons, paiements historiques et partiels, multi-fichiers, données contradictoires, fichier vide/corrompu/énorme, mauvais format, contenu malveillant, **prompt injection dans une cellule** (section 20), import interrompu, rollback, import partiel, deux imports simultanés, import vers le mauvais tenant, utilisateur sans permission.

### 25.2 Tests financiers de l'import (critiques)

```
Total obligation − Paiements alloués = Solde restant
1 000 − 650 = 350
```

Le système doit retrouver **exactement** la situation financière d'origine. Couvrir aussi : surpaiement, paiement partiel, paiements non identifiés, paiements sans date/méthode, obligation sans paiement, paiement supérieur à l'obligation — chacun avec le comportement attendu déjà défini dans `FINANCE.md` §25.

### 25.3 Import et année scolaire

Importer `2025-2026` puis `2026-2027` ne doit jamais fusionner les obligations des deux années — historique strictement séparé (`FINANCE.md` §20).

Statut : `📋 PLANIFIÉ`.

---

## 26. Roadmap

### MVP
Upload XLSX/CSV, analyse de structure de base, mapping IA avec confiance, validation structurelle et relationnelle, détection de doublons simple, preview + confirmation obligatoire, création établissement/classes/élèves/responsables/dossiers financiers de base — tout passant par le Financial Core.

### V1
Dry run complet, détection d'anomalies financières avancée, multi-fichiers avec matching inter-fichiers, mapping réutilisable, import de mise à jour (upsert contrôlé), rollback, batch/queue pour gros volumes, error center avec corrections groupées.

### V2
Templates d'import, score de qualité des données explicable, provenance complète exposée à l'utilisateur, reconstruction financière avancée (échéances complexes, paiements historiques multi-devises).

### Plus tard
OCR/PDF, IA multimodale, imports depuis d'autres systèmes scolaires via API, consolidation multi-établissements.

---

## Annexe A — Ce que ce tour de travail a ajouté au code

- Ce document.
- [assets/js/import-model.js](../assets/js/import-model.js) — catalogue codifié des entités et états du moteur d'import (section 23), pure référence, aucune logique exécutable, non chargé par aucune page.
- Aucune modification du mockup existant dans `app/inscription.html` : ses 5 étapes illustratives restent une simplification volontaire et cohérente du pipeline complet (section 4) pour un public non technique — voir section 5.

## Annexe B — Légende de statut

Identique à `SECURITE.md`/`FINANCE.md` Annexe C.
