// KLASSIO — Rapports (Direction) : finances, effectifs, présence, discipline,
// personnel — chaque graphique est calculé sur les données réelles.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;

  admin.initShell("rapports").then(function (c) {
    document.getElementById("printBtn").innerHTML = UI.icon("print", 15) + "Imprimer";
    document.getElementById("printBtn").addEventListener("click", function () { window.print(); });
    if (c.role !== "directeur") { document.getElementById("reportContent").innerHTML = UI.emptyState("Rapports réservés à la Direction", "", '<a href="dashboard.html" class="btn btn-ghost btn-sm">Retour</a>', "lock"); return; }
    load();
  });

  function load() {
    var host = document.getElementById("reportContent");
    host.innerHTML = '<div class="kpi-grid">' + UI.skeleton("kpi", 4) + "</div>" + UI.skeleton("card", 3);
    api.fetch("/reports/summary").then(function (res) {
      if (!res.ok) return admin.loadError(host, load, "Rapports indisponibles");
      var r = res.body, cur = r.currency, f = r.financial, att = r.attendance_30d;
      var monthly = r.monthly_collections.map(function (m) { var d = new Date(m.month + "-01T00:00:00"); return { label: d.toLocaleDateString("fr-FR", { month: "long", year: "numeric" }), value: m.total, display: UI.compactMoney(m.total, cur) }; });
      var totalStudents = r.by_cycle.reduce(function (s, c) { return s + c.student_count; }, 0);
      host.innerHTML = '<div class="kpi-grid">' + UI.kpi("Élèves actifs", totalStudents.toLocaleString("fr-FR"), { icon: "students" }) + UI.kpi("Taux de recouvrement", r.collection_rate + " %", { icon: "trend", tone: r.collection_rate >= 70 ? "ok" : "warn", sub: UI.compactMoney(f.total_paid, cur) + " / " + UI.compactMoney(f.total_due, cur) }) + UI.kpi("Présence (30 j)", att.rate != null ? att.rate + " %" : "—", { icon: "calendar", sub: att.total ? att.total.toLocaleString("fr-FR") + " appels" : "aucun appel enregistré" }) + UI.kpi("Incidents (30 j)", String(r.incidents_30d.reduce(function (s, i) { return s + i.n; }, 0)), { icon: "discipline" }) + "</div>" +
        '<div class="two-col"><div class="panel"><div class="panel-head"><h2>Encaissements par mois</h2></div>' + UI.barRows(monthly, { empty: "Aucun paiement confirmé." }) + '</div><div class="panel"><div class="panel-head"><h2>Répartition des élèves</h2></div>' + UI.barRows(r.by_cycle.map(function (c) { return { label: c.cycle.charAt(0).toUpperCase() + c.cycle.slice(1), value: c.student_count }; }), { empty: "Aucun élève." }) + '<div class="panel-head" style="margin-top:16px"><h2>Filles / garçons</h2></div>' + UI.barRows(r.by_gender.map(function (g) { return { label: g.gender === "F" ? "Filles" : g.gender === "M" ? "Garçons" : "Non renseigné", value: g.n, cls: g.gender === "—" ? "neutral" : "" }; })) + "</div></div>" +
        '<div class="two-col"><div class="panel"><div class="panel-head"><h2>Présence sur 30 jours</h2></div>' + (att.total ? UI.stackedBar([{ value: att.present, cls: "ok", label: "Présents" }, { value: att.late, cls: "warn", label: "Retards" }, { value: att.absent, cls: "bad", label: "Absents" }, { value: att.excused, cls: "neutral", label: "Excusés" }], att.total) + '<div class="legend"><span class="ok">' + att.present + " présents</span><span class=\"warn\">" + att.late + " retards</span><span class=\"bad\">" + att.absent + " absents</span><span>" + att.excused + " excusés</span></div>" : '<p class="muted">Aucun appel enregistré sur la période.</p>') + '<div class="panel-head" style="margin-top:16px"><h2>Incidents par catégorie</h2></div>' + UI.barRows(r.incidents_30d.map(function (i) { return { label: i.category, value: i.n, cls: "warn" }; }), { empty: "Aucun incident sur 30 jours." }) + "</div>" +
        '<div class="panel"><div class="panel-head"><h2>Structure du personnel & accès</h2></div>' + UI.barRows(r.staff.map(function (s) { return { label: UI.ROLE_LABELS[s.role] || s.role, value: s.n }; })) + '<div class="panel-head" style="margin-top:16px"><h2>Répartition par classe</h2></div>' + UI.barRows(r.classes.filter(function (c) { return c.student_count > 0; }).slice(0, 15).map(function (c) { return { label: c.name, value: c.student_count }; }), { empty: "Aucune classe avec élèves." }) + "</div></div>" +
        '<div class="panel"><div class="panel-head"><h2>Les 10 plus gros impayés</h2><span class="sub">' + r.students_without_payment_count + " élève(s) sans aucun paiement</span></div>" + (r.biggest_unpaid.length ? '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Élève</th><th>Classe</th><th class="num">Solde</th></tr></thead><tbody>' + r.biggest_unpaid.map(function (x) { return '<tr class="clickable" data-href="eleve-dossier.html?id=' + x.id + '&tab=finance"><td data-label="Élève"><span class="cell-main">' + UI.escapeHtml(x.first_name + " " + x.last_name) + '</span></td><td data-label="Classe">' + UI.escapeHtml(x.class_name || "—") + '</td><td data-label="Solde" class="num text-warn">' + UI.money(x.balance, cur) + "</td></tr>"; }).join("") + "</tbody></table></div>" : '<p class="muted">Aucun impayé.</p>') + "</div>";
      UI.wireHrefs(host);
    }).catch(function () { admin.loadError(host, load, "Le serveur Klassio est injoignable"); });
  }
})();
