# KLASSIO — point de reprise

> **Agents IA : lisez d'abord `AGENTS.md`** — il fixe ce qui ne doit jamais
> être affaibli (isolation, autorisation serveur, historique, tests), et ce qui
> reste libre. Ce fichier-ci donne l'état du projet ; celui-là donne les règles.

Ce fichier existe pour qu'une nouvelle conversation reprenne sans rien
redécouvrir. Lisez-le en entier : il contient tout ce qui n'est pas déductible
du code.

Dernière mise à jour : 2026-09-17 (espace professeur, invitations, calendrier, discipline §11, audit, paiement parent, site public + révocation d'accès + abonnement). §0 consolidé — il donne l'état courant, pas le journal des sessions.

---

## 0. REPRISE IMMÉDIATE — état au 17/09

> **Agents IA : lisez `AGENTS.md` d'abord**, puis cette section. Elle remplace
> le journal des sessions précédentes : tout ce qui suit est encore vrai.
> Le détail historique reste dans les commentaires du code, à côté du code
> qu'il explique — c'est là qu'il sert.

### En une phrase

Le produit fonctionne de bout en bout, **312 tests verts** (SQLite) et **16/16
modules** (PostgreSQL). La landing est terminée et **figée**. La démo et
l'application sont les chantiers ouverts.

### Ce qui est figé, ce qui est ouvert

| | |
|---|---|
| 🔒 **Landing** | `index.html`, `assets/js/main.js`, blocs « landing » de `style.css`. **Lire `LANDING_FIGEE.md` avant d'y écrire une ligne.** On n'y corrige qu'un défaut constaté. |
| ✅ **Démo** | `demo.html`, `page-demo.js`, `demo-data.js` — ouverte. Deux garde-fous : données toujours fictives et annoncées, et `style.css` est partagé. |
| ✅ **Application** | `app/*.html` et ses `page-*.js` — chantier principal. |

### Faire tourner le logiciel

```bash
./demarrer.sh          # API 5001 + pages 4173, Ctrl-C arrête les deux
```

Le **port 4173 n'est pas négociable** en développement : `ALLOWED_ORIGINS`
(`backend/app.py`) n'autorise que cette origine. Servir les pages ailleurs fait
échouer tous les appels API sans message clair.

Comptes de test dans la base de dev — École Pilote Klassio, tous avec le mot
de passe `Klassio2026!` :

| Rôle | Identifiant |
|---|---|
| Direction | `direction@ecole-pilote.test` |
| Professeur | `prof.pilote@ecole-pilote.test` |
| Directeur des disciplines | `dd.pilote@ecole-pilote.test` |
| Parent | `parent.pilote@ecole-pilote.test` |

L'établissement porte deux classes (6e A, 5e B), quatre élèves, une obligation,
un paiement et le reçu REC-2026-00001. Le professeur est titulaire de 6e A et
professeur de mathématiques en 5e B.

### Tests — les deux, l'un APRÈS l'autre

```bash
cd backend && ../backend_venv/bin/python -m unittest discover -s tests -t .
backend_venv/bin/python backend/tools/pg_tests.py
```

Ne **jamais** les lancer en parallèle : ils partagent `backend/klassio_test.db`
et s'inventent des échecs (18 faux échecs observés, disparus en séquentiel).

---

### Décisions à ne pas défaire

Chacune a coûté un défaut reproduit. Les commentaires du code disent lequel.

**Résultats et parent**
1. Toute lecture de `grades` destinée à un affichage filtre **`is_current=1`**.
   Trois chemins l'oubliaient : tableau de bord parent, rang du bulletin, liste
   de classe. L'historique se consulte par la route d'historique dédiée.
2. Toute donnée de résultat exposée au **parent** passe par
   `published_period_ids_for_student()`. Fermeture par défaut : une note sans
   période rattachée reste invisible.

**Navigation — trois fois le même piège**
3. `overflow: hidden` sans affordance **cache des fonctionnalités**. Corrigé sur
   les onglets du dossier élève (9 onglets, 4 inatteignables dont Finance) et
   sur le menu latéral (16 entrées coupées sur écran court). Ne pas y remettre
   un défilement invisible.
4. **On ne retire du menu que ce qui reste joignable ailleurs**, et on le
   vérifie lien par lien. Masquer une entrée n'a jamais protégé quoi que ce
   soit : l'autorisation est vérifiée par le serveur.
5. Une page absorbée par une entrée fusionnée doit **allumer** cette entrée
   (table `PORTE` dans `admin.js`), sinon l'utilisateur perd son repère.

**Interface**
6. `.btn::before` reste en **`z-index: -1`**. En 0, le cercle de survol passe
   au-dessus du texte non enveloppé et « Connexion » devient un ovale blanc.
7. `.chip` de la landing reste porté par `.tools-chaos` : le nom sert aussi aux
   pastilles de filtre des écrans de gestion, définies plus bas dans la feuille.
8. **États d'arrivée en CSS, états de départ en JavaScript.** C'est ce qui fait
   qu'en mouvement réduit ou sans script, tout s'affiche déjà en place.
9. `style.css` et `theme.js` sont partagés par **29 pages** : après
   modification, réversionner `?v=` PARTOUT. Oublié deux fois. Même règle pour
   `ui.js`, `app.js` et `admin.js`, partagés eux aussi.
10. **Chaque rôle a SA page d'arrivée** — `UI.homeFor(role)` dans `ui.js`, et
    nulle part ailleurs. Elle vit là parce que la page publique d'invitation en
    a besoin et ne charge que `ui.js` ; une seconde copie aurait divergé au
    premier changement de menu. Le rôle qu'on lui passe vient **toujours** d'une
    réponse serveur, jamais de `klassio_role`.
11. **La table `PORTE` d'`admin.js` est une liste par page, pas une chaîne**, et
    elle ne s'applique qu'à une page SANS entrée à elle dans le menu du rôle.
    Écrite pour les fusions du menu Direction et appliquée à tous les rôles,
    elle allumait deux entrées à la fois (§0 « Espace professeur »).

### Où en est la navigation

**Une seule zone porte l'identité (17/09).** La topbar affichait « Klassio » et
le nom de l'établissement — les deux mêmes informations que la barre latérale, à
vingt centimètres. Deux zones de navigation qui se répètent ne créent pas un
repère, elles en suppriment un. L'identité reste donc dans la **barre latérale**
(Klassio en surtitre, l'établissement en gras — la plateforme et l'école ne se
confondent pas), et la topbar dit **où l'on est** : `Section › Détail`, plus la
cloche. La section vient du **menu du rôle**, donc un professeur y lit « Mes
classes » et jamais « Direction ». Le détail est fourni par la page via
`admin.setContext()` — la coquille n'invente rien, et sans appel le fil s'arrête
à la section. Sous 560 px, le détail prime sur la section.

⚠️ Le lien vers la vitrine publique vivait dans la marque de la topbar : il a été
reporté sur la marque de la barre latérale, devenue un `<a>`. **Ne pas la
reremettre en `<div>`** — le clic retomberait dans le vide.

Le compte a quitté la topbar : il est en bas de la barre latérale (nom, rôle ·
établissement, puis Paramètres / Abonnement / Déconnexion). La topbar ne garde
que la cloche. Le thème est dans **Paramètres → Apparence** (Clair / Sombre /
Système — « system » est stocké tel quel et résolu à chaque lecture).

Menu Direction ramené de 16 à **11 entrées** : Accueil, Établissement,
Élèves & classes, Résultats, Finance, Discipline, Calendrier, Messages,
Boutique, Rapports, Assistant.

**Le professeur n'a pas d'« Accueil ».** Son menu compte 8 entrées et commence
par **Mes classes**, qui est aussi sa page d'arrivée : Mes classes, Mes élèves,
Suivi, Livres & devoirs, Messages, Calendrier, Notifications, Assistant.
`dashboard.html` l'y redirige (en conservant la chaîne de requête, qui porte
`?bienvenue=1`). Voir « Espace professeur » ci-dessous.

---

### Décisions qui attendent le propriétaire

**Tarifs — conflit non tranché.** Le projet a déjà un modèle codé et utilisé
pour facturer (`plans`, `api_billing`) :

| Formule | Élèves | Prix |
|---|---|---|
| Essentiel | 0–300 | 49 $ fixe |
| École | 301–1 000 | 60 $ + 0,30 $/élève |
| Complexe | 1 001–3 000 | 120 $ + 0,20 $/élève |
| Réseau | 3 001+ | sur devis |

Les prix demandés (100 / 250 / 500 $, plafond 500) **ne correspondent pas**, et
le modèle atteint 720 $ à 3 000 élèves. Changer cela touche le calcul des
factures. **Ne rien modifier sans décision explicite.**

**Anomalies historiques — une réparée le 18/09, une toujours ouverte.**
Les 6 896 paiements confirmés sans reçu ont été **réparés** sur demande
(`reparer_recus.py --appliquer`, strictement additif, sauvegarde préalable) :
il en reste 0. Les 16 jetons de session en clair, tous expirés et antérieurs au
hachage, sont **toujours là** — leur suppression demande une décision, la
contrainte « ne supprimer aucune donnée » tenant toujours. Le code est correct
dans les deux cas.

