// KLASSIO — loader 3D plein écran (création d'espace, import, opérations
// lourdes). Recréation vanilla de l'effet "boîtes qui s'assemblent en cube",
// recoloré lime/charbon. Montré UNIQUEMENT pendant une vraie requête ; les
// étapes listées sous le cube reflètent l'état réel (done / doing / todo)
// transmis par la page — jamais des coches fictives sur un minuteur.
(function () {
  "use strict";
  var overlay = null;

  function ensureOverlay() {
    if (overlay) return overlay;
    overlay = document.createElement("div");
    overlay.className = "klassio-loader-overlay";
    overlay.setAttribute("role", "status"); overlay.setAttribute("aria-live", "polite");
    overlay.innerHTML =
      '<div class="klassio-loader">' +
        '<div class="loader">' + [0, 1, 2, 3, 4, 5, 6, 7].map(function (i) { return '<div class="box box' + i + '"><div></div></div>'; }).join("") + '<div class="ground"><div></div></div></div>' +
        '<p class="klassio-loader-text"></p>' +
        '<ol class="klassio-loader-steps"></ol>' +
      "</div>";
    document.body.appendChild(overlay);
    return overlay;
  }

  function setSteps(steps) {
    var el = ensureOverlay().querySelector(".klassio-loader-steps");
    el.innerHTML = (steps || []).map(function (s) {
      var mark = s.state === "done" ? '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5L20 7"/></svg>'
               : s.state === "doing" ? '<span class="ls-spin"></span>' : '<span class="ls-dot"></span>';
      return '<li class="ls ' + (s.state || "todo") + '"><span class="ls-mark">' + mark + "</span><span>" + String(s.label).replace(/[&<>]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]; }) + "</span></li>";
    }).join("");
  }

  // L'affichage est différé d'une frame pour que la transition CSS parte d'un
  // état peint. Il faut donc pouvoir ANNULER cette frame : sans cela, une
  // requête qui répond plus vite qu'une frame — cas courant en local, ou sur
  // un petit fichier — produisait la séquence
  //
  //     show()  → planifie l'ajout de « shown »
  //     hide()  → retire une classe pas encore posée : sans effet
  //     frame   → pose « shown »
  //
  // et le voile plein écran restait affiché pour toujours, avalant tous les
  // clics de la page. Trouvé sur l'import des résultats ; l'import des élèves
  // y échappait par accident, un setTimeout précédant son hide().
  var frameEnAttente = null;

  function show(text, steps) {
    var el = ensureOverlay();
    el.querySelector(".klassio-loader-text").textContent = text || "Traitement en cours…";
    setSteps(steps || []);
    if (frameEnAttente !== null) cancelAnimationFrame(frameEnAttente);
    frameEnAttente = requestAnimationFrame(function () {
      frameEnAttente = null;
      el.classList.add("shown");
    });
  }

  function hide() {
    if (frameEnAttente !== null) { cancelAnimationFrame(frameEnAttente); frameEnAttente = null; }
    if (overlay) overlay.classList.remove("shown");
  }

  window.KlassioLoader = { show: show, hide: hide, setSteps: setSteps };
})();
