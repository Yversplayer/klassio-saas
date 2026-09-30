// KLASSIO — le formulaire de contact de la landing.
//
// Repris de contact.html (fusionnée dans la landing le 30/09), avec deux
// corrections :
//
//   1. L'ADRESSE DE L'API n'est plus écrite en dur. L'ancienne page visait
//      « http://localhost:5001/api » : depuis un autre appareil — le téléphone
//      d'un directeur sur le Wi-Fi de l'école, ou la production — le message
//      partait vers le localhost DU VISITEUR et échouait. On résout l'origine
//      comme ui.js le fait pour toute l'application : même machine en
//      développement, même origine partout ailleurs.
//   2. PLUS DE SCRIPT EN LIGNE. La landing porte `script-src 'self'` sans
//      'unsafe-inline' : un <script> inline y serait bloqué, et le formulaire
//      se soumettrait nativement — nom, e-mail et message dans l'URL.
//
// Ce qui ne change pas : le formulaire n'annonce JAMAIS un envoi avant la
// réponse du serveur, et n'invente pas d'échec quand le réseau coupe — un
// message parti dont la réponse s'est perdue ne doit pas pousser à le renvoyer
// trois fois. La validation ici est un confort ; c'est le backend qui tranche.
(function () {
  "use strict";

  var form = document.getElementById("contactForm");
  if (!form) return;
  var err = document.getElementById("cErr");
  var btn = document.getElementById("cGo");

  // Même règle qu'UI.apiOrigin() (ui.js), que la landing ne charge pas.
  function origineApi() {
    var h = window.location.hostname;
    if (h === "localhost" || h === "127.0.0.1" || h === "" || h === "::1") return "http://localhost:5001";
    if (window.location.port === "4173") return window.location.protocol + "//" + h + ":5001";
    return "";
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    err.hidden = true;
    var corps = {
      name: document.getElementById("cNom").value.trim(),
      email: document.getElementById("cEmail").value.trim(),
      subject: document.getElementById("cSujet").value.trim(),
      message: document.getElementById("cMsg").value.trim(),
      kind: document.getElementById("cType").value,
      school: document.getElementById("cEcole").value.trim() || undefined
    };
    if (corps.message.length < 10) {
      err.textContent = "Votre message est trop court pour qu'on puisse y répondre utilement.";
      err.hidden = false;
      return;
    }
    btn.disabled = true;
    var libelle = btn.textContent;
    btn.textContent = "Envoi…";
    fetch(origineApi() + "/api/public/contact", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(corps)
    }).then(function (r) {
      return r.json().then(function (b) { return { ok: r.ok, body: b }; });
    }).then(function (res) {
      btn.disabled = false;
      btn.textContent = libelle;
      if (!res.ok) {
        err.textContent = (res.body && res.body.error) || "Votre message n'a pas pu être envoyé.";
        err.hidden = false;
        return;
      }
      document.getElementById("cOkTexte").textContent = res.body.message;
      form.hidden = true;
      document.getElementById("cOk").hidden = false;
    }).catch(function () {
      btn.disabled = false;
      btn.textContent = libelle;
      err.textContent = "La connexion a été interrompue. Votre message a peut-être été reçu — attendez un instant avant de le renvoyer.";
      err.hidden = false;
    });
  });
})();
