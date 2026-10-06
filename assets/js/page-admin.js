// KLASSIO — connexion à l'administration de la plateforme (app/admin.html).
//
// Mot de passe + code à 6 chiffres (TOTP). La session vit dans un cookie
// HttpOnly que ce script ne voit pas ; il ne stocke rien. Le serveur répond
// un message unique quel que soit le facteur faux — l'écran n'en dit pas plus.
(function () {
  "use strict";
  var UI = window.KlassioUI;
  var BASE = (UI ? UI.apiOrigin() : "") + "/api/admin";
  var form = document.getElementById("adminForm");
  var err = document.getElementById("admError");
  var btn = document.getElementById("admBtn");
  var code = document.getElementById("admCode");

  function montrer(message) { err.textContent = message; err.hidden = !message; }

  if (UI && UI.qs("expired")) montrer("Session fermée (inactivité ou déconnexion). Reconnectez-vous.");

  // Déjà connecté : droit à l'administration.
  fetch(BASE + "/session", { credentials: "same-origin" }).then(function (r) {
    if (r.ok) window.location.replace("plateforme.html");
  }).catch(function () {});

  // Le code ne contient que des chiffres : on retire le reste à la frappe.
  code.addEventListener("input", function () { code.value = code.value.replace(/\D/g, "").slice(0, 6); });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    montrer("");
    var email = document.getElementById("admEmail").value.trim();
    var motDePasse = document.getElementById("admPassword").value;
    if (!email || !motDePasse || code.value.length !== 6) {
      montrer("Renseignez l'e-mail, le mot de passe et le code à 6 chiffres.");
      return;
    }
    if (UI) UI.btnState(btn, "loading", "Vérification…");
    fetch(BASE + "/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: email, password: motDePasse, code: code.value })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (corps) { return { ok: r.ok, corps: corps }; });
    }).then(function (res) {
      if (res.ok) { window.location.replace("plateforme.html"); return; }
      if (UI) UI.btnState(btn, "idle");
      // Un code ne sert qu'une fois : après un refus, il faut le suivant.
      code.value = "";
      montrer(res.corps.error || "Connexion impossible.");
    }).catch(function () {
      if (UI) UI.btnState(btn, "idle");
      montrer("Le serveur Klassio est injoignable. Réessayez dans un instant.");
    });
  });
})();