### Signalé, non reproductible — ne pas corriger à l'aveugle

- **Bascule de rôle sur Calendrier** : le rôle vient exclusivement de `/me` ;
  `klassio_role` n'est jamais relu pour rendre quoi que ce soit. Cause probable :
  **un seul jeton par navigateur** — ouvrir un second compte remplace le premier.
- **Invitation parent bloquée sur « En attente »** : vérifié de bout en bout,
  `pending` → `accepted` avec `accepted_at`, transition atomique.

### Messagerie — ce que c'est réellement

Fil **interne**, un par élève (`messages.student_id`), stocké en base. **Aucun
SMS, WhatsApp, e-mail ni appel sortant** — rien dans le code. Personnel → les
responsables de l'élève ; parent → le personnel du périmètre, jamais les autres
parents. Accès via `school.resolve_student_access`, non-lus par `message_reads`,
notification interne à chaque envoi. **Ne pas le présenter comme un canal externe.**

---

### Espace professeur — fait le 17/09

Le professeur entre par **ses classes**. Ce qui a changé, et pourquoi :

**Ce qui existait déjà et n'a pas été refait.** `page-classe.js` portait déjà
tout le parcours §8–§9 et connaissait déjà le rôle : Élèves / Présence / Notes
**ou** Appréciations selon le cycle / Conseil de classe (titulaire ou Direction,
`canCouncil()`) / Livres & devoirs / Horaire & examens. `page-discipline.js`
avait déjà une `teacherView()` entièrement distincte des onglets du DD. Les
périmètres serveur (`school.teacher_class_rows`, `resolve_student_access`)
étaient en place. **Le manque était l'entrée, pas le contenu.**

**`classes.html` est devenu son domicile.** Il y arrive à la connexion, après
l'activation d'une invitation et au bout de `dashboard.html`. L'écran montre ses
cartes de classe d'abord (matière ou titularité, effectif, état de l'appel),
puis sa file « à traiter » et l'horaire du jour. Il lit `GET /api/dashboard`,
qui renvoyait déjà exactement ces données pour ce rôle : **aucune route backend
n'a été ajoutée.**

**`renderProfesseur` a quitté `page-dashboard.js`.** Il n'y avait plus de chemin
vers lui, et une seconde page d'accueil qui redit la même chose dans un autre
cadrage est un piège. Chaque bloc a été relogé et vérifié lien par lien :
KPI → les cartes et la ligne de sous-titre ; horaire du jour et « à traiter »
→ ici ; incidents communiqués → `discipline.html` (menu « Suivi ») ;
événements → `calendrier.html` (menu « Calendrier »).

**`cloturerAccueil` a déménagé dans la coquille** (`admin.js`). Attachée au seul
tableau de bord, elle ne se serait plus déclenchée pour un professeur, qui
n'y atterrit plus : il aurait rejoué son invitation à chaque connexion.

**Aucune finance sur son chemin.** L'onglet « Situation financière » de la page
de classe reste une décision explicite de la Direction
(`tenant_settings.teacher_sees_finance`, gardée par `school.finance_visible`) —
non touchée sur consigne du 17/09. Rien d'autre n'expose de montant.

**Défaut trouvé et corrigé en chemin (P2).** La table `PORTE` d'`admin.js`
décrit les fusions du menu **Direction** mais s'appliquait à tous les rôles :
un professeur sur `classes.html` ou `classe.html` voyait « Mes classes » **et**
« Mes élèves » allumées, avec deux `aria-current="page"` dans la même
navigation. Corrigé : la porte ne s'ouvre que pour une page sans entrée à elle,
et c'est une liste de candidats dont on retient le premier présent dans ce
menu-ci. Vérifié en neutralisant le correctif — le défaut réapparaît à
l'identique — puis sur les 4 rôles, page par page, une seule entrée allumée.

**Comptes de test ajoutés dans la base de développement** (École Pilote
Klassio, mot de passe `Klassio2026!` pour tous) : `prof.pilote@`,
`dd.pilote@`, `parent.pilote@` `ecole-pilote.test`, plus une classe « 5e B »
et trois élèves. Le professeur est titulaire de 6e A et professeur de maths en
5e B — de quoi exercer les deux états de carte.

### Invitations (§16) — fait le 17/09

`etablissement.html` était **un rouleau de sept panneaux** : identité, cycles,
périodes, classes, équipe, invitations. Le bouton « Inviter » de l'en-tête ne
faisait que *défiler* jusqu'en bas. Il est maintenant découpé en **trois
onglets** (`UI.tabs`, déjà utilisé par classe et discipline), les chiffres de
tête restant visibles au-dessus quel que soit l'onglet :

| Onglet | Contenu |
|---|---|
| Identité & structure | informations générales, année active, répartitions par cycle et par classe |
| Périodes & proclamation | périodes, verrou, proclamation |
| Équipe & accès | le rôster **et** les invitations, avec un compteur d'invitations en attente sur l'onglet |

