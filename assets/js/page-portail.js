// KLASSIO — portail d'un établissement : page d'atterrissage aux couleurs de
// l'école (?e=adresse), connexion par email ou téléphone, réinitialisation de
// mot de passe via lien émis par la Direction (?reset=jeton). Le logiciel
// s'efface derrière l'établissement — Klassio n'apparaît qu'en pied de page.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi;
  var slug = UI.qs("e"), resetToken = UI.qs("reset");
  var branding = null;

  function applyBranding(b) {
    branding = b;
    document.title = b.name + " — Portail";
    document.getElementById("pName").textContent = b.name;
    document.getElementById("pTagline").textContent = b.tagline || "Espace parents, enseignants et direction";
    var logo = document.getElementById("pLogo");
    if (b.logo_data) { logo.innerHTML = '<img src="' + UI.escapeHtml(b.logo_data) + '" alt="">'; } else { logo.innerHTML = '<span>' + UI.escapeHtml((b.name || "?").split(/\s+/).map(function (w) { return w[0]; }).join("").slice(0, 3).toUpperCase()) + "</span>"; }
    if (b.cover_data) document.getElementById("pCover").style.backgroundImage = "url(" + b.cover_data + ")";
    if (b.accent_color) document.documentElement.style.setProperty("--accent", b.accent_color);
    document.getElementById("pFlag").hidden = !b.show_flag;
    try { localStorage.setItem("klassio_portal", b.slug); } catch (e) {}
  }

  function show(id) { ["stLoading", "stNotFound", "stLogin", "stReset", "stForgot"].forEach(function (s) { document.getElementById(s).hidden = s !== id; }); }

  function boot() {
    if (resetToken) {
      api.fetch("/password-reset/lookup?token=" + encodeURIComponent(resetToken)).then(function (res) {
        if (!res.ok) { show("stNotFound"); document.getElementById("nfText").textContent = res.body.error || "Lien invalide."; return; }
        applyBranding(res.body.branding);
        document.getElementById("resetWho").textContent = "Bonjour " + res.body.name + " — choisissez votre nouveau mot de passe pour " + res.body.tenant_name + ".";
        show("stReset");
      });
      return;
    }
    if (!slug) { try { slug = localStorage.getItem("klassio_portal"); } catch (e) {} }
    if (!slug) { show("stNotFound"); document.getElementById("nfText").textContent = "Aucune adresse d'établissement dans ce lien. Utilisez le lien envoyé par votre école, ou la connexion générale."; return; }
    api.fetch("/portal/" + encodeURIComponent(slug)).then(function (res) {
      if (!res.ok) { show("stNotFound"); document.getElementById("nfText").textContent = res.body.error || "Établissement introuvable."; return; }
      applyBranding(res.body);
      show("stLogin");
      if (api.getToken()) document.getElementById("alreadyIn").hidden = false;
    }).catch(function () { show("stNotFound"); document.getElementById("nfText").textContent = "Le serveur Klassio est momentanément injoignable."; });
  }

  // ---- Connexion ----
  document.getElementById("loginForm").addEventListener("submit", function (e) {
    e.preventDefault();
    var btn = document.getElementById("loginBtn"), err = document.getElementById("loginError");
    err.hidden = true;
    var identifier = document.getElementById("loginId").value.trim(), password = document.getElementById("loginPw").value;
    if (!identifier || !password) { err.textContent = "Indiquez votre email ou votre numéro, et votre mot de passe."; err.hidden = false; return; }
    UI.btnState(btn, "loading", "Connexion…");
    api.fetch("/auth/login", { method: "POST", body: JSON.stringify({ identifier: identifier, password: password }) }).then(function (res) {
      if (!res.ok) { UI.btnState(btn, "idle"); err.textContent = res.body.error || "Connexion impossible."; err.hidden = false; return; }
      api.storeSession(res.body);
      UI.btnState(btn, "success", "Connecté");
      window.location.href = UI.homeFor(res.body.role);
    }).catch(function () { UI.btnState(btn, "idle"); err.textContent = "Le serveur Klassio est momentanément injoignable."; err.hidden = false; });
  });

  // ---- Mot de passe oublié : pas de canal email → la Direction envoie un lien ----
  document.getElementById("forgotLink").addEventListener("click", function (e) { e.preventDefault(); show("stForgot"); });
  document.getElementById("forgotBack").addEventListener("click", function (e) { e.preventDefault(); show("stLogin"); });

  // ---- Réinitialisation ----
  api.wirePasswordRules(document.getElementById("resetPw"), document.getElementById("pwRules"));
  document.getElementById("resetForm").addEventListener("submit", function (e) {
    e.preventDefault();
    var btn = document.getElementById("resetBtn"), err = document.getElementById("resetError");
    err.hidden = true;
    var pw = document.getElementById("resetPw").value;
    if (!api.passwordMeetsRules(pw)) { err.textContent = "Le mot de passe ne respecte pas encore toutes les règles."; err.hidden = false; return; }
    UI.btnState(btn, "loading", "Enregistrement…");
    api.fetch("/password-reset", { method: "POST", body: JSON.stringify({ token: resetToken, password: pw }) }).then(function (res) {
      if (!res.ok) { UI.btnState(btn, "idle"); err.textContent = res.body.error || "Impossible de réinitialiser."; err.hidden = false; return; }
      api.storeSession(res.body);
      UI.btnState(btn, "success", "Mot de passe enregistré");
      UI.toast("Mot de passe mis à jour — vous êtes connecté(e).", "success");
      setTimeout(function () { window.location.href = UI.homeFor(res.body.role); }, 700);
    });
  });

  boot();
})();
