// KLASSIO — Données & exports.
//
// L'écran ne décide de rien : chaque état affiché vient du serveur. « Prêt »
// s'affiche parce que le backend a écrit READY, jamais parce qu'un bouton a
// été cliqué. Un export qui échoue le dit, avec la possibilité de recommencer.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var annees = [], historique = [], ctx = null;

  var RAPIDES = [
    ["students", "Élèves", "students"],
    ["classes", "Classes", "grid"],
    ["teachers", "Enseignants", "users"],
    ["results", "Résultats", "book"],
    ["attendance", "Présences", "clock"],
    ["discipline", "Discipline", "discipline"],
    ["obligations", "Frais scolaires", "finance"],
    ["payments", "Paiements", "finance"],
    ["receipts", "Reçus", "receipt"],
    ["guardians", "Responsables", "users"],
  ];

  function octets(n) {
    if (!n) return "—";
    if (n < 1024) return n + " o";
    if (n < 1024 * 1024) return Math.round(n / 1024) + " Ko";
    return (n / 1048576).toFixed(1) + " Mo";
  }

  function etatBadge(statut) {
    // UI.badge(status, label) — dans cet ordre. Inversé, il affichait « ok »
    // à la place de « Prêt » : le libellé partait dans le paramètre de style.
    var libelle = {
      READY: "Prêt", PROCESSING: "En cours", FAILED: "Échec",
      EXPIRED: "Expiré", CREATED: "En attente",
    }[statut] || statut;
    return UI.badge(statut, libelle);
  }

  function rendu() {
    var optionsAnnees = annees.map(function (a) {
      return '<option value="' + a.id + '"' + (a.is_active ? " selected" : "") + ">"
        + UI.escapeHtml(a.label) + "</option>";
    }).join("");

    var rapides = RAPIDES.map(function (r) {
      return '<button type="button" class="btn btn-ghost btn-sm" data-export="' + r[0] + '">'
        + UI.icon(r[2], 14) + UI.escapeHtml(r[1]) + "</button>";
    }).join(" ");

    var lignes = historique.length ? historique.map(function (e) {
      var peutTelecharger = e.status === "READY";
      return "<tr><td>" + UI.escapeHtml(e.year_label || "—") + "</td>"
        + "<td>" + UI.escapeHtml(e.kind === "annual" ? "Année complète" : e.kind) + "</td>"
        + "<td>" + UI.fmtDateTime(e.created_at) + "</td>"
        + "<td>" + UI.escapeHtml(e.requested_by_name || "—") + "</td>"
        + "<td>" + octets(e.file_size) + "</td>"
        + "<td>" + etatBadge(e.status) + "</td>"
        + '<td class="right">' + (peutTelecharger
            ? '<button type="button" class="btn btn-ghost btn-sm" data-dl="' + e.id + '">Télécharger</button>'
            : '<span class="muted" style="font-size:12.5px">—</span>') + "</td></tr>";
    }).join("") : '<tr><td colspan="7" class="muted" style="padding:18px 0">Aucun export pour le moment.</td></tr>';

    document.getElementById("exportContent").innerHTML =
      '<div class="panel"><div class="panel-head"><h2>Exporter l\'année complète</h2>'
      + '<span class="sub">Une archive ZIP contenant un classeur par type de données, plus un manifeste qui dit ce qu\'elle contient.</span></div>'
      + '<div class="row" style="gap:10px;flex-wrap:wrap">'
      + '<select id="anneeSel" style="min-width:220px">' + optionsAnnees + "</select>"
      + '<button type="button" class="btn btn-lime btn-sm" id="annuelBtn">' + UI.icon("download", 15) + "Générer l'archive</button>"
      + "</div>"
      + '<p class="form-msg" id="exportMsg" style="margin-top:10px"></p></div>'

      + '<div class="panel" style="margin-top:16px"><div class="panel-head"><h2>Exports rapides</h2>'
      + '<span class="sub">Un seul type de données, pour l\'année sélectionnée ci-dessus.</span></div>'
      + '<div class="row" style="gap:8px;flex-wrap:wrap">' + rapides + "</div></div>"

      + '<div class="panel" style="margin-top:16px"><div class="panel-head"><h2>Historique</h2>'
      + '<span class="sub">Les archives sont conservées 7 jours sur le serveur ; la trace de l\'export, elle, reste.</span></div>'
      + '<div class="table-wrap"><table class="table"><thead><tr><th>Année</th><th>Type</th><th>Date</th>'
      + "<th>Demandé par</th><th>Taille</th><th>État</th><th></th></tr></thead><tbody>"
      + lignes + "</tbody></table></div></div>";
    cabler();
  }

  function lancer(kind, bouton) {
    var msg = document.getElementById("exportMsg");
    var sel = document.getElementById("anneeSel");
    var payload = { kind: kind };
    if (sel && sel.value) payload.academic_year_id = sel.value;
    if (bouton) UI.btnState(bouton, "loading", "Génération…");
    msg.textContent = "Préparation de l'archive…"; msg.className = "form-msg";

    api.fetch("/exports", { method: "POST", body: JSON.stringify(payload) }).then(function (res) {
      if (!res.ok || res.body.status !== "READY") {
        if (bouton) UI.btnState(bouton, "error", "Échec");
        msg.textContent = (res.body && res.body.error) || "La génération a échoué.";
        msg.className = "form-msg error";
        return;
      }
      if (bouton) UI.btnState(bouton, "success", "Prêt");
      var total = Object.keys(res.body.counts || {}).reduce(function (s, k) { return s + res.body.counts[k]; }, 0);
      var texte = "Archive prête — " + total + " ligne(s), " + octets(res.body.file_size)
        + ". Le téléchargement démarre.";
      telecharger(res.body.id);
      // `recharger()` réécrit tout le panneau, y compris ce message. On le
      // repose APRÈS le rendu, sinon la Direction ne voit jamais la
      // confirmation de ce qu'elle vient de faire.
      recharger().then(function () {
        var apres = document.getElementById("exportMsg");
        if (apres) { apres.textContent = texte; apres.className = "form-msg ok"; }
      });
    });
  }

  function telecharger(id) {
    // Le téléchargement porte le jeton : la route revérifie l'établissement.
    // On passe par fetch plutôt qu'un lien direct, sinon l'en-tête
    // d'authentification ne serait pas envoyé.
    fetch(api.base + "/exports/" + id + "/download", {
      headers: { Authorization: "Bearer " + api.getToken() },
    }).then(function (r) {
      if (!r.ok) throw new Error("refus");
      var nom = "export.zip";
      var cd = r.headers.get("Content-Disposition") || "";
      var m = /filename="?([^"]+)"?/.exec(cd);
      if (m) nom = m[1];
      return r.blob().then(function (b) {
        var url = URL.createObjectURL(b);
        var a = document.createElement("a");
        a.href = url; a.download = nom; document.body.appendChild(a); a.click();
        document.body.removeChild(a); URL.revokeObjectURL(url);
      });
    }).catch(function () {
      var msg = document.getElementById("exportMsg");
      msg.textContent = "L'archive n'a pas pu être téléchargée. Elle a peut-être expiré — relancez l'export.";
      msg.className = "form-msg error";
    });
  }

  function recharger() {
    return api.fetch("/exports").then(function (r) {
      historique = (r.ok && r.body) || [];
      rendu();
    });
  }

  function cabler() {
    var b = document.getElementById("annuelBtn");
    if (b) b.addEventListener("click", function () { lancer("annual", b); });
    document.querySelectorAll("[data-export]").forEach(function (el) {
      el.addEventListener("click", function () { lancer(el.dataset.export, el); });
    });
    document.querySelectorAll("[data-dl]").forEach(function (el) {
      el.addEventListener("click", function () { telecharger(el.dataset.dl); });
    });
  }

  admin.initShell("exports").then(function (c) {
    ctx = c;
    if (ctx.role !== "directeur") {
      document.getElementById("exportContent").innerHTML = UI.emptyState(
        "Réservé à la Direction",
        "Exporter les données de l'établissement est un acte distinct de leur consultation.",
        '<a href="' + UI.homeFor(ctx.role) + '" class="btn btn-ghost btn-sm">Retour à l\'accueil</a>', "lock");
      return;
    }
    Promise.all([
      api.fetch("/academic-years").then(function (r) { annees = (r.ok && r.body) || []; }),
      api.fetch("/exports").then(function (r) { historique = (r.ok && r.body) || []; }),
    ]).then(rendu);
  });
})();
