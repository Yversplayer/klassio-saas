// KLASSIO — Gestion du consentement aux témoins (Cookies & vie privée).
// Respect strict de la vie privée : aucun traqueur intrusif, seules les
// sessions indispensables au logiciel sont utilisées.
(function () {
  "use strict";

  var STORAGE_KEY = "klassio_cookie_consent";
  if (localStorage.getItem(STORAGE_KEY)) return;

  function initBanner() {
    var banner = document.createElement("aside");
    banner.id = "cookieConsentBanner";
    banner.className = "cookie-banner";
    banner.setAttribute("aria-label", "Gestion de la confidentialité");

    banner.innerHTML =
      '<div class="cookie-content">' +
        '<div class="cookie-text">' +
          '<strong>Confidentialité & Témoins de connexion</strong>' +
          '<p>Klassio utilise exclusivement des cookies essentiels pour sécuriser votre authentification, mémoriser vos préférences et garantir le bon fonctionnement du service. Pour en savoir plus, consultez notre <a href="confidentialite.html">politique de confidentialité</a>.</p>' +
        '</div>' +
        '<div class="cookie-actions">' +
          '<button type="button" class="btn btn-ghost btn-xs" id="cookieEssentialBtn">Essentiels uniquement</button>' +
          '<button type="button" class="btn btn-primary btn-xs" id="cookieAcceptBtn">Accepter</button>' +
        '</div>' +
      '</div>';

    document.body.appendChild(banner);

    function closeBanner(choice) {
      try { localStorage.setItem(STORAGE_KEY, choice); } catch (e) {}
      banner.classList.add("cookie-banner-hide");
      setTimeout(function () { banner.remove(); }, 350);
    }

    var btnAccept = document.getElementById("cookieAcceptBtn");
    var btnEss = document.getElementById("cookieEssentialBtn");
    if (btnAccept) btnAccept.addEventListener("click", function () { closeBanner("accepted"); });
    if (btnEss) btnEss.addEventListener("click", function () { closeBanner("essential"); });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initBanner);
  } else {
    initBanner();
  }
})();
