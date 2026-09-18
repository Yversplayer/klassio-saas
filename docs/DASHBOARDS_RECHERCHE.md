# KLASSIO — Dashboards, Recherche Globale et Command Bar Intelligente
### Spécification V0.1 — Dashboard, Global Search & Intelligent Command System

Ce document s'appuie sur [SYSTEME_IA.md](SYSTEME_IA.md) (dont le principe "pas de chatbot" §1.1 est directement confirmé et détaillé ici), [EVENEMENTS.md](EVENEMENTS.md) (le dashboard est un consommateur du bus d'événements), [FINANCE.md](FINANCE.md) (le dashboard n'est jamais une source de vérité financière), [MULTI_TENANT.md](MULTI_TENANT.md) (isolation de la recherche et du dashboard) et [SECURITE.md](SECURITE.md) (permissions). Rien n'y est dupliqué.

## 0. État réel du projet — nuance importante

Contrairement aux six documents précédents, ce sujet a déjà une **implémentation visuelle partielle**, construite lors d'une session antérieure : [app/dashboard.html](../app/dashboard.html) affiche un dashboard par rôle (Directeur/Professeur/Parent/Élève) avec une barre centrale *"Que souhaitez-vous faire ?"*, une réponse qui apparaît en ligne sous la barre, et une carte d'insight ambiante — **exactement le motif visuel décrit dans ce brief**. Il faut cependant être précis sur ce que c'est réellement, pour ne pas se raconter d'histoire :

- La barre de recherche affiche **toujours la même réponse pré-écrite** pour le rôle courant, quel que soit le texte tapé (`assets/js/app.js`, `DASH_CONTENT[role].answer`) — ce n'est **pas** un Intent Engine, c'est une maquette du *motif d'interaction*.
- L'insight ambiant est un texte statique par rôle, pas un calcul réel sur des données.
- Les "actions rapides" (`quick-card`) sont des boutons **sans handler** — purement visuels.
- Le rôle vient de `localStorage`/paramètre d'URL, pas d'une authentification réelle.

**Ce que cela signifie pour ce document :** la *forme* de l'expérience (§6 "Command Bar ≠ chatbot", §21-24 dashboards par rôle) est déjà validée visuellement et **ne doit pas être reconstruite** — ce document en documente précisément le contrat pour qu'une implémentation réelle (Intent Engine, Context Engine, Permission Engine, vraies données) vienne l'alimenter sans changer son apparence. Légende de statut : `✅ IMPLÉMENTÉ` · `🟡 PARTIEL` (le cas de la maquette ci-dessus) · `📋 PLANIFIÉ` · `⛔ NON IMPLÉMENTÉ` · `🔌 FOURNISSEUR EXTERNE`.

---

## 1. Vision UX et philosophie produit

*Complexité derrière. Simplicité devant.* Le dashboard n'est pas une page de statistiques — c'est un **espace de travail personnel** qui répond à trois questions en un coup d'œil : *Où suis-je ? Qu'est-ce qui est important maintenant ? Que puis-je faire maintenant ?* L'utilisateur ne doit jamais avoir besoin d'apprendre l'architecture du logiciel — c'est le logiciel qui s'adapte à ce que l'utilisateur cherche à faire.

---

## 2. Architecture des dashboards par rôle

Quatre expériences distinctes, déjà incarnées dans le prototype (`app/dashboard.html`, sélection de rôle via `ROLE_MENUS`/`DASH_CONTENT` dans `app.js`) :

| Rôle | Ton | Densité | Statut prototype |
|---|---|---|---|
| Directeur | Formel, orienté décision | Situation financière + à surveiller + activité + insight | 🟡 Partiel (maquette visuelle) |
| Enseignant | Pratique, pédagogique | Classes, présences, à faire | 🟡 Partiel |
| Parent | Rassurant, simple | Enfant(s), échéances, dernière activité | 🟡 Partiel |
| Élève | Minimal | Cours du jour, à faire, informations | 🟡 Partiel |

Un dashboard n'affiche jamais un bloc vide "au cas où" — la composition change selon la situation réelle (section 4).

---

## 3. Dashboard Directeur

Structure retenue, dynamique par nature :

```
Bonjour, [Nom]. Voici ce qui mérite votre attention aujourd'hui.
[ Que souhaitez-vous faire ? ]                    ← Command Bar (section 6)
Situation financière : Recettes · Impayés · Trésorerie
À surveiller | Activité récente                    ← contenu variable (section 13)
Insights / recommandations IA                       ← jamais inventé (section 13.3)
```

**Dynamisme réel, pas cosmétique** : si aucune anomalie n'existe, *"À surveiller"* affiche *"Situation stable"*, jamais un bloc vide ou un placeholder générique ; si une anomalie financière existe, elle prend la priorité visuelle sur le bloc (cohérent avec l'Information Priority Engine, section 13.1). Jamais 50 cartes simultanées — la composition est choisie, pas empilée.

