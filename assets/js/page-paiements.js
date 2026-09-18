// KLASSIO — Paiements. Direction : historique opérationnel (reçus émis,
// paiements en attente de confirmation), recherche, filtres, enregistrement
// d'un paiement, impression d'un reçu. Parent : frais de ses enfants,
// demandes Mobile Money, reçus.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var ctx = null, receipts = [], students = [], pending = [];

  admin.initShell("paiements").then(function (c) {
    ctx = c;
    if (c.role === "parent") { document.getElementById("pageTitle").textContent = "Frais & reçus"; document.getElementById("pageSub").textContent = "Les frais de vos enfants, vos demandes de paiement et vos reçus."; }
    else if (c.role !== "directeur") { document.getElementById("paymentsContent").innerHTML = UI.emptyState("Réservé à la Direction", "Les opérations financières ne sont pas accessibles depuis votre espace.", '<a href="dashboard.html" class="btn btn-ghost btn-sm">Retour</a>', "lock"); return; }
    else {
      document.getElementById("pageActions").innerHTML = '<button type="button" class="btn btn-lime btn-sm" id="newPayBtn">' + UI.icon("plus", 15) + "Enregistrer un paiement</button>";
      document.getElementById("newPayBtn").addEventListener("click", openRecordModal);
      if (UI.qs("new")) setTimeout(openRecordModal, 300);
    }
    load();
  });

  function load() {
    var host = document.getElementById("paymentsContent");
    host.innerHTML = UI.skeleton("row", 8);
    if (ctx.role === "parent") return loadParent();
    Promise.all([api.fetch("/receipts"), api.fetch("/students"), api.fetch("/dashboard")]).then(function (r) {
      if (!r[0].ok) return admin.loadError(host, load, "Impossible de charger les paiements");
      receipts = r[0].body; students = r[1].body || [];
      renderDirector(r[2].body);
      if (UI.qs("receipt")) openReceipt(UI.qs("receipt"));
    }).catch(function () { admin.loadError(host, load, "Le serveur Klassio est injoignable"); });
  }

  function renderDirector(dash) {
    var cur = ctx.currency;
    var html = '<div class="kpi-grid">' + UI.kpi("Paiements confirmés", (dash.total_receipts || 0).toLocaleString("fr-FR"), { icon: "receipt", sub: "reçus émis au total" }) + UI.kpi("Encaissé ce mois", UI.money(dash.paid_this_month || 0, cur), { icon: "payments", tone: "ok" }) +
      UI.kpi("À confirmer", String(dash.pending_payments), { icon: "clock", tone: dash.pending_payments ? "warn" : "", sub: "Mobile Money en attente" }) + UI.kpi("Total encaissé", UI.compactMoney(dash.total_paid, cur), { icon: "finance" }) + "</div>" +
      (dash.pending_payments ? '<div class="panel" id="pendingPanel"><div class="panel-head"><h2>Paiements à confirmer</h2><span class="sub">Demandes Mobile Money des parents — confirmez après vérification réelle.</span></div><div id="pendingList">' + UI.skeleton("row", 2) + "</div></div>" : "") +
      '<div class="panel"><div class="toolbar" style="margin-bottom:12px"><label class="search" for="paySearch">' + UI.icon("search", 16) + '<input id="paySearch" type="search" placeholder="Rechercher par élève, numéro de reçu, identifiant…" /></label><select id="methodFilter"><option value="">Tous les moyens</option><option value="cash">Espèces</option><option value="bank">Banque</option><option value="mobile_money">Mobile Money</option><option value="card">Carte</option></select><span class="count-label" id="payCount"></span></div><div id="receiptsTable"></div></div>';
    document.getElementById("paymentsContent").innerHTML = html;
    document.getElementById("paySearch").addEventListener("input", UI.debounce(renderTable, 120));
    document.getElementById("methodFilter").addEventListener("change", renderTable);
    renderTable();
    if (dash.pending_payments) loadPending();
  }

  function loadPending() {
    // Les paiements en attente sont visibles dans les dossiers financiers des élèves concernés.
    var withPending = students.filter(function (s) { return s.total_due > 0; });
    var host = document.getElementById("pendingList");
    Promise.all(withPending.slice(0, 400).map(function (s) { return api.fetch("/students/" + s.id + "/financial-summary").then(function (r) { return r.ok ? { s: s, f: r.body } : null; }); })).then(function (rows) {
      pending = [];
      rows.forEach(function (x) { if (!x) return; x.f.obligations.forEach(function (o) { o.pending_payments.forEach(function (p) { pending.push({ student: x.s, ob: o, p: p }); }); }); });
      if (!pending.length) { host.innerHTML = '<p class="muted">Aucune demande en attente.</p>'; return; }
      host.innerHTML = '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Élève</th><th>Motif</th><th>Moyen</th><th>Demandé le</th><th class="num">Montant</th><th class="actions"></th></tr></thead><tbody>' + pending.map(function (x) {
        return '<tr><td data-label="Élève"><span class="cell-main">' + UI.escapeHtml(x.student.last_name + " " + x.student.first_name) + '</span><span class="cell-sub">' + UI.escapeHtml(x.student.class_name || "") + '</span></td><td data-label="Motif">' + UI.escapeHtml(x.ob.label) + '</td><td data-label="Moyen">' + UI.escapeHtml(UI.METHODS[x.p.method] || x.p.method) + '</td><td data-label="Demandé le">' + UI.fmtDateTime(x.p.created_at) + '</td><td data-label="Montant" class="num"><strong>' + UI.money(x.p.amount, x.ob.currency) + '</strong></td><td class="actions"><button type="button" class="btn btn-lime btn-xs confirm-btn" data-id="' + x.p.id + '">Confirmer</button></td></tr>';
      }).join("") + "</tbody></table></div>";
      host.querySelectorAll(".confirm-btn").forEach(function (b) {
        b.addEventListener("click", function () {
          UI.confirm("Confirmer ce paiement ?", "Confirmez uniquement après avoir vérifié la transaction Mobile Money. Un reçu numéroté sera émis et le parent notifié.", "Confirmer").then(function (ok) {
            if (!ok) return;
            UI.btnState(b, "loading", "…");
            api.fetch("/payments/" + b.dataset.id + "/confirm", { method: "POST", body: JSON.stringify({ provider_reference: "VERIFIED_BY_DIRECTION" }) }).then(function (res) {
              if (!res.ok) { UI.btnState(b, "error"); return UI.toast(res.body.error || "Confirmation impossible.", "error"); }
              UI.toast("Paiement confirmé" + (res.body.receipt_number ? " — reçu " + res.body.receipt_number : " — reçu en cours d'émission"), "success"); load();
            });
          });
        });
      });
    });
  }

  function renderTable() {
    var q = (document.getElementById("paySearch").value || "").trim().toLowerCase(), method = document.getElementById("methodFilter").value;
    var rows = receipts.filter(function (r) { if (method && r.method !== method) return false; if (!q) return true; return (r.number + " " + r.first_name + " " + r.last_name + " " + (r.code || "") + " " + r.label).toLowerCase().indexOf(q) !== -1; });
    document.getElementById("payCount").textContent = (rows.length === receipts.length ? UI.plural(rows.length, "opération") : rows.length + " / " + receipts.length) + (receipts.length >= 300 ? " (300 dernières)" : "");
    var host = document.getElementById("receiptsTable");
    if (!receipts.length) { host.innerHTML = UI.emptyState("Aucun paiement confirmé", "Enregistrez un paiement depuis un dossier élève ou avec le bouton ci-dessus — chaque confirmation émet un reçu numéroté.", "", "payments"); return; }
    if (!rows.length) { host.innerHTML = UI.emptyState("Aucun résultat", "Modifiez votre recherche ou vos filtres.", "", "search"); return; }
    host.innerHTML = '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Reçu</th><th>Élève</th><th>Motif</th><th>Moyen</th><th>Date</th><th class="num">Montant</th><th class="actions"></th></tr></thead><tbody>' + rows.slice(0, 200).map(function (r) {
      return '<tr class="clickable" data-rid="' + r.id + '"><td data-label="Reçu"><span class="chip-code">' + UI.escapeHtml(r.number) + '</span></td><td data-label="Élève"><span class="cell-main">' + UI.escapeHtml(r.last_name + " " + r.first_name) + '</span><span class="cell-sub">' + UI.escapeHtml(r.class_name || "") + '</span></td><td data-label="Motif">' + UI.escapeHtml(r.label) + '</td><td data-label="Moyen">' + UI.badge("neutral", UI.METHODS[r.method] || r.method) + '</td><td data-label="Date">' + UI.fmtDateTime(r.created_at) + '</td><td data-label="Montant" class="num"><strong>' + UI.money(r.amount, r.currency) + '</strong></td><td class="actions">' + UI.icon("eye", 16) + "</td></tr>";
    }).join("") + "</tbody></table></div>" + (rows.length > 200 ? '<p class="muted mt-8">200 premières opérations affichées — affinez la recherche.</p>' : "");
    host.querySelectorAll("tr[data-rid]").forEach(function (tr) { tr.setAttribute("tabindex", "0"); tr.addEventListener("click", function () { openReceipt(tr.dataset.rid); }); tr.addEventListener("keydown", function (e) { if (e.key === "Enter") openReceipt(tr.dataset.rid); }); });
  }

  // ---------------- Reçu (aperçu + impression) ----------------
  function openReceipt(id) {
    api.fetch("/receipts/" + id).then(function (res) {
      if (!res.ok) return UI.toast(res.body.error || "Reçu introuvable.", "error");
      var d = res.body, r = d.receipt;
      var m = UI.modal({ title: "Reçu " + r.number, size: "lg", body: '<div class="print-sheet" id="receiptSheet"><div class="ps-head"><div class="ps-school"><strong>' + UI.escapeHtml(d.school.name) + "</strong>" + (d.school.address ? "<span>" + UI.escapeHtml(d.school.address) + "</span>" : "") + (d.school.phone ? "<span>" + UI.escapeHtml(d.school.phone) + "</span>" : "") + (d.school.email ? "<span>" + UI.escapeHtml(d.school.email) + "</span>" : "") + '</div><div style="text-align:right"><h2>REÇU</h2><span class="chip-code">' + UI.escapeHtml(r.number) + '</span><div class="muted mt-8">' + UI.fmtDateTime(r.created_at) + "</div></div></div>" +
        '<dl class="dl"><dt>Élève</dt><dd>' + UI.escapeHtml(d.student.first_name + " " + d.student.last_name) + " (" + UI.escapeHtml(d.student.code || "") + ")</dd><dt>Classe</dt><dd>" + UI.escapeHtml(d.student.class_name || "—") + "</dd><dt>Motif</dt><dd>" + UI.escapeHtml(r.label) + "</dd><dt>Moyen de paiement</dt><dd>" + UI.escapeHtml(UI.METHODS[r.method] || r.method) + (d.payment.provider_reference && d.payment.provider_reference !== "RECORDED_IN_PERSON" ? " · réf. " + UI.escapeHtml(d.payment.provider_reference) : "") + "</dd><dt>Enregistré par</dt><dd>" + UI.escapeHtml(d.payment.recorded_by || "—") + "</dd></dl>" +
        '<div class="ps-total"><span>Montant reçu</span><span>' + UI.money(r.amount, r.currency) + '</span></div><p class="ps-foot">Reçu généré par Klassio à la confirmation réelle du paiement. Numéro unique, traçable dans le dossier de l\'élève et le journal de l\'établissement.</p></div>',
        footer: '<button type="button" class="btn btn-ghost btn-sm" id="rcClose">Fermer</button><a class="btn btn-ghost btn-sm" href="eleve-dossier.html?id=' + d.student.id + '&tab=recus">Dossier de l\'élève</a><button type="button" class="btn btn-lime btn-sm" id="rcPrint">' + UI.icon("print", 15) + "Imprimer</button>" });
      m.querySelector("#rcClose").addEventListener("click", UI.closeModal);
      m.querySelector("#rcPrint").addEventListener("click", function () { printElement(document.getElementById("receiptSheet")); });
    });
  }
  function printElement(el) {
    var w = window.open("", "_blank", "width=720,height=900");
    if (!w) return UI.toast("Autorisez les fenêtres pop-up pour imprimer.", "error");
    var css = Array.prototype.map.call(document.querySelectorAll('link[rel="stylesheet"]'), function (l) { return '<link rel="stylesheet" href="' + l.href + '">'; }).join("");
    w.document.write("<!doctype html><html><head><meta charset='utf-8'><title>Impression</title>" + css + "</head><body style='padding:24px'>" + el.outerHTML + "</body></html>");
    w.document.close(); w.focus(); setTimeout(function () { w.print(); }, 400);
  }

  // ---------------- Enregistrer un paiement (Direction) ----------------
  function openRecordModal() {
    var m = UI.modal({ title: "Enregistrer un paiement", body: '<form id="recForm"><div class="field"><label for="recStudent">Élève</label><input id="recStudent" placeholder="Nom, prénom ou identifiant…" autocomplete="off" list="studentsDl" /><datalist id="studentsDl"></datalist><span class="hint">Tapez au moins 2 caractères, puis choisissez l\'élève.</span></div><div id="recObligations"></div><p class="form-error" id="recErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="recCancel">Annuler</button>' });
    m.querySelector("#recCancel").addEventListener("click", UI.closeModal);
    var input = m.querySelector("#recStudent"), dl = m.querySelector("#studentsDl"), host = m.querySelector("#recObligations");
    input.addEventListener("input", UI.debounce(function () {
      var q = input.value.trim().toLowerCase(); if (q.length < 2) return;
      var exact = students.find(function (s) { return (s.last_name + " " + s.first_name + " — " + (s.code || "")) === input.value; });
      if (exact) return pickStudent(exact);
      var matches = students.filter(function (s) { return (s.first_name + " " + s.last_name + " " + (s.code || "")).toLowerCase().indexOf(q) !== -1; }).slice(0, 12);
      dl.innerHTML = matches.map(function (s) { return '<option value="' + UI.escapeHtml(s.last_name + " " + s.first_name + " — " + (s.code || "")) + '">' + UI.escapeHtml(s.class_name || "") + "</option>"; }).join("");
      if (matches.length === 1 && q.length > 4) pickStudent(matches[0]);
    }, 120));
    function pickStudent(s) {
      host.innerHTML = UI.skeleton("row", 2);
      api.fetch("/students/" + s.id + "/financial-summary").then(function (res) {
        if (!res.ok) { host.innerHTML = '<p class="form-error">' + UI.escapeHtml(res.body.error || "Erreur.") + "</p>"; return; }
        var open = res.body.obligations.filter(function (o) { return o.remaining > 0; });
        if (!open.length) { host.innerHTML = '<p class="muted">' + UI.escapeHtml(s.first_name + " " + s.last_name) + ' n\'a aucun solde restant. <a class="link-btn" href="eleve-dossier.html?id=' + s.id + '&tab=finance">Créer une obligation</a></p>'; return; }
        host.innerHTML = '<div class="form-grid" style="margin-top:8px"><div class="field full"><label for="recOb">Obligation</label><select id="recOb">' + open.map(function (o) { return '<option value="' + o.obligation_id + '" data-remaining="' + o.remaining + '" data-cur="' + o.currency + '">' + UI.escapeHtml(o.label) + " — reste " + UI.money(o.remaining, o.currency) + "</option>"; }).join("") + '</select></div><div class="field"><label for="recAmount">Montant</label><input id="recAmount" type="number" step="0.01" min="0.01" value="' + open[0].remaining + '" required /></div><div class="field"><label for="recMethod">Moyen</label><select id="recMethod"><option value="cash">Espèces</option><option value="bank">Banque</option><option value="mobile_money">Mobile Money</option></select></div><div class="full row" style="justify-content:flex-end"><button type="submit" class="btn btn-lime btn-sm" id="recSubmit">' + UI.icon("check", 15) + "Enregistrer</button></div></div>";
        host.querySelector("#recOb").addEventListener("change", function () { host.querySelector("#recAmount").value = this.selectedOptions[0].dataset.remaining; });
        m.querySelector("#recForm").onsubmit = function (e) {
          e.preventDefault();
          var btn = host.querySelector("#recSubmit"), err = m.querySelector("#recErr"); err.hidden = true;
          UI.btnState(btn, "loading", "Enregistrement…");
          var ob = host.querySelector("#recOb").value;
          api.fetch("/payments", { method: "POST", body: JSON.stringify({ obligation_id: ob, amount: parseFloat(host.querySelector("#recAmount").value), method: host.querySelector("#recMethod").value, idempotency_key: "ui-" + ob + "-" + Date.now() }) }).then(function (res) {
            if (!res.ok) { UI.btnState(btn, "error"); err.textContent = res.body.error || "Erreur."; err.hidden = false; return; }
            UI.btnState(btn, "success", res.body.status === "CONFIRMED" ? "Enregistré" : "En attente");
            UI.toast(res.body.status === "CONFIRMED" ? "Paiement confirmé" + (res.body.receipt_number ? " — reçu " + res.body.receipt_number : "") : "Paiement Mobile Money créé, en attente de confirmation.", "success");
            setTimeout(function () { UI.closeModal(); load(); if (res.body.receipt_id) openReceipt(res.body.receipt_id); }, 500);
          });
        };
      });
    }
  }

  // ---------------- Parent ----------------
  // ======================================================================
  // ESPACE PARENT — frais, échéancier, paiement, reçus
  //
  // Tout tient sur cette page. Avant, « Payer » était un LIEN qui renvoyait
  // vers le dossier de l'élève : deux écrans pour un geste, sur un téléphone.
  //
  // Trois règles que cet écran ne peut pas enfreindre :
  //
  // 1. AUCUN FAUX SUCCÈS. Il n'existe aujourd'hui aucune intégration Mobile
  //    Money : une demande du parent reste `CREATED` jusqu'à ce que
  //    l'établissement confirme la transaction pour de vrai. L'écran dit donc
  //    « demande transmise », jamais « paiement réussi ».
  // 2. UN PAIEMENT NON CONFIRMÉ N'EST PAS UN ÉCHEC. `CREATED`, `PENDING` et
  //    `PROCESSING` s'affichent tous comme « en cours de confirmation ».
  // 3. LE MONTANT EST DÉCIDÉ PAR LE SERVEUR. Le champ est borné ici par
  //    confort, mais `financial.create_payment` revalide contre la dette
  //    réelle — un JSON modifié ne passe pas.
  // ======================================================================

  var enfants = [], recus = [], jour = null, choisi = 0;

  function loadParent() {
    var host = document.getElementById("paymentsContent");
    Promise.all([api.fetch("/dashboard"), api.fetch("/receipts")]).then(function (r) {
      if (!r[0].ok) return admin.loadError(host, load, "Impossible de charger vos frais");
      enfants = r[0].body.children || [];
      jour = r[0].body.today || null;
      recus = r[1].ok ? r[1].body : [];
      if (choisi >= enfants.length) choisi = 0;
      renderParent();
      if (UI.qs("receipt")) openReceipt(UI.qs("receipt"));
    }).catch(function () { admin.loadError(host, load, "Le serveur Klassio est injoignable"); });
  }

  // Une échéance est dépassée au regard du JOUR DU SERVEUR, jamais de l'horloge
  // du téléphone : un appareil mal réglé ferait annoncer un retard imaginaire.
  function enRetard(o) { return !!(jour && o.due_date && o.due_date < jour && o.remaining > 0); }
  function enAttente(o) { return (o.pending_payments || []).length > 0; }

  // Les tranches d'un même frais : les obligations qui partagent
  // `catalog_item_id`, dans l'ordre de leurs échéances. Le nombre de tranches
  // n'est écrit nulle part — c'est l'établissement qui le décide en créant
  // autant d'obligations qu'il le souhaite.
  function grouperEnFrais(obligations) {
    var ordre = [], parFrais = {};
    obligations.slice().sort(function (a, b) {
      if (a.due_date && b.due_date) return a.due_date < b.due_date ? -1 : a.due_date > b.due_date ? 1 : 0;
      if (a.due_date) return -1;
      if (b.due_date) return 1;
      return 0;
    }).forEach(function (o) {
      var cle = o.catalog_item_id || o.label;
      if (!parFrais[cle]) { parFrais[cle] = { cle: cle, label: o.label, lignes: [] }; ordre.push(parFrais[cle]); }
      parFrais[cle].lignes.push(o);
    });
    return ordre;
  }

  // La prochaine chose à payer : le retard d'abord, l'échéance la plus proche
  // ensuite. Une obligation sans date ne passe jamais devant une obligation
  // datée — on ne réclame pas en priorité ce que l'école n'a pas daté.
  function prochaineEcheance(obligations) {
    var dues = obligations.filter(function (o) { return o.remaining > 0 && !enAttente(o); });
    if (!dues.length) return null;
    var retards = dues.filter(enRetard);
    var pool = retards.length ? retards : dues;
    var datees = pool.filter(function (o) { return o.due_date; });
    if (!datees.length) return pool[0];
    return datees.sort(function (a, b) { return a.due_date < b.due_date ? -1 : 1; })[0];
  }

  function etatObligation(o) {
    if (o.remaining <= 0) return UI.badge("ok", "Payée");
    if (enAttente(o)) return UI.badge("warn", "En cours de confirmation");
    if (enRetard(o)) return UI.badge("bad", "En retard");
    if (o.paid > 0) return UI.badge("warn", "Partiellement payée");
    return UI.badge("neutral", "À payer");
  }

  function renderParent() {
    var host = document.getElementById("paymentsContent");
    if (!enfants.length) {
      host.innerHTML = UI.emptyState("Aucun enfant rattaché à votre compte",
        "L'accès au dossier d'un élève vient uniquement d'une invitation de l'établissement.", "", "students");
      return;
    }
    var e = enfants[choisi], s = e.student, f = e.financial;
    var cur = f.currency || ctx.currency;

    // Sélecteur d'enfant — seulement s'il y en a plusieurs. Les soldes ne sont
    // jamais additionnés entre enfants sans le dire : chaque enfant a sa page.
    var selecteur = enfants.length > 1
      ? '<div class="enfant-tabs" role="tablist">' + enfants.map(function (c, i) {
          var reste = c.financial.balance;
          return '<button type="button" class="enfant-tab' + (i === choisi ? " active" : "") + '" data-enfant="' + i + '" role="tab" aria-selected="' + (i === choisi ? "true" : "false") + '">' +
            UI.avatar(c.student, 32) + '<span class="et-id"><strong>' + UI.escapeHtml(c.student.first_name) + "</strong><span>" +
            UI.escapeHtml(c.student.class_name || "Sans classe") + "</span></span>" +
            (reste > 0 ? UI.badge("warn", UI.money(reste, c.financial.currency || cur)) : UI.badge("ok", "À jour")) + "</button>";
        }).join("") + "</div>"
      : "";

    var prochaine = prochaineEcheance(f.obligations);
    var enCours = f.obligations.filter(enAttente);

    var tete = '<div class="panel enfant-tete"><div class="row between" style="flex-wrap:wrap;gap:12px">' +
      '<div class="row">' + UI.avatar(s, 46) + '<div><h2 style="margin:0;font-size:18px">' + UI.escapeHtml(s.first_name + " " + s.last_name) + "</h2>" +
      '<span class="muted">' + UI.escapeHtml(s.class_name || "Classe non affectée") + '</span></div></div>' +
      '<a class="link-btn" href="eleve-dossier.html?id=' + s.id + '&tab=finance">Dossier complet</a></div>' +
      '<div class="kpi-grid cols-3" style="margin-top:14px">' +
      UI.kpi("Frais de l'année", UI.money(f.total_due, cur), { icon: "receipt" }) +
      UI.kpi("Déjà payé", UI.money(f.total_paid, cur), { icon: "payments", tone: "ok" }) +
      UI.kpi("Reste à payer", UI.money(f.balance, cur), { icon: "finance", tone: f.balance > 0 ? "warn" : "ok" }) +
      "</div></div>";

    // Le bloc d'action : ce qu'il faut payer maintenant, et rien d'autre.
    var action;
    if (prochaine) {
      var retard = enRetard(prochaine);
      action = '<div class="panel bloc-payer' + (retard ? " est-retard" : "") + '">' +
        '<span class="bp-kicker">' + (retard ? "Paiement en retard" : "Prochaine échéance") + "</span>" +
        '<div class="bp-ligne"><strong class="bp-montant">' + UI.money(prochaine.remaining, prochaine.currency || cur) + "</strong>" +
        '<span class="bp-label">' + UI.escapeHtml(prochaine.label) + "</span></div>" +
        (prochaine.due_date
          ? '<p class="bp-date">' + UI.icon("calendar", 15) + (retard ? "Était due le " : "À régler avant le ") + UI.fmtDate(prochaine.due_date) + "</p>"
          : '<p class="bp-date">' + UI.icon("info", 15) + "Aucune date d'échéance fixée par l'établissement.</p>") +
        '<button type="button" class="btn btn-lime bp-btn" data-payer="' + prochaine.obligation_id + '">' + UI.icon("phone", 17) + "Payer maintenant</button>" +
        "</div>";
    } else if (enCours.length) {
      action = '<div class="panel bloc-payer est-attente"><span class="bp-kicker">Paiement en cours de confirmation</span>' +
        '<div class="bp-ligne"><strong class="bp-montant">' + UI.money(enCours.reduce(function (t, o) { return t + (o.pending_payments[0].amount || 0); }, 0), cur) + "</strong>" +
        '<span class="bp-label">' + UI.plural(enCours.length, "demande transmise", "demandes transmises") + "</span></div>" +
        '<p class="bp-date">' + UI.icon("clock", 15) + "L'établissement vérifie la transaction. Votre reçu sera émis une fois le paiement confirmé.</p></div>";
    } else {
      action = '<div class="panel">' + UI.emptyState("Aucun paiement à effectuer",
        "Tous les frais facturés pour " + s.first_name + " sont réglés. Les prochaines échéances apparaîtront ici dès que l'établissement les aura publiées.",
        "", "check") + "</div>";
    }

    var echeancier = '<div class="panel"><div class="panel-head"><h2>Échéancier</h2><span class="sub">' +
      UI.plural(f.obligations.length, "frais facturé", "frais facturés") + "</span></div>" +
      (f.obligations.length ? grouperEnFrais(f.obligations).map(function (frais) {
        var plusieurs = frais.lignes.length > 1;
        return '<div class="frais-bloc">' + (plusieurs ? '<h3 class="frais-titre">' + UI.escapeHtml(frais.label) + ' <span class="muted">— ' + UI.plural(frais.lignes.length, "tranche") + "</span></h3>" : "") +
          frais.lignes.map(function (o, i) { return ligneTranche(o, plusieurs ? i + 1 : null, cur); }).join("") + "</div>";
      }).join("") : '<p class="muted">Aucun frais n\'a encore été facturé pour ' + UI.escapeHtml(s.first_name) + ".</p>") + "</div>";

    host.innerHTML = selecteur + tete + action + echeancier + historique(f, s, cur);
    wireParent();
  }

  function ligneTranche(o, numero, cur) {
    var payable = o.remaining > 0 && !enAttente(o);
    return '<div class="obligation-card' + (enRetard(o) ? " ob-retard" : "") + '">' +
      '<div class="ob-head"><span class="ob-label">' + (numero ? "Tranche " + numero + " — " : "") + UI.escapeHtml(o.label) + "</span>" + etatObligation(o) + "</div>" +
      '<div class="ob-amounts">' + UI.money(o.amount, o.currency || cur) +
      (o.paid > 0 ? " · payé " + UI.money(o.paid, o.currency || cur) : "") +
      (o.remaining > 0 ? " · <strong>reste " + UI.money(o.remaining, o.currency || cur) + "</strong>" : "") +
      (o.due_date ? " · échéance " + UI.fmtDate(o.due_date) : "") + "</div>" +
      (enAttente(o)
        ? '<div class="payment-row"><span>' + UI.icon("clock", 14) + " Demande de " + UI.money(o.pending_payments[0].amount, o.currency || cur) +
          " transmise le " + UI.fmtDate(o.pending_payments[0].created_at) + "</span><span>" + UI.badge("warn", "En cours de confirmation") + "</span></div>"
        : "") +
      (payable ? '<div class="row mt-8"><button type="button" class="btn btn-lime btn-sm" data-payer="' + o.obligation_id + '">' + UI.icon("phone", 15) + "Payer " + UI.money(o.remaining, o.currency || cur) + "</button></div>" : "") +
      "</div>";
  }

  function historique(f, s, cur) {
    // Un paiement confirmé = un reçu. On lit les paiements de l'élève affiché,
    // pas la liste globale des reçus : l'historique suit l'enfant sélectionné.
    var lignes = [];
    f.obligations.forEach(function (o) {
      (o.payments || []).forEach(function (p) { lignes.push({ o: o, p: p }); });
    });
    lignes.sort(function (a, b) { return parseFloat(b.p.confirmed_at || 0) - parseFloat(a.p.confirmed_at || 0); });
    var recusParNumero = {};
    recus.forEach(function (r) { recusParNumero[r.number] = r.id; });

    return '<div class="panel"><div class="panel-head"><h2>Historique et reçus</h2><span class="sub">' +
      UI.plural(lignes.length, "paiement confirmé", "paiements confirmés") + "</span></div>" +
      (lignes.length
        ? '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Date</th><th>Motif</th><th>Moyen</th><th class="num">Montant</th><th>Reçu</th></tr></thead><tbody>' +
          lignes.map(function (l) {
            var rid = recusParNumero[l.p.receipt_number];
            return '<tr' + (rid ? ' class="clickable" data-rid="' + rid + '"' : "") + '>' +
              '<td data-label="Date">' + UI.fmtDate(l.p.confirmed_at) + "</td>" +
              '<td data-label="Motif"><span class="cell-main">' + UI.escapeHtml(l.o.label) + '</span>' +
              (l.p.provider_reference ? '<span class="cell-sub">Réf. ' + UI.escapeHtml(l.p.provider_reference) + "</span>" : "") + "</td>" +
              '<td data-label="Moyen">' + UI.escapeHtml(UI.METHODS[l.p.method] || l.p.method) + "</td>" +
              '<td data-label="Montant" class="num"><strong>' + UI.money(l.p.amount, l.o.currency || cur) + "</strong></td>" +
              '<td data-label="Reçu">' + (l.p.receipt_number ? '<span class="chip-code">' + UI.escapeHtml(l.p.receipt_number) + "</span>" : '<span class="muted">—</span>') + "</td></tr>";
          }).join("") + "</tbody></table></div>"
        : '<p class="muted">Aucun paiement confirmé pour ' + UI.escapeHtml(s.first_name) + ". Un reçu est émis à chaque paiement confirmé par l'établissement.</p>") + "</div>";
  }

  function wireParent() {
    var host = document.getElementById("paymentsContent");
    host.querySelectorAll("[data-enfant]").forEach(function (b) {
      b.addEventListener("click", function () { choisi = parseInt(b.dataset.enfant, 10); renderParent(); });
    });
    host.querySelectorAll("[data-payer]").forEach(function (b) {
      b.addEventListener("click", function () { openPayerModal(b.dataset.payer); });
    });
    host.querySelectorAll("tr[data-rid]").forEach(function (tr) {
      tr.addEventListener("click", function () { openReceipt(tr.dataset.rid); });
    });
  }

  function trouverObligation(id) {
    var f = enfants[choisi].financial;
    return f.obligations.filter(function (o) { return o.obligation_id === id; })[0] || null;
  }

  // ---- Payer ------------------------------------------------------------
  //
  // La clé d'idempotence est calculée UNE FOIS à l'ouverture de la modale, et
  // réutilisée à chaque tentative d'envoi. C'est ce qui fait qu'un double clic,
  // un réseau qui coupe et un renvoi manuel ne produisent qu'un seul paiement :
  // le serveur reconnaît la clé et renvoie le paiement déjà créé. Une clé
  // recalculée à chaque clic — avec `Date.now()` — annulerait la protection.
  function openPayerModal(obligationId) {
    var o = trouverObligation(obligationId);
    if (!o) return;
    var s = enfants[choisi].student, cur = o.currency || ctx.currency;
    var cle = "pay-" + obligationId + "-" + Date.now();

    var m = UI.modal({
      title: "Payer — " + s.first_name,
      body: '<div id="payEtat">' +
        '<p class="modal-text" style="margin-bottom:14px"><strong>' + UI.escapeHtml(o.label) + "</strong><br>" +
        "Reste à payer : <strong>" + UI.money(o.remaining, cur) + "</strong>" +
        (o.due_date ? " · échéance " + UI.fmtDate(o.due_date) : "") + "</p>" +
        '<form id="payerForm" class="form-grid">' +
        '<div class="field full"><label for="payMontant">Montant</label>' +
        '<input id="payMontant" type="number" inputmode="decimal" step="0.01" min="0.01" max="' + o.remaining + '" value="' + o.remaining + '" required />' +
        '<span class="hint">Vous pouvez payer une partie du montant. Le total est vérifié par l\'établissement.</span></div>' +
        '<div class="field full"><label for="payMoyen">Moyen de paiement</label>' +
        '<select id="payMoyen"><option value="mobile_money">Mobile Money</option></select>' +
        '<span class="hint">Les paiements en espèces ou par banque sont enregistrés directement par l\'établissement.</span></div>' +
        '<p class="note-inline full">' + UI.icon("info", 15) +
        "<span>Votre demande est transmise à l'établissement. <strong>Elle n'est comptabilisée qu'après confirmation réelle de la transaction</strong> — vous recevrez alors une notification et votre reçu.</span></p>" +
        '<p class="form-error full" id="payerErr" hidden></p></form></div>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="payerCancel">Annuler</button>' +
              '<button type="submit" form="payerForm" class="btn btn-lime btn-sm" id="payerGo">Envoyer la demande</button>'
    });
    m.querySelector("#payerCancel").addEventListener("click", UI.closeModal);

    m.querySelector("#payerForm").addEventListener("submit", function (ev) {
      ev.preventDefault();
      var btn = m.querySelector("#payerGo"), err = m.querySelector("#payerErr");
      err.hidden = true;
      UI.btnState(btn, "loading", "Envoi…");
      api.fetch("/payments", { method: "POST", body: JSON.stringify({
        obligation_id: obligationId,
        amount: parseFloat(m.querySelector("#payMontant").value),
        method: m.querySelector("#payMoyen").value,
        idempotency_key: cle,
      }) }).then(function (res) {
        if (!res.ok) {
          UI.btnState(btn, "error");
          err.textContent = res.body.error || "Impossible d'enregistrer cette demande.";
          err.hidden = false;
          return;
        }
        // On affiche l'état RÉEL renvoyé par le serveur. `CONFIRMED` n'arrive
        // ici que si l'établissement a déjà validé la transaction ; pour un
        // Mobile Money initié par un parent, c'est `CREATED` — une demande, pas
        // un paiement. On ne dit donc jamais « réussi » à sa place.
        UI.btnState(btn, "success", "Envoyée");
        montrerResultat(m, res.body, o, cur);
      }).catch(function () {
        // Une requête interrompue n'est PAS un échec de paiement : le serveur a
        // peut-être tout enregistré. On le dit, et on invite à rafraîchir —
        // la clé d'idempotence garantit qu'un renvoi ne paiera pas deux fois.
        UI.btnState(btn, "error");
        err.innerHTML = "La connexion a été interrompue. <strong>Votre demande a peut-être bien été transmise</strong> — fermez cette fenêtre et actualisez la page avant de réessayer.";
        err.hidden = false;
      });
    });
  }

  // L'écran de résultat reflète le statut renvoyé par le serveur, et lui seul.
  function montrerResultat(m, paiement, o, cur) {
    var confirme = paiement.status === "CONFIRMED";
    var corps = m.querySelector("#payEtat");
    corps.innerHTML = '<div class="pay-resultat ' + (confirme ? "ok" : "attente") + '">' +
      '<span class="pr-ic">' + UI.icon(confirme ? "check" : "clock", 26) + "</span>" +
      "<h3>" + (confirme ? "Paiement confirmé" : "Demande transmise") + "</h3>" +
      "<p>" + (confirme
        ? "Votre paiement de " + UI.money(paiement.amount, cur) + " est enregistré." +
          (paiement.receipt_number ? " Reçu " + UI.escapeHtml(paiement.receipt_number) + "." : "")
        : "Votre demande de " + UI.money(paiement.amount, cur) + " pour « " + UI.escapeHtml(o.label) + " » a bien été transmise à l'établissement. " +
          "Elle sera comptabilisée dès que la transaction aura été vérifiée, et votre reçu sera alors disponible ici.") + "</p></div>";
    m.querySelector(".modal-foot").innerHTML = '<button type="button" class="btn btn-lime btn-sm" id="payerFin">Terminer</button>';
    m.querySelector("#payerFin").addEventListener("click", function () { UI.closeModal(); load(); });
  }
})();
