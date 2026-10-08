// KLASSIO — Abonnement (Direction) : état, palier automatique selon les
// élèves actifs, factures, déclaration de paiement. Aucun fournisseur de
// paiement branché : la plateforme confirme après vérification réelle.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var ctx = null, S = null;

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
    // Espace ouvert : la facturation vit dans Paramètres → Facturation
    // (08/10/2026), au même endroit que le reste du compte. Cette page reste
    // l'adresse des notifications d'abonnement ; elle y renvoie.
    window.location.replace("parametres.html?section=facturation");
  }
})();
