// KLASSIO — Abonnement (Direction) : état, palier automatique selon les
// élèves actifs, factures, déclaration de paiement. Aucun fournisseur de
// paiement branché : la plateforme confirme après vérification réelle.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var ctx = null, S = null;
  var STATUS = { awaiting_plan: ["Offre à choisir", "warn"], awaiting_payment: ["En attente du paiement", "warn"], trial: ["Période d'essai", ""], active: ["Actif", ""], past_due: ["Retard de paiement", "warn"], suspended: ["Lecture seule", "bad"], cancelled: ["Résilié", "bad"] };

  admin.initShell("abonnement").then(function (c) {
    ctx = c;
    if (c.role !== "directeur") { document.getElementById("subContent").innerHTML = UI.emptyState("Réservé à la Direction", "", '<a href="dashboard.html" class="btn btn-ghost btn-sm">Retour</a>', "lock"); return; }
    load();
  });

  function load() {
    var host = document.getElementById("subContent");
    host.innerHTML = UI.skeleton("card", 2);
    api.fetch("/subscription").then(function (res) {
      if (!res.ok) return admin.loadError(host, load, "Impossible de charger l'abonnement");
      S = res.body; render();
    }).catch(function () { admin.loadError(host, load, "Le serveur Klassio est injoignable"); });
  }

  // Le cycle de l'école (07/10/2026) : au mois, ou à l'année (« 2 mois offerts »).
  // Avant, l'écran écrivait « / mois » à côté de tout montant — y compris
  // 999 $ pour une école facturée à l'année.
  function annuel() { return S.billing_cycle === "yearly"; }
  function nomOffre(code) {
    var p = S.plans.filter(function (x) { return x.code === code; })[0];
    return p ? p.name : code;
  }
  function render() {
    var host = document.getElementById("subContent");
    // Espace pas encore ouvert : l'écran se réduit au choix de l'offre et au
    // paiement — il n'y a rien d'autre à faire tant que l'espace est fermé.
    if (S.awaiting) {
      host.innerHTML = '<div class="panel"><div class="panel-head"><h2>' + (S.status === "awaiting_plan" ? "Choisissez votre offre" : "Réglez votre première facture") + '</h2><span class="sub">' + UI.escapeHtml(S.attention || "") + "</span></div><div id=\"offreHost\"></div></div>";
      window.KlassioOffres.render(document.getElementById("offreHost"), S, {
        reload: load,
        onBypass: function () { window.location.href = "dashboard.html"; },
      });
      return;
    }
    var st = STATUS[S.status] || [S.status, ""];
    var sub = S.status === "trial" ? "Essai gratuit — " + (S.days_left != null ? UI.plural(S.days_left, "jour restant", "jours restants") : "") : S.status === "active" ? "Prochaine échéance : " + (S.current_period_end ? UI.fmtDate(S.current_period_end) : "—") : S.attention || "";
    var inv = S.open_invoice;
    var hero = '<div class="status-hero"><div class="sh-main"><strong>' + UI.escapeHtml(S.school_name) + "</strong><span>" + UI.escapeHtml(sub) + '</span></div><span class="sh-badge ' + st[1] + '">' + st[0] + '</span><div style="margin-left:auto;text-align:right"><div style="font-size:12px;color:rgba(231,239,227,0.7)">Palier ' + (S.plan ? UI.escapeHtml(S.plan.name) : "—") + " · " + S.students.toLocaleString("fr-FR") + ' élèves actifs</div><div style="font-size:24px;font-weight:800">' + window.KlassioOffres.montant(S.estimated_amount, S.plan ? S.plan.currency : "USD") + ' <small style="font-size:12px;font-weight:500">' + (annuel() ? "/ an" : "/ mois") + "</small></div>" +
      (annuel() ? '<div style="font-size:12px;color:rgba(231,239,227,0.7)">soit ' + window.KlassioOffres.montant(S.monthly_equivalent, S.plan ? S.plan.currency : "USD") + " par mois</div>" : "") + "</div></div>";
    var invoicePanel = "";
    if (inv) {
      var due = UI.fmtDate(inv.due_at);
      invoicePanel = '<div class="panel" style="border-color:var(--lime-strong)"><div class="panel-head"><h2>Facture ' + UI.escapeHtml(inv.number) + '</h2>' + UI.badge(inv.status === "pending" ? "warn" : (S.status === "suspended" || S.status === "past_due" ? "bad" : "info"), inv.status === "pending" ? "Paiement déclaré — en attente de confirmation" : "À régler avant le " + due) + "</div>" +
        '<dl class="dl"><dt>Période</dt><dd>' + UI.fmtDate(inv.period_start) + " → " + UI.fmtDate(inv.period_end) + "</dd><dt>Élèves actifs facturés</dt><dd>" + inv.students + "</dd><dt>Offre</dt><dd>" + UI.escapeHtml(nomOffre(inv.plan_code)) + (inv.billing_cycle === "yearly" ? " · à l'année" : " · au mois") + "</dd><dt>Montant</dt><dd><strong>" + UI.money(inv.amount, inv.currency) + "</strong></dd>" + (inv.reference ? "<dt>Référence déclarée</dt><dd>" + UI.escapeHtml(inv.reference) + " (" + UI.escapeHtml(UI.METHODS[inv.method] || inv.method) + ")</dd>" : "") + "</dl>" +
        (inv.status === "open" ? '<div class="row mt-16"><button type="button" class="btn btn-lime btn-sm" id="payBtn">' + UI.icon("phone", 15) + "J'ai payé — déclarer le paiement</button></div>" : '<p class="muted mt-8">Klassio confirme votre paiement après vérification, puis votre espace repasse à jour automatiquement.</p>') + "</div>";
    }
    var plans = '<div class="panel"><div class="panel-head"><h2>Les offres</h2><span class="sub">Toutes les fonctionnalités dans chaque offre — si votre effectif grandit, l\'offre au-dessus s\'applique d\'elle-même. Pour changer d\'offre ou de rythme de paiement : <a href="mailto:mudeyimusimwa@gmail.com">écrivez à Klassio</a>.</span></div>' +
      window.KlassioOffres.cartesLecture(S) + "</div>";
    var history = '<div class="panel"><div class="panel-head"><h2>Factures</h2></div>' + (S.invoices.length ? '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>N°</th><th>Période</th><th class="num">Élèves</th><th class="num">Montant</th><th>Statut</th><th>Payée le</th></tr></thead><tbody>' + S.invoices.map(function (i) {
      return '<tr><td data-label="N°"><span class="chip-code">' + UI.escapeHtml(i.number) + '</span></td><td data-label="Période">' + UI.fmtDate(i.period_start) + " → " + UI.fmtDate(i.period_end) + '</td><td data-label="Élèves" class="num">' + i.students + '</td><td data-label="Montant" class="num">' + UI.money(i.amount, i.currency) + '</td><td data-label="Statut">' + UI.badge({ open: "warn", pending: "info", paid: "ok", void: "neutral" }[i.status], { open: "À régler", pending: "Déclarée", paid: "Payée", void: "Annulée" }[i.status]) + '</td><td data-label="Payée le">' + (i.paid_at ? UI.fmtDate(i.paid_at) : "—") + "</td></tr>";
    }).join("") + "</tbody></table></div>" : '<p class="muted">Aucune facture pour le moment.</p>') + "</div>";
    var how = '<div class="panel"><div class="panel-head"><h2>Comment ça marche</h2></div><ol class="step-list"><li><span class="num">1</span><span>Vous choisissez l\'offre adaptée à votre effectif ; <strong>l\'espace s\'ouvre</strong> à la confirmation du premier paiement.</span></li><li><span class="num">2</span><span>Ensuite une <strong>facture à chaque échéance</strong> — chaque mois, ou chaque année avec 2 mois offerts ; si votre effectif dépasse votre offre, l\'offre au-dessus s\'applique.</span></li><li><span class="num">3</span><span>Vous réglez par Mobile Money ou virement et déclarez la référence ; Klassio confirme.</span></li><li><span class="num">4</span><span>En cas de retard : rappel, puis <strong>lecture seule</strong> après ' + S.grace_days + ' jours — jamais de suppression de données.</span></li></ol><p class="note-inline">' + UI.icon("info", 15) + "<span>Circuit séparé des frais scolaires : l'argent versé par vos parents va sur le compte de l'établissement, jamais sur celui de Klassio. Beaucoup d'écoles répercutent l'abonnement via une ligne « frais numériques » dans leur catalogue.</span></p></div>";
    host.innerHTML = hero + invoicePanel + plans + '<div class="two-col">' + history + how + "</div>";
    var pb = document.getElementById("payBtn"); if (pb) pb.addEventListener("click", openPay);
  }

  function openPay() {
    var inv = S.open_invoice;
    var m = UI.modal({ title: "Déclarer le paiement de " + inv.number, body: '<form id="payForm" class="form-grid"><p class="modal-text full">Montant : <strong>' + UI.money(inv.amount, inv.currency) + '</strong>. Effectuez le paiement, puis indiquez la référence de la transaction — Klassio la vérifie avant de confirmer.</p>' +
      // Mêmes tuiles que la page de paiement (offres.js) : Mobile Money ou virement.
      '<fieldset class="of-methods full"><legend>Comment payez-vous ?</legend>' +
      '<label class="of-method"><input type="radio" name="pMethod" value="mobile_money" checked><span><b>Mobile Money</b><small>M-Pesa, Orange Money, Airtel Money</small></span></label>' +
      '<label class="of-method"><input type="radio" name="pMethod" value="bank"><span><b>Virement bancaire</b><small>Depuis le compte de l\'établissement</small></span></label></fieldset>' +
      '<div class="field full"><label for="pRef">Référence de la transaction</label><input id="pRef" required maxlength="80" placeholder="Ex. MP240911.1234.X12345" /></div><p class="form-error full" id="pErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="pCancel">Annuler</button><button type="submit" form="payForm" class="btn btn-lime btn-sm" id="pSubmit">Déclarer</button>' });
    m.querySelector("#pCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#payForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#pSubmit"), err = m.querySelector("#pErr"); err.hidden = true; UI.btnState(btn, "loading");
      api.fetch("/subscription/pay", { method: "POST", body: JSON.stringify({ invoice_id: inv.id, method: m.querySelector('input[name="pMethod"]:checked').value, reference: m.querySelector("#pRef").value.trim() }) }).then(function (res) {
        if (!res.ok) { UI.btnState(btn, "error"); err.textContent = res.body.error || "Impossible."; err.hidden = false; return; }
        UI.btnState(btn, "success", "Déclaré"); UI.toast(res.body.message, "success", 5000); setTimeout(function () { UI.closeModal(); load(); }, 500);
      });
    });
  }
})();
