// KLASSIO — briques des tableaux de bord « en gros » (accueil Direction,
// Finance), 08/10/2026. Du HTML, rien d'autre : le mouvement vit dans
// tableau.css, sous .ka-anim, et l'inclinaison dans app-visuel.js.
(function () {
  "use strict";
  var OBJETS = "../assets/objets/";

  // Un objet 3D décoratif (Higgsfield, fond détouré). `alt` vide et
  // aria-hidden : il n'apprend rien à personne, il habille.
  function objet(nom, classe, taille) {
    return '<img class="kt-objet' + (classe ? " " + classe : "") + '" src="' + OBJETS + nom + "-" + (taille || 480) + '.webp" alt="" aria-hidden="true" loading="lazy" decoding="async">';
  }

  // Donut en SVG : chaque segment est un arc décalé du précédent. Le total
  // vient du serveur ; un total nul dessine l'anneau vide, jamais un faux arc.
  function donut(segments, total, legende, valeur) {
    var r = 60, C = 2 * Math.PI * r, debut = 0;
    var arcs = total > 0 ? segments.filter(function (s) { return s.value > 0; }).map(function (s) {
      var l = (s.value / total) * C;
      var arc = '<circle class="arc" cx="80" cy="80" r="' + r + '" style="stroke:' + s.color + ";stroke-dasharray:" + l.toFixed(2) + " " + (C - l).toFixed(2) + ";stroke-dashoffset:" + (-debut).toFixed(2) + '"/>';
      debut += l;
      return arc;
    }).join("") : "";
    return '<div class="kt-donut"><svg viewBox="0 0 160 160" aria-hidden="true"><circle class="fond" cx="80" cy="80" r="' + r + '"/>' + arcs + "</svg>" +
      '<div class="kt-donut-centre"><small>' + legende + "</small><strong>" + valeur + "</strong></div></div>";
  }

  // Histogramme vertical : la plus haute colonne en lime.
  function histo(lignes, vide) {
    if (!lignes.length || !lignes.some(function (l) { return l.value > 0; })) return '<p class="kt-vide">' + vide + "</p>";
    var max = Math.max.apply(null, lignes.map(function (l) { return l.value; }));
    return '<div class="kt-histo">' + lignes.map(function (l, i) {
      var h = max > 0 ? Math.max(3, Math.round((l.value / max) * 100)) : 3;
      return '<div class="kt-histo-col' + (l.value === max && max > 0 ? " max" : "") + '"><span class="kt-histo-val">' + l.display + '</span><span class="kt-histo-barre" style="height:' + h + "%;animation-delay:" + (i * 0.06).toFixed(2) + 's"></span><span class="kt-histo-mois">' + l.label + "</span></div>";
    }).join("") + "</div>";
  }

  window.KlassioTableau = { objet: objet, donut: donut, histo: histo };
})();
