// KLASSIO — Dossier central de l'élève. UNE source (GET /api/students/:id),
// déjà filtrée par le backend selon le rôle : l'interface affiche les onglets
// que `sections` autorise, jamais plus. Tout ce qui touche à la discipline,
// aux résultats et aux justifications reste une décision humaine tracée.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var studentId = UI.qs("id"), ctx = null, D = null, tabsCtl = null, contacts = null, periods = [], resources = [], documents = [], thread = null;
  if (!studentId) { window.location.href = "eleves.html"; return; }

  var STATUS_FR = { present: "présent", late: "en retard", absent: "absent", excused: "excusé" };
  var DECISIONS = { admis: "Admis(e)", ajourne: "Ajourné(e)", doublant: "Doublant(e)" };

  admin.initShell("eleves").then(function (c) {
    ctx = c;
    var back = document.getElementById("backLink");
    back.innerHTML = UI.icon("chevronLeft", 15) + (c.role === "parent" ? "Mes enfants" : "Retour aux élèves");
    load();
  });

  var parcours = [];

  function isStaff() { return ctx.role === "directeur" || ctx.role === "discipline" || ctx.role === "professeur"; }
  function isDD() { return ctx.role === "directeur" || ctx.role === "discipline"; }

  function load() {
    document.getElementById("dossierHead").innerHTML = UI.skeleton("card", 1);
    document.getElementById("dossierPanels").innerHTML = UI.skeleton("card", 2);
    var calls = [api.fetch("/students/" + studentId), api.fetch("/students/" + studentId + "/contacts"), api.fetch("/documents"),
                 api.fetch("/students/" + studentId + "/enrollments")];
    if (ctx.role !== "parent") calls.push(api.fetch("/periods"));   // index 4
    Promise.all(calls).then(function (r) {
      if (!r[0].ok) {
        document.getElementById("dossierHead").innerHTML = "";
        document.getElementById("dossierPanels").innerHTML = UI.emptyState("Dossier introuvable ou accès non autorisé", r[0].body.error || "Ce dossier n'existe pas ou n'est pas dans votre périmètre.", '<a href="eleves.html" class="btn btn-ghost btn-sm">Retour</a>', "lock");
        return;
      }
      D = r[0].body;
      contacts = r[1].ok ? r[1].body : null;
      documents = r[2].ok ? r[2].body : [];
      parcours = r[3] && r[3].ok ? (r[3].body.parcours || []) : [];
      periods = r[4] && r[4].ok ? r[4].body.periods : [];
      var after = function () { renderHead(); renderTabs(); };
      if (D.student.class) api.fetch("/resources?class_id=" + D.student.class.id).then(function (rr) { resources = rr.ok ? rr.body : []; after(); });
      else after();
    }).catch(function () { admin.loadError(document.getElementById("dossierPanels"), load, "Le serveur Klassio est injoignable"); });
  }

  // ---------------- En-tête ----------------
  function renderHead() {
    var s = D.student, att = D.attendance.summary, b = D.bulletin, bal = D.discipline.balance;
    var canEdit = ctx.role === "directeur";
    // Le fil d'Ariane de la topbar se complète du nom de l'élève : la coquille
    // sait dans quelle section on est, seule cette page sait DE QUI il s'agit.
    admin.setContext(s.first_name + " " + s.last_name);
    var kpis = '<div class="dh-kpi"><span class="k">Présence</span><span class="v">' + (att.total ? att.rate + " %" : "—") + "</span></div>" +
      '<div class="dh-kpi"><span class="k">Absences</span><span class="v">' + att.absent + "</span></div>" +
      '<div class="dh-kpi"><span class="k">Retards</span><span class="v">' + att.late + "</span></div>";
    if (ctx.role !== "parent" || D.discipline.incidents.length) kpis += '<div class="dh-kpi"><span class="k">Conduite</span><span class="v ' + (bal.percent < 70 ? "text-warn" : "text-lime") + '">' + bal.remaining + " / " + bal.capital + "</span></div>";
    if (b.general_average_20 != null) kpis += '<div class="dh-kpi"><span class="k">Moyenne (' + UI.escapeHtml(b.period || "") + ')</span><span class="v">' + b.general_average_20 + "/20</span></div>";
    if (b.rank) kpis += '<div class="dh-kpi"><span class="k">Rang</span><span class="v">' + b.rank + " / " + b.class_size + "</span></div>";
    if (D.finance) kpis += '<div class="dh-kpi"><span class="k">Reste à payer</span><span class="v ' + (D.finance.balance > 0 ? "text-warn" : "text-lime") + '">' + UI.money(D.finance.balance, D.finance.currency) + "</span></div>";

    var today = D.attendance.today;
    var actions = "";
    if (canEdit) actions += '<button type="button" class="btn btn-ghost btn-sm" id="editBtn">' + UI.icon("edit", 15) + "Modifier</button>";
    if (isDD()) actions += '<button type="button" class="btn btn-ghost btn-sm" id="incBtn">' + UI.icon("discipline", 15) + "Incident</button>";
    if (ctx.role === "professeur") actions += '<button type="button" class="btn btn-ghost btn-sm" id="reportBtn">' + UI.icon("discipline", 15) + "Signaler au DD</button>";
    if (ctx.role !== "professeur") actions += '<a href="messages.html?student=' + s.id + '" class="btn btn-ghost btn-sm">' + UI.icon("mail", 15) + "Écrire</a>";
    if (s.class) actions += '<a href="classe.html?id=' + s.class.id + '" class="btn btn-ghost btn-sm">' + UI.icon("classes", 15) + UI.escapeHtml(s.class.name) + "</a>";

    document.getElementById("dossierHead").innerHTML = '<div class="dossier-head">' +
      '<div class="dh-photo">' + UI.avatar(s, 76) + (canEdit ? '<button type="button" class="photo-btn" id="photoBtn" aria-label="Changer la photo" title="Photo (JPEG/PNG, 300 Ko max)">' + UI.icon("camera", 14) + '</button><input type="file" id="photoInput" accept="image/png,image/jpeg" hidden>' : "") + "</div>" +
      "<div><h1>" + UI.escapeHtml(s.first_name + " " + s.last_name) + '</h1><div class="dh-meta"><span class="chip-code">' + UI.escapeHtml(s.code || "—") + "</span>" +
      (s.class ? "<span>" + UI.escapeHtml(s.class.name) + (s.class.cycle ? " · " + UI.badge(s.class.cycle) : "") + "</span>" : UI.badge("neutral", "Classe non affectée")) +
      (s.titulaire ? "<span>" + UI.icon("user", 13) + " " + UI.escapeHtml(s.titulaire.name) + "</span>" : "") +
      (today ? UI.badge(today.status, "Aujourd'hui : " + STATUS_FR[today.status]) : UI.badge("neutral", "Appel non envoyé")) +
      (s.status !== "active" ? UI.badge(s.status) : "") + "</div></div>" +
      '<div class="dh-actions">' + actions + "</div>" +
      '<div class="dh-kpis">' + kpis + "</div></div>";
    var eb = document.getElementById("editBtn"); if (eb) eb.addEventListener("click", openEditModal);
    var ib = document.getElementById("incBtn"); if (ib) ib.addEventListener("click", function () { window.location.href = "discipline.html?new=1&student=" + s.id; });
    var rb = document.getElementById("reportBtn"); if (rb) rb.addEventListener("click", openReportModal);
    var pb = document.getElementById("photoBtn");
    if (pb) {
      var input = document.getElementById("photoInput");
      pb.addEventListener("click", function () { input.click(); });
      input.addEventListener("change", function () {
        var file = input.files[0]; if (!file) return;
        UI.fileToDataUrl(file, 300 * 1024).then(function (d) {
          api.fetch("/students/" + studentId, { method: "PUT", body: JSON.stringify({ photo_data: d }) }).then(function (res) {
            if (!res.ok) return UI.toast(res.body.error || "Impossible d'enregistrer la photo.", "error");
            UI.toast("Photo enregistrée.", "success"); load();
          });
        }, function (err) { UI.toast(err.message, "error"); });
      });
    }
  }

  // ---------------- Onglets ----------------
  var TAB_DEFS = { profil: ["Profil", "id"], scolarite: ["Scolarité", "book"], presence: ["Présence", "calendar"], discipline: ["Discipline", "discipline"],
                   horaire: ["Horaire & examens", "clock"], documents: ["Documents", "file"], messages: ["Communication", "mail"], finance: ["Finance", "finance"], recus: ["Reçus & commandes", "receipt"] };
  function renderTabs() {
    var sections = D.sections.filter(function (k) { return TAB_DEFS[k] && !(k === "messages" && ctx.role === "professeur" && !D.student.class); });
    var counts = { presence: D.attendance.summary.total, discipline: D.discipline.incidents.length, scolarite: D.grades.length + D.appreciations.length, recus: D.receipts.length + D.orders.length, documents: documents.length + resources.length };
    document.getElementById("dossierTabs").innerHTML = sections.map(function (k) {
      return '<button type="button" class="tab-btn" data-tab="' + k + '">' + UI.icon(TAB_DEFS[k][1], 15) + TAB_DEFS[k][0] + (counts[k] ? '<span class="cnt">' + counts[k] + "</span>" : "") + "</button>";
    }).join("");
    document.getElementById("dossierPanels").innerHTML = sections.map(function (k) { return '<div data-tab-panel="' + k + '" hidden></div>'; }).join("");
    sections.forEach(function (k) { document.querySelector('[data-tab-panel="' + k + '"]').innerHTML = renderers[k](); });
    tabsCtl = UI.tabs(document.getElementById("dossierTabs"), function (name) {
      history.replaceState(null, "", "?id=" + studentId + "&tab=" + name);
      if (name === "messages") loadThread();
    });
    var wanted = UI.qs("tab");
    tabsCtl.activate(sections.indexOf(wanted) >= 0 ? wanted : sections[0], true);
    wireActions();
    UI.wireHrefs(document.getElementById("dossierPanels"));
  }

  var renderers = {
    profil: function () {
      var s = D.student;
      var guardians = D.guardians.length ? D.guardians.map(function (g) {
        return '<div class="roll-row"><span class="avatar-init soft" style="width:36px;height:36px;font-size:12px;">' + UI.escapeHtml(UI.initials(g)) + '</span><div class="roll-name">' + UI.escapeHtml((g.first_name + " " + (g.last_name || "")).trim()) + "<span>" + UI.escapeHtml(g.relationship || "Responsable") + (g.phone ? " · " + UI.escapeHtml(g.phone) : "") + (g.email ? " · " + UI.escapeHtml(g.email) : "") + "</span></div>" +
          (g.has_account != null ? UI.badge(g.has_account ? "ok" : "neutral", g.has_account ? "Compte actif" : "Sans compte") : "") + "</div>";
      }).join("") : '<p class="muted">Aucun responsable enregistré' + (ctx.role === "directeur" ? " — invitez un parent depuis Établissement pour le rattacher à ce dossier." : ".") + "</p>";
      return '<div class="two-col"><div class="panel"><div class="panel-head"><h2>Identité</h2></div><dl class="dl">' +
        "<dt>Identifiant</dt><dd><span class=\"chip-code\">" + UI.escapeHtml(s.code || "—") + "</span></dd><dt>Prénom</dt><dd>" + UI.escapeHtml(s.first_name) + "</dd><dt>Nom</dt><dd>" + UI.escapeHtml(s.last_name) + "</dd>" +
        "<dt>Genre</dt><dd>" + (s.gender === "F" ? "Fille" : s.gender === "M" ? "Garçon" : "—") + "</dd><dt>Date de naissance</dt><dd>" + (s.birth_date ? UI.fmtDate(s.birth_date) : "—") + "</dd>" +
        "<dt>Classe</dt><dd>" + (s.class ? UI.escapeHtml(s.class.name) : "Non affectée") + "</dd><dt>Titulaire</dt><dd>" + (s.titulaire ? UI.escapeHtml(s.titulaire.name) : "—") + "</dd>" +
        "<dt>Statut</dt><dd>" + UI.badge(s.status) + "</dd><dt>Dossier créé le</dt><dd>" + UI.fmtDate(s.created_at) + "</dd></dl>" +
        '<p class="note-inline">' + UI.icon("lock", 15) + "<span>L'élève n'a pas de compte : son identifiant sert au pointage et aux documents, jamais à se connecter.</span></p>" +
        parcoursBlock() + "</div>" +
        '<div class="panel"><div class="panel-head"><h2>Responsables</h2></div><div class="roll-list">' + guardians + "</div>" + contactsBlock() + "</div></div>";
    },

    scolarite: function () {
      var b = D.bulletin;
      var pubNote = "";
      if (ctx.role === "parent") pubNote = '<p class="note-inline">' + UI.icon("info", 15) + "<span>Vous voyez les périodes <strong>proclamées</strong> par l'établissement. Les notes en cours de saisie ne sont pas affichées.</span></p>";
      else if (periods.length) {
        pubNote = '<div class="pill-row" style="margin-bottom:12px">' + periods.map(function (p) { return UI.badge(p.published_at ? "ok" : "neutral", p.label + (p.published_at ? " · proclamée" : " · non proclamée")); }).join("") + "</div>" +
          (ctx.role === "directeur" ? '<p class="muted" style="margin-bottom:12px">La proclamation se pilote depuis <a class="link-btn" href="etablissement.html?tab=periodes">Établissement → Périodes</a>.</p>' : "");
      }
      var appr = D.appreciations.length ? apprBlock() : "";
      if (!D.grades.length && !D.appreciations.length) {
        return '<div class="panel">' + pubNote + UI.emptyState("Aucun résultat publié", ctx.role === "parent" ? "Les résultats apparaîtront ici dès que l'établissement aura proclamé la période." : "Les notes se saisissent depuis la page de la classe (onglet Notes) ; les appréciations depuis l'onglet Appréciations pour la maternelle.", D.student.class && (ctx.role === "directeur" || ctx.role === "professeur") ? '<a href="classe.html?id=' + D.student.class.id + '&tab=notes" class="btn btn-ghost btn-sm">Saisir des notes</a>' : "", "book") + "</div>";
      }
      var byPeriod = {};
      D.grades.forEach(function (g) { (byPeriod[g.period] = byPeriod[g.period] || []).push(g); });
      var periodNames = Object.keys(byPeriod);
      var canCouncil = ctx.role === "directeur" || (ctx.role === "professeur" && D.student.titulaire && ctx.user_id === D.student.titulaire.id);
      var councilRow = "";
      if (isStaff()) {
        councilRow = '<div class="row mt-16 no-print">' + (canCouncil ? '<button type="button" class="btn btn-ghost btn-sm" id="conductBtn">' + UI.icon("edit", 15) + "Cote de conduite" + (b.conduct.overridden ? " (fixée)" : "") + "</button>" : "") +
          (ctx.role === "directeur" ? '<button type="button" class="btn btn-ghost btn-sm" id="decisionBtn">' + UI.icon("check", 15) + "Décision de fin d'année</button>" : "") + "</div>";
      }
      var bulletinHtml = D.grades.length ? '<div class="panel"><div class="panel-head"><h2>Bulletin — ' + UI.escapeHtml(b.period || "") + '</h2><div class="row no-print"><select id="bulletinPeriod" class="btn-xs" style="height:34px;border-radius:100px;border:1px solid var(--line);padding:0 12px;background:var(--surface);font:inherit;font-size:12.5px;">' +
        b.periods.map(function (p) { return '<option value="' + UI.escapeHtml(p) + '"' + (p === b.period ? " selected" : "") + ">" + UI.escapeHtml(p) + "</option>"; }).join("") + '</select><button type="button" class="btn btn-ghost btn-xs" id="printBulletin">' + UI.icon("print", 14) + "Imprimer</button></div></div>" +
        pubNote + '<div class="bulletin" id="bulletinSheet">' + bulletinTable(b) + "</div>" + councilRow + "</div>" : '<div class="panel">' + pubNote + "</div>";
      var detail = periodNames.map(function (p) {
        return '<div class="panel"><div class="panel-head"><h2>Notes — ' + UI.escapeHtml(p) + '</h2></div><div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Matière</th><th class="num">Note</th><th>Commentaire</th><th>Saisie par</th><th>Date</th></tr></thead><tbody>' +
          byPeriod[p].map(function (g) { return '<tr><td data-label="Matière"><span class="cell-main">' + UI.escapeHtml(g.subject) + '</span></td><td data-label="Note" class="num"><strong>' + g.score + "</strong> / " + g.max_score + '</td><td data-label="Commentaire">' + UI.escapeHtml(g.comment || "—") + '</td><td data-label="Saisie par">' + UI.escapeHtml(g.recorded_by_name || "—") + '</td><td data-label="Date">' + UI.fmtDate(g.created_at) + "</td></tr>"; }).join("") + "</tbody></table></div></div>";
      }).join("");
      return bulletinHtml + appr + detail;
    },

    presence: function () {
      var a = D.attendance;
      var head = '<div class="kpi-grid">' + UI.kpi("Taux de présence", a.summary.total ? a.summary.rate + " %" : "—", { icon: "calendar", sub: a.summary.total + " jour(s) appelé(s)" }) +
        UI.kpi("Absences non justifiées", String(a.summary.absent), { tone: a.summary.absent ? "bad" : "ok" }) + UI.kpi("Absences justifiées", String(a.summary.excused), { tone: "" }) + UI.kpi("Retards", String(a.summary.late), { tone: a.summary.late ? "warn" : "" }) + "</div>";
      var justifs = justifBlock();
      if (!a.recent.length) return head + justifs + '<div class="panel">' + UI.emptyState("Aucun appel enregistré", "La présence apparaîtra ici dès que la classe aura été appelée.", "", "calendar") + "</div>";
      var grid = '<div class="panel"><div class="panel-head"><h2>Historique</h2><span class="sub">30 derniers appels</span></div><div class="att-grid">' + a.recent.slice().reverse().map(function (r) {
        var d = new Date(r.date + "T00:00:00");
        return '<span class="att-day ' + r.status + '" title="' + UI.escapeHtml(UI.fmtDate(r.date) + " — " + ({ present: "Présent", late: "Retard", absent: "Absent", excused: "Excusé" })[r.status] + (r.note ? " · " + r.note : "")) + '">' + d.getDate() + "</span>";
      }).join("") + '</div><div class="legend"><span class="ok">Présent</span><span class="warn">Retard</span><span class="bad">Absent</span><span>Excusé</span></div></div>';
      var jdates = {}; D.justifications.forEach(function (j) { jdates[j.date] = j; });
      var events = a.recent.filter(function (r) { return r.status !== "present"; }).slice(0, 20);
      var list = '<div class="panel"><div class="panel-head"><h2>Détail</h2>' + (ctx.role === "parent" ? '<span class="sub">Vous pouvez justifier une absence — la décision revient à l\'établissement</span>' : "") + "</div>" +
        (events.length ? '<div class="timeline">' + events.map(function (r) {
          var j = jdates[r.date];
          var action = "";
          if (ctx.role === "parent" && (r.status === "absent" || r.status === "late") && !j) action = ' <button type="button" class="link-btn justify-btn" data-date="' + r.date + '">Justifier</button>';
          else if (j) action = " " + UI.badge(j.status === "pending" ? "warn" : j.status === "accepted" ? "ok" : "bad", j.status === "pending" ? "Justification en cours" : j.status === "accepted" ? "Justifiée" : "Justification refusée");
          return '<div class="tl-item"><span class="tl-dot ' + (r.status === "absent" ? "bad" : r.status === "late" ? "warn" : "") + '"></span><div class="tl-body"><strong>' + ({ late: "Retard", absent: "Absence non justifiée", excused: "Absence justifiée" })[r.status] + action + "</strong><span>" + UI.escapeHtml(r.note || "") + "</span><em>" + UI.fmtDate(r.date) + "</em></div></div>";
        }).join("") + "</div>" : '<p class="muted">Toujours présent(e) sur la période.</p>') + "</div>";
      return head + justifs + grid + list;
    },

    discipline: function () {
      var inc = D.discipline.incidents, bal = D.discipline.balance, ths = D.discipline.thresholds || [];
      var gauge = '<div class="panel"><div class="panel-head"><h2>Capital de conduite</h2>' + (isDD() ? '<button type="button" class="btn btn-ghost btn-sm" id="adjustBtn">' + UI.icon("edit", 15) + "Modifier les points</button>" : "") + "</div>" +
        UI.gauge(bal.remaining, bal.capital, bal.conduct) +
        '<p class="muted mt-8">Chaque élève démarre avec ' + bal.capital + " points. " + (bal.delta < 0 ? "<strong>" + Math.abs(bal.delta) + " point(s)</strong> ont été retirés" : bal.delta > 0 ? "<strong>+" + bal.delta + " point(s)</strong> ont été accordés" : "Aucun retrait à ce jour") + " — il lui reste <strong>" + bal.remaining + "</strong>." + (ctx.role === "parent" ? " Chaque modification vous est notifiée." : "") + "</p>" +
        (ths.length ? '<div class="threshold-list mt-16">' + ths.map(function (t) {
          return '<div class="th' + (bal.remaining <= t.remaining_points ? " reached" : "") + '"><strong>' + t.remaining_points + "</strong><span>" + UI.escapeHtml(t.label) + (t.action ? " — " + UI.escapeHtml(t.action) : "") + "</span>" + (bal.remaining <= t.remaining_points ? UI.badge("bad", "Atteint") : "") + "</div>";
        }).join("") + '</div><p class="muted mt-8">Ces seuils sont fixés par l\'établissement. Klassio alerte ; la décision reste humaine.</p>' : "") + "</div>";
      var convs = convocationsBlock();
      if (!inc.length) return gauge + convs + '<div class="panel">' + UI.emptyState(ctx.role === "parent" ? "Aucune information communiquée" : "Aucun incident enregistré", ctx.role === "parent" ? "L'établissement vous informera ici des événements qu'il décide de vous communiquer." : "Les incidents enregistrés par le Directeur des disciplines ou la Direction apparaîtront ici.", "", "discipline") + "</div>";
      var list = '<div class="panel"><div class="panel-head"><h2>Historique</h2>' + (ctx.role === "professeur" ? '<span class="sub">Informations communicables uniquement</span>' : "") + '</div><div class="timeline">' + inc.map(function (i) {
        var canReply = ctx.role !== "professeur";
        return '<div class="tl-item"><span class="tl-dot ' + (i.severity === "high" ? "bad" : i.severity === "medium" ? "warn" : "") + '"></span><div class="tl-body"><strong>' + UI.escapeHtml(i.title) + " " + UI.badge(i.severity) + (i.points ? ' <span class="chip-code">' + (i.points > 0 ? "+" : "") + i.points + " pts</span>" : "") + (i.status && i.status !== "open" ? " " + UI.badge(i.status === "closed" ? "neutral" : i.status === "decided" ? "ok" : "warn", { convocation: "Convocation", decided: "Décidé", closed: "Clos" }[i.status]) : "") + "</strong>" +
          (i.description ? "<span>" + UI.escapeHtml(i.description) + "</span>" : "") + (i.action_taken ? '<span><strong style="font-size:12.5px">Mesure :</strong> ' + UI.escapeHtml(i.action_taken) + "</span>" : "") +
          (i.internal_note ? '<span class="note-inline" style="margin:8px 0 0">' + UI.icon("lock", 14) + "<span><strong>Note interne (DD / Direction)</strong> — " + UI.escapeHtml(i.internal_note) + "</span></span>" : "") +
          "<em>" + UI.fmtDate(i.occurred_at) + (i.recorded_by_name ? " · enregistré par " + UI.escapeHtml(i.recorded_by_name) : "") + (i.rule_label ? " · règle : " + UI.escapeHtml(i.rule_label) : "") + (ctx.role !== "parent" ? (i.notify_parent ? " · parent informé" : " · parent non informé") : "") + "</em>" +
          (canReply ? '<div class="row no-print" style="margin-top:8px;gap:8px"><button type="button" class="link-btn open-inc" data-id="' + i.id + '">' + (ctx.role === "parent" ? "Répondre / voir les échanges" : "Échanges et suites") + "</button>" + (isDD() ? '<button type="button" class="link-btn conv-inc" data-id="' + i.id + '">Convoquer les parents</button><button type="button" class="link-btn status-inc" data-id="' + i.id + '">Statut & mesure</button>' : "") + "</div>" : "") +
          '<div class="inc-detail" id="inc-' + i.id + '" hidden></div></div></div>';
      }).join("") + "</div></div>";
      return gauge + convs + list;
    },

    horaire: function () {
      var byDay = {};
      D.schedule.forEach(function (s) { (byDay[s.weekday] = byDay[s.weekday] || []).push(s); });
      var sched = D.schedule.length ? '<div class="schedule-grid">' + [1, 2, 3, 4, 5].map(function (d) {
        return '<div class="schedule-col"><h4>' + UI.WEEKDAYS[d] + "</h4>" + (byDay[d] || []).map(function (s) { return '<div class="slot"><strong>' + UI.escapeHtml(s.start_time + " – " + s.end_time) + "</strong>" + UI.escapeHtml(s.subject) + "<span>" + (s.teacher_name ? "<br>" + UI.escapeHtml(s.teacher_name) : "") + (s.room ? " · " + UI.escapeHtml(s.room) : "") + "</span></div>"; }).join("") + (byDay[d] ? "" : '<p class="muted">—</p>') + "</div>";
      }).join("") + "</div>" : UI.emptyState("Aucun horaire saisi", "L'emploi du temps est rattaché à la classe et saisi par la Direction.", D.student.class && ctx.role === "directeur" ? '<a href="classe.html?id=' + D.student.class.id + '&tab=horaire" class="btn btn-ghost btn-sm">Saisir l\'horaire</a>' : "", "clock");
      var today = UI.todayIso();
      var upcoming = D.exams.filter(function (e) { return e.date >= today; }), past = D.exams.filter(function (e) { return e.date < today; });
      var exams = D.exams.length ? '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Matière</th><th>Type</th><th>Date</th><th>Heure</th><th>Salle</th></tr></thead><tbody>' +
        upcoming.concat(past).map(function (e) { return '<tr' + (e.date < today ? ' style="opacity:0.55"' : "") + '><td data-label="Matière"><span class="cell-main">' + UI.escapeHtml(e.subject) + '</span></td><td data-label="Type">' + UI.escapeHtml(e.exam_type) + '</td><td data-label="Date">' + UI.fmtDate(e.date) + '</td><td data-label="Heure">' + UI.escapeHtml(e.start_time || "—") + '</td><td data-label="Salle">' + UI.escapeHtml(e.room || "—") + "</td></tr>"; }).join("") + "</tbody></table></div>"
        : '<p class="muted">Aucune évaluation planifiée pour cette classe.</p>';
      return '<div class="panel"><div class="panel-head"><h2>Emploi du temps' + (D.student.class ? " — " + UI.escapeHtml(D.student.class.name) : "") + '</h2><a class="link-btn" href="calendrier.html">Calendrier</a></div>' + sched + "</div>" +
        '<div class="panel"><div class="panel-head"><h2>Examens & évaluations</h2><span class="sub">' + upcoming.length + " à venir</span></div>" + exams + "</div>";
    },

    documents: function () {
      var docs = documents.length ? '<div class="doc-grid">' + documents.map(function (d) {
        return '<div class="doc-card"><span class="dc-ic">' + UI.icon("file", 18) + '</span><div class="dc-body"><strong>' + UI.escapeHtml(d.title) + "</strong><span>" + UI.escapeHtml(d.kind) + " · " + Math.round((d.file_size || 0) / 1024) + " Ko · " + UI.fmtDate(d.created_at) + '</span></div><button type="button" class="btn btn-ghost btn-xs doc-open" data-id="' + d.id + '">Ouvrir</button></div>';
      }).join("") + "</div>" : '<p class="muted">Aucun document publié par l\'établissement.</p>';
      var res = resources.length ? '<div class="doc-grid">' + resources.slice(0, 24).map(function (r) {
        return '<div class="doc-card"><span class="dc-ic">' + UI.icon(r.kind === "devoir" ? "clipboard" : "book", 18) + '</span><div class="dc-body"><strong>' + UI.escapeHtml(r.title) + "</strong><span>" + UI.escapeHtml(UI.EVENT_KIND_LABELS[r.kind] || r.kind) + (r.subject ? " · " + UI.escapeHtml(r.subject) : "") + (r.due_date ? " · à rendre le " + UI.fmtDate(r.due_date) : "") + '</span></div><a class="btn btn-ghost btn-xs" href="ressources.html?class_id=' + (D.student.class ? D.student.class.id : "") + '">Voir</a></div>';
      }).join("") + "</div>" : '<p class="muted">Aucun livre ni devoir publié pour cette classe.</p>';
      return '<div class="panel"><div class="panel-head"><h2>Documents de l\'élève</h2></div><div class="doc-grid">' +
        '<div class="doc-card"><span class="dc-ic">' + UI.icon("id", 18) + '</span><div class="dc-body"><strong>Attestation de fréquentation</strong><span>Données réelles du dossier — impression navigateur</span></div><button type="button" class="btn btn-lime btn-xs" id="attestBtn">' + UI.icon("print", 13) + "Imprimer</button></div>" +
        (D.grades.length ? '<div class="doc-card"><span class="dc-ic">' + UI.icon("book", 18) + '</span><div class="dc-body"><strong>Bulletin — ' + UI.escapeHtml(D.bulletin.period || "") + "</strong><span>Moyenne, rang, conduite</span></div><button type=\"button\" class=\"btn btn-ghost btn-xs\" id=\"goBulletin\">Ouvrir</button></div>" : "") +
        "</div></div>" +
        '<div class="panel"><div class="panel-head"><h2>Documents de l\'établissement</h2>' + (ctx.role === "directeur" ? '<a class="link-btn" href="documents.html">Gérer</a>' : "") + "</div>" + docs + "</div>" +
        '<div class="panel"><div class="panel-head"><h2>Livres & devoirs de la classe</h2><a class="link-btn" href="ressources.html' + (D.student.class ? "?class_id=" + D.student.class.id : "") + '">Tout voir</a></div>' + res + "</div>";
    },

    messages: function () {
      return '<div class="panel"><div class="panel-head"><h2>Cahier de communication</h2><a class="link-btn" href="messages.html?student=' + studentId + '">Ouvrir en grand</a></div>' +
        '<p class="muted" style="margin-bottom:12px">' + (ctx.role === "parent" ? "Fil unique avec le titulaire, le Directeur des disciplines et la Direction. Tout est tracé." : "Fil unique avec les responsables de cet élève. Tout est tracé.") + "</p>" +
        '<div class="msg-list" id="dossierThread" style="max-height:380px;border:1px solid var(--line);border-radius:14px;background:var(--surface-soft)">' + UI.skeleton("row", 2) + "</div>" +
        '<form class="msg-compose" id="dossierCompose" style="border:0;padding:12px 0 0"><textarea id="dossierMsg" maxlength="2000" placeholder="Écrire un message…" required></textarea><button type="submit" class="btn btn-lime btn-sm" id="dossierSend">' + UI.icon("mail", 15) + "Envoyer</button></form></div>";
    },

    finance: function () {
      var f = D.finance;
      if (!f) return "";
      var head = '<div class="kpi-grid cols-3">' + UI.kpi("Frais facturés", UI.money(f.total_due, f.currency), { icon: "finance" }) + UI.kpi("Payé", UI.money(f.total_paid, f.currency), { tone: "ok" }) + UI.kpi("Reste", UI.money(f.balance, f.currency), { tone: f.balance > 0 ? "warn" : "ok" }) + "</div>";
      var canRecord = ctx.role === "directeur", canPay = ctx.role === "parent";
      var addOb = canRecord ? '<button type="button" class="btn btn-ghost btn-sm" id="addObBtn">' + UI.icon("plus", 15) + "Ajouter une obligation</button>" : "";
      if (!f.obligations.length) return head + '<div class="panel"><div class="panel-head"><h2>Obligations</h2>' + addOb + "</div>" + UI.emptyState("Aucune obligation financière", canRecord ? "Créez une obligation à partir du catalogue (Finance) pour commencer le suivi." : "Aucun frais n'est facturé pour le moment.", "", "finance") + "</div>";
      var list = f.obligations.map(function (o) {
        var pays = o.payments.map(function (p) { return '<div class="payment-row"><span>' + UI.escapeHtml(UI.METHODS[p.method] || p.method) + " — " + UI.fmtDate(p.confirmed_at) + (p.receipt_number ? ' · <span class="chip-code">' + UI.escapeHtml(p.receipt_number) + "</span>" : "") + "</span><span>" + UI.money(p.amount, o.currency) + "</span></div>"; }).join("");
        var pending = o.pending_payments.map(function (p) { return '<div class="payment-row"><span>' + UI.badge("warn", "En attente de confirmation") + " " + UI.escapeHtml(UI.METHODS[p.method] || p.method) + " — " + UI.fmtDate(p.created_at) + "</span><span>" + UI.money(p.amount, o.currency) + (canRecord ? ' <button type="button" class="link-btn confirm-pay" data-id="' + p.id + '">Confirmer</button>' : "") + "</span></div>"; }).join("");
        var action = "";
        if (o.remaining > 0 && canRecord) action = '<button type="button" class="btn btn-ghost btn-xs pay-btn" data-ob="' + o.obligation_id + '" data-remaining="' + o.remaining + '" data-label="' + UI.escapeHtml(o.label) + '">' + UI.icon("payments", 14) + "Enregistrer un paiement</button>";
        // Le parent ne paie qu'à UN seul endroit : « Frais & reçus ». Ce dossier
        // lui montre la situation de son enfant ; deux modales de paiement
        // vivant dans deux écrans différents auraient fini par diverger — et
        // c'est l'écran dédié qui porte l'échéancier, le retard et l'historique.
        if (o.remaining > 0 && canPay && !o.pending_payments.length) action = '<a class="btn btn-lime btn-xs" href="paiements.html">' + UI.icon("phone", 14) + "Payer</a>";
        // Un trop-payé donne un « reste » négatif. Affiché tel quel, le parent
        // lisait « Reste -50,00 $ ». C'est une AVANCE : on le dit ainsi.
        var solde = o.remaining < 0
          ? " · Avance " + UI.money(Math.abs(o.remaining), o.currency)
          : " · Reste " + UI.money(o.remaining, o.currency);
        return '<div class="obligation-card"><div class="ob-head"><span class="ob-label">' + UI.escapeHtml(o.label) + "</span>" + UI.badge(o.status) + '</div><div class="ob-amounts">Facturé ' + UI.money(o.amount, o.currency) + " · Payé " + UI.money(o.paid, o.currency) + solde + (o.due_date ? " · Échéance " + UI.fmtDate(o.due_date) : "") + "</div>" + pays + pending + (action ? '<div class="row mt-8">' + action + "</div>" : "") + "</div>";
      }).join("");
      return head + '<div class="panel"><div class="panel-head"><h2>Obligations et paiements</h2>' + addOb + "</div>" + list +
        '<p class="note-inline mt-16">' + UI.icon("lock", 15) + "<span>La situation financière n'influence jamais la discipline ni les résultats : ce sont deux circuits séparés.</span></p></div>";
    },

    recus: function () {
      var receipts = D.receipts.length ? '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Reçu</th><th>Motif</th><th>Moyen</th><th>Date</th><th class="num">Montant</th><th class="actions"></th></tr></thead><tbody>' + D.receipts.map(function (r) {
        return '<tr class="clickable" data-href="paiements.html?receipt=' + r.id + '"><td data-label="Reçu"><span class="chip-code">' + UI.escapeHtml(r.number) + '</span></td><td data-label="Motif">' + UI.escapeHtml(r.label) + '</td><td data-label="Moyen">' + UI.escapeHtml(UI.METHODS[r.method] || r.method) + '</td><td data-label="Date">' + UI.fmtDate(r.created_at) + '</td><td data-label="Montant" class="num"><strong>' + UI.money(r.amount, r.currency) + '</strong></td><td class="actions">' + UI.icon("eye", 16) + "</td></tr>";
      }).join("") + "</tbody></table></div>" : '<p class="muted">Aucun reçu émis — un reçu est généré à chaque paiement confirmé.</p>';
      var orders = D.orders.length ? D.orders.map(function (o) {
        return '<div class="obligation-card"><div class="ob-head"><span class="ob-label">' + UI.escapeHtml(o.number) + " — " + UI.money(o.total, o.currency) + "</span>" + UI.badge(o.status, { pending: "À régler", paid: "Payée", ready: "Prête au retrait", delivered: "Remise", cancelled: "Annulée" }[o.status]) + "</div>" +
          '<div class="ob-amounts">' + UI.fmtDate(o.created_at) + (o.pickup_code && (o.status === "paid" || o.status === "ready") ? ' · code de retrait <span class="chip-code">' + UI.escapeHtml(o.pickup_code) + "</span>" : "") + "</div></div>";
      }).join("") : '<p class="muted">Aucune commande boutique pour cet élève.</p>';
      return '<div class="panel"><div class="panel-head"><h2>Reçus</h2></div>' + receipts + '</div><div class="panel"><div class="panel-head"><h2>Commandes boutique</h2><a class="link-btn" href="boutique.html">Boutique</a></div>' + orders + "</div>";
    },
  };

  // ---------------- Blocs réutilisés ----------------
  function contactsBlock() {
    if (!contacts) return "";
    var t = contacts.teachers.map(function (x) {
      var reach = x.contact_visible ? [x.phone, x.email].filter(Boolean).join(" · ") : "Coordonnées non communiquées";
      return '<div class="roll-row"><span class="avatar-init soft" style="width:32px;height:32px;font-size:11px">' + UI.escapeHtml((x.name || "?").split(" ").map(function (w) { return w[0]; }).join("").slice(0, 2).toUpperCase()) + '</span><div class="roll-name">' + UI.escapeHtml(x.name) + "<span>" + UI.escapeHtml(x.subject || "Enseignant") + " · " + UI.escapeHtml(reach) + "</span></div>" + (x.is_titulaire ? UI.badge("ok", "Titulaire") : "") + "</div>";
    }).join("");
    var dd = contacts.discipline.map(function (x) { return '<div class="roll-row"><span class="avatar-init soft" style="width:32px;height:32px;font-size:11px">' + UI.icon("discipline", 14) + '</span><div class="roll-name">' + UI.escapeHtml(x.name) + "<span>Directeur des disciplines" + (x.title ? " — " + UI.escapeHtml(x.title) : "") + "</span></div></div>"; }).join("");
    var sch = contacts.school;
    return '<div class="panel-head" style="margin-top:18px"><h2>Contacts</h2></div><div class="roll-list">' + (t || '<p class="muted">Aucun enseignant rattaché à cette classe.</p>') + dd +
      '<div class="roll-row"><span class="avatar-init soft" style="width:32px;height:32px;font-size:11px">' + UI.icon("building", 14) + '</span><div class="roll-name">Secrétariat<span>' + UI.escapeHtml([sch.phone, sch.email, sch.address].filter(Boolean).join(" · ") || "Coordonnées non renseignées") + "</span></div></div></div>";
  }

  // LE PARCOURS. Un élève n'est pas né dans sa classe de cette année : quand
  // il en a quitté une, le dossier doit le dire. Une seule ligne — l'année en
  // cours — signifie simplement qu'aucun passage n'a encore eu lieu, et le
  // bloc s'efface alors plutôt que d'afficher une « histoire » d'une ligne.
  function parcoursBlock() {
    if (parcours.length < 2) return "";
    var lignes = parcours.map(function (p) {
      // Une classe changée en cours d'année sans explication visible serait
      // une anomalie de plus pour qui relit le dossier. La correction se lit.
      var corr = p.corrected_reason
        ? '<div class="muted" style="font-size:12px">Corrigé depuis '
          + UI.escapeHtml(p.previous_class_name || "—") + " — "
          + UI.escapeHtml(p.corrected_reason)
          + (p.corrected_by_name ? " (" + UI.escapeHtml(p.corrected_by_name) + ")" : "")
          + "</div>"
        : "";
      return "<dt>" + UI.escapeHtml(p.year_label) + "</dt><dd>"
        + UI.escapeHtml(p.class_name || "Non affecté")
        + (p.courante ? " " + UI.badge("ok", "Année en cours") : "") + corr + "</dd>";
    }).join("");
    return '<div class="panel-head" style="margin-top:18px"><h2>Parcours</h2></div>'
      + '<dl class="dl">' + lignes + "</dl>";
  }

  function justifBlock() {
    var list = D.justifications;
    var canDecide = ctx.role === "directeur" || ctx.role === "discipline" || (ctx.role === "professeur" && D.student.titulaire && ctx.user_id === D.student.titulaire.id);
    if (!list.length) return "";
    return '<div class="panel"><div class="panel-head"><h2>Justifications</h2><span class="sub">' + UI.plural(list.filter(function (j) { return j.status === "pending"; }).length, "en attente") + '</span></div><div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Date</th><th>Motif</th><th>Pièce jointe</th><th>Statut</th><th class="actions"></th></tr></thead><tbody>' + list.map(function (j) {
      var actions = "";
      if (j.status === "pending" && canDecide) actions = '<button type="button" class="btn btn-lime btn-xs j-dec" data-id="' + j.id + '" data-status="accepted">Accepter</button> <button type="button" class="btn btn-danger btn-xs j-dec" data-id="' + j.id + '" data-status="refused">Refuser</button>';
      return '<tr><td data-label="Date">' + UI.fmtDate(j.date) + '</td><td data-label="Motif"><span class="cell-main">' + UI.escapeHtml(j.reason) + '</span>' + (j.decision_note ? '<span class="cell-sub">Réponse : ' + UI.escapeHtml(j.decision_note) + "</span>" : "") + '</td><td data-label="Pièce jointe">' + (j.attachment_name ? '<button type="button" class="link-btn j-att" data-id="' + j.id + '">' + UI.escapeHtml(j.attachment_name) + "</button>" : "—") + '</td><td data-label="Statut">' + UI.badge(j.status === "pending" ? "warn" : j.status === "accepted" ? "ok" : "bad", { pending: "En attente", accepted: "Acceptée", refused: "Refusée" }[j.status]) + '</td><td class="actions">' + actions + "</td></tr>";
    }).join("") + "</tbody></table></div></div>";
  }

  function convocationsBlock() {
    var list = D.convocations || [];
    if (!list.length) return isDD() ? "" : "";
    return '<div class="panel"><div class="panel-head"><h2>Convocations</h2></div><div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Date</th><th>Motif</th><th>Statut</th>' + (isDD() ? '<th class="actions"></th>' : "") + "</tr></thead><tbody>" + list.map(function (c) {
      var actions = isDD() && c.status === "planned" ? '<button type="button" class="btn btn-lime btn-xs cv-st" data-id="' + c.id + '" data-status="held">Tenue</button> <button type="button" class="btn btn-ghost btn-xs cv-st" data-id="' + c.id + '" data-status="missed">Manquée</button>' : "";
      return '<tr><td data-label="Date">' + UI.fmtDate(c.scheduled_on) + (c.scheduled_time ? " " + UI.escapeHtml(c.scheduled_time) : "") + '</td><td data-label="Motif">' + UI.escapeHtml(c.motif) + '</td><td data-label="Statut">' + UI.badge({ planned: "warn", held: "ok", missed: "bad", cancelled: "neutral" }[c.status], { planned: "Prévue", held: "Tenue", missed: "Manquée", cancelled: "Annulée" }[c.status]) + "</td>" + (isDD() ? '<td class="actions">' + actions + "</td>" : "") + "</tr>";
    }).join("") + "</tbody></table></div></div>";
  }

  function apprBlock() {
    var byPeriod = {};
    D.appreciations.forEach(function (a) { (byPeriod[a.period] = byPeriod[a.period] || []).push(a); });
    var LEVELS = { 1: "En construction", 2: "En cours d'acquisition", 3: "Acquis", 4: "Dépassé" };
    return Object.keys(byPeriod).map(function (p) {
      return '<div class="panel"><div class="panel-head"><h2>Appréciations — ' + UI.escapeHtml(p) + '</h2><span class="sub">Maternelle — pas de note chiffrée</span></div><div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Domaine</th><th>Niveau</th><th>Commentaire</th></tr></thead><tbody>' +
        byPeriod[p].map(function (a) { return '<tr><td data-label="Domaine"><span class="cell-main">' + UI.escapeHtml(a.domain) + '</span></td><td data-label="Niveau">' + UI.badge(a.level >= 3 ? "ok" : a.level === 2 ? "warn" : "neutral", LEVELS[a.level] || String(a.level)) + '</td><td data-label="Commentaire">' + UI.escapeHtml(a.comment || "—") + "</td></tr>"; }).join("") + "</tbody></table></div></div>";
    }).join("");
  }

  function bulletinTable(b) {
    if (!b.subjects.length) return '<p class="muted">Aucune note pour cette période.</p>';
    var c = b.conduct || {};
    return '<div class="ps-head" style="display:flex;justify-content:space-between;margin-bottom:12px"><div><strong>' + UI.escapeHtml(D.student.first_name + " " + D.student.last_name) + "</strong><br><span class=\"muted\">" + (D.student.class ? UI.escapeHtml(D.student.class.name) + " · " : "") + UI.escapeHtml(D.student.code || "") + "</span></div><div class=\"muted\">" + UI.escapeHtml(b.period) + "</div></div>" +
      '<table><thead><tr><th>Matière</th><th style="text-align:right">Évaluations</th><th style="text-align:right">Moyenne /20</th></tr></thead><tbody>' + b.subjects.map(function (s) { return "<tr><td>" + UI.escapeHtml(s.subject) + '</td><td class="avg" style="font-weight:500">' + s.count + '</td><td class="avg">' + s.average_20 + "</td></tr>"; }).join("") +
      '<tr><td><strong>Moyenne générale</strong></td><td></td><td class="avg">' + b.general_average_20 + (b.percent != null ? " <small>(" + b.percent + " %)</small>" : "") + "</td></tr>" +
      (b.rank ? '<tr><td><strong>Rang</strong></td><td></td><td class="avg">' + b.rank + " / " + b.class_size + "</td></tr>" : "") +
      (c.label ? '<tr><td><strong>Conduite</strong></td><td></td><td class="avg">' + UI.escapeHtml(c.label) + (c.overridden ? " <small>(fixée par le conseil)</small>" : " <small>(" + c.remaining + "/" + c.capital + " pts)</small>") + "</td></tr>" : "") +
      (b.decision ? '<tr><td><strong>Décision</strong></td><td></td><td class="avg">' + UI.escapeHtml(DECISIONS[b.decision.decision] || b.decision.decision) + (b.decision.mention ? " — " + UI.escapeHtml(b.decision.mention) : "") + "</td></tr>" : "") + "</tbody></table>";
  }

  // ---------------- Interactions ----------------
  function wireActions() {
    var pp = document.getElementById("bulletinPeriod");
    if (pp) pp.addEventListener("change", function () {
      api.fetch("/students/" + studentId + "/bulletin?period=" + encodeURIComponent(pp.value)).then(function (res) { if (res.ok) { D.bulletin = res.body; document.getElementById("bulletinSheet").innerHTML = bulletinTable(res.body); document.querySelector('[data-tab-panel="scolarite"] h2').textContent = "Bulletin — " + res.body.period; } });
    });
    var pb = document.getElementById("printBulletin");
    if (pb) pb.addEventListener("click", function () { UI.printSheet(document.getElementById("bulletinSheet"), "Bulletin — " + D.student.first_name + " " + D.student.last_name); });
    var gb = document.getElementById("goBulletin"); if (gb) gb.addEventListener("click", function () { tabsCtl.activate("scolarite"); });
    var ab = document.getElementById("attestBtn"); if (ab) ab.addEventListener("click", printAttestation);

    document.querySelectorAll(".pay-btn").forEach(function (b) { b.addEventListener("click", function () { openPayModal(b.dataset.ob, parseFloat(b.dataset.remaining), b.dataset.label); }); });
    document.querySelectorAll(".confirm-pay").forEach(function (b) {
      b.addEventListener("click", function () {
        UI.confirm("Confirmer ce paiement ?", "Confirmez uniquement après vérification réelle de la transaction Mobile Money. Un reçu sera émis.", "Confirmer").then(function (ok) {
          if (!ok) return;
          api.fetch("/payments/" + b.dataset.id + "/confirm", { method: "POST", body: "{}" }).then(function (res) {
            if (!res.ok) return UI.toast(res.body.error || "Confirmation impossible.", "error");
            UI.toast("Paiement confirmé" + (res.body.receipt_number ? " — reçu " + res.body.receipt_number : " — reçu en cours d'émission"), "success"); load();
          });
        });
      });
    });
    var ao = document.getElementById("addObBtn"); if (ao) ao.addEventListener("click", openObligationModal);

    // Présence / justifications
    document.querySelectorAll(".justify-btn").forEach(function (b) { b.addEventListener("click", function () { openJustifyModal(b.dataset.date); }); });
    document.querySelectorAll(".j-dec").forEach(function (b) { b.addEventListener("click", function () { decideJustification(b.dataset.id, b.dataset.status); }); });
    document.querySelectorAll(".j-att").forEach(function (b) {
      b.addEventListener("click", function () {
        api.fetch("/justifications/" + b.dataset.id + "/attachment").then(function (r) {
          if (!r.ok || !r.body.file_data) return UI.toast("Pièce jointe indisponible.", "error");
          var m = UI.modal({ title: r.body.file_name || "Pièce jointe", size: "lg", body: r.body.file_data.indexOf("data:image/") === 0 ? '<img src="' + UI.escapeHtml(r.body.file_data) + '" alt="" style="max-width:100%;border-radius:12px" />' : '<iframe src="' + UI.escapeHtml(r.body.file_data) + '" style="width:100%;height:60vh;border:0;border-radius:12px"></iframe>', footer: '<button type="button" class="btn btn-ghost btn-sm" id="attClose">Fermer</button>' });
          m.querySelector("#attClose").addEventListener("click", UI.closeModal);
        });
      });
    });

    // Discipline
    var adj = document.getElementById("adjustBtn"); if (adj) adj.addEventListener("click", openAdjustModal);
    document.querySelectorAll(".open-inc").forEach(function (b) { b.addEventListener("click", function () { toggleIncident(b.dataset.id, b); }); });
    document.querySelectorAll(".conv-inc").forEach(function (b) { b.addEventListener("click", function () { openConvocationModal(b.dataset.id); }); });
    document.querySelectorAll(".status-inc").forEach(function (b) { b.addEventListener("click", function () { openIncidentStatusModal(b.dataset.id); }); });
    document.querySelectorAll(".cv-st").forEach(function (b) {
      b.addEventListener("click", function () {
        api.fetch("/convocations/" + b.dataset.id + "/status", { method: "POST", body: JSON.stringify({ status: b.dataset.status, parent_attended: b.dataset.status === "held" }) }).then(function (r) {
          if (!r.ok) return UI.toast(r.body.error || "Impossible.", "error");
          UI.toast("Convocation mise à jour.", "success"); load();
        });
      });
    });

    // Scolarité — conseil de classe
    var cb = document.getElementById("conductBtn"); if (cb) cb.addEventListener("click", openConductModal);
    var db = document.getElementById("decisionBtn"); if (db) db.addEventListener("click", openDecisionModal);

    // Documents
    document.querySelectorAll(".doc-open").forEach(function (b) {
      b.addEventListener("click", function () {
        api.fetch("/documents/" + b.dataset.id + "/file").then(function (r) {
          if (!r.ok) return UI.toast(r.body.error || "Document indisponible.", "error");
          var m = UI.modal({ title: r.body.title || r.body.file_name, size: "lg", body: (r.body.file_data || "").indexOf("data:image/") === 0 ? '<img src="' + UI.escapeHtml(r.body.file_data) + '" alt="" style="max-width:100%;border-radius:12px" />' : '<iframe src="' + UI.escapeHtml(r.body.file_data) + '" style="width:100%;height:62vh;border:0;border-radius:12px"></iframe>', footer: '<button type="button" class="btn btn-ghost btn-sm" id="dClose">Fermer</button>' });
          m.querySelector("#dClose").addEventListener("click", UI.closeModal);
        });
      });
    });

    // Communication
    var form = document.getElementById("dossierCompose");
    if (form) form.addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = document.getElementById("dossierSend"), ta = document.getElementById("dossierMsg");
      if (!ta.value.trim()) return;
      UI.btnState(btn, "loading", "Envoi…");
      api.fetch("/messages/" + studentId, { method: "POST", body: JSON.stringify({ body: ta.value.trim() }) }).then(function (r) {
        if (!r.ok) { UI.btnState(btn, "error"); return UI.toast(r.body.error || "Envoi impossible.", "error"); }
        UI.btnState(btn, "success", "Envoyé"); ta.value = ""; loadThread();
      });
    });
  }

  function loadThread() {
    var host = document.getElementById("dossierThread"); if (!host) return;
    api.fetch("/messages/" + studentId).then(function (r) {
      if (!r.ok) { host.innerHTML = '<p class="muted">Fil indisponible.</p>'; return; }
      thread = r.body;
      host.innerHTML = thread.messages.length ? thread.messages.map(function (m) {
        var mine = m.sender_id === ctx.user_id;
        return '<div class="msg' + (mine ? " mine" : "") + '"><div class="bubble">' + UI.escapeHtml(m.body).replace(/\n/g, "<br>") + '</div><div class="meta">' + UI.escapeHtml(m.sender_name) + " · " + UI.escapeHtml(api.roleLabels[m.sender_role] || m.sender_role) + " · " + UI.relTime(m.created_at) + "</div></div>";
      }).join("") : '<p class="muted" style="padding:14px">Aucun message pour le moment. Écrivez le premier — il sera notifié.</p>';
      host.scrollTop = host.scrollHeight;
    });
  }

  function toggleIncident(id, btn) {
    var host = document.getElementById("inc-" + id);
    if (!host.hidden) { host.hidden = true; return; }
    host.hidden = false;
    host.innerHTML = UI.skeleton("row", 1);
    api.fetch("/incidents/" + id).then(function (r) {
      if (!r.ok) { host.innerHTML = '<p class="muted">Détail indisponible.</p>'; return; }
      var d = r.body;
      var replies = d.replies.length ? d.replies.map(function (x) {
        return '<div class="msg' + (x.author_role === ctx.role && ctx.role === "parent" ? " mine" : "") + '" style="max-width:100%"><div class="bubble">' + UI.escapeHtml(x.body).replace(/\n/g, "<br>") + '</div><div class="meta">' + UI.escapeHtml(x.author) + " · " + UI.escapeHtml(api.roleLabels[x.author_role] || x.author_role || "") + " · " + UI.relTime(x.created_at) + "</div></div>";
      }).join("") : '<p class="muted" style="font-size:12.5px">Aucun échange pour le moment.' + (ctx.role === "parent" ? " Vous pouvez donner votre version des faits." : "") + "</p>";
      host.innerHTML = '<div style="margin-top:10px;padding:12px;border-radius:12px;background:var(--surface-soft)"><strong style="font-size:12.5px;display:block;margin-bottom:8px">' + (ctx.role === "parent" ? "Droit de réponse" : "Échanges avec la famille") + "</strong>" + replies +
        '<form class="row" style="margin-top:10px;gap:8px" data-reply="' + id + '"><input class="grow" placeholder="Votre message…" maxlength="1500" style="padding:9px 12px;border-radius:10px;border:1px solid var(--line);background:var(--surface);font:inherit;font-size:13px;color:var(--ink)" required /><button type="submit" class="btn btn-ghost btn-sm">Envoyer</button></form></div>';
      host.querySelector("form").addEventListener("submit", function (e) {
        e.preventDefault();
        var input = this.querySelector("input"), b = this.querySelector("button");
        UI.btnState(b, "loading", "…");
        api.fetch("/incidents/" + id + "/replies", { method: "POST", body: JSON.stringify({ body: input.value.trim() }) }).then(function (rr) {
          if (!rr.ok) { UI.btnState(b, "error"); return UI.toast(rr.body.error || "Impossible.", "error"); }
          UI.btnState(b, "success", "Envoyé"); host.hidden = true; toggleIncident(id, btn);
        });
      });
    });
  }

  // ---------------- Modales ----------------
  function openJustifyModal(date) {
    var m = UI.modal({ title: "Justifier l'absence du " + UI.fmtDate(date), body: '<form id="jForm" class="form-grid"><p class="modal-text full">L\'établissement décide d\'accepter ou non. S\'il accepte, l\'absence devient « justifiée » dans le dossier.</p>' +
      '<div class="field full"><label for="jReason">Motif</label><textarea id="jReason" required maxlength="600" placeholder="Ex. Consultation médicale — certificat joint"></textarea></div>' +
      '<div class="field full"><label for="jFile">Pièce jointe (PDF ou photo, 1,5 Mo max)</label><input type="file" id="jFile" accept="application/pdf,image/png,image/jpeg" /></div><p class="form-error full" id="jErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="jCancel">Annuler</button><button type="submit" form="jForm" class="btn btn-lime btn-sm" id="jSubmit">Envoyer</button>' });
    m.querySelector("#jCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#jForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#jSubmit"), err = m.querySelector("#jErr"); err.hidden = true; UI.btnState(btn, "loading", "Envoi…");
      var file = m.querySelector("#jFile").files[0];
      var payload = { date: date, reason: m.querySelector("#jReason").value.trim() };
      var go = function () {
        api.fetch("/students/" + studentId + "/justifications", { method: "POST", body: JSON.stringify(payload) }).then(function (r) {
          if (!r.ok) { UI.btnState(btn, "error"); err.textContent = r.body.error || "Impossible."; err.hidden = false; return; }
          UI.btnState(btn, "success", "Envoyée"); UI.toast("Justification transmise — l'établissement décidera.", "success");
          setTimeout(function () { UI.closeModal(); load(); }, 500);
        });
      };
      if (file) UI.fileToDataUrl(file, 1500 * 1024).then(function (d) { payload.attachment_data = d; payload.attachment_name = file.name; go(); }, function (e2) { UI.btnState(btn, "error"); err.textContent = e2.message; err.hidden = false; });
      else go();
    });
  }

  function decideJustification(id, status) {
    var accepted = status === "accepted";
    var m = UI.modal({ title: accepted ? "Accepter la justification" : "Refuser la justification", body: '<form id="jdForm" class="form-grid"><p class="modal-text full">' + (accepted ? "L'absence sera enregistrée comme <strong>excusée</strong> et le parent sera informé." : "Le parent sera informé du refus. L'absence reste non justifiée.") + '</p><div class="field full"><label for="jdNote">Message au parent (facultatif)</label><input id="jdNote" maxlength="300" /></div></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="jdCancel">Annuler</button><button type="submit" form="jdForm" class="btn ' + (accepted ? "btn-lime" : "btn-danger") + ' btn-sm" id="jdSubmit">' + (accepted ? "Accepter" : "Refuser") + "</button>" });
    m.querySelector("#jdCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#jdForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#jdSubmit"); UI.btnState(btn, "loading");
      api.fetch("/justifications/" + id + "/decide", { method: "POST", body: JSON.stringify({ status: status, note: m.querySelector("#jdNote").value.trim() }) }).then(function (r) {
        if (!r.ok) { UI.btnState(btn, "error"); return UI.toast(r.body.error || "Impossible.", "error"); }
        UI.btnState(btn, "success"); UI.toast(accepted ? "Justification acceptée — absence excusée." : "Justification refusée.", "success");
        setTimeout(function () { UI.closeModal(); load(); }, 500);
      });
    });
  }

  function openAdjustModal() {
    var bal = D.discipline.balance;
    var last = D.discipline.incidents.filter(function (i) { return i.points < 0; })[0];
    var m = UI.modal({ title: "Modifier les points de " + D.student.first_name, body: '<form id="adjForm" class="form-grid">' +
      '<p class="modal-text full">' + (last ? "Dernier retrait : <strong>" + Math.abs(last.points) + " point(s)</strong> pour « " + UI.escapeHtml(last.title) + " » le " + UI.fmtDate(last.occurred_at) + ". " : "") + "Il lui reste <strong>" + bal.remaining + " / " + bal.capital + "</strong> points. Une correction n'efface rien : elle ajoute une ligne tracée.</p>" +
      '<div class="field"><label for="adjPts">Points</label><input id="adjPts" type="number" min="-100" max="100" step="1" required placeholder="Ex. 5 pour rendre 5 points" /><span class="hint">Positif pour rendre des points, négatif pour en retirer.</span></div>' +
      '<div class="field"><label for="adjNotify">Informer le parent</label><select id="adjNotify"><option value="1">Oui</option><option value="0">Non</option></select></div>' +
      '<div class="field full"><label for="adjReason">Motif</label><input id="adjReason" required maxlength="300" placeholder="Ex. Erreur de saisie — points restitués" /></div><p class="form-error full" id="adjErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="adjCancel">Annuler</button><button type="submit" form="adjForm" class="btn btn-lime btn-sm" id="adjSubmit">Enregistrer</button>' });
    m.querySelector("#adjCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#adjForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#adjSubmit"), err = m.querySelector("#adjErr"); err.hidden = true; UI.btnState(btn, "loading");
      api.fetch("/students/" + studentId + "/points-adjust", { method: "POST", body: JSON.stringify({ points: parseInt(m.querySelector("#adjPts").value, 10), reason: m.querySelector("#adjReason").value.trim(), notify_parent: m.querySelector("#adjNotify").value === "1" }) }).then(function (r) {
        if (!r.ok) { UI.btnState(btn, "error"); err.textContent = r.body.error || "Impossible."; err.hidden = false; return; }
        UI.btnState(btn, "success");
        UI.toast("Correction enregistrée — il lui reste " + r.body.balance.remaining + " points." + (r.body.crossed && r.body.crossed.length ? " Seuil franchi : " + r.body.crossed[0].label + "." : ""), r.body.crossed && r.body.crossed.length ? "error" : "success", 5000);
        setTimeout(function () { UI.closeModal(); load(); }, 500);
      });
    });
  }

  function openConvocationModal(incidentId) {
    var m = UI.modal({ title: "Convoquer les parents", body: '<form id="cvForm" class="form-grid"><p class="modal-text full">Le ou les responsables reçoivent une notification immédiate avec la date, l\'heure et le motif.</p>' +
      '<div class="field"><label for="cvDate">Date</label><input id="cvDate" type="date" required min="' + UI.todayIso() + '" value="' + UI.todayIso() + '" /></div>' +
      '<div class="field"><label for="cvTime">Heure</label><input id="cvTime" type="time" value="09:00" /></div>' +
      '<div class="field full"><label for="cvMotif">Motif</label><input id="cvMotif" required maxlength="300" placeholder="Ex. Entretien suite aux faits du 8 septembre" /></div><p class="form-error full" id="cvErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="cvCancel">Annuler</button><button type="submit" form="cvForm" class="btn btn-lime btn-sm" id="cvSubmit">Convoquer</button>' });
    m.querySelector("#cvCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#cvForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#cvSubmit"), err = m.querySelector("#cvErr"); err.hidden = true; UI.btnState(btn, "loading");
      api.fetch("/convocations", { method: "POST", body: JSON.stringify({ student_id: studentId, incident_id: incidentId || null, scheduled_on: m.querySelector("#cvDate").value, scheduled_time: m.querySelector("#cvTime").value, motif: m.querySelector("#cvMotif").value.trim() }) }).then(function (r) {
        if (!r.ok) { UI.btnState(btn, "error"); err.textContent = r.body.error || "Impossible."; err.hidden = false; return; }
        UI.btnState(btn, "success"); UI.toast("Convocation envoyée aux responsables.", "success");
        setTimeout(function () { UI.closeModal(); load(); }, 500);
      });
    });
  }

  function openIncidentStatusModal(incidentId) {
    var inc = D.discipline.incidents.find(function (i) { return i.id === incidentId; }) || {};
    var m = UI.modal({ title: "Suite donnée", body: '<form id="isForm" class="form-grid"><p class="modal-text full">La décision est humaine et tracée. Le parent n\'est informé que si l\'incident lui a été communiqué.</p>' +
      '<div class="field"><label for="isStatus">Statut</label><select id="isStatus"><option value="open"' + (inc.status === "open" ? " selected" : "") + '>Ouvert</option><option value="convocation"' + (inc.status === "convocation" ? " selected" : "") + '>Convocation</option><option value="decided"' + (inc.status === "decided" ? " selected" : "") + '>Décidé</option><option value="closed"' + (inc.status === "closed" ? " selected" : "") + '>Clos</option></select></div>' +
      '<div class="field full"><label for="isAction">Mesure décidée (communicable)</label><input id="isAction" maxlength="500" value="' + UI.escapeHtml(inc.action_taken || "") + '" placeholder="Ex. Travaux d\'intérêt général, entretien avec la Direction" /></div><p class="form-error full" id="isErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="isCancel">Annuler</button><button type="submit" form="isForm" class="btn btn-lime btn-sm" id="isSubmit">Enregistrer</button>' });
    m.querySelector("#isCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#isForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#isSubmit"), err = m.querySelector("#isErr"); err.hidden = true; UI.btnState(btn, "loading");
      api.fetch("/incidents/" + incidentId + "/status", { method: "POST", body: JSON.stringify({ status: m.querySelector("#isStatus").value, action_taken: m.querySelector("#isAction").value.trim() }) }).then(function (r) {
        if (!r.ok) { UI.btnState(btn, "error"); err.textContent = r.body.error || "Impossible."; err.hidden = false; return; }
        UI.btnState(btn, "success"); UI.toast("Suite enregistrée.", "success");
        setTimeout(function () { UI.closeModal(); load(); }, 500);
      });
    });
  }

  function openConductModal() {
    var b = D.bulletin, c = b.conduct || {};
    api.fetch("/discipline/thresholds").then(function (r) {
      var scale = r.ok && r.body.conduct_scale ? r.body.conduct_scale : [];
      var m = UI.modal({ title: "Cote de conduite — " + UI.escapeHtml(b.period || ""), body: '<form id="cdForm" class="form-grid">' +
        '<p class="modal-text full">Calculée : <strong>' + UI.escapeHtml(c.computed || "—") + "</strong> (" + c.remaining + "/" + c.capital + " points). Le conseil de classe peut la fixer autrement — la valeur calculée reste visible.</p>" +
        '<div class="field full"><label for="cdLabel">Cote retenue</label><select id="cdLabel">' + (scale.length ? scale.map(function (s) { return '<option value="' + UI.escapeHtml(s[1]) + '"' + (c.label === s[1] ? " selected" : "") + ">" + UI.escapeHtml(s[1]) + "</option>"; }).join("") : '<option value="Très bien">Très bien</option><option value="Bien">Bien</option><option value="Assez bien">Assez bien</option><option value="Passable">Passable</option><option value="Insuffisant">Insuffisant</option>') + "</select></div>" +
        '<div class="field full"><label for="cdNote">Motivation (facultative)</label><input id="cdNote" maxlength="300" value="' + UI.escapeHtml(c.note || "") + '" /></div></form>',
        footer: '<button type="button" class="btn btn-ghost btn-sm" id="cdCancel">Annuler</button>' + (c.overridden ? '<button type="button" class="btn btn-danger btn-sm" id="cdClear">Revenir au calcul</button>' : "") + '<button type="submit" form="cdForm" class="btn btn-lime btn-sm" id="cdSubmit">Enregistrer</button>' });
      m.querySelector("#cdCancel").addEventListener("click", UI.closeModal);
      var send = function (payload, btn) {
        UI.btnState(btn, "loading");
        api.fetch("/students/" + studentId + "/conduct", { method: "PUT", body: JSON.stringify(payload) }).then(function (rr) {
          if (!rr.ok) { UI.btnState(btn, "error"); return UI.toast(rr.body.error || "Impossible.", "error"); }
          UI.btnState(btn, "success"); UI.toast("Cote de conduite enregistrée.", "success");
          setTimeout(function () { UI.closeModal(); load(); }, 500);
        });
      };
      var cc = m.querySelector("#cdClear"); if (cc) cc.addEventListener("click", function () { send({ period: b.period, clear: true }, cc); });
      m.querySelector("#cdForm").addEventListener("submit", function (e) { e.preventDefault(); send({ period: b.period, label: m.querySelector("#cdLabel").value, note: m.querySelector("#cdNote").value.trim() }, m.querySelector("#cdSubmit")); });
    });
  }

  function openDecisionModal() {
    var d = D.bulletin.decision || {};
    var m = UI.modal({ title: "Décision de fin d'année", body: '<form id="dcForm" class="form-grid"><p class="modal-text full">Décision de la Direction. Les responsables en sont informés si vous le souhaitez.</p>' +
      '<div class="field"><label for="dcDec">Décision</label><select id="dcDec"><option value="admis"' + (d.decision === "admis" ? " selected" : "") + '>Admis(e)</option><option value="ajourne"' + (d.decision === "ajourne" ? " selected" : "") + '>Ajourné(e)</option><option value="doublant"' + (d.decision === "doublant" ? " selected" : "") + ">Doublant(e)</option></select></div>" +
      '<div class="field"><label for="dcMention">Mention</label><input id="dcMention" maxlength="40" value="' + UI.escapeHtml(d.mention || "") + '" placeholder="Ex. Distinction" /></div>' +
      '<div class="field full"><label for="dcNote">Observation</label><input id="dcNote" maxlength="300" value="' + UI.escapeHtml(d.note || "") + '" /></div>' +
      '<label class="check full"><input type="checkbox" id="dcNotify" checked /> Informer les responsables</label></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="dcCancel">Annuler</button><button type="submit" form="dcForm" class="btn btn-lime btn-sm" id="dcSubmit">Enregistrer</button>' });
    m.querySelector("#dcCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#dcForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#dcSubmit"); UI.btnState(btn, "loading");
      api.fetch("/students/" + studentId + "/decision", { method: "PUT", body: JSON.stringify({ decision: m.querySelector("#dcDec").value, mention: m.querySelector("#dcMention").value.trim(), note: m.querySelector("#dcNote").value.trim(), notify: m.querySelector("#dcNotify").checked }) }).then(function (r) {
        if (!r.ok) { UI.btnState(btn, "error"); return UI.toast(r.body.error || "Impossible.", "error"); }
        UI.btnState(btn, "success"); UI.toast("Décision enregistrée.", "success");
        setTimeout(function () { UI.closeModal(); load(); }, 500);
      });
    });
  }

  function openReportModal() {
    var m = UI.modal({ title: "Signaler au Directeur des disciplines", body: '<form id="rpForm" class="form-grid"><p class="modal-text full">Vous décrivez les faits ; le DD qualifie et décide des points et des suites. Vous serez informé(e) de la décision.</p>' +
      '<div class="field"><label for="rpDate">Date des faits</label><input id="rpDate" type="date" required max="' + UI.todayIso() + '" value="' + UI.todayIso() + '" /></div>' +
      '<div class="field full"><label for="rpDesc">Description</label><textarea id="rpDesc" required maxlength="1500" placeholder="Ce qui s\'est passé, où, quand, qui était présent."></textarea></div><p class="form-error full" id="rpErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="rpCancel">Annuler</button><button type="submit" form="rpForm" class="btn btn-lime btn-sm" id="rpSubmit">Envoyer au DD</button>' });
    m.querySelector("#rpCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#rpForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#rpSubmit"), err = m.querySelector("#rpErr"); err.hidden = true; UI.btnState(btn, "loading");
      api.fetch("/incident-reports", { method: "POST", body: JSON.stringify({ student_id: studentId, description: m.querySelector("#rpDesc").value.trim(), occurred_at: m.querySelector("#rpDate").value }) }).then(function (r) {
        if (!r.ok) { UI.btnState(btn, "error"); err.textContent = r.body.error || "Impossible."; err.hidden = false; return; }
        UI.btnState(btn, "success", "Envoyé"); UI.toast("Signalement transmis au Directeur des disciplines.", "success");
        setTimeout(UI.closeModal, 600);
      });
    });
  }

  function printAttestation() {
    api.fetch("/students/" + studentId + "/attestation").then(function (r) {
      if (!r.ok) return UI.toast(r.body.error || "Impossible de générer l'attestation.", "error");
      var a = r.body, s = a.student;
      var el = document.createElement("div");
      el.className = "print-sheet";
      el.innerHTML = '<div class="ps-head"><div class="ps-school">' + (a.school.logo_data ? '<img src="' + UI.escapeHtml(a.school.logo_data) + '" alt="" style="height:54px;border-radius:8px" />' : "") + "<strong>" + UI.escapeHtml(a.school.name) + "</strong><span>" + UI.escapeHtml([a.school.address, a.school.phone, a.school.email].filter(Boolean).join(" · ")) + '</span></div><div style="text-align:right"><h2>ATTESTATION</h2><span class="muted">de fréquentation scolaire</span></div></div>' +
        "<p>Je soussigné(e) <strong>" + UI.escapeHtml(a.director || "la Direction") + "</strong>, atteste que l'élève :</p>" +
        '<dl class="dl"><dt>Nom et prénom</dt><dd><strong>' + UI.escapeHtml(s.last_name + " " + s.first_name) + "</strong></dd><dt>Identifiant</dt><dd>" + UI.escapeHtml(s.code || "—") + "</dd><dt>Date de naissance</dt><dd>" + (s.birth_date ? UI.fmtDate(s.birth_date) : "—") + "</dd><dt>Classe</dt><dd>" + UI.escapeHtml(s.class_name || "—") + "</dd><dt>Année scolaire</dt><dd>" + UI.escapeHtml(a.academic_year) + "</dd></dl>" +
        "<p>est régulièrement inscrit(e) dans notre établissement" + (a.attendance.total ? " et présente un taux de présence de <strong>" + a.attendance.rate + " %</strong> sur " + a.attendance.total + " jour(s) d'appel enregistrés" : "") + ".</p>" +
        '<p>En foi de quoi la présente attestation lui est délivrée pour servir et valoir ce que de droit.</p><p class="ps-foot">Fait le ' + UI.fmtDate(a.issued_on) + ' — document généré par Klassio à partir des données réelles de l\'établissement.</p><div style="margin-top:48px;text-align:right"><span class="muted">Signature et sceau</span></div>';
      document.body.appendChild(el);
      UI.printSheet(el, "Attestation — " + s.first_name + " " + s.last_name);
      setTimeout(function () { el.remove(); }, 1000);
    });
  }

  // Enregistrement d'un paiement par la DIRECTION uniquement. Le parcours du
  // parent vit dans `page-paiements.js` — un seul écran de paiement par rôle.
  function openPayModal(obId, remaining, label) {
    var parent = false;
    var m = UI.modal({ title: "Enregistrer un paiement", body:
      '<p class="modal-text" style="margin-bottom:12px">' + UI.escapeHtml(label) + " — reste " + UI.money(remaining, D.finance.currency) + "</p>" +
      '<form id="payForm" class="form-grid"><div class="field"><label for="payAmount">Montant</label><input id="payAmount" type="number" step="0.01" min="0.01" max="' + remaining + '" value="' + remaining + '" required /></div>' +
      '<div class="field"><label for="payMethod">Moyen</label><select id="payMethod"' + (parent ? " disabled" : "") + ">" + (parent ? '<option value="mobile_money">Mobile Money</option>' : '<option value="cash">Espèces</option><option value="bank">Banque</option><option value="mobile_money">Mobile Money</option>') + "</select></div>" +
      (parent ? '<p class="note-inline full">' + UI.icon("info", 15) + "<span>Votre demande est transmise à l'établissement. Le paiement n'est comptabilisé qu'après confirmation réelle de la transaction — vous recevrez alors une notification et votre reçu.</span></p>" : '<p class="note-inline full">' + UI.icon("info", 15) + "<span>Espèces et banque sont confirmés immédiatement (vous en êtes la preuve) et génèrent un reçu. Un Mobile Money reste en attente jusqu'à vérification.</span></p>") +
      '<p class="form-error full" id="payErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="payCancel">Annuler</button><button type="submit" form="payForm" class="btn btn-lime btn-sm" id="paySubmit">' + (parent ? "Envoyer la demande" : "Enregistrer") + "</button>" });
    m.querySelector("#payCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#payForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#paySubmit"), err = m.querySelector("#payErr");
      err.hidden = true; UI.btnState(btn, "loading", parent ? "Envoi…" : "Enregistrement…");
      var amount = parseFloat(m.querySelector("#payAmount").value), method = parent ? "mobile_money" : m.querySelector("#payMethod").value;
      api.fetch("/payments", { method: "POST", body: JSON.stringify({ obligation_id: obId, amount: amount, method: method, idempotency_key: "ui-" + obId + "-" + Date.now() }) }).then(function (res) {
        if (!res.ok) { UI.btnState(btn, "error"); err.textContent = res.body.error || "Impossible d'enregistrer ce paiement."; err.hidden = false; return; }
        UI.btnState(btn, "success", res.body.status === "CONFIRMED" ? "Enregistré" : "Demande envoyée");
        UI.toast(res.body.status === "CONFIRMED" ? "Paiement confirmé" + (res.body.receipt_number ? " — reçu " + res.body.receipt_number : "") : "Demande de paiement transmise à l'établissement.", "success");
        setTimeout(function () { UI.closeModal(); load(); }, 600);
      }).catch(function () { UI.btnState(btn, "error"); err.textContent = "Le serveur Klassio est injoignable."; err.hidden = false; });
    });
  }

  // Créer un frais, éventuellement RÉPARTI EN TRANCHES.
  //
  // Une tranche n'est pas un nouvel objet : c'est une obligation de plus, avec
  // sa propre échéance. Trois obligations sur le même article de catalogue sont
  // les trois tranches d'un même frais — c'est ainsi que l'échéancier du parent
  // se reconstitue (`financial_summary` renvoie `catalog_item_id`). Aucune table
  // `installments` n'a été ajoutée : le Financial Core ne se double pas d'un
  // second modèle financier parallèle.
  //
  // Le nombre de tranches n'est écrit nulle part : l'école en met une, deux,
  // dix. La répartition proposée est régulière, et le dernier reste ajusté pour
  // que la somme tombe EXACTEMENT sur le total — un arrondi qui laisse traîner
  // 0,01 $ produit une dette d'un centime que personne ne peut solder.
  function openObligationModal() {
    api.fetch("/catalog-items").then(function (res) {
      var items = (res.body || []).filter(function (i) { return i.category !== "boutique"; });
      if (!items.length) return UI.toast("Créez d'abord un article de catalogue dans Finance.", "error");

      var m = UI.modal({ title: "Ajouter un frais", size: "lg", body:
        '<form id="obForm" class="form-grid">' +
        '<div class="field full"><label for="obItem">Article du catalogue</label><select id="obItem">' +
          items.map(function (i) { return '<option value="' + i.id + '" data-amount="' + i.amount + '" data-cur="' + UI.escapeHtml(i.currency) + '">' + UI.escapeHtml(i.name) + " — " + UI.money(i.amount, i.currency) + "</option>"; }).join("") + "</select></div>" +
        '<div class="field"><label for="obAmount">Montant total</label><input id="obAmount" type="number" step="0.01" min="0.01" placeholder="Prix catalogue" /><span class="hint">Vide = prix du catalogue.</span></div>' +
        '<div class="field"><label for="obCount">Nombre de tranches</label><input id="obCount" type="number" min="1" max="12" value="1" /><span class="hint">1 = paiement en une fois.</span></div>' +
        '<div class="field full" id="obEcheances"></div>' +
        '<p class="form-error full" id="obErr" hidden></p></form>',
        footer: '<button type="button" class="btn btn-ghost btn-sm" id="obCancel">Annuler</button><button type="submit" form="obForm" class="btn btn-lime btn-sm" id="obSubmit">Créer</button>' });
      m.querySelector("#obCancel").addEventListener("click", UI.closeModal);

      var sel = m.querySelector("#obItem"), champMontant = m.querySelector("#obAmount"), champNb = m.querySelector("#obCount");

      function totalChoisi() {
        var saisi = parseFloat(champMontant.value);
        if (saisi > 0) return saisi;
        return parseFloat(sel.options[sel.selectedIndex].dataset.amount) || 0;
      }
      function devise() { return sel.options[sel.selectedIndex].dataset.cur || D.finance.currency; }

      // Répartition : parts égales arrondies au centime, le dernier absorbe le
      // reliquat. 1000 / 3 donne 333,33 + 333,33 + 333,34, pas trois fois 333,33.
      function repartir(total, n) {
        var part = Math.floor((total / n) * 100) / 100, parts = [];
        for (var i = 0; i < n - 1; i++) parts.push(part);
        parts.push(Math.round((total - part * (n - 1)) * 100) / 100);
        return parts;
      }

      function dessinerEcheances() {
        var n = Math.max(1, Math.min(12, parseInt(champNb.value, 10) || 1));
        var parts = repartir(totalChoisi(), n), cur = devise();
        m.querySelector("#obEcheances").innerHTML =
          '<label>' + (n > 1 ? "Échéancier — " + UI.plural(n, "tranche") : "Échéance") + "</label>" +
          '<div class="tranche-liste">' + parts.map(function (p, i) {
            return '<div class="tranche-ligne">' +
              '<span class="tl-num">' + (n > 1 ? "Tranche " + (i + 1) : "Montant") + "</span>" +
              '<input type="number" class="tl-montant" step="0.01" min="0.01" value="' + p + '" data-i="' + i + '" aria-label="Montant de la tranche ' + (i + 1) + '" />' +
              '<span class="tl-cur">' + UI.escapeHtml(cur) + "</span>" +
              '<input type="date" class="tl-date" data-i="' + i + '" aria-label="Échéance de la tranche ' + (i + 1) + '" />' +
              "</div>";
          }).join("") + "</div>" +
          '<span class="hint" id="obSomme"></span>';
        verifierSomme();
        m.querySelectorAll(".tl-montant").forEach(function (c) { c.addEventListener("input", verifierSomme); });
      }

      // La somme des tranches doit retomber sur le total. On le dit à l'écran —
      // le serveur, lui, ne connaît que des obligations indépendantes : rien ne
      // l'empêcherait d'en créer trois qui ne font pas le compte.
      function verifierSomme() {
        var total = totalChoisi();
        var somme = Array.prototype.reduce.call(m.querySelectorAll(".tl-montant"),
          function (t, c) { return t + (parseFloat(c.value) || 0); }, 0);
        somme = Math.round(somme * 100) / 100;
        var el = m.querySelector("#obSomme");
        var ecart = Math.round((somme - total) * 100) / 100;
        el.textContent = ecart === 0
          ? "Somme des tranches : " + UI.money(somme, devise()) + " — conforme au total."
          : "Somme des tranches : " + UI.money(somme, devise()) + " — " + (ecart > 0 ? "dépasse" : "inférieure au") + " total de " + UI.money(Math.abs(ecart), devise()) + ".";
        el.className = ecart === 0 ? "hint" : "hint hint-alerte";
      }

      sel.addEventListener("change", dessinerEcheances);
      champMontant.addEventListener("input", dessinerEcheances);
      champNb.addEventListener("input", dessinerEcheances);
      dessinerEcheances();

      m.querySelector("#obForm").addEventListener("submit", function (e) {
        e.preventDefault();
        var btn = m.querySelector("#obSubmit"), err = m.querySelector("#obErr");
        err.hidden = true;
        var montants = Array.prototype.map.call(m.querySelectorAll(".tl-montant"), function (c) { return parseFloat(c.value); });
        var dates = Array.prototype.map.call(m.querySelectorAll(".tl-date"), function (c) { return c.value || null; });
        if (montants.some(function (v) { return !(v > 0); })) {
          err.textContent = "Chaque tranche doit porter un montant strictement positif."; err.hidden = false; return;
        }
        UI.btnState(btn, "loading", "Création…");
        // UN SEUL appel : le serveur vérifie que la somme des tranches tombe sur
        // le total, et écrit tout ou rien. En N appels successifs, la troisième
        // tranche pouvait échouer après l'écriture des deux premières — et il
        // fallait raconter un demi-succès à l'utilisateur.
        api.fetch("/academic-years").then(function (y) {
          return api.fetch("/obligations/schedule", { method: "POST", body: JSON.stringify({
            student_id: studentId,
            catalog_item_id: sel.value,
            academic_year_id: y.body[0] && y.body[0].id,
            total: totalChoisi(),
            installments: montants.map(function (montant, i) {
              return { amount: montant, due_date: dates[i] || null };
            }),
          }) });
        }).then(function (res) {
          if (!res.ok) {
            UI.btnState(btn, "error");
            err.textContent = res.body.error || "Erreur.";
            err.hidden = false;
            return;
          }
          UI.btnState(btn, "success", "Créé");
          UI.toast(res.body.count > 1 ? UI.plural(res.body.count, "tranche créée", "tranches créées") + "." : "Frais créé.", "success");
          setTimeout(function () { UI.closeModal(); load(); }, 500);
        }).catch(function () {
          UI.btnState(btn, "error");
          err.textContent = "Le serveur Klassio est injoignable.";
          err.hidden = false;
        });
      });
    });
  }

  function openEditModal() {
    api.fetch("/classes").then(function (res) {
      var classes = res.body || [], s = D.student;
      var m = UI.modal({ title: "Modifier le dossier", body:
        '<form id="editForm" class="form-grid"><div class="field"><label for="eFirst">Prénom</label><input id="eFirst" value="' + UI.escapeHtml(s.first_name) + '" required /></div><div class="field"><label for="eLast">Nom</label><input id="eLast" value="' + UI.escapeHtml(s.last_name) + '" required /></div>' +
        '<div class="field"><label for="eClass">Classe</label><select id="eClass"><option value="">Non affecté</option>' + classes.map(function (c) { return '<option value="' + c.id + '"' + (s.class && s.class.id === c.id ? " selected" : "") + ">" + UI.escapeHtml(c.name) + "</option>"; }).join("") + "</select></div>" +
        '<div class="field"><label for="eGender">Genre</label><select id="eGender"><option value="">—</option><option value="F"' + (s.gender === "F" ? " selected" : "") + '>Fille</option><option value="M"' + (s.gender === "M" ? " selected" : "") + ">Garçon</option></select></div>" +
        '<div class="field"><label for="eBirth">Date de naissance</label><input id="eBirth" type="date" value="' + UI.escapeHtml(s.birth_date || "") + '" /></div>' +
        '<div class="field"><label for="eStatus">Statut</label><select id="eStatus"><option value="active"' + (s.status === "active" ? " selected" : "") + '>Actif</option><option value="archived"' + (s.status === "archived" ? " selected" : "") + '>Archivé</option><option value="transferred"' + (s.status === "transferred" ? " selected" : "") + ">Transféré</option></select></div>" +
        '<p class="form-error full" id="editErr" hidden></p></form>',
        footer: '<button type="button" class="btn btn-ghost btn-sm" id="editCancel">Annuler</button><button type="submit" form="editForm" class="btn btn-lime btn-sm" id="editSubmit">Enregistrer</button>' });
      m.querySelector("#editCancel").addEventListener("click", UI.closeModal);
      m.querySelector("#editForm").addEventListener("submit", function (e) {
        e.preventDefault();
        var btn = m.querySelector("#editSubmit"), err = m.querySelector("#editErr");
        UI.btnState(btn, "loading");
        api.fetch("/students/" + studentId, { method: "PUT", body: JSON.stringify({ first_name: m.querySelector("#eFirst").value.trim(), last_name: m.querySelector("#eLast").value.trim(), class_id: m.querySelector("#eClass").value || null,
          gender: m.querySelector("#eGender").value || null, birth_date: m.querySelector("#eBirth").value || null, status: m.querySelector("#eStatus").value }) }).then(function (res2) {
          if (!res2.ok) { UI.btnState(btn, "error"); err.textContent = res2.body.error || "Erreur."; err.hidden = false; return; }
          UI.btnState(btn, "success"); UI.toast("Dossier mis à jour.", "success");
          setTimeout(function () { UI.closeModal(); load(); }, 500);
        });
      });
    });
  }
})();
