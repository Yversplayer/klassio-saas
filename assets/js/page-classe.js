// KLASSIO — Classe : élèves, appel (« qui n'est pas là », puis envoi qui
// informe les parents), notes ou appréciations selon le cycle, conseil de
// classe, livres & devoirs, horaire & examens, enseignants, finances.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var classId = UI.qs("id"), ctx = null, C = null, students = [], team = [], tabsCtl = null;
  var results = null, apprDomains = [], apprExisting = [], resources = [];
  if (!classId) { window.location.href = "classes.html"; return; }

  var LEVELS = { 1: "En construction", 2: "En cours d'acquisition", 3: "Acquis", 4: "Dépassé" };
  var LEVEL_SHORT = { 1: "EC", 2: "ECA", 3: "A", 4: "D" };

  admin.initShell("classes").then(function (c) {
    ctx = c;
    document.getElementById("backLink").innerHTML = UI.icon("chevronLeft", 15) + (c.role === "professeur" ? "Mes classes" : "Retour aux classes");
    load();
  });

  function isMaternelle() { return C && C.cycle === "maternelle"; }
  function canCouncil() { return ctx.role === "directeur" || (ctx.role === "professeur" && C.is_titulaire); }

  function load() {
    document.getElementById("classHead").innerHTML = UI.skeleton("card", 1);
    document.getElementById("classPanels").innerHTML = UI.skeleton("row", 6);
    var calls = [api.fetch("/classes/" + classId), api.fetch("/classes/" + classId + "/students"), api.fetch("/resources?class_id=" + classId)];
    if (ctx.role === "directeur") calls.push(api.fetch("/team"));
    Promise.all(calls).then(function (r) {
      if (!r[0].ok) {
        document.getElementById("classHead").innerHTML = "";
        document.getElementById("classPanels").innerHTML = UI.emptyState("Classe introuvable ou accès non autorisé", r[0].body.error || "", '<a href="classes.html" class="btn btn-ghost btn-sm">Retour</a>', "lock");
        return;
      }
      C = r[0].body; students = r[1].ok ? r[1].body.students : []; C.finance_visible = r[1].ok ? r[1].body.finance_visible : false;
      resources = r[2].ok ? r[2].body : [];
      team = r[3] && r[3].ok ? r[3].body.filter(function (m) { return m.role === "professeur"; }) : [];
      var done = function () { renderHead(); renderTabs(); };
      if (ctx.role !== "parent") {
        var extra = [api.fetch("/classes/" + classId + "/results")];
        if (isMaternelle() && ctx.role !== "discipline") extra.push(api.fetch("/appreciations/domains"), api.fetch("/classes/" + classId + "/appreciations"));
        Promise.all(extra).then(function (x) {
          results = x[0] && x[0].ok ? x[0].body : null;
          apprDomains = x[1] && x[1].ok ? x[1].body.domains : [];
          apprExisting = x[2] && x[2].ok ? x[2].body : [];
          done();
        });
      } else done();
    }).catch(function () { admin.loadError(document.getElementById("classPanels"), load, "Le serveur Klassio est injoignable"); });
  }

  function renderHead() {
    var at = C.attendance_today;
    var actions = "";
    if (ctx.role === "directeur") actions += '<button type="button" class="btn btn-ghost btn-sm" id="editClassBtn">' + UI.icon("edit", 15) + "Modifier</button>";
    if (ctx.role !== "parent") actions += '<a href="registres.html?class_id=' + classId + '" class="btn btn-ghost btn-sm">' + UI.icon("print", 15) + "Registre</a>";
    if (ctx.role !== "parent") actions += '<button type="button" class="btn btn-lime btn-sm" id="goRoll">' + UI.icon("clipboard", 15) + (at.recorded ? "Modifier l'appel" : "Faire l'appel") + "</button>";
    // Le fil d'Ariane de la topbar se complète ici : la coquille connaît la
    // section, seule cette page connaît la classe.
    admin.setContext(C.name);
    document.getElementById("classHead").innerHTML = '<div class="dossier-head"><div><h1>' + UI.escapeHtml(C.name) + '</h1><div class="dh-meta">' + (C.cycle ? UI.badge(C.cycle) : "") + (C.level ? "<span>Niveau " + UI.escapeHtml(C.level) + "</span>" : "") +
      "<span>" + UI.icon("user", 14) + " " + (C.titulaire ? "Titulaire : " + UI.escapeHtml(C.titulaire.name) : "Sans titulaire") + "</span>" + (C.is_titulaire ? UI.badge("ok", "Vous êtes titulaire") : "") + "</div></div>" +
      '<div class="dh-actions">' + actions + '</div><div class="dh-kpis"><div class="dh-kpi"><span class="k">Élèves</span><span class="v">' + C.student_count + '</span></div><div class="dh-kpi"><span class="k">Appel du jour</span><span class="v">' + (at.recorded ? at.recorded + " / " + C.student_count : "Non fait") + '</span></div><div class="dh-kpi"><span class="k">Absents</span><span class="v ' + (at.absent ? "text-warn" : "") + '">' + at.absent + '</span></div><div class="dh-kpi"><span class="k">Retards</span><span class="v">' + at.late + '</span></div><div class="dh-kpi"><span class="k">Enseignants</span><span class="v">' + C.teachers.length + "</span></div></div></div>";
    var e = document.getElementById("editClassBtn"); if (e) e.addEventListener("click", openEditClass);
    var g = document.getElementById("goRoll"); if (g) g.addEventListener("click", function () { tabsCtl.activate("presence"); });
  }

  function renderTabs() {
    var defs = [["eleves", "Élèves", "students"]];
    if (ctx.role !== "parent") defs.push(["presence", "Présence", "clipboard"]);
    if ((ctx.role === "directeur" || ctx.role === "professeur") && !isMaternelle()) defs.push(["notes", "Notes", "book"]);
    if ((ctx.role === "directeur" || ctx.role === "professeur") && isMaternelle()) defs.push(["appreciations", "Appréciations", "book"]);
    if (ctx.role !== "parent" && results) defs.push(["conseil", "Conseil de classe", "reports"]);
    if (ctx.role === "directeur" || ctx.role === "professeur") defs.push(["ressources", "Livres & devoirs", "book"]);
    defs.push(["horaire", "Horaire & examens", "clock"]);
    if (ctx.role === "directeur") defs.push(["enseignants", "Enseignants", "users"]);
    if (C.finance_visible) defs.push(["situation", "Situation financière", "finance"]);
    document.getElementById("classTabs").innerHTML = defs.map(function (d) { return '<button type="button" class="tab-btn" data-tab="' + d[0] + '">' + UI.icon(d[2], 15) + d[1] + "</button>"; }).join("");
    document.getElementById("classPanels").innerHTML = defs.map(function (d) { return '<div data-tab-panel="' + d[0] + '" hidden></div>'; }).join("");
    defs.forEach(function (d) { document.querySelector('[data-tab-panel="' + d[0] + '"]').innerHTML = renderers[d[0]](); });
    tabsCtl = UI.tabs(document.getElementById("classTabs"), function (n) { history.replaceState(null, "", "?id=" + classId + "&tab=" + n); });
    var wanted = UI.qs("tab"), names = defs.map(function (d) { return d[0]; });
    tabsCtl.activate(names.indexOf(wanted) >= 0 ? wanted : names[0], true);
    wire();
    UI.wireHrefs(document.getElementById("classPanels"));
  }

  var renderers = {
    eleves: function () {
      if (!students.length) return '<div class="panel">' + UI.emptyState("Aucun élève dans cette classe", ctx.role === "directeur" ? "Affectez des élèves depuis leur dossier (Modifier → Classe) ou ajoutez-en depuis Élèves." : "", "", "students") + "</div>";
      var staff = ctx.role !== "parent";
      return '<div class="panel compact"><div class="toolbar" style="margin-bottom:10px"><label class="search" for="clsSearch">' + UI.icon("search", 16) + '<input id="clsSearch" type="search" placeholder="Rechercher dans la classe…" /></label><span class="count-label">' + UI.plural(students.length, "élève") + "</span></div>" +
        (staff ? '<p class="muted" style="margin-bottom:10px">Absences justifiées et non justifiées, retards, points de conduite restants : tout ce qui est visible ici a été décidé par un humain.</p>' : "") +
        '<div class="table-wrap"><table class="data-table responsive" id="clsTable"><thead><tr><th>Élève</th><th>Identifiant</th><th>Aujourd\'hui</th>' + (staff ? "<th>Absences</th><th>Conduite</th>" : "") + (C.finance_visible ? '<th class="num">Solde</th>' : "") + '<th class="actions"></th></tr></thead><tbody>' +
        students.map(function (s) {
          var report = ctx.role === "professeur" ? '<button type="button" class="btn btn-ghost btn-xs report-btn" data-id="' + s.id + '" data-name="' + UI.escapeHtml(s.first_name + " " + s.last_name) + '">Signaler</button> ' : "";
          return '<tr data-name="' + UI.escapeHtml((s.first_name + " " + s.last_name + " " + (s.code || "")).toLowerCase()) + '"><td data-label="Élève"><a class="cell-main" href="eleve-dossier.html?id=' + s.id + '" style="color:inherit;text-decoration:none">' + UI.avatar(s, 30) + UI.escapeHtml(s.last_name + " " + s.first_name) + '</a></td><td data-label="Identifiant"><span class="chip-code">' + UI.escapeHtml(s.code || "") + '</span></td><td data-label="Aujourd\'hui">' + (s.attendance_status ? UI.badge(s.attendance_status) : '<span class="muted">—</span>') + "</td>" +
            (staff ? '<td data-label="Absences"><span class="pill-row">' + (s.absences_unjustified ? UI.badge("bad", s.absences_unjustified + " non just.") : "") + (s.absences_justified ? UI.badge("neutral", s.absences_justified + " just.") : "") + (s.lates ? UI.badge("warn", s.lates + " retard" + (s.lates > 1 ? "s" : "")) : "") + (!s.absences_unjustified && !s.absences_justified && !s.lates ? '<span class="muted">Assidu(e)</span>' : "") + "</span></td>" +
              '<td data-label="Conduite">' + (s.points_remaining != null ? UI.badge(s.points_remaining >= s.capital * 0.7 ? "ok" : s.points_remaining >= s.capital * 0.4 ? "warn" : "bad", s.points_remaining + " / " + s.capital) + (s.faults ? ' <span class="muted">' + s.faults + " fait(s)</span>" : "") : "—") + "</td>" : "") +
            (C.finance_visible ? '<td data-label="Solde" class="num ' + (s.balance > 0 ? "text-warn" : "text-lime") + '">' + UI.money(s.balance) + "</td>" : "") + '<td class="actions">' + report + '<a class="link-btn" href="eleve-dossier.html?id=' + s.id + '">Dossier</a></td></tr>';
        }).join("") + "</tbody></table></div></div>";
    },

    presence: function () {
      if (!students.length) return '<div class="panel">' + UI.emptyState("Aucun élève à appeler", "", "", "clipboard") + "</div>";
      var today = UI.todayIso();
      var gate = students.filter(function (s) { return s.attendance_status === "late"; }).length;
      return '<div class="panel"><div class="panel-head"><h2>Appel</h2><div class="row"><label for="rollDate" class="count-label">Date</label><input type="date" id="rollDate" value="' + today + '" max="' + today + '" style="height:36px;border-radius:100px;border:1px solid var(--line);padding:0 12px;background:var(--surface);font:inherit;font-size:13px;color:var(--ink)" /></div></div>' +
        '<p class="muted" style="margin-bottom:12px">Tout le monde est présent par défaut : <strong>marquez seulement qui n\'est pas là</strong>, puis envoyez. À l\'envoi, les parents des élèves présents reçoivent « votre enfant est bien à l\'école » (une fois par jour), et les absences partent au Directeur des disciplines.</p>' +
        (gate ? '<p class="note-inline">' + UI.icon("clock", 15) + "<span>" + UI.plural(gate, "retard déjà pointé au portail", "retards déjà pointés au portail") + " — l'heure d'arrivée constatée est conservée même si vous validez « présent ».</span></p>" : "") +
        '<div class="row" style="margin-bottom:12px;margin-top:12px"><button type="button" class="chip" id="allPresent">Tous présents</button><span class="roll-summary" id="rollSummary"></span></div>' +
        '<div class="roll-list" id="rollList">' + students.map(function (s) {
          var st = s.attendance_status || "present";
          return '<div class="roll-row" data-sid="' + s.id + '">' + UI.avatar(s, 34) + '<div class="roll-name">' + UI.escapeHtml(s.last_name + " " + s.first_name) + "<span>" + UI.escapeHtml(s.code || "") + (s.attendance_note ? " · " + UI.escapeHtml(s.attendance_note) : "") + '</span></div><div class="seg" role="radiogroup" aria-label="Statut de ' + UI.escapeHtml(s.first_name) + '">' +
            ["present", "late", "absent", "excused"].map(function (k) { return '<button type="button" data-status="' + k + '" class="' + (st === k ? "active " + k : "") + '" aria-pressed="' + (st === k) + '">' + ({ present: "P", late: "R", absent: "A", excused: "E" })[k] + "</button>"; }).join("") + "</div></div>";
        }).join("") + "</div>" +
        '<div class="sticky-actions"><span class="muted" id="rollHint">P = présent · R = retard · A = absent · E = excusé (justifié)</span><button type="button" class="btn btn-ghost" id="saveRoll">Enregistrer sans notifier</button><button type="button" class="btn btn-lime" id="finalizeRoll">' + UI.icon("check", 16) + "Envoyer l'appel</button></div></div>";
    },

    notes: function () {
      if (!students.length) return '<div class="panel">' + UI.emptyState("Aucun élève", "", "", "book") + "</div>";
      var periodOptions = (results && results.periods ? results.periods : []);
      return '<div class="panel"><div class="panel-head"><h2>Saisir des notes</h2><span class="sub">Une matière, une période, un barème — laissez vide pour un élève absent à l\'évaluation.</span></div>' +
        '<form id="gradesForm"><div class="form-grid" style="margin-bottom:14px"><div class="field"><label for="gSubject">Matière</label><input id="gSubject" required placeholder="Ex. Mathématiques" list="subjectsList" /><datalist id="subjectsList"><option>Mathématiques</option><option>Français</option><option>Sciences</option><option>Histoire</option><option>Géographie</option><option>Anglais</option><option>Éducation civique</option><option>Physique</option><option>Chimie</option><option>Biologie</option></datalist></div>' +
        '<div class="field"><label for="gPeriod">Période</label><input id="gPeriod" required placeholder="Ex. Période 1" list="periodsList" /><datalist id="periodsList">' + (periodOptions.length ? periodOptions.map(function (p) { return "<option>" + UI.escapeHtml(p) + "</option>"; }).join("") : "<option>Période 1</option><option>Période 2</option><option>Examen 1er semestre</option><option>Période 3</option><option>Période 4</option><option>Examen 2e semestre</option>") + "</datalist></div>" +
        '<div class="field"><label for="gMax">Barème (max)</label><input id="gMax" type="number" min="1" max="1000" value="20" required /></div></div>' +
        '<div class="table-wrap"><table class="data-table grades-table"><thead><tr><th>Élève</th><th class="num">Note</th><th>Commentaire</th></tr></thead><tbody>' + students.map(function (s) {
          return '<tr data-sid="' + s.id + '"><td><span class="cell-main">' + UI.escapeHtml(s.last_name + " " + s.first_name) + '</span></td><td class="num"><div class="grade-cell"><input type="number" class="grade-input g-score" step="0.5" min="0" placeholder="—" /><span class="muted">/ <span class="gmax">20</span></span></div></td><td><input class="g-comment" placeholder="Optionnel" style="width:100%;padding:8px 10px;border-radius:8px;border:1px solid var(--line);background:var(--surface-soft);font:inherit;font-size:13px;color:var(--ink)" /></td></tr>';
        }).join("") + "</tbody></table></div>" +
        '<div class="sticky-actions"><p class="form-error" id="gErr" hidden></p><button type="submit" class="btn btn-lime" id="saveGrades">' + UI.icon("check", 16) + "Enregistrer les notes</button></div></form>" +
        '<p class="note-inline">' + UI.icon("info", 15) + "<span>Les notes ne deviennent visibles des parents qu'après <strong>proclamation</strong> de la période par la Direction.</span></p></div>" +
        '<div class="panel"><div class="panel-head"><h2>Notes déjà saisies</h2></div><div id="gradesHistory">' + UI.skeleton("row", 3) + "</div></div>";
    },

    appreciations: function () {
      if (!students.length) return '<div class="panel">' + UI.emptyState("Aucun élève", "", "", "book") + "</div>";
      var existing = {};
      apprExisting.forEach(function (a) { existing[a.period + "|" + a.domain + "|" + a.student_id] = a; });
      return '<div class="panel"><div class="panel-head"><h2>Appréciations — maternelle</h2><span class="sub">Pas de note chiffrée : un niveau par domaine et par élève</span></div>' +
        '<form id="apprForm"><div class="form-grid" style="margin-bottom:14px"><div class="field"><label for="aPeriod">Période</label><input id="aPeriod" required value="' + UI.escapeHtml((results && results.periods && results.periods[results.periods.length - 1]) || "Période 1") + '" /></div>' +
        '<div class="field"><label for="aDomain">Domaine</label><select id="aDomain">' + apprDomains.map(function (d) { return "<option>" + UI.escapeHtml(d) + "</option>"; }).join("") + "</select></div></div>" +
        '<div class="table-wrap"><table class="data-table"><thead><tr><th>Élève</th><th>Niveau</th><th>Commentaire</th></tr></thead><tbody>' + students.map(function (s) {
          return '<tr data-sid="' + s.id + '"><td><span class="cell-main">' + UI.escapeHtml(s.last_name + " " + s.first_name) + '</span></td><td><div class="appr-level">' + [1, 2, 3, 4].map(function (l) { return '<button type="button" data-level="' + l + '" title="' + LEVELS[l] + '">' + LEVEL_SHORT[l] + "</button>"; }).join("") + '</div></td><td><input class="a-comment" placeholder="Optionnel" maxlength="300" style="width:100%;padding:8px 10px;border-radius:8px;border:1px solid var(--line);background:var(--surface-soft);font:inherit;font-size:13px;color:var(--ink)" /></td></tr>';
        }).join("") + "</tbody></table></div>" +
        '<div class="legend" style="margin-top:8px"><span>EC = en construction</span><span>ECA = en cours d\'acquisition</span><span>A = acquis</span><span>D = dépassé</span></div>' +
        '<div class="sticky-actions"><p class="form-error" id="aErr" hidden></p><button type="submit" class="btn btn-lime" id="saveAppr">' + UI.icon("check", 16) + "Enregistrer les appréciations</button></div></form></div>" +
        (apprExisting.length ? '<div class="panel"><div class="panel-head"><h2>Déjà enregistrées</h2></div><div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Période</th><th>Domaine</th><th>Élève</th><th>Niveau</th></tr></thead><tbody>' + apprExisting.slice(0, 80).map(function (a) {
          return '<tr><td data-label="Période">' + UI.escapeHtml(a.period) + '</td><td data-label="Domaine">' + UI.escapeHtml(a.domain) + '</td><td data-label="Élève">' + UI.escapeHtml(a.last_name + " " + a.first_name) + '</td><td data-label="Niveau">' + UI.badge(a.level >= 3 ? "ok" : a.level === 2 ? "warn" : "neutral", LEVELS[a.level]) + "</td></tr>";
        }).join("") + "</tbody></table></div></div>" : "");
    },

    conseil: function () {
      if (!results || !results.students.length) return '<div class="panel">' + UI.emptyState("Aucun résultat pour cette classe", "Saisissez d'abord des notes ou des appréciations.", "", "reports") + "</div>";
      var r = results, threshold = r.pass_threshold || 50;
      var withAvg = r.students.filter(function (s) { return s.percent != null; });
      var passed = withAvg.filter(function (s) { return s.percent >= threshold; }).length;
      var avg = withAvg.length ? Math.round(withAvg.reduce(function (a, s) { return a + s.percent; }, 0) / withAvg.length * 10) / 10 : null;
      var sel = '<select id="resPeriod" style="height:34px;border-radius:100px;border:1px solid var(--line);padding:0 12px;background:var(--surface);font:inherit;font-size:12.5px;color:var(--ink)">' + r.periods.map(function (p) { return '<option value="' + UI.escapeHtml(p) + '"' + (p === r.period ? " selected" : "") + ">" + UI.escapeHtml(p) + "</option>"; }).join("") + "</select>";
      return '<div class="kpi-grid cols-4">' + UI.kpi("Moyenne de classe", avg != null ? avg + " %" : "—", { icon: "reports" }) + UI.kpi("Au-dessus du seuil", passed + " / " + withAvg.length, { icon: "check", tone: passed === withAvg.length ? "ok" : "warn", sub: "seuil de réussite : " + threshold + " %" }) +
        UI.kpi("Élèves classés", String(withAvg.length), { icon: "students" }) + UI.kpi("Période", UI.escapeHtml(r.period || "—"), { icon: "calendar" }) + "</div>" +
        '<div class="panel"><div class="panel-head"><h2>Conseil de classe</h2><div class="row no-print">' + sel + '<button type="button" class="btn btn-ghost btn-sm" id="printCouncil">' + UI.icon("print", 15) + "Imprimer</button><button type=\"button\" class=\"btn btn-ghost btn-sm\" id=\"printBulletins\">" + UI.icon("book", 15) + "Bulletins de la classe</button></div></div>" +
        '<div id="councilSheet" class="print-sheet"><div class="ps-head"><div class="ps-school"><strong>' + UI.escapeHtml(ctx.tenant_name || "") + "</strong><span>Conseil de classe — " + UI.escapeHtml(r.class.name) + '</span></div><div style="text-align:right"><h2>RÉSULTATS</h2><span class="muted">' + UI.escapeHtml(r.period || "") + '</span></div></div><div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Rang</th><th>Élève</th><th class="num">Moyenne /20</th><th class="num">%</th><th>Conduite</th><th>Décision</th>' + (canCouncil() ? '<th class="actions no-print"></th>' : "") + "</tr></thead><tbody>" +
        r.students.slice().sort(function (a, b) { return (a.rank || 999) - (b.rank || 999); }).map(function (s) {
          var actions = canCouncil() ? '<button type="button" class="btn btn-ghost btn-xs cond-btn" data-id="' + s.id + '" data-name="' + UI.escapeHtml(s.first_name + " " + s.last_name) + '" data-label="' + UI.escapeHtml(s.conduct.label || "") + '">Conduite</button>' + (ctx.role === "directeur" ? ' <button type="button" class="btn btn-ghost btn-xs dec-btn" data-id="' + s.id + '" data-name="' + UI.escapeHtml(s.first_name + " " + s.last_name) + '">Décision</button>' : "") : "";
          return '<tr><td data-label="Rang">' + (s.rank || "—") + '</td><td data-label="Élève"><a href="eleve-dossier.html?id=' + s.id + '" style="color:inherit"><span class="cell-main">' + UI.escapeHtml(s.last_name + " " + s.first_name) + '</span></a></td><td data-label="Moyenne" class="num"><strong>' + (s.average_20 != null ? s.average_20 : "—") + '</strong></td><td data-label="%" class="num ' + (s.percent != null && s.percent < threshold ? "text-warn" : "") + '">' + (s.percent != null ? s.percent + " %" : "—") + '</td><td data-label="Conduite">' + UI.escapeHtml(s.conduct.label || "—") + (s.conduct.overridden ? " " + UI.badge("info", "fixée") : ' <span class="muted">' + s.conduct.remaining + "/" + s.conduct.capital + "</span>") + '</td><td data-label="Décision">' + (s.decision ? UI.badge(s.decision.decision === "admis" ? "ok" : "warn", ({ admis: "Admis(e)", ajourne: "Ajourné(e)", doublant: "Doublant(e)" })[s.decision.decision]) : '<span class="muted">—</span>') + "</td>" + (canCouncil() ? '<td class="actions no-print">' + actions + "</td>" : "") + "</tr>";
        }).join("") + '</tbody></table></div><p class="ps-foot">Moyennes calculées à partir des notes saisies ; la conduite vient du capital de points, sauf décision du conseil. Aucun classement n\'est publié aux parents sans proclamation.</p></div></div>';
    },

    ressources: function () {
      var can = ctx.role === "directeur" || ctx.role === "professeur";
      var list = resources.length ? '<div class="doc-grid">' + resources.map(function (r) {
        return '<div class="doc-card"><span class="dc-ic">' + UI.icon(r.kind === "devoir" ? "clipboard" : "book", 18) + '</span><div class="dc-body"><strong>' + UI.escapeHtml(r.title) + "</strong><span>" + UI.escapeHtml(UI.EVENT_KIND_LABELS[r.kind] || r.kind) + (r.subject ? " · " + UI.escapeHtml(r.subject) : "") + (r.due_date ? " · à rendre le " + UI.fmtDate(r.due_date) : "") + (r.file_name ? " · " + UI.escapeHtml(r.file_name) : "") + "</span></div>" +
          (r.file_name ? '<button type="button" class="btn btn-ghost btn-xs res-open" data-id="' + r.id + '">Ouvrir</button> ' : "") + (can ? '<button type="button" class="btn btn-danger btn-xs res-del" data-id="' + r.id + '">Retirer</button>' : "") + "</div>";
      }).join("") + "</div>" : UI.emptyState("Aucun livre ni devoir publié", "Publiez un manuel, une fiche ou un devoir : les parents de cette classe le verront immédiatement et seront notifiés.", "", "book");
      return '<div class="panel"><div class="panel-head"><h2>Livres & devoirs de la classe</h2>' + (can ? '<button type="button" class="btn btn-lime btn-sm" id="addResBtn">' + UI.icon("plus", 15) + "Publier</button>" : "") + "</div>" + list +
        '<p class="note-inline mt-16">' + UI.icon("info", 15) + "<span>Ce que vous publiez ici apparaît dans l'espace « Livres & devoirs » des parents de la classe, jamais ailleurs.</span></p></div>";
    },

    horaire: function () {
      var byDay = {};
      C.schedule.forEach(function (s) { (byDay[s.weekday] = byDay[s.weekday] || []).push(s); });
      var canEdit = ctx.role === "directeur";
      var sched = '<div class="schedule-grid">' + [1, 2, 3, 4, 5, 6].filter(function (d) { return d < 6 || byDay[6]; }).map(function (d) {
        return '<div class="schedule-col"><h4>' + UI.WEEKDAYS[d] + "</h4>" + (byDay[d] || []).map(function (s) { return '<div class="slot"><strong>' + UI.escapeHtml(s.start_time + " – " + s.end_time) + "</strong>" + UI.escapeHtml(s.subject) + "<span>" + (s.teacher_name ? "<br>" + UI.escapeHtml(s.teacher_name) : "") + (s.room ? " · " + UI.escapeHtml(s.room) : "") + "</span>" + (canEdit ? '<button type="button" class="slot-del" data-slot="' + s.id + '" aria-label="Supprimer">' + UI.icon("x", 13) + "</button>" : "") + "</div>"; }).join("") + (byDay[d] ? "" : '<p class="muted">—</p>') + "</div>";
      }).join("") + "</div>";
      var today = UI.todayIso();
      var exams = C.exams.length ? '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Matière</th><th>Type</th><th>Date</th><th>Heure</th><th>Salle</th>' + (canEdit ? '<th class="actions"></th>' : "") + "</tr></thead><tbody>" + C.exams.map(function (e) {
        return "<tr" + (e.date < today ? ' style="opacity:0.55"' : "") + '><td data-label="Matière"><span class="cell-main">' + UI.escapeHtml(e.subject) + '</span></td><td data-label="Type">' + UI.escapeHtml(e.exam_type) + '</td><td data-label="Date">' + UI.fmtDate(e.date) + '</td><td data-label="Heure">' + UI.escapeHtml(e.start_time || "—") + '</td><td data-label="Salle">' + UI.escapeHtml(e.room || "—") + "</td>" + (canEdit ? '<td class="actions"><button type="button" class="btn btn-danger btn-xs del-exam" data-exam="' + e.id + '">Supprimer</button></td>' : "") + "</tr>";
      }).join("") + "</tbody></table></div>" : '<p class="muted">Aucune évaluation planifiée.</p>';
      return '<div class="panel"><div class="panel-head"><h2>Emploi du temps</h2>' + (canEdit ? '<button type="button" class="btn btn-ghost btn-sm" id="addSlotBtn">' + UI.icon("plus", 15) + "Ajouter un créneau</button>" : "") + "</div>" + (C.schedule.length ? sched : '<p class="muted">Aucun créneau saisi' + (canEdit ? " — ajoutez les cours de la semaine." : ".") + "</p>") + "</div>" +
        '<div class="panel"><div class="panel-head"><h2>Examens & évaluations</h2>' + (canEdit ? '<button type="button" class="btn btn-ghost btn-sm" id="addExamBtn">' + UI.icon("plus", 15) + "Planifier</button>" : "") + "</div>" + exams + "</div>";
    },

    enseignants: function () {
      var list = C.teachers.length ? C.teachers.map(function (t) {
        return '<div class="roll-row"><span class="avatar-init soft" style="width:36px;height:36px;font-size:12px">' + UI.escapeHtml((t.name || "?").split(" ").map(function (w) { return w[0]; }).join("").slice(0, 2).toUpperCase()) + '</span><div class="roll-name">' + UI.escapeHtml(t.name) + "<span>" + UI.escapeHtml(t.subject || "Matière non précisée") + "</span></div>" + (t.is_titulaire ? UI.badge("ok", "Titulaire") : "") +
          '<button type="button" class="btn btn-danger btn-xs unassign" data-uid="' + t.user_id + '">Retirer</button></div>';
      }).join("") : '<p class="muted">Aucun enseignant rattaché à cette classe.</p>';
      var options = team.filter(function (t) { return !C.teachers.some(function (x) { return x.user_id === t.id; }); });
      return '<div class="panel"><div class="panel-head"><h2>Enseignants rattachés</h2></div><div class="roll-list">' + list + "</div>" +
        '<p class="note-inline mt-16">' + UI.icon("info", 15) + "<span>Au secondaire, seul le <strong>titulaire</strong> a un accès Klassio à la classe. C'est vous qui décidez qui l'est.</span></p></div>" +
        '<div class="panel"><div class="panel-head"><h2>Rattacher un enseignant</h2><span class="sub">Le titulaire est une décision explicite — jamais automatique.</span></div>' +
        (team.length ? '<form id="assignForm" class="form-grid"><div class="field"><label for="aUser">Enseignant</label><select id="aUser">' + (options.length ? options.map(function (t) { return '<option value="' + t.id + '">' + UI.escapeHtml(t.name) + "</option>"; }).join("") : '<option value="">Tous les enseignants sont déjà rattachés</option>') + '</select></div><div class="field"><label for="aSubject">Matière</label><input id="aSubject" placeholder="Ex. Mathématiques" /></div>' +
          '<label class="check full"><input type="checkbox" id="aTit" /> Titulaire de cette classe' + (C.titulaire ? " (remplacera " + UI.escapeHtml(C.titulaire.name) + ")" : "") + '</label><div class="full row"><button type="submit" class="btn btn-lime btn-sm" id="assignBtn"' + (options.length ? "" : " disabled") + ">Rattacher</button></div></form>"
          : '<p class="muted">Aucun professeur n\'a encore rejoint l\'établissement — <a class="link-btn" href="etablissement.html?tab=equipe">invitez-en un</a> en lui affectant directement ses classes.</p>') + "</div>";
    },

    situation: function () {
      var due = students.reduce(function (s, x) { return s + (x.total_due || 0); }, 0), paid = students.reduce(function (s, x) { return s + (x.total_paid || 0); }, 0);
      var withDue = students.filter(function (s) { return s.balance > 0; });
      return '<div class="kpi-grid cols-3">' + UI.kpi("Attendu", UI.money(due), { icon: "finance" }) + UI.kpi("Encaissé", UI.money(paid), { tone: "ok" }) + UI.kpi("Restant", UI.money(due - paid), { tone: due - paid > 0 ? "warn" : "ok", sub: UI.plural(withDue.length, "élève avec solde", "élèves avec solde") }) + "</div>" +
        '<div class="panel"><div class="panel-head"><h2>Situation par élève</h2></div>' + (students.length ? '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Élève</th><th class="num">Facturé</th><th class="num">Payé</th><th class="num">Reste</th><th>Statut</th></tr></thead><tbody>' + students.slice().sort(function (a, b) { return (b.balance || 0) - (a.balance || 0); }).map(function (s) {
          return '<tr class="clickable" data-href="eleve-dossier.html?id=' + s.id + '&tab=finance"><td data-label="Élève"><span class="cell-main">' + UI.escapeHtml(s.last_name + " " + s.first_name) + '</span></td><td data-label="Facturé" class="num">' + UI.money(s.total_due) + '</td><td data-label="Payé" class="num">' + UI.money(s.total_paid) + '</td><td data-label="Reste" class="num ' + (s.balance > 0 ? "text-warn" : "text-lime") + '">' + UI.money(s.balance) + '</td><td data-label="Statut">' + UI.badge(s.balance > 0 ? (s.total_paid > 0 ? "PARTIALLY_PAID" : "ISSUED") : "PAID") + "</td></tr>";
        }).join("") + "</tbody></table></div>" : '<p class="muted">Aucun élève.</p>') +
        '<p class="note-inline mt-16">' + UI.icon("lock", 15) + "<span>Cette vue n'a aucun effet sur la discipline ni sur les résultats : un solde impayé ne retire jamais de points.</span></p></div>";
    },
  };

  function wire() {
    var search = document.getElementById("clsSearch");
    if (search) search.addEventListener("input", UI.debounce(function () {
      var q = search.value.trim().toLowerCase();
      document.querySelectorAll("#clsTable tbody tr").forEach(function (tr) { tr.hidden = !!q && tr.dataset.name.indexOf(q) === -1; });
    }, 100));
    document.querySelectorAll(".report-btn").forEach(function (b) { b.addEventListener("click", function () { openReportModal(b.dataset.id, b.dataset.name); }); });

    // ---- Appel ----
    var rollList = document.getElementById("rollList");
    if (rollList) {
      var summary = function () {
        var counts = { present: 0, late: 0, absent: 0, excused: 0 };
        rollList.querySelectorAll(".seg button.active").forEach(function (b) { counts[b.dataset.status]++; });
        document.getElementById("rollSummary").innerHTML = "<strong>" + counts.present + "</strong> présents · <strong>" + counts.late + "</strong> retards · <strong>" + counts.absent + "</strong> absents · <strong>" + counts.excused + "</strong> excusés";
      };
      rollList.addEventListener("click", function (e) {
        var b = e.target.closest("button[data-status]"); if (!b) return;
        var seg = b.parentNode;
        seg.querySelectorAll("button").forEach(function (x) { x.className = ""; x.setAttribute("aria-pressed", "false"); });
        b.className = "active " + b.dataset.status; b.setAttribute("aria-pressed", "true");
        summary();
      });
      document.getElementById("allPresent").addEventListener("click", function () {
        rollList.querySelectorAll(".seg").forEach(function (seg) { seg.querySelectorAll("button").forEach(function (x) { x.className = x.dataset.status === "present" ? "active present" : ""; }); });
        summary();
      });
      summary();
      document.getElementById("rollDate").addEventListener("change", function () {
        var d = this.value;
        api.fetch("/classes/" + classId + "/attendance?date=" + d).then(function (res) {
          if (!res.ok) return;
          var map = {}; res.body.records.forEach(function (r) { map[r.student_id] = r.status; });
          rollList.querySelectorAll(".roll-row").forEach(function (row) {
            var st = map[row.dataset.sid] || "present";
            row.querySelectorAll(".seg button").forEach(function (x) { x.className = x.dataset.status === st ? "active " + st : ""; });
          });
          summary();
          document.getElementById("rollHint").textContent = res.body.records.length ? "Appel du " + UI.fmtDate(d) + " chargé — " + res.body.records.length + " enregistrement(s)." : "Aucun appel enregistré pour le " + UI.fmtDate(d) + ".";
        });
      });
      var save = function (btn, finalize) {
        var records = Array.prototype.map.call(rollList.querySelectorAll(".roll-row"), function (row) { return { student_id: row.dataset.sid, status: row.querySelector(".seg button.active").dataset.status }; });
        UI.btnState(btn, "loading", finalize ? "Envoi…" : "Enregistrement…");
        api.fetch("/classes/" + classId + "/attendance", { method: "POST", body: JSON.stringify({ date: document.getElementById("rollDate").value, records: records, finalize: !!finalize }) }).then(function (res) {
          if (!res.ok) { UI.btnState(btn, "error", "Réessayer"); return UI.toast(res.body.error || "Impossible d'enregistrer l'appel.", "error"); }
          UI.btnState(btn, "success", finalize ? "Appel envoyé" : "Enregistré");
          var parts = [res.body.saved + " élève(s)"];
          if (res.body.notified) parts.push(res.body.notified + " absence(s)/retard(s) signalé(s)");
          if (res.body.present_notified) parts.push(res.body.present_notified + " parent(s) informé(s) « à l'école »");
          if (res.body.kept_gate) parts.push(res.body.kept_gate + " retard(s) du portail conservé(s)");
          UI.toast("Appel enregistré — " + parts.join(", ") + ".", "success", 5000);
          setTimeout(load, 900);
        }).catch(function () { UI.btnState(btn, "error", "Réessayer"); UI.toast("Le serveur Klassio est injoignable.", "error"); });
      };
      document.getElementById("saveRoll").addEventListener("click", function () { save(this, false); });
      document.getElementById("finalizeRoll").addEventListener("click", function () { save(this, true); });
    }

    // ---- Notes ----
    var gForm = document.getElementById("gradesForm");
    if (gForm) {
      loadGradesHistory();
      document.getElementById("gMax").addEventListener("input", function () { var v = this.value || "20"; document.querySelectorAll(".gmax").forEach(function (x) { x.textContent = v; }); document.querySelectorAll(".g-score").forEach(function (i) { i.max = v; }); });
      gForm.addEventListener("submit", function (e) {
        e.preventDefault();
        var btn = document.getElementById("saveGrades"), err = document.getElementById("gErr");
        err.hidden = true;
        var entries = Array.prototype.map.call(gForm.querySelectorAll("tbody tr"), function (tr) { return { student_id: tr.dataset.sid, score: tr.querySelector(".g-score").value, comment: tr.querySelector(".g-comment").value }; }).filter(function (x) { return x.score !== ""; });
        if (!entries.length) { err.textContent = "Saisissez au moins une note."; err.hidden = false; return; }
        UI.btnState(btn, "loading", "Enregistrement…");
        api.fetch("/classes/" + classId + "/grades", { method: "POST", body: JSON.stringify({ subject: document.getElementById("gSubject").value.trim(), period: document.getElementById("gPeriod").value.trim(), max_score: parseFloat(document.getElementById("gMax").value), entries: entries }) }).then(function (res) {
          if (!res.ok) { UI.btnState(btn, "error", "Réessayer"); err.textContent = res.body.error || "Impossible d'enregistrer."; err.hidden = false; return; }
          UI.btnState(btn, "success", res.body.saved + " note(s) enregistrée(s)");
          UI.toast(res.body.saved + " note(s) enregistrée(s). Visibles des parents après proclamation de la période.", "success", 5000);
          gForm.querySelectorAll(".g-score, .g-comment").forEach(function (i) { i.value = ""; });
          loadGradesHistory();
        }).catch(function () { UI.btnState(btn, "error", "Réessayer"); });
      });
    }

    // ---- Appréciations ----
    var aForm = document.getElementById("apprForm");
    if (aForm) {
      aForm.addEventListener("click", function (e) {
        var b = e.target.closest(".appr-level button"); if (!b) return;
        b.parentNode.querySelectorAll("button").forEach(function (x) { x.classList.remove("active"); });
        b.classList.add("active");
      });
      var syncAppr = function () {
        var period = document.getElementById("aPeriod").value.trim(), domain = document.getElementById("aDomain").value;
        aForm.querySelectorAll("tbody tr").forEach(function (tr) {
          var found = apprExisting.find(function (a) { return a.period === period && a.domain === domain && a.student_id === tr.dataset.sid; });
          tr.querySelectorAll(".appr-level button").forEach(function (x) { x.classList.toggle("active", !!found && String(found.level) === x.dataset.level); });
          tr.querySelector(".a-comment").value = found && found.comment ? found.comment : "";
        });
      };
      document.getElementById("aPeriod").addEventListener("change", syncAppr);
      document.getElementById("aDomain").addEventListener("change", syncAppr);
      syncAppr();
      aForm.addEventListener("submit", function (e) {
        e.preventDefault();
        var btn = document.getElementById("saveAppr"), err = document.getElementById("aErr"); err.hidden = true;
        var entries = Array.prototype.map.call(aForm.querySelectorAll("tbody tr"), function (tr) {
          var active = tr.querySelector(".appr-level button.active");
          return { student_id: tr.dataset.sid, level: active ? parseInt(active.dataset.level, 10) : null, comment: tr.querySelector(".a-comment").value };
        }).filter(function (x) { return x.level; });
        if (!entries.length) { err.textContent = "Choisissez au moins un niveau."; err.hidden = false; return; }
        UI.btnState(btn, "loading");
        api.fetch("/classes/" + classId + "/appreciations", { method: "POST", body: JSON.stringify({ period: document.getElementById("aPeriod").value.trim(), domain: document.getElementById("aDomain").value, entries: entries }) }).then(function (res) {
          if (!res.ok) { UI.btnState(btn, "error"); err.textContent = res.body.error || "Impossible."; err.hidden = false; return; }
          UI.btnState(btn, "success", res.body.saved + " enregistrée(s)");
          UI.toast(res.body.saved + " appréciation(s) enregistrée(s).", "success");
          setTimeout(load, 800);
        });
      });
    }

    // ---- Conseil de classe ----
    var rp = document.getElementById("resPeriod");
    if (rp) rp.addEventListener("change", function () {
      api.fetch("/classes/" + classId + "/results?period=" + encodeURIComponent(this.value)).then(function (r) {
        if (!r.ok) return UI.toast("Impossible de charger la période.", "error");
        results = r.body;
        document.querySelector('[data-tab-panel="conseil"]').innerHTML = renderers.conseil();
        wire(); UI.wireHrefs(document.querySelector('[data-tab-panel="conseil"]'));
      });
    });
    // BULLETINS DE TOUTE LA CLASSE, EN UNE FOIS.
  //
  // Jusqu'ici la Direction ouvrait le dossier de chaque élève et imprimait son
  // bulletin : quarante-deux fois pour une classe, quatre cents pour l'école.
  // Personne ne fait ça — en pratique les bulletins repartaient sous Excel, et
  // Klassio ne servait plus à rien en fin de trimestre.
  //
  // Le serveur compose chaque bulletin avec LA MÊME fonction que le bulletin
  // individuel : le lot ne peut donc pas diverger de l'unité. Ici on ne fait
  // que mettre en page.
  function imprimerBulletins() {
    var btn = document.getElementById("printBulletins");
    var periode = (document.getElementById("resPeriod") || {}).value || "";
    UI.btnState(btn, "loading", "Préparation…");
    api.fetch("/classes/" + classId + "/bulletins" + (periode ? "?period=" + encodeURIComponent(periode) : ""))
      .then(function (res) {
        if (!res.ok) {
          UI.btnState(btn, "error", "Échec");
          UI.toast((res.body && res.body.error) || "Impossible de générer les bulletins.", "error");
          return;
        }
        var d = res.body;
        if (!d.count) {
          UI.btnState(btn, "idle");
          UI.toast("Aucun élève actif dans cette classe.", "warn");
          return;
        }
        var hote = document.getElementById("bulletinsSheet") || (function () {
          var el = document.createElement("div");
          el.id = "bulletinsSheet";
          el.style.display = "none";
          document.body.appendChild(el);
          return el;
        })();
        hote.innerHTML = d.bulletins.map(function (b, i) {
          return unBulletin(b, d, i < d.count - 1);
        }).join("");
        UI.btnState(btn, "success", d.count + " bulletin(s)");
        UI.printSheet(hote, "Bulletins — " + d.class_name + (d.period ? " — " + d.period : ""));
      });
  }

  function unBulletin(b, d, saltDePage) {
    var e = b.student;
    var lignes = (b.subjects || []).map(function (m) {
      return "<tr><td>" + UI.escapeHtml(m.subject) + '</td><td class="num">'
        + (m.average_20 != null ? m.average_20 : "—") + "</td></tr>";
    }).join("") || '<tr><td colspan="2" class="muted">Aucune note enregistrée pour cette période.</td></tr>';
    return '<div class="print-sheet"' + (saltDePage ? ' style="page-break-after:always"' : "")
      + '><div class="ps-head"><div class="ps-school"><strong>' + UI.escapeHtml(d.school_name || "")
      + "</strong><span>" + UI.escapeHtml(e.last_name + " " + e.first_name)
      + " — " + UI.escapeHtml(e.class_name || "") + "</span></div>"
      + '<div style="text-align:right"><h2>BULLETIN</h2><span class="muted">'
      + UI.escapeHtml(b.period || d.period || "") + "</span></div></div>"
      + '<div class="table-wrap"><table class="data-table"><thead><tr><th>Matière</th>'
      + '<th class="num">Moyenne /20</th></tr></thead><tbody>' + lignes + "</tbody></table></div>"
      + '<p class="ps-foot">Moyenne générale : <strong>'
      + (b.general_average_20 != null ? b.general_average_20 + " / 20" : "—") + "</strong>"
      + (b.rank ? " — rang " + b.rank + " / " + b.class_size : "")
      + (e.code ? " — identifiant " + UI.escapeHtml(e.code) : "") + "</p></div>";
  }

  var pc = document.getElementById("printCouncil"); if (pc) pc.addEventListener("click", function () { UI.printSheet(document.getElementById("councilSheet"), "Conseil de classe — " + C.name); });
    var pb = document.getElementById("printBulletins"); if (pb) pb.addEventListener("click", imprimerBulletins);
    document.querySelectorAll(".cond-btn").forEach(function (b) { b.addEventListener("click", function () { openConductModal(b.dataset.id, b.dataset.name, b.dataset.label); }); });
    document.querySelectorAll(".dec-btn").forEach(function (b) { b.addEventListener("click", function () { openDecisionModal(b.dataset.id, b.dataset.name); }); });

    // ---- Ressources ----
    var ar = document.getElementById("addResBtn"); if (ar) ar.addEventListener("click", openResourceModal);
    document.querySelectorAll(".res-open").forEach(function (b) {
      b.addEventListener("click", function () {
        api.fetch("/resources/" + b.dataset.id + "/file").then(function (r) {
          if (!r.ok) return UI.toast(r.body.error || "Fichier indisponible.", "error");
          var m = UI.modal({ title: r.body.title || r.body.file_name, size: "lg", body: (r.body.file_data || "").indexOf("data:image/") === 0 ? '<img src="' + UI.escapeHtml(r.body.file_data) + '" alt="" style="max-width:100%;border-radius:12px" />' : '<iframe src="' + UI.escapeHtml(r.body.file_data) + '" style="width:100%;height:62vh;border:0;border-radius:12px"></iframe>', footer: '<button type="button" class="btn btn-ghost btn-sm" id="rClose">Fermer</button>' });
          m.querySelector("#rClose").addEventListener("click", UI.closeModal);
        });
      });
    });
    document.querySelectorAll(".res-del").forEach(function (b) {
      b.addEventListener("click", function () {
        UI.confirm("Retirer cette publication ?", "Elle disparaîtra de l'espace des parents.", "Retirer").then(function (ok) {
          if (ok) api.fetch("/resources/" + b.dataset.id, { method: "DELETE" }).then(function () { UI.toast("Publication retirée.", "success"); load(); });
        });
      });
    });

    // ---- Horaire / examens ----
    var as = document.getElementById("addSlotBtn"); if (as) as.addEventListener("click", openSlotModal);
    var ae = document.getElementById("addExamBtn"); if (ae) ae.addEventListener("click", openExamModal);
    document.querySelectorAll(".slot-del").forEach(function (b) { b.addEventListener("click", function () { api.fetch("/schedule/" + b.dataset.slot, { method: "DELETE" }).then(function () { UI.toast("Créneau supprimé.", "success"); load(); }); }); });
    document.querySelectorAll(".del-exam").forEach(function (b) { b.addEventListener("click", function () { UI.confirm("Supprimer cette évaluation ?", "Elle disparaîtra des espaces parents.", "Supprimer").then(function (ok) { if (ok) api.fetch("/exams/" + b.dataset.exam, { method: "DELETE" }).then(function () { UI.toast("Évaluation supprimée.", "success"); load(); }); }); }); });

    // ---- Enseignants ----
    var af = document.getElementById("assignForm");
    if (af) af.addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = document.getElementById("assignBtn");
      UI.btnState(btn, "loading");
      api.fetch("/classes/" + classId + "/teachers", { method: "POST", body: JSON.stringify({ user_id: document.getElementById("aUser").value, subject: document.getElementById("aSubject").value.trim(), is_titulaire: document.getElementById("aTit").checked }) }).then(function (res) {
        if (!res.ok) { UI.btnState(btn, "error"); return UI.toast(res.body.error || "Erreur.", "error"); }
        UI.btnState(btn, "success"); UI.toast("Enseignant rattaché.", "success"); setTimeout(load, 500);
      });
    });
    document.querySelectorAll(".unassign").forEach(function (b) { b.addEventListener("click", function () { UI.confirm("Retirer cet enseignant de la classe ?", "Il perdra l'accès aux élèves de cette classe.", "Retirer").then(function (ok) { if (ok) api.fetch("/classes/" + classId + "/teachers/" + b.dataset.uid, { method: "DELETE" }).then(function () { UI.toast("Enseignant retiré.", "success"); load(); }); }); }); });
  }

  function loadGradesHistory() {
    api.fetch("/classes/" + classId + "/grades").then(function (res) {
      var host = document.getElementById("gradesHistory"); if (!host) return;
      if (!res.ok || !res.body.length) { host.innerHTML = '<p class="muted">Aucune note saisie pour cette classe.</p>'; return; }
      var groups = {};
      res.body.forEach(function (g) { var k = g.period + " · " + g.subject; (groups[k] = groups[k] || { n: 0, sum: 0, max: g.max_score, date: g.created_at }); groups[k].n++; groups[k].sum += g.score / g.max_score; });
      host.innerHTML = '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Période · Matière</th><th class="num">Notes</th><th class="num">Moyenne /20</th><th>Saisie le</th></tr></thead><tbody>' + Object.keys(groups).sort().map(function (k) { var g = groups[k]; return '<tr><td data-label="Évaluation"><span class="cell-main">' + UI.escapeHtml(k) + '</span></td><td data-label="Notes" class="num">' + g.n + '</td><td data-label="Moyenne" class="num"><strong>' + (g.sum / g.n * 20).toFixed(1) + '</strong></td><td data-label="Saisie le">' + UI.fmtDate(g.date) + "</td></tr>"; }).join("") + "</tbody></table></div>";
    });
  }

  // ---------------- Modales ----------------
  function openResourceModal() {
    var m = UI.modal({ title: "Publier pour la classe " + C.name, size: "lg", body: '<form id="resForm" class="form-grid">' +
      '<div class="field"><label for="rKind">Type</label><select id="rKind"><option value="livre">Livre / manuel</option><option value="devoir">Devoir</option><option value="fiche">Fiche / support</option><option value="lecture">Lecture</option></select></div>' +
      '<div class="field"><label for="rSubject">Matière</label><input id="rSubject" maxlength="60" placeholder="Ex. Français" /></div>' +
      '<div class="field full"><label for="rTitle">Titre</label><input id="rTitle" required maxlength="160" placeholder="Ex. Manuel de lecture — chapitre 4" /></div>' +
      '<div class="field full"><label for="rDesc">Consigne / description</label><textarea id="rDesc" maxlength="1000" placeholder="Ce que l\'élève doit faire, pour quand."></textarea></div>' +
      '<div class="field"><label for="rDue">À rendre le</label><input id="rDue" type="date" /></div>' +
      '<div class="field"><label for="rFile">Fichier (PDF ou image, 3,5 Mo max)</label><input type="file" id="rFile" accept="application/pdf,image/png,image/jpeg" /></div>' +
      '<p class="note-inline full">' + UI.icon("info", 15) + "<span>Les parents de la classe sont notifiés dès la publication.</span></p><p class=\"form-error full\" id=\"rErr\" hidden></p></form>",
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="rCancel">Annuler</button><button type="submit" form="resForm" class="btn btn-lime btn-sm" id="rSubmit">Publier</button>' });
    m.querySelector("#rCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#resForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#rSubmit"), err = m.querySelector("#rErr"); err.hidden = true; UI.btnState(btn, "loading", "Publication…");
      var payload = { class_id: classId, kind: m.querySelector("#rKind").value, title: m.querySelector("#rTitle").value.trim(), subject: m.querySelector("#rSubject").value.trim(), description: m.querySelector("#rDesc").value.trim(), due_date: m.querySelector("#rDue").value || null };
      var file = m.querySelector("#rFile").files[0];
      var go = function () {
        api.fetch("/resources", { method: "POST", body: JSON.stringify(payload) }).then(function (r) {
          if (!r.ok) { UI.btnState(btn, "error"); err.textContent = r.body.error || "Impossible."; err.hidden = false; return; }
          UI.btnState(btn, "success", "Publié"); UI.toast("Publié — les parents de la classe sont informés.", "success");
          setTimeout(function () { UI.closeModal(); load(); }, 600);
        });
      };
      if (file) UI.fileToDataUrl(file, 3500 * 1024).then(function (d) { payload.file_data = d; payload.file_name = file.name; go(); }, function (e2) { UI.btnState(btn, "error"); err.textContent = e2.message; err.hidden = false; });
      else go();
    });
  }

  function openReportModal(studentId, name) {
    var m = UI.modal({ title: "Signaler au Directeur des disciplines", body: '<form id="rpForm" class="form-grid"><p class="modal-text full">Élève : <strong>' + UI.escapeHtml(name) + "</strong>. Vous décrivez les faits ; le DD qualifie et décide des points et des suites.</p>" +
      '<div class="field"><label for="rpDate">Date des faits</label><input id="rpDate" type="date" required max="' + UI.todayIso() + '" value="' + UI.todayIso() + '" /></div>' +
      '<div class="field full"><label for="rpDesc">Description</label><textarea id="rpDesc" required maxlength="1500" placeholder="Ce qui s\'est passé, où, quand."></textarea></div><p class="form-error full" id="rpErr" hidden></p></form>',
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

  function openConductModal(studentId, name, current) {
    var scale = results.conduct_scale || [];
    var m = UI.modal({ title: "Cote de conduite — " + name, body: '<form id="cdForm" class="form-grid"><p class="modal-text full">Période <strong>' + UI.escapeHtml(results.period || "") + "</strong>. La cote calculée vient du capital de points ; le conseil peut la fixer autrement.</p>" +
      '<div class="field full"><label for="cdLabel">Cote retenue</label><select id="cdLabel">' + (scale.length ? scale.map(function (s) { return '<option value="' + UI.escapeHtml(s[1]) + '"' + (current === s[1] ? " selected" : "") + ">" + UI.escapeHtml(s[1]) + "</option>"; }).join("") : '<option>Très bien</option><option>Bien</option><option>Assez bien</option><option>Passable</option><option>Insuffisant</option>') + "</select></div>" +
      '<div class="field full"><label for="cdNote">Motivation (facultative)</label><input id="cdNote" maxlength="300" /></div></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="cdCancel">Annuler</button><button type="button" class="btn btn-danger btn-sm" id="cdClear">Revenir au calcul</button><button type="submit" form="cdForm" class="btn btn-lime btn-sm" id="cdSubmit">Enregistrer</button>' });
    m.querySelector("#cdCancel").addEventListener("click", UI.closeModal);
    var send = function (payload, btn) {
      UI.btnState(btn, "loading");
      api.fetch("/students/" + studentId + "/conduct", { method: "PUT", body: JSON.stringify(payload) }).then(function (r) {
        if (!r.ok) { UI.btnState(btn, "error"); return UI.toast(r.body.error || "Impossible.", "error"); }
        UI.btnState(btn, "success"); UI.toast("Cote enregistrée.", "success");
        setTimeout(function () { UI.closeModal(); load(); }, 500);
      });
    };
    m.querySelector("#cdClear").addEventListener("click", function () { send({ period: results.period, clear: true }, this); });
    m.querySelector("#cdForm").addEventListener("submit", function (e) { e.preventDefault(); send({ period: results.period, label: m.querySelector("#cdLabel").value, note: m.querySelector("#cdNote").value.trim() }, m.querySelector("#cdSubmit")); });
  }

  function openDecisionModal(studentId, name) {
    var m = UI.modal({ title: "Décision de fin d'année — " + name, body: '<form id="dcForm" class="form-grid"><p class="modal-text full">Réservée à la Direction. Les responsables peuvent en être informés.</p>' +
      '<div class="field"><label for="dcDec">Décision</label><select id="dcDec"><option value="admis">Admis(e)</option><option value="ajourne">Ajourné(e)</option><option value="doublant">Doublant(e)</option></select></div>' +
      '<div class="field"><label for="dcMention">Mention</label><input id="dcMention" maxlength="40" placeholder="Ex. Distinction" /></div>' +
      '<div class="field full"><label for="dcNote">Observation</label><input id="dcNote" maxlength="300" /></div>' +
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

  function openSlotModal() {
    var m = UI.modal({ title: "Ajouter un créneau", body: '<form id="slotForm" class="form-grid"><div class="field"><label for="sDay">Jour</label><select id="sDay">' + [1, 2, 3, 4, 5, 6].map(function (d) { return '<option value="' + d + '">' + UI.WEEKDAYS[d] + "</option>"; }).join("") + '</select></div><div class="field"><label for="sSubject">Matière</label><input id="sSubject" required /></div>' +
      '<div class="field"><label for="sStart">Début</label><input id="sStart" type="time" value="08:00" required /></div><div class="field"><label for="sEnd">Fin</label><input id="sEnd" type="time" value="09:00" required /></div>' +
      '<div class="field"><label for="sTeacher">Enseignant</label><select id="sTeacher"><option value="">—</option>' + team.map(function (t) { return '<option value="' + t.id + '">' + UI.escapeHtml(t.name) + "</option>"; }).join("") + '</select></div><div class="field"><label for="sRoom">Salle</label><input id="sRoom" placeholder="Ex. Salle 4" /></div><p class="form-error full" id="sErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="sCancel">Annuler</button><button type="submit" form="slotForm" class="btn btn-lime btn-sm" id="sSubmit">Ajouter</button>' });
    m.querySelector("#sCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#slotForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#sSubmit"), err = m.querySelector("#sErr"); UI.btnState(btn, "loading");
      api.fetch("/classes/" + classId + "/schedule", { method: "POST", body: JSON.stringify({ weekday: parseInt(m.querySelector("#sDay").value, 10), subject: m.querySelector("#sSubject").value.trim(), start_time: m.querySelector("#sStart").value, end_time: m.querySelector("#sEnd").value, teacher_user_id: m.querySelector("#sTeacher").value || null, room: m.querySelector("#sRoom").value.trim() }) }).then(function (res) {
        if (!res.ok) { UI.btnState(btn, "error"); err.textContent = res.body.error || "Erreur."; err.hidden = false; return; }
        UI.btnState(btn, "success"); setTimeout(function () { UI.closeModal(); load(); }, 400);
      });
    });
  }

  function openExamModal() {
    var m = UI.modal({ title: "Planifier une évaluation", body: '<form id="examForm" class="form-grid"><div class="field"><label for="xSubject">Matière</label><input id="xSubject" required /></div><div class="field"><label for="xType">Type</label><select id="xType"><option>Évaluation</option><option>Interrogation</option><option>Examen</option><option>Devoir</option></select></div>' +
      '<div class="field"><label for="xDate">Date</label><input id="xDate" type="date" required min="' + UI.todayIso() + '" /></div><div class="field"><label for="xTime">Heure</label><input id="xTime" type="time" /></div><div class="field"><label for="xRoom">Salle</label><input id="xRoom" /></div><div class="field"><label for="xNotes">Notes</label><input id="xNotes" placeholder="Optionnel" /></div><p class="form-error full" id="xErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="xCancel">Annuler</button><button type="submit" form="examForm" class="btn btn-lime btn-sm" id="xSubmit">Planifier</button>' });
    m.querySelector("#xCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#examForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#xSubmit"), err = m.querySelector("#xErr"); UI.btnState(btn, "loading");
      api.fetch("/classes/" + classId + "/exams", { method: "POST", body: JSON.stringify({ subject: m.querySelector("#xSubject").value.trim(), exam_type: m.querySelector("#xType").value, date: m.querySelector("#xDate").value, start_time: m.querySelector("#xTime").value || null, room: m.querySelector("#xRoom").value.trim(), notes: m.querySelector("#xNotes").value.trim() }) }).then(function (res) {
        if (!res.ok) { UI.btnState(btn, "error"); err.textContent = res.body.error || "Erreur."; err.hidden = false; return; }
        UI.btnState(btn, "success"); UI.toast("Évaluation planifiée — visible dans les espaces parents.", "success"); setTimeout(function () { UI.closeModal(); load(); }, 400);
      });
    });
  }

  function openEditClass() {
    var m = UI.modal({ title: "Modifier la classe", body: '<form id="ecForm" class="form-grid"><div class="field"><label for="ecName">Nom</label><input id="ecName" value="' + UI.escapeHtml(C.name) + '" required /></div><div class="field"><label for="ecLevel">Niveau</label><input id="ecLevel" value="' + UI.escapeHtml(C.level || "") + '" /></div>' +
      '<div class="field full"><label for="ecCycle">Cycle</label><select id="ecCycle">' + ["maternelle", "primaire", "secondaire"].map(function (c) { return '<option value="' + c + '"' + (C.cycle === c ? " selected" : "") + ">" + c.charAt(0).toUpperCase() + c.slice(1) + "</option>"; }).join("") + '</select><span class="hint">Le cycle détermine le périmètre du Directeur des disciplines et le mode d\'évaluation (appréciations en maternelle).</span></div><p class="form-error full" id="ecErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="ecCancel">Annuler</button><button type="submit" form="ecForm" class="btn btn-lime btn-sm" id="ecSubmit">Enregistrer</button>' });
    m.querySelector("#ecCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#ecForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#ecSubmit"), err = m.querySelector("#ecErr"); UI.btnState(btn, "loading");
      api.fetch("/classes/" + classId, { method: "PUT", body: JSON.stringify({ name: m.querySelector("#ecName").value.trim(), level: m.querySelector("#ecLevel").value.trim(), cycle: m.querySelector("#ecCycle").value }) }).then(function (res) {
        if (!res.ok) { UI.btnState(btn, "error"); err.textContent = res.body.error || "Erreur."; err.hidden = false; return; }
        UI.btnState(btn, "success"); setTimeout(function () { UI.closeModal(); load(); }, 400);
      });
    });
  }
})();
