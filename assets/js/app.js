// KLASSIO — client API + session + pages publiques (inscription, connexion).
(function () {
  "use strict";

  var UI = window.KlassioUI;
  // Voir KlassioUI.apiOrigin() : en production, même origine que la page.
  // Le repli couvre le cas — anormal — où ui.js n'aurait pas été chargé.
  var API_BASE = (UI ? UI.apiOrigin() : "http://localhost:5001") + "/api";

  function escapeHtml(s) { return UI ? UI.escapeHtml(s) : String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }

  // Règles réelles, revérifiées côté backend (validation.py) — l'affichage
  // ici n'est qu'un confort, jamais la source de vérité de la sécurité.
  function passwordMeetsRules(v) {
    return v.length >= 8 && /[A-Z]/.test(v) && /[a-z]/.test(v) && /[0-9]/.test(v) && /[^A-Za-z0-9]/.test(v);
  }
  function wirePasswordRules(inputEl, listEl) {
    if (!inputEl || !listEl) return;
    inputEl.addEventListener("input", function () {
      var v = inputEl.value;
      var checks = { length: v.length >= 8, upper: /[A-Z]/.test(v), lower: /[a-z]/.test(v), digit: /[0-9]/.test(v), special: /[^A-Za-z0-9]/.test(v) };
      listEl.querySelectorAll("li").forEach(function (li) { li.classList.toggle("met", !!checks[li.dataset.rule]); });
    });
  }

  // LE TOKEN DE SESSION N'EST PLUS ICI. Depuis le 06/10/2026, le serveur le
  // dépose dans un cookie HttpOnly que ce script ne peut pas lire — c'est tout
  // l'intérêt : une XSS qui passerait la CSP ne pourrait plus l'emporter
  // (backend/security.py, « Où vit le token de session »). Le navigateur
  // joint le cookie tout seul aux appels de la même origine.
  //
  // Un ancien token resté dans localStorage (version précédente) est effacé
  // au premier chargement : il n'a plus à traîner dans le navigateur.
  try { localStorage.removeItem("klassio_token"); } catch (e) {}

  function lireCookie(nom) {
    var m = document.cookie.match(new RegExp("(?:^|; )" + nom + "=([^;]*)"));
    return m ? decodeURIComponent(m[1]) : "";
  }
  // Le jeton CSRF, lui, est lisible : il ne permet rien sans le cookie de
  // session, et un autre site ne peut pas le lire. Sa présence sert aussi
  // d'indice « une session est ouverte » — un indice d'affichage seulement :
  // c'est le serveur qui tranche, par un 401.
  function estConnecte() { return !!lireCookie("klassio_csrf"); }

  function apiFetch(path, options) {
    options = options || {};
    options.headers = options.headers || {};
    if (!(options.body instanceof FormData)) options.headers["Content-Type"] = "application/json";
    var methode = (options.method || "GET").toUpperCase();
    // Toute écriture porte le jeton CSRF : sans lui, le serveur la refuse (403).
    if (methode !== "GET" && methode !== "HEAD") {
      var csrf = lireCookie("klassio_csrf");
      if (csrf) options.headers["X-CSRF-Token"] = csrf;
    }
    options.credentials = "same-origin";
    return fetch(API_BASE + path, options).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (body) {
        if (res.status === 401 && document.body.dataset.page !== "connexion") {
          window.location.href = "connexion.html?expired=1";
        }
        // UNE RÉPONSE QUI N'EST PAS DU JSON NE VIENT PAS DE L'API KLASSIO.
        //
        // Le frontend est servi par un hébergeur statique, l'API par un
        // serveur ailleurs. Tant que les deux ne sont pas reliés, l'appel
        // atterrit sur la page 404 HTML de l'hébergeur — qui est une RÉPONSE,
        // pas une panne réseau : le filet ci-dessous ne se déclenche donc pas,
        // et l'écran affichait « Connexion impossible ». L'utilisateur en
        // concluait qu'il s'était trompé de mot de passe, alors qu'aucune API
        // n'avait été jointe. Même piège derrière un proxy d'entreprise ou un
        // portail captif de wifi public, qui répondent aussi du HTML.
        //
        // Un corps vide sur une réponse réussie (204) reste normal : seul le
        // couple « échec + corps illisible » signale une API absente.
        if (body === null) {
          return res.ok
            ? { ok: true, status: res.status, body: {} }
            : { ok: false, status: res.status, body: {
                error: "L'API Klassio ne répond pas à cette adresse — le service n'est pas encore relié à ce site." } };
        }
        return { ok: res.ok, status: res.status, body: body };
      });
    }).catch(function () {
      // LE SERVEUR EST INJOIGNABLE — coupure réseau, dyno endormi, API pas
      // encore déployée. `fetch` REJETTE dans ce cas, il ne renvoie pas une
      // réponse. Sans ce filet, la promesse partait en rejet non capturé :
      // le bouton restait à « Chargement… » indéfiniment et l'écran ne disait
      // rien. À Kinshasa, où la connexion tombe pour de vrai, c'est le
      // scénario ordinaire, pas le cas rare.
      //
      // On renvoie donc un échec de la MÊME FORME qu'un refus du serveur.
      // Tous les appelants font déjà « if (!res.ok) showError(res.body.error) » :
      // ils affichent le message sans avoir à être modifiés, un par un.
      // `status: 0` distingue « pas de réponse » d'un vrai code HTTP.
      return {
        ok: false,
        status: 0,
        body: { error: "Le serveur Klassio est injoignable. Vérifiez votre connexion, puis réessayez." },
      };
    });
  }

  function storeSession(body, extra) {
    try {
      // Le token n'est PAS recopié : il est dans le cookie HttpOnly. Ne restent
      // ici que des indications d'affichage (nom, rôle, portail).
      localStorage.setItem("klassio_tenant_id", body.tenant_id);
      localStorage.setItem("klassio_role", body.role);
      localStorage.setItem("klassio_name", body.name || (extra && extra.name) || "");
      if (extra && extra.school) localStorage.setItem("klassio_etablissement", extra.school);
      if (body.slug) localStorage.setItem("klassio_portal", body.slug);
    } catch (e) {}
  }

  // Menus par rôle : [icône, libellé, page]. Ceci choisit uniquement ce qui
  // s'AFFICHE — chaque page revérifie le rôle réel via /api/me et le backend
  // refuse de toute façon ce qui n'est pas autorisé.
  // Le menu porte le TRAVAIL ; les réglages personnels vivent dans le bloc
  // compte, en bas de la barre latérale (admin.js → renderAccountBlock).
  // « Abonnement » et « Paramètres » en ont donc été retirés : ils y restent
  // atteignables, ce n'est pas une fonctionnalité perdue mais déplacée.
  //
  // Règle à tenir : on ne retire du menu que ce qui reste joignable ailleurs.
  // Masquer une entrée n'a jamais protégé quoi que ce soit — l'autorisation
  // est vérifiée par le serveur, pas par l'absence d'un lien.
  var ROLE_MENUS = {
    // Direction : le menu suit les DOMAINES, pas les tables.
    //   Élèves + Classes  → une entrée (liens croisés posés dans les deux pages)
    //   Finance + Paiements → une entrée (finance.html mène déjà aux paiements)
    //   Documents → dans Établissement, où vivent les documents institutionnels
    // Chaque page absorbée reste joignable : vérifié lien par lien avant de
    // retirer l'entrée. Une page sans lien entrant est une page perdue.
    directeur: [
      ["home", "Accueil", "dashboard.html"], ["building", "Établissement", "etablissement.html"],
      ["students", "Élèves & classes", "eleves.html"],
      ["book", "Résultats", "resultats.html"], ["finance", "Finance", "finance.html"],
      ["discipline", "Discipline", "discipline.html"], ["calendar", "Calendrier", "calendrier.html"],
      ["mail", "Messages", "messages.html"], ["store", "Boutique", "boutique.html"],
      // Rapports et exports vivent dans Établissement (demande du propriétaire,
      // 08/10/2026) : ce sont des vues de l'école entière, pas un domaine
      // quotidien. Les deux pages restent ; l'onglet « Rapports » y mène.
      ["ai", "Assistant", "ia.html"],
    ],
    discipline: [
      ["home", "Aujourd'hui", "dashboard.html"], ["clock", "Pointage", "pointage.html"], ["discipline", "Discipline", "discipline.html"],
      ["students", "Élèves & classes", "eleves.html"], ["calendar", "Calendrier", "calendrier.html"],
      ["mail", "Messages", "messages.html"], ["bell", "Notifications", "notifications.html"], ["ai", "Assistant", "ia.html"],
    ],
    // Professeur : il n'a PAS d'« Accueil ». Son métier commence à ses classes,
    // et un tableau de bord générique posé devant elles était une porte de trop
    // pour la même chose — deux entrées (« Accueil » puis « Mes classes ») qui
    // menaient au même travail. « Mes classes » est donc sa page d'arrivée
    // (voir homeFor) et sa première entrée ; elle a absorbé ce que le tableau
    // de bord lui apportait vraiment (horaire du jour, file à traiter), et
    // `dashboard.html` l'y renvoie pour qu'aucun lien ancien ne meure.
    professeur: [
      ["classes", "Mes classes", "classes.html"], ["students", "Mes élèves", "eleves.html"],
      ["discipline", "Suivi", "discipline.html"], ["book", "Livres & devoirs", "ressources.html"], ["mail", "Messages", "messages.html"],
      ["calendar", "Calendrier", "calendrier.html"], ["bell", "Notifications", "notifications.html"], ["ai", "Assistant", "ia.html"],
    ],
    parent: [
      ["home", "Accueil", "dashboard.html"], ["students", "Mes enfants", "eleves.html"], ["calendar", "Calendrier", "calendrier.html"],
      ["book", "Livres & devoirs", "ressources.html"], ["mail", "Messages", "messages.html"], ["file", "Documents", "documents.html"],
      ["payments", "Frais & reçus", "paiements.html"], ["store", "Boutique", "boutique.html"], ["bell", "Notifications", "notifications.html"],
      ["ai", "Assistant", "ia.html"],
    ],
  };
  // L'administration de la plateforme n'a plus d'entrée dans le menu d'une
  // école (06/10/2026) : elle a ses propres comptes et sa propre connexion
  // (app/admin.html, backend/platform_auth.py).
  var ROLE_LABELS = { directeur: "Direction", discipline: "Directeur des disciplines", professeur: "Professeur", parent: "Parent" };

  // Les civilités ne sont pas des prénoms. Un enseignant invité sous le nom
  // « M. Jean Kabasele » était accueilli par « Bienvenue, M.. » — le premier
  // mot étant pris tel quel, point compris.
  var CIVILITES = /^(m|mr|mme|mlle|dr|pr|prof|me|rev|frere|frère|soeur|sœur|abbe|abbé)\.?$/i;
  function firstName(fullName) {
    if (!fullName) return "";
    var mots = fullName.trim().split(/\s+/).filter(function (mot) { return !CIVILITES.test(mot); });
    return mots.length ? mots[0] : fullName.trim().split(/\s+/)[0];
  }

  // ============================================================
  // Inscription — le directeur crée l'espace ; import réel ensuite.
  // Les étapes affichées sous le loader 3D reflètent l'état RÉEL de la
  // requête (une seule requête = une étape "en cours", jamais des ✓ fictifs).
  // ============================================================
  function initInscription() {
    var dots = document.querySelectorAll("#stepDots span");
    var state = { schoolName: "", analysis: null };
    wirePasswordRules(document.getElementById("passwordInput"), document.getElementById("pwRules"));

    function goStep(n) {
      ["step-account", "step-import", "step-offre", "step-reveal"].forEach(function (id, i) { document.getElementById(id).hidden = i !== n - 1; });
      dots.forEach(function (d) { d.classList.toggle("active", parseInt(d.dataset.step, 10) === n); });
      // L'offre se choisit sur la page de paiement en deux volets (07/10/2026),
      // avec l'offre et la période éventuellement choisies sur les tarifs.
      if (n === 3) { window.location.href = "offre.html" + (offreDemandee ? "?offre=" + offreDemandee + (cycleDemande === "yearly" ? "&cycle=yearly" : "") : (cycleDemande === "yearly" ? "?cycle=yearly" : "")); }
    }

    // ÉTAPE 3 — l'offre, obligatoire : il n'existe pas de mode gratuit. Une
    // offre choisie depuis la page Tarifs du site (?offre=ecole) est
    // présélectionnée ; le serveur la refuse si elle ne couvre pas l'effectif.
    var offreDemandee = (location.search.match(/[?&]offre=([a-z]+)/) || [])[1] || null;
    var cycleDemande = /[?&]cycle=yearly(&|$)/.test(location.search) ? "yearly" : "monthly";
    function chargerOffre() {
      var host = document.getElementById("offreHost");
      host.innerHTML = UI.skeleton ? UI.skeleton("card", 2) : "";
      apiFetch("/subscription").then(function (res) {
        if (!res.ok) { host.innerHTML = '<p class="form-error">' + escapeHtml(res.body.error || "Impossible de charger les offres.") + "</p>"; return; }
        window.KlassioOffres.render(host, res.body, {
          preselect: offreDemandee,
          reload: chargerOffre,
          onDeclared: function (rep) {
            // Premier paiement déclaré : le serveur ouvre l'espace le temps de
            // la vérification (72 h). Sinon, l'étape 4 dit « créé », pas « prêt ».
            if (rep && rep.provisional_until) espaceOuvertProvisoirement(rep.message);
            else espaceEnAttente();
            goStep(4);
          },
          onBypass: function () { goStep(4); },
        });
      }).catch(function () { host.innerHTML = '<p class="form-error">Le serveur Klassio est momentanément injoignable.</p>'; });
    }
    // Un paiement déclaré n'est pas un paiement confirmé : l'étape 4 dit
    // « créé », pas « prêt », et mène à l'abonnement plutôt qu'au tableau de bord.
    function espaceOuvertProvisoirement(message) {
      document.getElementById("revealTitle").textContent = "Votre espace Klassio est ouvert";
      document.getElementById("revealSummary").textContent = message || "Klassio vérifie votre paiement ; vous pouvez déjà travailler.";
    }
    function espaceEnAttente() {
      document.getElementById("revealTitle").textContent = "Votre espace Klassio est créé";
      document.getElementById("revealSummary").textContent = "Il s'ouvrira dès que Klassio aura confirmé votre paiement. Vos élèves et vos classes importés vous y attendent.";
      var go = document.getElementById("goDashboard");
      go.textContent = "Suivre mon abonnement";
      go.setAttribute("href", "abonnement.html");
    }
    function showError(id, msg) { var el = document.getElementById(id); el.textContent = msg; el.hidden = !msg; }

    document.getElementById("createSpaceBtn").addEventListener("click", function () {
      showError("accountError", "");
      var school = document.getElementById("schoolInput").value.trim();
      var name = document.getElementById("nameInput").value.trim();
      var email = document.getElementById("emailInput").value.trim();
      var password = document.getElementById("passwordInput").value;
      if (!school || !name || !email || !password) return showError("accountError", "Merci de renseigner l'établissement, votre nom, votre email et un mot de passe.");
      if (!passwordMeetsRules(password)) return showError("accountError", "Le mot de passe ne respecte pas encore toutes les règles ci-dessus.");
      var btn = document.getElementById("createSpaceBtn");
      UI.btnState(btn, "loading", "Création en cours…");
      if (window.KlassioLoader) window.KlassioLoader.show("Klassio prépare votre établissement", [
        { label: "Vérification de l'établissement", state: "doing" }, { label: "Création du compte Direction", state: "todo" }, { label: "Ouverture de votre espace", state: "todo" }]);
      apiFetch("/auth/register-school", { method: "POST", body: JSON.stringify({ email: email, password: password, name: name, school_name: school }) })
        .then(function (res) {
          if (!res.ok) { UI.btnState(btn, "idle"); if (window.KlassioLoader) window.KlassioLoader.hide(); return showError("accountError", res.body.error || "Impossible de créer l'espace pour le moment."); }
          storeSession(res.body, { name: name, school: school });
          state.schoolName = school;
          if (window.KlassioLoader) { window.KlassioLoader.setSteps([{ label: "Vérification de l'établissement", state: "done" }, { label: "Création du compte Direction", state: "done" }, { label: "Ouverture de votre espace", state: "done" }]); }
          setTimeout(function () { if (window.KlassioLoader) window.KlassioLoader.hide(); UI.btnState(btn, "idle"); goStep(2); }, 700);
        }).catch(function () { UI.btnState(btn, "idle"); if (window.KlassioLoader) window.KlassioLoader.hide(); showError("accountError", "Le serveur Klassio est momentanément injoignable. Réessayez dans un instant."); });
    });

    var fileInput = document.getElementById("fileInput");
    var dropzone = document.getElementById("importDropzone");
    ["dragenter", "dragover"].forEach(function (ev) { dropzone.addEventListener(ev, function (e) { e.preventDefault(); dropzone.classList.add("drag"); }); });
    ["dragleave", "drop"].forEach(function (ev) { dropzone.addEventListener(ev, function (e) { e.preventDefault(); dropzone.classList.remove("drag"); }); });
    dropzone.addEventListener("drop", function (e) { if (e.dataTransfer.files[0]) analyzeFile(e.dataTransfer.files[0]); });
    fileInput.addEventListener("change", function () { if (fileInput.files[0]) analyzeFile(fileInput.files[0]); });

    function analyzeFile(file) {
      showError("importError", "");
      document.getElementById("importFileLabel").textContent = "Analyse de " + file.name + "…";
      dropzone.classList.add("busy");
      if (window.KlassioLoader) window.KlassioLoader.show("Analyse de votre fichier", [
        { label: "Lecture du fichier", state: "done" }, { label: "Détection des colonnes, élèves, classes et frais", state: "doing" }, { label: "Contrôle qualité (doublons, incohérences)", state: "todo" }]);
      var form = new FormData(); form.append("file", file);
      apiFetch("/onboarding/analyze-import", { method: "POST", body: form }).then(function (res) {
        dropzone.classList.remove("busy");
        document.getElementById("importFileLabel").textContent = "Choisir un autre fichier .xlsx ou .csv";
        if (window.KlassioLoader) window.KlassioLoader.hide();
        if (!res.ok) return showError("importError", res.body.error || "Impossible d'analyser ce fichier.");
        renderAnalysis(res.body);
      }).catch(function () { dropzone.classList.remove("busy"); if (window.KlassioLoader) window.KlassioLoader.hide(); showError("importError", "Le serveur Klassio est momentanément injoignable."); });
    }

    function renderAnalysis(a) {
      state.analysis = a;
      document.getElementById("resStudents").textContent = a.students_count.toLocaleString("fr-FR");
      document.getElementById("resClasses").textContent = a.classes_count;
      document.getElementById("resGuardians").textContent = a.guardians_count.toLocaleString("fr-FR");
      document.getElementById("resColumns").textContent = a.columns_recognized + " / " + a.columns_total;
      document.getElementById("resQualityBar").style.width = a.data_quality_score + "%";
      document.getElementById("resQuality").textContent = a.data_quality_score + " %";
      document.getElementById("resDuplicates").textContent = a.duplicates.length;
      document.getElementById("resMissing").textContent = a.missing_info_count;
      document.getElementById("resAnomalies").textContent = a.anomalies.length;
      document.getElementById("feesNote").hidden = a.fees_detected;
      var mapping = Object.keys(a.mapping).map(function (k) { return a.mapping[k]; });
      // Classeur à plusieurs feuilles : dire ce que Klassio a fait de CHACUNE
      // (liste d'élèves, paiements rattachés, feuille laissée de côté et
      // pourquoi). Sans cela, l'école ne savait pas que sa feuille Classes
      // n'avait pas été lue, ni que ses paiements l'avaient été.
      var ROLES = { eleves: "Élèves", paiements: "Paiements", ignoree: "Non lue" };
      var feuilles = (a.sheets || []).length > 1 ? a.sheets.map(function (f) {
        return '<div class="map-row' + (f.role === "ignoree" ? " unmapped" : "") + '"><span class="map-src">Feuille « ' + escapeHtml(f.name) + ' »</span><span class="map-arrow">' + UI.icon("chevronRight", 14) + '</span><span class="map-dst">' + escapeHtml(ROLES[f.role] || f.role) + '</span><span class="map-conf">' + escapeHtml(f.detail || "") + "</span></div>";
      }).join("") : "";
      document.getElementById("mappingList").innerHTML = feuilles + mapping.map(function (m) {
        var ok = m.field !== "unmapped";
        return '<div class="map-row' + (ok ? "" : " unmapped") + '"><span class="map-src">' + escapeHtml(m.header) + '</span><span class="map-arrow">' + UI.icon("chevronRight", 14) + '</span><span class="map-dst">' + escapeHtml(m.label) + '</span><span class="map-conf">' + Math.round(m.confidence * 100) + ' %</span></div>';
      }).join("");
      var ou = function (x) { return (x.sheet ? "Feuille « " + x.sheet + " », ligne " : "Ligne ") + x.row; };
      var issues = a.duplicates.map(function (d) { return ou(d) + " — doublon potentiel : " + d.name + " (déjà vu " + (d.sheet ? "" : "ligne ") + d.first_seen_row + ")"; })
        .concat(a.anomalies.map(function (x) { return ou(x) + " — " + x.name + " : " + x.issue; }));
      var panel = document.getElementById("anomaliesPanel");
      panel.hidden = !issues.length;
      document.getElementById("anomaliesList").innerHTML = issues.slice(0, 15).map(function (t) { return "<div>" + UI.icon("alert", 13) + escapeHtml(t) + "</div>"; }).join("") +
        (issues.length > 15 ? '<div class="muted">… et ' + (issues.length - 15) + " autre(s)</div>" : "");
      document.getElementById("previewBody").innerHTML = a.preview_records.map(function (r) {
        return "<tr><td>" + escapeHtml(r.last_name + " " + r.first_name) + "</td><td>" + escapeHtml(r.class_name) + "</td><td>" + escapeHtml(r.guardian_name || r.guardian_phone || "—") +
               "</td><td>" + (r.fee_amount == null ? "—" : UI.money(r.fee_amount)) + "</td><td>" + UI.money(r.paid_amount) + "</td></tr>";
      }).join("");
      document.getElementById("analysisResult").hidden = false;
      document.getElementById("importSkipRow").hidden = true;
    }

    document.getElementById("reAnalyzeBtn").addEventListener("click", function () {
      state.analysis = null; fileInput.value = "";
      document.getElementById("analysisResult").hidden = true; document.getElementById("importSkipRow").hidden = false;
    });

    document.getElementById("confirmImportBtn").addEventListener("click", function () {
      if (!state.analysis) return;
      var btn = document.getElementById("confirmImportBtn");
      UI.btnState(btn, "loading", "Import en cours…");
      var a = state.analysis;
      if (window.KlassioLoader) window.KlassioLoader.show("Klassio construit votre établissement", [
        { label: "Fichier analysé — " + a.students_count + " élèves, " + a.classes_count + " classes", state: "done" },
        { label: "Création des classes et des dossiers élèves", state: "doing" },
        { label: "Rattachement des responsables", state: "todo" },
        { label: "Préparation de la structure financière", state: "todo" },
        { label: "Finalisation de l'espace", state: "todo" }]);
      apiFetch("/onboarding/confirm-import", { method: "POST", body: JSON.stringify({ import_session_id: a.import_session_id, school_name: state.schoolName }) })
        .then(function (res) {
          if (!res.ok) { UI.btnState(btn, "idle"); if (window.KlassioLoader) window.KlassioLoader.hide(); return showError("importError", res.body.error || "Impossible d'importer ces données."); }
          var r = res.body;
          if (window.KlassioLoader) window.KlassioLoader.setSteps([
            { label: "Fichier analysé", state: "done" }, { label: r.students_count + " dossiers élèves et " + r.classes_count + " classes créés", state: "done" },
            { label: r.guardians_count + " responsables rattachés", state: "done" }, { label: r.obligations_count + " obligations et " + r.payments_count + " paiements intégrés", state: "done" },
            { label: "Données intégrées à votre espace", state: "done" }]);
          document.getElementById("revealSummary").textContent = r.message;
          setTimeout(function () { if (window.KlassioLoader) window.KlassioLoader.hide(); UI.btnState(btn, "idle"); goStep(3); }, 900);
        }).catch(function () { UI.btnState(btn, "idle"); if (window.KlassioLoader) window.KlassioLoader.hide(); showError("importError", "Le serveur Klassio est momentanément injoignable."); });
    });

    document.getElementById("skipImportBtn").addEventListener("click", function () {
      document.getElementById("revealSummary").textContent = "Vous pourrez importer un fichier ou ajouter vos élèves à tout moment depuis Élèves.";
      goStep(3);
    });
    // L'import (ou son report) mène à l'OFFRE, étape 3 — plus directement à
    // l'espace : on ne l'ouvre qu'une fois l'offre choisie et payée.

    var revealObserver = new MutationObserver(function () {
      var step = document.getElementById("step-reveal");
      if (step.hidden) return;
      var name = "", school = "";
      try { name = localStorage.getItem("klassio_name") || ""; school = localStorage.getItem("klassio_etablissement") || ""; } catch (e) {}
      document.getElementById("miniSidebar").innerHTML = ROLE_MENUS.directeur.slice(0, 7).map(function (item, i) {
        return '<div class="m-item' + (i === 0 ? " active" : "") + '">' + UI.icon(item[0], 14) + item[1] + "</div>";
      }).join("");
      document.getElementById("miniGreeting").textContent = "Bienvenue" + (name ? ", " + firstName(name) : "") + ".";
      document.getElementById("miniSchoolName").textContent = school;
    });
    revealObserver.observe(document.getElementById("step-reveal"), { attributes: true, attributeFilter: ["hidden"] });
    var miniToggle = document.getElementById("miniToggle"), miniSidebar = document.getElementById("miniSidebar");
    miniToggle.addEventListener("click", function () { miniSidebar.classList.toggle("shown"); miniToggle.classList.toggle("shifted", miniSidebar.classList.contains("shown")); });
  }

  // ============================================================
  // Connexion
  // ============================================================
  function initConnexion() {
    var btn = document.getElementById("loginBtn"), errorEl = document.getElementById("loginError");
    if (UI.qs("expired")) { errorEl.textContent = "Votre session a expiré — reconnectez-vous."; errorEl.hidden = false; }
    // Un utilisateur qui connaît déjà son établissement est renvoyé vers le portail de celui-ci.
    var known = null; try { known = localStorage.getItem("klassio_portal"); } catch (e) {}
    var portalHint = document.getElementById("portalHint");
    if (known && portalHint) { portalHint.innerHTML = 'Votre établissement : <a class="link-btn" href="portail.html?e=' + encodeURIComponent(known) + '">ouvrir son portail</a>'; portalHint.hidden = false; }
    function submit() {
      errorEl.hidden = true;
      var email = document.getElementById("loginEmail").value.trim(), password = document.getElementById("loginPassword").value;
      if (!email || !password) { errorEl.textContent = "Merci de renseigner votre email ou votre numéro, et votre mot de passe."; errorEl.hidden = false; return; }
      UI.btnState(btn, "loading", "Connexion…");
      apiFetch("/auth/login", { method: "POST", body: JSON.stringify({ identifier: email, password: password }) }).then(function (res) {
        if (!res.ok) { UI.btnState(btn, "idle"); errorEl.textContent = res.body.error || "Connexion impossible."; errorEl.hidden = false; return; }
        storeSession(res.body);
        UI.btnState(btn, "success", "Connecté");
        // « J'ai déjà un compte » depuis les tarifs : la Direction reprend son
        // choix sur la page de paiement. Seule valeur acceptée : « offre »
        // (jamais une adresse fournie par le lien — pas de redirection ouverte).
        if (UI.qs("suite") === "offre" && res.body.role === "directeur") {
          var o = (UI.qs("offre") || "").replace(/[^a-z]/g, "");
          window.location.href = "offre.html?" + (o ? "offre=" + o + "&" : "") + (UI.qs("cycle") === "yearly" ? "cycle=yearly" : "cycle=monthly");
          return;
        }
        window.location.href = UI.homeFor(res.body.role);
      }).catch(function () { UI.btnState(btn, "idle"); errorEl.textContent = "Le serveur Klassio est momentanément injoignable. Réessayez dans un instant."; errorEl.hidden = false; });
    }
    btn.addEventListener("click", submit);
    document.getElementById("loginPassword").addEventListener("keydown", function (e) { if (e.key === "Enter") submit(); });
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (document.body.dataset.page === "inscription") initInscription();
    if (document.body.dataset.page === "connexion") initConnexion();
  });

  window.KlassioApi = {
    fetch: apiFetch, roleMenus: ROLE_MENUS, roleLabels: ROLE_LABELS, firstName: firstName,
    passwordMeetsRules: passwordMeetsRules, wirePasswordRules: wirePasswordRules, storeSession: storeSession, estConnecte: estConnecte,
    // Origine de l'API, pour les rares appels qui ne passent pas par
    // apiFetch — un téléchargement de fichier, qui doit lire un blob et non
    // du JSON. Le cookie de session part de lui-même (même origine).
    base: API_BASE,
    homeFor: UI.homeFor,
  };
})();
