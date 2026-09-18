// KLASSIO — Résultats officiels (Direction) : import, aperçu, confirmation.
//
// Trois règles gouvernent ce fichier.
//
// 1. LE BACKEND DÉCIDE. Les compteurs affichés — lignes rapprochées, erreurs,
//    version proposée — viennent tous de la réponse serveur. Cette page ne
//    calcule aucun de ces chiffres et n'en renvoie aucun : la confirmation
//    n'envoie que l'identifiant de la session d'import.
//
// 2. AUCUN SUCCÈS SIMULÉ. Le chargement dure exactement le temps de la requête.
//    Il n'y a dans ce fichier aucun `setTimeout` qui fasse semblant qu'un
//    traitement avance — l'animation réutilisée est celle de l'import des
//    élèves (KlassioLoader), pilotée par les vraies transitions.
//
// 3. IMPORTER N'EST PAS PUBLIER. L'écran de succès le dit explicitement, et
//    renvoie vers Établissement pour la proclamation.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;

  var ctx = null;
  var periodes = [];
  var analyse = null;        // session d'import renvoyée par le serveur
  var enCours = false;       // garde anti-double-soumission
  var dernierFichier = null; // rejoué tel quel par « Réessayer »

  var hote = function () { return document.getElementById("resultsContent"); };

  admin.initShell("resultats").then(function (c) {
    ctx = c;
    if (c.role !== "directeur") {
      // La règle est appliquée par le serveur ; cet écran évite simplement de
      // proposer une action qui sera refusée.
      hote().innerHTML = UI.emptyState(
        "Import réservé à la Direction",
        "Seule la Direction importe les résultats officiels de l'établissement.",
        '<a href="dashboard.html" class="btn btn-ghost btn-sm">Retour</a>', "lock");
      return;
    }
    charger();
  });

  // --------------------------------------------------------------------
  // Chargement : périodes disponibles + historique des imports
  // --------------------------------------------------------------------
  function charger() {
    hote().innerHTML = UI.skeleton("card", 2);
    Promise.all([api.fetch("/periods"), api.fetch("/results/imports")]).then(function (r) {
      if (!r[0].ok) return admin.loadError(hote(), charger, "Périodes indisponibles");
      periodes = (r[0].body.periods || []);
      var historique = r[1].ok ? r[1].body : [];
      rendre(historique);
    });
  }

  function rendre(historique) {
    hote().innerHTML = panneauImport() + panneauHistorique(historique);
    brancherDepot();
    UI.wireHrefs(hote());
  }

  function panneauImport() {
    if (!periodes.length) {
      return '<div class="panel">' + UI.emptyState(
        "Aucune période déclarée",
        "Un résultat officiel appartient toujours à une période. Déclarez d'abord votre calendrier " +
        "académique depuis Établissement.",
        '<a href="etablissement.html?tab=periodes" class="btn btn-accent btn-sm">Configurer les périodes</a>',
        "calendar") + "</div>";
    }
    // Une période verrouillée n'accepte plus de résultats : le serveur refuse,
    // et on ne la propose donc pas.
    var ouvertes = periodes.filter(function (p) { return p.state !== "LOCKED" && p.state !== "ARCHIVED"; });
    if (!ouvertes.length) {
      return '<div class="panel">' + UI.emptyState(
        "Toutes vos périodes sont verrouillées",
        "Rouvrez une période depuis Établissement pour y importer des résultats.",
        '<a href="etablissement.html?tab=periodes" class="btn btn-ghost btn-sm">Voir les périodes</a>',
        "lock") + "</div>";
    }
    return '<div class="panel" id="importPanel">' +
      '<div class="panel-head"><h2>Importer des résultats officiels</h2></div>' +
      '<p class="muted" style="margin-bottom:14px">Votre établissement calcule ses résultats avec ses ' +
        'propres outils. Déposez ici le fichier Excel ou CSV : Klassio rapproche chaque ligne de vos ' +
        'élèves, signale ce qui ne correspond pas, et n\'écrit rien avant votre validation.</p>' +
      '<div class="field" style="max-width:420px">' +
        '<label for="periodSelect">Période concernée</label>' +
        '<select id="periodSelect">' + ouvertes.map(function (p) {
          return '<option value="' + UI.escapeHtml(p.id) + '">' + UI.escapeHtml(p.label) +
                 (p.division ? " — " + UI.escapeHtml(p.division) : "") + "</option>";
        }).join("") + "</select>" +
      "</div>" +
      // Structure identique à l'import des élèves : un <label for> ouvre le
      // sélecteur nativement — sans JS, et accessible au clavier.
      '<label class="import-card" id="resultsDropzone" for="resultsFile" style="margin-top:14px">' +
        '<span class="import-ic"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" ' +
          'stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">' +
          '<path d="M12 16V4M6 10l6-6 6 6M4 20h16"/></svg></span>' +
        '<span class="import-text">' +
          '<span class="import-title" id="resultsFileLabel">Choisir ou déposer un fichier .xlsx ou .csv</span>' +
          '<span class="import-sub">Identifiant de l\'élève, matière, résultat — les intitulés exacts ' +
            'n\'ont pas d\'importance, Klassio reconnaît les colonnes</span>' +
        "</span>" +
        '<span class="import-arrow">→</span>' +
      "</label>" +
      '<input type="file" id="resultsFile" accept=".xlsx,.csv" hidden />' +
      '<p class="form-error" id="importError" hidden role="alert"></p>' +
      '<div id="analysisHost"></div>' +
      "</div>";
  }

  function panneauHistorique(imports) {
    var lignes = (imports || []).map(function (i) {
      var etat = i.status === "confirmed" ? UI.badge("ok", "Importé")
        : i.status === "cancelled" ? UI.badge("neutral", "Annulé")
        : UI.badge("warn", "Non confirmé");
      return "<tr><td data-label=\"Date\">" + UI.fmtDateTime(i.confirmed_at || i.created_at) + "</td>" +
        '<td data-label="Fichier"><span class="cell-main">' + UI.escapeHtml(i.file_name || "—") + "</span></td>" +
        '<td data-label="Période">' + UI.escapeHtml(i.period_label || "—") + "</td>" +
        '<td data-label="Lignes" class="num">' + i.rows_matched + " / " + i.rows_total + "</td>" +
        '<td data-label="Par">' + UI.escapeHtml(i.created_by_name || "—") + "</td>" +
        '<td data-label="État">' + etat + "</td></tr>";
    }).join("");
    return '<div class="panel" id="historyPanel"><div class="panel-head"><h2>Imports précédents</h2></div>' +
      (lignes
        ? '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Date</th><th>Fichier</th>' +
          "<th>Période</th><th class=\"num\">Rapprochées</th><th>Par</th><th>État</th></tr></thead>" +
          "<tbody>" + lignes + "</tbody></table></div>"
        : '<p class="muted">Aucun import de résultats pour le moment.</p>') +
      "</div>";
  }

  // --------------------------------------------------------------------
  // Dépôt du fichier → analyse serveur
  // --------------------------------------------------------------------
  function brancherDepot() {
    var zone = document.getElementById("resultsDropzone");
    var input = document.getElementById("resultsFile");
    if (!zone || !input) return;
    ["dragenter", "dragover"].forEach(function (ev) {
      zone.addEventListener(ev, function (e) { e.preventDefault(); zone.classList.add("drag"); });
    });
    ["dragleave", "drop"].forEach(function (ev) {
      zone.addEventListener(ev, function (e) { e.preventDefault(); zone.classList.remove("drag"); });
    });
    zone.addEventListener("drop", function (e) {
      if (e.dataTransfer.files[0]) analyser(e.dataTransfer.files[0]);
    });
    input.addEventListener("change", function () { if (input.files[0]) analyser(input.files[0]); });
  }

  function erreur(message) {
    var el = document.getElementById("importError");
    if (!el) return;
    el.textContent = message;
    el.hidden = !message;
  }

  function analyser(fichier) {
    if (enCours) return;
    enCours = true;
    dernierFichier = fichier;
    erreur("");
    var select = document.getElementById("periodSelect");
    var periodId = select ? select.value : "";
    document.getElementById("resultsFileLabel").textContent = "Analyse de " + fichier.name + "…";
    document.getElementById("resultsDropzone").classList.add("busy");
    document.getElementById("analysisHost").innerHTML = "";

    // Même animation que l'import des élèves. Les étapes décrivent ce qui se
    // passe réellement côté serveur ; aucune ne « progresse » toute seule.
    if (window.KlassioLoader) window.KlassioLoader.show("Analyse de vos résultats", [
      { label: "Lecture du fichier", state: "doing" },
      { label: "Rapprochement avec vos élèves", state: "todo" },
      { label: "Contrôle des notes et des doublons", state: "todo" }]);

    var form = new FormData();
    form.append("file", fichier);
    form.append("period_id", periodId);

    api.fetch("/results/imports", { method: "POST", body: form }).then(function (res) {
      enCours = false;
      document.getElementById("resultsDropzone").classList.remove("busy");
      document.getElementById("resultsFileLabel").textContent = "Choisir un autre fichier .xlsx ou .csv";
      if (window.KlassioLoader) window.KlassioLoader.hide();
      if (!res.ok) {
        analyse = null;
        return erreur((res.body && res.body.error) || "Impossible d'analyser ce fichier.");
      }
      analyse = res.body;
      rendreAnalyse(analyse);
    }).catch(function () {
      enCours = false;
      document.getElementById("resultsDropzone").classList.remove("busy");
      if (window.KlassioLoader) window.KlassioLoader.hide();
      erreur("Le serveur Klassio est injoignable. Votre fichier n'a pas été analysé — réessayez.");
    });
  }

  // --------------------------------------------------------------------
  // Aperçu : ce que la Direction doit comprendre AVANT de confirmer
  // --------------------------------------------------------------------
  function rendreAnalyse(a) {
    var bloquant = a.blocking;
    var absents = a.students_without_result || [];

    var kpis = '<div class="kpi-grid">' +
      UI.kpi("Lignes lues", String(a.total_rows), { icon: "file" }) +
      UI.kpi("Rapprochées", String(a.matched), { icon: "students", tone: a.matched ? "ok" : "warn" }) +
      UI.kpi("À vérifier", String(a.warnings), { icon: "alert", tone: a.warnings ? "warn" : "" }) +
      UI.kpi("Erreurs", String(a.errors), { icon: "alert", tone: a.errors ? "bad" : "ok" }) +
      "</div>";

    var alerte = "";
    if (bloquant) {
      alerte = '<div class="notice bad" role="alert"><strong>' + a.errors +
        " ligne(s) en erreur — l'import est bloqué.</strong> Klassio n'importe jamais un résultat " +
        "ambigu. Corrigez le fichier, puis déposez-le à nouveau.</div>";
    } else if (a.warnings) {
      alerte = '<div class="notice warn"><strong>' + a.warnings + " ligne(s) à vérifier.</strong> " +
        "L'import reste possible, mais relisez-les ci-dessous.</div>";
    }

    // Les élèves absents du fichier : dits explicitement, jamais transformés en zéro.
    var manquants = absents.length
      ? '<div class="notice warn"><strong>' + absents.length + " élève(s) de cette année ne figurent pas " +
        "dans le fichier.</strong> Ils ne recevront <em>aucun</em> résultat pour cette période — ce n'est " +
        "pas un zéro.<div class=\"chips\" style=\"margin-top:8px\">" +
        absents.slice(0, 20).map(function (e) {
          return '<span class="chip">' + UI.escapeHtml(e.name) +
                 (e.class_name ? " · " + UI.escapeHtml(e.class_name) : "") + "</span>";
        }).join("") +
        (absents.length > 20 ? '<span class="chip">… et ' + (absents.length - 20) + " autre(s)</span>" : "") +
        "</div></div>"
      : "";

    var problemes = (a.problems || []);
    var listeProblemes = problemes.length
      ? '<div class="panel-head" style="margin-top:16px"><h2>Lignes à corriger</h2></div>' +
        '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th class="num">Ligne</th>' +
        "<th>Élève</th><th>Matière</th><th>Problème</th></tr></thead><tbody>" +
        problemes.map(function (l) {
          var ton = l.severity === "error" ? "bad" : "warn";
          return '<tr><td data-label="Ligne" class="num">' + l.row + "</td>" +
            '<td data-label="Élève"><span class="cell-main">' +
              UI.escapeHtml(l.matched_name || l.student_name || "—") + "</span>" +
              (l.student_code ? '<span class="cell-sub">' + UI.escapeHtml(l.student_code) + "</span>" : "") +
            "</td>" +
            '<td data-label="Matière">' + UI.escapeHtml(l.subject || "—") + "</td>" +
            '<td data-label="Problème">' + UI.badge(ton, l.severity === "error" ? "Erreur" : "À vérifier") +
              " " + UI.escapeHtml((l.issues || []).join(" · ")) + "</td></tr>";
        }).join("") + "</tbody></table></div>"
      : "";

    var mapping = (a.mapping || []).filter(function (m) { return m.field !== "unmapped"; });
    var ignorees = (a.mapping || []).filter(function (m) { return m.field === "unmapped"; });
    var blocMapping = '<div class="panel-head" style="margin-top:16px"><h2>Colonnes reconnues</h2></div>' +
      '<div>' + mapping.map(function (m) {
        return '<div class="map-row"><span class="map-src">' + UI.escapeHtml(m.header) + "</span>" +
          '<span class="map-arrow">' + UI.icon("chevronRight", 14) + "</span>" +
          '<span class="map-dst">' + UI.escapeHtml(m.label) + "</span></div>";
      }).join("") +
      (ignorees.length
        ? '<p class="muted" style="margin-top:8px">Colonnes ignorées : ' +
          ignorees.map(function (m) { return UI.escapeHtml(m.header); }).join(", ") + "</p>"
        : "") + "</div>";

    var remplacement = a.next_version > 1
      ? '<div class="notice warn"><strong>Version ' + a.next_version + ".</strong> Des résultats existent " +
        "déjà pour cette période. Ils seront remplacés comme version courante — " +
        "l'ancienne version reste consultable, rien n'est supprimé.</div>"
      : "";

    var resume = '<p class="wx-note" style="margin-top:14px">Vous êtes sur le point d\'importer <strong>' +
      a.matched + " résultat(s)</strong> pour <strong>" + a.students_in_file + " élève(s)</strong>, " +
      "période <strong>" + UI.escapeHtml(a.period_label || "—") + "</strong>.</p>";

    document.getElementById("analysisHost").innerHTML =
      '<div class="panel-head" style="margin-top:20px"><h2>Aperçu — ' +
        UI.escapeHtml(a.file_name || "fichier") + "</h2></div>" +
      kpis + alerte + manquants + remplacement + blocMapping + listeProblemes +
      (bloquant ? "" : resume) +
      '<p class="form-error" id="confirmError" hidden role="alert"></p>' +
      '<div class="row" style="margin-top:14px;gap:8px;flex-wrap:wrap">' +
        (bloquant
          ? '<button type="button" class="btn btn-ghost btn-sm" id="cancelImportBtn">Abandonner cet import</button>'
          : '<button type="button" class="btn btn-accent" id="confirmImportBtn">Importer ces résultats</button>' +
            '<button type="button" class="btn btn-ghost btn-sm" id="cancelImportBtn">Abandonner</button>') +
      "</div>" +
      '<p class="wx-note">Importer ne publie rien : les parents ne verront ces résultats qu\'après ' +
        "proclamation de la période.</p>";

    var confirmer = document.getElementById("confirmImportBtn");
    if (confirmer) confirmer.addEventListener("click", lancerConfirmation);
    var annuler = document.getElementById("cancelImportBtn");
    if (annuler) annuler.addEventListener("click", abandonner);
  }

  // --------------------------------------------------------------------
  // Confirmation — écriture réelle
  // --------------------------------------------------------------------
  function lancerConfirmation() {
    if (enCours || !analyse) return;
    enCours = true;
    var bouton = document.getElementById("confirmImportBtn");
    var err = document.getElementById("confirmError");
    if (err) err.hidden = true;
    UI.btnState(bouton, "loading", "Import en cours…");
    if (window.KlassioLoader) window.KlassioLoader.show("Enregistrement des résultats officiels", [
      { label: "Fichier analysé — " + analyse.matched + " résultat(s)", state: "done" },
      { label: "Écriture des résultats", state: "doing" },
      { label: "Conservation des versions précédentes", state: "todo" }]);

    // Le corps ne contient AUCUN compteur : le serveur relit sa propre session.
    api.fetch("/results/imports/" + analyse.import_id + "/confirm",
              { method: "POST", body: JSON.stringify({}) })
      .then(function (res) {
        enCours = false;
        if (window.KlassioLoader) window.KlassioLoader.hide();
        if (!res.ok) {
          UI.btnState(bouton, "idle");
          if (err) {
            err.textContent = (res.body && res.body.error) || "L'import n'a pas pu être finalisé.";
            err.hidden = false;
          }
          return;
        }
        UI.btnState(bouton, "idle");
        rendreSucces(res.body);
      })
      .catch(function () {
        enCours = false;
        if (window.KlassioLoader) window.KlassioLoader.hide();
        UI.btnState(bouton, "idle");
        if (err) {
          // On ne sait pas si le serveur a écrit : on le dit, et on renvoie
          // vers l'état réel plutôt que d'inviter à un réessai aveugle.
          err.textContent = "Le serveur est injoignable. L'import a peut-être abouti — " +
            "rechargez la page pour voir son état réel avant de recommencer.";
          err.hidden = false;
        }
      });
  }

  function rendreSucces(r) {
    document.getElementById("analysisHost").innerHTML =
      '<div class="notice ok" style="margin-top:20px"><strong>' + r.results_written +
        " résultat(s) importés</strong> pour la période « " + UI.escapeHtml(r.period_label) +
        " » — version " + r.version + ".</div>" +
      '<div class="notice warn"><strong>Ces résultats ne sont pas encore publiés.</strong> ' +
        "Les parents ne les verront qu'après proclamation de la période, qui reste une décision " +
        "distincte.</div>" +
      '<div class="row" style="margin-top:14px;gap:8px;flex-wrap:wrap">' +
        '<a href="etablissement.html?tab=periodes" class="btn btn-accent btn-sm">Aller proclamer la période</a>' +
        '<button type="button" class="btn btn-ghost btn-sm" id="newImportBtn">Importer un autre fichier</button>' +
      "</div>";
    analyse = null;
    document.getElementById("newImportBtn").addEventListener("click", charger);
    UI.toast("Résultats importés — non publiés.", "success");
    // L'historique affichait encore « Non confirmé » juste sous le message de
    // succès : il est rendu avant la confirmation. On le relit plutôt que de
    // recharger toute la page, pour ne pas effacer le récapitulatif.
    rafraichirHistorique();
  }

  function rafraichirHistorique() {
    api.fetch("/results/imports").then(function (r) {
      var panneau = document.getElementById("historyPanel");
      if (!r.ok || !panneau) return;
      var remplacant = document.createElement("div");
      remplacant.innerHTML = panneauHistorique(r.body);
      panneau.replaceWith(remplacant.firstChild);
    });
  }

  function abandonner() {
    if (!analyse) { charger(); return; }
    var id = analyse.import_id;
    analyse = null;
    api.fetch("/results/imports/" + id + "/cancel", { method: "POST", body: JSON.stringify({}) })
      .then(charger);
  }
})();