Statut : `🟡 PARTIEL` (structure visuelle construite avec des chiffres fixes ; la logique de dynamisme réelle — section/bloc qui apparaît ou disparaît selon la situation — reste `📋 PLANIFIÉ`).

---

## 4. Dashboard Enseignant, Parent, Élève

**Enseignant** : classes du jour, présences attendues/enregistrées, à faire pédagogique — jamais de donnée financière sensible des familles (`SECURITE.md` §7).

**Parent — gestion multi-enfants** : sélecteur de contexte explicite (`Tous les enfants / Jean / Marie / Paul`) ; une fois un enfant sélectionné, **toutes** les informations affichées concernent cet enfant seul, jamais un mélange (cohérent avec `MULTI_TENANT.md` §4 sur la contextualisation stricte des identités). Le principe est identique à un changement de tenant (`MULTI_TENANT.md` §7.1) mais à l'échelle d'un enfant plutôt que d'une école : changement explicite, jamais déduit.

**Élève** : cours du jour, devoirs, informations — le contenu financier visible dépend strictement de la politique de l'établissement (feature flag, `MULTI_TENANT.md` §19.2), jamais d'un défaut permissif.

Statut : `🟡 PARTIEL` (mêmes réserves que section 3).

---

## 5. La Command Bar — "Que souhaitez-vous faire ?"

### 5.1 Ce que c'est, et ce que ce n'est pas

**Confirmation directe d'un principe déjà posé** (`SYSTEME_IA.md` §1.1) : la Command Bar n'est **jamais** une fenêtre de chat. C'est une interface hybride `SEARCH + COMMAND + LANGAGE NATUREL + ASSISTANCE IA` — une saisie, une réponse en ligne, pas de fil de conversation persistant, pas de bouton flottant qui ouvre un panneau. Réponse à la question 1 de votre brief (section 26 ci-dessous) : **combinaison des trois, jamais un chatbot**, exactement le motif déjà construit dans `app/dashboard.html`.

### 5.2 Suggestions personnalisées

Au clic dans la barre, avant toute saisie, des exemples adaptés au rôle (déjà esquissés par role dans `DASH_CONTENT[role].search` du prototype, à titre de *placeholder* — les vraies suggestions contextuelles restent à construire) : le directeur voit *"Voir les impayés"*, le parent voit *"Voir mes paiements"*, etc.

### 5.3 Raccourcis

`Ctrl/Cmd+K` sur desktop pour ouvrir/focaliser la barre ; tap direct sur mobile — pas de raccourcis additionnels inutiles (cohérent avec le principe de sobriété du produit).

Statut : `🟡 PARTIEL` (le champ existe et affiche une réponse ; les suggestions dynamiques et le raccourci clavier sont `📋 PLANIFIÉ`).

---

## 6. Intent Engine

### 6.1 Architecture — l'IA ne décide jamais seule

```
Utilisateur → Command Bar → Compréhension IA → Intention structurée
   → Permission Engine → Validation → Outil métier autorisé → Résultat
```

Jamais `User → IA → Database`. Exactement l'architecture déjà posée dans `SYSTEME_IA.md` §2 — cette Command Bar est l'un des points d'entrée de cet orchestrateur, pas un système parallèle.

