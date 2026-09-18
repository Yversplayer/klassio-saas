// KLASSIO — thème clair/sombre. Chargé tôt (avant le <body>) pour appliquer
// le thème choisi avant le premier rendu, sans clignotement.
//
// Trois choix depuis le 17/09 : Clair, Sombre, Système. L'option « Système »
// avait d'abord été écartée (deux boutons seulement) ; le propriétaire du
// produit l'a demandée en la déplaçant dans Paramètres → Apparence.
//
// « system » est stocké TEL QUEL, et résolu à chaque lecture : un utilisateur
// qui choisit Système doit suivre son appareil, y compris quand celui-ci
// bascule après coup. Mémoriser la couleur résolue figerait ce choix.
// Les valeurs "light"/"dark" déjà enregistrées restent valides.
(function () {
  "use strict";

  function systemPrefersDark() {
    return !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
  }

  // Le choix brut, tel que l'utilisateur l'a exprimé : "light", "dark",
  // "system", ou null s'il n'a jamais tranché.
  function getChoice() {
    try {
      var stored = localStorage.getItem("klassio_theme");
      if (stored === "light" || stored === "dark" || stored === "system") return stored;
    } catch (e) {}
    return null;
  }

  // La couleur effectivement appliquée.
  function getPref() {
    var choix = getChoice();
    if (choix === "light" || choix === "dark") return choix;
    return systemPrefersDark() ? "dark" : "light";
  }

  function setPref(theme) {
    try { localStorage.setItem("klassio_theme", theme); } catch (e) {}
    if (theme === "system") theme = systemPrefersDark() ? "dark" : "light";
    var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!reduced && document.startViewTransition) {
      var vt = document.startViewTransition(function () {
        applyTheme(theme);
        syncToggleUI();
      });
      // `ready` et `finished` REJETTENT quand la transition est interrompue —
      // deux bascules rapprochées, onglet masqué, document dans un état qui ne
      // s'y prête pas. Personne ne les attend, donc sans ces catch chaque
      // changement de thème laissait une promesse rejetée non gérée dans la
      // console (« Transition was aborted because of invalid state »).
      // Le thème, lui, est appliqué dans tous les cas : le callback a déjà
      // tourné. Il n'y a rien à rattraper, seulement à ne pas crier.
      if (vt) {
        if (vt.ready && vt.ready.catch) vt.ready.catch(function () {});
        if (vt.finished && vt.finished.catch) vt.finished.catch(function () {});
      }
    } else {
      applyTheme(theme);
      syncToggleUI();
    }
  }

  applyTheme(getPref());

  function syncToggleUI() {
    var toggle = document.getElementById("themeToggle");
    if (!toggle) return;
    if (!toggle.querySelector(".theme-toggle-glider")) {
      var glider = document.createElement("span");
      glider.className = "theme-toggle-glider";
      glider.setAttribute("aria-hidden", "true");
      toggle.insertBefore(glider, toggle.firstChild);
    }
    var current = document.documentElement.getAttribute("data-theme");
    toggle.querySelectorAll("button").forEach(function (btn) {
      btn.classList.toggle("active", btn.dataset.themeChoice === current);
    });
  }

  function wireToggle() {
    var toggle = document.getElementById("themeToggle");
    if (!toggle) return;
    syncToggleUI();
    toggle.querySelectorAll("button").forEach(function (btn) {
      btn.addEventListener("click", function () { setPref(btn.dataset.themeChoice); });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wireToggle);
  } else {
    wireToggle();
  }

  // Quand le choix est « Système », l'appareil peut changer d'avis en cours de
  // route : on suit. Aucun effet si l'utilisateur a tranché lui-même.
  if (window.matchMedia) {
    var mq = window.matchMedia("(prefers-color-scheme: dark)");
    var suivre = function () { if (getChoice() === "system") { applyTheme(getPref()); syncToggleUI(); } };
    if (mq.addEventListener) mq.addEventListener("change", suivre);
    else if (mq.addListener) mq.addListener(suivre);
  }

  window.KlassioTheme = { get: getPref, set: setPref, getChoice: getChoice };
})();
