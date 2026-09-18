// KLASSIO — Notifications : liste complète, lu/non lu, lien vers l'objet.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var KIND_ICON = { attendance: "calendar", discipline: "discipline", grade: "book", payment: "payments", order: "store" };

  admin.initShell("notifications").then(function () {
    document.getElementById("pageActions").innerHTML = '<button type="button" class="btn btn-ghost btn-sm" id="readAll">' + UI.icon("check", 15) + "Tout marquer comme lu</button>";
    document.getElementById("readAll").addEventListener("click", function () { api.fetch("/notifications/read-all", { method: "POST" }).then(function () { load(); if (admin.refreshNotifications) admin.refreshNotifications(); }); });
    load();
  });

  function load() {
    var host = document.getElementById("notifPageList");
    host.innerHTML = UI.skeleton("row", 5);
    api.fetch("/notifications").then(function (res) {
      if (!res.ok) return admin.loadError(host, load, "Impossible de charger les notifications");
      var rows = res.body;
      if (!rows.length) { host.innerHTML = UI.emptyState("Aucune notification", "Présences, incidents, notes, paiements, commandes : tout ce qui vous concerne arrivera ici.", "", "bell"); return; }
      host.innerHTML = rows.map(function (n) {
        return '<a class="notif-item' + (n.status === "unread" ? " unread" : "") + '" href="' + UI.escapeHtml(n.link || "#") + '" data-id="' + n.id + '"><span class="notif-dot"></span><span class="kpi-ic" style="position:static;width:34px;height:34px;flex-shrink:0">' + UI.icon(KIND_ICON[n.kind] || "info", 16) + '</span><span class="notif-body"><strong>' + UI.escapeHtml(n.title) + "</strong><span>" + UI.escapeHtml(n.body) + "</span><em>" + UI.relTime(n.updated_at || n.created_at) + (n.count > 1 ? " · regroupée ×" + n.count : "") + (n.priority === "HIGH" ? " · prioritaire" : "") + "</em></span></a>";
      }).join("");
      host.querySelectorAll(".notif-item").forEach(function (el) {
        el.addEventListener("click", function (e) { if (el.getAttribute("href") === "#") e.preventDefault(); api.fetch("/notifications/" + el.dataset.id + "/read", { method: "POST" }).then(function () { el.classList.remove("unread"); if (admin.refreshNotifications) admin.refreshNotifications(); }); });
      });
    }).catch(function () { admin.loadError(host, load, "Le serveur Klassio est injoignable"); });
  }
})();
