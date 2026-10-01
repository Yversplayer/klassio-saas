// KLASSIO — moteur des scènes cinématiques (landing, démonstration, pages publiques).
//
// CE QUE FAIT CE FICHIER, ET CE QU'IL NE FAIT PAS
//
// Il lit le défilement et écrit, sur chaque scène, deux choses : --p (la
// progression sur la piste, de 0 à 1) et data-beat (l'étape en cours). Tout le
// reste — l'ordinateur qui s'ouvre, le téléphone qui entre, les fondus — est
// calculé en CSS à partir de ces deux valeurs, dans cine.css.
//
// Il ne crée aucun contenu. Chaque texte, chaque écran existe déjà dans le
// balisage : sans ce script, ou en mouvement réduit, la scène reste à plat et
// tout s'y lit. C'est la règle de la landing — états d'ARRIVÉE en CSS, états
// de DÉPART posés ici — et c'est ce qui garantit qu'un mouvement en moins ne
// coûte jamais une information.
//
// MÊME DISCIPLINE QUE LE PORTAIL DE main.js, POUR LES MÊMES RAISONS
//   - la géométrie est mesurée une fois (chargement, polices, redimension) ;
//   - le défilement est lu dans l'écouteur, jamais dans l'image : lire une
//     position après avoir écrit un style force un recalcul de mise en page ;
//   - l'image n'écrit que des propriétés, et seulement si elles ont changé.
(function () {
  "use strict";

  var docEl = document.documentElement;
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ------------------------------------------------------------ Économie de données
  // Un visiteur en mode « économie de données », ou sur une connexion
  // « slow-2g », ne charge aucune photographie : la miniature floue reste, le
  // texte aussi. Les images sont en chargement différé ; masquées par
  // `.kx-lite`, elles ne sont jamais demandées au serveur.
  //
  // PAS « 2g » : l'estimation du navigateur fluctue. Constaté en test, sur un
  // serveur LOCAL, la page s'est chargée classée « 2g » puis est passée à
  // « 3g » une seconde plus tard. À Kinshasa, masquer dès « 2g » priverait des
  // photos des visiteurs qui les chargeraient sans peine — les images font 10
  // à 50 Ko en version mobile, et la miniature floue tient l'écran pendant
  // qu'elles arrivent.
  try {
    var c = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    if (c && (c.saveData || c.effectiveType === "slow-2g")) docEl.classList.add("kx-lite");
  } catch (e) { /* API absente : on charge normalement. */ }

  function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }

  function lancer() {
    // -------------------------------------------------------- Écrans dupliqués
    // Le portable du « O » montre le même tableau de bord que la scène des
    // rôles. Plutôt que de recopier quarante lignes de balisage — qui
    // divergeraient à la première retouche — on le clone. Le « O » n'existe
    // que lorsque le script tourne ; la scène des rôles, elle, garde son
    // balisage réel et se lit sans script.
    [].forEach.call(document.querySelectorAll("[data-kx-clone]"), function (cible) {
      var source = document.querySelector(cible.getAttribute("data-kx-clone"));
      if (!source || cible.childElementCount) return;
      cible.appendChild(source.cloneNode(true));
      var copie = cible.lastElementChild;
      copie.removeAttribute("id");
      copie.classList.add("is-on");
    });

    // ------------------------------------------------ Apparition à l'écran
    var aVoir = document.querySelectorAll("[data-kx-inview]");
    if (aVoir.length && "IntersectionObserver" in window) {
      var io = new IntersectionObserver(function (entrees) {
        entrees.forEach(function (e) {
          if (e.isIntersecting) { e.target.classList.add("in-view"); io.unobserve(e.target); }
        });
      }, { threshold: 0.25 });
      [].forEach.call(aVoir, function (el) { io.observe(el); });
    } else {
      [].forEach.call(aVoir, function (el) { el.classList.add("in-view"); });
    }

    // ------------------------------------------------ Suivi de section
    // L'onglet de la section qu'on lit s'allume, et la lampe s'y déplace. Ce
    // n'est pas une animation : c'est un repère. Il tourne donc aussi en
    // mouvement réduit.
    suiviDeSection();

    // ---------------------------------------- Pied de page en rideau : clavier
    // Le pied de page est fixe sous la page. Un utilisateur au clavier qui y
    // entre par Tab focalise des liens découpés hors de l'écran — et un
    // élément fixe ne fait pas défiler la page quand il prend le focus. On
    // amène donc le rideau à l'écran dès que le focus y entre.
    [].forEach.call(document.querySelectorAll("[data-kx-footer]"), function (rideau) {
      rideau.addEventListener("focusin", function () {
        var r = rideau.getBoundingClientRect();
        if (r.top > 1) window.scrollTo(0, (window.scrollY || window.pageYOffset) + r.top);
      });
    });

    if (reduced) return;

    // Les états de DÉPART ne sont posés qu'ici, une fois le mouvement acquis :
    // sans script ou en mouvement réduit, cartes, filets et chiffres sont déjà
    // en place.
    departsAuVisible("[data-kx-arrive]", "kx-arriving");
    departsAuVisible("[data-kx-steps]", "kx-pending");
    compteursAuVisible();

    // ----------------------------------------------------------- Les effets
    // Scènes épinglées, colonnes de la galerie, pied de page : une seule
    // boucle de défilement pour tous.
    var effets = [].slice.call(document.querySelectorAll("[data-kx-scene]")).map(construire)
      .concat([].slice.call(document.querySelectorAll("[data-kx-speed]")).map(colonne))
      .concat([].slice.call(document.querySelectorAll("[data-kx-footer]")).map(rideauPied))
      .filter(Boolean);
    if (!effets.length) return;

    var dernier = window.scrollY || window.pageYOffset;
    var enCours = false;

    function image() {
      enCours = false;
      var vh = window.innerHeight, vw = window.innerWidth;
      for (var i = 0; i < effets.length; i++) effets[i].appliquer(dernier, vh, vw);
    }
    function auDefilement() {
      dernier = window.scrollY || window.pageYOffset;
      if (!enCours) { enCours = true; requestAnimationFrame(image); }
    }
    function mesurer() {
      for (var i = 0; i < effets.length; i++) effets[i].mesurer();
      dernier = window.scrollY || window.pageYOffset;
      image();
    }
    var minuterie = null;
    window.addEventListener("scroll", auDefilement, { passive: true });
    window.addEventListener("resize", function () {
      if (minuterie) clearTimeout(minuterie);
      minuterie = setTimeout(function () { minuterie = null; mesurer(); }, 140);
    });
    mesurer();
    // Les polices d'affichage, puis les images, déplacent la mise en page après
    // le premier calcul : on remesure à ces deux moments, pas à chaque image.
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(mesurer).catch(function () {});
    window.addEventListener("load", mesurer);

    // LA PAGE CHANGE DE HAUTEUR APRÈS « load ». Les photos de la galerie sont
    // en chargement différé, sans hauteur réservée : elles arrivent quand on
    // s'en approche, et tout ce qui est en dessous descend — FAQ, contact,
    // pied de page. Le rideau gardait l'ancienne position du pied de page : il
    // se levait 300 px trop tôt, hors de l'écran, et on arrivait sur un pied
    // de page déjà posé — l'effet de fin avait « disparu » (constaté le 01/10).
    // On remesure donc à chaque changement de hauteur du document.
    if ("ResizeObserver" in window) {
      var hauteur = document.documentElement.scrollHeight;
      var reMesure = null;
      new ResizeObserver(function () {
        var h = document.documentElement.scrollHeight;
        if (Math.abs(h - hauteur) < 2) return;
        hauteur = h;
        if (reMesure) clearTimeout(reMesure);
        reMesure = setTimeout(function () { reMesure = null; mesurer(); }, 120);
      }).observe(document.body);
    }
  }

  function hautDoc(el) {
    return el.getBoundingClientRect().top + (window.scrollY || window.pageYOffset);
  }
  function adoucir(t) { return 1 - Math.pow(1 - t, 3); }
  function formater(n) {
    return Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, "\u202f");
  }

  // Pose une classe de DÉPART, puis la retire à l'arrivée à l'écran — c'est
  // l'ajout de `in-view` qui déclenche la transition vers l'état normal.
  function departsAuVisible(selecteur, classe) {
    var els = document.querySelectorAll(selecteur);
    if (!els.length || !("IntersectionObserver" in window)) return;
    var io = new IntersectionObserver(function (entrees) {
      entrees.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add("in-view"); io.unobserve(e.target); }
      });
    }, { threshold: 0.18 });
    [].forEach.call(els, function (el) { el.classList.add(classe); io.observe(el); });
  }

  // Les chiffres montent de zéro quand ils arrivent à l'écran. La valeur
  // d'arrivée est dans le balisage : c'est elle qu'on lit sans script.
  function compteursAuVisible() {
    var els = document.querySelectorAll("[data-kx-countup]");
    if (!els.length || !("IntersectionObserver" in window)) return;
    var io = new IntersectionObserver(function (entrees) {
      entrees.forEach(function (e) {
        if (!e.isIntersecting) return;
        io.unobserve(e.target);
        var el = e.target, cible = parseFloat(el.getAttribute("data-kx-countup")), debut = null;
        (function pas(t) {
          if (debut === null) debut = t;
          var k = clamp((t - debut) / 1400, 0, 1);
          el.textContent = formater(cible * adoucir(k));
          if (k < 1) requestAnimationFrame(pas);
        })(performance.now());
      });
    }, { threshold: 0.4 });
    [].forEach.call(els, function (el) { el.textContent = "0"; io.observe(el); });
  }

  // L'onglet actif suit la section lue : la dernière dont le haut a passé le
  // tiers supérieur de l'écran.
  function suiviDeSection() {
    var liens = [].slice.call(document.querySelectorAll("[data-kx-spy]"));
    if (!liens.length) return;
    var cibles = liens.map(function (a) { return document.getElementById(a.getAttribute("data-kx-spy")); });
    var courant = null, enCours = false;
    function verifier() {
      enCours = false;
      var seuil = window.innerHeight * 0.35, actif = null;
      for (var i = 0; i < cibles.length; i++) {
        if (cibles[i] && cibles[i].getBoundingClientRect().top <= seuil) actif = liens[i];
      }
      if (actif === courant) return;
      courant = actif;
      liens.forEach(function (a) { a.classList.toggle("active", a === actif); });
      var lampe = document.querySelector("#tubelightNav .tubelight-lamp");
      if (lampe && lampe.placer) lampe.placer();
    }
    window.addEventListener("scroll", function () {
      if (!enCours) { enCours = true; requestAnimationFrame(verifier); }
    }, { passive: true });
    verifier();
  }

  // Une colonne de la galerie glisse à sa propre vitesse autour du centre de
  // l'écran : douce parallaxe, jamais plus de quelques dizaines de pixels.
  function colonne(el) {
    var vitesse = parseFloat(el.getAttribute("data-kx-speed")) || 0;
    if (!vitesse) return null;
    var geo = null, ecrit = null;
    return {
      mesurer: function () {
        el.style.transform = "";
        geo = { centre: hautDoc(el) + el.offsetHeight / 2 };
      },
      appliquer: function (sy, vh) {
        if (!geo) return;
        var y = Math.round((geo.centre - (sy + vh / 2)) * vitesse);
        if (y !== ecrit) { ecrit = y; el.style.transform = "translate3d(0," + y + "px,0)"; }
      }
    };
  }

  // Le rideau : --fp monte de 0 à 1 pendant que l'enveloppe du pied de page
  // entre à l'écran. Le nom géant monte et se pose, l'appel apparaît.
  function rideauPied(el) {
    var pied = el.querySelector(".kx-foot");
    if (!pied) return null;
    var geo = null, ecrit = -1;
    return {
      mesurer: function () { geo = { haut: hautDoc(el), h: el.offsetHeight }; },
      appliquer: function (sy, vh) {
        if (!geo) return;
        var p = clamp((sy + vh - geo.haut) / (geo.h * 0.85), 0, 1);
        if (Math.abs(p - ecrit) > 0.002) { ecrit = p; pied.style.setProperty("--fp", adoucir(p).toFixed(3)); }
      }
    };
  }

  // Découpe un texte en caractères (.kx-ch), mot par mot insécable, en
  // laissant intacts les SVG — l'ovale du manifeste en est un.
  function decouper(racine) {
    var lettres = [];
    (function parcourir(noeud) {
      [].slice.call(noeud.childNodes).forEach(function (enfant) {
        if (enfant.nodeType === 3) {
          var frag = document.createDocumentFragment();
          enfant.textContent.split(/(\s+)/).forEach(function (morceau) {
            if (!morceau) return;
            if (/^\s+$/.test(morceau)) { frag.appendChild(document.createTextNode(" ")); return; }
            var mot = document.createElement("span");
            mot.style.whiteSpace = "nowrap";
            for (var i = 0; i < morceau.length; i++) {
              var c = document.createElement("span");
              c.className = "kx-ch";
              c.textContent = morceau[i];
              mot.appendChild(c);
              lettres.push(c);
            }
            frag.appendChild(mot);
          });
          noeud.replaceChild(frag, enfant);
        } else if (enfant.nodeType === 1 && enfant.tagName.toLowerCase() !== "svg") {
          parcourir(enfant);
        }
      });
    })(racine);
    return lettres;
  }

  // Le train de mots de la devise : chaque mot passe au centre, ses lettres
  // dispersées s'y posent (d'après le moteur « Site Immersif »).
  function trainDeMots(train) {
    var mots = [].slice.call(train.querySelectorAll(".kx-motto-word")).map(function (m) {
      var mw = m.querySelector(".kx-mw");
      var texte = mw.textContent;
      mw.textContent = "";
      var lettres = [];
      for (var i = 0; i < texte.length; i++) {
        var sc = document.createElement("span");
        sc.className = "kx-sc";
        sc.textContent = texte[i];
        mw.appendChild(sc);
        lettres.push({ el: sc, amp: ((((i * 7919 + 31) % 13) - 6) / 6) || 0.45 });
      }
      return { el: m, lettres: lettres, centre: 0 };
    });
    return {
      mesurer: function () {
        train.style.transform = "";
        mots.forEach(function (m) { m.centre = m.el.offsetLeft + m.el.offsetWidth / 2; });
      },
      appliquer: function (p, vh, vw) {
        if (!mots.length) return;
        var t = clamp((p - 0.02) / 0.96, 0, 1);
        var x = vw / 2 - (mots[0].centre + (mots[mots.length - 1].centre - mots[0].centre) * t);
        train.style.transform = "translate3d(" + x.toFixed(1) + "px,0,0)";
        // Zone morte autour du centre : le mot lu est posé à plat, et son
        // sous-titre (18 px dessous) n'est plus traversé par des lettres
        // encore en vol. Sur téléphone, un mot occupe presque toute la
        // largeur : il reste longtemps « presque centré », d'où une
        // amplitude réduite — à 375 px, les lettres chevauchaient le texte.
        var amp = vh * (vw < 700 ? 0.16 : 0.3);
        mots.forEach(function (m) {
          var rel = clamp((m.centre + x - vw / 2) / vw, -1.3, 1.3);
          var vol = rel > 0 ? Math.max(0, rel - 0.12) : Math.min(0, rel + 0.12);
          m.el.style.opacity = (1 - Math.min(Math.abs(rel) * 1.1, 0.75)).toFixed(3);
          m.lettres.forEach(function (l) {
            l.el.style.transform = "translate3d(0," + (l.amp * vol * amp).toFixed(1) + "px,0) rotate(" + (l.amp * vol * 6).toFixed(2) + "deg)";
          });
        });
      }
    };
  }

  // Une scène : une piste haute (data-kx-track, en vh), un plateau épinglé,
  // un nombre d'étapes (data-kx-beats). Renvoie null s'il manque quelque
  // chose — la scène reste alors à plat, ce qui est un état complet.
  function construire(el) {
    var etapes = parseInt(el.getAttribute("data-kx-beats"), 10) || 1;
    var piste = parseFloat(el.getAttribute("data-kx-track")) || 400;
    if (!el.querySelector(".kx-sticky")) return null;

    el.classList.add("kx-live");
    el.style.setProperty("--kx-track", piste + "vh");

    var ecrans = [].slice.call(el.querySelectorAll(".kx-scr[data-on]")).map(function (s) {
      return { el: s, sur: s.getAttribute("data-on").split(",").map(Number) };
    });

    // L'horloge de la journée : l'heure court avec le défilement, d'un repère
    // au suivant. data-kx-times donne les repères en minutes depuis minuit
    // (un de plus que d'étapes : le dernier est l'heure de fin).
    var horloge = el.querySelector("[data-kx-clock]");
    var reperes = (el.getAttribute("data-kx-times") || "").split(",").map(Number).filter(function (n) { return !isNaN(n); });

    // Les compteurs : valeur d'ARRIVÉE écrite dans le balisage (juste sans
    // script) ; on repart de zéro ici, et on compte une seule fois, quand
    // l'étape qui les montre est atteinte.
    var compteurs = [].slice.call(el.querySelectorAll("[data-kx-count]")).map(function (n) {
      var cible = parseFloat(n.getAttribute("data-kx-count"));
      var suffixe = n.getAttribute("data-kx-suffix") || "";
      var aPartir = parseInt(n.getAttribute("data-kx-count-beat"), 10) || 1;
      n.textContent = "0" + suffixe;
      return { el: n, cible: cible, suffixe: suffixe, aPartir: aPartir, fait: false };
    });

    var geo = null;
    var pEcrit = -1;
    var etapeEcrite = -1;
    var minuteEcrite = -1;

    // Manifeste : le texte n'est découpé en lettres que s'il va s'animer.
    var encre = el.querySelector("[data-kx-ink]");
    var lettres = encre ? decouper(encre) : [];
    var encreEcrite = 0;
    // Devise : le train de mots.
    var trainEl = el.querySelector("[data-kx-motto]");
    var train = trainEl ? trainDeMots(trainEl) : null;

    // Séquences : une file d'éléments qui s'allument un à un sur une portion
    // de la piste — l'appel de la démonstration, où les mains se lèvent
    // l'une après l'autre pendant que la ligne de l'élève se coche sur le
    // téléphone. data-kx-seq="0.18 0.62" : début et fin, en progression de
    // scène. Les éléments de même data-kx-i avancent ENSEMBLE, où qu'ils
    // soient dans la scène (l'élève dans la classe, sa ligne à l'écran) :
    // .is-on quand leur tour est venu, .is-now pendant leur tour, et --seq
    // (0 → 1) sur le conteneur. L'ARRIVÉE — tout coché — est écrite dans le
    // balisage : sans script, l'appel s'affiche terminé ; le départ n'existe
    // qu'ici (règle 1).
    var sequences = [].slice.call(el.querySelectorAll("[data-kx-seq]")).map(function (s) {
      var bornes = s.getAttribute("data-kx-seq").split(/[\s,]+/).map(Number);
      var items = [].slice.call(s.querySelectorAll("[data-kx-i]")).map(function (it) {
        return { el: it, i: parseInt(it.getAttribute("data-kx-i"), 10) || 0 };
      });
      var n = 0;
      items.forEach(function (it) { n = Math.max(n, it.i + 1); });
      return { el: s, a: bornes[0] || 0, b: bornes[1] || 1, items: items, n: n, tour: -2, loc: -1 };
    });

    function mesurer() {
      var r = el.getBoundingClientRect();
      var sy = window.scrollY || window.pageYOffset;
      var course = el.offsetHeight - window.innerHeight;
      geo = course > 0 ? { haut: r.top + sy, course: course } : null;
      if (train) train.mesurer();
    }

    function compter(c) {
      c.fait = true;
      var debut = null;
      var duree = 1300;
      function pas(t) {
        if (debut === null) debut = t;
        var k = clamp((t - debut) / duree, 0, 1);
        var e = 1 - Math.pow(1 - k, 3);
        c.el.textContent = formater(c.cible * e) + c.suffixe;
        if (k < 1) requestAnimationFrame(pas);
      }
      requestAnimationFrame(pas);
    }

    function appliquer(sy, vh, vw) {
      if (!geo) return;
      var p = clamp((sy - geo.haut) / geo.course, 0, 1);

      if (lettres.length) {
        var n = Math.round(clamp((p - 0.04) / 0.5, 0, 1) * lettres.length);
        if (n !== encreEcrite) {
          var lo = Math.min(n, encreEcrite), hi = Math.max(n, encreEcrite);
          for (var q = lo; q < hi; q++) lettres[q].classList.toggle("on", q < n);
          encreEcrite = n;
        }
      }
      if (train) train.appliquer(p, vh, vw);

      for (var sq = 0; sq < sequences.length; sq++) {
        var seq = sequences[sq];
        var loc = clamp((p - seq.a) / (seq.b - seq.a), 0, 1);
        if (Math.abs(loc - seq.loc) > 0.001) {
          seq.loc = loc;
          seq.el.style.setProperty("--seq", loc.toFixed(3));
        }
        var tour = loc <= 0 ? -1 : (loc >= 1 ? seq.n : Math.min(seq.n - 1, Math.floor(loc * seq.n)));
        if (tour !== seq.tour) {
          seq.tour = tour;
          for (var it = 0; it < seq.items.length; it++) {
            seq.items[it].el.classList.toggle("is-on", seq.items[it].i <= tour);
            seq.items[it].el.classList.toggle("is-now", seq.items[it].i === tour);
          }
        }
      }

      if (Math.abs(p - pEcrit) > 0.0004) {
        pEcrit = p;
        el.style.setProperty("--p", p.toFixed(4));
      }

      var etape = clamp(Math.floor(p * etapes * 0.99999), 0, etapes - 1);
      if (etape !== etapeEcrite) {
        etapeEcrite = etape;
        el.setAttribute("data-beat", String(etape));
        for (var i = 0; i < ecrans.length; i++) {
          ecrans[i].el.classList.toggle("is-on", ecrans[i].sur.indexOf(etape) !== -1);
        }
        for (var k = 0; k < compteurs.length; k++) {
          if (!compteurs[k].fait && etape >= compteurs[k].aPartir) compter(compteurs[k]);
        }
      }

      if (horloge && reperes.length > etapes) {
        var dans = clamp(p * etapes - etape, 0, 1);
        var minutes = Math.round(reperes[etape] + (reperes[etape + 1] - reperes[etape]) * dans);
        if (minutes !== minuteEcrite) {
          minuteEcrite = minutes;
          var h = Math.floor(minutes / 60), m = minutes % 60;
          horloge.innerHTML = (h < 10 ? "0" : "") + h + "<span>:</span>" + (m < 10 ? "0" : "") + m;
        }
      }
    }

    return { mesurer: mesurer, appliquer: appliquer };
  }

  // Chargé en fin de page, AVANT main.js : tout le balisage au-dessus est déjà
  // là, et les scènes doivent avoir pris leur hauteur définitive avant que
  // main.js mesure les effets du récit situés sous elles. Attendre
  // DOMContentLoaded les ferait passer après lui, sur une page trop courte.
  if (document.body) lancer();
  else document.addEventListener("DOMContentLoaded", lancer);
})();
