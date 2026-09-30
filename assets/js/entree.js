// KLASSIO — décide, AVANT le premier rendu, si l'accueil animé doit jouer.
//
// Chargé dans <head> de la landing, en tout premier : c'est la seule façon
// que le splash ne s'affiche pas une seule frame quand il ne doit pas jouer.
// main.js, en fin de page, arriverait trop tard pour l'empêcher de clignoter.
//
// Deux cas le sautent :
//   - on arrive par une ancre (index.html#produit, #faq…) : on vient chercher
//     une section précise, pas l'accueil ;
//   - on l'a déjà vu dans cette session : le rejouer à chaque retour depuis la
//     démo ou le centre d'aide était la plainte exacte du propriétaire.
(function () {
  "use strict";
  var sauter = !!window.location.hash;
  try {
    if (window.sessionStorage.getItem("kx-accueil-vu") === "1") sauter = true;
    window.sessionStorage.setItem("kx-accueil-vu", "1");
  } catch (e) { /* stockage bloqué (navigation privée) : on joue l'accueil, c'est sans risque */ }
  if (sauter) document.documentElement.classList.add("kx-nosplash");

  // ARRIVER SUR UNE ANCRE, C'EST Y ÊTRE — PAS Y DESCENDRE.
  // style.css pose `scroll-behavior: smooth` sur <html>, ce qui vaut aussi
  // pour l'ancre du chargement : venir de faq.html (qui redirige vers #faq)
  // faisait défiler 22 000 px à travers toutes les scènes animées — et dans
  // un navigateur qui ralentit ses images, la page restait bloquée en haut
  // (constaté). On saute donc net, puis on rend le défilement doux aux clics
  // de la barre une fois la page chargée et posée.
  if (window.location.hash) {
    var racine = document.documentElement;
    racine.classList.add("kx-ancre");
    window.addEventListener("load", function () {
      window.setTimeout(function () { racine.classList.remove("kx-ancre"); }, 800);
    });
  }
})();
