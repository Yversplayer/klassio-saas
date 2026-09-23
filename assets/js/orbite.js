// KLASSIO — l'orbite : le moyeu en volume.
//
// Ce que le JS fait, et ce qu'il laisse au CSS.
//
// Il pose UN angle par module et trois valeurs qui en découlent (profondeur,
// échelle, opacité). Tout le reste — position sur le cercle, perspective,
// redressement des étiquettes — est décrit en CSS et composé par le GPU.
// Piloter six transformations complètes en JavaScript à chaque image
// coûterait le fil principal, qui a déjà le portail et les observateurs à
// tenir ; poser quatre variables, non.
//
// Pourquoi pas WebGL. Une scène 3D avec post-traitement tient sur un
// MacBook et s'effondre sur le téléphone d'un directeur d'école à Kinshasa.
// Les transformations CSS 3D donnent ici le même volume — perspective,
// occlusion, profondeur — pour un coût qui tient sur n'importe quel appareil.
(function () {
  "use strict";

  var M = window.KlassioMotion;
  var racine = document.getElementById("orbite");
  if (!racine) return;

  var scene = document.getElementById("orbScene");
  var legende = document.getElementById("orbLegende");
  var noeuds = Array.prototype.slice.call(racine.querySelectorAll(".orb-node"));
  if (!noeuds.length) return;

  // Ce que chaque module apporte. Le texte vit ici, pas dans le balisage :
  // une phrase de présentation n'a pas à être recopiée à chaque retouche de
  // mise en page.
  var MODULES = [
    "Chaque élève a un dossier unique, qui le suit d'une année à l'autre.",
    "Les classes portent l'année, le cycle et leur titulaire.",
    "Chaque paiement confirmé produit un reçu numéroté, jamais deux fois le même.",
    "La trésorerie se lit en temps réel, sans additionner des cahiers.",
    "Les dépenses entrent dans le même registre que les recettes.",
    "Les rapports se calculent sur les données réelles, jamais sur une copie.",
  ];
  var REPOS = "Tout converge vers une source unique.";

  var reduit = M ? M.reduit : window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var n = noeuds.length;
  var angle = 0;
  var fige = false;       // survol ou sélection : l'orbite s'arrête
  var choisi = -1;
  // ON DÉMARRE EN TOURNANT, l'observateur ARRÊTE.
  //
  // L'inverse — attendre que l'observateur déclare l'orbite visible — la
  // laisse figée pour toujours dès que la géométrie du repère est
  // inhabituelle : fenêtre de hauteur nulle, conteneur non encore mesuré,
  // onglet restauré. Démarrer puis laisser l'observateur mettre en pause est
  // la seule variante qui n'a pas d'état « jamais lancé ».
  var visible = true;
  var raf = 0;
  var dernier = 0;

  // Un ressort porte l'angle vers sa cible : quand on choisit un module, la
  // rotation ne saute pas, elle se pose. C'est ce qui distingue une mécanique
  // d'un changement d'état.
  var res = M ? new M.Ressort(0, 90, 18) : null;

  function placer() {
    for (var i = 0; i < n; i++) {
      var a = (i / n) * 360 + angle;
      var rad = (a * Math.PI) / 180;
      // sin(rad) vaut +1 quand le module est AU PLUS PRÈS du lecteur (bas de
      // l'ellipse vue de trois quarts), -1 quand il est derrière le noyau.
      var proximite = (Math.sin(rad) + 1) / 2;       // 0 (loin) → 1 (près)
      var el = noeuds[i];
      el.style.setProperty("--a", a.toFixed(2));
      el.style.setProperty("--z", String(Math.round(proximite * 40)));
      el.style.setProperty("--s", (0.82 + proximite * 0.28).toFixed(3));
      // On ne descend jamais sous 0,38 : un module devenu invisible derrière
      // le noyau ne serait plus cliquable ni annonçable, et l'orbite
      // paraîtrait perdre des éléments.
      el.style.setProperty("--o", (0.38 + proximite * 0.62).toFixed(3));
    }
  }

  function boucle(now) {
    raf = 0;
    var dt = dernier ? Math.min((now - dernier) / 1000, 1 / 30) : 1 / 60;
    dernier = now;
    if (res) {
      res.cible += fige ? 0 : dt * 9;   // ~9°/s : une révolution en 40 s
      angle = res.pas(dt);
    } else {
      if (!fige) angle += dt * 9;
    }
    placer();
    if (visible) raf = requestAnimationFrame(boucle);
  }

  function reveiller() {
    if (raf || !visible) return;
    dernier = 0;
    raf = requestAnimationFrame(boucle);
  }

  // ---- Choisir un module ------------------------------------------------
  //
  // Cliquer amène le module choisi AU PREMIER PLAN plutôt que d'ouvrir une
  // fiche par-dessus : l'orbite elle-même devient la réponse.
  function choisir(i) {
    if (choisi === i) {
      choisi = -1;
      fige = false;
      racine.removeAttribute("data-actif");
      noeuds.forEach(function (b) { b.setAttribute("aria-pressed", "false"); });
      if (legende) legende.textContent = REPOS;
      reveiller();
      return;
    }
    choisi = i;
    fige = true;
    racine.setAttribute("data-actif", "");
    noeuds.forEach(function (b, j) { b.setAttribute("aria-pressed", String(j === i)); });
    if (legende) legende.textContent = MODULES[i] || REPOS;
    // 90° amène l'élément au point le plus proche du lecteur.
    if (res) {
      var vise = 90 - (i / n) * 360;
      // On rejoint la cible par le plus court chemin : sans cela, passer du
      // sixième au premier module ferait faire un tour complet à l'orbite.
      while (vise - res.cible > 180) vise -= 360;
      while (vise - res.cible < -180) vise += 360;
      res.cible = vise;
      reveiller();
    } else {
      angle = 90 - (i / n) * 360;
      placer();
    }
  }

  noeuds.forEach(function (b, i) {
    b.setAttribute("aria-pressed", "false");
    b.addEventListener("click", function () { choisir(i); });
    // Au survol, l'orbite s'arrête : viser une cible mouvante est pénible,
    // et c'est exactement ce qu'un utilisateur reproche à ce genre d'objet.
    b.addEventListener("pointerenter", function () { fige = true; });
    b.addEventListener("pointerleave", function () { if (choisi < 0) { fige = false; reveiller(); } });
    b.addEventListener("focus", function () { fige = true; });
    b.addEventListener("blur", function () { if (choisi < 0) { fige = false; reveiller(); } });
  });

  if (scene) {
    scene.addEventListener("pointerenter", function () { fige = true; });
    scene.addEventListener("pointerleave", function () { if (choisi < 0) { fige = false; reveiller(); } });
  }

  // ---- Ne tourner que sous les yeux --------------------------------------
  //
  // Une boucle d'animation qui continue hors écran consomme la batterie d'un
  // téléphone sans que personne ne la regarde.
  placer();
  if (reduit) return;   // en mouvement réduit, l'orbite reste posée, à plat.

  reveiller();

  var io = new IntersectionObserver(function (entrees) {
    entrees.forEach(function (e) {
      visible = e.isIntersecting;
      if (visible) reveiller();
      else if (raf) { cancelAnimationFrame(raf); raf = 0; }
    });
  }, { threshold: 0.12 });
  io.observe(racine);

  document.addEventListener("visibilitychange", function () {
    if (document.hidden && raf) { cancelAnimationFrame(raf); raf = 0; }
    else reveiller();
  });
})();
