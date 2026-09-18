// KLASSIO — Abonnement (Direction) : état, palier automatique selon les
// élèves actifs, factures, déclaration de paiement. Aucun fournisseur de
// paiement branché : la plateforme confirme après vérification réelle.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var ctx = null, S = null;
  var STATUS = { trial: ["Période d'essai", ""], active: ["Actif", ""], past_due: ["Retard de paiement", "warn"], suspended: ["Lecture seule", "bad"], cancelled: ["Résilié", "bad"] };

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

  function priceLabel(p) {
    if (p.code === "reseau") return "Sur devis";
    return UI.money(p.base_price, p.currency) + (p.per_student ? " + " + UI.money(p.per_student, p.currency) + "/élève" : "");
  }
  function render() {
    var host = document.getElementById("subContent");
    var st = STATUS[S.status] || [S.status, ""];
    var sub = S.status === "trial" ? "Essai gratuit — " + (S.days_left != null ? UI.plural(S.days_left, "jour restant", "jours restants") : "") : S.status === "active" ? "Prochaine échéance : " + (S.current_period_end ? UI.fmtDate(S.current_period_end) : "—") : S.attention || "";
    var inv = S.open_invoice;
    var hero = '<div class="status-hero"><div class="sh-main"><strong>' + UI.escapeHtml(S.school_name) + "</strong><span>" + UI.escapeHtml(sub) + '</span></div><span class="sh-badge ' + st[1] + '">' + st[0] + '</span><div style="margin-left:auto;text-align:right"><div style="font-size:12px;color:rgba(231,239,227,0.7)">Palier ' + (S.plan ? UI.escapeHtml(S.plan.name) : "—") + " · " + S.students.toLocaleString("fr-FR") + ' élèves actifs</div><div style="font-size:24px;font-weight:800">' + UI.money(S.estimated_amount, S.plan ? S.plan.currency : "USD") + ' <small style="font-size:12px;font-weight:500">/ mois</small></div></div></div>';
    var invoicePanel = "";
    if (inv) {
      var due = UI.fmtDate(inv.due_at);
      invoicePanel = '<div class="panel" style="border-color:var(--lime-strong)"><div class="panel-head"><h2>Facture ' + UI.escapeHtml(inv.number) + '</h2>' + UI.badge(inv.status === "pending" ? "warn" : (S.status === "suspended" || S.status === "past_due" ? "bad" : "info"), inv.status === "pending" ? "Paiement déclaré — en attente de confirmation" : "À régler avant le " + due) + "</div>" +
        '<dl class="dl"><dt>Période</dt><dd>' + UI.fmtDate(inv.period_start) + " → " + UI.fmtDate(inv.period_end) + "</dd><dt>Élèves actifs facturés</dt><dd>" + inv.students + "</dd><dt>Palier</dt><dd>" + UI.escapeHtml(inv.plan_code) + "</dd><dt>Montant</dt><dd><strong>" + UI.money(inv.amount, inv.currency) + "</strong></dd>" + (inv.reference ? "<dt>Référence déclarée</dt><dd>" + UI.escapeHtml(inv.reference) + " (" + UI.escapeHtml(UI.METHODS[inv.method] || inv.method) + ")</dd>" : "") + "</dl>" +
        (inv.status === "open" ? '<div class="row mt-16"><button type="button" class="btn btn-lime btn-sm" id="payBtn">' + UI.icon("phone", 15) + "J'ai payé — déclarer le paiement</button></div>" : '<p class="muted mt-8">Klassio confirme votre paiement après vérification, puis votre espace repasse à jour automatiquement.</p>') + "</div>";
    }
    var plans = '<div class="panel"><div class="panel-head"><h2>Paliers</h2><span class="sub">Le palier suit automatiquement le nombre d\'élèves actifs — rien à choisir</span></div><div class="plan-grid">' + S.plans.map(function (p) {
      var current = S.plan && S.plan.code === p.code;
      return '<div class="plan-card' + (current ? " current" : "") + '"><h3>' + UI.escapeHtml(p.name) + '</h3><span class="pc-range">' + (p.max_students ? p.min_students + " – " + p.max_students + " élèves" : "au-delà de " + (p.min_students - 1) + " élèves") + '</span><span class="pc-price">' + priceLabel(p) + (p.code !== "reseau" ? " <small>/ mois</small>" : "") + "</span><p>" + UI.escapeHtml(p.description || "") + "</p>" + (current ? UI.badge("ok", "Votre palier") : "") + "</div>";
    }).join("") + "</div></div>";
    var history = '<div class="panel"><div class="panel-head"><h2>Factures</h2></div>' + (S.invoices.length ? '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>N°</th><th>Période</th><th class="num">Élèves</th><th class="num">Montant</th><th>Statut</th><th>Payée le</th></tr></thead><tbody>' + S.invoices.map(function (i) {
      return '<tr><td data-label="N°"><span class="chip-code">' + UI.escapeHtml(i.number) + '</span></td><td data-label="Période">' + UI.fmtDate(i.period_start) + " → " + UI.fmtDate(i.period_end) + '</td><td data-label="Élèves" class="num">' + i.students + '</td><td data-label="Montant" class="num">' + UI.money(i.amount, i.currency) + '</td><td data-label="Statut">' + UI.badge({ open: "warn", pending: "info", paid: "ok", void: "neutral" }[i.status], { open: "À régler", pending: "Déclarée", paid: "Payée", void: "Annulée" }[i.status]) + '</td><td data-label="Payée le">' + (i.paid_at ? UI.fmtDate(i.paid_at) : "—") + "</td></tr>";
    }).join("") + "</tbody></table></div>" : '<p class="muted">Aucune facture pendant la période d\'essai.</p>') + "</div>";
    var how = '<div class="panel"><div class="panel-head"><h2>Comment ça marche</h2></div><ol class="step-list"><li><span class="num">1</span><span><strong>30 jours d\'essai</strong>, import compris, sans engagement.</span></li><li><span class="num">2</span><span>Ensuite une <strong>facture mensuelle</strong> calculée sur vos élèves actifs — le palier s\'ajuste seul.</span></li><li><span class="num">3</span><span>Vous réglez par Mobile Money ou virement et déclarez la référence ; Klassio confirme.</span></li><li><span class="num">4</span><span>En cas de retard : rappel, puis <strong>lecture seule</strong> après ' + S.grace_days + ' jours — jamais de suppression de données.</span></li></ol><p class="note-inline">' + UI.icon("info", 15) + "<span>Circuit séparé des frais scolaires : l'argent versé par vos parents va sur le compte de l'établissement, jamais sur celui de Klassio. Beaucoup d'écoles répercutent l'abonnement via une ligne « frais numériques » dans leur catalogue.</span></p></div>";
    host.innerHTML = hero + invoicePanel + plans + '<div class="two-col">' + history + how + "</div>";
    var pb = document.getElementById("payBtn"); if (pb) pb.addEventListener("click", openPay);
  }

  function openPay() {
    var inv = S.open_invoice;
    var m = UI.modal({ title: "Déclarer le paiement de " + inv.number, body: '<form id="payForm" class="form-grid"><p class="modal-text full">Montant : <strong>' + UI.money(inv.amount, inv.currency) + '</strong>. Effectuez le paiement, puis indiquez la référence de la transaction — Klassio la vérifie avant de confirmer.</p>' +
      '<div class="field"><label for="pMethod">Moyen</label><select id="pMethod"><option value="mobile_money">Mobile Money</option><option value="bank">Virement bancaire</option></select></div><div class="field"><label for="pRef">Référence de la transaction</label><input id="pRef" required maxlength="80" placeholder="Ex. MP240911.1234.X12345" /></div><p class="form-error full" id="pErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="pCancel">Annuler</button><button type="submit" form="payForm" class="btn btn-lime btn-sm" id="pSubmit">Déclarer</button>' });
    m.querySelector("#pCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#payForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#pSubmit"), err = m.querySelector("#pErr"); err.hidden = true; UI.btnState(btn, "loading");
      api.fetch("/subscription/pay", { method: "POST", body: JSON.stringify({ invoice_id: inv.id, method: m.querySelector("#pMethod").value, reference: m.querySelector("#pRef").value.trim() }) }).then(function (res) {
        if (!res.ok) { UI.btnState(btn, "error"); err.textContent = res.body.error || "Impossible."; err.hidden = false; return; }
        UI.btnState(btn, "success", "Déclaré"); UI.toast(res.body.message, "success", 5000); setTimeout(function () { UI.closeModal(); load(); }, 500);
      });
    });
  }
})();
