// KLASSIO — Pointage au portail (DD / Direction) : l'élève arrive en retard,
// on tape son nom ou son identifiant, l'heure d'arrivée est enregistrée.
// Un « présent » saisi ensuite en classe ne l'écrase pas.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var ctx = null, log = [];

  admin.initShell("pointage").then(function (c) {
    ctx = c;
    if (c.role !== "discipline" && c.role !== "directeur") { document.getElementById("gateContent").innerHTML = UI.emptyState("Réservé au Directeur des disciplines", "", '<a href="dashboard.html" class="btn btn-ghost btn-sm">Retour</a>', "lock"); return; }
    render();
    refreshToday();
  });

  function render() {
    document.getElementById("gateContent").innerHTML =
      '<div class="panel"><div class="row" style="gap:12px;align-items:flex-end"><div class="field grow" style="margin:0"><label for="gateQ">Élève</label><input id="gateQ" class="gate-search" type="search" placeholder="Nom, prénom ou identifiant…" autocomplete="off" autofocus /></div><div class="field" style="margin:0;max-width:130px"><label for="gateTime">Heure d\'arrivée</label><input id="gateTime" type="time" value="' + new Date().toTimeString().slice(0, 5) + '" /></div></div><div id="gateResults" style="margin-top:12px"></div></div>' +
      '<div class="two-col"><div class="panel"><div class="panel-head"><h2>Pointés aujourd\'hui</h2><span class="sub" id="lateCount"></span></div><div class="gate-log" id="gateLog">' + UI.skeleton("row", 2) + '</div></div>' +
      '<div class="panel"><div class="panel-head"><h2>Comment ça marche</h2></div><ol class="step-list"><li><span class="num">1</span><span>Tapez le nom — les élèves de votre périmètre apparaissent.</span></li><li><span class="num">2</span><span>Cliquez « Retard » : l\'heure est enregistrée, le parent et le titulaire sont informés.</span></li><li><span class="num">3</span><span>Le titulaire fait l\'appel normalement en classe : le retard du portail est conservé, sans double saisie.</span></li></ol></div></div>';
    var q = document.getElementById("gateQ");
    q.addEventListener("input", UI.debounce(search, 150));
    q.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); var first = document.querySelector("#gateResults .gate-btn"); if (first) first.click(); } });
  }

  function search() {
    var q = document.getElementById("gateQ").value.trim(), host = document.getElementById("gateResults");
    if (q.length < 2) { host.innerHTML = ""; return; }
    api.fetch("/attendance/search?q=" + encodeURIComponent(q)).then(function (res) {
      if (!res.ok) return;
      host.innerHTML = res.body.length ? res.body.map(function (s) {
        var st = s.today_status ? UI.badge(s.today_status, ({ present: "présent", late: "retard" + (s.arrival_time ? " " + s.arrival_time : ""), absent: "absent", excused: "excusé" })[s.today_status]) : "";
        return '<div class="gate-result">' + UI.avatar(s, 38) + '<div><strong>' + UI.escapeHtml(s.last_name + " " + s.first_name) + '</strong><div class="muted">' + UI.escapeHtml(s.class_name || "") + ' · <span class="chip-code">' + UI.escapeHtml(s.code || "") + "</span> " + st + '</div></div><button type="button" class="btn btn-lime btn-sm gate-btn" data-id="' + s.id + '"' + (s.today_status === "late" ? " disabled" : "") + ">" + UI.icon("clock", 15) + (s.today_status === "late" ? "Déjà pointé" : "Retard") + "</button></div>";
      }).join("") : '<p class="muted">Aucun élève ne correspond dans votre périmètre.</p>';
      host.querySelectorAll(".gate-btn").forEach(function (b) { b.addEventListener("click", function () { mark(b); }); });
    });
  }

  function mark(btn) {
    UI.btnState(btn, "loading", "…");
    api.fetch("/attendance/gate", { method: "POST", body: JSON.stringify({ student_id: btn.dataset.id, arrival_time: document.getElementById("gateTime").value }) }).then(function (res) {
      if (!res.ok) { UI.btnState(btn, "error"); return UI.toast(res.body.error || "Impossible.", "error"); }
      var s = res.body.student;
      UI.btnState(btn, "success", "Pointé");
      UI.toast(s.first_name + " " + s.last_name + " — retard " + res.body.arrival_time + (res.body.late_count_30d >= 3 ? " · " + res.body.late_count_30d + "e retard en 30 jours" : ""), res.body.late_count_30d >= 3 ? "error" : "success", 4000);
      document.getElementById("gateQ").value = ""; document.getElementById("gateResults").innerHTML = ""; document.getElementById("gateQ").focus();
      refreshToday();
    });
  }

  function refreshToday() {
    api.fetch("/discipline/today").then(function (res) {
      if (!res.ok) return;
      var late = res.body.late_today;
      document.getElementById("lateCount").textContent = UI.plural(late.length, "retard");
      document.getElementById("gateLog").innerHTML = late.length ? late.map(function (s) { return '<div class="roll-row">' + UI.avatar(s, 32) + '<div class="roll-name">' + UI.escapeHtml(s.last_name + " " + s.first_name) + "<span>" + UI.escapeHtml(s.class_name || "") + (s.source === "gate" ? " · portail" : " · classe") + "</span></div>" + UI.badge("warn", s.arrival_time || "retard") + "</div>"; }).join("") : '<p class="muted">Aucun retard pointé aujourd\'hui.</p>';
    });
  }
})();
