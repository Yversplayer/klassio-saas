// KLASSIO — coquille applicative commune : sidebar par rôle (icônes SVG),
// fil d'Ariane de la topbar, cloche de notifications RÉELLE (compteur non lu +
// aperçu, rafraîchi toutes les 30 s), menu compte, comportement mobile.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi;

  function initShell(activePage) {
    var token = api.getToken();
    // Sans session : redirection, et une promesse qui ne se résout jamais (la page
    // est en train de partir) — plutôt qu'un rejet non capturé dans la console.
    if (!token) { window.location.href = "connexion.html"; return new Promise(function () {}); }

    var sidebar = document.getElementById("sidebar");
    var toggle = document.getElementById("sidebarToggle");
    var scrim = document.getElementById("sidebarScrim");
    var collapsedKey = "klassio_sidebar_collapsed";
    var isMobile = function () { return window.matchMedia("(max-width: 860px)").matches; };
    try { if (localStorage.getItem(collapsedKey) === "1" && !isMobile()) sidebar.classList.add("collapsed"); } catch (e) {}
    if (isMobile()) sidebar.classList.add("collapsed");
    toggle.innerHTML = UI.icon("menu", 18);
    function setCollapsed(v) {
      sidebar.classList.toggle("collapsed", v);
      if (scrim) scrim.hidden = v || !isMobile();
      try { if (!isMobile()) localStorage.setItem(collapsedKey, v ? "1" : "0"); } catch (e) {}
    }
    toggle.addEventListener("click", function () { setCollapsed(!sidebar.classList.contains("collapsed")); });
    if (scrim) scrim.addEventListener("click", function () { setCollapsed(true); });

    var current = activePage || document.body.dataset.page;

    return api.fetch("/me").then(function (res) {
      if (!res.ok) { window.location.href = "connexion.html?expired=1"; return new Promise(function () {}); }
      var ctx = res.body;
      UI.setCurrency(ctx.currency);
      try { localStorage.setItem("klassio_role", ctx.role); localStorage.setItem("klassio_name", ctx.user_name || ""); if (ctx.tenant_name) localStorage.setItem("klassio_etablissement", ctx.tenant_name); } catch (e) {}

      var menus = (api.roleMenus[ctx.role] || api.roleMenus.parent).slice();
      if (ctx.is_platform_admin) menus.push(api.platformMenu);

      // Une page absorbée par une entrée fusionnée doit ALLUMER cette entrée.
      // Sans cette table, être sur Classes ou Paiements n'éclairait plus rien
      // dans le menu : l'utilisateur perdait son repère.
      //
      // Deux règles, chacune payée par un défaut :
      //
      // 1. La porte ne s'ouvre que pour une page SANS entrée à elle. La table
      //    décrit les fusions du menu Direction ; appliquée à tous les rôles,
      //    elle allumait DEUX entrées à la fois. Un professeur sur
      //    `classes.html` voyait « Mes classes » et « Mes élèves » actives —
      //    deux `aria-current="page"` dans la même navigation, et plus de
      //    repère du tout, exactement ce que la table devait éviter.
      // 2. Une page peut donner sur plusieurs portes selon le rôle : ouvrir une
      //    classe ramène le professeur à « Mes classes », la Direction à
      //    « Élèves & classes ». D'où une LISTE par page, dans laquelle on
      //    retient la première porte qui existe réellement dans ce menu-ci.
      var PORTE = {
        classes: ["eleves"],
        classe: ["classes", "eleves"],
        "eleve-dossier": ["eleves"],
        paiements: ["finance"],
        documents: ["etablissement"],
        registres: ["discipline"],
        // Exporter ses données, c'est les faire sortir — la même famille que
        // les rapports. Une douzième entrée de menu pour une page qu'on
        // ouvre trois fois par an encombrerait la navigation quotidienne.
        exports: ["rapports"],
        // La délibération examine les résultats de l'année : elle appartient
        // au domaine Résultats, pas à une entrée de menu à elle.
        deliberations: ["resultats"],
        // Le passage d'année place des élèves dans des classes : c'est le
        // domaine Élèves & classes. On y arrive par la délibération, d'où le
        // repli sur Résultats pour un menu qui n'aurait pas la première.
        passage: ["eleves", "resultats"],
      };
      var pagesDuMenu = menus.map(function (item) { return item[2].replace(".html", ""); });
      var porte = null;
      if (pagesDuMenu.indexOf(current) < 0) {
        (PORTE[current] || []).some(function (candidate) {
          if (pagesDuMenu.indexOf(candidate) >= 0) { porte = candidate; return true; }
          return false;
        });
      }

      document.getElementById("sidebarNav").innerHTML = menus.map(function (item) {
        var page = item[2].replace(".html", "");
        var active = page === current || page === porte;
        return '<a href="' + item[2] + '" class="s-item' + (active ? " active" : "") + '"' + (active ? ' aria-current="page"' : "") + '><span class="s-ic">' + UI.icon(item[0], 17) + "</span><span>" + item[1] + "</span></a>";
      }).join("");
      renderAccountBlock(ctx);

      // CONTEXTE, pas identité. La topbar affichait « Klassio » et le nom de
      // l'établissement — exactement ce que porte déjà la barre latérale, à
      // vingt centimètres de là. Deux zones de navigation qui répètent la même
      // chose ne créent pas de repère, elles en suppriment un : l'utilisateur
      // ne sait plus laquelle regarder.
      //
      // L'identité reste donc dans la barre latérale, une seule fois, et la
      // topbar dit OÙ L'ON EST. La section vient du menu du rôle : un
      // professeur n'y lira jamais « Direction », parce que l'entrée provient
      // de son propre menu, construit sur /me.
      var entree = menus.filter(function (item) {
        var page = item[2].replace(".html", "");
        return page === current || page === porte;
      })[0];
      contexteSection = entree ? entree[1] : "";
      renderContexte();
      // Le portail porte le nom de l'école : logo et nom dans la barre latérale, Klassio en « propulsé par ».
      var b = ctx.branding || {};
      var brand = document.querySelector(".sidebar .s-brand");
      if (brand && ctx.tenant_name) {
        // Le seul lien de l'application vers la vitrine publique vivait dans la
        // marque de la topbar, qu'on vient de retirer. Il se reporte ici : ôter
        // une identité en double ne doit pas faire disparaître un chemin au
        // passage. La marque devient donc un lien — un `href` posé sur un
        // `<div>` n'aurait rien fait, et le clic serait tombé dans le vide.
        var lien = document.createElement("a");
        lien.className = brand.className;
        lien.href = "../index.html";
        lien.title = "Ouvrir le site public Klassio";
        lien.innerHTML = (b.logo_data ? '<img src="' + UI.escapeHtml(b.logo_data) + '" class="school-logo" alt="">' : '<img src="../assets/logo.png" class="brand-mark" alt="">') +
          '<div class="s-school"><span>' + (b.logo_data ? "Propulsé par Klassio" : "Klassio") + "</span><strong>" + UI.escapeHtml(ctx.tenant_name) + "</strong></div>";
        brand.replaceWith(lien);
      }
      if (b.accent_color) document.documentElement.style.setProperty("--accent", b.accent_color);
      try { if (b.slug) localStorage.setItem("klassio_portal", b.slug); } catch (e) {}
      document.title = document.title.replace(/— Klassio.*$/, "— " + (ctx.tenant_name || "Klassio"));

      wireNotifications(ctx);
      wireSubscriptionBanner(ctx, current);
      cloturerAccueil(ctx);
      if (isMobile()) document.getElementById("sidebarNav").addEventListener("click", function () { setCollapsed(true); });
      return ctx;
    });
  }

  // Fil d'Ariane : la section du menu, plus le détail que la page fournit.
  //
  // Le détail est fourni PAR LA PAGE parce qu'elle seule le connaît — le nom
  // d'une classe ou d'un élève arrive avec la réponse du serveur, pas avec
  // l'URL. La coquille n'invente donc rien : sans appel à `setContext`, le fil
  // s'arrête à la section.
  var contexteSection = "", contexteDetail = "";

  function renderContexte() {
    var hote = document.getElementById("topbarContext");
    if (!hote) return;
    var morceaux = [];
    if (contexteSection) morceaux.push('<span class="tc-section">' + UI.escapeHtml(contexteSection) + "</span>");
    if (contexteDetail) morceaux.push('<span class="tc-sep" aria-hidden="true">' + UI.icon("chevronRight", 13) + '</span><span class="tc-detail">' + UI.escapeHtml(contexteDetail) + "</span>");
    hote.innerHTML = morceaux.join("");
  }

  // Appelée par une page qui a chargé son objet : `admin.setContext("6e A")`.
  function setContext(detail) {
    contexteDetail = detail || "";
    renderContexte();
  }

  // Fin de la Welcome Experience. L'utilisateur arrive depuis l'activation de
  // son invitation (`?bienvenue=1`) : on clôt l'accueil CÔTÉ SERVEUR, pour
  // qu'il ne se rejoue pas sur un autre appareil ni après un vidage du cache —
  // le stockage local ne saurait pas le retenir.
  //
  // Ceci vit dans la coquille, et non dans une page : chaque rôle arrive chez
  // lui (UI.homeFor), et le professeur n'atterrit plus sur le tableau de bord.
  // Attaché à une seule page, l'accueil ne se serait plus clôturé pour lui — il
  // aurait rejoué son invitation à chaque connexion. Partout ailleurs, sans le
  // paramètre, la fonction ne fait rien.
  function cloturerAccueil(ctx) {
    var params = new URLSearchParams(window.location.search);
    if (params.get("bienvenue") !== "1") return;
    // L'adresse est nettoyée d'abord : un rafraîchissement ne doit pas rejouer
    // l'arrivée, et l'appel ci-dessous est de toute façon idempotent.
    window.history.replaceState({}, "", window.location.pathname);
    api.fetch("/me/onboarding", { method: "POST", body: JSON.stringify({}) }).then(function (r) {
      if (r && r.ok) annoncerArrivee(ctx);
    });
  }

  function annoncerArrivee(ctx) {
    // Le sous-titre s'appelle `dashSub` sur le tableau de bord et `pageSub`
    // partout ailleurs : on prend celui qui existe sur la page d'arrivée.
    var sub = document.getElementById("dashSub") || document.getElementById("pageSub");
    if (!sub) return;
    var bandeau = document.createElement("p");
    bandeau.className = "wx-arrivee";
    bandeau.setAttribute("role", "status");
    bandeau.textContent = ctx.role === "parent"
      ? "Votre espace familial est prêt. Vous y retrouverez les résultats, les présences et les paiements de vos enfants."
      : ctx.role === "professeur"
        ? "Votre espace enseignant est prêt. Voici vos classes."
        : "Votre espace est prêt.";
    sub.insertAdjacentElement("afterend", bandeau);
  }

  // Abonnement : le directeur atterrit sur l'écran Abonnement quand celui-ci
  // le demande (fin d'essai proche, retard, suspension) — une fois par session,
  // sinon un bandeau discret. Les autres rôles voient seulement « lecture seule ».
  function wireSubscriptionBanner(ctx, current) {
    var sub = ctx.subscription || {};
    var host = document.querySelector(".main-col");
    if (!host) return;
    // La redirection automatique vers l'écran d'abonnement a été retirée :
    // détourner un directeur qui vient faire l'appel du matin pour lui parler
    // de facturation, c'est interrompre l'école pour un sujet commercial.
    // L'information vit dans Paramètres → Abonnement, où on la cherche.
    //
    // UNE SEULE exception demeure, et elle n'est pas commerciale : quand
    // l'espace passe en LECTURE SEULE, il faut dire pourquoi. Sans ce bandeau,
    // l'utilisateur verrait ses enregistrements échouer sans explication.
    var text = null, cls = "warn";
    if (sub.read_only) { text = ctx.role === "directeur" ? "Espace en lecture seule — facture d'abonnement en attente. Vos données sont intactes." : "L'espace de l'établissement est temporairement en lecture seule (abonnement). Consultation possible, enregistrement suspendu."; cls = "bad"; }
    if (!text) return;
    var bar = document.createElement("div");
    bar.className = "sub-banner " + cls;
    bar.innerHTML = UI.icon("alert", 15) + "<span>" + UI.escapeHtml(text) + "</span>" + (ctx.role === "directeur" ? '<a href="parametres.html?tab=abonnement" class="link-btn">Voir l\'abonnement</a>' : "");
    host.insertBefore(bar, host.querySelector(".dash-body"));
  }

  // Le compte vit dans la BARRE LATÉRALE, plus dans le coin de la topbar.
  //
  // Avant : une pastille d'initiale en haut à droite ouvrait un menu à deux
  // entrées, tandis que « Abonnement » et « Paramètres » occupaient deux lignes
  // du menu principal — au même rang que Élèves ou Finance, alors que ce sont
  // des réglages, pas du travail quotidien. La topbar ne garde donc que les
  // notifications, et tout ce qui touche à la personne connectée est réuni ici.
  //
  // On n'y met aucune entrée qui ne mène nulle part : pas de lien « Aide »
  // tant que l'écran d'aide n'existe pas.
  function renderAccountBlock(ctx) {
    var hote = document.getElementById("roleTag");
    if (!hote) return;
    var nom = ctx.user_name || "Utilisateur";
    var role = api.roleLabels[ctx.role] || ctx.role;
    var ecole = ctx.tenant_name || "";

    hote.className = "s-account";
    hote.innerHTML =
      '<button type="button" class="s-account-btn" id="accountBtn" aria-expanded="false" aria-haspopup="true">' +
        '<span class="s-av">' + UI.escapeHtml(nom.charAt(0).toUpperCase()) + "</span>" +
        '<span class="s-acc-id"><strong>' + UI.escapeHtml(nom) + "</strong>" +
          "<span>" + UI.escapeHtml(role) + (ecole ? " · " + UI.escapeHtml(ecole) : "") + "</span></span>" +
        '<span class="s-acc-chev" aria-hidden="true">' + UI.icon("chevron-up", 14) + "</span>" +
      "</button>" +
      '<div class="s-account-menu" id="accountMenu" hidden role="menu">' +
        '<a href="parametres.html" class="s-acc-item" role="menuitem">' + UI.icon("settings", 15) + "Paramètres</a>" +
        (ctx.role === "directeur"
          ? '<a href="abonnement.html" class="s-acc-item" role="menuitem">' + UI.icon("receipt", 15) + "Abonnement</a>"
          : "") +
        '<button type="button" class="s-acc-item" id="logoutBtn" role="menuitem">' + UI.icon("logout", 15) + "Se déconnecter</button>" +
      "</div>";

    var btn = document.getElementById("accountBtn");
    var menu = document.getElementById("accountMenu");
    function ouvrir(v) {
      menu.hidden = !v;
      btn.setAttribute("aria-expanded", v ? "true" : "false");
      hote.classList.toggle("open", v);
    }
    btn.addEventListener("click", function () { ouvrir(menu.hidden); });
    document.addEventListener("click", function (e) {
      if (!menu.hidden && !hote.contains(e.target)) ouvrir(false);
    });
    // Un menu qui ne se referme pas à Échap piège l'utilisateur au clavier.
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !menu.hidden) { ouvrir(false); btn.focus(); }
    });

    document.getElementById("logoutBtn").addEventListener("click", function () {
      api.fetch("/auth/logout", { method: "POST" }).finally(function () {
        try { ["klassio_token", "klassio_role", "klassio_name", "klassio_tenant_id"].forEach(function (k) { localStorage.removeItem(k); }); } catch (e) {}
        window.location.href = "connexion.html";
      });
    });
  }

  function wireNotifications(ctx) {
    var bell = document.getElementById("bellBtn");
    if (!bell) return;
    bell.innerHTML = UI.icon("bell", 17) + '<span class="bell-count" id="bellCount" hidden></span>';
    var pop = document.createElement("div");
    pop.className = "popover notif-pop"; pop.hidden = true;
    pop.innerHTML = '<div class="pop-head"><strong>Notifications</strong><button type="button" class="link-btn" id="readAllBtn">Tout marquer lu</button></div><div class="notif-list" id="notifList">' + UI.skeleton("row", 3) + "</div>" +
      '<a href="notifications.html" class="pop-foot">Voir toutes les notifications ' + UI.icon("chevronRight", 14) + "</a>";
    bell.parentNode.appendChild(pop);

    function render(summary) {
      var count = document.getElementById("bellCount");
      count.textContent = summary.unread_count > 99 ? "99+" : summary.unread_count;
      count.hidden = !summary.unread_count;
      bell.setAttribute("aria-label", summary.unread_count ? summary.unread_count + " notifications non lues" : "Notifications");
      var list = document.getElementById("notifList");
      if (!summary.latest.length) { list.innerHTML = UI.emptyState("Aucune notification", "Vous serez informé(e) ici des événements qui vous concernent.", "", "bell"); return; }
      list.innerHTML = summary.latest.map(function (n) {
        return '<a class="notif-item' + (n.status === "unread" ? " unread" : "") + '" href="' + UI.escapeHtml(n.link || "notifications.html") + '" data-id="' + n.id + '">' +
          '<span class="notif-dot"></span><span class="notif-body"><strong>' + UI.escapeHtml(n.title) + "</strong><span>" + UI.escapeHtml(n.body) + "</span><em>" + UI.relTime(n.updated_at || n.created_at) + (n.count > 1 ? " · ×" + n.count : "") + "</em></span></a>";
      }).join("");
      list.querySelectorAll(".notif-item").forEach(function (el) {
        el.addEventListener("click", function () { api.fetch("/notifications/" + el.dataset.id + "/read", { method: "POST" }); });
      });
    }
    function refresh() { return api.fetch("/notifications/summary").then(function (res) { if (res.ok) render(res.body); }); }
    refresh();
    setInterval(function () { if (!document.hidden) refresh(); }, 30000);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });

    bell.addEventListener("click", function () { pop.hidden = !pop.hidden; if (!pop.hidden) refresh(); });
    document.addEventListener("click", function (e) { if (!pop.hidden && !pop.contains(e.target) && !bell.contains(e.target)) pop.hidden = true; });
    pop.querySelector("#readAllBtn").addEventListener("click", function () { api.fetch("/notifications/read-all", { method: "POST" }).then(refresh); });
    window.KlassioAdmin.refreshNotifications = refresh;
  }

  // Erreur réseau/serveur uniforme pour les chargements de page
  function loadError(container, retryFn, title) {
    var id = "retry-" + Math.random().toString(36).slice(2, 8);
    container.innerHTML = UI.errorState(title, null, id);
    var b = document.getElementById(id);
    if (b) b.addEventListener("click", retryFn);
  }

  window.KlassioAdmin = { initShell: initShell, escapeHtml: UI.escapeHtml, money: UI.money, loadError: loadError, setContext: setContext };
})();
