// KLASSIO — Design System runtime : composants réutilisables partagés par
// toutes les pages de l'application (aucune duplication page par page).
//
// Contenu : icônes SVG (jamais d'emoji comme élément d'interface), états de
// boutons (default → loading → success/error), skeletons, états vides,
// états d'erreur avec "Réessayer", toasts, modales (Escape / clic extérieur),
// onglets, formatage monétaire par devise, badges de statut, avatars à
// initiales (jamais une photo inventée), petits graphiques en barres.
(function () {
  "use strict";

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // ---------------- Icônes (traits 1.75, 24×24, currentColor) ----------------
  var PATHS = {
    home: '<path d="M3 11.5 12 4l9 7.5"/><path d="M5 10v10h5v-6h4v6h5V10"/>',
    building: '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M9 7h2M13 7h2M9 11h2M13 11h2M9 15h2M13 15h2M10 21v-3h4v3"/>',
    students: '<path d="M2 9l10-5 10 5-10 5z"/><path d="M6 11.5V16c0 1.5 2.7 3 6 3s6-1.5 6-3v-4.5"/><path d="M22 9v6"/>',
    classes: '<path d="M4 6h16v12H4z"/><path d="M4 10h16"/><path d="M9 18v2M15 18v2"/>',
    finance: '<rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10h18"/><circle cx="16.5" cy="14.5" r="1.5"/>',
    payments: '<path d="M4 7h16v10H4z"/><path d="M8 12h.01M12 12h4"/><path d="M4 11h16"/>',
    discipline: '<path d="M12 3l8 3v6c0 4.5-3.3 8-8 9-4.7-1-8-4.5-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
    store: '<path d="M4 8h16l-1 12H5z"/><path d="M8 8a4 4 0 0 1 8 0"/>',
    reports: '<path d="M4 20V10M10 20V4M16 20v-8M22 20H2"/>',
    ai: '<path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z"/><path d="M19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    bell: '<path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 21h4"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    check: '<path d="M5 12l5 5L20 7"/>',
    x: '<path d="M6 6l12 12M18 6 6 18"/>',
    alert: '<path d="M12 3 2 20h20z"/><path d="M12 9v5M12 17h.01"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    file: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 13h6M9 17h6"/>',
    chevronRight: '<path d="m9 6 6 6-6 6"/>',
    chevronLeft: '<path d="m15 6-6 6 6 6"/>',
    chevronDown: '<path d="m6 9 6 6 6-6"/>',
    logout: '<path d="M10 4H5v16h5"/><path d="M14 8l4 4-4 4M18 12H9"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    print: '<path d="M7 8V3h10v5"/><rect x="4" y="8" width="16" height="9" rx="2"/><path d="M7 14h10v7H7z"/>',
    eye: '<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    edit: '<path d="M4 20h4l10.5-10.5a2 2 0 0 0-4-4L4 16z"/><path d="m13 7 4 4"/>',
    trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    users: '<circle cx="9" cy="8" r="3.5"/><path d="M2 20a7 7 0 0 1 14 0"/><circle cx="17" cy="9" r="3"/><path d="M16 15.5a5.5 5.5 0 0 1 6 4.5"/>',
    phone: '<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z"/>',
    mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
    download: '<path d="M12 4v12M6 10l6 6 6-6M4 20h16"/>',
    refresh: '<path d="M20 12a8 8 0 1 1-2.3-5.7"/><path d="M20 4v5h-5"/>',
    book: '<path d="M4 4h6a3 3 0 0 1 3 3v13a2 2 0 0 0-2-2H4z"/><path d="M20 4h-6a3 3 0 0 0-3 3v13a2 2 0 0 1 2-2h7z"/>',
    clipboard: '<rect x="6" y="4" width="12" height="17" rx="2"/><path d="M9 4V2h6v2M9 11h6M9 15h6"/>',
    id: '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8.5" cy="11" r="2"/><path d="M5 17a3.5 3.5 0 0 1 7 0M14 10h4M14 14h4"/>',
    receipt: '<path d="M6 3h12v18l-2-1.5L14 21l-2-1.5L10 21l-2-1.5L6 21z"/><path d="M9 8h6M9 12h6M9 16h3"/>',
    trend: '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    grid: '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
    list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    cart: '<circle cx="9" cy="20" r="1.5"/><circle cx="17" cy="20" r="1.5"/><path d="M3 4h2l2.5 11h11L21 7H6.2"/>',
    inbox: '<path d="M4 4h16v16H4z"/><path d="M4 14h5l1.5 2h3L15 14h5"/>',
    lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 17-6-5-8 8"/>',
    upload: '<path d="M12 16V4M6 10l6-6 6 6M4 20h16"/>',
    camera: '<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>',
  };

  function icon(name, size) {
    var p = PATHS[name] || PATHS.info;
    size = size || 18;
    return '<svg class="ic ic-' + name + '" viewBox="0 0 24 24" width="' + size + '" height="' + size + '" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + p + "</svg>";
  }

  // ---------------- Formats ----------------
  var SYMBOLS = { USD: "$", CDF: "FC", EUR: "€" };
  var defaultCurrency = "USD";

  function money(v, currency) {
    var cur = currency || defaultCurrency;
    var n = Number(v) || 0;
    var digits = cur === "CDF" ? 0 : 2;
    var s = n.toLocaleString("fr-FR", { minimumFractionDigits: 0, maximumFractionDigits: digits });
    return s + " " + (SYMBOLS[cur] || cur);
  }
  function compactMoney(v, currency) {
    var cur = currency || defaultCurrency;
    var n = Number(v) || 0;
    var abs = Math.abs(n);
    var out;
    if (abs >= 1e9) out = (n / 1e9).toLocaleString("fr-FR", { maximumFractionDigits: 1 }) + " Md";
    else if (abs >= 1e6) out = (n / 1e6).toLocaleString("fr-FR", { maximumFractionDigits: 1 }) + " M";
    else if (abs >= 1e4) out = (n / 1e3).toLocaleString("fr-FR", { maximumFractionDigits: 1 }) + " k";
    else out = n.toLocaleString("fr-FR", { maximumFractionDigits: cur === "CDF" ? 0 : 2 });
    return out + " " + (SYMBOLS[cur] || cur);
  }
  function fmtDate(v) {
    if (!v) return "—";
    var d = typeof v === "number" || /^\d+(\.\d+)?$/.test(String(v)) ? new Date(parseFloat(v) * 1000) : new Date(v + (String(v).length === 10 ? "T00:00:00" : ""));
    if (isNaN(d.getTime())) return String(v);
    return d.toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" });
  }
  function fmtDateTime(v) {
    if (!v) return "—";
    var d = new Date(parseFloat(v) * 1000);
    if (isNaN(d.getTime())) return String(v);
    return d.toLocaleString("fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  }
  function relTime(v) {
    var t = parseFloat(v) * 1000, diff = Date.now() - t;
    if (isNaN(t)) return "";
    var m = Math.round(diff / 60000);
    if (m < 1) return "à l'instant";
    if (m < 60) return "il y a " + m + " min";
    var h = Math.round(m / 60);
    if (h < 24) return "il y a " + h + " h";
    var d = Math.round(h / 24);
    if (d < 7) return "il y a " + d + " j";
    return fmtDate(v);
  }
  function initials(s) {
    var f = (s.first_name || "").trim(), l = (s.last_name || "").trim();
    return ((f[0] || "") + (l[0] || "")).toUpperCase() || "?";
  }
  function fullName(s) { return ((s.first_name || "") + " " + (s.last_name || "")).trim(); }
  function plural(n, one, many) { return n + " " + (n > 1 ? (many || one + "s") : one); }
  var WEEKDAYS = ["", "Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"];

  // Avatar : photo réelle fournie par l'établissement, sinon initiales.
  function avatar(s, size, cls) {
    size = size || 40;
    var style = 'style="width:' + size + "px;height:" + size + 'px;font-size:' + Math.round(size * 0.36) + 'px"';
    // escapeHtml sur une URL insérée dans un attribut : le serveur impose déjà
    // une forme stricte de data URI, mais une donnée n'est jamais insérée
    // brute dans du HTML. Vérifié pendant l'audit : sans cela, un guillemet
    // dans photo_data refermait l'attribut et injectait de vrais attributs
    // (un onerror est arrivé jusque dans le DOM).
    if (s.photo_data) return '<span class="avatar-img ' + (cls || "") + '" ' + style + '><img src="' + escapeHtml(s.photo_data) + '" alt=""></span>';
    return '<span class="avatar-init ' + (cls || "") + '" ' + style + ">" + escapeHtml(initials(s)) + "</span>";
  }

  // ---------------- Statuts ----------------
  var STATUS = {
    present: ["Présent", "ok"], late: ["Retard", "warn"], absent: ["Absent", "bad"], excused: ["Excusé", "neutral"],
    PAID: ["Payé", "ok"], PARTIALLY_PAID: ["Partiel", "warn"], ISSUED: ["Dû", "bad"],
    CONFIRMED: ["Confirmé", "ok"], CREATED: ["En attente", "warn"], PENDING: ["En attente", "warn"], FAILED: ["Échoué", "bad"], CANCELLED: ["Annulé", "neutral"],
    pending: ["En attente", "warn"], accepted: ["Acceptée", "ok"], revoked: ["Révoquée", "bad"], expired: ["Expirée", "neutral"],
    paid: ["Payée", "ok"], delivered: ["Livrée", "ok"], cancelled: ["Annulée", "neutral"],
    low: ["Mineur", "neutral"], medium: ["Modéré", "warn"], high: ["Grave", "bad"],
    active: ["Actif", "ok"], archived: ["Archivé", "neutral"], transferred: ["Transféré", "neutral"],
    maternelle: ["Maternelle", "neutral"], primaire: ["Primaire", "info"], secondaire: ["Secondaire", "ok"],
  };
  function badge(status, label) {
    var s = STATUS[status] || [label || status || "—", "neutral"];
    return '<span class="badge ' + s[1] + '">' + escapeHtml(label || s[0]) + "</span>";
  }
  var METHODS = { cash: "Espèces", bank: "Banque", mobile_money: "Mobile Money", card: "Carte" };
  var ROLE_LABELS = { directeur: "Direction", discipline: "Directeur des disciplines", professeur: "Professeur", parent: "Parent" };

  // Page d'arrivée d'un rôle : après connexion, après activation d'une
  // invitation, et au bout des liens « Retour ». Le professeur n'entre pas par
  // un tableau de bord mais par SES CLASSES — c'est là que son métier commence.
  //
  // Le rôle passé ici vient TOUJOURS d'une réponse serveur (/auth/login,
  // /password-reset, l'acceptation d'invitation ou /me) — jamais de
  // localStorage : `klassio_role` est un cache d'affichage qu'un second compte
  // ouvert dans le même navigateur écrase. Une arrivée choisie sur ce cache
  // enverrait l'utilisateur chez le rôle précédent.
  //
  // Cette fonction vit dans ui.js, et non dans app.js, parce que la page
  // publique d'invitation en a besoin et ne charge que ui.js. Une seule
  // définition : deux copies auraient divergé au premier changement de menu.
  function homeFor(role) {
    return role === "professeur" ? "classes.html" : "dashboard.html";
  }

  // ---------------- États ----------------
  function skeleton(kind, n) {
    n = n || 3;
    var out = "";
    for (var i = 0; i < n; i++) {
      if (kind === "kpi") out += '<div class="kpi-card is-skeleton"><span class="sk sk-text w40"></span><span class="sk sk-title w70"></span></div>';
      else if (kind === "row") out += '<div class="sk-row"><span class="sk sk-circle"></span><span class="sk sk-text w50"></span><span class="sk sk-text w20"></span></div>';
      else if (kind === "card") out += '<div class="panel is-skeleton"><span class="sk sk-title w50"></span><span class="sk sk-text w90"></span><span class="sk sk-text w70"></span></div>';
      else if (kind === "folder") out += '<div class="sfolder is-skeleton"><span class="sk sk-circle lg"></span><span class="sk sk-text w60"></span><span class="sk sk-text w40"></span></div>';
      else out += '<span class="sk sk-text w80"></span>';
    }
    return '<div class="sk-wrap" aria-busy="true" aria-live="polite">' + out + "</div>";
  }
  function emptyState(title, text, actionHtml, iconName) {
    return '<div class="empty-state">' + icon(iconName || "inbox", 28) + "<h3>" + escapeHtml(title) + "</h3>" +
           (text ? "<p>" + escapeHtml(text) + "</p>" : "") + (actionHtml || "") + "</div>";
  }
  function errorState(title, text, retryId) {
    return '<div class="error-state" role="alert">' + icon("alert", 26) + "<h3>" + escapeHtml(title || "Impossible de charger les données") + "</h3>" +
           "<p>" + escapeHtml(text || "Nous n'avons pas pu récupérer les données. Réessayez dans quelques instants.") + "</p>" +
           (retryId ? '<button type="button" class="btn btn-ghost btn-sm" id="' + retryId + '">' + icon("refresh", 15) + " Réessayer</button>" : "") + "</div>";
  }

  // ---------------- Boutons : default → loading → success / error ----------------
  function btnState(btn, state, label) {
    if (!btn) return;
    if (!btn.dataset.idleHtml) btn.dataset.idleHtml = btn.innerHTML;
    btn.classList.remove("is-loading", "is-success", "is-error");
    btn.disabled = false;
    if (state === "loading") {
      btn.classList.add("is-loading"); btn.disabled = true;
      btn.innerHTML = '<span class="spinner" aria-hidden="true"></span>' + escapeHtml(label || "Enregistrement…");
    } else if (state === "success") {
      btn.classList.add("is-success"); btn.disabled = true;
      btn.innerHTML = icon("check", 15) + escapeHtml(label || "Enregistré");
      setTimeout(function () { btnState(btn, "idle"); }, 1600);
    } else if (state === "error") {
      btn.classList.add("is-error");
      btn.innerHTML = icon("alert", 15) + escapeHtml(label || "Réessayer");
      setTimeout(function () { btnState(btn, "idle"); }, 2200);
    } else {
      btn.innerHTML = btn.dataset.idleHtml;
    }
  }

  // ---------------- Toasts ----------------
  function toast(message, type, ms) {
    var host = document.getElementById("toastHost");
    if (!host) { host = document.createElement("div"); host.id = "toastHost"; host.className = "toast-host"; host.setAttribute("aria-live", "polite"); document.body.appendChild(host); }
    var el = document.createElement("div");
    el.className = "toast " + (type || "info");
    el.innerHTML = icon(type === "success" ? "check" : type === "error" ? "alert" : "info", 16) + "<span>" + escapeHtml(message) + "</span>";
    host.appendChild(el);
    requestAnimationFrame(function () { el.classList.add("shown"); });
    setTimeout(function () { el.classList.remove("shown"); setTimeout(function () { el.remove(); }, 300); }, ms || 3200);
  }

  // ---------------- Modales ----------------
  var openModal = null;
  function modal(opts) {
    closeModal();
    var wrap = document.createElement("div");
    wrap.className = "modal-backdrop";
    wrap.innerHTML = '<div class="modal ' + (opts.size || "") + '" role="dialog" aria-modal="true" aria-labelledby="modalTitle">' +
      '<div class="modal-head"><h2 id="modalTitle">' + escapeHtml(opts.title || "") + '</h2><button type="button" class="icon-btn modal-close" aria-label="Fermer">' + icon("x", 16) + "</button></div>" +
      '<div class="modal-body">' + (opts.body || "") + "</div>" +
      (opts.footer ? '<div class="modal-foot">' + opts.footer + "</div>" : "") + "</div>";
    document.body.appendChild(wrap);
    document.body.classList.add("no-scroll");
    requestAnimationFrame(function () { wrap.classList.add("shown"); });
    wrap.querySelector(".modal-close").addEventListener("click", closeModal);
    wrap.addEventListener("mousedown", function (e) { if (e.target === wrap && opts.dismissible !== false) closeModal(); });
    var first = wrap.querySelector("input, select, textarea, button:not(.modal-close)");
    if (first) setTimeout(function () { first.focus(); }, 50);
    openModal = wrap;
    if (opts.onOpen) opts.onOpen(wrap);
    return wrap;
  }
  function closeModal() {
    if (!openModal) return;
    var m = openModal; openModal = null;
    m.classList.remove("shown");
    document.body.classList.remove("no-scroll");
    setTimeout(function () { m.remove(); }, 220);
  }
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && openModal) closeModal(); });

  function confirmDialog(title, text, okLabel) {
    return new Promise(function (resolve) {
      var m = modal({ title: title, body: "<p class='modal-text'>" + escapeHtml(text) + "</p>",
        footer: '<button type="button" class="btn btn-ghost btn-sm" id="cfCancel">Annuler</button><button type="button" class="btn btn-lime btn-sm" id="cfOk">' + escapeHtml(okLabel || "Confirmer") + "</button>" });
      m.querySelector("#cfCancel").addEventListener("click", function () { closeModal(); resolve(false); });
      m.querySelector("#cfOk").addEventListener("click", function () { closeModal(); resolve(true); });
    });
  }

  // ---------------- Onglets ----------------
  function tabs(container, onChange) {
    var buttons = container.querySelectorAll("[data-tab]");
    function activate(name, silent) {
      buttons.forEach(function (b) {
        var on = b.dataset.tab === name;
        b.classList.toggle("active", on); b.setAttribute("aria-selected", on ? "true" : "false");
      });
      document.querySelectorAll("[data-tab-panel]").forEach(function (p) { p.hidden = p.dataset.tabPanel !== name; });
      if (!silent && onChange) onChange(name);
    }
    buttons.forEach(function (b) { b.setAttribute("role", "tab"); b.addEventListener("click", function () { activate(b.dataset.tab); }); });
    container.addEventListener("keydown", function (e) {
      var idx = Array.prototype.indexOf.call(buttons, document.activeElement);
      if (idx < 0) return;
      if (e.key === "ArrowRight") { buttons[(idx + 1) % buttons.length].focus(); buttons[(idx + 1) % buttons.length].click(); }
      if (e.key === "ArrowLeft") { buttons[(idx - 1 + buttons.length) % buttons.length].focus(); buttons[(idx - 1 + buttons.length) % buttons.length].click(); }
    });
    return { activate: activate };
  }

  // ---------------- Graphiques légers ----------------
  function barRows(items, opts) {
    opts = opts || {};
    if (!items.length) return '<p class="muted">' + escapeHtml(opts.empty || "Aucune donnée pour le moment.") + "</p>";
    var max = Math.max.apply(null, items.map(function (i) { return Number(i.value) || 0; })) || 1;
    return '<div class="bar-rows">' + items.map(function (i) {
      var pct = Math.round((Number(i.value) || 0) / max * 100);
      return '<div class="bar-row' + (i.href ? " clickable" : "") + '"' + (i.href ? ' data-href="' + escapeHtml(i.href) + '"' : "") + '><span class="br-label" title="' + escapeHtml(i.label) + '">' + escapeHtml(i.label) + '</span>' +
             '<span class="br-track"><span class="br-bar ' + (i.cls || "") + '" style="width:' + pct + '%"></span></span>' +
             '<span class="br-value">' + escapeHtml(i.display != null ? i.display : i.value) + "</span></div>";
    }).join("") + "</div>";
  }
  function stackedBar(parts, total) {
    total = total || parts.reduce(function (s, p) { return s + (p.value || 0); }, 0);
    if (!total) return '<div class="stack-bar empty"></div>';
    return '<div class="stack-bar">' + parts.map(function (p) {
      var w = Math.round((p.value || 0) / total * 100);
      return w ? '<span class="sb ' + p.cls + '" style="width:' + w + '%" title="' + escapeHtml(p.label + " : " + p.value) + '"></span>' : "";
    }).join("") + "</div>";
  }
  function ring(pct, label, cls) {
    pct = Math.max(0, Math.min(100, Math.round(pct || 0)));
    var r = 26, c = 2 * Math.PI * r;
    return '<div class="ring ' + (cls || "") + '"><svg viewBox="0 0 64 64" width="64" height="64"><circle class="ring-bg" cx="32" cy="32" r="' + r + '"/><circle class="ring-fg" cx="32" cy="32" r="' + r + '" stroke-dasharray="' + c.toFixed(1) + '" stroke-dashoffset="' + (c * (1 - pct / 100)).toFixed(1) + '"/></svg>' +
           '<div class="ring-txt"><strong>' + pct + '%</strong>' + (label ? "<span>" + escapeHtml(label) + "</span>" : "") + "</div></div>";
  }

  // Jauge de capital (points de conduite restants)
  function gauge(remaining, capital, label) {
    var pct = capital ? Math.max(0, Math.min(100, Math.round(remaining / capital * 100))) : 0;
    var tone = pct >= 70 ? "ok" : pct >= 40 ? "warn" : "bad";
    return '<div class="gauge ' + tone + '"><div class="gauge-track"><span class="gauge-fill" style="width:' + pct + '%"></span></div>' +
           '<div class="gauge-txt"><strong>' + remaining + '</strong> / ' + capital + " points" + (label ? ' · <em>' + escapeHtml(label) + "</em>" : "") + "</div></div>";
  }
  var EVENT_KIND_LABELS = { evenement: "Événement", communique: "Communiqué", reunion: "Réunion", fete: "Fête", deuil: "Deuil", conge: "Congé", examens: "Examens", echeance: "Échéance",
                            examen: "Examen", devoir: "Devoir", convocation: "Convocation", presence_present: "Présent", presence_late: "Retard", presence_absent: "Absent", presence_excused: "Excusé" };
  var EVENT_KIND_TONES = { deuil: "neutral", conge: "info", fete: "ok", reunion: "warn", examens: "bad", examen: "bad", devoir: "info", convocation: "bad", echeance: "warn", communique: "neutral", evenement: "ok",
                           presence_present: "ok", presence_late: "warn", presence_absent: "bad", presence_excused: "info" };
  function fileToDataUrl(file, maxBytes) {
    return new Promise(function (resolve, reject) {
      if (file.size > maxBytes) return reject(new Error("Fichier trop lourd (" + Math.round(maxBytes / 1024 / 1024 * 10) / 10 + " Mo maximum)."));
      var r = new FileReader(); r.onload = function () { resolve(r.result); }; r.onerror = function () { reject(new Error("Lecture impossible.")); }; r.readAsDataURL(file);
    });
  }
  function printSheet(el, title) {
    var w = window.open("", "_blank", "width=820,height=1000");
    if (!w) { toast("Autorisez les fenêtres pop-up pour imprimer.", "error"); return; }
    var css = Array.prototype.map.call(document.querySelectorAll('link[rel="stylesheet"]'), function (l) { return '<link rel="stylesheet" href="' + l.href + '">'; }).join("");
    w.document.write("<!doctype html><html lang='fr'><head><meta charset='utf-8'><title>" + escapeHtml(title || "Impression") + "</title>" + css + "</head><body style='padding:28px;background:#fff'>" + el.outerHTML + "</body></html>");
    w.document.close(); w.focus(); setTimeout(function () { w.print(); }, 500);
  }

  function kpi(label, value, opts) {
    opts = opts || {};
    return '<div class="kpi-card ' + (opts.cls || "") + (opts.href ? " clickable" : "") + '"' + (opts.href ? ' data-href="' + escapeHtml(opts.href) + '"' : "") + ">" +
           (opts.icon ? '<span class="kpi-ic">' + icon(opts.icon, 18) + "</span>" : "") +
           '<span class="kpi-k">' + escapeHtml(label) + '</span><span class="kpi-v ' + (opts.tone || "") + '">' + escapeHtml(value) + "</span>" +
           (opts.sub ? '<span class="kpi-sub">' + escapeHtml(opts.sub) + "</span>" : "") + "</div>";
  }

  // Liste « à traiter » : seulement ce qui a un compte > 0 — une file d'attente
  // qui affiche des zéros n'est plus une file, c'est un décor.
  //
  // Partagée par le tableau de bord (Direction, DD, parent) et par l'accueil du
  // professeur : le même composant, pas une seconde liste qui divergerait.
  // `vide` est fourni par l'appelant, parce que ce qui « apparaîtra ici »
  // dépend du rôle — on ne promet pas des commandes et des paiements à un
  // enseignant qui ne les verra jamais.
  function todoPanel(items, title, vide) {
    var live = items.filter(function (i) { return i.count > 0; });
    return '<div class="panel"><div class="panel-head"><h2>' + escapeHtml(title || "À traiter") + '</h2><span class="sub">' + (live.length ? plural(live.length, "sujet en attente", "sujets en attente") : "Rien en attente") + "</span></div>" +
      (live.length ? '<div class="roll-list">' + live.map(function (i) {
        return '<a class="roll-row" href="' + escapeHtml(i.href) + '" style="text-decoration:none;color:inherit"><span class="avatar-init soft" style="width:36px;height:36px;font-size:12px;">' + icon(i.icon, 16) + '</span><div class="roll-name">' + escapeHtml(i.label) + "<span>" + escapeHtml(i.sub || "") + "</span></div>" + badge(i.tone || "warn", String(i.count)) + icon("chevronRight", 15) + "</a>";
      }).join("") + "</div>" : '<p class="muted">' + escapeHtml(vide || "Tout est à jour.") + "</p>") + "</div>";
  }

  function wireHrefs(root) {
    (root || document).querySelectorAll("[data-href]").forEach(function (el) {
      if (el.dataset.wired) return;
      el.dataset.wired = "1";
      el.setAttribute("tabindex", "0"); el.setAttribute("role", "link");
      el.addEventListener("click", function () { window.location.href = el.dataset.href; });
      el.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); window.location.href = el.dataset.href; } });
    });
  }

  function debounce(fn, ms) { var t; return function () { var a = arguments, c = this; clearTimeout(t); t = setTimeout(function () { fn.apply(c, a); }, ms || 180); }; }
  function qs(name) { return new URLSearchParams(window.location.search).get(name); }
  function todayIso() { var d = new Date(); return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); }

  window.KlassioUI = {
    escapeHtml: escapeHtml, icon: icon, money: money, compactMoney: compactMoney, setCurrency: function (c) { if (c) defaultCurrency = c; },
    fmtDate: fmtDate, fmtDateTime: fmtDateTime, relTime: relTime, initials: initials, fullName: fullName, plural: plural, WEEKDAYS: WEEKDAYS,
    avatar: avatar, badge: badge, METHODS: METHODS, ROLE_LABELS: ROLE_LABELS,
    homeFor: homeFor,
    skeleton: skeleton, emptyState: emptyState, errorState: errorState, btnState: btnState, toast: toast,
    modal: modal, closeModal: closeModal, confirm: confirmDialog, tabs: tabs,
    barRows: barRows, stackedBar: stackedBar, ring: ring, kpi: kpi, gauge: gauge, todoPanel: todoPanel, wireHrefs: wireHrefs, debounce: debounce, qs: qs, todayIso: todayIso,
    EVENT_KIND_LABELS: EVENT_KIND_LABELS, EVENT_KIND_TONES: EVENT_KIND_TONES, fileToDataUrl: fileToDataUrl, printSheet: printSheet,
  };
})();
