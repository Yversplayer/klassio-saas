// KLASSIO — le choix de l'offre, obligatoire avant l'ouverture d'un espace.
//
// Utilisé par la page de paiement (app/offre.html) et l'écran Abonnement d'un
// espace pas encore ouvert. Il n'existe pas de mode gratuit (décision du
// propriétaire, 01/10/2026) ; on paie au mois ou à l'année (07/10/2026,
// « 2 mois offerts »).
//
// CE QUE CE FICHIER NE DÉCIDE PAS. Le serveur refuse une offre plus petite
// que l'effectif, refuse l'offre sur devis en libre-service et l'annuel sur
// une offre qui n'en a pas, émet la facture, et seul un administrateur de la
// plateforme confirme un paiement. L'écran grise ce que le serveur refuserait
// — par confort — et affiche ce que le serveur répond. Le bouton « mode
// testeur » n'apparaît que si le SERVEUR dit que le contournement est actif.
//
// Aucun faux succès : « paiement déclaré » n'est affiché qu'après la réponse
// du serveur, et rien ne prétend qu'un paiement est confirmé avant qu'il le soit.
//
// Présentation refaite le 07/10/2026 sur le modèle des cartes de la landing
// (médaillon, prix, un bouton par offre) : même composant, mêmes routes.
(function () {
  "use strict";
  var UI = window.KlassioUI;
  // Résolu À L'USAGE, pas au chargement : ce fichier peut être chargé avant
  // app.js, qui définit KlassioApi (constaté le 01/10/2026).
  var api = { fetch: function (chemin, opts) { return window.KlassioApi.fetch(chemin, opts); } };
  var WHATSAPP = "243971839237";
  var ICONES = {
    essentiel: '<path d="M12 21V11"/><path d="M12 11c0-4 3-6 7-6 0 4-3 6-7 6Z"/><path d="M12 14c0-3-2.5-5-6-5 0 3 2.5 5 6 5Z"/>',
    ecole: '<path d="M3 10 12 5l9 5"/><path d="M5 10v9h14v-9"/><path d="M10 19v-5h4v5"/>',
    complexe: '<path d="M3 20V9l5-3 5 3v11"/><path d="M13 20v-8l4-2 4 2v8"/><path d="M2 20h20"/><path d="M6.5 13h3M6.5 16h3M16 15h2"/>',
    reseau: '<circle cx="12" cy="5" r="2.2"/><circle cx="5" cy="18" r="2.2"/><circle cx="19" cy="18" r="2.2"/><path d="M11 7 6 16M13 7l5 9M7.2 18h9.6"/>'
  };

  function wa(texte) { return "https://wa.me/" + WHATSAPP + "?text=" + encodeURIComponent(texte); }
  // « 99,90 $ » au mois ; « 999 $ » à l'année (montants ronds). Jamais « 99,9 $ ».
  function montant(v, cur) {
    var n = Number(v), dec = Math.round(n) === n ? 0 : 2;
    // L'espace fine (U+202F) du français n'existe pas dans la police du site :
    // « 1499 $ » s'affichait collé. Espace insécable ordinaire à la place.
    return n.toLocaleString("fr-FR", { minimumFractionDigits: dec, maximumFractionDigits: 2 }).replace(/\u202f/g, "\u00a0") + (!cur || cur === "USD" ? "\u00a0$" : " " + cur);
  }
  function tranche(p) {
    return p.max_students ? (p.min_students ? "De " + p.min_students.toLocaleString("fr-FR") + " à " : "Jusqu'à ") + p.max_students.toLocaleString("fr-FR") + " élèves"
                          : "Plus de " + (p.min_students - 1).toLocaleString("fr-FR") + " élèves ou plusieurs établissements";
  }
  function surDevis(p) { return p.max_students == null && !Number(p.base_price); }
  function annuelPossible(p) { return p.yearly_price != null && !surDevis(p); }
  function medaille(code) {
    return '<span class="of-medal" aria-hidden="true"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' + (ICONES[code] || ICONES.ecole) + "</svg></span>";
  }

  // host : élément à remplir. S : réponse de GET /api/subscription.
  // opts : { preselect: code, cycle: "monthly"|"yearly", onDeclared: fn(S),
  //          onBypass: fn(), reload: fn() }
  function render(host, S, opts) {
    opts = opts || {};
    var inv = S.open_invoice;
    var auMoinsUnAnnuel = S.plans.some(annuelPossible);
    var etat = {
      cycle: (inv && inv.billing_cycle) || S.billing_cycle === "yearly" && "yearly" || (opts.cycle === "yearly" ? "yearly" : "monthly"),
      choix: !(inv && inv.status === "open")
    };
    if (!auMoinsUnAnnuel) etat.cycle = "monthly";

    function testeur() {
      if (!S.bypass) return "";
      return '<div class="of-tester">' + UI.icon("info", 15) + "<span><strong>Mode testeur actif sur ce serveur.</strong> L'abonnement est contourné : vous pouvez entrer sans payer pour tester le logiciel. Ce mode n'existe pas en production.</span>" +
        (opts.onBypass ? '<button type="button" class="btn btn-ghost btn-sm" id="ofBypass">Entrer sans payer (testeur)</button>' : "") + "</div>";
    }

    if (inv && inv.status === "pending") {
      // Ouverture provisoire (72 h, une fois) : le SERVEUR dit si elle court.
      var jusqua = S.provisional && S.provisional_until ? new Date(parseFloat(S.provisional_until) * 1000) : null;
      host.innerHTML = testeur() + '<div class="of-wait"><span class="of-wait-ic">' + UI.icon("clock", 20) + "</span><div><strong>Paiement déclaré — " + (jusqua ? "en cours de vérification" : "en attente de confirmation") + "</strong>" +
        "<p>Facture " + UI.escapeHtml(inv.number) + " · " + montant(inv.amount, inv.currency) + " · référence " + UI.escapeHtml(inv.reference || "—") + ". " +
        (jusqua ? "Votre espace est ouvert pendant la vérification, jusqu'au " + jusqua.toLocaleDateString("fr-FR", { day: "numeric", month: "long" }) + " à " + jusqua.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }) + "." : "Votre espace s'ouvre dès que Klassio a vérifié le paiement.") + "</p>" +
        (jusqua ? '<a class="btn btn-lime btn-sm" href="dashboard.html">Entrer dans mon espace</a> ' : "") +
        '<a class="btn btn-ghost btn-sm" target="_blank" rel="noopener" href="' + wa("Bonjour, je viens de déclarer le paiement de la facture " + inv.number + " pour " + (S.school_name || "mon établissement") + ".") + '">' + UI.icon("phone", 15) + "Prévenir Klassio sur WhatsApp</a></div></div>";
      wireBypass(host, opts);
      return;
    }

    function prixDe(p) {
      return etat.cycle === "yearly" && annuelPossible(p) ? Number(p.yearly_price) : Number(p.base_price);
    }

    function vueCartes() {
      var html = testeur();
      if (auMoinsUnAnnuel) {
        html += '<div class="of-switch" role="group" aria-label="Période de facturation">' +
          '<button type="button" class="of-opt" data-cycle="monthly" aria-pressed="' + (etat.cycle === "monthly") + '">Mensuel</button>' +
          '<button type="button" class="of-opt" data-cycle="yearly" aria-pressed="' + (etat.cycle === "yearly") + '">Annuel <span class="of-gift">2 mois offerts</span></button></div>';
      }
      var choisi = (inv && inv.plan_code) || opts.preselect || (S.required_plan && S.required_plan.code);
      html += '<div class="of-plans">' + S.plans.map(function (p) {
        var trop = p.max_students != null && S.students > p.max_students;
        var devis = surDevis(p);
        var reco = S.required_plan && S.required_plan.code === p.code;
        var prix = prixDe(p);
        var annuel = etat.cycle === "yearly" && annuelPossible(p);
        return '<article class="of-plan' + (choisi === p.code && !trop ? " is-choice" : "") + (trop ? " is-off" : "") + '">' +
          medaille(p.code) +
          '<div class="of-plan-top"><h3>' + UI.escapeHtml(p.name) + "</h3>" + (reco && !devis && !trop ? '<span class="of-reco">Votre effectif</span>' : "") + "</div>" +
          '<span class="of-range">' + UI.escapeHtml(tranche(p)) + "</span>" +
          '<p class="of-price">' + (devis ? "<b>Sur devis</b>" : "<b>" + montant(prix, p.currency) + "</b> <small>" + (annuel ? "/ an" : "/ mois") + "</small>") + "</p>" +
          (annuel ? '<span class="of-eq">soit ' + montant(Math.round(prix / 12 * 100) / 100, p.currency) + " par mois</span>" : '<span class="of-eq">Toutes les fonctionnalités</span>') +
          (trop ? '<span class="of-note">Votre établissement compte ' + S.students.toLocaleString("fr-FR") + " élèves</span>"
            : devis ? '<a class="of-cta" target="_blank" rel="noopener" href="' + wa("Bonjour, je souhaite un devis Klassio pour " + (S.school_name || "notre réseau d'établissements") + ".") + '">Demander un devis</a>'
            : '<button type="button" class="of-cta' + (choisi === p.code ? " is-primary" : "") + '" data-plan="' + UI.escapeHtml(p.code) + '">Choisir ' + UI.escapeHtml(p.name) + "</button>") +
          "</article>";
      }).join("") + "</div>";
      html += '<p class="form-error" id="ofErr" role="alert" hidden></p>';
      host.innerHTML = html;
      wireBypass(host, opts);
      host.querySelectorAll(".of-opt").forEach(function (b) {
        b.addEventListener("click", function () { if (etat.cycle !== b.dataset.cycle) { etat.cycle = b.dataset.cycle; vueCartes(); } });
      });
      host.querySelectorAll(".of-cta[data-plan]").forEach(function (b) {
        b.addEventListener("click", function () { choisir(b, b.dataset.plan); });
      });
    }

    function erreur(t) { var e = host.querySelector("#ofErr"); if (e) { e.textContent = t; e.hidden = !t; } }

    function choisir(bouton, code) {
      erreur("");
      UI.btnState(bouton, "loading", "Enregistrement…");
      api.fetch("/subscription/choose", { method: "POST", body: JSON.stringify({ plan_code: code, billing_cycle: etat.cycle }) }).then(function (res) {
        if (!res.ok) { UI.btnState(bouton, "idle"); return erreur(res.body.error || "Impossible d'enregistrer cette offre."); }
        if (opts.reload) opts.reload();
      }).catch(function () { UI.btnState(bouton, "idle"); erreur("Le serveur Klassio est injoignable. Réessayez dans un instant."); });
    }

    function vuePaiement() {
      var plan = S.plans.filter(function (p) { return p.code === inv.plan_code; })[0];
      var annuel = inv.billing_cycle === "yearly";
      host.innerHTML = testeur() + '<div class="of-pay">' +
        '<div class="of-pay-head">' + medaille(inv.plan_code) + '<div><span class="of-kicker">Facture ' + UI.escapeHtml(inv.number) + "</span>" +
        "<strong>" + montant(inv.amount, inv.currency) + "</strong> <small>" + (annuel ? "pour un an" : "pour le premier mois") + " · offre " + UI.escapeHtml(plan ? plan.name : inv.plan_code) + "</small></div>" +
        '<button type="button" class="of-link" id="ofChanger">Changer d\'offre</button></div>' +
        '<form class="of-form" id="ofPayForm" novalidate>' +
        '<fieldset class="of-methods"><legend>Comment payez-vous ?</legend>' +
        '<label class="of-method"><input type="radio" name="ofMethod" value="mobile_money" checked><span><b>Mobile Money</b><small>M-Pesa, Orange Money, Airtel Money</small></span></label>' +
        '<label class="of-method"><input type="radio" name="ofMethod" value="bank"><span><b>Virement bancaire</b><small>Depuis le compte de l\'établissement</small></span></label></fieldset>' +
        '<ol class="of-steps"><li>Demandez les coordonnées de paiement Klassio : <a target="_blank" rel="noopener" href="' + wa("Bonjour, je souhaite régler la facture " + inv.number + " (" + inv.amount + " " + inv.currency + ") pour " + (S.school_name || "mon établissement") + ".") + '">WhatsApp</a> ou <a href="mailto:mudeyimusimwa@gmail.com">mudeyimusimwa@gmail.com</a>.</li>' +
        "<li>Effectuez le paiement, puis indiquez sa référence : Klassio la vérifie et ouvre votre espace.</li></ol>" +
        '<div class="field"><label for="ofRef">Référence de la transaction</label><input id="ofRef" required maxlength="80" placeholder="Ex. MP240911.1234.X12345"></div>' +
        '<button type="submit" class="btn btn-lime" id="ofPaySubmit">Déclarer le paiement</button></form>' +
        '<p class="form-error" id="ofErr" role="alert" hidden></p></div>';
      wireBypass(host, opts);
      host.querySelector("#ofChanger").addEventListener("click", function () { etat.choix = true; vueCartes(); });
      var f = host.querySelector("#ofPayForm");
      f.addEventListener("submit", function (e) {
        e.preventDefault();
        erreur("");
        var ref = host.querySelector("#ofRef").value.trim();
        if (!ref) return erreur("Indiquez la référence de la transaction.");
        var methode = host.querySelector('input[name="ofMethod"]:checked').value;
        var b = host.querySelector("#ofPaySubmit");
        UI.btnState(b, "loading", "Envoi…");
        api.fetch("/subscription/pay", { method: "POST", body: JSON.stringify({ invoice_id: inv.id, method: methode, reference: ref }) }).then(function (res) {
          if (!res.ok) { UI.btnState(b, "idle"); return erreur(res.body.error || "Impossible de déclarer ce paiement."); }
          if (opts.onDeclared) opts.onDeclared(res.body);
          else if (opts.reload) opts.reload();
        }).catch(function () { UI.btnState(b, "idle"); erreur("La connexion a été interrompue. Votre déclaration a peut-être été reçue — rechargez avant de la renvoyer."); });
      });
    }

    if (etat.choix) vueCartes(); else vuePaiement();
  }

  function wireBypass(host, opts) {
    var b = host.querySelector("#ofBypass");
    if (b && opts.onBypass) b.addEventListener("click", opts.onBypass);
  }

  // Les offres EN LECTURE SEULE, pour l'écran Abonnement d'une école déjà
  // ouverte : le même dessin que le choix, sans bouton (changer d'offre en
  // cours d'abonnement passe par Klassio — le serveur refuse /choose, 409).
  // Chaque carte montre le prix au mois ET à l'année ; l'offre de l'école et
  // son cycle sont signalés.
  function cartesLecture(S) {
    var actuel = S.plan ? S.plan.code : null;
    var cycle = S.billing_cycle === "yearly" ? "yearly" : "monthly";
    return '<div class="of-plans of-plans-4">' + S.plans.map(function (p) {
      var devis = surDevis(p);
      var c = p.code === actuel;
      return '<article class="of-plan' + (c ? " is-choice" : "") + '">' + medaille(p.code) +
        '<div class="of-plan-top"><h3>' + UI.escapeHtml(p.name) + "</h3>" + (c ? '<span class="of-reco">Votre offre' + (cycle === "yearly" ? " · à l'année" : " · au mois") + "</span>" : "") + "</div>" +
        '<span class="of-range">' + UI.escapeHtml(tranche(p)) + "</span>" +
        '<p class="of-price">' + (devis ? "<b>Sur devis</b>" : "<b>" + montant(p.base_price, p.currency) + "</b> <small>/ mois</small>") + "</p>" +
        (annuelPossible(p) ? '<span class="of-eq">ou ' + montant(p.yearly_price, p.currency) + " par an — 2 mois offerts</span>" : '<span class="of-eq">Tarif adapté à votre réseau</span>') +
        "</article>";
    }).join("") + "</div>";
  }

  window.KlassioOffres = { render: render, whatsapp: wa, cartesLecture: cartesLecture, montant: montant };
})();
