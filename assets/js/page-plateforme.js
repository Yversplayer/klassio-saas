// KLASSIO — Administration de la plateforme (rôle global) : établissements,
// abonnements, factures déclarées à confirmer, paliers.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var ctx = null, O = null;

  admin.initShell("plateforme").then(function (c) {
    ctx = c;
    if (!c.is_platform_admin) { document.getElementById("platContent").innerHTML = UI.emptyState("Réservé à l'administration Klassio", "", '<a href="dashboard.html" class="btn btn-ghost btn-sm">Retour</a>', "lock"); return; }
    load();
  });

  function load() {
    var host = document.getElementById("platContent");
    host.innerHTML = '<div class="kpi-grid">' + UI.skeleton("kpi", 4) + "</div>" + UI.skeleton("card", 2);
    api.fetch("/platform/overview").then(function (res) {
      if (!res.ok) return admin.loadError(host, load, "Impossible de charger la plateforme");
      O = res.body; render();
    }).catch(function () { admin.loadError(host, load, "Le serveur Klassio est injoignable"); });
  }

  function render() {
    var host = document.getElementById("platContent");
    var c = O.counts;
    var STATUS = { trial: ["Essai", "info"], active: ["Actif", "ok"], past_due: ["Retard", "warn"], suspended: ["Suspendu", "bad"], cancelled: ["Résilié", "neutral"] };
    host.innerHTML = '<div class="kpi-grid cols-5">' + UI.kpi("Établissements", String(c.total), { icon: "building" }) + UI.kpi("En essai", String(c.trial), { icon: "clock" }) + UI.kpi("Actifs", String(c.active), { icon: "check", tone: "ok" }) + UI.kpi("En retard / suspendus", c.past_due + " / " + c.suspended, { icon: "alert", tone: c.past_due + c.suspended ? "warn" : "" }) + UI.kpi("MRR estimé", UI.money(O.mrr), { icon: "finance", tone: "ok", sub: "abonnements actifs" }) + "</div>" +
      '<div class="panel"><div class="panel-head"><h2>Paiements déclarés à confirmer</h2><span class="sub">Vérifiez la référence sur votre compte avant de confirmer</span></div>' + (O.pending_invoices.length ? '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Établissement</th><th>Facture</th><th class="num">Montant</th><th>Moyen · référence</th><th class="actions"></th></tr></thead><tbody>' + O.pending_invoices.map(function (i) {
        return '<tr><td data-label="Établissement"><span class="cell-main">' + UI.escapeHtml(i.tenant_name) + '</span></td><td data-label="Facture"><span class="chip-code">' + UI.escapeHtml(i.number) + '</span></td><td data-label="Montant" class="num"><strong>' + UI.money(i.amount, i.currency) + '</strong></td><td data-label="Référence">' + UI.escapeHtml(UI.METHODS[i.method] || i.method || "—") + " · " + UI.escapeHtml(i.reference || "—") + '</td><td class="actions"><button type="button" class="btn btn-lime btn-xs conf" data-id="' + i.id + '">Confirmer</button> <button type="button" class="btn btn-danger btn-xs void" data-id="' + i.id + '">Annuler</button></td></tr>';
      }).join("") + "</tbody></table></div>" : '<p class="muted">Aucun paiement en attente de confirmation.</p>') + "</div>" +
      '<div class="panel"><div class="panel-head"><h2>Établissements</h2></div><div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Établissement</th><th>Direction</th><th class="num">Élèves</th><th>Palier</th><th class="num">Montant / mois</th><th>Statut</th><th class="actions"></th></tr></thead><tbody>' + O.tenants.map(function (t) {
        var st = STATUS[t.status] || [t.status, "neutral"];
        return '<tr><td data-label="Établissement"><span class="cell-main">' + UI.escapeHtml(t.name) + '</span><span class="cell-sub">' + UI.escapeHtml(t.slug || "") + " · créé le " + UI.fmtDate(t.created_at) + '</span></td><td data-label="Direction">' + (t.director ? UI.escapeHtml(t.director.name) + '<span class="cell-sub">' + UI.escapeHtml(t.director.email || t.director.phone || "") + "</span>" : "—") + '</td><td data-label="Élèves" class="num">' + t.students + '</td><td data-label="Palier">' + UI.escapeHtml(t.plan || "—") + '</td><td data-label="Montant" class="num">' + UI.money(t.amount) + '</td><td data-label="Statut">' + UI.badge(st[1], st[0] + (t.status === "trial" && t.days_left != null ? " · " + t.days_left + " j" : "")) + '</td><td class="actions"><button type="button" class="btn btn-ghost btn-xs ext" data-id="' + t.id + '" data-name="' + UI.escapeHtml(t.name) + '">Prolonger l\'essai</button> ' + (t.status === "suspended" ? '<button type="button" class="btn btn-ghost btn-xs react" data-id="' + t.id + '">Réactiver</button>' : "") + "</td></tr>";
      }).join("") + "</tbody></table></div></div>" +
      '<div class="panel"><div class="panel-head"><h2>Paliers</h2><span class="sub">Modifiables — appliqués aux prochaines factures</span></div><div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Palier</th><th>Élèves</th><th class="num">Forfait</th><th class="num">Par élève</th><th class="actions"></th></tr></thead><tbody>' + O.plans.map(function (p) {
        return '<tr data-code="' + p.code + '"><td data-label="Palier"><span class="cell-main">' + UI.escapeHtml(p.name) + '</span><span class="cell-sub">' + UI.escapeHtml(p.description || "") + '</span></td><td data-label="Élèves">' + p.min_students + (p.max_students ? " – " + p.max_students : " +") + '</td><td data-label="Forfait" class="num"><input type="number" step="0.01" min="0" class="grade-input p-base" value="' + p.base_price + '" style="width:90px" /></td><td data-label="Par élève" class="num"><input type="number" step="0.01" min="0" class="grade-input p-per" value="' + p.per_student + '" style="width:90px" /></td><td class="actions"><button type="button" class="btn btn-ghost btn-xs save-plan">Enregistrer</button></td></tr>';
      }).join("") + "</tbody></table></div></div>";
    host.querySelectorAll(".conf").forEach(function (b) { b.addEventListener("click", function () { UI.confirm("Confirmer ce paiement ?", "L'établissement repasse « actif » et est notifié.", "Confirmer").then(function (ok) { if (ok) api.fetch("/platform/invoices/" + b.dataset.id + "/confirm", { method: "POST" }).then(function (r) { if (!r.ok) return UI.toast(r.body.error || "Impossible.", "error"); UI.toast("Paiement confirmé.", "success"); load(); }); }); }); });
    host.querySelectorAll(".void").forEach(function (b) { b.addEventListener("click", function () { UI.confirm("Annuler cette facture ?", "", "Annuler la facture").then(function (ok) { if (ok) api.fetch("/platform/invoices/" + b.dataset.id + "/void", { method: "POST" }).then(function () { UI.toast("Facture annulée.", "success"); load(); }); }); }); });
    host.querySelectorAll(".ext").forEach(function (b) { b.addEventListener("click", function () { UI.confirm("Prolonger l'essai de 15 jours ?", b.dataset.name, "Prolonger").then(function (ok) { if (ok) api.fetch("/platform/tenants/" + b.dataset.id, { method: "PUT", body: JSON.stringify({ extend_trial_days: 15 }) }).then(function () { UI.toast("Essai prolongé.", "success"); load(); }); }); }); });
    host.querySelectorAll(".react").forEach(function (b) { b.addEventListener("click", function () { api.fetch("/platform/tenants/" + b.dataset.id, { method: "PUT", body: JSON.stringify({ status: "active" }) }).then(function () { UI.toast("Établissement réactivé.", "success"); load(); }); }); });
    host.querySelectorAll(".save-plan").forEach(function (b) { b.addEventListener("click", function () { var tr = b.closest("tr"); UI.btnState(b, "loading"); api.fetch("/platform/plans/" + tr.dataset.code, { method: "PUT", body: JSON.stringify({ base_price: parseFloat(tr.querySelector(".p-base").value), per_student: parseFloat(tr.querySelector(".p-per").value) }) }).then(function (r) { if (!r.ok) { UI.btnState(b, "error"); return UI.toast(r.body.error || "Impossible.", "error"); } UI.btnState(b, "success"); }); }); });
  }
})();
