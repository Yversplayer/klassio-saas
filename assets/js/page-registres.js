// KLASSIO — Registres imprimables : présence par classe et période,
// discipline par classe/période — pour l'inspection et les conseils.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var ctx = null, classes = [];
  var type = UI.qs("type") || "attendance", classId = UI.qs("class_id") || "";
  var from = UI.qs("from") || new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10), to = UI.qs("to") || UI.todayIso();

  admin.initShell("registres").then(function (c) {
    ctx = c;
    if (c.role === "parent") { document.getElementById("regContent").innerHTML = UI.emptyState("Réservé au personnel", "", '<a href="dashboard.html" class="btn btn-ghost btn-sm">Retour</a>', "lock"); return; }
    api.fetch("/classes").then(function (r) { classes = r.ok ? r.body : []; if (!classId && classes.length) classId = classes[0].id; renderToolbar(); load(); });
  });

  function renderToolbar() {
    document.getElementById("pageActions").innerHTML = '<select id="rType"><option value="attendance"' + (type === "attendance" ? " selected" : "") + '>Présence</option>' + (ctx.role !== "professeur" ? '<option value="discipline"' + (type === "discipline" ? " selected" : "") + ">Discipline</option>" : "") + '</select><select id="rClass">' + (type === "discipline" && ctx.role !== "professeur" ? '<option value="">Toutes mes classes</option>' : "") + classes.map(function (c) { return '<option value="' + c.id + '"' + (c.id === classId ? " selected" : "") + ">" + UI.escapeHtml(c.name) + "</option>"; }).join("") + '</select><input type="date" id="rFrom" value="' + from + '" style="height:42px;border-radius:100px;border:1.5px solid var(--line);padding:0 12px;background:var(--surface);font:inherit;color:var(--ink)" /><input type="date" id="rTo" value="' + to + '" style="height:42px;border-radius:100px;border:1.5px solid var(--line);padding:0 12px;background:var(--surface);font:inherit;color:var(--ink)" /><button type="button" class="btn btn-lime btn-sm" id="rPrint">' + UI.icon("print", 15) + "Imprimer</button>";
    document.getElementById("rType").addEventListener("change", function () { type = this.value; renderToolbar(); load(); });
    document.getElementById("rClass").addEventListener("change", function () { classId = this.value; load(); });
    document.getElementById("rFrom").addEventListener("change", function () { from = this.value; load(); });
    document.getElementById("rTo").addEventListener("change", function () { to = this.value; load(); });
    document.getElementById("rPrint").addEventListener("click", function () { window.print(); });
  }

  function load() {
    var host = document.getElementById("regContent");
    host.innerHTML = UI.skeleton("card", 1);
    var url = type === "attendance" ? "/registers/attendance?class_id=" + classId + "&from=" + from + "&to=" + to : "/registers/discipline?from=" + from + "&to=" + to + (classId ? "&class_id=" + classId : "");
    api.fetch(url).then(function (res) {
      if (!res.ok) { host.innerHTML = UI.emptyState("Registre indisponible", res.body.error || "", "", "lock"); return; }
      type === "attendance" ? renderAttendance(res.body) : renderDiscipline(res.body);
    });
  }

  function renderAttendance(r) {
    var host = document.getElementById("regContent");
    if (!r.days.length) { host.innerHTML = '<div class="panel">' + UI.emptyState("Aucun appel sur la période", "Élargissez les dates ou choisissez une autre classe.", "", "calendar") + "</div>"; return; }
    host.innerHTML = '<div class="print-sheet"><div class="ps-head"><div class="ps-school"><strong>' + UI.escapeHtml(r.school) + "</strong><span>Registre de présence — " + UI.escapeHtml(r.class.name) + "</span></div><div style=\"text-align:right\"><h2>PRÉSENCES</h2><span class=\"muted\">" + UI.fmtDate(r.from) + " → " + UI.fmtDate(r.to) + '</span></div></div><div class="table-wrap"><table class="register"><thead><tr><th class="name">Élève</th>' + r.days.map(function (d) { return "<th>" + d.slice(8, 10) + "/" + d.slice(5, 7) + "</th>"; }).join("") + "<th>P</th><th>R</th><th>A</th><th>E</th></tr></thead><tbody>" + r.students.map(function (s) {
      return '<tr><td class="name">' + UI.escapeHtml(s.last_name + " " + s.first_name) + ' <span class="muted">' + UI.escapeHtml(s.code || "") + "</span></td>" + r.days.map(function (d) { var m = s.marks[d] || ""; return '<td class="' + m + '">' + m + "</td>"; }).join("") + "<td>" + s.totals.P + "</td><td>" + s.totals.R + "</td><td>" + s.totals.A + "</td><td>" + s.totals.E + "</td></tr>";
    }).join("") + '</tbody></table></div><p class="ps-foot">P = présent · R = retard · A = absent (non justifié) · E = excusé. Généré par Klassio le ' + UI.fmtDate(UI.todayIso()) + ".</p></div>";
  }

  function renderDiscipline(r) {
    var host = document.getElementById("regContent");
    if (!r.rows.length) { host.innerHTML = '<div class="panel">' + UI.emptyState("Aucun incident sur la période", "", "", "discipline") + "</div>"; return; }
    host.innerHTML = '<div class="print-sheet"><div class="ps-head"><div class="ps-school"><strong>' + UI.escapeHtml(r.school) + "</strong><span>Registre de discipline" + (r.class ? " — " + UI.escapeHtml(r.class.name) : "") + '</span></div><div style="text-align:right"><h2>DISCIPLINE</h2><span class="muted">' + UI.fmtDate(r.from) + " → " + UI.fmtDate(r.to) + '</span></div></div><div class="table-wrap"><table class="register"><thead><tr><th>Date</th><th class="name">Élève</th><th>Classe</th><th class="name">Fait</th><th>Catégorie</th><th>Gravité</th><th>Points</th><th class="name">Mesure</th><th>Statut</th><th>Par</th></tr></thead><tbody>' + r.rows.map(function (i) {
      return "<tr><td>" + UI.fmtDate(i.occurred_at) + '</td><td class="name">' + UI.escapeHtml(i.first_name + " " + i.last_name) + "</td><td>" + UI.escapeHtml(i.class_name || "") + '</td><td class="name">' + UI.escapeHtml(i.title) + "</td><td>" + UI.escapeHtml(i.category) + "</td><td>" + ({ low: "Mineur", medium: "Modéré", high: "Grave" })[i.severity] + "</td><td>" + (i.points > 0 ? "+" : "") + i.points + '</td><td class="name">' + UI.escapeHtml(i.action_taken || "—") + "</td><td>" + ({ open: "Ouvert", convocation: "Convocation", decided: "Décidé", closed: "Clos" })[i.status] + "</td><td>" + UI.escapeHtml(i.recorded_by_name || "") + "</td></tr>";
    }).join("") + '</tbody></table></div><p class="ps-foot">Les notes internes ne figurent jamais sur ce registre. Généré par Klassio le ' + UI.fmtDate(UI.todayIso()) + ".</p></div>";
  }
})();