**Pourquoi Équipe et Invitations ensemble.** C'est un seul sujet — qui a accès
à cette école. Séparés, ils se renvoyaient l'un à l'autre (l'état vide de
l'Équipe dit « invitez vos enseignants »), et inviter quelqu'un puis lui
affecter ses classes obligeait à remonter la page. **Décision du propriétaire
le 17/09 :** fusionner en onglets plutôt que créer une page — le menu Direction
reste à 11 entrées. Mesuré ce jour-là : à 768 px de hauteur, une 12e entrée
remplit la barre latérale à ras bord.

**Rien n'est devenu injoignable.** `?tab=` est la forme courante, mais les
ancres `#invitations`, `#equipe` et `#periodes` restent honorées (table
`ANCRES`), y compris sans rechargement (`hashchange`) — elles vivent dans des
signets, et sept écrans y pointaient. Les liens entrants ont été basculés sur
`?tab=` : tableau de bord (action « Inviter » et file « à traiter »),
page de classe, dossier élève, écran d'import des résultats.

**Défaut trouvé en chemin (🟢 P3, latent).** `createInvitation` rappelait
`wire()` en entier pour rafraîchir un seul panneau. Mesuré : chaque invitation
créée ajoutait **un écouteur de plus** sur `#addPeriodBtn`, `.reset-link` et
`.edit-member`. Aucun symptôme aujourd'hui, et il faut savoir pourquoi : deux
filets indépendants l'absorbent — `UI.modal` commence par `closeModal()`, donc
un double déclenchement n'empile pas deux boîtes ; et le seul gestionnaire sans
modale (préréglage des périodes) tape sur une route **idempotente par libellé**.
Corrigé par extraction de `wireInvitations()` : on rebranche ce qu'on redessine.
Le jour où l'on ajoute ici un gestionnaire sans confirmation et sans idempotence
serveur, il aurait tiré.

### Frontend académique et discipline — fait le 17/09

**Calendrier académique.** L'onglet « Périodes & proclamation » d'Établissement
est devenu l'écran de calendrier : périodes par division, **état calculé par le
serveur** (`school.period_state` : brouillon, à venir, en cours, saisie en
cours, terminée, verrouillée, archivée), dates, les trois échéances (saisie,
validation, proclamation) avec signalement de celles dépassées, période en
cours mise en évidence. Édition complète d'une période (division, dates,
échéances, pondération, état) via `PUT /api/periods/<id>`, qui n'était branché
sur aucune interface. **Verrou et réouverture motivée** : verrouiller ferme la
saisie et désactive « Modifier » ; rouvrir exige une raison d'au moins dix
caractères, vérifiée **côté serveur** (testé : une raison courte est refusée en
400 même en contournant l'écran), et l'historique des réouvertures est
consultable — qui, quoi, quand.

**Aperçu d'audience avant proclamation.** « Proclamer » n'est plus un
« Êtes-vous sûr ? ». L'écran appelle `/publication-preview`, qui utilise la
**même fonction** que la publication (`school.compute_publication_audience`) :
l'aperçu ne peut donc pas annoncer autre chose que ce qui sera fait. Il montre
qui verra, qui ne verra pas et **pourquoi**, la politique de diffusion en
vigueur, et la liste nominative des inclus. Le bouton reste désarmé si personne
ne recevrait la proclamation.

**Portail parent — « prochaine proclamation ».** Nouvelle tuile sur l'espace
familial, alimentée par `_prochaine_proclamation` (backend). Deux règles :
la date n'est affichée **que si l'établissement en a déclaré une** — sinon
« Date non annoncée », jamais un « bientôt » inventé au nom de l'école — et un
brouillon ou une période archivée est sauté. Les trois cas ont été exercés.

**Discipline §11 — la Direction et le DD séparés.** Le DD garde son **poste de
travail** : « Aujourd'hui » en premier, bouton Pointage, rien de changé. La
Direction reçoit un premier onglet **« Vue d'ensemble »** : volumes 7/30 jours,
ce qui se répète (par catégorie), où cela se passe (par classe), élèves sous un
seuil. Aucun onglet n'est retiré à la Direction — elle n'atterrit simplement
plus sur le poste de travail quotidien.

⚠️ **Piège écarté en chemin.** La tuile « incidents 7 jours » affichait d'abord
une tendance en pourcentage. Sur un établissement qui venait d'enregistrer ses
six premiers faits, elle annonçait « **+330 %** » : la moyenne mensuelle était
faite de ces mêmes jours, la comparaison se mordait la queue. Un chiffre
circulaire qui se lit comme une alarme n'est pas une information. Remplacé par
un fait — « 6 des 6 faits du mois ». **Ne pas réintroduire de tendance sans une
fenêtre de comparaison réellement disjointe.**

### Audit fonctionnel global — fait le 17/09

Reporté depuis le 15/09 en attendant l'interface académique ; elle est là, il a
donc été mené. Méthode : les quatre rôles exercés dans le navigateur sur un
établissement réel, puis les garanties éprouvées **contre le serveur**, jamais
contre l'écran.

**Balayage des écrans** — 42 chargements de page (Direction 18, professeur 9,
DD 5, parent 10) : **zéro échec d'API, zéro erreur JavaScript**, aucune page en
état d'erreur. Les états vides rencontrés sont légitimes et explicites.

**Garanties vérifiées en conditions réelles :**

| Garantie | Épreuve | Résultat |
|---|---|---|
| Le parent ne voit que le proclamé | Note 17/20 en période proclamée, 6/20 en période non proclamée | Parent : 17 seul. Direction : les deux |
| Proclamation réversible | Retrait de P1 → P2 proclamée → P1 remise | La vue parent suit exactement, dans les deux sens |
| Isolation inter-établissements | 7 routes appelées avec les identifiants d'une autre école | **404** partout, jamais `200 []` |
| Autorisation serveur | 9 routes Direction tentées par professeur, DD, parent | 403 partout ; seuls `team` et `discipline/overview` s'ouvrent au DD, à son périmètre |
| Périmètre intra-école | Parent sur un autre élève de la même école | 404. Sa liste ne contient que son enfant |
| Idempotence des paiements | Même clé envoyée deux fois | **201** puis **200**, même paiement, un seul encaissement |
| Circuit financier | Obligation 150 → paiement 50 → reçu | `REC-2026-00002` émis, solde recalculé à 100 |
| Messagerie interne | Parent écrit, Direction et titulaire lisent | Fil correct, aucun canal externe |
| IA en lecture seule | `grep` d'écritures + demande de suppression | 0 `INSERT/UPDATE/DELETE` dans le module ; la demande est **refusée** explicitement |
| Aucun faux succès | Recherche de `setTimeout` simulant une progression | Aucun dans l'application (seuls landing et démo, assumés) |
| Professeur et finances | 4 routes financières + charge utile de sa classe | `finance_visible: false`, aucun solde exposé, 403 sur les lectures |

**🟠 Un défaut trouvé et corrigé — `GET /api/catalog-items`.** Seule de toutes
les lectures financières, cette route n'avait **aucune vérification de
permission** : un professeur ou un DD y lisait la grille tarifaire complète de
l'établissement, montants compris, alors que leur accès financier est fermé.
Ce n'est pas la situation d'une famille — c'est le tarif public, que les
parents voient de toute façon — mais l'écart avec les autres routes n'était pas
voulu. Fermé par `@require_permission("store.read")`, qui colle exactement :
Direction et parents l'ont (les parents en ont besoin pour la Boutique),
professeur et DD ne l'ont pas. Test ciblé ajouté et **vu échouer sans le
correctif** (200 au lieu de 403). Les trois appelants ont été vérifiés un par
un : deux écrans Direction, un parcours parent — aucune régression.

**🟢 Limite relevée, non corrigée.** L'assistant IA retombe sur « je n'ai pas
assez d'informations » pour « quel est le taux de recouvrement ? », alors que
le tableau de bord affiche ce chiffre. C'est une couverture d'intentions
incomplète, pas un défaut de sécurité — et le repli est honnête plutôt
qu'inventé. À élargir avec le reste du chantier IA.

### Paiement des frais dans l'espace parent — fait le 17/09

**Ce qui existait déjà et n'a pas été refait.** Le Financial Core est solide :
idempotence avec détection de conflit de charge utile, transition `CONFIRMED`
atomique, grand livre, reçu `UNIQUE(payment_id)`, notification, audit. Le
parcours parent existait **côté serveur** — `POST /api/payments` accepte un
parent en `mobile_money` uniquement, et le paiement reste `CREATED` jusqu'à
confirmation par l'établissement. Aucune table n'a été ajoutée, aucun second
modèle financier créé.

**🟠 P1 corrigé — le montant n'était validé nulle part.** Le formulaire portait
un `max` HTML, et rien d'autre. Sonde réelle : un parent envoyant
`{"amount": 999999}` sur une obligation de 90 $ obtenait **201**. Impact mesuré
sur une copie jetable de la base — dès que la Direction confirmait la demande,
d'un clic et sans que le montant lui soit opposé : solde **90 → -999 909**,
**reçu officiel de 999 999 $ émis**, écriture du même montant au grand livre.
Un document faux et une comptabilité fausse, à partir d'un champ de formulaire.
Corrigé dans `financial.create_payment`, qui compare désormais au **reste dû**
(pas au montant de l'obligation : les paiements partiels restent possibles).
Test vu échouer sans le correctif.

⚠️ **`allow_overpayment=True` n'est pas une porte dérobée.** Un seul appelant
l'ouvre : la reprise d'historique (`ingestion.confirm_import`). Une école qui
migre déclare son propre passé — « frais 250, déjà versé 400 » existe, l'analyse
d'import le **signale** à la Direction avant écriture, et refuser ferait échouer
toute la migration pour une ligne. **Ne pas étendre ce drapeau à un autre
appelant.** C'est la suite de tests qui a attrapé cette régression (test_13).

**Écran parent refondu** (`paiements.html`, menu « Frais & reçus »). Avant,
« Payer » était un **lien** renvoyant vers `eleve-dossier.html` : deux écrans
pour un geste, sur un téléphone. Désormais tout y est : sélecteur d'enfant (les
soldes ne sont jamais additionnés sans le dire), situation de l'enfant, bloc
d'action « prochaine échéance » ou « paiement en retard », échéancier,
historique avec référence et reçu, et **le paiement sur place**.

**Les tranches ne sont pas une table.** Plusieurs obligations partageant le même
`catalog_item_id` pour un élève **sont** les tranches d'un même frais, ordonnées
par échéance. `financial_summary` expose désormais `catalog_item_id` pour que
l'échéancier se reconstitue. Côté Direction, « Ajouter un frais » permet de
répartir en **N tranches configurables** (1 à 12) via `POST /api/obligations`
appelé N fois ; la répartition ajuste le dernier montant pour que la somme tombe
exactement (1000/3 → 333,33 + 333,33 + **333,34**, jamais un centime orphelin).

**Ce qui n'est pas fait, et pourquoi.** Il n'existe **aucune intégration Mobile
Money ou bancaire**. Le parcours s'arrête donc à « demande transmise à
l'établissement », qui la confirme après vérification réelle. Les statuts
`PENDING`, `PROCESSING`, `FAILED` et `UNKNOWN` **restent inatteignables** : rien
ne les produit, et en fabriquer serait mentir. Pas de table `payment_attempts`,
pas de webhook — la route `/payments/<id>/confirm` en tient lieu et porte déjà
l'idempotence qui s'appliquera à un vrai.

**Éprouvé de bout en bout dans le navigateur** (mobile 375 px, clair et sombre) :
demande parent → l'écran affiche « Demande transmise » avec une **horloge
ambre**, jamais une coche verte ; confirmation Direction → reçu REC-2026-00005,
référence `MM-TX-88421`, solde à jour, **notification émise après confirmation**,
reçu consultable. Double clic sur « Envoyer » → **un seul paiement** (la clé
d'idempotence est calculée une fois à l'ouverture de la modale, pas à chaque
clic). Le jour de référence vient du serveur (`dashboard.today`) : « en retard »
ne dépend pas de l'horloge du téléphone.

**P2 et P3 réglés le 17/09.** L'échéancier se crée par
`POST /api/obligations/schedule` : **un seul appel, somme vérifiée par le
serveur, tout ou rien**. L'écran la contrôlait, et lui seul — un client modifié
créait trois tranches de 100 pour un frais de 1 000, et la dette devenait 300
sans que rien ne proteste ; et en N appels séparés, la troisième pouvait échouer
après l'écriture des deux premières. Vu échouer sans le contrôle. Par ailleurs,
le parent ne paie plus qu'à **un seul endroit** (« Frais & reçus ») : le dossier
élève l'y renvoie par un lien au lieu d'ouvrir une seconde modale.

### Site public, révocation d'accès, abonnement — fait le 17/09

**Révocation d'accès (§2).** La route ne faisait que réécrire un statut. Sur une
invitation `pending` cela suffisait ; sur une invitation **acceptée** elle ne
faisait **rien** — la personne gardait son compte, sa session et l'accès aux
dossiers. Une Direction lisait « révoquée » pendant qu'un parent continuait de
consulter l'enfant d'une autre famille.

Désormais : l'invitation passe en `revoked` (datée, auteur, motif), le
**membership** passe en `revoked`, et les **sessions** sont fermées.
`security.resolve_session` revérifiant le membership à chaque requête, la
coupure est immédiate. **Rien du métier n'est supprimé** : ni l'élève, ni son
dossier, ni ses paiements, ni ses reçus. Vu échouer sans le correctif
(`200 != 401`). ⚠️ La **Direction ne se révoque pas** par ce chemin : une école
sans accès Direction devient inadministrable.

**Abonnement (§1).** La carte « Période d'essai — X jours restants » a quitté le
Dashboard, ainsi que la redirection automatique vers l'écran d'abonnement. Le
calcul n'a pas bougé (`api_billing.summary` reste seul juge) ; seule la
présentation a déménagé vers **Paramètres → Abonnement Klassio**. Le bandeau de
**lecture seule** demeure dans la coquille : il n'est pas commercial, il
explique pourquoi l'enregistrement est suspendu.

⚠️ **Conflit tarifaire NON tranché.** La base porte 49 / 60+0,30 / 120+0,20 /
devis (seuils 300, 1 000, 3 000). Le prompt du 17/09 mentionne 100 / 250 / 500.
`plans` pilote le calcul des factures : **rien n'a été modifié**, l'écran affiche
la configuration réelle. Décision du propriétaire attendue.

**Suppression de compte (§12).** Paramètres → Supprimer mon compte, avec
réauthentification par mot de passe. L'identité est **neutralisée** plutôt que la
ligne supprimée : des paiements, des audits et des invitations pointent dessus.
Sont conservés : dossiers élèves, résultats, **pièces comptables** et journal
d'audit. La dernière Direction d'un établissement ne peut pas se supprimer.

**Site public (§3 à §11, §14, §17).** Huit pages créées :
`a-propos.html`, `aide.html` (19 articles, 6 catégories, recherche locale),
`faq.html` (14 questions), `contact.html`, `securite.html`,
`confidentialite.html`, `cgu.html`, `mentions.html`. Socle commun dans
`assets/js/public.js` — navigation, pied de page, menu mobile — écrit une fois.
`robots.txt` et `sitemap.xml` ajoutés ; `/app/` est exclu de l'indexation.

⚠️ **`index.html` reste FIGÉE.** Seuls des LIENS y ont été ajoutés (navbar, pied
de page) et **un bouton mort corrigé** — « Demander une démo » pointait sur `#`
alors que `demo.html` existe. Hero, sections, effets de défilement et palette :
intacts. Voir `LANDING_FIGEE.md`.

**Contact public.** `POST /api/public/contact` — seule route d'écriture sans
authentification. Limite de débit 5/heure par IP, tailles bornées, aucune donnée
d'établissement lue, et une réponse neutre qui **ne révèle pas** si l'adresse
correspond à un compte. Lecture réservée à l'administration Klassio.

⚠️ **Les pages légales portent des encadrés « à faire valider par un juriste »**
et des champs « à compléter par l'éditeur » (raison sociale, hébergeur, durées
de conservation, droit applicable). **Ne pas les retirer sans validation
juridique réelle** — une mention légale inventée est pire que son absence.

