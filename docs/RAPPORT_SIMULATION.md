# Klassio — Rapport de simulation grandeur nature
### Exécuté réellement le 2026-09-08 contre le backend local (pas une projection théorique)

Deux établissements réels créés et exploités via l'API, en parallèle, dans la même base : **Complexe Scolaire La Référence** (~2 340 élèves, structure maternelle/primaire/secondaire complète) et **Institut Notre Avenir** (~504 élèves). Tous les chiffres de ce rapport sont mesurés, pas estimés — scripts dans `/private/tmp/.../scratchpad/simulate.py` et `verify.py` de cette session.

## A. Volume réel généré

| | Complexe Scolaire La Référence | Institut Notre Avenir | Total |
|---|---|---|---|
| Classes | 39 | 9 | 48 |
| Élèves | 2 340 | 504 | 2 844 |
| Responsables (pool) | 1 872 | 403 | 2 276 |
| Liens élève-responsable | — | — | 2 845 |
| Articles de catalogue | 15 | 15 | 30 |
| Obligations | 2 954 | 629 | 3 583 |
| Paiements | 2 530 | 539 | 3 069 |
| Écritures du grand livre | — | — | 3 069 |
| Événements | — | — | 6 652 |
| Notifications | — | — | 3 069 |
| Entrées d'audit | — | — | 28 300 |

Temps de génération : 2 340 élèves en 67,0 s (34,9/s) ; 2 954 obligations + 2 530 paiements en 127,2 s. École B : 504 élèves en 13,5 s ; 629 obligations + 539 paiements en 26,3 s.

## B/C. Fonctionnalités testées et résultats

| Fonctionnalité | Résultat | Détail |
|---|---|---|
| Inscription établissement | **PASS** | 2 tenants réels créés |
| Connexion | **PASS** | |
| Structure (années/classes) | **PASS** | 48 classes réparties sur 3 niveaux |
| Création d'élèves en masse | **PASS** | 2 844 élèves, ~35-37/s |
| Familles multi-enfants | **PASS** | Pool de responsables partagés, fratries réelles créées |
| Catalogue financier | **PASS** | 15 articles différenciés x2 écoles |
| Obligations | **PASS** | 3 583, montants variables |
| Paiements cash/banque/Mobile Money | **PASS** | Auto-confirmation cash/banque vérifiée, Mobile Money confirmé séparément |
| États FAILED / UNKNOWN / REFUNDED / REVERSED | **NON TESTABLE** | Aucun endpoint ne les produit — 100 % des 3 069 paiements en base sont `CONFIRMED`, aucun autre statut n'existe jamais dans le système actuel |
| Corrections/ajustements financiers | **NON TESTABLE** | Aucun endpoint |
| Dossier financier ("dette expliquée") | **PASS** | 9 ms, cohérent à 100 % |
| Dashboard directeur | **PASS** (avec réserve perf) | Voir section E |
| Dashboard parent | **PASS** | Vérifié : ne voit que son enfant, chiffres corrects |
| Dashboard professeur/élève | **PARTIAL** | Répond honnêtement "non implémenté" — aucune vraie fonctionnalité |
| Isolation multi-tenant | **PASS intégral** | 4/4 tentatives croisées bloquées |
| Permissions directeur/parent | **PASS** | Vérifié côté backend, pas seulement l'UI |
| Rôles Caissier / Responsable financier | **NON TESTABLE** | Prévus dans `SECURITE.md`, absents du RBAC réel (seuls directeur/professeur/parent/eleve existent) |
| Compte Élève fonctionnel | **NON TESTABLE** | Aucun rapprochement compte↔dossier élève n'existe |
| Command Bar / recherche naturelle | **NON TESTABLE** | N'existe pas réellement (déjà documenté dans `DASHBOARDS_RECHERCHE.md`) |
| Recherche classique | **PARTIAL** | Pas d'endpoint de recherche — uniquement liste complète + filtrage client |
| Import Excel | **NON TESTABLE** | N'existe pas ; contourné par écriture directe via l'API pour cette simulation — **ceci ne valide en rien le pipeline d'import réel**, qui reste entièrement à construire |
| Idempotence à l'échelle | **PASS** | Rejeu de clé → même paiement, pas de double crédit |
| Rejet des montants invalides à l'échelle | **PASS** | Négatif toujours refusé (400) |
| Notifications différenciées par rôle | **PASS fonctionnel, échec d'usage** | Voir section J |
| Audit log | **PASS fonctionnel, bruit excessif** | 28 300 lignes pour 3 069 transactions réelles |

## D. Problèmes identifiés

