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

    if (reduced) return;

    // ------------------------------------------------------------- Les scènes
    var scenes = [].slice.call(document.querySelectorAll("[data-kx-scene]")).map(construire).filter(Boolean);
    if (!scenes.length) return;

    var dernier = window.scrollY || window.pageYOffset;
    var enCours = false;

    function image() {
      enCours = false;
      var vh = window.innerHeight;
      for (var i = 0; i < scenes.length; i++) scenes[i].appliquer(dernier, vh);
    }
    function auDefilement() {
      dernier = window.scrollY || window.pageYOffset;
      if (!enCours) { enCours = true; requestAnimationFrame(image); }
    }
    function mesurer() {
      for (var i = 0; i < scenes.length; i++) scenes[i].mesurer();
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

    function mesurer() {
      var r = el.getBoundingClientRect();
      var sy = window.scrollY || window.pageYOffset;
      var course = el.offsetHeight - window.innerHeight;
      geo = course > 0 ? { haut: r.top + sy, course: course } : null;
    }

    function formater(n) {
      return Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");
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

    function appliquer(sy) {
      if (!geo) return;
      var p = clamp((sy - geo.haut) / geo.course, 0, 1);

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
