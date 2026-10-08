// KLASSIO — Boutique scolaire (refaite le 08/10/2026).
//
// Le propriétaire : « la boutique fait plus statistique que boutique ». Le
// parent voit désormais une VITRINE — photos, catégories, recherche, état du
// stock, panier — et la Direction, seule à gérer, tient son stock et ses
// chiffres dans des onglets à part : Vitrine, Stock, Commandes, Statistiques.
//
// Ce qui n'a PAS changé : le panier, les tailles, la commande rattachée au
// dossier de l'élève (une obligation du Financial Core), le paiement, le code
// de retrait. Le stock, lui, ne bouge plus sans une ligne au journal
// (POST /store/products/<id>/stock : réception, défectueux, perte, retrait,
// inventaire ; ventes et annulations s'y inscrivent seules).
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var ctx = null, products = [], orders = [], children = [], cart = {}, settings = null;
  var categorie = "", recherche = "", onglet = "vitrine", stats = null, journal = null;

  var ORDER_LABELS = { pending: "À régler", paid: "Payée — à préparer", ready: "Prête au retrait", delivered: "Remise", cancelled: "Annulée" };
  var ORDER_TONES = { pending: "warn", paid: "info", ready: "ok", delivered: "neutral", cancelled: "neutral" };
  var MOUVEMENTS = { reception: "Réception (réassort)", vente: "Vente", annulation: "Annulation de commande", defectueux: "Produit défectueux", perte: "Perte", retrait: "Retrait du stock", inventaire: "Inventaire" };

  // Photos d'illustration fournies avec Klassio (assets/boutique), choisies
  // d'après le nom ou la catégorie quand l'école n'a pas mis sa propre photo.
  var ILLUSTRATIONS = [
    [/cravate/, "cravate"], [/pantalon|culotte|short/, "pantalon"], [/jupe|robe/, "jupe"], [/pull|gilet|sweat|veste/, "pull"],
    [/chemise|polo|blouse|uniforme/, "chemise"], [/chaussure|soulier|sandale/, "chaussures"], [/sac|cartable/, "sac"],
    [/journal/, "journal"], [/calligraph|[ée]criture/, "calligraphie"], [/g[ée]om[ée]tr|r[eè]gle|compas|[ée]querre|rapporteur|trousse/, "geometrie"],
    [/livre|manuel|dictionnaire/, "manuels"], [/cahier|carnet|bloc/, "cahiers"]
  ];
  function illustration(p) {
    var texte = ((p.name || "") + " " + (p.category || "")).toLowerCase();
    for (var i = 0; i < ILLUSTRATIONS.length; i++) if (ILLUSTRATIONS[i][0].test(texte)) return ILLUSTRATIONS[i][1];
    return null;
  }
  function photo(p, taille) {
    if (p.has_image) return api.base + "/store/products/" + encodeURIComponent(p.id) + "/image?v=" + encodeURIComponent(p.image_updated_at || "1");
    var cle = illustration(p);
    return cle ? "../assets/boutique/" + cle + "-" + (taille || 480) + ".webp" : null;
  }
  function etat(p) {
    if (!p.active) return ["neutral", "Retiré de la vente"];
    if (p.stock <= 0) return ["bad", "Rupture de stock"];
    if (p.stock <= (p.min_stock || 0)) return ["warn", "Plus que " + p.stock];
    return ["ok", "En stock"];
  }
  function maj(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }

  admin.initShell("boutique").then(function (c) {
    ctx = c;
    if (c.role !== "parent" && c.role !== "directeur") { document.getElementById("storeContent").innerHTML = UI.emptyState("Boutique non disponible pour votre rôle", "", '<a href="dashboard.html" class="btn btn-ghost btn-sm">Retour</a>', "store"); return; }
    if (c.role === "directeur") {
      document.getElementById("pageSub").textContent = "Votre vitrine, votre stock, vos commandes et vos chiffres. Seule la Direction ajoute, retire et réapprovisionne les articles.";
      document.getElementById("pageActions").innerHTML = '<button type="button" class="btn btn-lime btn-sm" id="addProdBtn">' + UI.icon("plus", 15) + "Ajouter un produit</button>";
      document.getElementById("addProdBtn").addEventListener("click", function () { openProductModal(null); });
      onglet = UI.qs("tab") || "vitrine";
    } else document.getElementById("pageSub").textContent = "Uniformes, cahiers, livres, fournitures — commandez le soir, votre enfant retire à l'école.";
    load();
  });

  function load() {
    var host = document.getElementById("storeContent");
    host.innerHTML = '<div class="ks-grille">' + UI.skeleton("card", 4) + "</div>";
    var calls = [api.fetch("/store/products"), api.fetch("/store/orders"), api.fetch("/settings")];
    if (ctx.role === "parent") calls.push(api.fetch("/students"));
    Promise.all(calls).then(function (r) {
      if (!r[0].ok) return admin.loadError(host, load, "Impossible de charger la boutique");
      products = r[0].body.map(function (p) { p.optionList = p.options ? JSON.parse(p.options) : []; return p; });
      orders = r[1].ok ? r[1].body : [];
      settings = r[2].ok ? r[2].body : {};
      children = r[3] ? r[3].body : [];
      stats = null; journal = null;
      ctx.role === "parent" ? renderParent() : renderDirector();
    }).catch(function () { admin.loadError(host, load, "Le serveur Klassio est injoignable"); });
  }

  function cartKey(id, variant) { return variant ? id + "|" + variant : id; }
  function cartParts(key) { var i = key.indexOf("|"); return i === -1 ? [key, null] : [key.slice(0, i), key.slice(i + 1)]; }

  // ---------------- La vitrine (parent ; aperçu pour la Direction) ----------------
  function vitrine(apercu) {
    var visibles = products.filter(function (p) { return p.active; });
    var cats = []; visibles.forEach(function (p) { if (cats.indexOf(p.category) < 0) cats.push(p.category); }); cats.sort();
    var nomEcole = ctx.tenant_name || "votre école";
    var collage = ["chemise", "pull", "sac"].map(function (k, i) { return '<img class="ks-hero-img ks-hero-img-' + i + '" src="../assets/boutique/' + k + '-480.webp" alt="" loading="lazy" decoding="async">'; }).join("");
    return '<section class="ks-hero"><div class="ks-hero-texte"><span class="ks-hero-sur">Boutique de l\'école</span><h2>' + UI.escapeHtml(nomEcole) + "</h2>" +
        "<p>Uniformes, cahiers, livres et fournitures — commandez le soir, votre enfant retire à l'école avec son code.</p>" +
        (apercu ? '<span class="ks-apercu">Aperçu : c\'est ce que voient les parents</span>' : '<a href="#ksPanier" class="btn btn-lime btn-sm">' + UI.icon("cart", 15) + "Voir mon panier</a>") + "</div>" +
        '<div class="ks-hero-collage" aria-hidden="true">' + collage + "</div></section>" +
      '<div class="ks-barre"><div class="ks-cats" role="tablist" aria-label="Catégories">' +
        '<button type="button" role="tab" data-cat="" aria-selected="' + (categorie === "") + '">Tout</button>' +
        cats.map(function (c) { return '<button type="button" role="tab" data-cat="' + UI.escapeHtml(c) + '" aria-selected="' + (categorie === c) + '">' + UI.escapeHtml(maj(c)) + "</button>"; }).join("") + "</div>" +
        '<label class="search ks-recherche" for="ksQ">' + UI.icon("search", 16) + '<input id="ksQ" type="search" placeholder="Chercher un article…" value="' + UI.escapeHtml(recherche) + '" /></label></div>' +
      (apercu && products.some(function (p) { return p.active && !p.has_image; })
        ? '<div class="ks-avis" role="note">' + UI.icon("image", 18) + "<div><strong>Ces photos sont des illustrations Klassio.</strong> Remplacez-les par les photos des articles de votre école : touchez une photo pour la changer, et modifier au même endroit le prix, les tailles et la quantité en stock.</div></div>" : "") +
      '<div class="ks-grille" id="ksGrille"></div>';
  }

  function remplirGrille(apercu) {
    var g = document.getElementById("ksGrille"); if (!g) return;
    var q = recherche.trim().toLowerCase();
    var liste = products.filter(function (p) {
      return p.active && (!categorie || p.category === categorie) && (!q || (p.name + " " + (p.description || "") + " " + p.category).toLowerCase().indexOf(q) >= 0);
    });
    if (!liste.length) {
      g.innerHTML = '<div class="panel ks-vide">' + (products.some(function (p) { return p.active; })
        ? UI.emptyState("Aucun article ne correspond", "Essayez une autre catégorie ou un autre mot.", "", "search")
        : UI.emptyState("La boutique est vide pour le moment", apercu ? "Ajoutez votre premier produit : il apparaîtra ici pour les parents." : "L'établissement n'a pas encore publié de produits.", "", "store")) + "</div>";
      return;
    }
    g.innerHTML = (apercu ? '<button type="button" class="ks-carte ks-ajout" id="ksAjout">' + UI.icon("plus", 26) + "<strong>Nouvel article</strong><span>Photo, prix, tailles, stock</span></button>" : "") +
      liste.map(function (p) { return carte(p, apercu); }).join("");
    if (apercu) {
      // La Direction gère sa boutique depuis la vitrine elle-même : toucher un
      // article ouvre sa fiche (photo, prix, tailles, stock), sur ordinateur
      // comme sur téléphone.
      document.getElementById("ksAjout").addEventListener("click", function () { openProductModal(null); });
      g.querySelectorAll(".ks-carte[data-pid]").forEach(function (c) {
        var ouvrir = function () { openProductModal(products.find(function (x) { return x.id === c.dataset.pid; })); };
        c.addEventListener("click", ouvrir);
        c.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); ouvrir(); } });
      });
    } else wireProductCards();
  }

  function carte(p, apercu) {
    var src = photo(p), e = etat(p), dispo = p.stock > 0, opts = p.optionList && p.optionList.length;
    // Le parent voit l'article, ce qui reste en stock, le prix et les tailles —
    // rien de la gestion. La Direction voit en plus de quoi modifier.
    return '<article class="ks-carte' + (apercu ? " ks-editable" : "") + '" data-pid="' + UI.escapeHtml(p.id) + '"' + (apercu ? ' tabindex="0" role="button" aria-label="Modifier ' + UI.escapeHtml(p.name) + '"' : "") + ">" +
      '<div class="ks-photo">' + (src ? '<img src="' + UI.escapeHtml(src) + '" alt="" loading="lazy" decoding="async">' : '<span class="ks-sans-photo">' + UI.icon("store", 34) + "</span>") +
        '<span class="ks-etat ' + e[0] + '">' + UI.escapeHtml(e[1]) + "</span>" +
        (apercu ? '<span class="ks-modifier">' + UI.icon("camera", 16) + (p.has_image ? "Modifier" : "Mettre votre photo") + "</span>" : "") + "</div>" +
      '<div class="ks-corps">' + (apercu ? '<span class="ks-cat">' + UI.escapeHtml(maj(p.category)) + "</span>" : "") + "<h3>" + UI.escapeHtml(p.name) + "</h3>" +
        (apercu && p.description ? '<p class="ks-desc">' + UI.escapeHtml(p.description) + "</p>" : "") +
        (!apercu ? '<span class="ks-reste">' + (dispo ? UI.plural(p.stock, "article restant", "articles restants") : "Plus aucun article") + "</span>" : "") +
        (opts && dispo && !apercu ? '<div class="ks-tailles">' + p.optionList.map(function (o, i) { return '<button type="button" class="ks-taille var-btn' + (i === 0 ? " active" : "") + '" data-var="' + UI.escapeHtml(o) + '">' + UI.escapeHtml(o) + "</button>"; }).join("") + "</div>" : "") +
        '<div class="ks-pied"><span class="ks-prix">' + UI.money(p.price, p.currency) + "</span>" +
        (apercu ? '<span class="muted">' + p.stock + " en stock</span>"
          : dispo ? '<div class="qty"><button type="button" class="dec" aria-label="Retirer un ' + UI.escapeHtml(p.name) + '">−</button><span class="qv">0</span><button type="button" class="inc" aria-label="Ajouter un ' + UI.escapeHtml(p.name) + '">+</button></div>'
          : UI.badge("neutral", "Indisponible")) + "</div></div></article>";
  }

  function brancherVitrine(apercu) {
    document.querySelectorAll(".ks-cats [data-cat]").forEach(function (b) {
      b.addEventListener("click", function () {
        categorie = b.dataset.cat;
        document.querySelectorAll(".ks-cats [data-cat]").forEach(function (x) { x.setAttribute("aria-selected", String(x === b)); });
        remplirGrille(apercu);
      });
    });
    var q = document.getElementById("ksQ");
    if (q) q.addEventListener("input", function () { recherche = q.value; remplirGrille(apercu); });
    remplirGrille(apercu);
  }

  // ---------------- Parent ----------------
  function renderParent() {
    var host = document.getElementById("storeContent");
    if (!children.length) { host.innerHTML = UI.emptyState("Aucun enfant rattaché", "La boutique est rattachée au dossier de votre enfant.", "", "students"); return; }
    host.innerHTML = '<div class="ks-boutique"><div class="ks-rayon">' + vitrine(false) + "</div>" +
      '<aside class="ks-cote"><div class="panel cart-panel" id="ksPanier"><div class="panel-head"><h2>' + UI.icon("cart", 17) + ' Panier</h2></div><div id="cartBody"></div></div></aside></div>' +
      '<div class="panel"><div class="panel-head"><h2>Mes commandes</h2></div>' + ordersView(false) + "</div>";
    brancherVitrine(false);
    renderCart();
    wireOrderActions();
  }

  function wireProductCards() {
    document.querySelectorAll(".ks-carte").forEach(function (card) {
      var pid = card.dataset.pid, p = products.find(function (x) { return x.id === pid; });
      if (!p) return;
      var variant = function () { var a = card.querySelector(".var-btn.active"); return a ? a.dataset.var : null; };
      var refresh = function () { var q = cart[cartKey(pid, variant())] || 0; var el = card.querySelector(".qv"); if (el) el.textContent = q; card.classList.toggle("dans-panier", q > 0); };
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

  // ---------------- Direction : quatre onglets ----------------
  function renderDirector() {
    var host = document.getElementById("storeContent");
    var aPreparer = orders.filter(function (o) { return o.status === "paid"; }).length;
    var alertes = products.filter(function (p) { return p.active && p.stock <= (p.min_stock || 0); }).length;
    var defs = [["vitrine", "Vitrine", "store", 0], ["stock", "Stock", "list", alertes], ["commandes", "Commandes", "cart", aPreparer], ["stats", "Statistiques", "reports", 0]];
    host.innerHTML = '<div class="tabs" id="ksTabs" role="tablist">' + defs.map(function (d) {
      return '<button type="button" class="tab-btn" data-tab="' + d[0] + '">' + UI.icon(d[2], 15) + d[1] + (d[3] ? '<span class="cnt">' + d[3] + "</span>" : "") + "</button>";
    }).join("") + "</div>" + defs.map(function (d) { return '<div data-tab-panel="' + d[0] + '" hidden></div>'; }).join("");
    document.querySelector('[data-tab-panel="vitrine"]').innerHTML = vitrine(true);
    brancherVitrine(true);
    document.querySelector('[data-tab-panel="stock"]').innerHTML = vueStock();
    document.querySelector('[data-tab-panel="commandes"]').innerHTML = vueCommandes();
    document.querySelector('[data-tab-panel="stats"]').innerHTML = '<div class="panel">' + UI.skeleton("row", 4) + "</div>";
    var tabs = UI.tabs(document.getElementById("ksTabs"), function (n) { onglet = n; history.replaceState(null, "", "boutique.html?tab=" + n); if (n === "stats") chargerStats(); });
    tabs.activate(["vitrine", "stock", "commandes", "stats"].indexOf(onglet) >= 0 ? onglet : "vitrine", true);
    if (onglet === "stats") chargerStats();
    brancherStock();
    wireOrderActions();
  }

  function vueCommandes() {
    var toPrepare = orders.filter(function (o) { return o.status === "paid"; });
    var ready = orders.filter(function (o) { return o.status === "ready"; });
    return (toPrepare.length || ready.length ? '<div class="panel"><div class="panel-head"><h2>Économat — aujourd\'hui</h2><span class="sub">Préparez, puis remettez contre code</span></div><div class="roll-list">' +
        toPrepare.map(function (o) { return '<div class="roll-row"><span class="avatar-init soft" style="width:34px;height:34px;font-size:11px">' + UI.icon("cart", 15) + '</span><div class="roll-name">' + UI.escapeHtml(o.number) + " — " + UI.escapeHtml(o.first_name + " " + o.last_name) + "<span>" + o.items.map(function (i) { return i.quantity + " × " + UI.escapeHtml(i.name) + (i.variant ? " (" + UI.escapeHtml(i.variant) + ")" : ""); }).join(", ") + (o.pickup_date ? " · retrait dès le " + UI.fmtDate(o.pickup_date) : "") + '</span></div><button type="button" class="btn btn-lime btn-xs ord-status" data-id="' + o.id + '" data-status="ready">Préparée</button></div>'; }).join("") +
        ready.map(function (o) { return '<div class="roll-row"><span class="avatar-init soft" style="width:34px;height:34px;font-size:11px">' + UI.icon("check", 15) + '</span><div class="roll-name">' + UI.escapeHtml(o.number) + " — " + UI.escapeHtml(o.first_name + " " + o.last_name) + "<span>Prête · code " + UI.escapeHtml(o.pickup_code || "—") + '</span></div><button type="button" class="btn btn-ghost btn-xs ord-deliver" data-id="' + o.id + '" data-number="' + UI.escapeHtml(o.number) + '">Remettre</button></div>'; }).join("") + "</div></div>" : "") +
      '<div class="panel"><div class="panel-head"><h2>Commandes</h2><span class="sub">Heure limite de commande : ' + UI.escapeHtml(settings.store_cutoff_time || "20:00") + " — modifiable dans Paramètres</span></div>" + ordersView(true) + "</div>";
  }

  // ---- Stock : chaque article, son état, ses mouvements ----
  function vueStock() {
    if (!products.length) return '<div class="panel">' + UI.emptyState("Aucun produit", "Ajoutez uniformes, cahiers, livres… Les parents pourront commander depuis leur espace.", '<button type="button" class="btn btn-lime btn-sm" id="emptyProd">' + UI.icon("plus", 15) + "Ajouter un produit</button>", "store") + "</div>";
    var ruptures = products.filter(function (p) { return p.active && p.stock <= 0; }).length;
    var bas = products.filter(function (p) { return p.active && p.stock > 0 && p.stock <= (p.min_stock || 0); }).length;
    var valeur = products.filter(function (p) { return p.active; }).reduce(function (s, p) { return s + p.stock * p.price; }, 0);
    var cur = products[0] ? products[0].currency : null;
    return '<div class="kpi-grid cols-4">' + UI.kpi("Articles en vente", String(products.filter(function (p) { return p.active; }).length), { icon: "store", sub: products.filter(function (p) { return !p.active; }).length + " retiré(s) de la vente" }) +
      UI.kpi("Ruptures", String(ruptures), { icon: "alert", tone: ruptures ? "bad" : "ok", sub: "plus rien à vendre" }) +
      UI.kpi("Stock bas", String(bas), { icon: "clock", tone: bas ? "warn" : "ok", sub: "sous le seuil d'alerte" }) +
      UI.kpi("Valeur du stock", UI.money(valeur, cur), { icon: "finance", sub: "au prix de vente" }) + "</div>" +
      '<div class="panel"><div class="panel-head"><h2>Articles</h2><span class="sub">Réception, défectueux, perte, retrait, inventaire : tout passe au journal</span></div>' +
      '<div class="table-wrap"><table class="data-table responsive ks-table"><thead><tr><th>Article</th><th class="num">Prix</th><th class="num">Stock</th><th>État</th><th class="actions"></th></tr></thead><tbody>' +
      products.map(function (p) {
        var e = etat(p), src = photo(p, 480);
        return '<tr><td data-label="Article"><div class="ks-ligne">' + (src ? '<img src="' + UI.escapeHtml(src) + '" alt="" loading="lazy">' : '<span class="ks-mini-vide">' + UI.icon("store", 16) + "</span>") +
          '<div><span class="cell-main">' + UI.escapeHtml(p.name) + '</span><span class="cell-sub">' + UI.escapeHtml(maj(p.category)) + (p.optionList.length ? " · " + UI.escapeHtml(p.optionList.join(", ")) : "") + "</span></div></div></td>" +
          '<td data-label="Prix" class="num">' + UI.money(p.price, p.currency) + '</td><td data-label="Stock" class="num"><strong>' + p.stock + '</strong><span class="cell-sub">seuil ' + (p.min_stock || 0) + "</span></td>" +
          '<td data-label="État">' + UI.badge(e[0], e[1]) + "</td>" +
          '<td class="actions"><div class="ks-actions">' +
            '<button type="button" class="btn btn-lime btn-xs ks-mvt" data-id="' + UI.escapeHtml(p.id) + '" data-kind="reception">' + UI.icon("plus", 13) + "Réception</button>" +
            '<button type="button" class="btn btn-ghost btn-xs ks-mvt" data-id="' + UI.escapeHtml(p.id) + '" data-kind="sortie">Sortie</button>' +
            '<button type="button" class="btn btn-ghost btn-xs ks-mvt" data-id="' + UI.escapeHtml(p.id) + '" data-kind="inventaire">Inventaire</button>' +
            '<button type="button" class="btn btn-ghost btn-xs edit-prod" data-id="' + UI.escapeHtml(p.id) + '">Modifier</button></div></td></tr>';
      }).join("") + "</tbody></table></div></div>";
  }

  function brancherStock() {
    var e = document.getElementById("emptyProd"); if (e) e.addEventListener("click", function () { openProductModal(null); });
    document.querySelectorAll(".edit-prod").forEach(function (b) { b.addEventListener("click", function () { openProductModal(products.find(function (p) { return p.id === b.dataset.id; })); }); });
    document.querySelectorAll(".ks-mvt").forEach(function (b) { b.addEventListener("click", function () { ouvrirMouvement(products.find(function (p) { return p.id === b.dataset.id; }), b.dataset.kind); }); });
  }

  function ouvrirMouvement(p, kind) {
    if (!p) return;
    var choix = kind === "sortie"
      ? '<div class="field full"><label for="mvKind">Pourquoi sort-il du stock ?</label><select id="mvKind"><option value="defectueux">Produit défectueux (abîmé, mal taillé)</option><option value="perte">Perte (perdu, volé, introuvable)</option><option value="retrait">Retrait du stock (fin de saison, vidage)</option></select></div>'
      : '<input type="hidden" id="mvKind" value="' + kind + '">';
    var titre = kind === "reception" ? "Réception — " : kind === "inventaire" ? "Inventaire — " : "Sortie de stock — ";
    var aide = kind === "reception" ? "Combien d'articles arrivent ? Ils s'ajoutent au stock (" + p.stock + " aujourd'hui)."
      : kind === "inventaire" ? "Combien en avez-vous compté ? Ce nombre devient le stock (" + p.stock + " selon Klassio) ; l'écart passe au journal."
      : "Combien sortent ? Ils quittent le stock (" + p.stock + " aujourd'hui) et ne sont plus vendus.";
    var m = UI.modal({ title: titre + p.name, body: '<form id="mvForm" class="form-grid"><p class="modal-text full">' + UI.escapeHtml(aide) + "</p>" + choix +
      '<div class="field"><label for="mvQty">' + (kind === "inventaire" ? "Quantité comptée" : "Quantité") + '</label><input id="mvQty" type="number" min="' + (kind === "inventaire" ? 0 : 1) + '" step="1" required value="' + (kind === "inventaire" ? p.stock : 1) + '"></div>' +
      '<div class="field' + (kind === "reception" || kind === "inventaire" ? "" : " full") + '"><label for="mvRaison">' + (kind === "sortie" ? "Raison (obligatoire)" : "Note (facultatif)") + '</label><input id="mvRaison" maxlength="200"' + (kind === "sortie" ? " required" : "") + ' placeholder="' + (kind === "sortie" ? "Ex. Couture défaite, taille 8 ans" : "Ex. Livraison du fournisseur") + '"></div>' +
      '<p class="form-error full" id="mvErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="mvCancel">Annuler</button><button type="submit" form="mvForm" class="btn btn-lime btn-sm" id="mvOk">Enregistrer</button>' });
    m.querySelector("#mvCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#mvForm").addEventListener("submit", function (ev) {
      ev.preventDefault();
      var btn = m.querySelector("#mvOk"), err = m.querySelector("#mvErr"); err.hidden = true; UI.btnState(btn, "loading");
      api.fetch("/store/products/" + encodeURIComponent(p.id) + "/stock", { method: "POST", body: JSON.stringify({ kind: m.querySelector("#mvKind").value, quantity: parseInt(m.querySelector("#mvQty").value, 10), reason: m.querySelector("#mvRaison").value.trim() }) }).then(function (r) {
        if (!r.ok) { UI.btnState(btn, "error"); err.textContent = r.body.error || "Impossible."; err.hidden = false; return; }
        UI.btnState(btn, "success"); UI.toast(r.body.unchanged ? "Stock inchangé." : "Stock mis à jour : " + r.body.stock + " en stock.", "success");
        onglet = "stock"; setTimeout(function () { UI.closeModal(); load(); }, 400);
      });
    });
  }

  // ---- Statistiques ----
  function chargerStats() {
    if (stats) return;
    Promise.all([api.fetch("/store/stats"), api.fetch("/store/movements")]).then(function (r) {
      var panneau = document.querySelector('[data-tab-panel="stats"]');
      if (!r[0].ok) return admin.loadError(panneau, function () { stats = null; chargerStats(); }, "Impossible de charger les statistiques");
      stats = r[0].body; journal = r[1].ok ? r[1].body : [];
      panneau.innerHTML = vueStats();
    });
  }

  function vueStats() {
    var t = stats.totaux, cur = products[0] ? products[0].currency : null;
    var max = Math.max.apply(null, stats.par_mois.map(function (m) { return m.montant; }).concat([1]));
    var vendus = stats.produits.filter(function (p) { return p.vendus > 0; });
    var dormants = stats.produits.filter(function (p) { return p.active && p.vendus === 0 && p.stock > 0; });
    return '<div class="kpi-grid cols-4">' + UI.kpi("Encaissé", UI.money(t.encaisse, cur), { icon: "finance", tone: "ok", sub: "commandes payées" }) +
      UI.kpi("En attente de paiement", UI.money(t.en_attente, cur), { icon: "clock", tone: t.en_attente ? "warn" : "" }) +
      UI.kpi("Commandes", String(t.commandes), { icon: "cart", sub: t.a_preparer + " à préparer" }) +
      UI.kpi("Produits défectueux", String(t.defectueux), { icon: "alert", tone: t.defectueux ? "warn" : "ok", sub: "sortis du stock" }) + "</div>" +
      '<div class="two-col"><div class="panel"><div class="panel-head"><h2>Ventes par mois</h2><span class="sub">6 derniers mois</span></div>' +
        (stats.par_mois.length ? '<div class="ks-barres">' + stats.par_mois.map(function (m) {
          var d = new Date(m.mois + "-01T00:00:00");
          return '<div class="ks-barre-col"><span class="ks-barre-val">' + UI.escapeHtml(UI.compactMoney ? UI.compactMoney(m.montant, cur) : String(m.montant)) + '</span><span class="ks-histo-barre" style="height:' + Math.max(4, Math.round(m.montant / max * 100)) + '%"></span><span class="ks-barre-mois">' + d.toLocaleDateString((window.KLASSIO_LOCALE || "fr-FR"), { month: "short" }) + "</span></div>";
        }).join("") + "</div>" : '<p class="muted">Aucune vente pour le moment.</p>') + "</div>" +
      '<div class="panel"><div class="panel-head"><h2>Ce qui se vend</h2><span class="sub">quantités vendues</span></div>' +
        UI.barRows(vendus.slice(0, 8).map(function (p) { return { label: p.name, value: p.vendus }; }), { empty: "Aucune vente pour le moment." }) + "</div></div>" +
      '<div class="two-col"><div class="panel"><div class="panel-head"><h2>À surveiller</h2><span class="sub">ruptures, stock bas, articles qui dorment</span></div>' +
        (stats.produits.some(function (p) { return p.etat === "rupture" || p.etat === "bas"; }) || dormants.length ? '<ul class="ks-surveiller">' +
          stats.produits.filter(function (p) { return p.etat === "rupture" || p.etat === "bas"; }).map(function (p) { return "<li>" + UI.badge(p.etat === "rupture" ? "bad" : "warn", p.etat === "rupture" ? "Rupture" : "Stock bas") + " " + UI.escapeHtml(p.name) + ' <span class="muted">· ' + p.stock + " en stock</span></li>"; }).join("") +
          dormants.slice(0, 5).map(function (p) { return "<li>" + UI.badge("neutral", "Aucune vente") + " " + UI.escapeHtml(p.name) + ' <span class="muted">· ' + p.stock + " en stock</span></li>"; }).join("") + "</ul>"
          : '<p class="muted">Rien à signaler : aucun article en rupture ni sous son seuil.</p>') + "</div>" +
      '<div class="panel"><div class="panel-head"><h2>Journal du stock</h2><span class="sub">derniers mouvements</span></div>' +
        (journal.length ? '<div class="timeline">' + journal.slice(0, 12).map(function (m) {
          return '<div class="tl-item"><span class="tl-dot ' + (m.quantity > 0 ? "" : "warn") + '"></span><div class="tl-body"><strong>' + UI.escapeHtml(MOUVEMENTS[m.kind] || m.kind) + " · " + UI.escapeHtml(m.product_name) + " " + (m.quantity > 0 ? "+" : "") + m.quantity + "</strong>" +
            "<span>" + UI.escapeHtml(m.reason || "") + (m.user_name ? " — " + UI.escapeHtml(m.user_name) : "") + "</span><em>" + UI.fmtDateTime(m.created_at) + " · stock après : " + m.stock_after + "</em></div></div>";
        }).join("") + "</div>" : '<p class="muted">Aucun mouvement enregistré.</p>') + "</div></div>";
  }

  // ---- Produit : ajout et modification (Direction seule) ----
  // La photo est réduite DANS le navigateur (800 px, JPEG) avant l'envoi :
  // une photo de téléphone fait 3 à 5 Mo, la boutique n'en a besoin que de
  // 100 Ko — et le serveur refuse tout ce qui dépasse 400 Ko.
  function reduirePhoto(fichier) {
    return new Promise(function (resolve, reject) {
      // Sur téléphone, « image/* » propose l'appareil photo ou la galerie ; la
      // photo est ensuite convertie en JPEG ici, quel que soit son format.
      if (!/^image\//.test(fichier.type)) return reject(new Error("Choisissez une photo."));
      var lecteur = new FileReader();
      lecteur.onerror = function () { reject(new Error("Lecture impossible.")); };
      lecteur.onload = function () {
        var img = new Image();
        img.onerror = function () { reject(new Error("Ce fichier n'est pas une image lisible.")); };
        img.onload = function () {
          var cote = 800, r = Math.min(1, cote / Math.max(img.width, img.height));
          var c = document.createElement("canvas"); c.width = Math.round(img.width * r); c.height = Math.round(img.height * r);
          c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
          resolve(c.toDataURL("image/jpeg", 0.82));
        };
        img.src = lecteur.result;
      };
      lecteur.readAsDataURL(fichier);
    });
  }

  function openProductModal(p) {
    var nouvellePhoto;   // undefined : inchangée ; null : retirée ; chaîne : nouvelle
    var apercu = p ? photo(p, 480) : null;
    var m = UI.modal({ title: p ? "Modifier le produit" : "Ajouter un produit", size: "lg", body: '<form id="prodForm" class="form-grid">' +
      '<div class="field full ks-photo-champ"><div class="ks-photo-apercu" id="pPhotoApercu">' + (apercu ? '<img src="' + UI.escapeHtml(apercu) + '" alt="">' : UI.icon("image", 28)) + "</div>" +
        '<div><label for="pPhoto">Photo du produit</label><input id="pPhoto" type="file" accept="image/*">' +
        '<span class="hint">Une photo de votre article. Sans photo, Klassio affiche une illustration d\'après le nom (chemise, cravate, cahier…).</span>' +
        (p && p.has_image ? '<button type="button" class="link-btn" id="pPhotoRetirer">Retirer la photo</button>' : "") + "</div></div>" +
      '<div class="field full"><label for="pName">Nom</label><input id="pName" required maxlength="120" value="' + UI.escapeHtml(p ? p.name : "") + '" placeholder="Ex. Chemise blanche à manches courtes" /></div>' +
      '<div class="field full"><label for="pDesc">Description</label><input id="pDesc" maxlength="300" value="' + UI.escapeHtml(p && p.description ? p.description : "") + '" placeholder="Ex. Tissu coton, logo brodé de l\'école" /></div>' +
      '<div class="field"><label for="pCat">Catégorie</label><input id="pCat" list="pcats" value="' + UI.escapeHtml(p ? p.category : "uniformes") + '" /><datalist id="pcats"><option>uniformes</option><option>cahiers</option><option>livres</option><option>calligraphie</option><option>fournitures</option><option>matériel</option></datalist></div>' +
      '<div class="field"><label for="pPrice">Prix (' + UI.escapeHtml(ctx.currency) + ')</label><input id="pPrice" type="number" step="0.01" min="0.01" required value="' + (p ? p.price : "") + '" /></div>' +
      '<div class="field"><label for="pStock">' + (p ? "Quantité en stock" : "Stock de départ") + '</label><input id="pStock" type="number" min="0" required value="' + (p ? p.stock : 0) + '" />' +
        (p ? '<span class="hint">Changer ce nombre enregistre un inventaire au journal du stock.</span>' : "") + "</div>" +
      '<div class="field"><label for="pMin">Seuil d\'alerte</label><input id="pMin" type="number" min="0" value="' + (p ? (p.min_stock || 0) : 3) + '" /><span class="hint">Sous ce nombre, l\'article est signalé « stock bas ».</span></div>' +
      '<div class="field full"><label for="pOpts">Tailles ou variantes</label><input id="pOpts" value="' + UI.escapeHtml(p && p.optionList ? p.optionList.join(", ") : "") + '" placeholder="Ex. 6 ans, 8 ans, 10 ans" /><span class="hint">Séparées par des virgules. Le parent devra en choisir une.</span></div>' +
      (p ? '<label class="check full"><input type="checkbox" id="pActive"' + (p.active ? " checked" : "") + " /> En vente (visible par les parents)</label>" : "") +
      '<p class="form-error full" id="pErr" hidden></p></form>',
      footer: (p ? '<button type="button" class="btn btn-danger btn-sm" id="pDelete" style="margin-right:auto">Supprimer</button>' : "") +
        '<button type="button" class="btn btn-ghost btn-sm" id="pCancel">Annuler</button><button type="submit" form="prodForm" class="btn btn-lime btn-sm" id="pSubmit">' + (p ? "Enregistrer" : "Ajouter") + "</button>" });
    m.querySelector("#pCancel").addEventListener("click", UI.closeModal);
    var err = m.querySelector("#pErr");
    m.querySelector("#pPhoto").addEventListener("change", function () {
      var f = this.files && this.files[0]; if (!f) return;
      err.hidden = true;
      reduirePhoto(f).then(function (url) {
        nouvellePhoto = url;
        m.querySelector("#pPhotoApercu").innerHTML = '<img src="' + url + '" alt="">';
      }, function (e) { err.textContent = e.message; err.hidden = false; });
    });
    var retirer = m.querySelector("#pPhotoRetirer");
    if (retirer) retirer.addEventListener("click", function () { nouvellePhoto = null; m.querySelector("#pPhotoApercu").innerHTML = UI.icon("image", 28); });
    var del = m.querySelector("#pDelete");
    if (del) del.addEventListener("click", function () {
      UI.btnState(del, "loading");
      api.fetch("/store/products/" + encodeURIComponent(p.id), { method: "DELETE" }).then(function (r) {
        if (!r.ok) { UI.btnState(del, "error"); err.textContent = r.body.error || "Impossible de supprimer."; err.hidden = false; return; }
        UI.toast("Produit supprimé.", "success"); onglet = "stock"; UI.closeModal(); load();
      });
    });
    m.querySelector("#prodForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#pSubmit"); err.hidden = true; UI.btnState(btn, "loading");
      var opts = m.querySelector("#pOpts").value.split(",").map(function (x) { return x.trim(); }).filter(Boolean);
      var payload = { name: m.querySelector("#pName").value.trim(), description: m.querySelector("#pDesc").value.trim(), category: m.querySelector("#pCat").value.trim(),
        price: parseFloat(m.querySelector("#pPrice").value), min_stock: parseInt(m.querySelector("#pMin").value, 10) || 0, options: opts };
      var qte = parseInt(m.querySelector("#pStock").value, 10) || 0;
      if (!p || qte !== p.stock) payload.stock = qte;
      if (p) payload.active = m.querySelector("#pActive").checked;
      if (nouvellePhoto !== undefined) payload.image_data = nouvellePhoto;
      api.fetch(p ? "/store/products/" + encodeURIComponent(p.id) : "/store/products", { method: p ? "PUT" : "POST", body: JSON.stringify(payload) }).then(function (res) {
        if (!res.ok) { UI.btnState(btn, "error"); err.textContent = res.body.error || "Erreur."; err.hidden = false; return; }
        UI.btnState(btn, "success"); UI.toast(p ? "Produit mis à jour." : "Produit ajouté.", "success"); setTimeout(function () { UI.closeModal(); load(); }, 400);
      });
    });
  }
})();