### Campagne de tests k6 — faite le 18/09

Objet : éprouver le produit tel qu'il est, par l'API, avec des assertions
MÉTIER. Un 200 ne prouve rien et n'a jamais été compté comme un succès.

**Ce qui existait a été ÉTENDU, pas remplacé.** `tools/k6/` passe de 6 à 13
scénarios ; `commun.js`, `env.json` et le seeder sont inchangés.

| Ajouté | Ce qu'il éprouve | Checks |
|---|---|---|
| `rbac.js` | matrice des permissions, jeton absent, jeton forgé, non-divulgation de `/api/settings` | 59 |
| `invitations.js` | cycle de vie d'un accès, escalade refusée, usage unique, révocation immédiate | 22 |
| `academique.js` | saisie ≠ proclamation, versions, ce que le parent voit et quand | 16 |
| `recus.js` | sous concurrence, aucun paiement confirmé ne reste sans reçu | 1 375 paiements |
| `ia.js` | l'assistant lit, n'écrit jamais, ne fuit pas | 27 |
| `regressions.js` | les défauts déjà corrigés ne sont pas revenus | 18 |
| `concurrence.js` | deux personnes qui agissent **en même temps** | 17 |
| `complet.js` | l'orchestrateur : les huit scénarios fonctionnels, un seul verdict | **196 / 196** |
| `paliers.sh` | balayage 1 → 100 VUs, tableau p50/p90/p95/p99 | — |

#### Quatre défauts RÉELS trouvés, tous corrigés et verrouillés

**🔴 P1 — Deux guichets pouvaient encaisser deux fois le même solde.**
Mesuré par `concurrence.js` : six guichets soldant ensemble le même frais, une
dette de **350 $ avait encaissé 1 046 $** — sept paiements CONFIRMED, tous
pourvus d'un reçu officiel. Le contrôle de montant existait, mais seulement à la
CRÉATION du paiement, et il ne compare qu'aux paiements déjà confirmés : deux
intentions créées avant toute confirmation passent donc toutes les deux.
Correctif : la validation est refaite **à la confirmation**, sous verrou sur
l'obligation (`db.verrouiller_ligne` — `SELECT … FOR UPDATE` en PostgreSQL,
transaction IMMEDIATE en SQLite). La reprise d'historique garde son passe-droit
explicite (`allow_overpayment`). Verrouillé par
`test_21sexies_deux_guichets_ne_peuvent_pas_encaisser_deux_fois_le_solde`, qui
rend la course déterministe — **vu échouer** (`200 != 400`) sans le correctif.

⚠️ Effet de bord attrapé au passage : la garde se déclenchait aussi sur le
chemin IDEMPOTENT (même paiement confirmé deux fois → refus au lieu de 200). Il
a fallu relire le statut du paiement **sous le verrou**. Détecté par
`test_audit_prerelease.DoubleConfirmationDePaiement`, qui joue 20 tours.

**🔴 P1 — Numérotation des reçus en échec sous concurrence.** 5 essais ne
suffisaient pas (« max + 1 » sur une séquence partagée) : un paiement réussi
finissait en 500, et le reçu manquait. Porté à 25 essais, et **on ne transforme
plus un paiement réussi en erreur** — on renvoie `None` en le journalisant.
`recus.js` : 1 375 paiements confirmés, 0 sans reçu, 0 erreur 500.

**🔴 P1 — Versionnement des notes absent en saisie manuelle.** Deux lignes
`is_current=1` pour le même élève/matière/période. Corrigé dans `record_grades`.

**🟢 Vocabulaire de refus de l'IA.** « Passe l'abonnement en payé. » recevait un
`fallback` honnête (« je n'ai pas assez d'informations ») : rien n'était écrit,
mais rien n'était refusé non plus. `ai_assistant.py` ne contient **aucun**
INSERT/UPDATE/DELETE — la lecture seule est garantie par construction, pas par
un filtre. Ajout de l'entité `abonnement` et d'un verbe précis.

#### Un faux positif dans MES PROPRES tests, corrigé

`regressions.js` interrogeait `/api/students/<id>/finance` — une route qui
n'existe pas (c'est `/financial-summary`). Les comparaisons « avant/après »
valaient `0 === 0` et passaient au vert **sans rien mesurer**. Un garde-fou
exige désormais que la route réponde 200 avant toute comparaison. De même,
`concurrence.js` C1 refuse de conclure si une requête a été étranglée (429) :
« une seule réussit » serait vrai sans que la prise atomique ait été éprouvée.

#### Ce qui a été REFUSÉ

L'acceptation d'une invitation est plafonnée à **10 tentatives / 5 min / IP**
(bucket `invite_accept`). Une campagne `complet.js` en consomme 9 : deux
campagnes coup sur coup déclenchent la protection. **La protection n'a pas été
desserrée** — on ne touche pas à une règle de sécurité pour faire verdir un
test. Les scénarios concernés s'arrêtent avec un message qui l'explique.

#### 🟠 → 🟢 Le wifi de l'école — résolu le 18/09

Le plafond comptait TOUTES les tentatives, réussies comprises, et la clé est
l'adresse IP. Or les parents d'une école congolaise acceptent leur invitation
depuis le wifi de l'établissement : ils partagent une seule adresse. Le jour de
la rentrée, **le onzième parent était refusé parce que dix voisins avaient
réussi avant lui**. La protection frappait exactement les gens qu'elle devait
servir.

Correctif — la règle que le code appliquait déjà à la connexion, étendue aux
quatre routes publiques qui gardent un secret (`invite_lookup`, `invite_accept`,
`reset_lookup`, `reset_apply`) :

1. **Seul un échec SUR LE SECRET consomme le budget.** Un jeton inconnu est le
   signal d'énumération ; une inscription réussie n'est pas un abus.
2. **Une réussite efface l'ardoise de l'adresse** (`security.clear_attempts`) —
   sinon une poignée de liens tronqués par WhatsApp finirait par bloquer toute
   l'école.
