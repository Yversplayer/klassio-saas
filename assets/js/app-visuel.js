// KLASSIO — couche visuelle de l'application (07/10/2026).
//
// Le propriétaire : « on a tout misé sur le site, la landing et la démo ; on a
// délaissé l'aspect visuel du logiciel ». En thème sombre, un écran sans
// données — une école qui commence, un onglet vide — n'était qu'un grand
// rectangle noir avec trois lignes grises.
//
// Ce fichier ajoute, sans toucher ni aux données ni aux états :
//   1. un BANDEAU PHOTO en tête de chaque écran (photos d'illustration déjà
//      publiées sur la landing : adultes de face, élèves de dos ou au loin,
//      aucun drapeau, aucun texte lisible) ;
//   2. une PILE DE PHOTOS en 3D dans les états vides ;
//   3. un PIED DE PAGE sur chaque écran : contact et pages légales. L'adresse
//      vivait dans la barre latérale, qui se replie par défaut — elle n'était
//      donc visible sur aucun écran, contrairement à ce qu'on croyait ;
//   4. le masquage des NOTES JAUNES d'explication pour une Direction dont
//      l'établissement n'a encore ni élève ni classe (demande du 07/10) : elles
//      commentaient des vues qui ne contenaient rien.
//
// Ce qu'il ne fait JAMAIS : simuler un chargement, un succès ou une donnée. Une
// photo est un décor. Elle n'annonce rien, et rien de ce qu'elle reçoit ne
// décide d'un accès — le rôle sert seulement à choisir une image.
//
// Trois replis, parce que Kinshasa n'est pas un MacBook :
//   - économie de données ou réseau 2G : aucune photo n'est téléchargée, le
//     bandeau garde son dégradé vert forêt ;
//   - mouvement réduit : rien ne bouge, tout est en place ;
//   - Élèves & classes, Mes classes et l'écran d'une classe : AUCUNE animation
//     ajoutée, à la demande du propriétaire — photos fixes seulement.
(function () {
  "use strict";
  var api = window.KlassioApi;
  var root = document.documentElement;
  var page = document.body.dataset.page || "";
  var CINE = "../assets/cine/";

  var mqReduit = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  var mqFin = window.matchMedia ? window.matchMedia("(hover: hover) and (pointer: fine)") : null;
  var cnx = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
  var sansPhoto = !!(cnx && (cnx.saveData || /(^|-)2g$/.test(cnx.effectiveType || "")));
  var CALMES = { eleves: 1, classes: 1, classe: 1 };
  var anime = !CALMES[page] && !(mqReduit && mqReduit.matches);

  root.classList.add("ka-app");
  if (sansPhoto) root.classList.add("ka-sans-photo");
  if (anime) root.classList.add("ka-anim");

  // ------------------------------------------------------------------
  // Photos : une par écran, avec son point focal. Le bandeau ne montre
  // qu'une tranche de l'image ; sans point focal, on garderait le ciel et
  // on couperait les visages.
  // ------------------------------------------------------------------
  var FOCUS = {
    "campus": "50% 62%", "campus1": "50% 70%", "campus2": "50% 72%", "d0730": "50% 60%",
    "d1000": "50% 55%", "d1300": "50% 68%", "d1630": "50% 62%", "dusk": "50% 66%",
    "gal-proclamation": "50% 52%", "gal-recre": "50% 56%", "gal-tampon": "55% 50%",
    "mod-direction": "50% 24%", "mod-discipline": "50% 38%", "mod-eleves": "50% 24%",
    "mod-frais": "50% 40%", "mod-presences": "50% 12%", "mod-resultats": "50% 55%",
    "portail": "50% 55%", "pub": "50% 55%"
  };
  // Bandeaux : des photos en PAYSAGE seulement. Un portrait (le parent, les
  // mains levées, les cartables) agrandi à la largeur d'un bandeau ne
  // laissait voir qu'un morceau de visage. Les portraits servent aux piles des
  // états vides, où le cadre est presque carré.
  // La Boutique a son propre bandeau de vitrine (page-boutique.js) : pas de second.
  var ECRAN = {
    eleves: "campus1", classes: "mod-presences", discipline: "gal-recre", pointage: "portail",
    registres: "d1300", resultats: "gal-proclamation", deliberations: "mod-resultats",
    passage: "campus", finance: "mod-frais", paiements: "gal-tampon",
    calendrier: "d0730", messages: "d1630", notifications: "d1000", documents: "mod-eleves",
    ressources: "pub", rapports: "campus2", exports: "d1300", etablissement: "dusk",
    parametres: "portail", abonnement: "mod-direction"
  };
  // L'accueil dépend du rôle : on attend /me plutôt que de deviner sur
  // `klassio_role`, cache d'affichage qu'un second compte du même navigateur
  // écrase (voir ui.js, homeFor). Deviner, c'était télécharger parfois deux
  // photos pour en montrer une.
  var SELON_ROLE = { dashboard: 1 };
  // Pas de photo à l'accueil de la Direction (demande du propriétaire, 08/10) :
  // un inconnu en costume « représentait » le directeur de chaque école.
  var ACCUEIL = { directeur: null, discipline: "mod-discipline", parent: "campus2", professeur: "mod-presences" };

  function photoDe(role) {
    if (page === "dashboard") return role in ACCUEIL ? ACCUEIL[role] : "campus1";
    return ECRAN[page] || null;
  }

  // ------------------------------------------------------------------
  // 1. Bandeau photo
  // ------------------------------------------------------------------
  var tete = document.querySelector(".dash-body > .page-header");
  var fond = null, accroche = null;

  function preparerBandeau() {
    // L'Assistant occupe toute la hauteur de l'écran (.ia-page) : un bandeau
    // y pousserait la zone de réponse sous la ligne de flottaison.
    if (!tete || document.querySelector(".ia-page")) { tete = null; return; }
    if (!ECRAN[page] && !SELON_ROLE[page]) { tete = null; return; }
    tete.classList.add("ka-hero");
    fond = document.createElement("div");
    fond.className = "ka-hero-fond";
    fond.setAttribute("aria-hidden", "true");
    tete.insertBefore(fond, tete.firstChild);

    // Le nom de l'établissement, en sur-titre doré — la barre latérale qui le
    // portait est repliée par défaut.
    var titre = tete.querySelector("h1");
    if (titre && titre.parentNode) {
      titre.parentNode.classList.add("ka-hero-texte");
      accroche = document.createElement("span");
      accroche.className = "ka-hero-accroche";
      accroche.setAttribute("aria-hidden", "true");
      titre.parentNode.insertBefore(accroche, titre);
    }

    // La mention « Photo d'illustration » a été retirée à la demande du
    // propriétaire (08/10/2026).

    if (!SELON_ROLE[page]) poserPhoto(ECRAN[page]);
  }

  function poserPhoto(cle) {
    if (!fond || !cle || fond.dataset.cle === cle) return;
    fond.dataset.cle = cle;
    if (sansPhoto) return;
    // Les clés viennent de la table ci-dessus, jamais d'une donnée.
    var image = document.createElement("img");
    image.className = "ka-hero-img";
    image.alt = "";
    image.decoding = "async";
    image.style.objectPosition = FOCUS[cle] || "50% 50%";
    var cadre = document.createElement("picture");
    // La version 1600 px n'est servie qu'aux grands écrans haute densité : un
    // téléphone de 375 px à densité 3 la réclamerait sinon, sur une connexion
    // mobile, pour un bandeau de 160 px de haut.
    var grande = document.createElement("source");
    grande.media = "(min-width: 1100px) and (min-resolution: 1.5dppx)";
    grande.srcset = CINE + cle + "-1600.webp";
    cadre.appendChild(grande);
    cadre.appendChild(image);
    var marquer = function () { image.classList.add("is-loaded"); };
    image.addEventListener("load", marquer);
    image.src = CINE + cle + "-960.webp";
    if (image.complete && image.naturalWidth) marquer();
    fond.textContent = "";
    fond.appendChild(cadre);
  }

  // Profondeur : la photo glisse et pivote légèrement sous le pointeur, le
  // texte et les boutons restent immobiles — on ne fait jamais bouger ce
  // qu'on doit pouvoir cliquer. Le défilement ajoute une parallaxe douce.
  function animerBandeau() {
    if (!tete || !anime) return;
    var etat = { rx: 0, ry: 0, px: 0, py: 0, sy: 0 }, raf = 0;
    function poser() {
      raf = 0;
      fond.style.setProperty("--ka-rx", etat.rx.toFixed(2) + "deg");
      fond.style.setProperty("--ka-ry", etat.ry.toFixed(2) + "deg");
      fond.style.setProperty("--ka-px", etat.px.toFixed(1) + "px");
      fond.style.setProperty("--ka-py", (etat.py + etat.sy).toFixed(1) + "px");
    }
    function planifier() { if (!raf) raf = requestAnimationFrame(poser); }
    if (mqFin && mqFin.matches) {
      tete.addEventListener("pointermove", function (e) {
        var r = tete.getBoundingClientRect();
        var x = (e.clientX - r.left) / r.width - 0.5, y = (e.clientY - r.top) / r.height - 0.5;
        etat.ry = x * 5; etat.rx = -y * 4; etat.px = -x * 18; etat.py = -y * 10;
        planifier();
      });
      tete.addEventListener("pointerleave", function () {
        etat.rx = etat.ry = etat.px = etat.py = 0;
        planifier();
      });
    }
    window.addEventListener("scroll", function () {
      var r = tete.getBoundingClientRect();
      if (r.bottom < 0) return;
      etat.sy = Math.min(26, Math.max(0, -r.top * 0.2));
      planifier();
    }, { passive: true });
  }

  // ------------------------------------------------------------------
  // 2. Cartes indicateurs : légère inclinaison 3D et reflet sous le pointeur
  // ------------------------------------------------------------------
  function inclinerCartes() {
    if (!anime || !(mqFin && mqFin.matches)) return;
    var carte = null, dernier = null, raf = 0;
    function relacher(c) {
      c.classList.remove("ka-incline");
      ["--ka-rx", "--ka-ry", "--ka-mx", "--ka-my"].forEach(function (p) { c.style.removeProperty(p); });
    }
    function appliquer() {
      raf = 0;
      var e = dernier;
      var cible = e.target && e.target.closest ? e.target.closest(".dash-body .kpi-card, .dash-body .kt-3d") : null;
      if (carte && carte !== cible) relacher(carte);
      carte = cible;
      if (!carte) return;
      var r = carte.getBoundingClientRect();
      var x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
      carte.classList.add("ka-incline");
      carte.style.setProperty("--ka-ry", ((x - 0.5) * 10).toFixed(2) + "deg");
      carte.style.setProperty("--ka-rx", ((0.5 - y) * 8).toFixed(2) + "deg");
      carte.style.setProperty("--ka-mx", (x * 100).toFixed(1) + "%");
      carte.style.setProperty("--ka-my", (y * 100).toFixed(1) + "%");
    }
    document.addEventListener("pointermove", function (e) {
      dernier = e;
      if (!raf) raf = requestAnimationFrame(appliquer);
    }, { passive: true });
    // Le pointeur quitte la fenêtre : aucun `pointermove` ne viendra redresser
    // la carte, on la relâche ici.
    document.addEventListener("mouseout", function (e) {
      if (!e.relatedTarget && carte) { relacher(carte); carte = null; }
    });
  }

  // ------------------------------------------------------------------
  // 3. États vides : une pile de deux photos en 3D, l'icône en pastille
  // ------------------------------------------------------------------
  // Par icône d'état vide (UI.emptyState) : la photo de devant, celle de
  // derrière. Pas de photo pour « lock » (accès refusé) ni « search » (une
  // recherche sans résultat) : ce ne sont pas des écrans vides, ce sont des
  // réponses, et une image les rendrait moins lisibles.
  var PILES = {
    students: ["campus1", "gal-sacs"], classes: ["d1000", "gal-mains"],
    discipline: ["gal-recre", "mod-discipline"], 
    book: ["gal-craie", "pub"], store: ["gal-sacs", "mod-frais"],
    reports: ["gal-proclamation", "mod-resultats"], payments: ["mod-frais", "gal-tampon"],
    finance: ["mod-frais", "gal-tampon"], mail: ["gal-parent", "d1630"],
    inbox: ["d1300", "gal-tampon"], bell: ["d1630", "portail"],
    users: ["mod-direction", "gal-proclamation"], file: ["d1300", "mod-eleves"],
    clock: ["portail", "mod-discipline"], clipboard: ["mod-presences", "gal-mains"],
    check: ["gal-mains", "campus2"]
  };

  function carteDe(cle, classe) {
    var c = document.createElement("span");
    c.className = "ka-carte " + classe;
    var image = document.createElement("img");
    image.alt = "";
    image.loading = "lazy";
    image.decoding = "async";
    image.src = CINE + cle + "-480.webp";
    c.appendChild(image);
    return c;
  }

  function habiller(vide) {
    if (vide.classList.contains("ka-vide")) return;
    vide.classList.add("ka-vide");
    if (sansPhoto) return;
    var icone = null;
    for (var i = 0; i < vide.children.length; i++) {
      if (vide.children[i].classList && vide.children[i].classList.contains("ic")) { icone = vide.children[i]; break; }
    }
    if (!icone) return;
    var nom = null;
    icone.classList.forEach(function (c) { if (c.indexOf("ic-") === 0) nom = c.slice(3); });
    if (nom === "calendar") { poserCalendrier(vide, icone); return; }
    var duo = PILES[nom];
    if (!duo) return;
    var pile = document.createElement("div");
    pile.className = "ka-pile";
    pile.setAttribute("aria-hidden", "true");
    pile.appendChild(carteDe(duo[1], "ka-carte-arriere"));
    pile.appendChild(carteDe(duo[0], "ka-carte-avant"));
    vide.insertBefore(pile, icone);
    pile.appendChild(icone);
    vide.classList.add("ka-vide-photo");
  }

  // États vides « calendrier » (aucune période déclarée, rien de planifié) :
  // pas de photos — le propriétaire les trouvait mal venues à cet endroit —
  // mais un calendrier dessiné, ses journées cochées. Un décor : aucune date,
  // aucun chiffre de l'école n'y figure.
  var JOURS_COCHES = { 3: "ok", 8: "ok", 11: "ok", 15: "etoile", 18: "ok", 22: "ok", 25: "ok", 29: "etoile" };
  function poserCalendrier(vide, icone) {
    var cal = document.createElement("div");
    cal.className = "ka-cal";
    cal.setAttribute("aria-hidden", "true");
    var cases = "";
    for (var i = 0; i < 2; i++) cases += '<span class="ka-cal-j ka-cal-vide"></span>';
    for (var j = 1; j <= 30; j++) {
      var etat = JOURS_COCHES[j];
      cases += '<span class="ka-cal-j' + (etat ? " ka-cal-" + etat : "") + '">' + j + "</span>";
    }
    cal.innerHTML = '<div class="ka-cal-feuille"><div class="ka-cal-tete"><i></i><i></i></div>' +
      '<div class="ka-cal-sem"><span>L</span><span>M</span><span>M</span><span>J</span><span>V</span><span>S</span><span>D</span></div>' +
      '<div class="ka-cal-grille">' + cases + "</div></div>";
    vide.insertBefore(cal, icone);
    cal.appendChild(icone);
    vide.classList.add("ka-vide-photo");
  }

  function parcourir(noeud) {
    if (!noeud || noeud.nodeType !== 1) return;
    if (noeud.classList.contains("empty-state")) habiller(noeud);
    var vides = noeud.querySelectorAll(".empty-state");
    for (var i = 0; i < vides.length; i++) habiller(vides[i]);
  }

  function observerVides() {
    var corps = document.querySelector(".dash-body");
    if (!corps || !window.MutationObserver) return;
    parcourir(corps);
    new MutationObserver(function (mutations) {
      for (var i = 0; i < mutations.length; i++) {
        var ajouts = mutations[i].addedNodes;
        for (var j = 0; j < ajouts.length; j++) parcourir(ajouts[j]);
      }
    }).observe(corps, { childList: true, subtree: true });
  }

  // ------------------------------------------------------------------
  // 4. Pied de page
  // ------------------------------------------------------------------
  function poserPied() {
    var colonne = document.querySelector(".main-col");
    if (!colonne || colonne.querySelector(".ka-foot")) return;
    var pied = document.createElement("footer");
    pied.className = "ka-foot";
    // Contenu fixe, écrit ici : aucune donnée de la base n'y entre.
    pied.innerHTML =
      '<p class="ka-foot-contact">Une question ? <a href="mailto:mudeyimusimwa@gmail.com">mudeyimusimwa@gmail.com</a>' +
        ' · <a href="https://wa.me/243971839237" target="_blank" rel="noopener">WhatsApp</a></p>' +
      '<nav class="ka-foot-liens" aria-label="Aide et informations légales">' +
        '<a href="../aide.html">Centre d\'aide</a><a href="../cgu.html">Conditions d\'utilisation</a>' +
        '<a href="../confidentialite.html">Confidentialité</a><a href="../mentions.html">Mentions légales</a>' +
        '<a href="../securite.html">Sécurité</a></nav>' +
      '<p class="ka-foot-sig"><img src="../assets/logo.png" alt="" width="16" height="16">Klassio · ' +
        new Date().getFullYear() + ' · Conçu à Kinshasa</p>';
    colonne.appendChild(pied);
  }

  // ------------------------------------------------------------------
  // 5. École encore vide : les notes jaunes d'explication se retirent
  // ------------------------------------------------------------------
  // « Cette vue rassemble ce qui a été enregistré… » au pied d'une vue qui ne
  // contient rien : la note explique un écran que la Direction ne peut pas
  // encore lire. Seule la Direction est concernée (demande du propriétaire).
  //
  // Restent affichées les notes marquées `note-garde` : celles qui portent un
  // AVERTISSEMENT (l'abonnement demande votre attention ; supprimer le seul
  // compte Direction rendrait l'espace inadministrable). Une école vide en a
  // autant besoin qu'une autre.
  //
  // La réponse vient du serveur (GET /classes, déjà autorisé à la Direction) ;
  // elle ne décide que de l'affichage d'une aide. Une école qui a des élèves ne
  // redevient pas vide dans la session : on ne repose plus la question.
  function ecoleVide(ctx) {
    if (ctx.role !== "directeur" || !api) { root.classList.remove("ka-ecole-vide"); return; }
    var cle = "klassio_ecole_vide:" + (ctx.tenant_id || "");
    var connu = null;
    try { connu = sessionStorage.getItem(cle); } catch (e) {}
    if (connu === "0") return;
    if (connu === "1") root.classList.add("ka-ecole-vide");
    api.fetch("/classes").then(function (r) {
      if (!r || !r.ok || !Array.isArray(r.body)) return;
      var eleves = r.body.reduce(function (s, c) { return s + (c.student_count || 0); }, 0);
      var vide = !r.body.length || !eleves;
      root.classList.toggle("ka-ecole-vide", vide);
      try { sessionStorage.setItem(cle, vide ? "1" : "0"); } catch (e) {}
    }).catch(function () {});
  }

  // ------------------------------------------------------------------
  // Appelé par la coquille (admin.js) une fois /me reçu.
  // ------------------------------------------------------------------
  function contexte(ctx) {
    if (!ctx) return;
    // L'accueil nomme déjà l'établissement sous le titre : pas de doublon.
    if (accroche && ctx.tenant_name && page !== "dashboard") accroche.textContent = ctx.tenant_name;
    if (SELON_ROLE[page]) {
      var cle = photoDe(ctx.role);
      if (cle) poserPhoto(cle);
    }
    ecoleVide(ctx);
  }

  preparerBandeau();
  animerBandeau();
  inclinerCartes();
  observerVides();
  poserPied();

  window.KlassioDecor = { contexte: contexte };
})();
