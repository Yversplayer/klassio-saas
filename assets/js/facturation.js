// KLASSIO — Facturation (Direction), 08/10/2026.
//
// Le propriétaire : « inspire-toi du menu facturation de Claude ». Une offre en
// tête, le moyen de paiement, la facture en cours, l'historique, puis
// changer d'offre — en lignes calmes séparées d'un filet, pas en cartes
// empilées. Rendu dans Paramètres → Facturation ; abonnement.html y renvoie
// dès que l'espace est ouvert.
//
// Rien n'est recalculé ici : statut, jours restants, palier, montant viennent
// de GET /api/subscription (api_billing). Aucun paiement n'est simulé : la
// Direction DÉCLARE une référence, la plateforme confirme après vérification.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi;
  var ETATS = { awaiting_plan: ["warn", "Offre à choisir"], awaiting_payment: ["warn", "En attente du paiement"], trial: ["info", "Période d'essai"], active: ["ok", "Actif"], past_due: ["warn", "Facture en retard"], suspended: ["bad", "Lecture seule"], cancelled: ["neutral", "Résilié"] };
  var MAIL = "mailto:mudeyimusimwa@gmail.com";

  function montant(v, cur) { return window.KlassioOffres ? window.KlassioOffres.montant(v, cur) : UI.money(v, cur); }
  function nomOffre(S, code) {
    var p = (S.plans || []).filter(function (x) { return x.code === code; })[0];
    return p ? p.name : code;
  }
  function ligne(titre, desc, droite) {
    return '<div class="kr-ligne"><div class="kr-lib"><strong>' + titre + "</strong>" + (desc ? "<span>" + desc + "</span>" : "") + '</div><div class="kr-ctrl">' + (droite || "") + "</div></div>";
  }

  function render(host, S, opts) {
    opts = opts || {};
    if (S.awaiting) {
      host.innerHTML = '<div class="kr-bloc">' + ligne("Votre espace attend son offre", UI.escapeHtml(S.attention || "Choisissez une offre pour ouvrir l'espace de votre établissement."),
        '<a class="btn btn-lime btn-sm" href="abonnement.html">Choisir une offre</a>') + "</div>";
      return;
    }
    var plan = S.plan, cur = plan ? plan.currency : "USD", annuel = S.billing_cycle === "yearly";
    var etat = ETATS[S.status] || ["neutral", S.status];
    var sous = S.status === "trial" ? (S.days_left != null ? UI.plural(S.days_left, "jour restant", "jours restants") + " d'essai" : "Période d'essai")
      : S.current_period_end ? (annuel ? "Facturation annuelle" : "Facturation mensuelle") + " · prochaine échéance le " + UI.fmtDate(S.current_period_end) : (annuel ? "Facturation annuelle" : "Facturation mensuelle");

    var offre = '<div class="kr-offre"><span class="kr-offre-ic">' + UI.icon("receipt", 22) + '</span><div class="kr-offre-txt"><strong>Offre ' + UI.escapeHtml(plan ? plan.name : "—") + " " + UI.badge(etat[0], etat[1]) + "</strong><span>" + UI.escapeHtml(sous) + "</span><span>" + UI.plural(S.students, "élève actif", "élèves actifs") + (plan && plan.max_students ? " · jusqu'à " + plan.max_students.toLocaleString(window.KLASSIO_LOCALE || "fr-FR") + " élèves" : "") + "</span></div>" +
      '<div class="kr-offre-prix"><strong>' + montant(S.estimated_amount, cur) + "</strong><span>" + (annuel ? "par an" : "par mois") + "</span>" + (annuel && S.monthly_equivalent ? "<span>soit " + montant(S.monthly_equivalent, cur) + " par mois</span>" : "") + "</div></div>";

    var inv = S.open_invoice;
    var paiement = '<div class="kr-bloc"><h3>Paiement</h3>' +
      ligne("Moyen de paiement", "Mobile Money (M-Pesa, Orange Money, Airtel Money) ou virement bancaire. Vous déclarez la référence de la transaction ; Klassio la vérifie avant de confirmer.",
        inv && inv.status === "open" ? '<button type="button" class="btn btn-lime btn-sm" id="krPayer">' + UI.icon("phone", 15) + "Déclarer un paiement</button>"
          : inv && inv.status === "pending" ? UI.badge("info", "Paiement déclaré — en vérification") : '<span class="muted">Aucune facture à régler</span>') +
      (inv ? ligne("Facture " + UI.escapeHtml(inv.number), UI.fmtDate(inv.period_start) + " → " + UI.fmtDate(inv.period_end) + " · " + UI.escapeHtml(nomOffre(S, inv.plan_code)) + " · " + inv.students + " élèves" + (inv.reference ? " · référence " + UI.escapeHtml(inv.reference) : ""),
        "<strong>" + UI.money(inv.amount, inv.currency) + "</strong>" + (inv.status === "open" ? '<span class="kr-petit">avant le ' + UI.fmtDate(inv.due_at) + "</span>" : "")) : "") +
      "</div>";

    var factures = '<div class="kr-bloc"><h3>Factures</h3>' + (S.invoices && S.invoices.length ? '<div class="table-wrap"><table class="data-table responsive kr-table"><thead><tr><th>Période</th><th>N°</th><th class="num">Total</th><th>Statut</th><th>Payée le</th></tr></thead><tbody>' + S.invoices.map(function (i) {
      return '<tr><td data-label="Période">' + UI.fmtDate(i.period_start) + " → " + UI.fmtDate(i.period_end) + '</td><td data-label="N°"><span class="chip-code">' + UI.escapeHtml(i.number) + '</span></td><td data-label="Total" class="num">' + UI.money(i.amount, i.currency) + '</td><td data-label="Statut">' + UI.badge({ open: "warn", pending: "info", paid: "ok", void: "neutral" }[i.status] || "neutral", { open: "À régler", pending: "Déclarée", paid: "Payée", void: "Annulée" }[i.status] || i.status) + '</td><td data-label="Payée le">' + (i.paid_at ? UI.fmtDate(i.paid_at) : "—") + "</td></tr>";
    }).join("") + "</tbody></table></div>" : '<p class="kr-vide">Aucune facture pour le moment.</p>') + "</div>";

    var offres = window.KlassioOffres ? '<div class="kr-bloc"><h3>Les offres</h3><p class="kr-intro">Toutes les fonctionnalités dans chaque offre. Si votre effectif grandit, l\'offre au-dessus s\'applique d\'elle-même.</p>' + window.KlassioOffres.cartesLecture(S) + "</div>" : "";

    var changer = '<div class="kr-bloc"><h3>Changer d\'offre</h3>' +
      ligne("Changer d'offre ou de rythme de paiement", "Au mois, ou à l'année avec deux mois offerts. Écrivez à Klassio : nous ajustons votre abonnement.", '<a class="btn btn-ghost btn-sm" href="' + MAIL + '">Écrire à Klassio</a>') +
      ligne("En cas de retard", "Rappel, puis lecture seule après " + UI.plural(S.grace_days, "jour", "jours") + ". Vos données ne sont jamais supprimées pour un retard de paiement.", "") +
      ligne("Frais scolaires", "L'abonnement Klassio est distinct des frais payés par les familles : ceux-ci vont sur le compte de l'établissement, dans Finance.", '<a class="btn btn-ghost btn-sm" href="finance.html">Ouvrir Finance</a>') +
      "</div>";

    host.innerHTML = offre + (S.attention ? '<p class="note-inline note-garde">' + UI.icon("alert", 15) + "<span>" + UI.escapeHtml(S.attention) + "</span></p>" : "") + paiement + factures + offres + changer;
    var b = document.getElementById("krPayer");
    if (b) b.addEventListener("click", function () { declarer(S, opts.reload); });
  }

  function declarer(S, reload) {
    var inv = S.open_invoice;
    var m = UI.modal({ title: "Déclarer le paiement de " + inv.number, body: '<form id="payForm" class="form-grid"><p class="modal-text full">Montant : <strong>' + UI.money(inv.amount, inv.currency) + '</strong>. Effectuez le paiement, puis indiquez la référence de la transaction — Klassio la vérifie avant de confirmer.</p>' +
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
        UI.btnState(btn, "success", "Déclaré"); UI.toast(res.body.message, "success", 5000); setTimeout(function () { UI.closeModal(); if (reload) reload(); }, 500);
      }).catch(function () { UI.btnState(btn, "error"); err.textContent = "Le serveur Klassio est injoignable."; err.hidden = false; });
    });
  }

  window.KlassioFacturation = { render: render };
})();
