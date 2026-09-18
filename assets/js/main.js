// KLASSIO — interactions de la landing
(function () {
  "use strict";

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------------------------------------------------------------- Splash
  // Il se retire tout seul, et on peut l'écourter : clic, touche ou molette.
  // Il portait 2 s fixes sans rien indiquer au visiteur — c'est long pour un
  // écran qui ne dit rien, et un visiteur qui revient le subit à chaque fois.
  var splash = document.getElementById("splash");
  if (splash) {
    var splashTimer = null;
    var hideSplash = function () {
      if (splashTimer) { clearTimeout(splashTimer); splashTimer = null; }
      splash.classList.add("hide");
      document.body.classList.remove("no-scroll");
      document.removeEventListener("keydown", hideSplash);
      window.removeEventListener("wheel", hideSplash);
      window.removeEventListener("touchstart", hideSplash);
      setTimeout(function () { if (splash.parentNode) splash.remove(); }, 950);
    };
    splashTimer = setTimeout(hideSplash, reduced ? 200 : 1400);
    splash.addEventListener("click", hideSplash);
    document.addEventListener("keydown", hideSplash);
    window.addEventListener("wheel", hideSplash, { passive: true });
    window.addEventListener("touchstart", hideSplash, { passive: true });
  } else {
    document.body.classList.remove("no-scroll");
  }

  // ------------------------------------------------------- Barre de navigation
  var navbar = document.getElementById("navbar");
  if (navbar) {
    var onScroll = function () {
      if (window.scrollY > 12) navbar.classList.add("scrolled");
      else navbar.classList.remove("scrolled");
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  // ------------------------------------------------------ Révélation au scroll
  var revealEls = document.querySelectorAll(".reveal");
  var revealObserver = new IntersectionObserver(
    function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("in-view");
          revealObserver.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.18 }
  );
  revealEls.forEach(function (el) { revealObserver.observe(el); });

  // ------------------------------------------------------------ Nappe (déroulé)
  var nappe = document.getElementById("nappe");
  if (nappe) {
    var nappeObserver = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            nappe.classList.add("unroll");
            nappeObserver.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.25 }
    );
    nappeObserver.observe(nappe);
  }

  // =========================================================================
  // RÉCIT — trois effets liés au défilement
  //
  // Même discipline que le portail : la géométrie est mesurée une fois
  // (chargement, polices, redimensionnement), la frame n'écrit que des styles,
  // et le défilement est lu dans l'écouteur, jamais dans la frame — lire une
  // position après avoir écrit un style force un recalcul de mise en page.
  //
  // Chaque effet se construit seul et renvoie null s'il lui manque quelque
  // chose : la page reste une page. Les états d'ARRIVÉE sont décrits en CSS,
  // et l'état de départ est calculé ici — c'est ce qui fait qu'en mouvement
  // réduit ou sans JavaScript, tout s'affiche déjà en place.
  // =========================================================================

  function clampV(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }
  function easeOutCubic(t) { return 1 - Math.pow(1 - t, 3); }

  // --- 02 — Les satellites sortent du noyau, un par un ---------------------
  function buildHub() {
    var hub = document.getElementById("hub");
    var core = document.getElementById("hubCore");
    if (!hub || !core) return null;
    var nodes = [].slice.call(hub.querySelectorAll(".hub-node"));
    var lines = [].slice.call(hub.querySelectorAll(".hub-line"));
    if (nodes.length < 2) return null;
    var geo = null;

    function measure() {
      // Retour à l'état d'arrivée avant de lire : mesurer une position déjà
      // transformée ferait dériver un peu plus à chaque redimensionnement.
      nodes.forEach(function (n) { n.style.transform = ""; });
      var sy = window.scrollY || window.pageYOffset;
      var hRect = hub.getBoundingClientRect();
      var cRect = core.getBoundingClientRect();
      var cx = cRect.left + cRect.width / 2;
      var cy = cRect.top + cRect.height / 2;
      if (!hRect.height) { geo = null; return; }
      geo = {
        top: hRect.top + sy,
        height: hRect.height,
        offsets: nodes.map(function (n) {
          var r = n.getBoundingClientRect();
          return { dx: cx - (r.left + r.width / 2), dy: cy - (r.top + r.height / 2) };
        })
      };
    }

    function apply(scrollY, vh) {
      if (!geo) return;
      var raw = clampV((scrollY + vh - geo.top) / (vh + geo.height), 0, 1);
      // Fenêtre utile : l'émission commence une fois le noyau bien en vue.
      var p = clampV((raw - 0.16) / 0.46, 0, 1);
      var span = 0.34;
      var step = (1 - span) / (nodes.length - 1);
      var pulse = 1;

      nodes.forEach(function (n, i) {
        var t = clampV((p - i * step) / span, 0, 1);
        var e = easeOutCubic(t);
        var o = geo.offsets[i];
        n.style.transform =
          "translate(" + (o.dx * (1 - e)).toFixed(1) + "px," + (o.dy * (1 - e)).toFixed(1) +
          "px) scale(" + (0.55 + 0.45 * e).toFixed(3) + ")";
        n.style.opacity = clampV(t * 2.4, 0, 1).toFixed(3);
        n.classList.toggle("emitting", t > 0.03 && t < 0.9);
        if (t > 0 && t < 1) pulse = t;
        if (lines[i]) lines[i].style.setProperty("--hl", (1 - e).toFixed(3));
      });

      core.style.setProperty("--hub-pulse", pulse.toFixed(3));
    }

    return { measure: measure, apply: apply };
  }

  // --- 03 — Les cartes entrent par la gauche, puis la droite, en alternance -
  function buildReality() {
    var wrap = document.getElementById("localReality");
    if (!wrap) return null;
    var cards = [].slice.call(wrap.querySelectorAll(".reality-card"));
    if (!cards.length) return null;
    var geo = null;

    function measure() {
      var sy = window.scrollY || window.pageYOffset;
      geo = cards.map(function (c) {
        var r = c.getBoundingClientRect();
        return { top: r.top + sy };
      });
    }

    function apply(scrollY, vh) {
      if (!geo) return;
      cards.forEach(function (c, i) {
        // 0 quand la carte entre par le bas de l'écran, 1 après un peu plus
        // d'un demi-écran de défilement. Bornée à 1 : une fois arrivée, elle
        // se fixe et ne repart jamais.
        var t = clampV((scrollY + vh - geo[i].top) / (vh * 0.55), 0, 1);
        c.style.setProperty("--rc-p", easeOutCubic(t).toFixed(3));
      });
    }

    return { measure: measure, apply: apply };
  }

  // --- 05 — Le décompte : une garantie nette, les autres en retrait ---------
  function buildTrust() {
    var grid = document.getElementById("trustGrid");
    var runway = document.querySelector(".trust-runway");
    var counter = document.getElementById("trustCurrent");
    if (!grid || !runway) return null;
    var cards = [].slice.call(grid.querySelectorAll(".trust-card"));
    if (cards.length < 2) return null;
    var geo = null;
    var shown = -1;

    function measure() {
      var sy = window.scrollY || window.pageYOffset;
      var r = runway.getBoundingClientRect();
      var g = grid.getBoundingClientRect();
      var stickyTop = parseFloat(window.getComputedStyle(grid).top);
      if (!isFinite(stickyTop)) stickyTop = 0;
      // La grille est épinglée : la course utile va du moment où elle se cale
      // à celui où elle se décroche, soit la hauteur de piste moins la sienne.
      geo = { start: r.top + sy - stickyTop, travel: Math.max(1, r.height - g.height) };
    }

    function setActive(i) {
      if (i === shown) return;
      shown = i;
      cards.forEach(function (c, k) {
        var active = k === i;
        var d = Math.abs(k - i);
        c.classList.toggle("active", active);
        c.style.setProperty("--tc-blur", active ? "0px" : Math.min(4, 1.4 + d * 0.9).toFixed(1) + "px");
        c.style.setProperty("--tc-op", active ? "1" : (d === 1 ? "0.5" : "0.34"));
        c.style.setProperty("--tc-scale", active ? "1.03" : "0.97");
      });
      if (counter) counter.textContent = String(i + 1);
    }

    function apply(scrollY) {
      if (!geo) return;
      var p = clampV((scrollY - geo.start) / geo.travel, 0, 1);
      // Un peu de marge aux deux bouts : on ne change pas d'étape au premier
      // pixel, et la dernière reste tenue jusqu'à la sortie de la piste.
      var idx = clampV(Math.floor(clampV((p - 0.06) / 0.86, 0, 0.999) * cards.length), 0, cards.length - 1);
      setActive(idx);
    }

    // Sans défilement (piste plus courte que l'écran), on montre la première
    // plutôt que de laisser trois cartes floues sans raison.
    setActive(0);
    return { measure: measure, apply: apply };
  }

  if (!reduced) {
    var storyEffects = [];
    [buildHub(), buildReality(), buildTrust()].forEach(function (e) { if (e) storyEffects.push(e); });

    if (storyEffects.length) {
      var storyTicking = false;
      var storyScroll = window.scrollY || window.pageYOffset;

      var runStory = function () {
        storyTicking = false;
        var vh = window.innerHeight;
        for (var i = 0; i < storyEffects.length; i++) storyEffects[i].apply(storyScroll, vh);
      };

      var onScrollStory = function () {
        storyScroll = window.scrollY || window.pageYOffset;
        if (!storyTicking) {
          storyTicking = true;
          requestAnimationFrame(runStory);
        }
      };

      var measureStory = function () {
        for (var i = 0; i < storyEffects.length; i++) storyEffects[i].measure();
        runStory();
      };

      var storyResize = null;
      window.addEventListener("scroll", onScrollStory, { passive: true });
      window.addEventListener("resize", function () {
        if (storyResize) clearTimeout(storyResize);
        storyResize = setTimeout(function () { storyResize = null; measureStory(); }, 120);
      });

      measureStory();
      // Les polices d'affichage, puis les images, déplacent la mise en page
      // après le premier calcul : on remesure aux deux moments plutôt que de
      // relire des positions à chaque image.
      if (document.fonts && document.fonts.ready) {
        document.fonts.ready.then(measureStory).catch(function () {});
      }
      window.addEventListener("load", measureStory);
    }
  }

  // =========================================================================
  // HERO — entrer dans le « O » de Klassio
  //
  // Le mot-marque est là AU REPOS. Le défilement ne le fait pas apparaître :
  // il ne fait qu'y entrer. Trois conséquences dans ce code, chacune payée par
  // un défaut constaté :
  //
  //   1. Aucune opacité n'est posée sur le mot-marque ni sur un de ses
  //      ancêtres. Une couche translucide rend l'ouverture translucide avec
  //      elle, et on lit la page à travers le trou du O.
  //
  //   2. Ce qu'on voit dedans n'est JAMAIS mis à l'échelle : c'est une couche
  //      plein écran (.portal-reveal) découpée par un disque dont on pilote le
  //      rayon et le centre. Agrandir le contenu avec l'ouverture ne montre que
  //      des fragments de lettres géantes — ce qui se lisait comme « des écrits
  //      parasites dans le trou » ; le compenser par un scale(1/n) CSS le rend
  //      illisible, le navigateur tramant la couche avant de l'agrandir.
  //
  //   3. La géométrie est mesurée une fois, pas à chaque image. updatePortal()
  //      n'écrit que des transformations et ne lit plus aucune position :
  //      l'ancienne version appelait deux getBoundingClientRect() par frame
  //      juste avant d'écrire un transform, ce qui force un recalcul de mise
  //      en page à chaque image.
  // =========================================================================
  var portalContainer = document.getElementById("portalContainer");
  var heroQuestion = document.getElementById("heroQuestion");
  var heroSupport = document.getElementById("heroSupport");
  var answerCue = document.getElementById("answerCue");
  var wordmark = document.getElementById("glyphWordmarkWrap");
  var aperture = document.getElementById("glyphAperture");
  var interior = document.getElementById("glyphInterior");
  var reveal = document.getElementById("portalReveal");
  var hud = document.getElementById("telemetryHud");

  // Tout est testé : un seul élément manquant et l'effet est simplement
  // désactivé, la page reste une page. L'ancienne garde en oubliait deux,
  // utilisés juste en dessous sans condition.
  var portalReady = !reduced && portalContainer && heroQuestion && heroSupport &&
    answerCue && wordmark && aperture && interior && reveal && hud;

  if (portalReady) {
    var ticking = false;
    var lastScroll = window.scrollY || window.pageYOffset;
    var geo = null;

    function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }
    function easeOut(t) { return 1 - Math.pow(1 - t, 3); }

    // Mesure unique : on remet la scène au repos, on lit, on restaure.
    function measure() {
      wordmark.style.transform = "";

      var vw = window.innerWidth;
      var vh = window.innerHeight;
      var a = aperture.getBoundingClientRect();
      var w = wordmark.getBoundingClientRect();
      var iRect = interior.getBoundingClientRect();
      var track = portalContainer.offsetHeight - vh;

      if (!w.width || !w.height || iRect.width < 1 || track <= 0) { geo = null; return; }

      // Le disque se tient un cheveu EN DEÇÀ du bord intérieur de l'anneau :
      // sinon le crénelage laisse apparaître un liseré de page entre les deux.
      var holeR = (iRect.width / 2) * 0.97;
      var cx = a.left + a.width / 2;
      var cy = a.top + a.height / 2;

      geo = {
        trackTop: portalContainer.offsetTop,
        track: track,
        cx: cx,
        cy: cy,
        holeR: holeR,
        // Décalage à parcourir pour amener le centre du « O » au centre de
        // l'écran. Avec transform-origin posé sur ce même centre, un
        // translate() le déplace d'autant de pixels quelle que soit l'échelle.
        dx: vw / 2 - cx,
        dy: vh / 2 - cy,
        // Échelle nécessaire pour que l'ouverture couvre l'écran en entier,
        // diagonale comprise. Calculée et non devinée : un facteur fixe est
        // soit insuffisant sur grand écran, soit inutilement coûteux sur petit.
        maxScale: clamp((Math.sqrt(vw * vw + vh * vh) / 2 / holeR) * 1.04, 4, 80)
      };

      wordmark.style.transformOrigin =
        ((cx - w.left) / w.width * 100).toFixed(2) + "% " +
        ((cy - w.top) / w.height * 100).toFixed(2) + "%";

      apply();
    }

    function apply() {
      ticking = false;
      if (!geo) return;

      var progress = clamp((lastScroll - geo.trackTop) / geo.track, 0, 1);

      // 1. L'appui s'efface en premier (0.02 → 0.16). La petite zone morte
      //    évite qu'un micro-défilement de trackpad n'escamote les boutons.
      var pSupport = clamp((progress - 0.02) / 0.14, 0, 1);
      heroSupport.style.opacity = (1 - pSupport).toFixed(3);
      heroSupport.style.transform = "translateY(" + (-24 * pSupport).toFixed(1) + "px)";
      heroSupport.style.pointerEvents = pSupport > 0.5 ? "none" : "auto";

      // 2. La question s'efface ensuite (0.06 → 0.26) : elle reste lisible
      //    pendant que la plongée s'amorce.
      var pQuestion = clamp((progress - 0.06) / 0.20, 0, 1);
      heroQuestion.style.opacity = (1 - pQuestion).toFixed(3);
      heroQuestion.style.transform = "translateY(" + (-42 * pQuestion).toFixed(1) + "px)";
      answerCue.style.opacity = (1 - pQuestion).toFixed(3);

      // 3. Recentrage du « O » (0 → 0.30), puis plongée (0.10 → 0.82).
      //    La plongée s'achève avant la fin de la piste : les ~18 % restants
      //    sont un temps de pause, une fois arrivé à l'intérieur.
      var pMove = easeOut(clamp(progress / 0.30, 0, 1));
      var pZoom = clamp((progress - 0.10) / 0.72, 0, 1);
      var scale = 1 + (geo.maxScale - 1) * Math.pow(pZoom, 2.6);

      wordmark.style.transform =
        "translate(" + (geo.dx * pMove).toFixed(1) + "px," + (geo.dy * pMove).toFixed(1) +
        "px) scale(" + scale.toFixed(4) + ")";

      // 4. L'ouverture. Elle suit le trou du « O » à l'écran : même centre,
      //    même rayon. Le contenu dessous ne bouge ni ne grandit.
      reveal.style.setProperty("--portal-r", (geo.holeR * scale).toFixed(1) + "px");
      reveal.style.setProperty("--portal-cx", (geo.cx + geo.dx * pMove).toFixed(1) + "px");
      reveal.style.setProperty("--portal-cy", (geo.cy + geo.dy * pMove).toFixed(1) + "px");

      // 5. Le contenu ne se révèle que lorsque l'ouverture est assez large
      //    pour en montrer autre chose qu'un fragment.
      hud.style.opacity = clamp((progress - 0.58) / 0.20, 0, 1).toFixed(3);
    }

    // Le défilement est lu ICI, jamais dans la frame : lire scrollY après avoir
    // écrit des styles forcerait le recalcul qu'on cherche justement à éviter.
    function onScrollPortal() {
      lastScroll = window.scrollY || window.pageYOffset;
      if (!ticking) {
        ticking = true;
        requestAnimationFrame(apply);
      }
    }

    // Le redimensionnement passe par le même garde `ticking` et par une
    // temporisation : sans elle, chaque événement empilait sa propre frame.
    var resizeTimer = null;
    function onResize() {
      if (resizeTimer) clearTimeout(resizeTimer);
      resizeTimer = setTimeout(function () {
        resizeTimer = null;
        measure();
      }, 120);
    }

    window.addEventListener("scroll", onScrollPortal, { passive: true });
    window.addEventListener("resize", onResize);

    measure();
    // Les polices d'affichage changent la largeur du mot-marque, donc la
    // position du « O » : on remesure une fois qu'elles sont posées.
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(measure).catch(function () {});
    }
  }
})();