3. Un jeton RÉEL mais déjà utilisé, révoqué ou expiré **ne compte pas** : son
   porteur l'a bien reçu. `_invitation_state` distingue ces cas de « inconnue ».

**Aucun plafond n'a été desserré.** C'est plus strict pour un attaquant — qui
échoue à chaque coup et se fait couper aussi vite qu'avant — et ouvert pour une
école entière. Trois tests, chacun falsifié séparément :

| Test | Vu échouer sans le correctif |
|---|---|
| `test_20bis_le_wifi_de_l_ecole_ne_bloque_pas_les_parents` | « le parent 10 a été refusé : 429 » |
| `test_20ter_l_enumeration_de_jetons_reste_coupee` | 15 jetons inventés jamais bloqués |
| `test_20quater_quelques_liens_cassés_ne_bloquent_pas_toute_l_ecole` | 429 au 11ᵉ lien cassé |

Effet de bord bienvenu : le seeder n'entame plus le compteur, et **deux
campagnes `complet.js` enchaînées passent à 100 %** — vérifié. L'étape manuelle
de vidage de `rate_limit_attempts` documentée plus tôt a été retirée.

#### Montée en charge — mesurée, pas estimée

`tools/k6/paliers.sh` rejoue le MÊME parcours métier (une matinée d'école) avec
de plus en plus d'utilisateurs. SQLite, gunicorn 2 workers × 4 threads, portable
local — **la production tourne sur PostgreSQL**, ces chiffres ne s'y transposent
pas tels quels.

| VUs | p50 | p90 | p95 | p99 | erreurs | req/s | checks KO |
|---|---|---|---|---|---|---|---|
| 1 | 16 ms | 23 ms | 42 ms | 224 ms | 0 % | 1,4 | 0 |
| 5 | 15 ms | 23 ms | 27 ms | 51 ms | 0 % | 6,3 | 0 |
| 10 | 16 ms | 27 ms | 37 ms | 67 ms | 0 % | 12,4 | 0 |
| 25 | 22 ms | 85 ms | 126 ms | 215 ms | 0 % | 28,2 | 0 |
| 50 | 215 ms | 604 ms | 709 ms | 939 ms | 0 % | 41,2 | 0 |
| 100 | 252 ms | 591 ms | 691 ms | 932 ms | 0 % | 84,4 | 0 |

**Le coude est entre 25 et 50 utilisateurs simultanés** — c'est le plafond des
8 fils de gunicorn (2 × 4). Au-delà, les requêtes font la queue : la latence
monte d'un cran puis **reste stable** de 50 à 100 VUs pendant que le débit
double (41 → 84 req/s). Dégradation propre : **0 % d'erreur et 11 595 checks
tous verts à 100 VUs**. Un seul seuil franchi, `klassio_dossier_eleve`
(765 ms pour 500 ms visés) : le seuil datait d'une mesure à 30 VUs. **Il n'a pas
été relevé** — il fait son travail.

Écritures concurrentes, même campagne : `recus.js` 770 paiements confirmés, 0
sans reçu, 0 erreur 500 ; `finance.js` 1 063 paiements acceptés, **0 double
comptage**, 4 145/4 145 checks. Le verrou ajouté ne produit aucun
« database is locked ».

⚠️ **Non rejoués** : `pic.js` et `audit.js` lisent `env-echelle.json`, le jeu à
5 écoles × 2 000 élèves du 13/09, absent de la base courante. Les relancer
demande de refaire ce peuplement.

#### 🟠 → 🟢 6 896 paiements confirmés sans reçu — réparés le 18/09

Relevé sur la base de travail. Tous antérieurs au premier reçu jamais émis : le
mécanisme d'émission est arrivé après coup et il est correct depuis. Aucun
paiement récent n'était concerné.

Vérification avant d'écrire : **aucun établissement ne mélangeait les deux cas**
— chacun avait soit tous ses reçus, soit aucun. La numérotation étant *par
établissement*, les cinq concernés repartent de `REC-2026-00001` dans l'ordre
des confirmations. Pas d'inversion chronologique, qui aurait été inacceptable
sur une pièce comptable.

`backend/tools/reparer_recus.py --appliquer` — strictement additif, il n'écrit
que des lignes `receipts` par la fonction du circuit normal (`issue_receipt`) :
un reçu réparé est indiscernable d'un reçu émis à l'encaissement. Sauvegarde
préalable : `backend/klassio.db.avant-reparation-recus-20260918-015558`.

Après : **0 paiement confirmé sans reçu, 0 doublon, 0 numéro en collision**, et
chaque établissement a une séquence contiguë de `00001` à N.

⚠️ **Un autre invariant reste violé** : 16 jetons de session stockés en clair,
tous datés du 8 au 10/09 — la dernière session en clair est du 10/09 à 13 h 38,
la première hachée du 10/09 à 14 h 19. Le code est correct depuis
(`create_session` ne stocke que l'empreinte SHA-256) ; ce sont 16 lignes mortes,
expirées depuis, antérieures au correctif. **Non supprimées** — une suppression
dans les données réelles se décide, elle ne se glisse pas dans un lot de
corrections.

#### Piège d'environnement à connaître

Le seeder crée les comptes de rôle **en acceptant de vraies invitations**.
Avant le 18/09, le compteur `invite_accept` était donc déjà à 10/10 juste après
le peuplement, et la campagne échouait sans le moindre défaut. **Résolu** par le
correctif ci-dessus : une acceptation réussie ne consomme plus rien. Vérifié —
compteur vide après peuplement, deux campagnes enchaînées à 100 %.

#### État des suites

- SQLite : **332 tests OK** (5 ajoutés).
- PostgreSQL 16 réel : **16/16 modules verts** — c'est là que vit le `FOR UPDATE`.
- k6 fonctionnel : **196 / 196 checks**, 14 seuils tenus.

### Prochaine étape

1. **Adaptateur fournisseur Mobile Money** — c'est lui qui débloquera
   `PENDING`/`PROCESSING`/`UNKNOWN`, les webhooks et la réconciliation. Tant
   qu'il n'existe pas, ne pas simuler ces états.
2. Le reste du brief maître (IA, aide & support, légal) — après.
3. **Tarifs** : toujours en attente d'une décision du propriétaire (voir plus haut).
4. **Bulletins PDF** et notifications de calendrier (§15) — jamais commencés.

---

## 1. Ce qu'est Klassio, en trois lignes

SaaS de gestion scolaire multi-établissement pour la RDC. Backend Flask,
frontend en HTML/JS sans framework, PostgreSQL en cible de production.
L'élève est l'entité centrale — **il n'existe aucun compte « élève »** : quatre
rôles seulement (directeur, discipline, professeur, parent).

---

## 2. Où en est le projet — état au 2026-09-14

**Le produit est fonctionnel et solide. P1 et P2 sont faits. Deux défauts P0
trouvés par l'audit du 14 septembre ont été reproduits puis corrigés. Le
déploiement n'a toujours jamais été fait.**

| | |
|---|---|
| Tests | **312, tous verts**, sur SQLite **et** PostgreSQL 16 réel (16/16 modules) |
| Sécurité | audité, exploité, corrigé (XSS stocké, isolation, idempotence) |
| Isolation multi-tenant | **zéro fuite** sur des dizaines de milliers de tentatives croisées, jusqu'à 450 utilisateurs simultanés |
| Performance | 116 req/s, aucune erreur applicative jusqu'à 450 VU |
| Moteur actif | **SQLite** (`KLASSIO_DB_BACKEND=sqlite`) — bascule volontairement gelée |
| Déploiement | **jamais fait**. Pas de dépôt git, pas d'hébergement |

### Pourquoi la bascule PostgreSQL est gelée

Mesuré depuis Kinshasa vers Supabase (Irlande) : ~300 ms par requête, 1,9 s par
ouverture de connexion. Une page en déclenche des dizaines. **La bascule n'a de
sens qu'une fois le backend hébergé en Europe, près de la base.** La migration
elle-même est faite et vérifiée (53 tables, 137 132 lignes copiées).

---

## 3. Ce que l'audit du 14 septembre a trouvé et corrigé

Quatre correctifs, tous reproduits avant d'être écrits, tous couverts par un
test qui échoue sans le correctif.

### P0-a — notes non proclamées visibles du parent (fuite inter-années)

`published_period_labels()` comparait les périodes par leur seul LIBELLÉ, et
`grades` ne portait aucune année. Or « Période 1 » existe chaque année :
proclamer la Période 1 de 2025-2026 rendait visibles aux parents les notes de
la Période 1 de 2026-2027, jamais proclamées. **Invisible la première année**
— il n'y a alors qu'un millésime, donc aucune collision.

Correctif : `grades.academic_year_id` et `appreciations.academic_year_id`
(migration additive, rétro-remplie depuis la classe), et la clé de publication
devient `(année, libellé)` — `school.published_period_keys()`. Fermeture par
défaut : un résultat sans année reste invisible du parent.

### P0-b — invitation à usage unique consommée deux fois

L'invitation n'était marquée « acceptée » qu'en fin de route. Deux
acceptations simultanées lisaient donc toutes les deux `pending`. **Mesuré :
deux comptes parent créés, tous deux rattachés au même enfant.** Un lien
transféré par WhatsApp — cas courant — donnait à un tiers l'accès au dossier.

Correctif : prise atomique (`UPDATE … WHERE status='pending'` + `rowcount`),
dans la même transaction que les rattachements. Le perdant repart en 404 sans
rien avoir écrit.

### P0-c — appréciation d'une année écrasant celle de l'année précédente

Le remplacement portait sur (élève, période, domaine) sans l'année : saisir
« Période 1 / Langage » en 2027 supprimait la ligne de 2026. Perte de données
silencieuse. Correctif : le `DELETE` est borné à l'année.

### P1 — `tenant_id` dans les sous-requêtes : **fait**

`api_school.py` (`class_students`, 4 sous-requêtes) et `app.py`
(`list_classes`, 5 sous-requêtes, dont `students` et `class_teachers` que le
rapport d'origine n'avait pas relevées).

Mesuré sur 800 000 lignes de présence (10 000 élèves × 80 jours) :

| | |
|---|---|
| Avant | 12 369 ms — plan : `SCAN x` |
| Après | 2,4 ms — plan : `SEARCH x USING INDEX idx_attendance_student` |
| Gain | **4 883×** |

### Trois défauts mineurs trouvés en chemin

- `POST /api/invitations` renvoyait **500** sur un corps JSON qui n'est pas un
  objet (`data.get` sur une chaîne). `or {}` ne protégeait pas : une chaîne
  JSON non vide est vraie. Un accesseur unique, `validation.json_object()`,
  couvre désormais **61 lectures de corps** dans les six modules d'API.
- `assets/js/page-invitation.js` référençait une variable hors portée dans un
  `try/catch` vide : `klassio_portal` n'était jamais enregistré, en silence.
  Disparu avec la réécriture de la page.
- `api.firstName("M. Jean Kabasele")` renvoyait « M. », d'où un « Bienvenue,
  M.. » sur le premier écran vu par un enseignant. Les civilités sont
  maintenant ignorées.

### Contraste

Le jeton global `--ink-faint` donne **3,80:1** en thème sombre et **3,17:1**
en thème clair sur fond de carte — sous le seuil AA de 4,5:1. Les composants
d'accueil utilisent `--ink-soft` (mesuré 6,6 à 8,0:1). **Le jeton global n'a
pas été touché** : il est utilisé dans toute l'application, et ce choix
revient au produit, pas à un correctif de passage.

### P2 — garde-fou sur le plan d'exécution : **fait**

`backend/tests/test_plans.py`. Interroge le planificateur plutôt que les
résultats, sur les deux moteurs (`EXPLAIN QUERY PLAN` côté SQLite, `EXPLAIN`
sur données semées côté PostgreSQL, dont le planificateur est fondé sur le
coût et choisit toujours un balayage sur une table vide).

Le fichier contient un test qui rejoue la requête **fautive** et exige que le
plan la trahisse : un garde-fou qu'on n'a jamais vu se déclencher ne garde
rien. Cette précaution a servi immédiatement — la première version cherchait
`SCAN attendance` alors que SQLite annonce `SCAN x`, et passait donc à vide.

### Welcome Experience parent et professeur : **faite**

Parcours en cinq temps — accueil, contexte réel, activation, traitement,
succès — dans `app/invitation.html` et `assets/js/page-invitation.js`.

Ce qui a été ajouté côté serveur : `memberships.onboarding_completed_at` et
`memberships.staff_code` (identifiant interne `TCH-XXXX-XXXX`, généré par le
serveur, refusé s'il vient du client) ; `GET`/`POST /api/me/onboarding`
(idempotent, avec `replay` pour « Revoir l'introduction ») ; états
d'invitation distincts (`utilisee`, `revoquee`, `expiree`, `inconnue`) au lieu
d'un unique message ; contexte enseignant enrichi (effectifs, cycle,
titularité) ; réponse d'acceptation qui **relit la base après le commit**
plutôt que de recopier ce que la page affichait.

Vérifié dans le navigateur, pas seulement en test :

- le chargeur dure exactement le temps de la requête — prouvé en ralentissant
  `/accept` de 3,5 s : **la coche n'apparaît pas** tant que le serveur n'a pas
  répondu ;
- réseau coupé → message honnête (« votre compte n'a peut-être pas été créé »),
  **aucune coche**, bouton Réessayer qui rejoue la même demande ; après
  rétablissement : 1 compte, 1 lien, 0 doublon, 0 compte orphelin ;
- lien déjà consommé → « Ce compte est déjà activé » + Se connecter, au lieu
  d'un « lien invalide » trompeur ;
- mobile 375 px, thème clair et sombre, `prefers-reduced-motion` (animations
  neutralisées, parcours intact).

**OTP non implémenté**, décision explicite : il n'existe aucun canal d'envoi
SMS dans le projet, et une vérification qui ne vérifie rien serait une fausse
fonctionnalité. Le lien d'invitation reste la preuve de réception, le mot de
passe la preuve de possession.

### Audit pré-release — ce qui a été passé au crible

**Financial Core.** Un défaut de concurrence trouvé et corrigé : `confirm_payment`
lisait le statut puis écrivait sans condition. Mesuré avant correctif, **8 doubles
confirmations simultanées sur 40** produisaient deux écritures au grand livre et
**deux notifications au parent** pour un seul paiement. C'est le scénario d'un
webhook Mobile Money rejoué. Corrigé par transition atomique ; 0 sur 40 après.

Le reste du noyau financier tient : montants nul, négatif, texte, NaN, infini et
hors-limite tous refusés ; partiel → soldé correct ; idempotence exacte (même clé
+ même charge = même paiement, même clé + autre montant = refus) ; isolation
croisée en 404 dans les deux sens.

**Import.** Un CSV renommé `.xlsx` et un `.xlsx` tronqué renvoyaient **500**.
Corrigé : message qui désigne le fichier. Le verrou de double confirmation
fonctionnait déjà (200 + 409, 2 élèves et non 4), l'isolation aussi.

**Sonde de santé.** `/api/health` répondait `{"status":"ok"}` **sans jamais
interroger la base**. Elle aurait continué à dire que tout va bien avec la base
injoignable. Elle vérifie désormais, et répond 503 sinon.

**Trop-payé.** Le parent lisait « Reste **-40,00 $** ». Affiché désormais
« Avance 40,00 $ ».

**Ce qui a tenu, vérifié et non corrigé :**

- *IA* : `ai_assistant.py` ne contient **aucun** INSERT/UPDATE/DELETE — la
  lecture seule est architecturale, pas un filtre de mots. 10 tentatives
  d'écriture (dont anglais, fautes de frappe, « ignore tes instructions »,
  fausse autorisation) : rien écrit. Aucune fuite inter-établissement ni de
  périmètre parent.
- *Sessions* : changer le mot de passe révoque **toutes** les sessions, y
  compris celle qui a fait le changement ; ancien mot de passe refusé ;
  déconnexion effective.
- *Fichiers* : stockés en data-URI en base, donc **aucune URL à deviner**.
  HTML, SVG et exécutables refusés ; lecture croisée en 404 ; plafond appliqué.
- *Notifications* : sur une absence, **une seule** notification, au bon parent.
  Ni le parent de l'autre élève, ni celui d'un homonyme d'un autre
  établissement.
- *Boutons* : 68 boutons porteurs d'un identifiant, **aucun mort**. Pages des
  trois rôles chargées sans erreur.
- *IDOR* : parent → élève non autorisé = 404 ; routes de Direction = 403 ;
  `/settings` correctement filtré pour le parent (3 champs).

## 3bis. Fondation académique — ce qui a été construit et éprouvé

**Structures pilotées par les données.** Une école déclare six périodes au
primaire et quatre au secondaire dans la MÊME année ; une autre en déclare
trois ; une troisième dix aux noms libres. Aucun nombre, aucun vocabulaire
(« trimestre », « semestre ») n'est écrit dans le code.

**État d'une période** : ce que la Direction décide (DRAFT / LOCKED / ARCHIVED)
prime ; sinon l'état se déduit des dates (UPCOMING / OPEN / CLOSING / CLOSED).
Personne n'a à cliquer quoi que ce soit le 1er novembre pour que la période 2
commence.

**Verrou et réouverture.** Une période verrouillée refuse la modification ET la
saisie de notes, côté serveur, y compris avec un payload retouché. La
réouverture exige un motif d'au moins 10 caractères, enregistre qui/quand/
pourquoi, et se referme avec le verrou suivant.

**Audience de publication recalculée au serveur.** Le navigateur envoie des
CRITÈRES (classes, niveaux, élèves) ; le serveur repart des élèves réels.
Vérifié : un élève d'un autre établissement, une classe étrangère, un
identifiant inventé ou un élève archivé ne produisent aucun destinataire.

**Politique de diffusion configurable** (`tenant_settings.results_policy`) :
`always` par défaut — aucune école ne se voit imposer une condition financière
qu'elle n'a pas demandée. En mode `balance`, un plafond et des classes
exemptées. Elle gouverne la DIFFUSION : le résultat officiel reste au dossier
et reste visible du personnel.

### Défauts trouvés pendant cette phase

| | |
|---|---|
| `/reopenings` répondait `200 []` à une autre école | corrigé — 404, relevé par la passe d'isolation du release gate |
| Modification partielle non validée contre les dates en base | corrigé — une fin antérieure au début enregistré passait |
| Unicité `(tenant, année, libellé)` sans la division | corrigé — une école ne pouvait pas nommer « Période 1 » au primaire ET au secondaire. Contrainte de table remplacée par un index, table reconstruite (12 lignes avant / 12 après sur la base de dev) |
| **`/api/students/:id/bulletin` ignorait `only_published`** | corrigé — **défaut préexistant** : un parent obtenait par cette route des résultats jamais proclamés, que `/api/students` lui refusait |
| `schema_postgres.sql` non régénéré | corrigé — il est DÉRIVÉ de `schema.sql` par `tools/pg_schema.py` |

### Preuve que les tests ne sont pas aveugles

Cinq régressions injectées une par une, puis restaurées :

| Régression injectée | Tests en échec |
|---|---|
| l'audience fait confiance à la liste du client | 5 |
| le verrou laisse tout passer | 2 |
| la prise atomique de publication retirée | 3 |
| `only_published` retiré du bulletin | 1 |
| la division retirée de la clé d'unicité | 1 |

Couverture de `api_academics.py` : **67 % → 90 %**. `school.py` : 86 % → 93 %.

## 3ter. Import des résultats officiels

`backend/results_import.py` + 5 routes dans `api_academics.py`. Klassio ne
calcule pas les notes : l'établissement les calcule, Klassio les reçoit, les
rapproche, signale ce qui cloche, et n'écrit qu'après validation.

**Le nom n'est jamais un identifiant.** Rapprochement sur le code élève ; à
défaut le nom, mais alors signalé « à vérifier » et jamais compté comme sûr ;
deux homonymes produisent une erreur, pas un choix arbitraire.

**Rien d'ambigu n'entre en base.** Une seule ligne en erreur bloque tout
l'import. Sont bloquants : code inconnu, note hors barème, doublon dans le
fichier, matière absente, période différente de celle de l'import.

**Un élève absent du fichier n'a pas zéro** — il n'a pas de résultat, et la
liste nominative des absents est remontée.

**Versionnage.** Un second import ne supprime rien : les résultats en place
passent en `is_current = 0`, datés et rattachés à l'import qui les a remplacés.
`/api/results/history` expose toutes les versions.

**L'import ne publie JAMAIS.** La proclamation reste la décision distincte
validée en §3bis, avec son audience.

### Défauts trouvés pendant cette phase

| | |
|---|---|
| « Cote /20 » détecté comme barème au lieu de note | corrigé — ordre de détection : la note avant le barème |
| **`grades_for_student` ignorait `is_current`** | corrigé — après deux versions, le parent voyait **les deux notes** de la même matière |
| `_parse_uploaded_table` inaccessible depuis api_academics | déplacé dans `ingestion.py` (import circulaire sinon) |
| 3 routes d'import hors du balayage d'isolation | corrigé — le balayage couvre **65/69** routes (62 avant) |

Six régressions injectées puis restaurées, toutes détectées : nom traité comme
preuve, doublons non détectés, erreurs non bloquantes, écrasement silencieux de
version, prise atomique retirée, filtre de version courante retiré.

Couverture : `results_import.py` **91 %**, `api_academics.py` **90 %**.

## 3quater. Écran d'import des résultats

`app/resultats.html` + `assets/js/page-resultats.js`, entrée « Résultats » au
menu de la Direction uniquement.

Parcours exercé à la main dans le navigateur, avec de vrais fichiers :

| | |
|---|---|
| Fichier à anomalies | 5 lues, 3 rapprochées, 2 erreurs · **aucun bouton « Importer »** · anomalies détaillées ligne par ligne |
| Élève absent du fichier | nommé explicitement — « ce n'est pas un zéro » |
| Fichier propre | 3 résultats écrits, version 1, `source='import'` |
| Second import | version 2 courante, version 1 conservée et datée |
| Après import | **période non proclamée, 0 publication** en base |
| Rôle parent | « Import réservé à la Direction », et pas d'entrée de menu |

**Colonnes reconnues sans configuration** : « ID Élève », « Branche »,
« Cote /20 » ont été rattachées automatiquement à identifiant, matière et
résultat.

### Un défaut préexistant trouvé en chemin — `loader.js`

`show()` posait la classe `shown` dans un `requestAnimationFrame` ; `hide()`
appelé avant cette frame retirait une classe pas encore posée, puis la frame
l'ajoutait. **Le voile plein écran restait affiché et avalait tous les clics.**
Se déclenche quand la réponse arrive en moins d'une frame — cas courant en
local. L'import des élèves y échappait par accident (un `setTimeout` précédait
son `hide()`). Corrigé : `hide()` annule la frame en attente.

### Contraste

Les encadrés `.notice` en thème clair donnaient 3,89 et 4,49 pour 1 avec les
jetons globaux `--warn` et `--ok` — sous AA. Teintes assombries dans le
composant (6,8 à 7,6 en clair, 6,2 à 7,7 en sombre). **Les jetons globaux ne
sont pas touchés.**

Six régressions frontend injectées puis restaurées, toutes détectées : envoi de
compteurs au serveur, `setTimeout` simulant le succès, publication depuis
l'écran d'import, correctif du voile retiré, entrée de menu donnée au parent,
route inexistante appelée.

## 4. Décisions prises — ne pas les rouvrir

- **Architecture** : PostgreSQL derrière Flask. Le backend garde son modèle de
  sécurité (`school.py`, périmètres par rôle). L'option « tout via Supabase
  RLS » a été écartée.
- **Aucun chatbot.** L'IA de Klassio est ambiante et contextuelle, jamais une
  fenêtre de conversation. Elle est **strictement en lecture seule** — toute
  demande d'écriture est refusée et journalisée.
- **L'élève n'est pas un compte utilisateur.**
- **Hébergement recommandé** : Heroku région `eu`. Déploiement confié à
  Emergant ; son livrable unique est `DEPLOIEMENT.md`.
- **Six lignes orphelines** dans `invitation_classes` : conservées, ne pas
  supprimer sans décision commune.
- **SQLite reste le moteur de développement.** Mesuré : il produit de vraies
  erreurs sous concurrence (93 `database is locked`, 60 `disk I/O error`) que
  PostgreSQL ne produit jamais. C'est un outil de développement, pas de
  production.

## 5. Contraintes posées par l'utilisateur

1. Ne pas modifier l'architecture fonctionnelle.
2. Ne supprimer aucune donnée.
3. Ne pas lancer le déploiement définitif.
4. Ne pas casser les tests existants.
5. Garder la compatibilité SQLite (dev) **et** PostgreSQL (prod).
6. Documenter un problème **avant** de proposer une correction.
7. Consolider la documentation — ne pas empiler de nouveaux fichiers.

---

## 6. Commandes utiles

```bash
# Tests — SQLite
backend_venv/bin/python -m unittest discover -s backend/tests -t backend

# Tests — PostgreSQL 16 RÉEL, local, jetable (~30 s, sans Docker ni réseau)
backend_venv/bin/python backend/tools/pg_tests.py

# Invariants de données (26 contrôles, sortie non nulle si violation)
backend_venv/bin/python backend/tools/verifier_invariants.py

# Voir le produit tourner
backend_venv/bin/gunicorn --chdir backend --workers 2 --threads 4 \
  --worker-class gthread --bind 127.0.0.1:5001 app:app &
python3 -m http.server 4173      # puis http://localhost:4173/app/connexion.html

# État Supabase
bash tools/supabase.sh etat
```

### Rejouer l'audit de performance

```bash
# 1. Jeu à grande échelle sur une base jetable (refuse de toucher klassio.db)
KLASSIO_DB_PATH=/tmp/klassio_echelle.db \
  backend_venv/bin/python backend/tools/seed_echelle.py --ecoles 5 --eleves 2000 --jours 80

# 2. Serveur sur cette base, port 5010
# 3. Campagne k6
k6 run -e ECOLES=5 -e VUS=40 -e PROFIL=sain tools/k6/audit.js
k6 run tools/k6/pic.js
```

`PROFIL=complet` inclut les deux routes lentes ; `PROFIL=sain` les écarte pour
mesurer le reste. Résultats de référence : `tools/k6/resultats/campagne.json`
(42 paliers).

---

## 7. Outils du projet

| Outil | Rôle |
|---|---|
| `backend/tools/pg_tests.py` | Suite contre PostgreSQL local embarqué, ou Supabase en schéma isolé |
| `backend/tools/verifier_invariants.py` | 26 invariants de données |
| `backend/tools/reparer_recus.py` | Émet les reçus manquants d'anciens paiements |
| `backend/tools/seed_echelle.py` | Jeu de données à grande échelle |
| `backend/tools/seed_charge.py` | Deux établissements réalistes via l'API |
| `backend/tools/charge_locale.py` | Scénarios de charge en Python, sans k6 |
| `backend/tools/release.py` | Phase `release` du déploiement |
| `tools/k6/audit.js`, `pic.js` | Scénarios k6 paramétrables |
| `tools/supabase.sh` | `etat`, `verifier`, `mot-de-passe` |

**k6 v2.2.0 et le serveur MCP k6 v0.6.1 sont installés et approuvés.** Les six
outils MCP (`run_script`, `validate_script`, `info`, `list_sections`,
`get_documentation`, `search_terraform`) sont disponibles.

---

## 8. Deux copies du projet — attention

- `/Users/macbookpro/klassio-saas` — **copie principale**, c'est là que tout
  doit être créé.
- `/Users/macbookpro/Desktop/klassio-saas` — miroir ouvert dans VS Code.

```bash
rsync -a --delete --exclude 'backend/klassio_test.db*' --exclude '.DS_Store' \
  --exclude '__pycache__' --exclude 'backend_venv' \
  --exclude 'tools/k6/env-echelle.json' --exclude 'tools/k6/env-pg.json' \
  /Users/macbookpro/klassio-saas/ /Users/macbookpro/Desktop/klassio-saas/
```

`--delete` efface du miroir ce qui n'existe pas dans la copie principale. Un
fichier créé seulement dans le miroir sera perdu — c'est déjà arrivé avec
`.mcp.json`.

---

## 9. Ce qui reste à faire, par ordre

- [x] ~~P1 — `tenant_id` dans les sous-requêtes~~ — fait, mesuré 4 883× (§3).
- [x] ~~P2 — garde-fou sur le plan d'exécution~~ — fait, bi-moteur (§3).
- [x] ~~Welcome Experience parent et professeur~~ — faite et vérifiée dans le
      navigateur (§3). Reste ouvert : l'OTP (aucun canal SMS), et le parcours
      du Directeur des disciplines qui n'a qu'un écran de contexte générique.
- [x] ~~Audit pré-release~~ — fait (§3). Restent les points listés ci-dessous,
      qui demandent un environnement déployé ou une décision produit.
- [x] ~~Système académique — FONDATION~~ : faite et éprouvée (§3bis).
      `grades.period_id` remplace le libellé libre comme clé ; structures
      configurables par division ; verrou et réouverture motivée ; audience de
      publication recalculée au serveur ; politique de diffusion configurable.
- [x] ~~Import des résultats officiels~~ (Excel/CSV) — fait et éprouvé (§3ter).
      **Backend seulement : aucune interface n'est encore branchée dessus.**
- [x] ~~Écran d'import des résultats~~ — fait (`app/resultats.html`,
      `assets/js/page-resultats.js`), parcours exercé à la main dans le
      navigateur (§3quater).
- [x] ~~Espace professeur (§8–§9)~~ — fait le 17/09 : il entre par ses classes,
      `classes.html` est sa page d'arrivée, `dashboard.html` l'y redirige,
      `renderProfesseur` supprimé, table `PORTE` corrigée. Détail en §0.
- [x] ~~Invitations (§16)~~ — fait le 17/09 : `etablissement.html` découpé en
      trois onglets, « Équipe & accès » réunit rôster et invitations. Détail en §0.
- [x] ~~Reste du frontend académique~~ — fait le 17/09 : écran de calendrier
      (périodes, dates, échéances, verrou/réouverture), aperçu d'audience avant
      proclamation, portail parent « prochaine proclamation ». Détail en §0.
- [x] ~~Discipline Direction / DD (§11)~~ — fait le 17/09 : onglet « Vue
      d'ensemble » pour la Direction, poste de travail inchangé pour le DD.
- [x] ~~Audit fonctionnel global~~ — fait le 17/09 : 42 écrans, 11 garanties
      éprouvées contre le serveur, un défaut trouvé et corrigé
      (`catalog-items` sans permission). Détail en §0.
- [ ] **Bulletins PDF** et notifications de calendrier (§15 du cahier des charges).
- [ ] **P3 — tableau de bord** : 28 requêtes SQL, agrégats sans `LIMIT`.
      Croissance mesurée 92 → 141 ms quand l'historique quadruple. Tient
      aujourd'hui, à traiter si le produit vise de plus gros établissements.
- [x] ~~Initialiser le dépôt git~~ — fait le 18/09.
      **`git@github.com:Yversplayer/klassio-saas.git`, dépôt PUBLIC** (choix du
      propriétaire, après recommandation inverse : le code porte tout le modèle
      de sécurité). Exclus par `.gitignore` et vérifiés absents du distant :
      `backend/.env` (clé de service Supabase, mot de passe de la base) et tous
      les `*.db` (élèves mineurs nommés, responsables, paiements, empreintes de
      mots de passe). 198 fichiers, 4,7 Mo. Accès par clé SSH ed25519 **sans
      phrase de passe** — elle vaut donc ce que vaut l'accès au portable.
- [ ] Confier le déploiement Heroku à Emergant — `DEPLOIEMENT.md` §3.3.
- [ ] Jouer une fois `pg_tests.py --supabase` avant la bascule (seul mode qui
      exerce le pooler en mode transaction).
- [ ] Ne basculer `KLASSIO_DB_BACKEND=postgres` qu'**après** hébergement européen.
- [ ] Après mise en production : drain de logs, sauvegardes Supabase vérifiées,
      supervision de `/api/health`.

### Non vérifié — à savoir

- Comportement réel sur Supabase depuis un dyno européen (mesures faites en
  local, sans latence réseau).
- Test d'endurance : campagne la plus longue = 60 s par palier. La mémoire est
  restée plate, mais ce n'est pas une preuve sur plusieurs heures.
- Accessibilité clavier et lecteur d'écran.
- `backend/klassio.db` (base de DÉVELOPPEMENT) : 16 jetons de session en clair
  d'avant le hachage, et la table `import_sessions` absente. (Les reçus
  manquants, eux, ont été réparés le 18/09.)
  `verifier_invariants.py` signale donc 2 violations qui ne concernent PAS le
  code — `security.create_session` hache bien. Un `db.init_db()` sur cette base
  créerait les tables manquantes sans rien effacer ; non fait, contrainte
  « ne supprimer aucune donnée ».
