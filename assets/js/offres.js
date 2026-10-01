// KLASSIO — le choix de l'offre, obligatoire avant l'ouverture d'un espace.
//
// Utilisé à deux endroits : l'étape « Votre offre » de l'inscription (après
// le dépôt des fichiers Excel) et l'écran Abonnement d'un espace pas encore
// ouvert. Il n'existe pas de mode gratuit (décision du propriétaire,
// 01/10/2026).
//
// CE QUE CE FICHIER NE DÉCIDE PAS. Le serveur refuse une offre plus petite
// que l'effectif, refuse l'offre sur devis en libre-service, émet la facture,
// et seul un administrateur de la plateforme confirme un paiement. L'écran
// grise ce que le serveur refuserait — par confort — et affiche ce que le
// serveur répond. Le bouton « mode testeur » n'apparaît que si le SERVEUR dit
// que le contournement est actif (KLASSIO_CONTOURNER_ABONNEMENT) : il ne fait
// que naviguer, il n'ouvre rien.
//
// Aucun faux succès : « paiement déclaré » n'est affiché qu'après la réponse
// du serveur, et rien ne prétend qu'un paiement est confirmé avant qu'il le soit.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi;
  var WHATSAPP = "243971839237";

  function wa(texte) { return "https://wa.me/" + WHATSAPP + "?text=" + encodeURIComponent(texte); }
  // Toujours deux décimales : « 99,90 $ », comme sur la page Tarifs — un prix
  // affiché « 99,9 $ » fait brouillon sur une offre commerciale.
  function montant(v, cur) {
    return Number(v).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + (!cur || cur === "USD" ? " $" : " " + cur);
  }
  function prix(p) { return montant(p.base_price, p.currency); }
  function tranche(p) {
    return p.max_students ? (p.min_students ? "De " + p.min_students.toLocaleString("fr-FR") + " à " : "Jusqu'à ") + p.max_students.toLocaleString("fr-FR") + " élèves"
                          : "Plus de " + (p.min_students - 1).toLocaleString("fr-FR") + " élèves ou plusieurs établissements";
  }
  function surDevis(p) { return p.max_students == null && !Number(p.base_price); }

  // host : élément à remplir. S : réponse de GET /api/subscription.
  // opts : { preselect: code, onDeclared: fn(S), onBypass: fn(), reload: fn() }
  function render(host, S, opts) {
    opts = opts || {};
    var inv = S.open_invoice;
    var choisi = S.status === "awaiting_payment" && S.plan ? S.plan.code : (opts.preselect || (S.required_plan && S.required_plan.code));
    var html = "";

    if (S.bypass) {
      html += '<div class="of-tester">' + UI.icon("info", 15) + "<span><strong>Mode testeur actif sur ce serveur.</strong> L'abonnement est contourné : vous pouvez entrer sans payer pour tester le logiciel. Ce mode n'existe pas en production.</span>" +
        (opts.onBypass ? '<button type="button" class="btn btn-ghost btn-sm" id="ofBypass">Entrer sans payer (testeur)</button>' : "") + "</div>";
    }

    if (inv && inv.status === "pending") {
      html += '<div class="of-wait"><span class="of-wait-ic">' + UI.icon("clock", 20) + "</span><div><strong>Paiement déclaré — en attente de confirmation</strong>" +
        "<p>Facture " + UI.escapeHtml(inv.number) + " · " + montant(inv.amount, inv.currency) + " · référence " + UI.escapeHtml(inv.reference || "—") +
        ". Votre espace s'ouvre dès que Klassio a vérifié le paiement.</p>" +
        '<a class="btn btn-ghost btn-sm" target="_blank" rel="noopener" href="' + wa("Bonjour, je viens de déclarer le paiement de la facture " + inv.number + " pour " + (S.school_name || "mon établissement") + ".") + '">' + UI.icon("phone", 15) + "Prévenir Klassio sur WhatsApp</a></div></div>";
      host.innerHTML = html;
      wireBypass(host, opts);
      return;
    }

    html += '<div class="plan-grid of-grid">' + S.plans.map(function (p) {
      var trop = p.max_students != null && S.students > p.max_students;
      var devis = surDevis(p);
      var reco = S.required_plan && S.required_plan.code === p.code;
      return '<label class="plan-card of-card' + (trop ? " of-off" : "") + (choisi === p.code ? " current" : "") + '">' +
        (devis ? "" : '<input type="radio" name="ofPlan" value="' + UI.escapeHtml(p.code) + '"' + (choisi === p.code ? " checked" : "") + (trop ? " disabled" : "") + ">") +
        "<h3>" + UI.escapeHtml(p.name) + "</h3>" +
        '<span class="pc-range">' + UI.escapeHtml(tranche(p)) + "</span>" +
        '<span class="pc-price">' + (devis ? "Sur devis" : prix(p) + " <small>/ mois</small>") + "</span>" +
        "<p>Toutes les fonctionnalités, utilisateurs illimités.</p>" +
        (trop ? '<span class="of-note">Votre établissement compte ' + S.students.toLocaleString("fr-FR") + " élèves</span>" : "") +
        (reco && !devis ? UI.badge("ok", "Adaptée à votre effectif") : "") +
        (devis ? '<a class="btn btn-ghost btn-sm" target="_blank" rel="noopener" href="' + wa("Bonjour, je souhaite un devis Klassio pour " + (S.school_name || "notre réseau d'établissements") + ".") + '">Demander un devis</a>' : "") +
        "</label>";
    }).join("") + "</div>";

    html += '<p class="form-error" id="ofErr" hidden></p>';
    if (inv && inv.status === "open") {
      html += payBlock(S, inv);
    } else {
      html += '<div class="of-actions"><button type="button" class="btn btn-lime" id="ofChoose">Choisir cette offre</button></div>';
    }
    host.innerHTML = html;
    wireBypass(host, opts);

    var err = host.querySelector("#ofErr");
    function erreur(t) { err.textContent = t; err.hidden = !t; }
    host.querySelectorAll('input[name="ofPlan"]').forEach(function (r) {
      r.addEventListener("change", function () {
        host.querySelectorAll(".of-card").forEach(function (c) { c.classList.toggle("current", c.contains(r) && r.checked); });
        var b = host.querySelector("#ofChoose");
        if (!b) {
          // Une facture est déjà ouverte : changer d'offre la remplace.
          var zone = host.querySelector(".of-pay");
          if (zone) zone.outerHTML = '<div class="of-actions"><button type="button" class="btn btn-lime" id="ofChoose">Changer pour cette offre</button></div>';
          wireChoose();
        }
      });
    });
    function wireChoose() {
      var b = host.querySelector("#ofChoose");
      if (!b) return;
      b.addEventListener("click", function () {
        erreur("");
        var sel = host.querySelector('input[name="ofPlan"]:checked');
        if (!sel) return erreur("Choisissez une offre.");
        UI.btnState(b, "loading", "Enregistrement…");
        api.fetch("/subscription/choose", { method: "POST", body: JSON.stringify({ plan_code: sel.value }) }).then(function (res) {
          if (!res.ok) { UI.btnState(b, "idle"); return erreur(res.body.error || "Impossible d'enregistrer cette offre."); }
          if (opts.reload) opts.reload();
        }).catch(function () { UI.btnState(b, "idle"); erreur("Le serveur Klassio est injoignable. Réessayez dans un instant."); });
      });
    }
    wireChoose();
    wirePay(host, S, opts, erreur);
  }

  function payBlock(S, inv) {
    return '<div class="of-pay"><div class="of-pay-head"><div><span class="of-kicker">Facture ' + UI.escapeHtml(inv.number) + "</span><strong>" + montant(inv.amount, inv.currency) + "</strong> <small>pour le premier mois</small></div></div>" +
      "<ol class=\"of-steps\"><li>Demandez les coordonnées de paiement Klassio (Mobile Money ou virement) : " +
      '<a target="_blank" rel="noopener" href="' + wa("Bonjour, je souhaite régler la facture " + inv.number + " (" + inv.amount + " " + inv.currency + ") pour " + (S.school_name || "mon établissement") + ".") + '">écrire sur WhatsApp</a>.</li>' +
      "<li>Effectuez le paiement.</li><li>Indiquez ici la référence de la transaction : Klassio la vérifie, puis ouvre votre espace.</li></ol>" +
      '<form class="of-form" id="ofPayForm"><div class="field"><label for="ofMethod">Moyen</label><select id="ofMethod"><option value="mobile_money">Mobile Money</option><option value="bank">Virement bancaire</option></select></div>' +
      '<div class="field"><label for="ofRef">Référence de la transaction</label><input id="ofRef" required maxlength="80" placeholder="Ex. MP240911.1234.X12345"></div>' +
      '<button type="submit" class="btn btn-lime" id="ofPaySubmit">Déclarer le paiement</button></form></div>';
  }

  function wirePay(host, S, opts, erreur) {
    var f = host.querySelector("#ofPayForm");
    if (!f) return;
    f.addEventListener("submit", function (e) {
      e.preventDefault();
      erreur("");
      var b = host.querySelector("#ofPaySubmit");
      UI.btnState(b, "loading", "Envoi…");
      api.fetch("/subscription/pay", { method: "POST", body: JSON.stringify({ invoice_id: S.open_invoice.id, method: host.querySelector("#ofMethod").value, reference: host.querySelector("#ofRef").value.trim() }) }).then(function (res) {
        if (!res.ok) { UI.btnState(b, "idle"); return erreur(res.body.error || "Impossible de déclarer ce paiement."); }
        if (opts.onDeclared) opts.onDeclared(res.body);
        else if (opts.reload) opts.reload();
      }).catch(function () { UI.btnState(b, "idle"); erreur("La connexion a été interrompue. Votre déclaration a peut-être été reçue — rechargez avant de la renvoyer."); });
    });
  }

  function wireBypass(host, opts) {
    var b = host.querySelector("#ofBypass");
    if (b && opts.onBypass) b.addEventListener("click", opts.onBypass);
  }

  window.KlassioOffres = { render: render, whatsapp: wa };
})();
