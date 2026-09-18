// KLASSIO — Calendrier : vue mensuelle + liste, alimentée par GET /api/calendar
// (événements ciblés, examens, devoirs, échéances, présences, convocations).
// Direction et DD publient événements et communiqués ; les destinataires
// autorisés sont notifiés par le backend.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var ctx = null, month = (UI.qs("date") || UI.todayIso()).slice(0, 7), feed = null, classes = [];

  admin.initShell("calendrier").then(function (c) {
    ctx = c;
    if (c.role === "directeur" || c.role === "discipline") {
      document.getElementById("pageActions").innerHTML = '<button type="button" class="btn btn-ghost btn-sm" id="commBtn">' + UI.icon("mail", 15) + 'Communiqué</button><button type="button" class="btn btn-lime btn-sm" id="evtBtn">' + UI.icon("plus", 15) + "Événement</button>";
      document.getElementById("commBtn").addEventListener("click", function () { openEventModal("communique"); });
      document.getElementById("evtBtn").addEventListener("click", function () { openEventModal("evenement"); });
      api.fetch("/classes").then(function (r) { classes = r.ok ? r.body : []; });
    }
    load();
  });

  function load() {
    var host = document.getElementById("calContent");
    if (!feed) host.innerHTML = UI.skeleton("card", 2);
    api.fetch("/calendar?month=" + month).then(function (res) {
      if (!res.ok) return admin.loadError(host, load, "Impossible de charger le calendrier");
      feed = res.body;
      render();
    }).catch(function () { admin.loadError(host, load, "Le serveur Klassio est injoignable"); });
  }

  function render() {
    var host = document.getElementById("calContent");
    var y = parseInt(month.slice(0, 4), 10), m = parseInt(month.slice(5, 7), 10);
    var first = new Date(y, m - 1, 1), daysInMonth = new Date(y, m, 0).getDate();
    var startDow = (first.getDay() + 6) % 7; // lundi = 0
    var byDate = {};
    feed.items.forEach(function (i) {
      if (!i.date) return;
      var d = i.date, end = i.end || i.date;
      // Événement sur plusieurs jours : une entrée par jour du mois
      var cur = new Date(d + "T00:00:00"), stop = new Date(end + "T00:00:00");
      while (cur <= stop) {
        var key = cur.getFullYear() + "-" + String(cur.getMonth() + 1).padStart(2, "0") + "-" + String(cur.getDate()).padStart(2, "0");
        if (key.slice(0, 7) === month) (byDate[key] = byDate[key] || []).push(i);
        cur.setDate(cur.getDate() + 1);
      }
    });
    var todayIso = UI.todayIso();
    var ex = feed.exam_period || {};
    var title = first.toLocaleDateString("fr-FR", { month: "long", year: "numeric" });
    var cells = "";
    for (var i = 0; i < startDow; i++) cells += '<div class="cal-cell other"></div>';
    for (var d = 1; d <= daysInMonth; d++) {
      var key = month + "-" + String(d).padStart(2, "0");
      var items = byDate[key] || [];
      var inExam = ex.starts && ex.ends && key >= ex.starts && key <= ex.ends;
      cells += '<div class="cal-cell' + (key === todayIso ? " today" : "") + (inExam ? " exam-period" : "") + '" data-date="' + key + '"><span class="cd">' + d + "</span>" +
        items.slice(0, 3).map(function (it) { return '<span class="cal-pill ' + (UI.EVENT_KIND_TONES[it.kind] || "") + '" title="' + UI.escapeHtml(it.title) + '">' + UI.escapeHtml(it.title) + "</span>"; }).join("") +
        (items.length > 3 ? '<span class="cal-more">+' + (items.length - 3) + "</span>" : "") +
        '<span class="dots">' + items.slice(0, 5).map(function (it) { return '<span class="dot ' + (UI.EVENT_KIND_TONES[it.kind] || "") + '"></span>'; }).join("") + "</span></div>";
    }
    var list = feed.items.filter(function (i) { return i.date; });
    var upcoming = list.filter(function (i) { return i.date >= todayIso; });
    var listHtml = (upcoming.length ? upcoming : list).slice(0, 40).map(function (i) {
      return '<div class="tl-item"><span class="tl-dot ' + (UI.EVENT_KIND_TONES[i.kind] || "") + '"></span><div class="tl-body"><strong>' + UI.escapeHtml(i.title) + " " + UI.badge(UI.EVENT_KIND_TONES[i.kind] || "neutral", UI.EVENT_KIND_LABELS[i.kind] || i.kind) + "</strong>" +
        (i.body ? "<span>" + UI.escapeHtml(i.body) + "</span>" : "") + "<em>" + UI.fmtDate(i.date) + (i.end && i.end !== i.date ? " → " + UI.fmtDate(i.end) : "") + (i.time ? " · " + UI.escapeHtml(i.time) : "") + (i.link ? ' · <a class="link-btn" href="' + UI.escapeHtml(i.link) + '">Ouvrir</a>' : "") + "</em></div></div>";
    }).join("");
    host.innerHTML = '<div class="panel"><div class="cal-head"><button type="button" class="icon-btn" id="calPrev" aria-label="Mois précédent">' + UI.icon("chevronLeft", 16) + "</button><h2>" + UI.escapeHtml(title) + '</h2><button type="button" class="icon-btn" id="calNext" aria-label="Mois suivant">' + UI.icon("chevronRight", 16) + "</button></div>" +
      (inExamNow(ex, todayIso) ? '<p class="note-inline">' + UI.icon("alert", 15) + "<span>Période d'examens en cours (" + UI.fmtDate(ex.starts) + " → " + UI.fmtDate(ex.ends) + "). Les horaires d'examens de chaque classe sont dans l'onglet Horaire & examens des dossiers.</span></p>" : "") +
      '<div class="cal-grid">' + ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"].map(function (x) { return '<div class="cal-dow">' + x + "</div>"; }).join("") + cells + "</div>" +
      '<div class="legend" style="margin-top:12px"><span class="ok">Événement / présent</span><span class="warn">Réunion / échéance / retard</span><span class="bad">Examen / convocation / absent</span><span>Communiqué / deuil</span></div></div>' +
      '<div class="panel"><div class="panel-head"><h2>' + (upcoming.length ? "À venir" : "Ce mois") + '</h2><span class="sub">' + UI.plural(list.length, "élément") + "</span></div>" + (listHtml ? '<div class="timeline cal-list">' + listHtml + "</div>" : UI.emptyState("Rien de planifié ce mois-ci", "Les événements de l'école, examens et devoirs apparaîtront ici.", "", "calendar")) + "</div>" +
      (ctx.role === "directeur" || ctx.role === "discipline" ? '<div class="panel"><div class="panel-head"><h2>Publications</h2><span class="sub">Vos événements et communiqués</span></div><div id="myEvents">' + UI.skeleton("row", 2) + "</div></div>" : "");
    document.getElementById("calPrev").addEventListener("click", function () { shift(-1); });
    document.getElementById("calNext").addEventListener("click", function () { shift(1); });
    host.querySelectorAll(".cal-cell[data-date]").forEach(function (c) { c.addEventListener("click", function () { openDay(c.dataset.date, byDate[c.dataset.date] || []); }); });
    if (document.getElementById("myEvents")) loadMine();
  }
  function inExamNow(ex, today) { return ex.starts && ex.ends && today >= ex.starts && today <= ex.ends; }
  function shift(n) {
    var y = parseInt(month.slice(0, 4), 10), m = parseInt(month.slice(5, 7), 10) + n;
    if (m < 1) { m = 12; y--; } if (m > 12) { m = 1; y++; }
    month = y + "-" + String(m).padStart(2, "0"); load();
  }
  function openDay(date, items) {
    var body = items.length ? '<div class="timeline">' + items.map(function (i) { return '<div class="tl-item"><span class="tl-dot ' + (UI.EVENT_KIND_TONES[i.kind] || "") + '"></span><div class="tl-body"><strong>' + UI.escapeHtml(i.title) + "</strong>" + (i.body ? "<span>" + UI.escapeHtml(i.body) + "</span>" : "") + "<em>" + (UI.EVENT_KIND_LABELS[i.kind] || i.kind) + (i.time ? " · " + UI.escapeHtml(i.time) : "") + (i.link ? ' · <a class="link-btn" href="' + UI.escapeHtml(i.link) + '">Ouvrir</a>' : "") + "</em></div></div>"; }).join("") + "</div>" : '<p class="muted">Rien ce jour-là.</p>';
    var footer = (ctx.role === "directeur" || ctx.role === "discipline") ? '<button type="button" class="btn btn-lime btn-sm" id="dayAdd">' + UI.icon("plus", 14) + "Ajouter un événement</button>" : "";
    var m = UI.modal({ title: UI.fmtDate(date), body: body, footer: footer });
    var b = m.querySelector("#dayAdd"); if (b) b.addEventListener("click", function () { UI.closeModal(); openEventModal("evenement", date); });
  }

  function loadMine() {
    api.fetch("/calendar/events").then(function (res) {
      var host = document.getElementById("myEvents"); if (!host || !res.ok) return;
      var mine = res.body.filter(function (e) { return e.can_delete; });
      if (!mine.length) { host.innerHTML = '<p class="muted">Aucune publication pour le moment.</p>'; return; }
      host.innerHTML = '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Type</th><th>Titre</th><th>Date</th><th>Cible</th><th>Audience</th><th class="actions"></th></tr></thead><tbody>' + mine.slice(0, 40).map(function (e) {
        return '<tr><td data-label="Type">' + UI.badge(UI.EVENT_KIND_TONES[e.kind] || "neutral", UI.EVENT_KIND_LABELS[e.kind] || e.kind) + '</td><td data-label="Titre"><span class="cell-main">' + UI.escapeHtml(e.title) + '</span><span class="cell-sub">' + UI.escapeHtml((e.body || "").slice(0, 80)) + '</span></td><td data-label="Date">' + (e.starts_on ? UI.fmtDate(e.starts_on) + (e.ends_on && e.ends_on !== e.starts_on ? " → " + UI.fmtDate(e.ends_on) : "") : "—") + '</td><td data-label="Cible">' + UI.escapeHtml(e.target_label) + '</td><td data-label="Audience">' + ({ all: "Tous", parents: "Parents", staff: "Personnel" })[e.audience] + '</td><td class="actions"><button type="button" class="btn btn-danger btn-xs del-evt" data-id="' + e.id + '">Supprimer</button></td></tr>';
      }).join("") + "</tbody></table></div>";
      host.querySelectorAll(".del-evt").forEach(function (b) { b.addEventListener("click", function () { UI.confirm("Supprimer cette publication ?", "Elle disparaîtra des calendriers.", "Supprimer").then(function (ok) { if (ok) api.fetch("/calendar/events/" + b.dataset.id, { method: "DELETE" }).then(function () { UI.toast("Supprimé.", "success"); load(); }); }); }); });
    });
  }

  function openEventModal(kind, date) {
    var isComm = kind === "communique";
    var scopeOpts = '<option value="all">' + (ctx.role === "discipline" ? "Mon périmètre" : "Toute l'école") + '</option><option value="cycle">Un cycle</option><option value="class">Une classe</option>';
    var m = UI.modal({ title: isComm ? "Publier un communiqué" : "Ajouter un événement", size: "lg", body:
      '<form id="evForm" class="form-grid">' +
      '<div class="field"><label for="evKind">Type</label><select id="evKind">' + ["evenement", "communique", "reunion", "fete", "deuil", "conge", "examens", "echeance"].map(function (k) { return '<option value="' + k + '"' + (k === kind ? " selected" : "") + ">" + UI.EVENT_KIND_LABELS[k] + "</option>"; }).join("") + "</select></div>" +
      '<div class="field"><label for="evTitle">Titre</label><input id="evTitle" required maxlength="160" placeholder="' + (isComm ? "Ex. Fermeture exceptionnelle vendredi" : "Ex. Réunion des parents de 6e") + '" /></div>' +
      '<div class="field full"><label for="evBody">Message</label><textarea id="evBody" maxlength="2000" placeholder="Le texte reçu par les destinataires"></textarea></div>' +
      '<div class="field"><label for="evStart">Date</label><input id="evStart" type="date" value="' + (date || "") + '" /></div><div class="field"><label for="evEnd">Fin (si plusieurs jours)</label><input id="evEnd" type="date" /></div>' +
      '<div class="field"><label for="evTime">Heure</label><input id="evTime" type="time" /></div>' +
      '<div class="field"><label for="evAud">Audience</label><select id="evAud"><option value="all">Parents et personnel</option><option value="parents">Parents</option><option value="staff">Personnel</option></select></div>' +
      '<div class="field"><label for="evScope">Cible</label><select id="evScope">' + scopeOpts + "</select></div>" +
      '<div class="field" id="evValueWrap" hidden><label for="evValue">Précision</label><select id="evValue"></select></div>' +
      '<p class="note-inline full">' + UI.icon("info", 15) + "<span>Chaque destinataire autorisé reçoit une notification ; l'événement apparaît dans son calendrier. Les envois WhatsApp/SMS suivront le branchement du canal.</span></p>" +
      '<p class="form-error full" id="evErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="evCancel">Annuler</button><button type="submit" form="evForm" class="btn btn-lime btn-sm" id="evSubmit">Publier</button>' });
    m.querySelector("#evCancel").addEventListener("click", UI.closeModal);
    var scope = m.querySelector("#evScope"), valueWrap = m.querySelector("#evValueWrap"), value = m.querySelector("#evValue");
    scope.addEventListener("change", function () {
      valueWrap.hidden = scope.value === "all";
      if (scope.value === "cycle") value.innerHTML = ["maternelle", "primaire", "secondaire"].filter(function (c) { return ctx.role !== "discipline" || (ctx.scope_cycles || ["secondaire"]).indexOf(c) >= 0; }).map(function (c) { return '<option value="' + c + '">' + c.charAt(0).toUpperCase() + c.slice(1) + "</option>"; }).join("");
      if (scope.value === "class") value.innerHTML = classes.map(function (c) { return '<option value="' + c.id + '">' + UI.escapeHtml(c.name) + "</option>"; }).join("");
    });
    m.querySelector("#evForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#evSubmit"), err = m.querySelector("#evErr"); err.hidden = true;
      UI.btnState(btn, "loading", "Publication…");
      api.fetch("/calendar/events", { method: "POST", body: JSON.stringify({ kind: m.querySelector("#evKind").value, title: m.querySelector("#evTitle").value.trim(), body: m.querySelector("#evBody").value.trim(), starts_on: m.querySelector("#evStart").value || null, ends_on: m.querySelector("#evEnd").value || null, starts_time: m.querySelector("#evTime").value || null, audience: m.querySelector("#evAud").value, target_scope: scope.value, target_value: scope.value === "all" ? null : value.value }) }).then(function (res) {
        if (!res.ok) { UI.btnState(btn, "error"); err.textContent = res.body.error || "Impossible de publier."; err.hidden = false; return; }
        UI.btnState(btn, "success", "Publié"); UI.toast("Publié — " + UI.plural(res.body.notified, "personne notifiée", "personnes notifiées") + ".", "success", 4500);
        setTimeout(function () { UI.closeModal(); load(); }, 500);
      }).catch(function () { UI.btnState(btn, "error"); });
    });
  }
})();
