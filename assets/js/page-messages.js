// KLASSIO — Cahier de communication : fils par élève. Le périmètre vient du
// backend (parent : ses enfants ; titulaire : sa classe ; DD : son cycle ;
// Direction : tout). Chaque message notifie l'autre partie.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var ctx = null, threads = [], current = UI.qs("student"), timer = null;

  admin.initShell("messages").then(function (c) { ctx = c; load(); });

  function load() {
    var host = document.getElementById("msgContent");
    host.innerHTML = UI.skeleton("row", 5);
    api.fetch("/messages/threads").then(function (res) {
      if (!res.ok) return admin.loadError(host, load, "Impossible de charger les messages");
      threads = res.body;
      render();
      if (current) openThread(current); else if (threads.length && window.innerWidth > 860) openThread(threads[0].id);
    }).catch(function () { admin.loadError(host, load, "Le serveur Klassio est injoignable"); });
  }

  function render() {
    var host = document.getElementById("msgContent");
    if (!threads.length) { host.innerHTML = UI.emptyState("Aucun fil de discussion", ctx.role === "parent" ? "Aucun enfant rattaché à votre compte." : "Aucun élève dans votre périmètre.", "", "mail"); return; }
    host.innerHTML = '<div class="msg-layout"><div><div class="toolbar" style="margin-bottom:8px"><label class="search" for="thSearch">' + UI.icon("search", 15) + '<input id="thSearch" type="search" placeholder="Rechercher un élève…" /></label></div><div class="msg-threads" id="threadList"></div></div>' +
      '<div class="msg-pane" id="msgPane">' + UI.emptyState("Choisissez un élève", "Le fil de discussion s'ouvre ici.", "", "mail") + "</div></div>";
    renderThreads("");
    document.getElementById("thSearch").addEventListener("input", UI.debounce(function () { renderThreads(this.value.trim().toLowerCase()); }, 120));
  }
  function renderThreads(q) {
    var list = threads.filter(function (t) { return !q || (t.first_name + " " + t.last_name + " " + (t.code || "") + " " + (t.class_name || "")).toLowerCase().indexOf(q) !== -1; });
    document.getElementById("threadList").innerHTML = list.map(function (t) {
      return '<div class="msg-thread' + (t.id === current ? " active" : "") + '" data-id="' + t.id + '">' + UI.avatar(t, 36) + '<div class="mt-body"><strong>' + UI.escapeHtml(t.first_name + " " + t.last_name) + "</strong><span>" + UI.escapeHtml(t.last_body || (t.class_name || "") + " · aucun message") + "</span></div>" + (t.unread ? '<span class="mt-unread">' + t.unread + "</span>" : "") + "</div>";
    }).join("") || '<p class="muted">Aucun élève ne correspond.</p>';
    document.querySelectorAll(".msg-thread").forEach(function (el) { el.addEventListener("click", function () { openThread(el.dataset.id); }); });
  }

  function openThread(studentId) {
    current = studentId;
    history.replaceState(null, "", "messages.html?student=" + studentId);
    document.querySelectorAll(".msg-thread").forEach(function (el) { el.classList.toggle("active", el.dataset.id === studentId); });
    var pane = document.getElementById("msgPane");
    pane.innerHTML = UI.skeleton("row", 3);
    api.fetch("/messages/" + studentId).then(function (res) {
      if (!res.ok) { pane.innerHTML = UI.emptyState("Fil introuvable", res.body.error || "", "", "lock"); return; }
      var s = res.body.student, msgs = res.body.messages;
      pane.innerHTML = '<div class="msg-pane-head">' + UI.avatar(s, 36) + '<div class="grow"><strong>' + UI.escapeHtml(s.first_name + " " + s.last_name) + '</strong><div class="muted">' + UI.escapeHtml(s.class_name || "") + ' · <span class="chip-code">' + UI.escapeHtml(s.code || "") + '</span></div></div><a class="btn btn-ghost btn-xs" href="eleve-dossier.html?id=' + s.id + '">Dossier</a></div>' +
        '<div class="msg-list" id="msgList">' + (msgs.length ? msgs.map(bubble).join("") : '<p class="muted" style="margin:auto;text-align:center">Aucun message pour le moment.<br>' + (ctx.role === "parent" ? "Écrivez au titulaire ou à l'école ci-dessous." : "Écrivez aux parents ci-dessous.") + "</p>") + "</div>" +
        '<form class="msg-compose" id="composeForm"><textarea id="composeBody" placeholder="Votre message…" maxlength="2000" required></textarea><button type="submit" class="btn btn-lime btn-sm" id="composeBtn">Envoyer</button></form>';
      var list = document.getElementById("msgList"); list.scrollTop = list.scrollHeight;
      document.getElementById("composeForm").addEventListener("submit", function (e) {
        e.preventDefault();
        var body = document.getElementById("composeBody").value.trim(); if (!body) return;
        var btn = document.getElementById("composeBtn"); UI.btnState(btn, "loading", "Envoi…");
        api.fetch("/messages/" + studentId, { method: "POST", body: JSON.stringify({ body: body }) }).then(function (r) {
          if (!r.ok) { UI.btnState(btn, "error"); return UI.toast(r.body.error || "Envoi impossible.", "error"); }
          UI.btnState(btn, "success", "Envoyé"); document.getElementById("composeBody").value = "";
          openThread(studentId);
          api.fetch("/messages/threads").then(function (t) { if (t.ok) { threads = t.body; renderThreads(""); document.querySelectorAll(".msg-thread").forEach(function (el) { el.classList.toggle("active", el.dataset.id === studentId); }); } });
        });
      });
      document.querySelectorAll(".msg-thread").forEach(function (el) { if (el.dataset.id === studentId) { var u = el.querySelector(".mt-unread"); if (u) u.remove(); } });
      if (admin.refreshNotifications) admin.refreshNotifications();
    });
  }
  function bubble(m) {
    var mine = m.sender_id === ctx.user_id;
    return '<div class="msg' + (mine ? " mine" : "") + '"><div class="bubble">' + UI.escapeHtml(m.body).replace(/\n/g, "<br>") + '</div><div class="meta">' + (mine ? "Vous" : UI.escapeHtml(m.sender_name) + " · " + UI.escapeHtml(UI.ROLE_LABELS[m.sender_role] || m.sender_role)) + " · " + UI.fmtDateTime(m.created_at) + "</div></div>";
  }
  // Rafraîchissement discret du fil ouvert (pas de WebSocket sur ce serveur)
  timer = setInterval(function () { if (current && !document.hidden) { api.fetch("/messages/threads").then(function (t) { if (t.ok) { threads = t.body; var q = (document.getElementById("thSearch") || {}).value || ""; if (document.getElementById("threadList")) renderThreads(q.trim().toLowerCase()); } }); } }, 30000);
})();
