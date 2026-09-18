// KLASSIO — page d'inscription : un directeur déjà connecté qui revient
// pour importer (#import) saute directement à l'étape 2, sans recréer un
// établissement.
(function () {
  "use strict";
  if (location.hash !== "#import") return;
  var token = null;
  try { token = localStorage.getItem("klassio_token"); } catch (e) {}
  if (!token) return;
  window.KlassioApi.fetch("/me").then(function (res) {
    if (!res.ok || res.body.role !== "directeur") return;
    document.getElementById("step-account").hidden = true;
    document.getElementById("step-import").hidden = false;
    document.querySelectorAll("#stepDots span").forEach(function (d) { d.classList.toggle("active", d.dataset.step === "2"); });
    document.querySelector("#step-import .auth-kicker").textContent = "Import";
    document.querySelector("#step-import h1").textContent = "Importer un fichier dans " + (res.body.tenant_name || "votre établissement");
    document.getElementById("skipImportBtn").textContent = "Retour à mon espace";
    document.getElementById("skipImportBtn").addEventListener("click", function (e) { e.stopImmediatePropagation(); window.location.href = "dashboard.html"; }, true);
    try { localStorage.setItem("klassio_etablissement", res.body.tenant_name || ""); } catch (e) {}
  });
})();