### 6.2 Exemple de transformation

```
"Montre-moi les élèves de 6e A qui doivent encore payer septembre."
   ↓
{
  "intent": "students.search",
  "tenant_id": "<résolu côté serveur, jamais dans le texte>",
  "filters": { "class": "6e A", "financial_status": "unpaid", "period": "September" }
}
```

L'IA produit l'intention structurée ; elle ne l'exécute jamais elle-même — l'outil `search_students()` (section 12) est appelé par le backend, après vérification de permission.

Statut : `📋 PLANIFIÉ`.

---

## 7. Context Engine

Fournit à l'Intent Engine, uniquement ce que la permission autorise : utilisateur courant, rôle, tenant (`MULTI_TENANT.md` §7), année scolaire active, **page/entité courante** (déterminant pour la désambiguïsation, section 9), filtres actifs, permissions résolues, activité récente, événements pertinents (`EVENEMENTS.md` §16.5).

**Exemples de résolution contextuelle** (repris de votre brief, déjà cohérents avec `SYSTEME_IA.md` §5) :
- Sur l'écran `Finance`, *"Montre-moi les retards"* → retards **financiers**, jamais de présence.
- Sur l'écran `6e A`, *"Qui n'a pas payé ?"* → élèves de 6e A + impayés, filtre de classe implicite.
- Dans le dossier d'un élève, *"Que reste-t-il à payer ?"* → solde de cet élève précisément, sans reformuler la question.

Statut : `📋 PLANIFIÉ`.

---

## 8. Recherche — deux niveaux

| Niveau | Nature | Exemple |
|---|---|---|
| 1 — Déterministe | Rapide, exact | Nom, matricule, téléphone, classe, facture, transaction |
| 2 — Naturelle | Interprétée par l'IA, exécutée par le backend | *"Les élèves qui ont payé moins de la moitié de leur obligation."* |

Le niveau 1 ne passe jamais par l'IA — c'est une recherche indexée classique, plus rapide et plus prévisible ; le niveau 2 s'active quand la requête ne correspond pas à un motif de recherche simple.

### 8.1 Recherche universelle et isolation

La recherche porte sur élèves, parents, enseignants, classes, paiements, obligations, dépenses, fournisseurs, documents, produits, stocks, événements, notifications, rapports — **mais toujours filtrée par tenant avant tout traitement sémantique** (`MULTI_TENANT.md` §15.1) : le filtre tenant s'applique en amont du classement par pertinence, jamais après. Un directeur d'école A qui cherche *"Jean Dupont"* ne verra jamais un *"Jean Dupont — École B"*, même si le nom est identique — ce n'est pas un cas particulier à gérer, c'est une conséquence structurelle du filtrage tenant-first.

### 8.2 Recherche financière — intégration directe au Financial Core

*"Combien avons-nous encaissé cette semaine ?"*, *"Qui doit encore payer septembre ?"*, *"Quelles dépenses attendent une validation ?"* — chaque requête de ce type se traduit en appel à un outil du Financial Core (`FINANCE.md` §22-23), jamais en un calcul reconstruit dans la couche recherche.

### 8.3 Résultats et suggestions