- Contraste du jeton global `--ink-faint` : sous AA dans les deux thèmes (§3).
  Non corrigé globalement — décision produit.
- **8 états de paiement sur 10 sont inatteignables.** Le schéma déclare
  `PENDING PROCESSING FAILED CANCELLED EXPIRED UNKNOWN REFUNDED REVERSED` ;
  le code ne produit que `CREATED` et `CONFIRMED`. Il n'existe **ni
  remboursement, ni annulation, ni traitement d'un `UNKNOWN`**. Qui lit le
  schéma croit ces fonctions présentes : elles ne le sont pas. À implémenter
  avec l'adaptateur du vrai fournisseur, pas avant.
- **Pas de validation par signature de fichier.** Un contenu quelconque déclaré
  `data:image/png` est accepté. Non exploitable — le navigateur suit le type
  déclaré, un faux PNG s'affiche cassé — mais du contenu invalide entre en base.
  Non corrigé : une liste de signatures mal calibrée rejetterait de vrais
  fichiers, ce qui serait pire.
- **Aucune détection de doublons à l'import.** Deux lignes identiques créent
  deux élèves. À traiter avec l'import des résultats, qui en a besoin de toute
  façon.
- **Injection de formule.** Un nom `=cmd|'/c calc'!A1` est stocké tel quel.
  Inerte aujourd'hui — **aucun export CSV n'existe**. À neutraliser le jour où
  un export est ajouté.
