// KLASSIO — Paramètres : compte, mot de passe (révoque les autres sessions),
// préférences personnelles, et pour la Direction les règles de vie scolaire,
// la communication aux parents, le portail et les identifiants élèves.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var ctx = null;

  // Sections par rôle, dans l'ordre de la colonne de gauche. Une section
  // qu'un rôle ne concerne pas n'apparaît pas — plutôt qu'un écran vide.
  var SECTIONS = {
    directeur: ["general", "compte", "confidentialite", "notifications", "etablissement", "facturation"],
    professeur: ["general", "compte", "confidentialite", "acces"],
    discipline: ["general", "compte", "confidentialite", "acces"],
    parent: ["general", "compte", "confidentialite", "notifications"],
  };
  var NOMS = { general: "Général", compte: "Compte", confidentialite: "Confidentialité", notifications: "Notifications", etablissement: "Établissement", acces: "Vos accès", facturation: "Facturation" };

  admin.initShell("parametres").then(function (c) {
    ctx = c;
    document.getElementById("pName").textContent = c.user_name || "—";
    document.getElementById("pRole").textContent = (api.roleLabels[c.role] || c.role) + (c.title ? " — " + c.title : "");
    document.getElementById("pSchool").textContent = c.tenant_name || "—";
    naviguer(c);
    renderProfile(c);
    renderLangues();
    renderPreferences(c);
    renderConfidentialite(c);
    renderAbonnement(c);
    renderSuppression(c);
    if (c.role === "directeur") loadSettings();
    else if (c.role === "professeur") document.getElementById("krAcces").innerHTML = '<div class="kr-bloc">' + ligne("Situation financière des classes", "", c.finance_visible ? UI.badge("ok", "Autorisée par la Direction") : UI.badge("neutral", "Non autorisée")) + ligne("Titulaire", "", c.is_titulaire ? UI.badge("ok", "Oui") : "Non") + ligne("Niveau", "", UI.escapeHtml(c.teaching_level === "primaire" ? "Maternelle / primaire" : c.teaching_level === "secondaire" ? "Secondaire" : "—")) + '<p class="kr-intro">Ces accès sont décidés par la Direction — rien ne se règle depuis votre espace.</p></div>';
    else if (c.role === "discipline") document.getElementById("krAcces").innerHTML = '<div class="kr-bloc"><h3>Votre périmètre</h3><div class="pill-row">' + (c.scope_cycles || []).map(function (x) { return UI.badge(x, x); }).join("") + '</div><p class="kr-intro">Vous voyez les classes de ces cycles : présences, retards, incidents, convocations. Les finances ne relèvent jamais de la discipline. Le périmètre et le titre sont fixés par la Direction.</p>' + ligne("Capital de points et seuils", "", '<a class="btn btn-ghost btn-sm" href="discipline.html?tab=regles">Voir</a>') + "</div>";
  });

  // Une ligne « réglage » : libellé et explication à gauche, contrôle à droite.
  function ligne(titre, desc, droite) {
    return '<div class="kr-ligne"><div class="kr-lib"><strong>' + titre + "</strong>" + (desc ? "<span>" + desc + "</span>" : "") + '</div><div class="kr-ctrl">' + (droite || "") + "</div></div>";
  }

  // ---- Navigation entre sections ----
  // `?section=` porte la section ; `?tab=abonnement` (ancien lien, bandeau de
  // lecture seule) mène à Facturation.
  function naviguer(c) {
    var liste = SECTIONS[c.role] || SECTIONS.parent;
    var nav = document.getElementById("krNav");
    nav.innerHTML = liste.map(function (n) { return '<a href="parametres.html?section=' + n + '" class="kr-nav-item" data-section="' + n + '">' + NOMS[n] + "</a>"; }).join("");
    var voulu = UI.qs("tab") === "abonnement" ? "facturation" : UI.qs("section");
    montrer(liste.indexOf(voulu) >= 0 ? voulu : liste[0], false);
    nav.addEventListener("click", function (e) {
      var a = e.target.closest("[data-section]");
      if (!a) return;
      e.preventDefault();
      montrer(a.dataset.section, true);
    });
    window.addEventListener("popstate", function () {
      var s = UI.qs("section");
      montrer(liste.indexOf(s) >= 0 ? s : liste[0], false);
    });
    if (location.hash === "#langue") setTimeout(function () { var l = document.getElementById("langue"); if (l) l.scrollIntoView({ block: "start" }); }, 150);
  }
  function montrer(nom, pousser) {
    document.querySelectorAll(".kr-section").forEach(function (s) { s.hidden = s.dataset.section !== nom; });
    document.querySelectorAll(".kr-nav-item").forEach(function (a) {
      var on = a.dataset.section === nom;
      a.classList.toggle("active", on);
      if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    if (pousser) { history.pushState(null, "", "parametres.html?section=" + nom); window.scrollTo(0, 0); }
  }

  // ---- Langue ----
  // La traduction elle-même vit dans langue.js : ici, seulement le choix.
  function renderLangues() {
    var hote = document.getElementById("krLangues"), L = window.KlassioLangue;
    if (!hote || !L) return;
    var actuelle = L.actuelle();
    hote.innerHTML = L.liste().map(function (l) {
      var on = l.code === actuelle;
      return '<button type="button" role="radio" aria-checked="' + on + '" class="kr-langue' + (on ? " active" : "") + '" data-langue="' + l.code + '" lang="' + l.code + '"><strong data-no-tr>' + l.nom + "</strong><span>" + l.region + "</span></button>";
    }).join("");
    hote.addEventListener("click", function (e) {
      var b = e.target.closest("[data-langue]");
      if (!b || b.dataset.langue === L.actuelle()) return;
      hote.querySelectorAll("[data-langue]").forEach(function (x) { x.disabled = true; });
      L.choisir(b.dataset.langue).then(function (ok) {
        if (!ok) { hote.querySelectorAll("[data-langue]").forEach(function (x) { x.disabled = false; }); UI.toast("Impossible d'enregistrer la langue.", "error"); return; }
        window.location.reload();
      });
    });
  }

  // ---- Confidentialité ----
  // Ne rassemble que ce qui existe vraiment : la politique publiée, la
  // sécurité, la visibilité des coordonnées, l'export, l'assistant en lecture
  // seule, la suppression du compte. Aucun réglage décoratif.
  function renderConfidentialite(c) {
    var hote = document.getElementById("krConfidentialite");
    var html = '<div class="kr-bloc"><h3>Vos données</h3>' +
      ligne("Politique de confidentialité", "Ce que Klassio collecte, pourquoi, combien de temps, et vos droits.", '<a class="btn btn-ghost btn-sm" href="../confidentialite.html" target="_blank" rel="noopener">Lire</a>') +
      ligne("Sécurité", "Comment les données des élèves et des familles sont protégées.", '<a class="btn btn-ghost btn-sm" href="../securite.html" target="_blank" rel="noopener">Lire</a>') +
      (c.role === "directeur" ? ligne("Exporter les données de l'établissement", "Un classeur Excel par type de données, dans une archive à télécharger.", '<a class="btn btn-ghost btn-sm" href="exports.html">Exporter</a>') : "") +
      '</div><div class="kr-bloc" id="krVisibilite"></div>' +
      '<div class="kr-bloc"><h3>Assistant</h3>' +
      ligne("En lecture seule", "L'assistant de Klassio ne peut ni créer, ni modifier, ni supprimer quoi que ce soit.", UI.badge("ok", "Toujours")) +
      ligne("Vos échanges avec l'assistant", "Supprimés avec votre compte.", "") +
      "</div>" +
      '<div class="kr-bloc"><h3>Suppression</h3>' +
      ligne("Supprimer mon compte", "Ce qui part et ce qui reste vous est expliqué avant toute confirmation.", '<a class="btn btn-ghost btn-sm" href="parametres.html?section=compte" id="krVersSuppr">Voir</a>') + "</div>";
    hote.innerHTML = html;
    document.getElementById("krVersSuppr").addEventListener("click", function (e) {
      e.preventDefault(); montrer("compte", true);
      document.getElementById("suppressionCompte").scrollIntoView({ block: "start" });
    });
  }

  api.wirePasswordRules(document.getElementById("pwNew"), document.getElementById("pwRules"));
  document.getElementById("pwForm").addEventListener("submit", function (e) {
    e.preventDefault();
    var msg = document.getElementById("pwMsg"), btn = document.getElementById("pwBtn");
    msg.className = "form-msg"; msg.textContent = "";
    var next = document.getElementById("pwNew").value;
    if (!api.passwordMeetsRules(next)) { msg.textContent = "Le nouveau mot de passe ne respecte pas encore toutes les règles."; msg.className = "form-msg error"; return; }
    UI.btnState(btn, "loading", "Mise à jour…");
    api.fetch("/me/password", { method: "POST", body: JSON.stringify({ current_password: document.getElementById("pwCurrent").value, new_password: next }) }).then(function (res) {
      if (!res.ok) { UI.btnState(btn, "error"); msg.textContent = res.body.error || "Impossible de changer le mot de passe."; msg.className = "form-msg error"; return; }
      // La nouvelle session est déjà dans le cookie, posée par le serveur.
      document.getElementById("pwForm").reset();
      UI.btnState(btn, "success", "Mis à jour");
      msg.textContent = "Mot de passe mis à jour. Vos autres sessions ont été déconnectées."; msg.className = "form-msg success";
    });
  });

  var dec = document.getElementById("krDeconnexion");
  if (dec) dec.addEventListener("click", function () { var b = document.getElementById("logoutBtn"); if (b) b.click(); });

  // ---- Profil : téléphone et email de connexion ----
  // ---- Apparence : le thème, déplacé de la topbar vers les paramètres ----
  function wireApparence() {
    var hote = document.getElementById("themeChoice");
    var T = window.KlassioTheme;
    if (!hote || !T) return;
    var boutons = [].slice.call(hote.querySelectorAll("[data-theme-pick]"));
    function refleter() {
      // getChoice() renvoie le choix BRUT : « Système » doit rester coché
      // comme tel, même si la couleur appliquée est sombre.
      var actuel = (T.getChoice && T.getChoice()) || "system";
      boutons.forEach(function (b) {
        var on = b.dataset.themePick === actuel;
        b.classList.toggle("active", on);
        b.setAttribute("aria-checked", on ? "true" : "false");
      });
    }
    hote.addEventListener("click", function (e) {
      var b = e.target.closest("[data-theme-pick]");
      if (!b) return;
      T.set(b.dataset.themePick);
      refleter();
    });
    refleter();
  }
  wireApparence();

  // ---- Suppression du compte --------------------------------------------
  //
  // Trois exigences tenues ici :
  //
  // 1. TROUVABLE. Elle est dans les paramètres, à sa place, pas enfouie dans un
  //    email de support. Les magasins d'applications l'exigent, et c'est dû.
  // 2. EXPLICITE. On dit ce qui part ET ce qui reste, AVANT de demander quoi
  //    que ce soit. La crainte légitime — « vais-je effacer le dossier de mon
  //    enfant ? » — se lève avant le formulaire, pas après.
  // 3. RÉAUTHENTIFIÉE. Le mot de passe est redemandé : une session laissée
  //    ouverte sur un poste partagé ne doit pas suffire à supprimer un compte.
  function renderSuppression(c) {
    var hote = document.getElementById("suppressionCorps");
    if (!hote) return;
    hote.innerHTML =
      '<p class="muted" style="margin-bottom:14px">Votre compte et vos données personnelles seront supprimés. ' +
      "Vous ne pourrez plus accéder à Klassio.</p>" +
      '<div class="two-col" style="margin-bottom:16px">' +
      '<div><h3 style="font-size:14px;margin:0 0 6px">Ce qui est supprimé</h3><ul class="muted" style="font-size:13.5px;line-height:1.7;padding-left:18px;margin:0">' +
      "<li>Votre nom, votre email, votre téléphone</li><li>Votre mot de passe et vos sessions</li>" +
      "<li>Vos échanges avec l'assistant</li></ul></div>" +
      '<div><h3 style="font-size:14px;margin:0 0 6px">Ce qui est conservé</h3><ul class="muted" style="font-size:13.5px;line-height:1.7;padding-left:18px;margin:0">' +
      "<li>Les dossiers des élèves — ils appartiennent à l'établissement</li>" +
      "<li>Les résultats, présences et documents</li>" +
      "<li>Les paiements et reçus — pièces comptables</li>" +
      "<li>Le journal d'audit</li></ul></div></div>" +
      (c.role === "directeur"
        // `note-garde` : un avertissement, pas une explication — il reste
        // affiché même dans une école encore vide (voir app-visuel.css).
        ? '<p class="note-inline note-garde" style="margin-bottom:14px">' + UI.icon("alert", 15) +
          "<span>Vous êtes Direction. Si vous êtes la seule de votre établissement, nommez d'abord une autre Direction — sans elle, l'espace deviendrait inadministrable pour les familles et les enseignants.</span></p>"
        : "") +
      '<button type="button" class="btn btn-danger btn-sm" id="supprBtn">' + UI.icon("trash", 15) + "Supprimer mon compte</button>";

    document.getElementById("supprBtn").addEventListener("click", function () {
      var m = UI.modal({
        title: "Supprimer définitivement votre compte ?",
        body: '<form id="supprForm" class="form-grid">' +
          '<p class="modal-text full">Cette action est <strong>définitive</strong>. Vous perdrez immédiatement l\'accès à Klassio. ' +
          "Les données de votre établissement ne sont pas supprimées.</p>" +
          '<div class="field full"><label for="supprPw">Confirmez avec votre mot de passe</label>' +
          '<input id="supprPw" type="password" autocomplete="current-password" required />' +
          '<span class="hint">Nous le redemandons pour être sûrs que c\'est bien vous.</span></div>' +
          '<p class="form-error full" id="supprErr" hidden></p></form>',
        footer: '<button type="button" class="btn btn-ghost btn-sm" id="supprCancel">Annuler</button>' +
                '<button type="submit" form="supprForm" class="btn btn-danger btn-sm" id="supprGo">Supprimer mon compte</button>'
      });
      m.querySelector("#supprCancel").addEventListener("click", UI.closeModal);
      m.querySelector("#supprForm").addEventListener("submit", function (e) {
        e.preventDefault();
        var btn = m.querySelector("#supprGo"), err = m.querySelector("#supprErr");
        err.hidden = true;
        UI.btnState(btn, "loading", "Suppression…");
        api.fetch("/me/delete", { method: "POST", body: JSON.stringify({
          password: m.querySelector("#supprPw").value,
        }) }).then(function (res) {
          if (!res.ok) {
            UI.btnState(btn, "error");
            err.textContent = res.body.error || "Suppression impossible.";
            err.hidden = false;
            return;
          }
          UI.btnState(btn, "success", "Supprimé");
          try { localStorage.clear(); } catch (x) {}
          m.querySelector(".modal-body").innerHTML =
            '<div class="pay-resultat ok"><span class="pr-ic">' + UI.icon("check", 26) + "</span>" +
            "<h3>Compte supprimé</h3><p>" + UI.escapeHtml(res.body.message) + "</p></div>";
          m.querySelector(".modal-foot").innerHTML = '<a href="../index.html" class="btn btn-lime btn-sm">Retour à l\'accueil</a>';
        }).catch(function () {
          UI.btnState(btn, "error");
          err.textContent = "Le serveur Klassio est injoignable.";
          err.hidden = false;
        });
      });
    });
  }

  // ---- Abonnement Klassio (Direction) -----------------------------------
  //
  // Toute l'information commerciale de l'établissement, à un seul endroit.
  // Elle est AFFICHÉE ici, pas recalculée : `api_billing.summary` reste seul
  // juge du statut, des jours restants, du palier et du montant. Le navigateur
  // ne décompte rien — un compteur calculé côté client se décalerait dès que
  // l'horloge du poste dérive, et personne ne saurait lequel croire.
  //
  // Aucun paiement d'abonnement n'est simulé : il n'existe pas d'intégration
  // de règlement pour l'abonnement Klassio, et l'écran ne prétend pas le
  // contraire.
  function renderAbonnement(c) {
    if (c.role !== "directeur") return;
    var corps = document.getElementById("abonnementCorps");
    function charger() {
      corps.innerHTML = UI.skeleton("row", 3);
      api.fetch("/subscription").then(function (res) {
        if (!res.ok) { corps.innerHTML = UI.errorState("Facturation indisponible", res.body.error || ""); return; }
        window.KlassioFacturation.render(corps, res.body, { reload: charger });
      }).catch(function () { corps.innerHTML = UI.errorState("Le serveur Klassio est injoignable"); });
    }
    charger();
  }

  function renderProfile(c) {
    var host = document.getElementById("profilePanel");
    if (!host) return;
    host.innerHTML = '<div class="kr-bloc"><h3>Identifiants de connexion</h3><p class="kr-intro">Connectez-vous avec l\'un ou l\'autre.</p><form id="profileForm" class="form-grid">' +
      '<div class="field"><label for="prPhone">Téléphone</label><input id="prPhone" type="tel" value="' + UI.escapeHtml(c.phone || "") + '" placeholder="09xx xxx xxx" /></div>' +
      '<div class="field"><label for="prEmail">Email</label><input id="prEmail" type="email" value="' + UI.escapeHtml(c.email || "") + '" placeholder="vous@exemple.com" /></div>' +
      '<div class="full row between"><p class="form-msg" id="prMsg"></p><button type="submit" class="btn btn-ghost btn-sm" id="prBtn">Enregistrer</button></div></form></div>';
    document.getElementById("profileForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = document.getElementById("prBtn"), msg = document.getElementById("prMsg"); msg.textContent = "";
      UI.btnState(btn, "loading");
      api.fetch("/me", { method: "PUT", body: JSON.stringify({ phone: document.getElementById("prPhone").value.trim() || null, email: document.getElementById("prEmail").value.trim() || null }) }).then(function (r) {
        if (!r.ok) { UI.btnState(btn, "error"); msg.textContent = r.body.error || "Erreur."; msg.className = "form-msg error"; return; }
        UI.btnState(btn, "success"); msg.textContent = "Identifiants mis à jour."; msg.className = "form-msg success";
      });
    });
  }

  // ---- Préférences personnelles (notifications, coordonnées) ----
  // Préférences personnelles : la notification quotidienne d'un parent va dans
  // Notifications ; le téléphone d'un professeur est une affaire de
  // visibilité, il va dans Confidentialité.
  function renderPreferences(c) {
    if (c.role !== "parent" && c.role !== "professeur") return;
    api.fetch("/me/preferences").then(function (r) {
      if (!r.ok) return;
      var p = r.body, hote;
      if (c.role === "parent") {
        hote = document.getElementById("krNotifications");
        hote.innerHTML = '<div class="kr-bloc"><h3>Vos notifications</h3>' + sw("notify_present_daily", "Me prévenir chaque jour que mon enfant est bien arrivé", "Une notification par enfant et par jour, à la validation de l'appel. Les absences et retards vous sont signalés dans tous les cas.", p.notify_present_daily) + "</div>";
      } else {
        hote = document.getElementById("krVisibilite");
        hote.innerHTML = "<h3>Vos coordonnées</h3>" + sw("share_phone", "Autoriser les parents de mes classes à voir mon téléphone", "Sinon, les parents passent par le cahier de communication de Klassio. La Direction peut aussi ouvrir les coordonnées pour tout l'établissement.", p.share_phone);
      }
      hote.querySelectorAll("input[data-pref]").forEach(function (cb) {
        cb.addEventListener("change", function () {
          var payload = {}; payload[cb.dataset.pref] = cb.checked;
          api.fetch("/me/preferences", { method: "PUT", body: JSON.stringify(payload) }).then(function (rr) {
            if (!rr.ok) { cb.checked = !cb.checked; return UI.toast("Impossible d'enregistrer.", "error"); }
            UI.toast("Préférence enregistrée.", "success");
          });
        });
      });
    });
  }

  function logoEnJpeg(file) {
    return new Promise(function (resolve, reject) {
      if (file.size > 15 * 1024 * 1024) return reject(new Error("Image trop lourde (15 Mo maximum)."));
      var url = URL.createObjectURL(file), img = new Image();
      img.onload = function () {
        var k = Math.min(1, 400 / Math.max(img.width, img.height));
        var c = document.createElement("canvas");
        c.width = Math.max(1, Math.round(img.width * k)); c.height = Math.max(1, Math.round(img.height * k));
        var g = c.getContext("2d");
        g.fillStyle = "#ffffff"; g.fillRect(0, 0, c.width, c.height);
        g.drawImage(img, 0, 0, c.width, c.height);
        URL.revokeObjectURL(url);
        resolve(c.toDataURL("image/jpeg", 0.88));
      };
      img.onerror = function () { URL.revokeObjectURL(url); reject(new Error("Cette image n'a pas pu être lue.")); };
      img.src = url;
    });
  }

  function readImage(file, maxBytes, cb) {
    if (file.size > maxBytes) return UI.toast("Image trop lourde (" + Math.round(maxBytes / 1024) + " Ko maximum).", "error");
    var reader = new FileReader(); reader.onload = function () { cb(reader.result); }; reader.readAsDataURL(file);
  }

  function renderBranding(s) {
    var b = s.branding || {}, origin = window.location.origin;
    return '<div class="panel" id="brandingPanel"><div class="panel-head"><h2>Portail de l\'établissement</h2><span class="sub">Ce que voient parents, enseignants et DD en ouvrant votre lien</span></div>' +
      '<div class="field"><label for="bSlug">Adresse du portail</label><div class="portal-url"><span>' + UI.escapeHtml(origin) + '/app/portail.html?e=</span><input id="bSlug" value="' + UI.escapeHtml(b.slug || "") + '" /></div><span class="hint">Lettres, chiffres et tirets. C\'est ce lien que vous imprimez et partagez — <a class="link-btn" id="openPortal" href="portail.html?e=' + UI.escapeHtml(b.slug || "") + '" target="_blank" rel="noopener">ouvrir le portail</a>.</span></div>' +
      '<div class="form-grid"><div class="field full"><label for="bTagline">Phrase d\'accueil</label><input id="bTagline" maxlength="160" value="' + UI.escapeHtml(b.tagline || "") + '" placeholder="Ex. Une école, une famille" /></div>' +
      '<div class="field"><label>Logo</label><div class="brand-upload"><div class="bu-preview" id="logoPreview">' + (b.logo_data ? '<img src="' + UI.escapeHtml(b.logo_data) + '" alt="">' : UI.icon("image", 22)) + '</div><div class="bu-text"><strong>Logo de l\'école</strong>Toute image ; il apparaîtra sur les reçus, attestations, registres et bulletins<br><button type="button" class="link-btn" id="logoBtn">Choisir</button>' + (b.logo_data ? ' · <button type="button" class="link-btn" id="logoClear">Retirer</button>' : "") + '</div><input type="file" id="logoInput" accept="image/*" hidden></div></div>' +
      '<div class="field"><label>Photo de couverture</label><div class="brand-upload"><div class="bu-preview wide" id="coverPreview">' + (b.cover_data ? '<img src="' + UI.escapeHtml(b.cover_data) + '" alt="">' : UI.icon("image", 22)) + '</div><div class="bu-text"><strong>Photo de l\'établissement</strong>JPEG, paysage, 1 Mo max<br><button type="button" class="link-btn" id="coverBtn">Choisir</button>' + (b.cover_data ? ' · <button type="button" class="link-btn" id="coverClear">Retirer</button>' : "") + '</div><input type="file" id="coverInput" accept="image/png,image/jpeg" hidden></div></div>' +
      '<div class="field"><label for="bColor">Couleur de l\'école</label><div class="color-row"><input type="color" id="bColor" value="' + UI.escapeHtml(b.accent_color || "#5C9600") + '" /><span class="muted">Boutons et éléments actifs du portail</span></div></div>' +
      '<label class="check"><input type="checkbox" id="bFlag"' + (b.show_flag ? " checked" : "") + ' /> Afficher le drapeau de la RDC sur le portail</label></div>' +
      '<div class="row" style="justify-content:flex-end;margin-top:10px"><button type="button" class="btn btn-lime btn-sm" id="brandSave">Enregistrer le portail</button></div></div>' +
      '<div class="panel"><div class="panel-head"><h2>Identifiants des élèves</h2><span class="sub">Format des nouveaux dossiers — les identifiants existants ne changent pas</span></div><div class="form-grid">' +
      '<div class="field"><label for="cPrefix">Préfixe</label><input id="cPrefix" maxlength="8" value="' + UI.escapeHtml(s.code_prefix || "STU") + '" /><span class="hint">Ex. les initiales de l\'école : CSLR</span></div>' +
      '<div class="field"><label for="cMode">Format</label><select id="cMode"><option value="random"' + (s.code_mode !== "sequential" ? " selected" : "") + '>Aléatoire — CSLR-7K4X-92M8</option><option value="sequential"' + (s.code_mode === "sequential" ? " selected" : "") + '>Séquentiel — CSLR-0001, 0002…</option></select></div>' +
      '<div class="full row between"><span class="muted">Aperçu : <span class="chip-code" id="codePreview"></span></span><button type="button" class="btn btn-ghost btn-sm" id="codeSave">Enregistrer</button></div></div>' +
      '<p class="note-inline">' + UI.icon("lock", 15) + "<span>Un identifiant élève sert au pointage, aux documents et aux registres. Il ne donne <strong>jamais</strong> accès à un compte : les élèves n'en ont pas.</span></p></div>";
  }

  function wireBranding() {
    function preview() { var pfx = (document.getElementById("cPrefix").value || "STU").toUpperCase().replace(/[^A-Z0-9]/g, ""); document.getElementById("codePreview").textContent = document.getElementById("cMode").value === "sequential" ? pfx + "-0001" : pfx + "-7K4X-92M8"; }
    document.getElementById("cPrefix").addEventListener("input", preview); document.getElementById("cMode").addEventListener("change", preview); preview();
    var pending = {};
    document.getElementById("logoBtn").addEventListener("click", function () { document.getElementById("logoInput").click(); });
    document.getElementById("coverBtn").addEventListener("click", function () { document.getElementById("coverInput").click(); });
    // Le logo devient un JPEG carré de 400 px au plus, sur fond blanc
    // (08/10/2026) : c'est le format que les bulletins PDF savent incorporer,
    // et il reste léger. Toute image est acceptée — photo du tampon comprise.
    document.getElementById("logoInput").addEventListener("change", function () {
      var f = this.files[0]; if (!f) return;
      logoEnJpeg(f).then(function (d) { pending.logo_data = d; document.getElementById("logoPreview").innerHTML = '<img src="' + UI.escapeHtml(d) + '" alt="">'; })
        .catch(function (e) { UI.toast(e.message || "Image illisible.", "error"); });
    });
    document.getElementById("coverInput").addEventListener("change", function () { if (this.files[0]) readImage(this.files[0], 900 * 1024, function (d) { pending.cover_data = d; document.getElementById("coverPreview").innerHTML = '<img src="' + UI.escapeHtml(d) + '" alt="">'; }); });
    var lc = document.getElementById("logoClear"); if (lc) lc.addEventListener("click", function () { pending.logo_data = null; document.getElementById("logoPreview").innerHTML = UI.icon("image", 22); });
    var cc = document.getElementById("coverClear"); if (cc) cc.addEventListener("click", function () { pending.cover_data = null; document.getElementById("coverPreview").innerHTML = UI.icon("image", 22); });
    document.getElementById("bSlug").addEventListener("input", function () { document.getElementById("openPortal").href = "portail.html?e=" + encodeURIComponent(this.value.trim()); });
    document.getElementById("brandSave").addEventListener("click", function () {
      var btn = this; UI.btnState(btn, "loading");
      var payload = { slug: document.getElementById("bSlug").value.trim(), tagline: document.getElementById("bTagline").value.trim(), accent_color: document.getElementById("bColor").value, show_flag: document.getElementById("bFlag").checked };
      Object.keys(pending).forEach(function (k) { payload[k] = pending[k]; });
      api.fetch("/settings", { method: "PUT", body: JSON.stringify(payload) }).then(function (r) {
        if (!r.ok) { UI.btnState(btn, "error"); return UI.toast(r.body.error || "Erreur.", "error"); }
        UI.btnState(btn, "success"); UI.toast("Portail enregistré.", "success"); pending = {};
        setTimeout(loadSettings, 600);
      });
    });
    document.getElementById("codeSave").addEventListener("click", function () {
      var btn = this; UI.btnState(btn, "loading");
      api.fetch("/settings", { method: "PUT", body: JSON.stringify({ code_prefix: document.getElementById("cPrefix").value.trim(), code_mode: document.getElementById("cMode").value }) }).then(function (r) {
        if (!r.ok) { UI.btnState(btn, "error"); return UI.toast(r.body.error || "Erreur.", "error"); }
        UI.btnState(btn, "success"); UI.toast("Format des identifiants enregistré.", "success");
      });
    });
  }

  function loadSettings() {
    var host = document.getElementById("settingsPanels");
    host.innerHTML = UI.skeleton("card", 2);
    Promise.all([api.fetch("/settings"), api.fetch("/discipline/thresholds")]).then(function (res) {
      if (!res[0].ok) return admin.loadError(host, loadSettings);
      var s = res[0].body, th = res[1].ok ? res[1].body : { capital: 100, thresholds: [] };
      host.innerHTML = '<div class="panel"><div class="panel-head"><h2>Établissement</h2></div><form id="etabForm" class="form-grid"><div class="field full"><label for="sName">Nom</label><input id="sName" value="' + UI.escapeHtml(s.school_name || "") + '" required /></div><div class="field"><label for="sPhone">Téléphone</label><input id="sPhone" value="' + UI.escapeHtml(s.school_phone || "") + '" /></div><div class="field"><label for="sEmail">Email</label><input id="sEmail" type="email" value="' + UI.escapeHtml(s.school_email || "") + '" /></div><div class="field full"><label for="sAddr">Adresse</label><input id="sAddr" value="' + UI.escapeHtml(s.school_address || "") + '" /></div>' +
        '<div class="field"><label for="sCur">Devise par défaut</label><select id="sCur">' + ["USD", "CDF", "EUR"].map(function (c) { return '<option value="' + c + '"' + (s.currency === c ? " selected" : "") + ">" + c + "</option>"; }).join("") + '</select><span class="hint">Utilisée pour l\'import, le catalogue et la boutique.</span></div>' +
        '<div class="full row" style="justify-content:flex-end"><button type="submit" class="btn btn-lime btn-sm" id="etabBtn">Enregistrer</button></div></form></div>' +

        '<div class="panel"><div class="panel-head"><h2>Vie scolaire</h2><span class="sub">Règles communes à tout l\'établissement</span></div><form id="lifeForm" class="form-grid">' +
        '<div class="field"><label for="sPass">Seuil de réussite (%)</label><input id="sPass" type="number" min="0" max="100" step="0.5" value="' + (s.pass_threshold != null ? s.pass_threshold : 50) + '" /><span class="hint">Utilisé par le conseil de classe pour situer chaque élève.</span></div>' +
        '<div class="field"><label for="sCut">Heure limite des commandes boutique</label><input id="sCut" type="time" value="' + UI.escapeHtml(s.store_cutoff_time || "20:00") + '" /><span class="hint">Commande payée avant cette heure : retrait le jour ouvré suivant.</span></div>' +
        '<div class="field"><label for="sExamStart">Période d\'examens — début</label><input id="sExamStart" type="date" value="' + UI.escapeHtml(s.exam_period_starts || "") + '" /></div>' +
        '<div class="field"><label for="sExamEnd">Période d\'examens — fin</label><input id="sExamEnd" type="date" value="' + UI.escapeHtml(s.exam_period_ends || "") + '" /><span class="hint">Pendant cette période, l\'horaire des examens est mis en avant dans l\'espace des parents.</span></div>' +
        '<div class="field"><label for="sThr">Seuil d\'alerte disciplinaire (points de delta)</label><input id="sThr" type="number" max="0" min="-1000" value="' + s.discipline_alert_threshold + '" /><span class="hint">Alerte complémentaire aux seuils de capital.</span></div>' +
        '<div class="full row" style="justify-content:flex-end"><button type="submit" class="btn btn-lime btn-sm" id="lifeBtn">Enregistrer</button></div></form>' +
        '<div class="panel-head" style="margin-top:20px"><h2>Capital de conduite</h2><a class="link-btn" href="discipline.html?tab=regles">Modifier les seuils</a></div>' +
        '<p class="muted">Capital de départ : <strong>' + th.capital + ' points</strong>.</p><div class="threshold-list mt-8">' + (th.thresholds || []).map(function (t) { return '<div class="th"><strong>' + t.remaining_points + "</strong><span>" + UI.escapeHtml(t.label) + (t.action ? " — " + UI.escapeHtml(t.action) : "") + "</span></div>"; }).join("") + "</div></div>" +

        renderBranding(s);
      // Communication aux parents → Notifications ; qui voit les coordonnées et
      // les soldes → Confidentialité. Mêmes interrupteurs, mêmes routes.
      document.getElementById("krNotifications").innerHTML = '<div class="kr-bloc"><h3>Communication aux parents</h3><p class="kr-intro">Vérifiée côté serveur à chaque requête.</p>' +
        sw2("parent_notify_present", "Prévenir les parents que leur enfant est bien arrivé", "Envoyé à la validation de l'appel, une fois par enfant et par jour. Chaque parent peut se désabonner de son côté.", s.parent_notify_present) +
        sw2("parent_notify_attendance", "Informer les parents des absences et retards", "Notification dès l'enregistrement de l'appel ou du pointage au portail.", s.parent_notify_attendance) +
        sw2("parent_notify_incidents", "Autoriser la communication d'incidents aux parents", "Le DD choisit ensuite, incident par incident, d'informer ou non. Les notes internes ne sont jamais transmises.", s.parent_notify_incidents) +
        sw2("parent_notify_grades", "Informer les parents des nouveaux résultats", "Les résultats restent invisibles tant que la période n'est pas proclamée.", s.parent_notify_grades) +
        '<p class="note-inline mt-16">' + UI.icon("lock", 15) + "<span>Aucune de ces options ne permet à Klassio de décider à votre place : l'outil informe, vous décidez.</span></p></div>";
      document.getElementById("krVisibilite").innerHTML = "<h3>Qui voit quoi</h3>" +
        sw2("teacher_contact_visible", "Rendre visibles le téléphone et l'email des enseignants", "Sinon, les parents passent par le cahier de communication. Chaque enseignant peut ouvrir ses coordonnées de son côté.", s.teacher_contact_visible) +
        sw2("teacher_sees_finance", "Les professeurs voient la situation financière de leurs classes", "Sans cette autorisation, aucun solde n'est transmis à un professeur — ni dans les listes, ni dans les dossiers, ni via l'assistant.", s.teacher_sees_finance);
      wireBranding();
      document.getElementById("etabForm").addEventListener("submit", function (e) {
        e.preventDefault();
        var btn = document.getElementById("etabBtn"); UI.btnState(btn, "loading");
        api.fetch("/settings", { method: "PUT", body: JSON.stringify({ school_name: document.getElementById("sName").value.trim(), school_phone: document.getElementById("sPhone").value.trim(), school_email: document.getElementById("sEmail").value.trim(), school_address: document.getElementById("sAddr").value.trim(), currency: document.getElementById("sCur").value }) }).then(function (r) {
          if (!r.ok) { UI.btnState(btn, "error"); return UI.toast(r.body.error || "Erreur.", "error"); }
          UI.btnState(btn, "success"); UI.toast("Réglages enregistrés.", "success");
          document.getElementById("pSchool").textContent = document.getElementById("sName").value.trim();
        });
      });
      document.getElementById("lifeForm").addEventListener("submit", function (e) {
        e.preventDefault();
        var btn = document.getElementById("lifeBtn"); UI.btnState(btn, "loading");
        api.fetch("/settings", { method: "PUT", body: JSON.stringify({
          pass_threshold: parseFloat(document.getElementById("sPass").value),
          store_cutoff_time: document.getElementById("sCut").value,
          exam_period_starts: document.getElementById("sExamStart").value || null,
          exam_period_ends: document.getElementById("sExamEnd").value || null,
          discipline_alert_threshold: parseInt(document.getElementById("sThr").value, 10),
        }) }).then(function (r) {
          if (!r.ok) { UI.btnState(btn, "error"); return UI.toast(r.body.error || "Erreur.", "error"); }
          UI.btnState(btn, "success"); UI.toast("Règles de vie scolaire enregistrées.", "success");
        });
      });
      document.querySelectorAll("input[data-flag]").forEach(function (cb) {
        cb.addEventListener("change", function () {
          var payload = {}; payload[cb.dataset.flag] = cb.checked;
          api.fetch("/settings", { method: "PUT", body: JSON.stringify(payload) }).then(function (r) {
            if (!r.ok) { cb.checked = !cb.checked; return UI.toast(r.body.error || "Erreur.", "error"); }
            UI.toast("Réglage enregistré.", "success");
          });
        });
      });
    });
  }

  function sw2(flag, title, desc, on) {
    return '<label class="switch"><span class="sw-text"><strong>' + UI.escapeHtml(title) + "</strong>" + (desc ? "<span>" + UI.escapeHtml(desc) + "</span>" : "") + '</span><input type="checkbox" data-flag="' + flag + '"' + (on ? " checked" : "") + " /></label>";
  }
  function sw(pref, title, desc, on) {
    return '<label class="switch"><span class="sw-text"><strong>' + UI.escapeHtml(title) + "</strong>" + (desc ? "<span>" + UI.escapeHtml(desc) + "</span>" : "") + '</span><input type="checkbox" data-pref="' + pref + '"' + (on ? " checked" : "") + " /></label>";
  }
})();
