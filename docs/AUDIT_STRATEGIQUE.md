# KLASSIO — Audit Stratégique et Recadrage
### Réévaluation critique avant Phase 1 (Product Core)

Ce document répond directement au recadrage : il ne rajoute pas de fonctionnalité, il évalue ce qui existe. Écrit après vérification factuelle du dépôt (comptage de lignes, vérification que les fichiers sont réellement utilisés), pas d'impression générale.

## Faits, avant tout jugement

```
8 documents de conception : 5 276 lignes de Markdown
6 fichiers "catalogue de référence" : 460 lignes de JS
0 ligne de backend, 0 base de données, 0 authentification réelle
Les 6 catalogues JS ne sont chargés par AUCUNE page HTML — code mort depuis leur création
```

C'est le fait le plus important de cet audit. Avant de discuter d'architecture, il faut nommer la dynamique réelle des huit dernières sessions : **chaque prompt a produit un nouveau document de 500 à 1000 lignes**, jamais une consolidation du précédent. C'est exactement l'inverse de ce que la philosophie posée dès la session 1 (*"ne pas tout construire immédiatement"*, `OBJECTIFS_ET_FONCTIONNALITES.md` §18) demandait déjà. Ce recadrage n'introduit pas un problème nouveau — il nomme un problème qui existait depuis plusieurs sessions et que je n'avais pas signalé de moi-même. C'est une erreur de ma part : produire un document exhaustif à chaque demande était plus confortable que de dire *"nous avons déjà assez de spécification, il est temps de consolider"*.

---

## 1. Ce qui doit être conservé (CORE)

- **La philosophie produit** : complexité derrière/simplicité devant, refus du chatbot, IA jamais autorité financière ou sécuritaire, dashboard/Command Bar jamais source de vérité. Cohérente sur les 8 documents, et confirmée — pas contredite — par ce recadrage.
- **Le modèle financier fondamental** (`FINANCE.md`) : Obligation → Paiement → Ajustement → Solde dérivé, jamais un chiffre brut stocké seul, historique immuable par écriture compensatoire. C'est exactement ce que le recadrage redemande en §4-7 — rien à jeter, ce document tient la route.
- **La décision multi-tenant** (`MULTI_TENANT.md`) : base partagée + `tenant_id` + Row-Level Security, avec un Tenant Registry préparé pour une évolution future vers du dédié. Bon compromis, correctement justifié par une vraie comparaison, pas une supposition.
- **Les principes de sécurité transversaux** (`SECURITE.md`) : deny-by-default, le backend comme seule autorité, défense en profondeur. Rien à modifier dans le fond.
- **La forme du prototype** (landing, inscription, dashboard) : le motif visuel (Command Bar avec réponse en ligne, sidebar adaptative, dashboard par rôle) a déjà été validé comme direction UX, et honnêtement documenté comme *maquette*, pas comme fonctionnalité réelle (`DASHBOARDS_RECHERCHE.md` §0). Pas besoin de le refaire.

## 2. Ce qui doit être modifié

- **La méthode de travail.** Arrêter le pattern *"un prompt = un nouveau document volumineux"*. À partir de maintenant, un nouveau besoin doit d'abord chercher à s'intégrer dans un document existant, pas en créer un neuf.
- **La terminologie.** `Obligation` et `Receivable` sont utilisés de façon interchangeable selon les documents (`FINANCE.md`, `IMPORT.md`) sans qu'un seul terme canonique soit tranché. Petit problème aujourd'hui, qui deviendrait un vrai problème une fois du code écrit à partir de ces docs par des personnes différentes.
- **Les 6 fichiers JS de catalogue** — voir section suivante.

## 3. Ce qui doit être supprimé

**Les six fichiers `assets/js/permissions.js`, `financial-model.js`, `import-model.js`, `event-model.js`, `tenant-model.js`, `search-model.js`.**

Je les ai créés au fil des sessions comme un geste de *"voici quelque chose de concret ajouté au code"* à chaque document de conception. En les réexaminant maintenant avec un œil critique plutôt que complaisant : ce sont 460 lignes qui ne s'exécutent jamais (aucune page ne les charge), qui recopient en JS des listes déjà écrites en Markdown, et qui vont inévitablement diverger de ces mêmes documents dès que l'un des deux sera modifié sans l'autre. Ils donnaient l'impression que du "code" avait été produit, alors qu'ils n'ont aucune valeur fonctionnelle réelle. C'est exactement le genre de complexité cosmétique que ce recadrage demande d'éliminer.