Résultats groupés par type, aperçu compact (nom, classe, solde — jamais un pavé d'informations), actions directement proposées quand pertinent (section 10). Suggestions pendant la frappe adaptées au rôle, au contexte, à l'historique récent (*user-scoped* et *tenant-scoped*, jamais partagées entre utilisateurs — cohérent avec `MULTI_TENANT.md` §15.2 sur le cache).

Statut : `📋 PLANIFIÉ`.

---

## 9. Ambiguïté, zéro résultat, recherche multi-tour

**Ambiguïté** : *"Jean"* renvoyant trois élèves (Jean Dupont, Jean Kabeya, Jean Ilunga) → présenter les choix, **jamais deviner** si une erreur pourrait entraîner une action incorrecte (cohérent avec `SYSTEME_IA.md` §10.3, §14 seuils de confiance déjà posés pour l'import — même logique ici).

**Zéro résultat** : jamais un simple *"Aucun résultat"* sans piste — proposer des reformulations plausibles, et si l'intention elle-même est ambiguë (*"retards"* → financier ou présence ?), le demander explicitement plutôt que de choisir arbitrairement.

**Multi-tour** : *"Montre-moi les impayés"* → *"Pour quelle période ?"* → *"Septembre"* → résultat, puis *"Seulement la 6e"* affine le même contexte sans le reformuler entièrement. Le contexte de la question précédente (période, filtre) est conservé le temps de l'échange — **mais reste une réponse en ligne éphémère, jamais un fil de conversation persistant** (cohérent avec `SYSTEME_IA.md` §5, expiration rapide du contexte de question, pas une mémoire longue durée).

Statut : `📋 PLANIFIÉ`.

---

## 10. Recherche actionnable, exécution de commande, confirmation

### 10.1 Actions proposées depuis un résultat

*"Montre-moi les élèves qui doivent encore payer"* → liste + actions proposées (*"Préparer un rappel"*, *"Exporter"*) — chaque action proposée repasse par le circuit complet, jamais une exécution directe depuis l'affichage (cohérent avec `EVENEMENTS.md` §17.7 sur les notifications actionnables — même règle ici).

### 10.2 Commandes et preview obligatoire

```
"Créer une dépense de 350 USD pour l'achat de fournitures."
   → Intent → Preview ("Vous êtes sur le point de créer : Dépense 350 $, Catégorie Y")
   → [Annuler] [Confirmer] → Permission → Validation → Business Logic → Event
```

Une phrase ne déclenche **jamais** directement une écriture réelle — le niveau de confirmation croît avec la sensibilité de l'action (MFA/approbation pour un montant élevé, cohérent avec `FINANCE.md` §19.2, `SECURITE.md` §5.1 step-up authentication).

Statut : `📋 PLANIFIÉ`.

---

## 11. AI Tool Calling

```
search_students() · get_student_financial_status() · get_payments() · get_class()
get_treasury_summary() · get_overdue_obligations() · create_expense() · create_installment()
generate_report()
```

Renvoi direct au catalogue déjà défini dans `SYSTEME_IA.md` §7 — ce document n'en crée pas un second, il précise que la Command Bar est l'interface qui déclenche ces mêmes outils. **Disponibilité d'un outil = User + Rôle + Tenant + Permission + Contexte**, jamais une liste fixe indépendante du rôle : `get_school_financial_summary()` est disponible pour un directeur, refusé pour un parent ou un enseignant — la vérification est identique à celle de n'importe quelle route API (`SECURITE.md` §6).

Statut : `📋 PLANIFIÉ`.

---

## 12. Insights, briefing et priorité de l'information

### 12.1 Information Priority Engine

Une même donnée n'a pas la même importance selon l'audience : un paiement de 250 $ est normal pour le directeur, très important pour le parent concerné, sans intérêt pour l'enseignant. Chaque information porte donc `importance × audience × contexte` (repris de votre brief), pas seulement un niveau `CRITICAL/HIGH/NORMAL/LOW` global — ce triplet déterminé au moment de la résolution d'audience, cohérent avec `EVENEMENTS.md` §17.2 (résolution d'audience) et §17.4 (priorité).

### 12.2 Insights et briefing — jamais de donnée inventée

*"28 % des élèves de 5e B n'ont pas réglé leur échéance de septembre, soit 11 points de plus que la moyenne des autres classes."* — le calcul (28 %, 11 points) vient systématiquement d'un outil déterministe (`FINANCE.md`, `SYSTEME_IA.md` §10.4) ; l'IA reformule et hiérarchise, elle ne calcule jamais elle-même une statistique affichée comme donnée de dashboard. Renvoi complet à `SYSTEME_IA.md` §10.2 (IA proactive), §10.4 (insights), §10.5 (briefing) — ce document n'ajoute qu'une précision : le dashboard est le principal point d'affichage de ces capacités déjà spécifiées.

Statut : `📋 PLANIFIÉ`.

---

## 13. Intégration Event Engine, Notification Engine, Financial Core

### 13.1 Dashboard comme consommateur d'événements

```
payment.confirmed → Event Engine → Audience Resolver → Dashboard Update (directeur, parent, dossier élève)
                                                       → rien pour l'enseignant (hors périmètre)
```

Repris directement de `EVENEMENTS.md` §17.2 (résolution d'audience) et §18 (dashboard temps réel, SSE) — ce document confirme que le dashboard est l'un des principaux consommateurs visuels du bus, au même titre que le Notification Center.

### 13.2 Ne jamais confondre notification et dashboard

Une notification est *quelque chose qui mérite l'attention* ; le dashboard est *l'environnement de travail global*. Un même événement peut alimenter les deux sans dupliquer l'information quatre fois — le dashboard lit l'état courant, la notification signale un changement ponctuel.

### 13.3 Le dashboard n'est jamais une source de vérité

Il **agrège** Financial Core, Student System, Inventory, Trésorerie — il ne recalcule et ne stocke jamais un chiffre indépendamment d'eux (cohérent avec `FINANCE.md` §16.1, déjà posé : *"aucun [module] ne recalcule un solde de façon indépendante"*).

### 13.4 Boucle complète

```
Dashboard → Commande → Intent → Permission → Action métier → Event
   → Mise à jour dashboard → Notification → Contexte IA mis à jour
```

Exemple : *"Ajouter une dépense de 350 USD"* → `ExpenseCreated` → dashboard mis à jour → workflow d'approbation si seuil dépassé (`FINANCE.md` §19.1) → notification.

Statut : `📋 PLANIFIÉ`.

---

## 14. Performance

**Jamais** 50 requêtes SQL, 10 appels API et 5 appels IA au chargement. Stratégie : agrégats précalculés/mis en cache pour les indicateurs du dashboard (mis à jour par les événements plutôt que recalculés à chaque ouverture, cohérent avec `EVENEMENTS.md` §18), affichage immédiat des données critiques (déjà disponibles en cache), chargement progressif des insights IA en second temps — **si l'IA est indisponible, le dashboard reste pleinement fonctionnel** (cohérent avec `SYSTEME_IA.md` §18, dégradation gracieuse déjà posée comme principe absolu).

Statut : `📋 PLANIFIÉ`.

---

## 15. Responsive et accessibilité

**Desktop** : sidebar + Command Bar + dashboard (déjà la structure du prototype). **Mobile** : hiérarchie repensée, pas seulement réduite — barre supérieure, Command Bar proéminente, cartes empilées, navigation basse optionnelle. **Accessibilité** : navigation clavier complète, compatibilité lecteur d'écran, contraste suffisant (cohérent avec la palette déjà posée), tailles de texte lisibles, focus visible — non négociable, pas une amélioration V2.

Statut : `🟡 PARTIEL` (le CSS actuel a un point de rupture mobile basique ; l'accessibilité clavier/lecteur d'écran n'a pas été auditée).

---

## 16. Sécurité, multi-tenant, prompt injection

Trois renvois, aucune duplication :
- **Permissions** : `Event/Search → Permission Engine → Résultat`, jamais l'inverse — `SECURITE.md` §6-8.
- **Multi-tenant** : filtre tenant appliqué avant tout traitement sémantique — `MULTI_TENANT.md` §15.
- **Prompt injection** : un texte provenant d'un élève, d'un fichier Excel ou d'un commentaire reste une **donnée**, jamais une instruction pour l'IA, y compris dans une requête de recherche — `SYSTEME_IA.md` §12.2, `IMPORT.md` §20.

Réponse directe à un scénario du brief : un parent qui tape *"Montre-moi les paiements des autres élèves"* reçoit *"Je peux uniquement vous montrer les informations auxquelles vous avez accès"* — pas un refus sec, pas une fuite, cohérent avec le ton déjà défini dans `SECURITE.md` §26 (UX de la sécurité).

Statut : `📋 PLANIFIÉ`.

---

## 17. Personnalisation, widgets, favoris

Apprentissage progressif des actions/pages/recherches fréquentes, préférences de notification et d'horaire — **mais la personnalisation ne modifie jamais une permission** (une action masquée par préférence reste interdite si elle l'était, et une action non favorite reste autorisée si elle l'est). Widgets configurables avec des recommandations par défaut sensées — jamais un dashboard vide façon tableur à construire soi-même dès le premier jour (cohérent avec la section 19).

Statut : `📋 PLANIFIÉ`.

---

## 18. Import → Dashboard : zéro configuration

Rappel de la chaîne déjà spécifiée dans `IMPORT.md` §4 : `Excel → Analyse → Mapping → Validation → Import → Environnement scolaire → Financial Core → Dashboard`. Immédiatement après un import réussi, le dashboard est **automatiquement peuplé** de données réelles (nombre d'élèves, classes, obligations importées) — le directeur ne configure jamais 25 widgets ni 50 paramètres avant de pouvoir travailler. C'est la même philosophie que la révélation de la sidebar déjà construite dans `app/inscription.html` (apparaît exactement au moment de la création de l'espace) — appliquée ici au dashboard entier.

Statut : `📋 PLANIFIÉ` (dépend de l'existence réelle du moteur d'import et du Financial Core).

---

## 19. Cas limites

| Cas | Comportement attendu |
|---|---|
| Plusieurs élèves du même nom | Désambiguïsation explicite, jamais une sélection automatique (section 9) |
| Plusieurs écoles du même nom | Isolation par `tenant_id` opaque, jamais par nom (`MULTI_TENANT.md` §4) |
| Parent avec plusieurs enfants | Contexte explicite par enfant, jamais mélangé (section 4) |
| Utilisateur multi-écoles | Changement de tenant explicite et audité (`MULTI_TENANT.md` §7.1) |
| Changement d'année scolaire | Historique séparé, dashboard reflète l'année active (`FINANCE.md` §20) |
| Classe supprimée / élève transféré | Le dashboard reflète l'état courant, jamais une référence orpheline |
| Compte désactivé | Session invalidée immédiatement, dashboard inaccessible |
| Permissions modifiées en cours de session | Nouvelle vérification à la prochaine action sensible, jamais un cache de permission obsolète |
| Événement retardé | Le dashboard affiche l'état connu, se met à jour à la réception (pas de blocage dans l'attente) |
| Paiement confirmé pendant consultation | Mise à jour temps réel (SSE, `EVENEMENTS.md` §18), jamais une incohérence figée |
| IA indisponible | Dashboard pleinement fonctionnel sans insight (section 14) |
| Recherche ambiguë / sans résultat / trop large | Sections 9, comportements différenciés |
| Action interdite | Refus clair, jamais une fuite d'information sur pourquoi (`SECURITE.md` §4) |
| Données en attente de réconciliation | Affichées comme telles (`UNRECONCILED`, `FINANCE.md` §7.5), jamais comme confirmées |
| Connexion lente / réseau coupé | Dégradation progressive, dernières données connues affichées avec indication de fraîcheur, jamais une page blanche |
| Tenant suspendu | Accès bloqué proprement, message clair, aucune donnée partielle exposée |

Statut : `📋 PLANIFIÉ`.

---

## 20. Observabilité et métriques produit

**Technique** : temps de chargement du dashboard, latence de recherche, taux de succès des commandes, confiance de reconnaissance d'intention, taux de recherche sans résultat, latence/taux d'échec IA, taux d'annulation d'action, taux de refus de permission — sans jamais collecter de donnée sensible au-delà du nécessaire (cohérent avec `SECURITE.md` §14, minimisation).

**Produit** : temps jusqu'à la première action utile, taux de succès de recherche, taux de complétion de commande, profondeur de navigation moyenne, actions les plus utilisées, intentions les plus souvent mal comprises, engagement du dashboard. Objectif explicite : **réduire le nombre d'étapes nécessaires pour accomplir une tâche** — la métrique qui compte n'est pas l'usage de la Command Bar en soi, mais la vitesse à laquelle une tâche réelle est accomplie, quel que soit le chemin choisi (navigation, recherche ou commande).

Statut : `📋 PLANIFIÉ`.

---

## 21. Architecture technique

Le schéma du brief est solide ; une correction : **Navigation et Command Bar ne convergent pas nécessairement toutes deux vers l'Intent Engine** — la navigation classique (clic sur un menu) va directement au routeur applicatif, sans passer par la compréhension IA, qui n'a de sens que pour la saisie en langage naturel. Les deux chemins aboutissent au même Permission Engine et aux mêmes Business Services, jamais à deux systèmes d'autorisation distincts.

```
                         UTILISATEUR
                              │
                        ┌─────┴─────┐
                        ▼           ▼
                  NAVIGATION   COMMAND BAR
                  (directe)         │
                        │           ▼
                        │     INTENT ENGINE (IA)
                        │           │
                        │           ▼
                        │     CONTEXT ENGINE
                        │           │
                        └─────┬─────┘
                              ▼
                     PERMISSION ENGINE
                              │
                              ▼
                    BUSINESS SERVICES
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
      Financial            Students            Inventory
        Core                 Core                 Core
          │                   │                   │
          └───────────────────┼───────────────────┘
                              ▼
                        EVENT ENGINE
             ┌────────────────┼────────────────┐
             ▼                ▼                ▼
        DASHBOARD       NOTIFICATIONS      CONTEXTE IA
        (résultat)         (Center)         (insights)
```

Statut : `📋 PLANIFIÉ`.

---

## 22. Matrice d'architecture de l'information par rôle

| Fonction | Directeur | Enseignant | Parent | Élève |
|---|---|---|---|---|
| Dashboard globale établissement | ✔ | — | — | — |
| Finance établissement | ✔ | Limité (aucune donnée famille) | — | — |
| Finance de son enfant | — | — | ✔ | Selon politique établissement |
| Classes | ✔ | ✔ (les siennes) | Enfant uniquement | — |
| Présences | ✔ | ✔ (les siennes) | Enfant uniquement | — |
| Documents | ✔ | ✔ (pédagogiques) | ✔ (enfant) | ✔ (siens) |
| Recherche globale | ✔ | Limitée à son périmètre | Limitée à ses enfants | Limitée à lui-même |
| Command Bar / IA | ✔ | ✔ | ✔ | ✔ (toujours filtrée par permission) |
| Administration / paramètres | ✔ | — | — | — |
| Import Excel | ✔ | — | — | — |
| Gestion des utilisateurs | ✔ | — | — | — |
| Trésorerie / comptes de règlement | ✔ (selon permission fine, `SECURITE.md` §8) | — | — | — |

Cette matrice est la même que celle déjà posée dans `SECURITE.md` §8 (permissions) — reformulée ici du point de vue de l'information affichée plutôt que de l'action autorisée, les deux devant toujours rester cohérentes.

---

## 23. Réponses directes à vos 22 questions

1. **Combinaison des trois** — recherche + commande + langage naturel, jamais un chatbot (section 5.1).
2. **Architecture** : Intent Engine → Permission Engine → Business Services → Event Engine, aucun raccourci IA→base de données (section 6.1, 21).
3. **Déterministe** : calculs financiers, permissions, exécution des actions, recherche de niveau 1 (section 8).
4. **IA** : compréhension d'intention, désambiguïsation, reformulation d'insight, suggestions (jamais le calcul source).
5. **Phrase → intention** : Intent Engine avec schéma structuré (`intent`, `filters`, `tenant_id` résolu serveur) — section 6.2.
6. **Permissions** : mêmes couches que toute API (`SECURITE.md` §6-8), jamais une règle spéciale pour la Command Bar.
7. **Ambiguïtés** : présenter les choix, jamais deviner si le risque d'erreur existe (section 9).
8. **Actions critiques** : preview obligatoire + confirmation + MFA/approbation selon seuil (section 10.2).
9. **Event Engine** : dashboard et recherche sont des consommateurs du bus, jamais une source parallèle (section 13.1).
10. **Notification Engine** : notification = signal ponctuel, dashboard = état courant, jamais confondus (section 13.2).
11. **Financial Core** : toute donnée financière affichée provient d'un appel direct, jamais recalculée localement (section 13.3).
12. **Dashboards par rôle** : composition différente par défaut, pas un template unique avec des sections cachées (section 2-4).
13. **Dynamique sans chaos** : Information Priority Engine — un nombre de blocs limité, choisis selon la situation réelle (section 12.1).
14. **Éviter la surcharge** : navigation réduite aux grandes catégories, le détail passe par la Command Bar (section 5, 31 du brief).
15. **Recherche rapide** : niveau 1 déterministe et indexé pour les cas fréquents, l'IA seulement quand nécessaire (section 8).
16. **Multi-tenant** : filtre tenant avant tout traitement sémantique, jamais après (section 8.1, `MULTI_TENANT.md` §15).
17. **Plusieurs enfants** : contexte explicite par enfant, jamais mélangé (section 4).
18. **Plusieurs écoles** : changement de tenant explicite et audité (`MULTI_TENANT.md` §7.1).
19. **IA contextuelle** : Context Engine alimenté par page/entité courante, jamais une IA "aveugle" au contexte (section 7).
20. **Aucune fuite** : Permission Engine appliqué avant tout résultat, réponse neutre en cas de refus (section 16).
21. **IA indisponible** : dashboard et recherche déterministe restent pleinement fonctionnels (section 14).
22. **Mesurer l'utilité** : temps jusqu'à la première action utile, taux de complétion de commande — pas le volume d'usage de l'IA en soi (section 20).

---

## 24. Tests

Reprend et étend `EVENEMENTS.md` §28, `SECURITE.md` §27, `MULTI_TENANT.md` §17 pour ce périmètre : recherche cross-tenant (doit toujours échouer), désambiguïsation (noms similaires), zéro résultat, intention mal comprise, action critique sans confirmation (doit être bloquée), permission refusée depuis la Command Bar, dashboard avec IA indisponible (doit rester utilisable), dashboard pendant une mise à jour d'événement concurrente, parent changeant de contexte enfant en cours de session.

---

## 25. Roadmap

### MVP
Command Bar avec recherche déterministe (niveau 1) + intégration Financial Core pour les requêtes financières les plus fréquentes, dashboards par rôle avec agrégats précalculés (pas de recalcul à la volée), permissions strictes dès le premier jour, réponse en ligne sans fenêtre de chat (déjà la forme du prototype).

### V1
Intent Engine complet (niveau 2, langage naturel), Context Engine branché sur la page/entité courante, insights IA réels (remplaçant les textes statiques actuels), actions critiques avec preview + confirmation, dashboard temps réel via événements (SSE).

### V2
Recherche multi-tour avec contexte de suivi, personnalisation progressive (sans jamais toucher aux permissions), widgets configurables avec recommandations par défaut, observabilité complète (section 20).

### Plus tard
Suggestions intelligentes fondées sur l'historique agrégé (respectant strictement l'isolation tenant/utilisateur), accessibilité avancée auditée formellement, favoris et raccourcis personnels.

---

## Annexe A — État précis du prototype existant

`app/dashboard.html` + `assets/js/app.js` (`DASH_CONTENT`, `ROLE_MENUS`) incarnent déjà : dashboard par rôle, Command Bar avec réponse en ligne (canned, pas de vrai Intent Engine), carte d'insight ambiante (texte statique), sidebar adaptative togglable. Rien de tout cela ne doit être reconstruit visuellement — ce document définit le contrat que la future implémentation backend doit satisfaire pour que ces mêmes écrans deviennent réels plutôt que simulés.

## Annexe B — Ce que ce tour de travail a ajouté au code

[assets/js/search-model.js](../assets/js/search-model.js) — catalogue codifié (taxonomie d'intentions, niveaux de priorité d'information, formes d'entités de recherche/commande), pure référence sans logique exécutable, même esprit que les cinq catalogues précédents.

## Annexe C — Légende de statut

Identique aux six documents précédents.
