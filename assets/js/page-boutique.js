// KLASSIO — Boutique scolaire. Parent : catalogue réel, tailles/variantes,
// panier, commande pour un enfant (→ obligation dans le Financial Core),
// paiement, code de retrait. Direction/économat : produits, préparation,
// remise contre code — l'élève récupère son achat le lendemain.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var ctx = null, products = [], orders = [], children = [], cart = {}, settings = null;

  var ORDER_LABELS = { pending: "À régler", paid: "Payée — à préparer", ready: "Prête au retrait", delivered: "Remise", cancelled: "Annulée" };
  var ORDER_TONES = { pending: "warn", paid: "info", ready: "ok", delivered: "neutral", cancelled: "neutral" };

  admin.initShell("boutique").then(function (c) {
    ctx = c;
    if (c.role !== "parent" && c.role !== "directeur") { document.getElementById("storeContent").innerHTML = UI.emptyState("Boutique non disponible pour votre rôle", "", '<a href="dashboard.html" class="btn btn-ghost btn-sm">Retour</a>', "store"); return; }
    if (c.role === "directeur") {
      document.getElementById("pageSub").textContent = "Produits vendus par l'établissement, commandes des parents et retraits à l'économat — reliés au même Financial Core que les frais.";
      document.getElementById("pageActions").innerHTML = '<button type="button" class="btn btn-lime btn-sm" id="addProdBtn">' + UI.icon("plus", 15) + "Ajouter un produit</button>";
      document.getElementById("addProdBtn").addEventListener("click", function () { openProductModal(null); });
    } else document.getElementById("pageSub").textContent = "Uniformes, cahiers, livres, fournitures — commandez le soir, votre enfant retire à l'école.";
    load();
  });

  function load() {
    var host = document.getElementById("storeContent");
    host.innerHTML = '<div class="product-grid">' + UI.skeleton("card", 4) + "</div>";
    var calls = [api.fetch("/store/products"), api.fetch("/store/orders"), api.fetch("/settings")];
    if (ctx.role === "parent") calls.push(api.fetch("/students"));
    Promise.all(calls).then(function (r) {
      if (!r[0].ok) return admin.loadError(host, load, "Impossible de charger la boutique");
      products = r[0].body.map(function (p) { p.optionList = p.options ? JSON.parse(p.options) : []; return p; });
      orders = r[1].ok ? r[1].body : [];
      settings = r[2].ok ? r[2].body : {};
      children = r[3] ? r[3].body : [];
      ctx.role === "parent" ? renderParent() : renderDirector();
    }).catch(function () { admin.loadError(host, load, "Le serveur Klassio est injoignable"); });
  }

  function cartKey(id, variant) { return variant ? id + "|" + variant : id; }
  function cartParts(key) { var i = key.indexOf("|"); return i === -1 ? [key, null] : [key.slice(0, i), key.slice(i + 1)]; }

  // ---------------- Parent ----------------
  function renderParent() {
    var host = document.getElementById("storeContent");
    if (!children.length) { host.innerHTML = UI.emptyState("Aucun enfant rattaché", "La boutique est rattachée au dossier de votre enfant.", "", "students"); return; }
    var cats = {}; products.forEach(function (p) { if (p.active !== 0) (cats[p.category] = cats[p.category] || []).push(p); });
    var cutoff = settings.store_cutoff_time || "20:00";
    host.innerHTML = '<div class="panel" style="display:flex;gap:14px;align-items:center;flex-wrap:wrap"><span class="avatar-init soft" style="width:40px;height:40px">' + UI.icon("store", 18) + '</span><div class="grow"><strong>Commandez le soir, votre enfant retire le lendemain</strong><div class="muted" style="font-size:12.5px">Toute commande payée avant ' + UI.escapeHtml(cutoff) + " est préparée pour le jour ouvré suivant. L'élève retire à l'économat avec son <strong>code de retrait</strong> — sans argent liquide à l'école.</div></div></div>" +
      '<div class="two-col" style="grid-template-columns:2fr 1fr"><div>' + (Object.keys(cats).length ? Object.keys(cats).sort().map(function (c) {
        return '<div class="panel"><div class="panel-head"><h2>' + UI.escapeHtml(c.charAt(0).toUpperCase() + c.slice(1)) + '</h2></div><div class="product-grid">' + cats[c].map(productCard).join("") + "</div></div>";
      }).join("") : '<div class="panel">' + UI.emptyState("La boutique est vide pour le moment", "L'établissement n'a pas encore publié de produits.", "", "store") + "</div>") + "</div>" +
      '<div><div class="panel cart-panel"><div class="panel-head"><h2>Panier</h2></div><div id="cartBody"></div></div></div></div>' +
      '<div class="panel"><div class="panel-head"><h2>Mes commandes</h2></div>' + ordersView(false) + "</div>";
    wireProductCards();
    renderCart();
    wireOrderActions();
  }

  function productCard(p) {
    var hasOpts = p.optionList && p.optionList.length;
    return '<div class="product-card" data-pid="' + p.id + '"><span class="pc-cat">' + UI.escapeHtml(p.category) + "</span><h3>" + UI.escapeHtml(p.name) + '</h3><span class="pc-price">' + UI.money(p.price, p.currency) + '</span><span class="pc-stock">' + (p.stock > 0 ? p.stock + " disponible(s)" : "Rupture de stock") + "</span>" +
      (hasOpts && p.stock > 0 ? '<div class="pill-row" style="margin:6px 0">' + p.optionList.map(function (o, i) { return '<button type="button" class="chip var-btn' + (i === 0 ? " active" : "") + '" data-var="' + UI.escapeHtml(o) + '">' + UI.escapeHtml(o) + "</button>"; }).join("") + "</div>" : "") +
      '<div class="pc-actions">' + (p.stock > 0 ? '<div class="qty"><button type="button" class="dec" aria-label="Retirer">−</button><span class="qv">0</span><button type="button" class="inc" aria-label="Ajouter">+</button></div>' : UI.badge("neutral", "Indisponible")) + "</div></div>";
  }

  function wireProductCards() {
    document.querySelectorAll(".product-card").forEach(function (card) {
      var pid = card.dataset.pid, p = products.find(function (x) { return x.id === pid; });
      if (!p) return;
      var variant = function () { var a = card.querySelector(".var-btn.active"); return a ? a.dataset.var : null; };
      var refresh = function () { var q = cart[cartKey(pid, variant())] || 0; var el = card.querySelector(".qv"); if (el) el.textContent = q; };
      card.querySelectorAll(".var-btn").forEach(function (b) { b.addEventListener("click", function () { card.querySelectorAll(".var-btn").forEach(function (x) { x.classList.remove("active"); }); b.classList.add("active"); refresh(); }); });
      var inc = card.querySelector(".inc"), dec = card.querySelector(".dec");
      if (inc) inc.addEventListener("click", function () { var k = cartKey(pid, variant()); cart[k] = Math.min((cart[k] || 0) + 1, p.stock); refresh(); renderCart(); });
      if (dec) dec.addEventListener("click", function () { var k = cartKey(pid, variant()); cart[k] = Math.max((cart[k] || 0) - 1, 0); if (!cart[k]) delete cart[k]; refresh(); renderCart(); });
      refresh();
    });
  }

  function renderCart() {
    var body = document.getElementById("cartBody"); if (!body) return;
    var keys = Object.keys(cart);
    if (!keys.length) { body.innerHTML = '<p class="muted">Votre panier est vide.</p>'; return; }
    var total = 0, cur = null;
    var lines = keys.map(function (k) {
      var parts = cartParts(k), p = products.find(function (x) { return x.id === parts[0]; });
      if (!p) return "";
      total += p.price * cart[k]; cur = p.currency;
      return '<div class="cart-line"><span>' + cart[k] + " × " + UI.escapeHtml(p.name) + (parts[1] ? ' <span class="chip-code">' + UI.escapeHtml(parts[1]) + "</span>" : "") + "</span><span>" + UI.money(p.price * cart[k], p.currency) + "</span></div>";
    }).join("");
    body.innerHTML = lines + '<div class="cart-total"><span>Total</span><span>' + UI.money(total, cur) + '</span></div><div class="field mt-16"><label for="cartChild">Pour</label><select id="cartChild">' + children.map(function (c) { return '<option value="' + c.id + '">' + UI.escapeHtml(c.first_name + " " + c.last_name) + (c.class_name ? " — " + UI.escapeHtml(c.class_name) : "") + "</option>"; }).join("") + "</select></div>" +
      '<p class="note-inline">' + UI.icon("info", 15) + "<span>La commande crée une ligne dans le dossier de votre enfant. Réglez-la par Mobile Money ; dès confirmation, l'économat prépare et votre enfant retire avec son code.</span></p>" +
      '<button type="button" class="btn btn-lime block" id="orderBtn">' + UI.icon("cart", 16) + "Passer la commande</button>";
    document.getElementById("orderBtn").addEventListener("click", function () {
      var btn = this;
      UI.btnState(btn, "loading", "Commande en cours…");
      var items = keys.map(function (k) { var parts = cartParts(k); return { product_id: parts[0], quantity: cart[k], variant: parts[1] }; });
      api.fetch("/store/orders", { method: "POST", body: JSON.stringify({ student_id: document.getElementById("cartChild").value, items: items }) }).then(function (res) {
        if (!res.ok) { UI.btnState(btn, "error", "Réessayer"); return UI.toast(res.body.error || "Commande impossible.", "error"); }
        UI.btnState(btn, "success", "Commande " + res.body.number);
        cart = {};
        var m = UI.modal({ title: "Commande " + res.body.number + " enregistrée", body: '<p class="modal-text">Montant : <strong>' + UI.money(res.body.total, res.body.currency) + "</strong>.</p>" +
          '<p class="modal-text" style="margin-top:10px">Réglez-la depuis le dossier de votre enfant (onglet Finance). Dès que l\'établissement confirme le paiement, la commande est préparée pour le <strong>' + UI.fmtDate(res.body.pickup_date) + '</strong>.</p>' +
          '<div class="panel" style="margin-top:14px;text-align:center"><span class="muted" style="font-size:12.5px">Code de retrait de votre enfant</span><div style="font-size:30px;font-weight:800;letter-spacing:0.12em;margin-top:6px">' + UI.escapeHtml(res.body.pickup_code) + "</div></div>",
          footer: '<button type="button" class="btn btn-ghost btn-sm" id="okBtn">Fermer</button><a class="btn btn-lime btn-sm" href="eleve-dossier.html?id=' + document.getElementById("cartChild").value + '&tab=finance">Payer maintenant</a>' });
        m.querySelector("#okBtn").addEventListener("click", function () { UI.closeModal(); load(); });
      }).catch(function () { UI.btnState(btn, "error", "Réessayer"); });
    });
  }

  // ---------------- Commandes (les deux rôles) ----------------
  function ordersView(isDirector) {
    if (!orders.length) return '<p class="muted">' + (isDirector ? "Aucune commande pour le moment." : "Vous n'avez pas encore passé de commande.") + "</p>";
    return '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Commande</th>' + (isDirector ? "<th>Parent</th>" : "") + '<th>Élève</th><th>Articles</th><th>Statut</th><th class="num">Total</th><th class="num">Reste</th><th>Retrait</th><th class="actions"></th></tr></thead><tbody>' + orders.map(function (o) {
      var actions = "";
      if (isDirector) {
        if (o.status === "paid") actions = '<button type="button" class="btn btn-lime btn-xs ord-status" data-id="' + o.id + '" data-status="ready">Marquer prête</button>';
        else if (o.status === "ready") actions = '<button type="button" class="btn btn-lime btn-xs ord-deliver" data-id="' + o.id + '" data-number="' + UI.escapeHtml(o.number) + '">Remettre à l\'élève</button>';
        else if (o.status === "pending") actions = '<button type="button" class="btn btn-danger btn-xs ord-status" data-id="' + o.id + '" data-status="cancelled">Annuler</button>';
      } else if (o.status === "pending" && o.remaining > 0) actions = '<a class="btn btn-lime btn-xs" href="eleve-dossier.html?id=' + o.student_id + '&tab=finance">Payer</a>';
      var pickup = o.status === "ready" || o.status === "paid" ? (o.pickup_code ? '<span class="chip-code">' + UI.escapeHtml(o.pickup_code) + "</span>" + (o.pickup_date ? '<span class="cell-sub">dès le ' + UI.fmtDate(o.pickup_date) + "</span>" : "") : "—") : o.status === "delivered" ? '<span class="muted">Remise le ' + UI.fmtDate(o.delivered_at || o.updated_at) + "</span>" : "—";
      return '<tr><td data-label="Commande"><span class="chip-code">' + UI.escapeHtml(o.number) + '</span><span class="cell-sub">' + UI.fmtDate(o.created_at) + "</span></td>" + (isDirector ? '<td data-label="Parent">' + UI.escapeHtml(o.parent_name) + "</td>" : "") +
        '<td data-label="Élève">' + UI.escapeHtml(o.first_name + " " + o.last_name) + '</td><td data-label="Articles">' + o.items.map(function (i) { return i.quantity + " × " + UI.escapeHtml(i.name) + (i.variant ? " (" + UI.escapeHtml(i.variant) + ")" : ""); }).join(", ") + '</td><td data-label="Statut">' + UI.badge(ORDER_TONES[o.status], ORDER_LABELS[o.status]) + '</td><td data-label="Total" class="num">' + UI.money(o.total, o.currency) + '</td><td data-label="Reste" class="num ' + (o.remaining > 0 ? "text-warn" : "text-lime") + '">' + UI.money(o.remaining, o.currency) + '</td><td data-label="Retrait">' + pickup + '</td><td class="actions">' + actions + "</td></tr>";
    }).join("") + "</tbody></table></div>";
  }

  function wireOrderActions() {
    document.querySelectorAll(".ord-status").forEach(function (b) {
      b.addEventListener("click", function () {
        var st = b.dataset.status;
        UI.confirm(st === "ready" ? "Marquer cette commande comme prête ?" : "Annuler cette commande ?", st === "ready" ? "Le parent est informé que son enfant peut venir retirer avec son code." : "Le stock sera restitué et la ligne retirée du dossier de l'élève.", st === "ready" ? "Prête" : "Annuler la commande").then(function (ok) {
          if (!ok) return;
          api.fetch("/store/orders/" + b.dataset.id + "/status", { method: "POST", body: JSON.stringify({ status: st }) }).then(function (res) { if (!res.ok) return UI.toast(res.body.error || "Erreur.", "error"); UI.toast("Commande mise à jour.", "success"); load(); });
        });
      });
    });
    document.querySelectorAll(".ord-deliver").forEach(function (b) {
      b.addEventListener("click", function () {
        var m = UI.modal({ title: "Remise de la commande " + b.dataset.number, body: '<form id="dlForm" class="form-grid"><p class="modal-text full">Demandez à l\'élève son code de retrait (il figure dans l\'espace de ses parents). La remise n\'est enregistrée qu\'avec le bon code.</p>' +
          '<div class="field full"><label for="dlCode">Code de retrait</label><input id="dlCode" required maxlength="6" style="font-size:22px;letter-spacing:0.12em;text-transform:uppercase" placeholder="XXXXXX" autocomplete="off" /></div><p class="form-error full" id="dlErr" hidden></p></form>',
          footer: '<button type="button" class="btn btn-ghost btn-sm" id="dlCancel">Annuler</button><button type="submit" form="dlForm" class="btn btn-lime btn-sm" id="dlSubmit">Confirmer la remise</button>' });
        m.querySelector("#dlCancel").addEventListener("click", UI.closeModal);
        m.querySelector("#dlForm").addEventListener("submit", function (e) {
          e.preventDefault();
          var btn = m.querySelector("#dlSubmit"), err = m.querySelector("#dlErr"); err.hidden = true; UI.btnState(btn, "loading");
          api.fetch("/store/orders/" + b.dataset.id + "/status", { method: "POST", body: JSON.stringify({ status: "delivered", pickup_code: m.querySelector("#dlCode").value.trim().toUpperCase() }) }).then(function (r) {
            if (!r.ok) { UI.btnState(btn, "error"); err.textContent = r.body.error || "Impossible."; err.hidden = false; return; }
            UI.btnState(btn, "success"); UI.toast("Commande remise — le parent est informé.", "success");
            setTimeout(function () { UI.closeModal(); load(); }, 500);
          });
        });
      });
    });
  }

  // ---------------- Direction / économat ----------------
  function renderDirector() {
    var host = document.getElementById("storeContent");
    var pendingN = orders.filter(function (o) { return o.status === "pending"; }).length;
    var toPrepare = orders.filter(function (o) { return o.status === "paid"; });
    var ready = orders.filter(function (o) { return o.status === "ready"; });
    var revenue = orders.filter(function (o) { return o.status !== "cancelled"; }).reduce(function (s, o) { return s + (o.paid || 0); }, 0);
    host.innerHTML = '<div class="kpi-grid cols-5">' + UI.kpi("Produits", String(products.length), { icon: "store", sub: products.filter(function (p) { return p.active; }).length + " actifs" }) +
      UI.kpi("En attente de paiement", String(pendingN), { icon: "clock", tone: pendingN ? "warn" : "" }) +
      UI.kpi("À préparer", String(toPrepare.length), { icon: "cart", tone: toPrepare.length ? "warn" : "ok", sub: "payées, non préparées" }) +
      UI.kpi("Prêtes au retrait", String(ready.length), { icon: "check", tone: ready.length ? "info" : "" }) +
      UI.kpi("Encaissé boutique", UI.money(revenue), { icon: "finance", tone: "ok" }) + "</div>" +
      (toPrepare.length || ready.length ? '<div class="panel"><div class="panel-head"><h2>Économat — aujourd\'hui</h2><span class="sub">Préparez, puis remettez contre code</span></div><div class="roll-list">' +
        toPrepare.map(function (o) { return '<div class="roll-row"><span class="avatar-init soft" style="width:34px;height:34px;font-size:11px">' + UI.icon("cart", 15) + '</span><div class="roll-name">' + UI.escapeHtml(o.number) + " — " + UI.escapeHtml(o.first_name + " " + o.last_name) + "<span>" + o.items.map(function (i) { return i.quantity + " × " + UI.escapeHtml(i.name) + (i.variant ? " (" + UI.escapeHtml(i.variant) + ")" : ""); }).join(", ") + (o.pickup_date ? " · retrait dès le " + UI.fmtDate(o.pickup_date) : "") + '</span></div><button type="button" class="btn btn-lime btn-xs ord-status" data-id="' + o.id + '" data-status="ready">Préparée</button></div>'; }).join("") +
        ready.map(function (o) { return '<div class="roll-row"><span class="avatar-init soft" style="width:34px;height:34px;font-size:11px">' + UI.icon("check", 15) + '</span><div class="roll-name">' + UI.escapeHtml(o.number) + " — " + UI.escapeHtml(o.first_name + " " + o.last_name) + "<span>Prête · code " + UI.escapeHtml(o.pickup_code || "—") + '</span></div><button type="button" class="btn btn-ghost btn-xs ord-deliver" data-id="' + o.id + '" data-number="' + UI.escapeHtml(o.number) + '">Remettre</button></div>'; }).join("") + "</div></div>" : "") +
      '<div class="panel"><div class="panel-head"><h2>Commandes</h2></div>' + ordersView(true) + "</div>" +
      '<div class="panel"><div class="panel-head"><h2>Produits</h2><span class="sub">Heure limite de commande : ' + UI.escapeHtml(settings.store_cutoff_time || "20:00") + ' — modifiable dans Paramètres</span></div>' + (products.length ? '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Produit</th><th>Catégorie</th><th>Variantes</th><th class="num">Prix</th><th class="num">Stock</th><th>Statut</th><th class="actions"></th></tr></thead><tbody>' + products.map(function (p) {
        return '<tr><td data-label="Produit"><span class="cell-main">' + UI.escapeHtml(p.name) + '</span></td><td data-label="Catégorie">' + UI.escapeHtml(p.category) + '</td><td data-label="Variantes">' + (p.optionList.length ? p.optionList.map(function (o) { return '<span class="chip-code">' + UI.escapeHtml(o) + "</span>"; }).join(" ") : '<span class="muted">—</span>') + '</td><td data-label="Prix" class="num">' + UI.money(p.price, p.currency) + '</td><td data-label="Stock" class="num">' + (p.stock <= 3 ? UI.badge("warn", String(p.stock)) : p.stock) + '</td><td data-label="Statut">' + UI.badge(p.active ? "ok" : "neutral", p.active ? "Actif" : "Masqué") + '</td><td class="actions"><button type="button" class="btn btn-ghost btn-xs edit-prod" data-id="' + p.id + '">Modifier</button></td></tr>';
      }).join("") + "</tbody></table></div>" : UI.emptyState("Aucun produit", "Ajoutez uniformes, cahiers, livres… Les parents pourront commander depuis leur espace.", '<button type="button" class="btn btn-lime btn-sm" id="emptyProd">' + UI.icon("plus", 15) + "Ajouter un produit</button>", "store")) + "</div>";
    var e = document.getElementById("emptyProd"); if (e) e.addEventListener("click", function () { openProductModal(null); });
    host.querySelectorAll(".edit-prod").forEach(function (b) { b.addEventListener("click", function () { openProductModal(products.find(function (p) { return p.id === b.dataset.id; })); }); });
    wireOrderActions();
  }

  function openProductModal(p) {
    var m = UI.modal({ title: p ? "Modifier le produit" : "Ajouter un produit", body: '<form id="prodForm" class="form-grid"><div class="field full"><label for="pName">Nom</label><input id="pName" required value="' + UI.escapeHtml(p ? p.name : "") + '" /></div>' +
      '<div class="field"><label for="pCat">Catégorie</label><input id="pCat" list="pcats" value="' + UI.escapeHtml(p ? p.category : "fournitures") + '" /><datalist id="pcats"><option>uniformes</option><option>cahiers</option><option>livres</option><option>calligraphie</option><option>fournitures</option><option>matériel</option></datalist></div>' +
      '<div class="field"><label for="pPrice">Prix (' + UI.escapeHtml(ctx.currency) + ')</label><input id="pPrice" type="number" step="0.01" min="0.01" required value="' + (p ? p.price : "") + '" /></div>' +
      '<div class="field"><label for="pStock">Stock</label><input id="pStock" type="number" min="0" required value="' + (p ? p.stock : 0) + '" /></div>' +
      '<div class="field"><label for="pOpts">Variantes</label><input id="pOpts" value="' + UI.escapeHtml(p && p.optionList ? p.optionList.join(", ") : "") + '" placeholder="Ex. 6 ans, 8 ans, 10 ans" /><span class="hint">Tailles ou couleurs séparées par des virgules. Le parent devra en choisir une.</span></div>' +
      (p ? '<label class="check"><input type="checkbox" id="pActive"' + (p.active ? " checked" : "") + " /> Visible par les parents</label>" : "") + '<p class="form-error full" id="pErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="pCancel">Annuler</button><button type="submit" form="prodForm" class="btn btn-lime btn-sm" id="pSubmit">' + (p ? "Enregistrer" : "Ajouter") + "</button>" });
    m.querySelector("#pCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#prodForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#pSubmit"), err = m.querySelector("#pErr"); UI.btnState(btn, "loading");
      var opts = m.querySelector("#pOpts").value.split(",").map(function (x) { return x.trim(); }).filter(Boolean);
      var payload = { name: m.querySelector("#pName").value.trim(), category: m.querySelector("#pCat").value.trim(), price: parseFloat(m.querySelector("#pPrice").value), stock: parseInt(m.querySelector("#pStock").value, 10), options: opts };
      if (p) payload.active = m.querySelector("#pActive").checked;
      api.fetch(p ? "/store/products/" + p.id : "/store/products", { method: p ? "PUT" : "POST", body: JSON.stringify(payload) }).then(function (res) {
        if (!res.ok) { UI.btnState(btn, "error"); err.textContent = res.body.error || "Erreur."; err.hidden = false; return; }
        UI.btnState(btn, "success"); UI.toast(p ? "Produit mis à jour." : "Produit ajouté.", "success"); setTimeout(function () { UI.closeModal(); load(); }, 400);
      });
    });
  }
})();