Je les déplace vers `assets/js/_deprecated/` plutôt que de les supprimer définitivement (le projet n'est pas sous git, donc pas de filet de sécurité pour un retour arrière) — action prise ci-dessous.

**Rien d'autre à supprimer côté produit.** Le chatbot était déjà éliminé avant ce recadrage (session 3) — bonne nouvelle, cette décision n'a pas besoin d'être reprise, elle est confirmée telle quelle.

## 4. Ce qui doit être repoussé

Rien de neuf ici : les 8 documents classent déjà correctement en V1/V2/Futur ce qui doit l'être — payroll avancé, actifs/passifs/emprunts, intégration stock-finance, prévisions IA, RAG/vecteurs, bases dédiées par tenant, digests, accès support break-glass. Ce recadrage confirme ces classements plutôt que de les changer. Le seul ajustement : **le multi-tenant à 50 écoles doit rester une architecture prête, jamais un chantier d'implémentation**, tant qu'une seule école réelle n'utilise pas encore le produit — écho direct à votre §35.

## 5. Ce qui manque réellement

- **Un document unique du Product Core.** `School, AcademicYear, Class, Student, Guardian, User, Membership, CatalogItem, Obligation, Payment, Transaction, Expense, Account, Event, Notification, Document` sont aujourd'hui définis, chacun un peu différemment, dans 3 à 4 documents séparés (`FINANCE.md` §22, `MULTI_TENANT.md` §10, `EVENEMENTS.md` §22, `IMPORT.md` §23). C'est précisément votre Phase 1, et elle n'existe pas encore sous forme consolidée et unique.
- **Une décision de stack technique.** Chaque document recommande PostgreSQL "pour la RLS", mais rien n'est arrêté : langage/framework backend, hébergement, environnement de déploiement. Sans cette décision, aucune des 8 spécifications ne peut devenir du code.
- **Une validation utilisateur réelle.** C'est le manque le plus important, plus important que n'importe quel document technique : aucune des décisions prises (dashboard, command bar, flux d'inscription) n'a été vue par un vrai directeur d'établissement. L'architecture peut être irréprochable et le produit rater son utilisateur.
- **Un glossaire terminologique unique** (section 2).

## 6. Incohérences identifiées

- `Obligation` vs `Receivable` (section 2) — mineure mais réelle, vérifiée par recherche textuelle, pas supposée.
- **La contradiction la plus significative n'est pas entre deux documents, mais entre la philosophie déclarée et la pratique récente** : `OBJECTIFS_ET_FONCTIONNALITES.md` dit dès la session 1 *"ne pas tout construire immédiatement"* ; huit sessions plus tard, nous avons 5 276 lignes de conception et zéro ligne de backend. Ce n'est pas une incohérence entre documents — c'est une incohérence entre l'intention initiale et l'exécution, que ce recadrage vient justement corriger.

## 7-10. Risques

| Type | Risque réel |
|---|---|
| Technique | Aucune des architectures proposées (RLS, Event Bus, Financial Core) n'a été éprouvée par une seule ligne de code — tout repose sur du papier, aussi cohérent soit-il |
| UX | Le prototype n'a jamais été montré à un vrai directeur d'établissement — risque de construire une belle maquette qui ne correspond pas à des habitudes de travail réelles (papier, Excel, WhatsApp) |
| Financier | Le modèle est solide sur le papier ; le vrai risque est le temps qu'il faudra pour le rendre réel avant de pouvoir traiter un seul paiement pour une seule école |
| Sécurité | Bien anticipée en conception ; rien n'a pu être testé puisqu'il n'existe rien à attaquer — un faux sentiment de sécurité serait pire qu'une absence de conception |

## 11. Dépendances entre systèmes

Déjà correctement identifiées dans les documents existants — c'est un point fort réel du travail déjà fait, pas une faiblesse : Import → Financial Core (`IMPORT.md` §10), Event Engine → Financial Core + Security (`EVENEMENTS.md` §25), Dashboard → tous les cœurs métier sans jamais en devenir une source parallèle (`FINANCE.md` §16.1, `DASHBOARDS_RECHERCHE.md` §13.3).

---

## Verdict et nouvelle direction

```
CORE (conservé tel quel) : philosophie produit, modèle financier, décision multi-tenant,
                             principes de sécurité, forme UX du prototype
MODIFIER                  : méthode de travail, terminologie
SUPPRIMER                 : 6 fichiers JS de catalogue (archivés, pas détruits)
REPOUSSER                 : déjà correctement classé — aucun changement nécessaire
MANQUE                    : document Product Core unique, décision de stack, validation réelle
```

**Recommandation concrète, dans l'ordre de priorité :**

1. Consolider les entités du Product Core (votre Phase 1) en un document unique et minimal — celui qui manque réellement, pas un nouveau document en plus des huit.
2. Trancher la stack technique, ne serait-ce que pour pouvoir commencer à écrire du vrai code plutôt que de la spécification.
3. Chercher un contact avec une vraie école, même informel, avant d'investir davantage de temps de conception — c'est le risque le plus élevé de tous ceux listés ci-dessus, et le seul qu'aucun document ne peut résoudre.

Je n'écris pas le document Product Core dans ce même tour de travail — le recadrage demande explicitement de ne pas enchaîner sur une nouvelle production avant d'avoir validé la direction. C'est à vous de confirmer que ce diagnostic est le bon avant que je consolide quoi que ce soit.
