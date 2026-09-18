// KLASSIO — socle des pages publiques : navigation, pied de page, thème.
//
// Écrit UNE fois et injecté dans chaque page publique. Sans cela, huit pages
// porteraient huit copies du même en-tête, et la neuvième aurait un lien mort
// que personne ne verrait avant un client.
//
// `index.html` est FIGÉE (voir LANDING_FIGEE.md) : elle garde sa propre barre,
// on s'est contenté d'y AJOUTER les liens vers ces pages. Ce fichier ne
// s'exécute donc pas sur la landing.
(function () {
  "use strict";

  var PAGES = [
    { href: "a-propos.html", label: "À propos" },
    { href: "aide.html", label: "Centre d'aide" },
    { href: "faq.html", label: "FAQ" },
    { href: "contact.html", label: "Contact" },
  ];

  var courante = (window.location.pathname.split("/").pop() || "index.html");

  function nav() {
    return '<nav class="navbar pub-nav" id="navbar">' +
      '<a href="index.html" class="brand"><img src="assets/logo.png" class="brand-mark" alt="Klassio">Klassio</a>' +
      '<div class="nav-links">' +
        '<a href="index.html#produit">Produit</a>' +
        PAGES.map(function (p) {
          return '<a href="' + p.href + '"' + (p.href === courante ? ' aria-current="page" class="actif"' : "") + ">" + p.label + "</a>";
        }).join("") +
      "</div>" +
      '<div class="nav-actions">' +
        '<a href="app/connexion.html" class="btn btn-ghost btn-sm">Connexion</a>' +
        '<a href="app/inscription.html" class="btn btn-primary btn-sm"><span class="btn-label">Créer mon espace</span></a>' +
      "</div>" +
      '<button type="button" class="pub-burger" id="pubBurger" aria-label="Ouvrir le menu" aria-expanded="false">' +
        '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg>' +
      "</button></nav>";
  }

  // Le pied de page ne liste QUE des pages qui existent. Un lien « Guides » vers
  // le vide vaut moins que pas de lien du tout : il fait douter du reste.
  function footer() {
    var cols = [
      ["Klassio", [["a-propos.html", "À propos"], ["index.html#produit", "Produit"], ["demo.html", "Démonstration"], ["contact.html", "Contact"]]],
      ["Pour qui", [["a-propos.html#roles", "Direction"], ["a-propos.html#roles", "Professeurs"], ["a-propos.html#roles", "Parents"], ["a-propos.html#roles", "Directeur des disciplines"]]],
      ["Ressources", [["aide.html", "Centre d'aide"], ["faq.html", "FAQ"], ["securite.html", "Sécurité"], ["app/inscription.html", "Créer un espace"]]],
      ["Légal", [["confidentialite.html", "Confidentialité"], ["cgu.html", "Conditions générales"], ["mentions.html", "Mentions légales"], ["confidentialite.html#suppression", "Suppression du compte"]]],
    ];
    return "<footer><div class=\"container\"><div class=\"footer-top\">" +
      '<div><a href="index.html" class="brand"><img src="assets/logo.png" class="brand-mark" alt="Klassio">Klassio</a>' +
      '<p class="footer-tag">La clarté derrière chaque établissement. Klassio réunit élèves, résultats, présence, discipline et finances autour d\'un dossier unique par élève.</p></div>' +
      '<div class="footer-cols">' + cols.map(function (c) {
        return '<div class="footer-col"><h5>' + c[0] + "</h5>" +
          c[1].map(function (l) { return '<a href="' + l[0] + '">' + l[1] + "</a>"; }).join("") + "</div>";
      }).join("") + "</div></div>" +
      '<div class="footer-bottom"><span>© 2026 Klassio. Tous droits réservés.</span><span>Kinshasa, République démocratique du Congo</span></div>' +
      "</div></footer>";
  }

  document.addEventListener("DOMContentLoaded", function () {
    var hoteNav = document.getElementById("pubNav");
    if (hoteNav) hoteNav.outerHTML = nav();
    var hotePied = document.getElementById("pubFooter");
    if (hotePied) hotePied.outerHTML = footer();

    var burger = document.getElementById("pubBurger");
    if (burger) {
      burger.addEventListener("click", function () {
        var ouvert = document.body.classList.toggle("pub-menu-ouvert");
        burger.setAttribute("aria-expanded", ouvert ? "true" : "false");
      });
    }
    // La barre se densifie au défilement — même geste que la landing, pour que
    // le passage de l'une à l'autre ne donne pas l'impression de changer de site.
    var barre = document.getElementById("navbar");
    if (barre) {
      var majBarre = function () { barre.classList.toggle("scrolled", window.scrollY > 10); };
      majBarre();
      window.addEventListener("scroll", majBarre, { passive: true });
    }
  });
})();
