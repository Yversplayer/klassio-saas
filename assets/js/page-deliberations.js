// KLASSIO — Délibérations.
//
// L'écran réunit ce que le conseil doit voir et rien de plus. Il ne conclut
// jamais : les pastilles disent « à examiner », pas « à faire redoubler », et
// aucun bouton ne propose de décision par défaut. La case Décision reste vide
// tant qu'une personne habilitée ne l'a pas remplie.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var ctx = null, annees = [], classes = [], periodes = [], seances = [];
  var courante = null, filtre = "tous";

  var PASTILLE = { ok: ["ok", "OK"], attention: ["warn", "À surveiller"], examiner: ["error", "À examiner"] };

  function pastille(sig) {
    var p = PASTILLE[sig.niveau] || PASTILLE.ok;
    var titre = sig.motif ? ' title="' + UI.escapeHtml(sig.motif) + '"' : "";
    return '<span class="badge ' + p[0] + '"' + titre + ">" + p[1] + "</span>";
  }

  // ---- Liste des séances ----------------------------------------------
  function rendreListe() {
    var optAnnees = annees.map(function (a) {
      return '<option value="' + a.id + '"' + (a.is_active ? " selected" : "") + ">" + UI.escapeHtml(a.label) + "</option>";
    }).join("");
    var optClasses = classes.map(function (c) {
      return '<option value="' + c.id + '">' + UI.escapeHtml(c.name) + "</option>";
    }).join("");
    // Les périodes viennent du calendrier configuré : une école à quatre
    // périodes en voit quatre, une école à six en voit six. Rien n'est écrit
    // en dur ici.
    var optPeriodes = '<option value="">— Délibération annuelle —</option>' + periodes.map(function (p) {
      return '<option value="' + p.id + '">' + UI.escapeHtml(p.label) + "</option>";
    }).join("");

    var lignes = seances.length ? seances.map(function (s) {
      return '<tr data-open="' + s.id + '" style="cursor:pointer">'
        + "<td>" + UI.escapeHtml(s.year_label || "—") + "</td>"
        + "<td>" + UI.escapeHtml(s.period_label || "Année complète") + "</td>"
        + "<td><strong>" + UI.escapeHtml(s.class_name) + "</strong></td>"
        + "<td>" + s.student_count + " élève(s)</td>"
        + "<td>" + s.decided_count + " / " + s.student_count + "</td>"
        + "<td>" + UI.badge(s.status === "CLOSED" ? "ok" : "warn",
                            s.status === "CLOSED" ? "Terminée" : "En cours") + "</td></tr>";
    }).join("") : '<tr><td colspan="6" class="muted" style="padding:18px 0">Aucune délibération ouverte.</td></tr>';

    var creation = ctx.role === "directeur"
      ? '<div class="panel"><div class="panel-head"><h2>Ouvrir une délibération</h2>'
        + '<span class="sub">La séance s\'appuie sur le calendrier de votre établissement.</span></div>'
        + '<div class="row" style="gap:10px;flex-wrap:wrap">'
        + '<select id="dAnnee" style="min-width:170px">' + optAnnees + "</select>"
        + '<select id="dPeriode" style="min-width:200px">' + optPeriodes + "</select>"
        + '<select id="dClasse" style="min-width:170px">' + optClasses + "</select>"
        + '<button type="button" class="btn btn-lime btn-sm" id="dCreer">' + UI.icon("reports", 15) + "Ouvrir</button>"
        + '</div><p class="form-msg" id="dMsg" style="margin-top:10px"></p></div>'
      : "";

    document.getElementById("delibContent").innerHTML = creation
      + '<div class="panel" style="margin-top:16px"><div class="panel-head"><h2>Séances</h2></div>'
      + '<div class="table-wrap"><table class="table"><thead><tr><th>Année</th><th>Période</th>'
      + "<th>Classe</th><th>Effectif</th><th>Décidés</th><th>État</th></tr></thead><tbody>"
      + lignes + "</tbody></table></div></div>";
    cablerListe();
  }

  function cablerListe() {
    var b = document.getElementById("dCreer");
    if (b) b.addEventListener("click", function () {
      var msg = document.getElementById("dMsg");
      var periode = document.getElementById("dPeriode").value;
      UI.btnState(b, "loading", "Ouverture…");
      api.fetch("/deliberations", { method: "POST", body: JSON.stringify({
        class_id: document.getElementById("dClasse").value,
        period_id: periode || null,
        kind: periode ? "PERIOD" : "ANNUAL",
      }) }).then(function (res) {
        if (!res.ok) {
          UI.btnState(b, "error", "Échec");
          msg.textContent = (res.body && res.body.error) || "Impossible d'ouvrir la séance.";
          msg.className = "form-msg error"; return;
        }
        UI.btnState(b, "success", res.body.already_exists ? "Déjà ouverte" : "Ouverte");
        ouvrir(res.body.id);
      });
    });
    document.querySelectorAll("[data-open]").forEach(function (tr) {
      tr.addEventListener("click", function () { ouvrir(tr.dataset.open); });
    });
  }

  // ---- Tableau du conseil ---------------------------------------------
  function ouvrir(id) {
    api.fetch("/deliberations/" + id).then(function (res) {
      if (!res.ok) { UI.toast((res.body && res.body.error) || "Séance inaccessible.", "error"); return; }
      courante = res.body; filtre = "tous";
      rendreTableau();
    });
  }

  function rendreTableau() {
    var d = courante;
    var visibles = d.rows.filter(function (r) {
      if (filtre === "examiner") return r.signals.ensemble.niveau !== "ok";
      if (filtre === "decides") return !!r.decision;
      return true;
    });
    var aExaminer = d.rows.filter(function (r) { return r.signals.ensemble.niveau !== "ok"; }).length;
    var decides = d.rows.filter(function (r) { return !!r.decision; }).length;

    var onglet = function (cle, libelle, n) {
      return '<button type="button" class="btn btn-ghost btn-sm' + (filtre === cle ? " active" : "")
        + '" data-filtre="' + cle + '">' + libelle + " (" + n + ")</button>";
    };

    var lignes = visibles.map(function (r) {
      var s = r.signals;
      return '<tr data-eleve="' + r.student.id + '" style="cursor:pointer">'
        + '<td><span class="cell-main">' + UI.escapeHtml(r.student.last_name + " " + r.student.first_name) + "</span></td>"
        + '<td class="num">' + (r.results.percent != null ? r.results.percent + " %" : "—") + "</td>"
        + "<td>" + pastille(s.resultats) + "</td>"
        + "<td>" + pastille(s.presence) + "</td>"
        + "<td>" + pastille(s.discipline) + "</td>"
        + "<td>" + UI.escapeHtml(s.ensemble.libelle) + "</td>"
        + "<td>" + (r.decision
            ? UI.badge("ok", d.decisions_available[r.decision.value] || r.decision.value)
            : '<span class="muted">—</span>') + "</td></tr>";
    }).join("") || '<tr><td colspan="7" class="muted" style="padding:18px 0">Aucun élève dans ce filtre.</td></tr>';

    document.getElementById("delibContent").innerHTML =
      '<div class="row between" style="margin-bottom:14px"><div>'
      + '<h2 style="margin:0">Délibération — ' + UI.escapeHtml(d.class.name) + "</h2>"
      + '<p class="muted" style="margin:4px 0 0">' + UI.escapeHtml(d.period || "Année complète")
      + " · " + d.count + " élève(s)</p></div>"
      + '<button type="button" class="btn btn-ghost btn-sm" id="dRetour">Toutes les séances</button></div>'
      + '<div class="row" style="gap:8px;margin-bottom:12px">'
      + onglet("tous", "Tous", d.count) + onglet("examiner", "À examiner", aExaminer)
      + onglet("decides", "Décisions", decides) + "</div>"
      + '<div class="panel"><div class="table-wrap"><table class="table"><thead><tr>'
      + "<th>Élève</th><th>Moyenne</th><th>Résultats</th><th>Présence</th><th>Discipline</th>"
      + "<th>Situation</th><th>Décision</th></tr></thead><tbody>" + lignes + "</tbody></table></div>"
      + '<p class="muted" style="margin-top:12px;font-size:12.5px">Les indicateurs signalent des '
      + "éléments à examiner. Ils ne constituent jamais une décision — celle-ci appartient au conseil.</p></div>";

    document.getElementById("dRetour").addEventListener("click", function () { charger(); });
    document.querySelectorAll("[data-filtre]").forEach(function (b) {
      b.addEventListener("click", function () { filtre = b.dataset.filtre; rendreTableau(); });
    });
    document.querySelectorAll("[data-eleve]").forEach(function (tr) {
      tr.addEventListener("click", function () { ouvrirEleve(tr.dataset.eleve); });
    });
  }

  // ---- Dossier individuel ---------------------------------------------
  function ouvrirEleve(studentId) {
    api.fetch("/deliberations/" + courante.id + "/students/" + studentId).then(function (res) {
      if (!res.ok) { UI.toast("Dossier inaccessible.", "error"); return; }
      var d = res.body, e = d.student;
      var matieres = (d.bulletin.subjects || []).map(function (m) {
        return "<tr><td>" + UI.escapeHtml(m.subject) + '</td><td class="num">'
          + (m.average_20 != null ? m.average_20 : "—") + "</td></tr>";
      }).join("") || '<tr><td colspan="2" class="muted">Aucun résultat enregistré.</td></tr>';

      var incidents = (d.incidents || []).slice(0, 6).map(function (i) {
        return "<li>" + UI.fmtDate(i.occurred_at) + " — " + UI.escapeHtml(i.title)
          + (i.points ? " (" + i.points + " pts)" : "") + "</li>";
      }).join("") || '<li class="muted">Aucun incident enregistré.</li>';

      var depots = (d.entries || []).map(function (x) {
        var remplace = x.superseded_at ? ' <span class="muted">(remplacé)</span>' : "";
        var titre = x.kind === "DECISION" ? "Décision" : (x.kind === "AVIS" ? "Avis" : "Observation");
        return '<li style="margin-bottom:8px">' + UI.badge(x.kind === "DECISION" ? "ok" : "info", titre)
          + " " + (x.value ? "<strong>" + UI.escapeHtml(d.decisions_available[x.value] || x.value) + "</strong> — " : "")
          + UI.escapeHtml(x.comment || "") + '<br><span class="muted" style="font-size:12px">'
          + UI.escapeHtml(x.author_name || "") + " · " + UI.fmtDateTime(x.created_at) + remplace + "</span></li>";
      }).join("") || '<li class="muted">Rien n\'a encore été déposé.</li>';

      var choix = Object.keys(d.decisions_available).map(function (k) {
        return '<option value="' + k + '">' + UI.escapeHtml(d.decisions_available[k]) + "</option>";
      }).join("");

      // Le dépôt proposé dépend du RÔLE, et le serveur le revérifie de toute
      // façon : masquer un bouton n'a jamais protégé personne.
      var zone = "";
      if (d.can_decide || d.can_give_opinion) {
        zone = '<div class="panel" style="margin-top:14px"><div class="panel-head"><h2>'
          + (d.can_decide ? "Décision du conseil" : "Votre avis") + "</h2><span class=\"sub\">"
          + (d.can_decide ? "Elle fait foi et sera conservée avec son auteur et sa date."
                          : "Un avis éclaire le conseil. Il ne vaut pas décision.") + "</span></div>"
          + '<div class="row" style="gap:10px;flex-wrap:wrap">'
          + '<select id="eVal" style="min-width:230px"><option value="">— Choisir —</option>' + choix + "</select>"
          + '<input type="text" id="eCom" placeholder="Motif ou commentaire" style="flex:1;min-width:220px;border:1px solid var(--line);border-radius:10px;padding:10px 12px;font:inherit;background:var(--surface);color:var(--ink)" />'
          + '<button type="button" class="btn btn-lime btn-sm" id="eEnr">Enregistrer</button></div></div>';
      }
      zone += '<div class="panel" style="margin-top:14px"><div class="panel-head"><h2>Observation</h2>'
        + '<span class="sub">Ajoutée au dossier. Elle n\'écrase jamais les précédentes.</span></div>'
        + '<div class="row" style="gap:10px"><input type="text" id="eObs" placeholder="Observation du conseil" style="flex:1;border:1px solid var(--line);border-radius:10px;padding:10px 12px;font:inherit;background:var(--surface);color:var(--ink)" />'
        + '<button type="button" class="btn btn-ghost btn-sm" id="eObsBtn">Ajouter</button></div></div>';

      var m = UI.modal({
        title: e.last_name + " " + e.first_name + " — " + (e.class_name || ""),
        size: "wide",
        body: '<div class="kpi-grid cols-3">'
          + UI.kpi("Moyenne générale", d.bulletin.general_average_20 != null ? d.bulletin.general_average_20 + " / 20" : "—", { icon: "book" })
          + UI.kpi("Absences", String((d.attendance && d.attendance.absent) || 0), { icon: "clock" })
          + UI.kpi("Conduite", UI.escapeHtml(d.bulletin.conduct.label || "—"), { icon: "discipline" })
          + "</div>"
          + '<div class="panel" style="margin-top:14px"><div class="panel-head"><h2>Résultats</h2></div>'
          + '<div class="table-wrap"><table class="table"><thead><tr><th>Matière</th><th class="num">Moyenne /20</th></tr></thead><tbody>'
          + matieres + "</tbody></table></div></div>"
          + '<div class="panel" style="margin-top:14px"><div class="panel-head"><h2>Discipline</h2></div>'
          + "<ul style=\"margin:0;padding-left:18px\">" + incidents + "</ul></div>"
          + '<div class="panel" style="margin-top:14px"><div class="panel-head"><h2>Dépôts du conseil</h2></div>'
          + "<ul style=\"margin:0;padding-left:18px;list-style:none\">" + depots + "</ul></div>"
          + zone,
        footer: '<a href="eleve-dossier.html?id=' + e.id + '" class="btn btn-ghost btn-sm">Ouvrir le dossier complet</a>',
      });

      var enr = m.querySelector("#eEnr");
      if (enr) enr.addEventListener("click", function () {
        var val = m.querySelector("#eVal").value;
        if (!val) { UI.toast("Choisissez une décision.", "warn"); return; }
        var kind = d.can_decide ? "DECISION" : "AVIS";
        var libelle = d.decisions_available[val];
        // La décision n'est jamais enregistrée sur un simple clic : c'est un
        // acte institutionnel, il se confirme.
        UI.confirm(kind === "DECISION" ? "Enregistrer la décision" : "Enregistrer votre avis",
                   (kind === "DECISION" ? "Décision officielle : " : "Avis : ") + libelle
                   + ". Elle sera conservée avec votre nom et la date.",
                   "Confirmer").then(function (ok) {
          if (!ok) return;
          deposer(studentId, kind, val, m.querySelector("#eCom").value);
        });
      });
      m.querySelector("#eObsBtn").addEventListener("click", function () {
        var t = m.querySelector("#eObs").value.trim();
        if (!t) { UI.toast("Écrivez l'observation.", "warn"); return; }
        deposer(studentId, "OBSERVATION", null, t);
      });
    });
  }

  function deposer(studentId, kind, value, comment) {
    api.fetch("/deliberations/" + courante.id + "/entries", { method: "POST", body: JSON.stringify({
      kind: kind, student_id: studentId, value: value, comment: comment || null,
    }) }).then(function (res) {
      if (!res.ok) { UI.toast((res.body && res.body.error) || "Refusé.", "error"); return; }
      UI.closeModal();
      UI.toast(kind === "DECISION" ? "Décision enregistrée." : (kind === "AVIS" ? "Avis enregistré." : "Observation ajoutée."), "ok");
      ouvrir(courante.id);
    });
  }

  // ---- Démarrage -------------------------------------------------------
  function charger() {
    return Promise.all([
      api.fetch("/deliberations").then(function (r) { seances = (r.ok && r.body) || []; }),
      api.fetch("/academic-years").then(function (r) { annees = (r.ok && r.body) || []; }),
      api.fetch("/classes").then(function (r) { classes = (r.ok && r.body) || []; }),
      api.fetch("/periods").then(function (r) { periodes = (r.ok && r.body && r.body.periods) || []; }),
    ]).then(rendreListe);
  }

  admin.initShell("deliberations").then(function (c) {
    ctx = c;
    if (c.role === "parent") {
      document.getElementById("delibContent").innerHTML = UI.emptyState(
        "Les délibérations sont internes",
        "Le conseil délibère entre professionnels. Ce qui vous concerne — la décision — apparaît sur le bulletin de votre enfant.",
        '<a href="' + UI.homeFor(c.role) + '" class="btn btn-ghost btn-sm">Retour à l\'accueil</a>', "lock");
      return;
    }
    charger();
  });
})();
