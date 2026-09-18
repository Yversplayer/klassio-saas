// KLASSIO — Documents : règlement et documents officiels (téléversés par la
// Direction), attestations de fréquentation et bulletins imprimables — tous
// générés à partir des données réelles, imprimés par le navigateur.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var ctx = null, docs = [], students = [];

  admin.initShell("documents").then(function (c) {
    ctx = c;
    if (c.role === "directeur") {
      document.getElementById("pageActions").innerHTML = '<button type="button" class="btn btn-lime btn-sm" id="upBtn">' + UI.icon("upload", 15) + "Téléverser un document</button>";
      document.getElementById("upBtn").addEventListener("click", openUpload);
    }
    load();
  });

  function load() {
    var host = document.getElementById("docContent");
    host.innerHTML = UI.skeleton("card", 2);
    Promise.all([api.fetch("/documents"), api.fetch("/students")]).then(function (r) {
      if (!r[0].ok) return admin.loadError(host, load, "Impossible de charger les documents");
      docs = r[0].body; students = r[1].ok ? r[1].body : [];
      render();
    }).catch(function () { admin.loadError(host, load, "Le serveur Klassio est injoignable"); });
  }

  var KIND = { reglement: "Règlement intérieur", calendrier: "Calendrier scolaire", autre: "Document" };
  function render() {
    var host = document.getElementById("docContent");
    var official = docs.length ? '<div class="doc-grid">' + docs.map(function (d) {
      return '<div class="doc-card"><div class="dc-ic">' + UI.icon(d.kind === "reglement" ? "discipline" : "file", 18) + '</div><div class="dc-body"><strong>' + UI.escapeHtml(d.title) + "</strong><span>" + KIND[d.kind] + " · " + UI.fmtDate(d.created_at) + (d.file_size ? " · " + Math.round(d.file_size / 1024) + " Ko" : "") + (d.visible_to === "staff" ? " · personnel uniquement" : "") + '</span></div><div class="row" style="flex-direction:column;gap:6px"><button type="button" class="btn btn-ghost btn-xs open-doc" data-id="' + d.id + '">' + UI.icon("eye", 13) + "Ouvrir</button>" + (ctx.role === "directeur" ? '<button type="button" class="link-btn del-doc" data-id="' + d.id + '">Supprimer</button>' : "") + "</div></div>";
    }).join("") + "</div>" : UI.emptyState("Aucun document officiel", ctx.role === "directeur" ? "Téléversez le règlement intérieur, le calendrier scolaire ou toute note officielle." : "L'établissement n'a pas encore publié de document.", "", "file");
    var mine = ctx.role === "parent" ? students : students.slice(0, 0);
    var personal = "";
    if (ctx.role === "parent" || ctx.role === "directeur" || ctx.role === "professeur") {
      var list = ctx.role === "parent" ? students : [];
      personal = '<div class="panel"><div class="panel-head"><h2>Documents par élève</h2><span class="sub">Attestation de fréquentation et bulletin — imprimables</span></div>' +
        (ctx.role === "parent" ? (list.length ? '<div class="doc-grid">' + list.map(function (s) {
          return '<div class="doc-card"><div class="dc-ic">' + UI.avatar(s, 40) + '</div><div class="dc-body"><strong>' + UI.escapeHtml(s.first_name + " " + s.last_name) + "</strong><span>" + UI.escapeHtml(s.class_name || "") + ' · <span class="chip-code">' + UI.escapeHtml(s.code || "") + '</span></span></div><div class="row" style="flex-direction:column;gap:6px"><button type="button" class="btn btn-ghost btn-xs att-btn" data-id="' + s.id + '">' + UI.icon("print", 13) + 'Attestation</button><a class="btn btn-ghost btn-xs" href="eleve-dossier.html?id=' + s.id + '&tab=scolarite">' + UI.icon("book", 13) + "Bulletin</a></div></div>";
        }).join("") + "</div>" : '<p class="muted">Aucun enfant rattaché.</p>')
        : '<div class="toolbar"><label class="search" for="attSearch">' + UI.icon("search", 15) + '<input id="attSearch" type="search" placeholder="Rechercher un élève pour imprimer son attestation…" /></label></div><div id="attResults"></div>') + "</div>";
    }
    host.innerHTML = '<div class="panel"><div class="panel-head"><h2>Documents de l\'établissement</h2></div>' + official + "</div>" + personal;
    host.querySelectorAll(".open-doc").forEach(function (b) { b.addEventListener("click", function () { openDoc(b.dataset.id); }); });
    host.querySelectorAll(".del-doc").forEach(function (b) { b.addEventListener("click", function () { UI.confirm("Supprimer ce document ?", "", "Supprimer").then(function (ok) { if (ok) api.fetch("/documents/" + b.dataset.id, { method: "DELETE" }).then(function () { UI.toast("Document supprimé.", "success"); load(); }); }); }); });
    host.querySelectorAll(".att-btn").forEach(function (b) { b.addEventListener("click", function () { printAttestation(b.dataset.id); }); });
    var search = document.getElementById("attSearch");
    if (search) search.addEventListener("input", UI.debounce(function () {
      var q = search.value.trim().toLowerCase(), res = document.getElementById("attResults");
      if (q.length < 2) { res.innerHTML = ""; return; }
      var hits = students.filter(function (s) { return (s.first_name + " " + s.last_name + " " + (s.code || "")).toLowerCase().indexOf(q) !== -1; }).slice(0, 8);
      res.innerHTML = hits.map(function (s) { return '<div class="gate-result">' + UI.avatar(s, 34) + '<div><strong>' + UI.escapeHtml(s.last_name + " " + s.first_name) + '</strong><div class="muted">' + UI.escapeHtml(s.class_name || "") + " · " + UI.escapeHtml(s.code || "") + '</div></div><button type="button" class="btn btn-ghost btn-xs att-btn" data-id="' + s.id + '">' + UI.icon("print", 13) + "Attestation</button></div>"; }).join("") || '<p class="muted">Aucun élève ne correspond.</p>';
      res.querySelectorAll(".att-btn").forEach(function (b) { b.addEventListener("click", function () { printAttestation(b.dataset.id); }); });
    }, 150));
  }

  function openDoc(id) {
    api.fetch("/documents/" + id + "/file").then(function (res) {
      if (!res.ok || !res.body.file_data) return UI.toast(res.body.error || "Document indisponible.", "error");
      var w = window.open("", "_blank");
      if (!w) return UI.toast("Autorisez les fenêtres pop-up pour ouvrir le document.", "error");
      w.document.write('<!doctype html><title>' + UI.escapeHtml(res.body.title) + '</title><body style="margin:0;background:#111"><' + (res.body.file_data.indexOf("data:application/pdf") === 0 ? 'iframe src="' + res.body.file_data + '" style="border:0;width:100vw;height:100vh"></iframe' : 'img src="' + res.body.file_data + '" style="max-width:100%;display:block;margin:0 auto"') + "></body>");
      w.document.close();
    });
  }

  function printAttestation(studentId) {
    api.fetch("/students/" + studentId + "/attestation").then(function (res) {
      if (!res.ok) return UI.toast(res.body.error || "Attestation indisponible.", "error");
      var a = res.body, s = a.student;
      var m = UI.modal({ title: "Attestation de fréquentation", size: "lg", body: '<div class="print-sheet" id="attSheet"><div class="ps-head"><div class="ps-school">' + (a.school.logo_data ? '<img src="' + UI.escapeHtml(a.school.logo_data) + '" alt="" style="width:56px;height:56px;border-radius:12px;object-fit:cover;margin-bottom:8px">' : "") + "<strong>" + UI.escapeHtml(a.school.name) + "</strong>" + (a.school.address ? "<span>" + UI.escapeHtml(a.school.address) + "</span>" : "") + (a.school.phone ? "<span>" + UI.escapeHtml(a.school.phone) + "</span>" : "") + '</div><div style="text-align:right"><h2>ATTESTATION</h2><span class="muted">de fréquentation scolaire</span><div class="muted mt-8">' + UI.fmtDate(a.issued_on) + "</div></div></div>" +
        '<p style="font-size:14.5px;line-height:1.8">Je soussigné(e) <strong>' + UI.escapeHtml(a.director || "la Direction") + "</strong>, Direction de <strong>" + UI.escapeHtml(a.school.name) + "</strong>, atteste que l'élève <strong>" + UI.escapeHtml(s.first_name + " " + s.last_name) + "</strong>" + (s.birth_date ? ", né(e) le " + UI.fmtDate(s.birth_date) + "," : "") + " identifiant <strong>" + UI.escapeHtml(s.code || "—") + "</strong>, est régulièrement inscrit(e) et fréquente l'établissement en classe de <strong>" + UI.escapeHtml(s.class_name || "—") + "</strong> pour l'année scolaire <strong>" + UI.escapeHtml(a.academic_year || "en cours") + "</strong>.</p>" +
        (a.attendance.total ? '<p class="muted">Présence enregistrée : ' + a.attendance.rate + " % sur " + a.attendance.total + " jour(s) appelé(s), " + a.attendance.absent + " absence(s) non justifiée(s).</p>" : "") +
        '<p style="margin-top:36px;text-align:right">Fait à ____________________, le ' + UI.fmtDate(a.issued_on) + '<br><br><br><strong>Signature et cachet de la Direction</strong></p><p class="ps-foot">Document généré par Klassio à partir du dossier réel de l\'élève. Vérifiable auprès de l\'établissement avec l\'identifiant ci-dessus.</p></div>',
        footer: '<button type="button" class="btn btn-ghost btn-sm" id="attClose">Fermer</button><button type="button" class="btn btn-lime btn-sm" id="attPrint">' + UI.icon("print", 15) + "Imprimer</button>" });
      m.querySelector("#attClose").addEventListener("click", UI.closeModal);
      m.querySelector("#attPrint").addEventListener("click", function () { UI.printSheet(document.getElementById("attSheet"), "Attestation — " + s.first_name + " " + s.last_name); });
    });
  }

  function openUpload() {
    var m = UI.modal({ title: "Téléverser un document officiel", body: '<form id="upForm" class="form-grid"><div class="field full"><label for="uTitle">Titre</label><input id="uTitle" required maxlength="160" placeholder="Ex. Règlement intérieur 2026-2027" /></div><div class="field"><label for="uKind">Type</label><select id="uKind"><option value="reglement">Règlement intérieur</option><option value="calendrier">Calendrier scolaire</option><option value="autre">Autre</option></select></div><div class="field"><label for="uVis">Visible par</label><select id="uVis"><option value="all">Tous (parents inclus)</option><option value="staff">Personnel uniquement</option></select></div>' +
      '<div class="field full"><label>Fichier (PDF ou image, 4 Mo max)</label><div class="brand-upload"><div class="bu-preview">' + UI.icon("file", 22) + '</div><div class="bu-text"><strong id="uFileName">Aucun fichier</strong><button type="button" class="link-btn" id="uPick">Choisir</button></div><input type="file" id="uFile" accept="application/pdf,image/png,image/jpeg" hidden></div></div>' +
      '<p class="note-inline full">' + UI.icon("info", 15) + '<span>Pour extraire les règles disciplinaires du règlement (points, fautes), utilisez Discipline → Règles → « Importer le règlement ».</span></p><p class="form-error full" id="uErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="uCancel">Annuler</button><button type="submit" form="upForm" class="btn btn-lime btn-sm" id="uSubmit">Téléverser</button>' });
    m.querySelector("#uCancel").addEventListener("click", UI.closeModal);
    var fileData = null, fileName = null;
    m.querySelector("#uPick").addEventListener("click", function () { m.querySelector("#uFile").click(); });
    m.querySelector("#uFile").addEventListener("change", function () { var f = this.files[0]; if (!f) return; UI.fileToDataUrl(f, 4 * 1024 * 1024).then(function (d) { fileData = d; fileName = f.name; m.querySelector("#uFileName").textContent = f.name; }).catch(function (e) { UI.toast(e.message, "error"); }); });
    m.querySelector("#upForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#uSubmit"), err = m.querySelector("#uErr"); err.hidden = true;
      if (!fileData) { err.textContent = "Choisissez un fichier."; err.hidden = false; return; }
      UI.btnState(btn, "loading", "Envoi…");
      api.fetch("/documents", { method: "POST", body: JSON.stringify({ title: m.querySelector("#uTitle").value.trim(), kind: m.querySelector("#uKind").value, visible_to: m.querySelector("#uVis").value, file_name: fileName, file_data: fileData }) }).then(function (res) {
        if (!res.ok) { UI.btnState(btn, "error"); err.textContent = res.body.error || "Impossible."; err.hidden = false; return; }
        UI.btnState(btn, "success"); UI.toast("Document publié.", "success"); setTimeout(function () { UI.closeModal(); load(); }, 400);
      });
    });
  }
})();
