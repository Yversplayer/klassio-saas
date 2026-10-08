// KLASSIO — langue de l'interface (08/10/2026).
//
// Le propriétaire : « si l'utilisateur préfère utiliser le logiciel en
// anglais, il le peut via les paramètres », dans un lot de langues pour un
// usage international.
//
// LE PRINCIPE. Le logiciel est écrit en français, dans ~30 pages et leurs
// scripts. Plutôt que de réécrire chaque écran autour de clés, la phrase
// française AFFICHÉE sert de clé : ce script parcourt le texte rendu (et les
// placeholder, title, aria-label, alt), le remplace par sa traduction, et
// observe le DOM pour traduire ce que les scripts ajoutent ensuite. Les
// dictionnaires vivent dans assets/i18n/<code>.js, produits depuis
// tools/i18n/<code>.json ; tools/i18n/extraire.py dresse la liste des phrases.
//
// CE QUI N'EST JAMAIS TRADUIT. Les données de l'école (noms d'élèves, de
// classes, montants, codes) ne sont pas dans les dictionnaires : elles
// passent telles quelles. Un élément marqué data-no-tr ou translate="no" est
// laissé intact. Les documents produits par le serveur (bulletins PDF,
// emails, exports) restent en français.
//
// CHARGEMENT. Ce fichier est appelé dans le <head>, avant tout autre script
// de page. Pour une autre langue que le français, il écrit la balise du
// dictionnaire (même origine : la CSP script-src 'self' l'accepte) et masque
// la page jusqu'à la première traduction — sans quoi on lirait le français
// une fraction de seconde. Un filet de 1,5 s rend la page visible quoi qu'il
// arrive : une traduction en retard ne doit jamais donner une page blanche.
(function () {
  "use strict";
  var LANGUES = [
    { code: "fr", nom: "Français", region: "Langue d'origine", locale: "fr-FR" },
    { code: "en", nom: "English", region: "Anglais", locale: "en-GB" },
    // Une langue n'entre dans cette liste qu'avec son dictionnaire complet
    // (assets/i18n/<code>.js) : proposer une langue sans traduction ferait
    // croire qu'elle existe. Le serveur accepte déjà es, pt, de, sw, ln.
  ];
  var CLE = "klassio_langue";
  var parCode = {};
  LANGUES.forEach(function (l) { parCode[l.code] = l; });

  function lire() {
    try { var v = localStorage.getItem(CLE); return parCode[v] ? v : "fr"; } catch (e) { return "fr"; }
  }
  var langue = lire();
  var info = parCode[langue];
  var root = document.documentElement;
  root.setAttribute("lang", langue);
  window.KLASSIO_LOCALE = info.locale;

  var moi = document.currentScript && document.currentScript.src;
  var base = moi ? moi.replace(/js\/langue\.js.*$/, "") : "../assets/";
  var VERSION = "1847366190";

  if (langue !== "fr") {
    root.classList.add("kl-attente");
    document.write('<style>html.kl-attente body{visibility:hidden}</style>');
    document.write('<script src="' + base + "i18n/" + langue + ".js?v=" + VERSION + '"><\/script>');
    setTimeout(function () { root.classList.remove("kl-attente"); }, 1500);
  }

  // ------------------------------------------------------------------
  // Traduction d'un texte
  // ------------------------------------------------------------------
  var D = null, P = [], profondeur = 0;
  var ESPACES = /\s+/g;
  var NOMBRE = /\d+(?:[\s.,]\d+)*/g;

  function cle(s) { return s.replace(ESPACES, " ").trim(); }

  function traduireCle(k) {
    if (!k || !D) return null;
    var t = D[k];
    if (t != null) return t;
    // Les nombres changent, la phrase non : « 3 jours restants » se cherche
    // sous « {n} jours restants ».
    var nombres = [];
    var gabarit = k.replace(NOMBRE, function (m) { nombres.push(m); return "{n}"; });
    if (nombres.length && D[gabarit] != null) {
      var i = 0;
      return D[gabarit].replace(/\{n\}/g, function () { return nombres[i++] || ""; });
    }
    // Un nombre en tête : « 3 jours restants » → « jours restants »,
    // « 100 % des élèves » → « % des élèves ».
    var tete = k.match(/^((?:\d[\d\s.,]*\d|\d)(?:\s?(?:\$|FC|€))?)\s*(%.*|[^\d\s].*)$/);
    if (tete && D[tete[2]] != null) return tete[1] + (tete[2].charAt(0) === "%" ? "" : " ") + D[tete[2]];
    // Un nombre en queue : « Octobre 2026 », « Période 3 ».
    var queue = k.match(/^(.*\D)\s+(\d[\d\s.,\-–\/]*)$/);
    if (queue && D[queue[1]] != null) return D[queue[1]] + " " + queue[2];
    // Plusieurs morceaux assemblés : « 42 classes · 8 enseignants ».
    var sep = k.indexOf(" · ") >= 0 ? " · " : k.indexOf(" — ") >= 0 ? " — " : null;
    if (sep && profondeur < 2) {
      profondeur++;
      var change = false;
      var parts = k.split(sep).map(function (p) {
        var tp = traduireCle(p.trim());
        if (tp != null) { change = true; return tp; }
        return p;
      });
      profondeur--;
      if (change) return parts.join(sep);
    }
    // Phrases qui enveloppent une donnée (« Bonjour, Awa. »).
    for (var j = 0; j < P.length; j++) {
      var m = k.match(P[j][0]);
      if (m) {
        // $1 recopie la donnée telle quelle (un nom, une date) ; $T1 la
        // traduit si c'est une phrase connue (le titre d'une page).
        return P[j][1].replace(/\$(T?)(\d)/g, function (_, tr, n) {
          var g = m[+n] || "";
          if (!tr) return g;
          var tg = traduireCle(cle(g));
          return tg != null ? tg : g;
        });
      }
    }
    return null;
  }

  function traduire(texte) {
    if (!texte || !/[A-Za-zÀ-ÿ]/.test(texte)) return null;
    var t = traduireCle(cle(texte));
    if (t == null) return null;
    var debut = texte.match(/^\s*/)[0], fin = texte.match(/\s*$/)[0];
    return debut + t + fin;
  }

  // ------------------------------------------------------------------
  // Parcours du DOM
  // ------------------------------------------------------------------
  var IGNORE = { SCRIPT: 1, STYLE: 1, TEXTAREA: 1, NOSCRIPT: 1, CODE: 1, PRE: 1 };
  var ATTRS = ["placeholder", "title", "aria-label", "alt"];
  var poses = new WeakMap();

  function protege(el) {
    return !el || IGNORE[el.nodeName] || (el.closest && el.closest("[data-no-tr],[translate='no'],[contenteditable='true']"));
  }

  function texteNoeud(n) {
    if (poses.get(n) === n.nodeValue) return;
    if (protege(n.parentElement)) return;
    var t = traduire(n.nodeValue);
    if (t != null && t !== n.nodeValue) { n.nodeValue = t; poses.set(n, t); }
  }

  function attributs(el) {
    if (protege(el)) return;
    for (var i = 0; i < ATTRS.length; i++) {
      var v = el.getAttribute(ATTRS[i]);
      if (v) {
        var t = traduire(v);
        if (t != null && t !== v) el.setAttribute(ATTRS[i], t);
      }
    }
    if (el.nodeName === "INPUT" && (el.type === "submit" || el.type === "button") && el.value) {
      var tv = traduire(el.value);
      if (tv != null) el.value = tv;
    }
  }

  function parcourir(racine) {
    if (!racine) return;
    if (racine.nodeType === 3) { texteNoeud(racine); return; }
    if (racine.nodeType !== 1 || protege(racine)) return;
    attributs(racine);
    var w = document.createTreeWalker(racine, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode: function (n) {
        if (n.nodeType === 1 && (IGNORE[n.nodeName] || n.hasAttribute("data-no-tr") || n.getAttribute("translate") === "no")) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    var n;
    while ((n = w.nextNode())) {
      if (n.nodeType === 3) texteNoeud(n); else attributs(n);
    }
  }

  function demarrer() {
    D = (window.KLASSIO_I18N && window.KLASSIO_I18N.d) || null;
    if (!D) { root.classList.remove("kl-attente"); return; }
    P = (window.KLASSIO_I18N.p || []).map(function (r) { return [new RegExp(r[0]), r[1]]; });
    var titre = traduire(document.title);
    if (titre) document.title = titre;
    parcourir(document.body);
    root.classList.remove("kl-attente");
    new MutationObserver(function (mutations) {
      for (var i = 0; i < mutations.length; i++) {
        var m = mutations[i];
        if (m.type === "childList") {
          for (var j = 0; j < m.addedNodes.length; j++) parcourir(m.addedNodes[j]);
        } else if (m.type === "characterData") {
          texteNoeud(m.target);
        } else if (m.type === "attributes") {
          attributs(m.target);
        }
      }
    }).observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });
    // Le titre de l'onglet change avec certaines pages (nom de l'école).
    var t = document.querySelector("title");
    if (t) new MutationObserver(function () {
      var tt = traduire(document.title);
      if (tt && tt !== document.title) document.title = tt;
    }).observe(t, { childList: true, characterData: true, subtree: true });
  }

  if (langue !== "fr") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", demarrer);
    else demarrer();
  }

  // ------------------------------------------------------------------
  // Choix de la langue
  // ------------------------------------------------------------------
  // Mémorisée sur l'appareil (pour s'appliquer dès la première image) ET
  // sur le compte (PUT /api/me/preferences), pour suivre l'utilisateur d'un
  // appareil à l'autre : /me la renvoie, et `accorder` aligne l'appareil.
  function memoriser(code) { try { localStorage.setItem(CLE, code); } catch (e) {} }

  function choisir(code) {
    if (!parCode[code]) return Promise.resolve(false);
    var api = window.KlassioApi;
    if (!api) { memoriser(code); return Promise.resolve(true); }
    return api.fetch("/me/preferences", { method: "PUT", body: JSON.stringify({ language: code }) }).then(function (r) {
      if (!r.ok) return false;
      memoriser(code);
      return true;
    }).catch(function () { return false; });
  }

  // Appelée par la coquille une fois /me reçu. Une seule tentative par
  // onglet : si l'appareil ne peut rien mémoriser, on ne boucle pas.
  function accorder(code) {
    if (!code || !parCode[code] || code === langue) return;
    try {
      if (sessionStorage.getItem("klassio_langue_accord") === code) return;
      sessionStorage.setItem("klassio_langue_accord", code);
    } catch (e) { return; }
    memoriser(code);
    window.location.reload();
  }

  window.KlassioLangue = {
    liste: function () { return LANGUES.slice(); },
    actuelle: function () { return langue; },
    choisir: choisir,
    accorder: accorder,
    t: function (s) { return (langue !== "fr" && traduire(s)) || s; },
  };
})();