| Sévérité | Problème | Reproduction | Impact | Cause probable | Correction recommandée |
|---|---|---|---|---|---|
| **HIGH** | Notifications non groupées | Le directeur de La Référence a **2 530 notifications individuelles** ("Nouveau paiement reçu") après une seule vague de paiements | Un vrai directeur serait submergé dès la première semaine réelle d'utilisation — la fonctionnalité de regroupement est déjà spécifiée (`EVENEMENTS.md` §17.5) mais jamais câblée dans le backend réel | `notif_module.on_payment_confirmed` crée une notification atomique par paiement, sans agrégation temporelle | Regrouper les notifications `payment.confirmed` du même destinataire sur une fenêtre courte (ex. 10 min) en un seul résumé, comme déjà décrit dans la spec |
| **HIGH** | Aucune recherche réelle à l'échelle | Sur l'écran Élèves, aucun champ ne filtre les 2 340 lignes déjà chargées — "Kasongo" apparaît 78 fois, impossible à isoler sans faire défiler ou Ctrl+F | Un directeur ne peut pas retrouver un élève précis dans un établissement de cette taille | Aucun filtre/recherche n'a été construit sur l'écran (hors scope du dernier chantier de connexion backend) | Ajouter un simple filtre texte côté client sur la liste déjà chargée — pas besoin d'un moteur de recherche pour une première version |
| **MEDIUM** | Dashboard directeur : requêtes O(n) | 338 ms pour 2 340 élèves, 70,6 ms pour 504 (ratio quasi parfaitement linéaire) | Acceptable aujourd'hui ; extrapolé, ~1,4 s à 10 000 élèves, ~7 s à 50 000 | `GET /dashboard` boucle `financial_summary()` élève par élève au lieu d'une requête agrégée (même faille de conception déjà corrigée sur `/students`) | Appliquer le même correctif d'agrégation SQL que celui déjà fait sur `GET /students` |
| **MEDIUM** | Bruit de l'audit log | 28 300 entrées pour 3 069 transactions réelles (~9 lignes d'audit par transaction) | L'audit devient difficile à exploiter pour une vraie investigation — noyé sous les vérifications de permission routinières | `require_permission` journalise **chaque** vérification réussie au même niveau qu'une action sensible | Séparer un "log d'accès" routinier d'un "journal d'audit" réservé aux actions sensibles (déjà distingué en théorie dans `SECURITE.md` §11, pas dans le code) |
| **MEDIUM** | Rôles Caissier / Responsable financier absents | La matrice de permissions réelle ne connaît que 4 rôles ; `SECURITE.md` §7-8 en prévoyait 7 | Un directeur ne peut pas déléguer l'encaissement à un caissier sans lui donner tous les droits financiers d'un directeur | RBAC implémenté en session 11 avec un sous-ensemble volontairement réduit du MVP | Ajouter `caissier` (permissions limitées : `payments.create` plafonné) et `responsable_financier` avant tout usage réel avec du personnel |
| **LOW** | `GET /audit-logs` plus lent que les autres listes limitées | 82,5 ms contre 14-45 ms pour des endpoints comparables avec `LIMIT` | Pas critique aujourd'hui, tendance à surveiller | Absence d'index sur `audit_logs(created_at)` malgré le tri | Ajouter l'index (`events(created_at)` également, par précaution) |
| **OBSERVATION** | Cohérence financière parfaite | Total facturé mesuré (1 680 929 $) à moins de 0,1 % du calcul théorique attendu à partir de la configuration tarifaire | — | — | Aucune action — c'est le résultat le plus important du rapport |
| **OBSERVATION** | Élève sans compte fonctionnel | Impossible de tester un vrai parcours élève | Connu depuis la session 12, confirmé toujours vrai à l'échelle | Absence de champ `student.user_id` | À trancher : un élève a-t-il vraiment besoin d'un compte séparé de celui d'un parent au MVP ? |

**Aucun problème CRITIQUE.** Rien ne compromet l'intégrité financière, la sécurité ou l'isolation multi-tenant à cette échelle — c'est le résultat central de cette simulation.

## E. Performance (mesures réelles)

| Opération | Temps mesuré | Volume concerné |
|---|---|---|
| Création d'un élève (moyenne, en masse) | ~28 ms | 2 844 élèves créés |
| `GET /students` | 84 ms | 2 340 lignes |
| `GET /students/:id/financial-summary` | **9 ms** | Indépendant du volume total — excellent |
| `GET /dashboard` (directeur, La Référence) | 323-338 ms | 2 340 élèves (2 mesures cohérentes) |
| `GET /dashboard` (directeur, Notre Avenir) | 70,6 ms | 504 élèves — confirme la linéarité O(n) |
| `GET /events` (LIMIT 50) | 44,7 ms | 6 652 lignes en base |
| `GET /audit-logs` (LIMIT 100) | 82,5 ms | 28 300 lignes en base |
| `GET /notifications` (LIMIT 30) | 14,8 ms | 2 530 lignes pour ce destinataire |

Aucune opération n'est aujourd'hui inutilisable. La seule tendance préoccupante est le dashboard directeur, dont le temps croît linéairement avec le nombre d'élèves plutôt que de rester constant.