- **Sauvegardes jamais testées.** Aucune restauration n'a été exercée ; RPO et
  RTO ne sont pas établis. « Supabase fait des sauvegardes » n'est pas une
  stratégie vérifiée.
- **Pas de journalisation structurée** (request id, latence, dépendance en
  échec). À faire avec le déploiement, où elle devient utile.

---

## 10. Historique des audits

Trois passages successifs, tous documentés en détail ailleurs :

| Date | Passage | Où |
|---|---|---|
| 2026-09-12 | Mise en production : déploiement, portabilité PostgreSQL, CORS, réserve de connexions, index | `DEPLOIEMENT.md` §1.1–1.5 |
| 2026-09-12 | Release gate : XSS stocké exploité puis corrigé, import non atomique, six faux succès, jetons dans les logs | `DEPLOIEMENT.md` §1.10 |
| 2026-09-12 | Tests sérieux : session d'import, colonne Prénom ignorée, rang de bulletin faux, compression gzip, purge des sessions | `DEPLOIEMENT.md` §1.11 |
| 2026-09-13 | Performance et scalabilité : 42 paliers k6, SQLite vs PostgreSQL | `RAPPORT_PERFORMANCE.md` |

Quatre documents en tout, et pas un de plus : `REPRISE.md` (ici),
`DEPLOIEMENT.md` (audit + procédure pour Emergant), `RAPPORT_PERFORMANCE.md`,
`README.md`. Les documents intermédiaires ont été supprimés à mesure.
