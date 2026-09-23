// KLASSIO — moteur de mouvement.
//
// POURQUOI CE FICHIER EXISTE, ET POURQUOI IL N'IMPORTE RIEN
//
// Les références visuelles qui ont inspiré cet écran (MATTER, CAUSTIC) sont
// bâties sur Three.js, GSAP et Tailwind, chargés depuis des CDN. Ici, deux
// contraintes rendent cette voie impossible, et il vaut mieux les nommer que
// de s'y heurter :
//
//   1. La CSP de chaque page porte `script-src 'self'`. Un script de CDN ne
//      se charge pas — silencieusement. La page paraît simplement cassée.
//   2. Le projet n'a ni npm, ni bundler, ni React. Le backend Flask sert ces
//      fichiers tels quels, et 29 pages en dépendent.
//
// Relâcher la CSP pour faire entrer une bibliothèque serait payer en sécurité
// ce qu'on peut obtenir autrement. Tout ce qui suit est donc natif : ressorts
// calculés à la main, découpage typographique par l'API DOM, révélations par
// IntersectionObserver. Cela tient en quelques centaines de lignes, ne coûte
// aucun téléchargement, et fonctionne sur un téléphone d'entrée de gamme à
// Kinshasa — ce que ne ferait pas une scène WebGL avec post-traitement.
//
// RÈGLE TENUE PARTOUT ICI : aucun `innerHTML`. Le découpage lit du
// `textContent` et fabrique des nœuds. Une XSS stockée a déjà été exploitée
// dans ce projet ; un moteur d'animation n'a aucune raison de rouvrir cette
// porte.
(function () {
  "use strict";

  var reduit = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------------------------------------------------------------------
  // Découpage typographique
  // ---------------------------------------------------------------------

  /**
   * Enveloppe chaque caractère dans un <span>, sans jamais passer par du HTML.
   *
   * Deux précautions qui ne sont pas du zèle :
   *   - les espaces deviennent des espaces insécables dans leur propre span,
   *     sinon le navigateur les effondre et les mots se collent ;
   *   - le texte d'origine reste lisible des lecteurs d'écran via aria-label,
   *     car une phrase éclatée en 40 spans est annoncée lettre par lettre.
   */
  function decouperCaracteres(el, decalage) {
    var texte = el.textContent;
    if (!texte || el.dataset.decoupe === "1") return 0;
    el.setAttribute("aria-label", texte.trim());
    el.textContent = "";
    var i = 0, n = 0;
    for (; i < texte.length; i++) {
      var c = texte[i];
      var span = document.createElement("span");
      span.className = "mo-c";
      span.setAttribute("aria-hidden", "true");
      span.textContent = c === " " ? " " : c;
      if (c !== " ") {
        span.style.setProperty("--mo-i", String(n + (decalage || 0)));
        n++;
      } else {
        span.style.setProperty("--mo-i", String(n + (decalage || 0)));
      }
      el.appendChild(span);
    }
    el.dataset.decoupe = "1";
    return n;
  }

  /** Même principe, mot par mot : plus lisible pour un paragraphe long. */
  function decouperMots(el, decalage) {
    var texte = el.textContent;
    if (!texte || el.dataset.decoupe === "1") return 0;
    el.setAttribute("aria-label", texte.trim());
    el.textContent = "";
    var mots = texte.split(/(\s+)/);
    var n = 0;
    mots.forEach(function (mot) {
      if (!mot) return;
      if (/^\s+$/.test(mot)) { el.appendChild(document.createTextNode(" ")); return; }
      var ext = document.createElement("span");
      ext.className = "mo-w";
      ext.setAttribute("aria-hidden", "true");
      var inner = document.createElement("span");
      inner.className = "mo-w-i";
      inner.textContent = mot;
      inner.style.setProperty("--mo-i", String(n + (decalage || 0)));
      ext.appendChild(inner);
      el.appendChild(ext);
      n++;
    });
    el.dataset.decoupe = "1";
    return n;
  }

  /**
   * Prépare un élément et renvoie une fonction qui le joue.
   *
   * `data-mo` vaut "chars", "words" ou "lines". Le décalage entre unités est
   * porté par une variable CSS : c'est le CSS qui anime, le JS ne fait que
   * poser l'index et basculer une classe. Une animation pilotée en JS image
   * par image tombe dès que le fil principal est occupé ; une transition CSS
   * continue sur le compositeur.
   */
  function preparer(el) {
    var mode = el.dataset.mo || "words";
    if (mode === "chars") decouperCaracteres(el, 0);
    else if (mode === "words") decouperMots(el, 0);
    el.classList.add("mo-prep");
  }

  function jouer(el) {
    if (el.dataset.moJoue === "1") return;
    el.dataset.moJoue = "1";
    // Un délai d'entrée permet d'échelonner plusieurs blocs entre eux, pas
    // seulement les unités à l'intérieur d'un bloc.
    var retard = parseFloat(el.dataset.moDelay || "0");
    if (retard > 0) {
      el.style.setProperty("--mo-delay", retard + "ms");
    }
    el.classList.add("mo-in");
  }

  // ---------------------------------------------------------------------
  // Révélation à l'entrée dans le champ
  // ---------------------------------------------------------------------

  function observer(racine) {
    var cibles = (racine || document).querySelectorAll("[data-mo]");
    if (!cibles.length) return;

    Array.prototype.forEach.call(cibles, preparer);

    if (reduit) {
      // Mouvement réduit : on affiche l'état d'arrivée, immédiatement. Rien
      // n'est perdu — seul le trajet disparaît.
      Array.prototype.forEach.call(cibles, function (el) { el.classList.add("mo-in", "mo-instant"); });
      return;
    }

    var io = new IntersectionObserver(function (entrees) {
      entrees.forEach(function (e) {
        if (!e.isIntersecting) return;
        jouer(e.target);
        io.unobserve(e.target);
      });
    }, { threshold: 0.18, rootMargin: "0px 0px -8% 0px" });

    Array.prototype.forEach.call(cibles, function (el) { io.observe(el); });
  }

  // ---------------------------------------------------------------------
  // Ressort — une intégration, pas une courbe de Bézier
  // ---------------------------------------------------------------------

  /**
   * Un ressort amorti, intégré à chaque image.
   *
   * La différence avec une transition CSS n'est pas cosmétique : un ressort
   * réagit à sa VITESSE courante. Si la cible change en cours de route, le
   * mouvement se poursuit sans repartir de zéro — c'est ce qui donne la
   * sensation « physique » plutôt qu'« animée ».
   */
  function Ressort(valeur, raideur, amortissement) {
    this.v = valeur || 0;
    this.cible = this.v;
    this.vitesse = 0;
    this.k = raideur || 120;
    this.d = amortissement || 15;
  }
  Ressort.prototype.pas = function (dt) {
    // dt borné : un onglet réveillé après 3 s produirait une force absurde et
    // ferait exploser le ressort.
    dt = Math.min(dt, 1 / 30);
    var force = (this.cible - this.v) * this.k;
    var frein = this.vitesse * this.d;
    this.vitesse += (force - frein) * dt;
    this.v += this.vitesse * dt;
    return this.v;
  };

  // ---------------------------------------------------------------------
  // Vitesse de défilement → typographie
  // ---------------------------------------------------------------------

  /**
   * Publie `--mo-stretch` et `--mo-blur` sur <html>, d'après la vitesse de
   * défilement lissée par un ressort.
   *
   * L'idée vient de MATTER : le texte n'est pas posé sur la page, il subit le
   * mouvement. Avec une police variable, l'axe `wdth` se comprime quand on
   * défile vite et revient à 100 quand on s'arrête. Le flou suit la même
   * grandeur, très en dessous — au-delà de 2 px il devient illisible, et
   * l'effet doit rester une sensation, pas un obstacle à la lecture.
   */
  function typographieCinetique() {
    if (reduit) return;
    var racine = document.documentElement;
    var dernier = window.scrollY, dernierT = performance.now();
    var res = new Ressort(0, 160, 16);
    var actif = false;
    // LA DISTANCE S'ACCUMULE SUR LES ÉVÉNEMENTS, PAS ENTRE DEUX IMAGES.
    //
    // Mesurer l'écart entre deux images rate tout défilement qui se termine
    // avant la première : la position a déjà bougé quand la boucle démarre,
    // l'écart image-à-image vaut zéro, et le ressort s'arrête sans jamais
    // être monté. On additionne donc ce que les événements rapportent, et la
    // boucle consomme ce compteur.
    var distance = 0;

    function boucle(now) {
      var dt = Math.max((now - dernierT) / 1000, 0.001);
      dernierT = now;
      var vitesse = distance / dt;
      distance = 0;
      // Normalisée : ~2600 px/s est un défilement franc.
      res.cible = Math.min(vitesse / 2600, 1);
      var v = res.pas(dt);
      racine.style.setProperty("--mo-stretch", (100 - v * 24).toFixed(1));
      racine.style.setProperty("--mo-blur", (v * 1.5).toFixed(2) + "px");
      // On ne s'arrête que lorsque le ressort EST REVENU au repos, vitesse
      // comprise : couper sur la seule valeur laisserait un élan en suspens.
      if (v < 0.004 && Math.abs(res.vitesse) < 0.02 && res.cible < 0.004) {
        actif = false;
        racine.style.setProperty("--mo-stretch", "100");
        racine.style.setProperty("--mo-blur", "0px");
        return;
      }
      requestAnimationFrame(boucle);
    }

    window.addEventListener("scroll", function () {
      var y = window.scrollY;
      distance += Math.abs(y - dernier);
      dernier = y;
      if (actif) return;
      actif = true;
      dernierT = performance.now() - 16;
      requestAnimationFrame(boucle);
    }, { passive: true });
  }

  // ---------------------------------------------------------------------
  // Curseur
  // ---------------------------------------------------------------------

  /**
   * Point + anneau, en `mix-blend-mode: difference`.
   *
   * Le point suit exactement le pointeur ; l'anneau le rattrape par ressort.
   * C'est ce décalage qui donne l'impression d'une masse, et c'est pour cela
   * qu'il est calculé plutôt que transitionné.
   *
   * Il ne REMPLACE jamais le curseur système : on le superpose et on masque
   * le natif uniquement là où un vrai pointeur existe (`hover: hover`). Sur
   * un écran tactile, il ne s'installe pas du tout — il n'y aurait rien à
   * suivre, et deux couches fixes de plus coûteraient des images perdues.
   */
  function curseur() {
    if (reduit) return;
    if (!window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;

    var point = document.createElement("div");
    point.className = "mo-cursor";
    point.setAttribute("aria-hidden", "true");
    var anneau = document.createElement("div");
    anneau.className = "mo-ring";
    anneau.setAttribute("aria-hidden", "true");
    document.body.appendChild(point);
    document.body.appendChild(anneau);
    document.documentElement.classList.add("mo-cursor-on");

    var x = innerWidth / 2, y = innerHeight / 2;
    var rx = new Ressort(x, 120, 15), ry = new Ressort(y, 120, 15);
    var echelle = new Ressort(1, 160, 16);
    var t = performance.now();

    document.addEventListener("pointermove", function (e) {
      x = e.clientX; y = e.clientY;
      rx.cible = x; ry.cible = y;
      point.style.transform = "translate3d(" + x + "px," + y + "px,0)";
    }, { passive: true });

    // Sur un élément actionnable, l'anneau grossit : le curseur dit ce qui
    // est cliquable avant qu'on ne l'ait cliqué.
    document.addEventListener("pointerover", function (e) {
      var a = e.target.closest && e.target.closest("a,button,[role=button],input,select,textarea,.mo-magnet");
      echelle.cible = a ? 1.9 : 1;
      anneau.classList.toggle("mo-ring-on", !!a);
    }, { passive: true });

    document.addEventListener("pointerleave", function () {
      point.style.opacity = "0"; anneau.style.opacity = "0";
    });
    document.addEventListener("pointerenter", function () {
      point.style.opacity = ""; anneau.style.opacity = "";
    });

    (function boucle(now) {
      var dt = (now - t) / 1000 || 0.016; t = now;
      var ax = rx.pas(dt), ay = ry.pas(dt), s = echelle.pas(dt);
      anneau.style.transform = "translate3d(" + ax + "px," + ay + "px,0) scale(" + s.toFixed(3) + ")";
      requestAnimationFrame(boucle);
    })(t);
  }

  // ---------------------------------------------------------------------
  // Aimantation
  // ---------------------------------------------------------------------

  /**
   * Un élément `.mo-magnet` se penche vers le pointeur quand il en approche.
   *
   * Le rayon est proportionnel à la taille de l'élément : un grand bouton
   * attire de plus loin qu'une petite puce, ce qui correspond à l'intuition.
   */
  function aimants(racine) {
    if (reduit) return;
    if (!window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;
    var els = (racine || document).querySelectorAll(".mo-magnet");
    if (!els.length) return;

    Array.prototype.forEach.call(els, function (el) {
      var sx = new Ressort(0, 140, 14), sy = new Ressort(0, 140, 14);
      var t = performance.now(), anime = false;

      function boucle(now) {
        var dt = (now - t) / 1000 || 0.016; t = now;
        var vx = sx.pas(dt), vy = sy.pas(dt);
        el.style.transform = "translate3d(" + vx.toFixed(2) + "px," + vy.toFixed(2) + "px,0)";
        if (Math.abs(vx) < 0.05 && Math.abs(vy) < 0.05 && sx.cible === 0 && sy.cible === 0) {
          el.style.transform = ""; anime = false; return;
        }
        requestAnimationFrame(boucle);
      }
      function reveiller() { if (!anime) { anime = true; t = performance.now(); requestAnimationFrame(boucle); } }

      el.addEventListener("pointermove", function (e) {
        var r = el.getBoundingClientRect();
        var dx = e.clientX - (r.left + r.width / 2);
        var dy = e.clientY - (r.top + r.height / 2);
        sx.cible = dx * 0.22; sy.cible = dy * 0.28;
        reveiller();
      }, { passive: true });
      el.addEventListener("pointerleave", function () {
        sx.cible = 0; sy.cible = 0; reveiller();
      }, { passive: true });
    });
  }

  // ---------------------------------------------------------------------
  // Séquence — des blocs qui se succèdent, pas qui surgissent ensemble
  // ---------------------------------------------------------------------

  /**
   * Joue une liste d'éléments l'un après l'autre, et renvoie une promesse.
   * Sert au splash : « Bonjour », puis « Bienvenue sur Klassio », puis
   * l'invitation — jamais les trois d'un coup.
   */
  function sequence(elements, pas) {
    pas = pas || 420;
    return new Promise(function (resolve) {
      if (reduit) {
        elements.forEach(function (el) { if (el) el.classList.add("mo-in", "mo-instant"); });
        resolve();
        return;
      }
      var i = 0;
      (function suivant() {
        if (i >= elements.length) { setTimeout(resolve, pas); return; }
        var el = elements[i++];
        if (el) jouer(el);
        setTimeout(suivant, pas);
      })();
    });
  }

  var LARGEUR_LAMPE = 32;   // doit suivre .tubelight-lamp { width } dans style.css

  // ---------------------------------------------------------------------
  // LA LAMPE DE NAVIGATION
  // ---------------------------------------------------------------------
  //
  // Une barre de lumière posée au-dessus de l'onglet où l'on se trouve.
  //
  // POURQUOI ELLE EST ICI, ET PLUS DANS main.js
  //
  // Elle n'existait que sur la landing. Les autres pages publiques font
  // rebâtir leur barre par public.js, qui ne connaissait pas la lampe : en
  // ouvrant « À propos », « Centre d'aide » ou « Produit » depuis une de ces
  // pages, la lumière DISPARAISSAIT — l'exact inverse de ce qu'une lampe de
  // position doit faire. Elle vit donc dans la couche partagée, et chaque
  // page l'allume sur son propre onglet.
  //
  // POURQUOI ELLE SE REPLACE PLUSIEURS FOIS
  //
  // On la posait une fois, 100 ms après le chargement. Mesurer une pilule
  // avant que la police d'affichage ne soit arrivée donne une largeur qui
  // n'est plus la bonne un instant plus tard ; et en arrivant sur
  // `index.html#produit`, la mesure tombait pendant le splash, donc à zéro :
  // la lampe partait à gauche de la barre, hors de tout onglet. Elle se
  // replace maintenant tant qu'elle n'a pas pu mesurer, puis au chargement
  // complet, au retour des polices, et à chaque redimensionnement.
  function lampeNav(nav) {
    nav = nav || document.getElementById("tubelightNav")
               || document.querySelector(".navbar .nav-links");
    if (!nav) return null;

    var liens = Array.prototype.slice.call(nav.querySelectorAll("a"));
    if (!liens.length) return null;

    var lampe = nav.querySelector(".tubelight-lamp");
    if (!lampe) {
      lampe = document.createElement("div");
      lampe.className = "tubelight-lamp";
      lampe.setAttribute("aria-hidden", "true");
      var lueur = document.createElement("div");
      lueur.className = "tubelight-glow";
      lampe.appendChild(lueur);
      nav.insertBefore(lampe, nav.firstChild);
    }

    // L'onglet courant, dans l'ordre de confiance : une marque explicite, la
    // page réellement ouverte, puis le premier onglet. Le dernier recours
    // compte : sans lui, une page sans onglet correspondant éteindrait la
    // lampe, et c'est précisément ce qu'on corrige.
    function courant() {
      return nav.querySelector("a.active")
          || nav.querySelector('a[aria-current="page"]')
          || liens[0];
    }

    // Sous 1060 px la barre devient un menu déroulant : les onglets s'empilent
    // en colonne. Une barre horizontale de 32 px posée « au-dessus de l'onglet »
    // n'y veut plus rien dire — elle se retrouverait au-dessus de la pile
    // entière. On la laisse donc éteinte tant que les onglets ne sont pas sur
    // une même ligne, et le test le dit sans dépendre d'un point de rupture
    // écrit deux fois : deux onglets alignés ont le même `offsetTop`.
    function enLigne() {
      return liens.length < 2 || liens[0].offsetTop === liens[1].offsetTop;
    }

    function placer() {
      var el = courant();
      if (!el || !el.offsetWidth || !enLigne()) return false;   // pas mesurable
      var x = el.offsetLeft + (el.offsetWidth - LARGEUR_LAMPE) / 2;
      lampe.style.transform = "translateX(" + Math.round(x) + "px)";
      lampe.classList.add("active");              // ajoutée, jamais retirée
      return true;
    }

    function replacer() {
      if (!placer()) requestAnimationFrame(placer);
    }

    // ELLE NE SUIT PAS LA SOURIS. Elle se déplace quand on CHANGE de page :
    // survoler une barre ne veut rien dire, et une lampe qui court d'un
    // onglet à l'autre sans que rien n'ait changé ne renseigne sur rien.
    liens.forEach(function (a) {
      a.addEventListener("click", function () {
        liens.forEach(function (x) { x.classList.remove("active"); });
        a.classList.add("active");
        placer();
      });
    });

    replacer();
    requestAnimationFrame(replacer);
    window.addEventListener("load", replacer);
    window.addEventListener("resize", replacer, { passive: true });
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(replacer).catch(function () {});
    }
    return lampe;
  }

  window.KlassioMotion = {
    observer: observer,
    preparer: preparer,
    jouer: jouer,
    sequence: sequence,
    decouperCaracteres: decouperCaracteres,
    decouperMots: decouperMots,
    Ressort: Ressort,
    typographieCinetique: typographieCinetique,
    curseur: curseur,
    aimants: aimants,
    lampeNav: lampeNav,
    reduit: reduit,
  };
})();
