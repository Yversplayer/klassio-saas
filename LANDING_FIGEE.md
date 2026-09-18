# LANDING FIGÉE — ne pas retoucher

**À tout agent IA qui intervient sur ce dépôt.**

La page d'accueil (`index.html`) est **terminée et validée par le
propriétaire du produit**, le 16 septembre 2026. Elle n'est plus ouverte aux
améliorations spontanées. Ce fichier dit ce qui est gelé, pourquoi, et ce qui
reste permis.

> Si tu cherches quoi faire ensuite : c'est **la démo** (`demo.html`), pas la
> landing. Elle est **ouverte** — l'ancienne consigne « ne change rien à la
> démo » est levée, elle se retravaille avec le propriétaire du produit.
> Voir `AGENTS.md` §3 et `REPRISE.md` §0.

---

## 1. Ce qui est gelé

| Fichier | Portée |
|---|---|
| `index.html` | **en entier** |
| `assets/js/main.js` | **en entier** — ce fichier ne sert qu'à la landing |
| `assets/css/style.css` | **seulement les blocs listés ci-dessous** |

La feuille de style est partagée par les 29 pages : on ne peut pas la geler en
entier. Les blocs qui appartiennent à la landing sont repérables par leur
commentaire d'en-tête :

- `FlowButtons` — les boutons, partagés avec toute l'application
- `Splash / greeting`
- `Navbar`
- `KLASSIO — Hero « question → réponse », puis entrée dans le « O »`
  (et ses sous-blocs : *Scène au repos*, *La réponse : le mot-marque*,
  *Appui*, *Replis*)
- `Story sections`
- `Bande de capacités (bandeau défilant)`
- `05 — Le décompte de la confiance`
- `Nappe (unrolling feature banner)`
- `Final CTA`, `Footer`, `Responsive`

---

## 2. Ce que « gelé » veut dire

**Interdit sans demande explicite du propriétaire :**

- refondre, « moderniser », « nettoyer » ou réécrire la page ;
- changer la composition du hero, les textes, la palette, les polices,
  les espacements, les rayons, les ombres ;
- ajouter, retirer ou réordonner une section ;
- modifier, remplacer ou « optimiser » les quatre effets liés au défilement
  (entrée dans le « O », émergence en étoile, entrées alternées, décompte de
  la confiance) ;
- supprimer un commentaire de code : ils racontent le défaut qu'ils
  empêchent, pas ce que fait la ligne.

**Toujours permis, et même attendu :**

- corriger un **vrai défaut** constaté : débordement, texte illisible,
  contraste insuffisant, erreur console, régression d'accessibilité ;
- corriger une **régression** causée par un travail fait ailleurs ;
- réversionner (`?v=`) après une correction — voir §4.

Dans ces cas : la correction la plus étroite possible, jamais l'occasion
d'une refonte. Et on dit ce qu'on a changé.

---

## 3. Décisions à ne pas défaire

Chacune a coûté un défaut reproduit. Les détails sont dans les commentaires
du code et dans `REPRISE.md` §0.

1. **Klassio est visible dès le premier écran**, sous la phrase, comme LA
   RÉPONSE. Le mot-marque ne doit jamais « apparaître » en cours de
   défilement : défiler ne fait qu'une chose, entrer dans le « O ».

2. **Aucune opacité < 1 sur le mot-marque ni sur un de ses ancêtres** pendant
   la plongée. Une couche translucide rend l'ouverture translucide avec elle,
   et la page se lit à travers le trou du « O ».

3. **Le contenu vu dans le « O » n'est jamais mis à l'échelle.** C'est une
   couche plein écran opaque (`.portal-reveal`) découpée par un disque. Ne pas
   l'agrandir avec l'ouverture ; ne pas compenser par un `scale(1/n)` CSS.

4. **`.btn::before` reste en `z-index: -1`.** En 0, le cercle de survol passe
   au-dessus du texte non enveloppé : « Connexion » redevient un ovale blanc.

5. **`.chip` de la landing reste porté par `.tools-chaos`.** Le nom est aussi
   celui des pastilles de filtre des écrans de gestion, définies plus bas dans
   la même feuille.

6. **Les états d'arrivée sont en CSS, les états de départ en JavaScript.**
   C'est ce qui fait qu'en mouvement réduit ou sans script, tout s'affiche
   déjà en place. Ne pas inverser.

7. **Les replis restent complets** : `prefers-reduced-motion`, le bloc
   `<noscript>` d'`index.html`, et le mobile à 375 px sans débordement
   horizontal. Un mouvement en moins ne doit jamais coûter une information.

---

## 4. Si tu dois quand même y toucher

1. Lis `AGENTS.md`, puis `REPRISE.md` §0.
2. Écris d'abord **quel défaut** tu corriges, et comment tu l'as reproduit.
3. Fais la correction la plus étroite possible.
4. Vérifie **dans le navigateur**, pas seulement dans le code : 375 px et
   pleine largeur, thème clair **et** sombre, mouvement réduit, sans
   JavaScript, aucun débordement horizontal, aucune erreur console.
5. **Incrémente `?v=` sur les 29 pages** si tu as touché `style.css` ou
   `theme.js` — ils sont partagés. Un oubli sert une feuille périmée à tout
   visiteur qui revient. C'est déjà arrivé deux fois.
6. Les deux suites doivent rester vertes, lancées **l'une après l'autre** :

   ```bash
   backend_venv/bin/python -m unittest discover -s backend/tests -t backend
   backend_venv/bin/python backend/tools/pg_tests.py
   ```

7. Synchronise le miroir du Bureau (commande au §7 d'`AGENTS.md`).
