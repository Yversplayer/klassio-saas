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

  // Refonte du 08/10/2026, sur le modèle « cartes » du propriétaire : deux
  // grandes cartes (encaissé, restant) qui s'inclinent, des pastilles
  // d'action, les derniers paiements en lignes, un donut et un histogramme.
  // Les chiffres n'ont pas bougé : /reports/summary, /dashboard et
  // /catalog-items, exactement comme avant. Le mouvement vit dans tableau.css,
  // sous .ka-anim — rien ne bouge en mouvement réduit.
  function render(rep, dash, items) {
    var T = window.KlassioTableau;
    var cur = rep.currency, f = rep.financial;
    var monthly = rep.monthly_collections.map(function (m) { var d = new Date(m.month + "-01T00:00:00"); return { label: d.toLocaleDateString("fr-FR", { month: "short" }), value: m.total, display: UI.compactMoney(m.total, cur) }; });
    var classRows = dash.classes_outstanding.filter(function (c) { return c.student_count > 0; }).map(function (c) { return { label: c.name, value: c.outstanding, display: UI.compactMoney(c.outstanding, cur), cls: c.outstanding > 0 ? "warn" : "", href: "classe.html?id=" + c.id + "&tab=situation" }; });
    var catalogue = items.filter(function (i) { return i.category !== "boutique"; });
    var aConfirmer = dash.pending_payments || 0;

    var cartes = '<div class="kt-cartes">' +
      '<a class="kt-banque sombre kt-3d" href="paiements.html"><span class="kt-banque-lbl">Encaissé</span><span class="kt-banque-val">' + UI.money(f.total_paid, cur) + '</span><span>paiements confirmés</span>' + T.objet("pieces", "", 240) +
        '<span class="kt-banque-pied"><span>' + rep.collection_rate + ' % de l\'attendu</span><span class="kt-puce" aria-hidden="true"></span></span></a>' +
      '<a class="kt-banque clair kt-3d" href="#impayes"><span class="kt-banque-lbl">Restant à encaisser</span><span class="kt-banque-val">' + UI.money(f.outstanding, cur) + '</span><span>sur ' + UI.money(f.total_due, cur) + " attendus</span>" + T.objet("telephone", "", 240) +
        '<span class="kt-banque-pied"><span>' + UI.plural(rep.students_without_payment_count, "élève sans aucun paiement", "élèves sans aucun paiement") + '</span><span class="kt-puce" aria-hidden="true"></span></span></a>' +
      "</div>";

    var pastilles = '<div class="kt-pastilles">' +
      '<a class="kt-pastille on" href="paiements.html?new=1"><span class="ic-rond">' + UI.icon("plus", 15) + "</span>Enregistrer</a>" +
      '<a class="kt-pastille" href="paiements.html?filter=pending"><span class="ic-rond">' + UI.icon("phone", 15) + "</span>À confirmer" + (aConfirmer ? '<span class="cnt">' + aConfirmer + "</span>" : "") + "</a>" +
      '<a class="kt-pastille" href="#impayes"><span class="ic-rond">' + UI.icon("alert", 15) + "</span>Impayés</a>" +
      '<button type="button" class="kt-pastille" id="pastilleCatalogue"><span class="ic-rond">' + UI.icon("finance", 15) + "</span>Catalogue</button>" +
      "</div>";

    var recents = dash.recent_payments || [];
    var derniers = '<section class="kt-carte"><div class="kt-tete"><h2>Derniers paiements</h2><a class="link-btn" href="paiements.html">Tout voir</a></div>' +
      (recents.length ? '<div class="kt-liste">' + recents.map(function (p) {
        return '<div class="kt-ligne"><span class="kt-rond">' + UI.escapeHtml(UI.initials(p)) + "</span><span><strong>" + UI.escapeHtml(p.first_name + " " + p.last_name) + "</strong><small>" + UI.escapeHtml(UI.METHODS[p.method] || p.method) + " · " + UI.fmtDateTime(p.confirmed_at) + (p.receipt_number ? " · Reçu " + UI.escapeHtml(p.receipt_number) : "") + '</small></span><span class="kt-montant">' + UI.money(p.amount, p.currency) + "<br>" + UI.badge("ok", "Confirmé") + "</span></div>";
      }).join("") + "</div>" : '<p class="kt-vide">Aucun paiement confirmé pour le moment.</p>') + "</section>";

    var stat = '<section class="kt-carte kt-3d"><div class="kt-tete"><h2>Recouvrement</h2><span class="sub">année en cours</span></div>' +
      T.donut([{ value: f.total_paid, color: "#7BC400" }, { value: f.outstanding, color: "var(--kt-donut-att, #16301F)" }], f.total_due, "attendu", UI.compactMoney(f.total_due, cur)) +
      '<div class="kt-legende"><span>Encaissé ' + rep.collection_rate + ' %</span><span class="att">Restant ' + UI.compactMoney(f.outstanding, cur) + "</span></div>" +
      '<div class="kt-tete" id="impayes"><h2>Plus gros impayés</h2><a class="link-btn" href="eleves.html?finance=due">Tous</a></div>' +
      (rep.biggest_unpaid.length ? '<div class="kt-liste">' + rep.biggest_unpaid.slice(0, 6).map(function (r) {
        return '<div class="kt-ligne" data-href="eleve-dossier.html?id=' + r.id + '&tab=finance"><span class="kt-rond clair">' + UI.escapeHtml(UI.initials(r)) + "</span><span><strong>" + UI.escapeHtml(r.first_name + " " + r.last_name) + "</strong><small>" + UI.escapeHtml(r.class_name || "—") + '</small></span><span class="kt-montant text-warn">−' + UI.money(r.balance, cur) + "</span></div>";
      }).join("") + "</div>" : '<p class="kt-vide">Aucun impayé — situation à jour.</p>') + "</section>";

    var mois = '<section class="kt-carte"><div class="kt-tete"><h2>Encaissements par mois</h2><span class="sub">6 derniers mois</span></div>' + T.histo(monthly, "Aucun paiement confirmé pour le moment.") + "</section>";
    var parClasse = '<section class="kt-carte"><div class="kt-tete"><h2>Solde restant par classe</h2></div>' + UI.barRows(classRows, { empty: "Aucune classe avec élèves." }) + "</section>";

    var cat = '<section class="kt-carte" id="catalogue"><div class="kt-tete"><h2>Catalogue des frais</h2><span class="sub">Les obligations se créent depuis chaque dossier élève</span></div>' + (catalogue.length ? '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Article</th><th>Catégorie</th><th class="num">Montant</th></tr></thead><tbody>' + catalogue.map(function (it) { return '<tr><td data-label="Article"><span class="cell-main">' + UI.escapeHtml(it.name) + '</span></td><td data-label="Catégorie">' + UI.escapeHtml(it.category) + '</td><td data-label="Montant" class="num">' + UI.money(it.amount, it.currency) + "</td></tr>"; }).join("") + "</tbody></table></div>" : UI.emptyState("Aucun article", "Ajoutez vos frais (scolarité, inscription, transport…) pour pouvoir les facturer.", '<button type="button" class="btn btn-lime btn-sm" id="emptyItem">' + UI.icon("plus", 15) + "Ajouter un article</button>", "finance")) + "</section>";

    var html = '<div class="kt-grille"><div class="kt-pile"><div>' + cartes + pastilles + "</div>" + derniers + "</div>" + stat + "</div>" +
      '<div class="kt-grille kt-egal">' + mois + parClasse + "</div>" + cat;
    var host = document.getElementById("financeContent");
    host.innerHTML = html;
    var e = document.getElementById("emptyItem"); if (e) e.addEventListener("click", openItemModal);
    document.getElementById("pastilleCatalogue").addEventListener("click", function () { document.getElementById("catalogue").scrollIntoView({ behavior: "smooth", block: "start" }); });
    UI.wireHrefs(host);
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
