// KLASSIO — le moteur de mouvement sur les pages publiques secondaires.
//
// Les pages de la navigation (À propos, Centre d'aide, FAQ, Contact,
// Sécurité, pages légales) n'avaient aucun mouvement : on passait d'une
// landing vivante à des documents figés, et la rupture se sentait.
//
// Elles n'ont PAS besoin du même traitement que la landing. Un centre d'aide
// se lit, il ne se contemple pas : on y met la révélation du titre, le
// curseur et la typographie cinétique, et on s'arrête là. Échelonner douze
// titres de CGU ferait une page qui clignote à chaque molette.
(function () {
  "use strict";
  function demarrer() {
    var M = window.KlassioMotion;
    if (!M) return;
    M.observer(document);
    M.typographieCinetique();
    M.curseur();
    M.aimants(document);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", demarrer);
  } else {
    demarrer();
  }
})();
