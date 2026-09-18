// KLASSIO — Finance (Direction) : vision globale — attendu, encaissé,
// restant, taux, évolution mensuelle, soldes par classe, impayés, catalogue.
// Finance ≠ Paiements : ici les obligations et soldes, là-bas les opérations.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var ctx = null;

  admin.initShell("finance").then(function (c) {
    ctx = c;
    if (c.role !== "directeur") { document.getElementById("financeContent").innerHTML = UI.emptyState("Réservé à la Direction", "La situation financière globale n'est pas accessible depuis votre espace.", '<a href="dashboard.html" class="btn btn-ghost btn-sm">Retour</a>', "lock"); return; }
    document.getElementById("pageActions").innerHTML = '<a href="paiements.html?new=1" class="btn btn-lime btn-sm">' + UI.icon("payments", 15) + 'Enregistrer un paiement</a><button type="button" class="btn btn-ghost btn-sm" id="addItemBtn">' + UI.icon("plus", 15) + "Article de catalogue</button>";
    document.getElementById("addItemBtn").addEventListener("click", openItemModal);
    load();
  });

  function load() {
    var host = document.getElementById("financeContent");
    host.innerHTML = '<div class="kpi-grid">' + UI.skeleton("kpi", 4) + "</div>" + UI.skeleton("card", 2);
    Promise.all([api.fetch("/reports/summary"), api.fetch("/dashboard"), api.fetch("/catalog-items")]).then(function (r) {
      if (!r[0].ok) return admin.loadError(host, load, "Impossible de charger la situation financière");
      render(r[0].body, r[1].body, r[2].body || []);
    }).catch(function () { admin.loadError(host, load, "Le serveur Klassio est injoignable"); });
  }

  function render(rep, dash, items) {
    var cur = rep.currency, f = rep.financial;
    var monthly = rep.monthly_collections.map(function (m) { var d = new Date(m.month + "-01T00:00:00"); return { label: d.toLocaleDateString("fr-FR", { month: "short", year: "2-digit" }), value: m.total, display: UI.compactMoney(m.total, cur) }; });
    var classRows = dash.classes_outstanding.filter(function (c) { return c.student_count > 0; }).map(function (c) { return { label: c.name, value: c.outstanding, display: UI.compactMoney(c.outstanding, cur), cls: c.outstanding > 0 ? "warn" : "", href: "classe.html?id=" + c.id + "&tab=situation" }; });
    var html = '<div class="kpi-grid">' + UI.kpi("Montant attendu", UI.money(f.total_due, cur), { icon: "finance", sub: "obligations émises" }) + UI.kpi("Encaissé", UI.money(f.total_paid, cur), { icon: "payments", tone: "ok", sub: "paiements confirmés" }) +
      UI.kpi("Solde restant", UI.money(f.outstanding, cur), { icon: "alert", tone: f.outstanding > 0 ? "warn" : "ok" }) + UI.kpi("Taux de recouvrement", rep.collection_rate + " %", { icon: "trend", tone: rep.collection_rate >= 70 ? "ok" : "warn", sub: rep.students_without_payment_count + " élève(s) sans aucun paiement" }) + "</div>" +
      '<div class="two-col"><div class="panel"><div class="panel-head"><h2>Encaissements par mois</h2><span class="sub">6 derniers mois</span></div>' + UI.barRows(monthly, { empty: "Aucun paiement confirmé pour le moment." }) + "</div>" +
      '<div class="panel"><div class="panel-head"><h2>Recouvrement</h2></div><div class="row" style="gap:22px">' + UI.ring(rep.collection_rate, "recouvré", rep.collection_rate < 50 ? "warn" : "") + '<div class="grow">' + UI.stackedBar([{ value: f.total_paid, cls: "ok", label: "Encaissé" }, { value: f.outstanding, cls: "warn", label: "Restant" }], f.total_due) + '<div class="legend"><span class="ok">Encaissé ' + UI.compactMoney(f.total_paid, cur) + '</span><span class="warn">Restant ' + UI.compactMoney(f.outstanding, cur) + "</span></div></div></div></div></div>" +
      '<div class="two-col"><div class="panel"><div class="panel-head"><h2>Solde restant par classe</h2></div>' + UI.barRows(classRows, { empty: "Aucune classe avec élèves." }) + "</div>" +
      '<div class="panel" id="impayes"><div class="panel-head"><h2>Les plus gros impayés</h2><a class="link-btn" href="eleves.html?finance=due">Voir tous</a></div>' + (rep.biggest_unpaid.length ? '<div class="table-wrap"><table class="data-table"><thead><tr><th>Élève</th><th>Classe</th><th class="num">Solde</th></tr></thead><tbody>' + rep.biggest_unpaid.map(function (r) { return '<tr class="clickable" data-href="eleve-dossier.html?id=' + r.id + '&tab=finance"><td><span class="cell-main">' + UI.escapeHtml(r.first_name + " " + r.last_name) + "</span></td><td>" + UI.escapeHtml(r.class_name || "—") + '</td><td class="num text-warn">' + UI.money(r.balance, cur) + "</td></tr>"; }).join("") + "</tbody></table></div>" : '<p class="muted">Aucun impayé — situation à jour.</p>') + "</div></div>" +
      '<div class="panel"><div class="panel-head"><h2>Catalogue des frais</h2><span class="sub">Ce que l\'établissement peut facturer. Les obligations se créent depuis chaque dossier élève.</span></div>' + (items.filter(function (i) { return i.category !== "boutique"; }).length ? '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Article</th><th>Catégorie</th><th class="num">Montant</th></tr></thead><tbody>' + items.filter(function (i) { return i.category !== "boutique"; }).map(function (it) { return '<tr><td data-label="Article"><span class="cell-main">' + UI.escapeHtml(it.name) + '</span></td><td data-label="Catégorie">' + UI.escapeHtml(it.category) + '</td><td data-label="Montant" class="num">' + UI.money(it.amount, it.currency) + "</td></tr>"; }).join("") + "</tbody></table></div>" : UI.emptyState("Aucun article", "Ajoutez vos frais (scolarité, inscription, transport…) pour pouvoir les facturer.", '<button type="button" class="btn btn-lime btn-sm" id="emptyItem">' + UI.icon("plus", 15) + "Ajouter un article</button>", "finance")) + "</div>";
    document.getElementById("financeContent").innerHTML = html;
    var e = document.getElementById("emptyItem"); if (e) e.addEventListener("click", openItemModal);
    UI.wireHrefs(document.getElementById("financeContent"));
    if (location.hash === "#impayes") document.getElementById("impayes").scrollIntoView();
  }

  function openItemModal() {
    var m = UI.modal({ title: "Ajouter un article de catalogue", body: '<form id="itemForm" class="form-grid"><div class="field full"><label for="iName">Nom</label><input id="iName" required placeholder="Ex. Frais de scolarité — Trimestre 1" /></div><div class="field"><label for="iCat">Catégorie</label><input id="iCat" placeholder="scolarité" list="catList" /><datalist id="catList"><option>scolarité</option><option>inscription</option><option>transport</option><option>cantine</option><option>uniforme</option><option>examens</option></datalist></div><div class="field"><label for="iAmount">Montant</label><input id="iAmount" type="number" step="0.01" min="0.01" required /></div><div class="field"><label for="iCur">Devise</label><select id="iCur"><option value="USD"' + (ctx.currency === "USD" ? " selected" : "") + '>USD ($)</option><option value="CDF"' + (ctx.currency === "CDF" ? " selected" : "") + '>CDF (FC)</option><option value="EUR">EUR (€)</option></select></div><p class="form-error full" id="iErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="iCancel">Annuler</button><button type="submit" form="itemForm" class="btn btn-lime btn-sm" id="iSubmit">Ajouter</button>' });
    m.querySelector("#iCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#itemForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#iSubmit"), err = m.querySelector("#iErr"); UI.btnState(btn, "loading");
      api.fetch("/catalog-items", { method: "POST", body: JSON.stringify({ name: m.querySelector("#iName").value.trim(), category: m.querySelector("#iCat").value.trim() || "frais", amount: parseFloat(m.querySelector("#iAmount").value), currency: m.querySelector("#iCur").value }) }).then(function (res) {
        if (!res.ok) { UI.btnState(btn, "error"); err.textContent = res.body.error || "Erreur."; err.hidden = false; return; }
        UI.btnState(btn, "success"); UI.toast("Article ajouté au catalogue.", "success"); setTimeout(function () { UI.closeModal(); load(); }, 400);
      });
    });
  }
})();