## F. Financial Core — vérification de cohérence

Total facturé théorique attendu (180×500 + 1080×650 + 1080×800 + ~25% d'articles supplémentaires) ≈ 1 679 400 $. Total facturé réellement mesuré par le dashboard : **1 680 929 $** — écart de 0,09 %, entièrement expliqué par l'aléa des articles supplémentaires. Échantillon indépendant de 30 élèves recalculé manuellement : cohérent avec le taux de recouvrement global (66 % contre 62,2 % sur l'ensemble — écart normal d'échantillonnage). **Aucune incohérence trouvée** entre dossier élève, dashboard et sommes individuelles. Les états `FAILED`/`UNKNOWN`/`REFUNDED`/`REVERSED` restent non implémentés et donc non vérifiables.

## G. Multi-tenant

4/4 tests critiques réussis à cette échelle : lecture du dossier financier d'un élève de l'autre école (x2, dans les deux sens), présence d'élèves d'une école dans la liste de l'autre (0 intersection sur 2 340 + 504 IDs), paiement déposé sur une obligation d'un autre tenant. **Isolation confirmée intégralement**, y compris avec des identifiants réels à grande échelle plutôt que des cas jouets.

## H. Permissions

Directeur : accès complet confirmé. Parent : strictement cantonné à son enfant lié — création d'élève bloquée (403), dossier d'un autre enfant bloqué (404), audit log bloqué (403), tout vérifié côté backend et pas seulement masqué côté interface. Professeur : dashboard répond honnêtement plutôt que d'inventer un contenu. Élève et rôles Caissier/Responsable financier : non testables (absents du système réel, voir section D).

## I. Import à grande échelle

**Non testé tel que demandé.** Le pipeline d'import réel (`docs/IMPORT.md`) n'existe pas dans le code — seule une maquette visuelle existe dans `app/inscription.html`. Pour permettre le reste de la simulation, les 2 844 élèves ont été créés par appels directs à l'API (`POST /students`), ce qui prouve que l'API tient la charge mais **ne valide en rien** le mapping IA, la détection de doublons, la normalisation ou l'aperçu avant import — tout cela reste à construire et à tester séparément le jour où l'import existera réellement.

## J. UX — où un vrai directeur serait perdu ou ralenti

- **Notifications** : 2 530 notifications individuelles rendraient le centre de notifications inutilisable dès la première rentrée réelle.
- **Recherche** : aucun moyen de retrouver un élève précis dans une liste de 2 340 sans faire défiler manuellement.
- **Dossier financier** : à l'inverse, c'est l'écran qui tient le mieux la charge — rapide, clair, cohérent, exactement ce qu'un directeur consulte le plus souvent.

## K. Backend — parties encore simulées, incomplètes ou fragiles

Command Bar (100 % simulée), import Excel (100 % absent), rôles Caissier/Responsable financier (absents du RBAC), compte Élève (non fonctionnel), états de paiement avancés (absents), dashboard directeur (O(n), fonctionnel mais pas scalable indéfiniment), audit log (fonctionnel mais bruyant), notifications (fonctionnelles mais non groupées), rate limiter (en mémoire, déjà noté précédemment).

## L. Recommandations

1. **Critique** — Aucune.
2. **Prioritaire** — Regroupement des notifications ; recherche/filtre réel sur l'écran Élèves ; permettre un accès élève minimal.
3. **Important** — Corriger le O(n) du dashboard directeur (même correctif déjà appliqué à `/students`) ; ajouter les rôles Caissier/Responsable financier ; réduire le bruit de l'audit log ; indexer `created_at` sur `audit_logs`/`events`.
4. **Plus tard** — Pagination généralisée, import Excel réel, Command Bar réelle, états de paiement avancés (remboursements, corrections, échecs).
5. **Ne pas faire maintenant** — Rate limiter distribué (Redis), sharding, infrastructure multi-région : rien dans ces mesures ne le justifie à ce stade.

## Réponse à la question posée

*"Si une vraie école d'environ 2 300 à 2 400 élèves utilisait Klassio demain, où le système tiendrait-il parfaitement, et où commencerait-il à montrer ses limites ?"*

**Ça tiendrait parfaitement** sur l'essentiel : intégrité financière, isolation entre écoles, permissions, création de données, dossier financier individuel — tout est cohérent, rapide et correctement cloisonné, même à 2 844 élèves répartis sur deux établissements simultanément.

**Ça montrerait ses limites** immédiatement sur l'expérience quotidienne du directeur : il serait noyé sous les notifications dès la première semaine, et incapable de retrouver un élève précis sans faire défiler une liste de plus de deux mille lignes. Le seul risque de performance réel (le dashboard) est encore loin d'être critique, mais suit une trajectoire qu'il faudra corriger avant de viser un établissement significativement plus grand.
