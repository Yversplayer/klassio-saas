// KLASSIO — section Tarifs de la landing (07/10/2026).
//
// Deux choses, rien d'autre :
//   1. la bascule Mensuel / Annuel. Les prix annuels sont ceux que le serveur
//      facture (backend/db.py, PRIX_ANNUELS_2026_10) ; ils sont écrits dans la
//      page, en attributs data-, et vérifiés par tests/test_abonnement.py ;
//   2. la fenêtre de choix : le directeur « qui a trouvé », puis créer son
//      espace ou se connecter, l'offre et la période portées dans l'adresse.
//
// Sans ce script, la section reste entière : prix mensuels, liens directs
// vers l'inscription. Mouvement réduit : les chiffres changent sans défiler.
(function () {
  "use strict";
  var section = document.getElementById("tarifs");
  if (!section) return;
  var bascule = section.querySelector(".kx-tp-switch");
  var cartes = [].slice.call(section.querySelectorAll(".kx-tp-card[data-mensuel]"));
  var fenetre = document.getElementById("tpModal");
  var reduit = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var cycle = "monthly";

  function montant(v, decimales) {
    // Espace fine (U+202F) absente de la police : « 1499 $ » collé. Insécable ordinaire.
    return v.toLocaleString("fr-FR", { minimumFractionDigits: decimales, maximumFractionDigits: decimales }).replace(/\u202f/g, "\u00a0") + "\u00a0$";
  }
  function decimalesDe(v) { return Math.round(v) === v ? 0 : 2; }

  function defiler(el, depart, arrivee) {
    var dec = decimalesDe(arrivee);
    if (reduit || depart === arrivee) { el.textContent = montant(arrivee, dec); return; }
    var debut = null;
    function pas(t) {
      if (debut === null) debut = t;
      var k = Math.min(1, (t - debut) / 650);
      k = 1 - Math.pow(1 - k, 3);
      el.textContent = montant(k < 1 ? depart + (arrivee - depart) * k : arrivee, k < 1 ? 2 : dec);
      if (k < 1) window.requestAnimationFrame(pas);
    }
    window.requestAnimationFrame(pas);
  }

  function lienInscription(code) {
    return "app/inscription.html?offre=" + encodeURIComponent(code) + (cycle === "yearly" ? "&cycle=yearly" : "");
  }

  function appliquer(nouveau) {
    if (nouveau === cycle) return;
    var ancien = cycle;
    cycle = nouveau;
    bascule.querySelectorAll(".kx-tp-opt").forEach(function (b) {
      b.setAttribute("aria-pressed", b.dataset.cycle === cycle ? "true" : "false");
    });
    cartes.forEach(function (carte) {
      var de = parseFloat(ancien === "yearly" ? carte.dataset.annuel : carte.dataset.mensuel);
      var a = parseFloat(cycle === "yearly" ? carte.dataset.annuel : carte.dataset.mensuel);
      defiler(carte.querySelector(".kx-tp-num"), de, a);
      carte.querySelector(".kx-tp-per").textContent = cycle === "yearly" ? "/ an" : "/ mois";
      carte.querySelector(".kx-tp-eq").hidden = cycle !== "yearly";
      carte.querySelector(".kx-tp-cta").href = lienInscription(carte.dataset.code);
    });
  }

  if (bascule) {
    bascule.hidden = false;
    bascule.addEventListener("click", function (e) {
      var b = e.target.closest(".kx-tp-opt");
      if (b) appliquer(b.dataset.cycle);
    });
  }

  // Fenêtre de choix. Sans <dialog> (navigateur ancien) : le lien direct suffit.
  if (!fenetre || typeof fenetre.showModal !== "function") return;
  var recap = document.getElementById("tpRecap");
  var creer = document.getElementById("tpCreer");
  var connexion = document.getElementById("tpConnexion");

  cartes.forEach(function (carte) {
    carte.querySelector(".kx-tp-cta").addEventListener("click", function (e) {
      e.preventDefault();
      var code = carte.dataset.code;
      var prix = parseFloat(cycle === "yearly" ? carte.dataset.annuel : carte.dataset.mensuel);
      recap.innerHTML = "Offre <b>" + carte.dataset.nom.replace(/[<>&"]/g, "") + "</b> · " +
        montant(prix, decimalesDe(prix)) + (cycle === "yearly" ? " par an, 2 mois offerts" : " par mois") +
        ". Toutes les fonctionnalités, utilisateurs illimités.";
      creer.href = lienInscription(code);
      connexion.href = "app/connexion.html?suite=offre&offre=" + encodeURIComponent(code) + (cycle === "yearly" ? "&cycle=yearly" : "");
      fenetre.showModal();
      creer.focus();
    });
  });
  fenetre.addEventListener("click", function (e) {
    // Un clic sur le fond (hors du contenu) ferme, comme Échap.
    if (e.target === fenetre || e.target.closest("[data-tp-close]")) fenetre.close();
  });
})();
