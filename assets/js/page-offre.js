// KLASSIO — page de paiement (app/offre.html, 07/10/2026).
//
// On y arrive depuis l'inscription (après l'import), depuis la connexion
// (« J'ai déjà un compte » sur les tarifs), ou parce que l'espace de l'école
// est fermé (admin.js y renvoie la Direction). L'offre et la période choisies
// sur la landing voyagent dans l'adresse (?offre=ecole&cycle=yearly) et ne
// font que PRÉSÉLECTIONNER : c'est le serveur qui accepte ou refuse.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi;
  var host = document.getElementById("offreHost");
  var titre = document.getElementById("kpTitre");
  var sous = document.getElementById("kpSous");
  var offre = (location.search.match(/[?&]offre=([a-z]+)/) || [])[1] || null;
  var cycle = /[?&]cycle=yearly(&|$)/.test(location.search) ? "yearly" : "monthly";

  // L'écran de gauche ne s'anime qu'avec ce script (sans lui : tout affiché).
  var ecran = document.querySelector(".kp-ecran");
  if (ecran) ecran.classList.add("kp-anime");

  if (!api.estConnecte()) {
    window.location.replace("connexion.html?suite=offre" + (offre ? "&offre=" + offre : "") + (cycle === "yearly" ? "&cycle=yearly" : ""));
    return;
  }

  function message(t, texte, lienHref, lienTexte) {
    titre.textContent = t;
    sous.textContent = texte;
    host.innerHTML = lienHref ? '<a class="of-cta is-primary" href="' + lienHref + '">' + UI.escapeHtml(lienTexte) + "</a>" : "";
  }

  function charger() {
    host.innerHTML = UI.skeleton ? UI.skeleton("card", 2) : "";
    api.fetch("/me").then(function (moi) {
      if (!moi.ok) return;
      if (moi.body.role !== "directeur") {
        return message("Réservé à la Direction", "Seule la Direction de l'établissement choisit et règle l'offre Klassio.", "dashboard.html", "Retour à mon espace");
      }
      return api.fetch("/subscription").then(function (res) {
        if (!res.ok) { host.innerHTML = '<p class="form-error">' + UI.escapeHtml(res.body.error || "Impossible de charger les offres.") + "</p>"; return; }
        var S = res.body;
        if (!S.awaiting && !(S.open_invoice && S.open_invoice.status === "open")) {
          return message("Votre abonnement est actif", "Rien à régler pour le moment : votre espace est ouvert.", "dashboard.html", "Entrer dans mon espace");
        }
        if (S.open_invoice && S.open_invoice.status === "pending") {
          titre.textContent = "Paiement déclaré";
          sous.textContent = "Klassio vérifie votre paiement. Vous n'avez rien d'autre à faire.";
        } else if (S.open_invoice && S.open_invoice.status === "open") {
          titre.textContent = "Réglez votre facture";
          sous.textContent = "Payez par Mobile Money ou virement, puis indiquez la référence : votre espace s'ouvre pendant la vérification.";
        }
        window.KlassioOffres.render(host, S, {
          preselect: offre, cycle: cycle, reload: charger,
          onDeclared: function () { charger(); },
          onBypass: function () { window.location.href = "dashboard.html"; }
        });
      });
    }).catch(function () {
      host.innerHTML = '<p class="form-error">Le serveur Klassio est injoignable. Réessayez dans un instant.</p>';
    });
  }
  charger();
})();
