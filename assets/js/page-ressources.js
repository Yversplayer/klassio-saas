// KLASSIO — Livres & devoirs : ressources publiées par classe. Le titulaire
// (ou la Direction) publie ; les parents de la classe consultent et
// téléchargent ; un devoir a une date de remise qui alimente le calendrier.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var ctx = null, items = [], classes = [], filterClass = UI.qs("class") || "", filterKind = "";
  var KINDS = { livre: ["Livre", "book"], lecon: ["Leçon", "file"], fiche: ["Fiche", "clipboard"], devoir: ["Devoir", "edit"], autre: ["Autre", "file"] };

  admin.initShell("ressources").then(function (c) {
    ctx = c;
    if (c.role === "directeur" || c.role === "professeur") {
      document.getElementById("pageActions").innerHTML = '<button type="button" class="btn btn-lime btn-sm" id="pubBtn">' + UI.icon("upload", 15) + "Publier</button>";
      document.getElementById("pubBtn").addEventListener("click", openPublish);
    }
    if (c.role === "parent") document.getElementById("pageSub").textContent = "Livres, leçons, fiches et devoirs publiés pour les classes de vos enfants.";
    load();
  });

  function load() {
    var host = document.getElementById("resContent");
    host.innerHTML = UI.skeleton("card", 3);
    Promise.all([api.fetch("/resources"), api.fetch("/classes")]).then(function (r) {
      if (!r[0].ok) return admin.loadError(host, load, "Impossible de charger les ressources");
      items = r[0].body; classes = r[1].ok ? r[1].body : [];
      render();
    }).catch(function () { admin.loadError(host, load, "Le serveur Klassio est injoignable"); });
  }

  function render() {
    var host = document.getElementById("resContent");
    var today = UI.todayIso();
    var due = items.filter(function (i) { return i.kind === "devoir" && i.due_date && i.due_date >= today; });
    var list = items.filter(function (i) { return (!filterClass || i.class_id === filterClass) && (!filterKind || i.kind === filterKind); });
    var kpis = '<div class="kpi-grid cols-3">' + UI.kpi("Ressources", String(items.length), { icon: "book" }) + UI.kpi("Devoirs à rendre", String(due.length), { icon: "edit", tone: due.length ? "warn" : "ok", sub: due.length ? "prochain : " + UI.fmtDate(due.sort(function (a, b) { return a.due_date < b.due_date ? -1 : 1; })[0].due_date) : "" }) + UI.kpi("Classes", String(classes.length), { icon: "classes" }) + "</div>";
    var toolbar = '<div class="toolbar"><select id="fClass"><option value="">Toutes les classes</option>' + classes.map(function (c) { return '<option value="' + c.id + '"' + (c.id === filterClass ? " selected" : "") + ">" + UI.escapeHtml(c.name) + "</option>"; }).join("") + '</select><div class="chips" id="kindChips">' + [""].concat(Object.keys(KINDS)).map(function (k) { return '<button type="button" class="chip' + (k === filterKind ? " active" : "") + '" data-kind="' + k + '">' + (k ? KINDS[k][0] + "s" : "Tout") + "</button>"; }).join("") + '</div><span class="count-label">' + UI.plural(list.length, "élément") + "</span></div>";
    var body;
    if (!items.length) body = UI.emptyState("Aucune ressource publiée", ctx.role === "parent" ? "Les enseignants publieront ici livres, leçons et devoirs." : "Publiez un livre, une leçon, une fiche ou un devoir pour une classe.", ctx.role !== "parent" && ctx.role !== "discipline" ? '<button type="button" class="btn btn-lime btn-sm" id="emptyPub">' + UI.icon("upload", 15) + "Publier</button>" : "", "book");
    else if (!list.length) body = UI.emptyState("Aucun résultat", "Modifiez vos filtres.", "", "search");
    else body = '<div class="doc-grid">' + list.map(function (r) {
      var k = KINDS[r.kind] || KINDS.autre, late = r.kind === "devoir" && r.due_date && r.due_date < today;
      return '<div class="doc-card"><div class="dc-ic">' + UI.icon(k[1], 18) + '</div><div class="dc-body"><strong>' + UI.escapeHtml(r.title) + "</strong><span>" + UI.escapeHtml(r.class_name) + (r.subject ? " · " + UI.escapeHtml(r.subject) : "") + (r.due_date ? " · " + (late ? "échéance passée " : "à rendre le ") + UI.fmtDate(r.due_date) : "") + " · " + UI.escapeHtml(r.author || "") + "</span>" + (r.description ? '<span style="display:block;margin-top:3px;color:var(--ink-soft)">' + UI.escapeHtml(r.description.slice(0, 140)) + "</span>" : "") + '</div><div class="row" style="flex-direction:column;gap:6px">' + UI.badge(r.kind === "devoir" ? (late ? "neutral" : "warn") : "info", k[0]) + (r.file_name ? '<button type="button" class="btn btn-ghost btn-xs open-file" data-id="' + r.id + '">' + UI.icon("download", 13) + "Ouvrir</button>" : "") + (ctx.role === "directeur" || ctx.role === "professeur" ? '<button type="button" class="link-btn del-res" data-id="' + r.id + '">Retirer</button>' : "") + "</div></div>";
    }).join("") + "</div>";
    host.innerHTML = kpis + toolbar + '<div class="panel">' + body + "</div>";
    document.getElementById("fClass").addEventListener("change", function () { filterClass = this.value; render(); });
    document.querySelectorAll("#kindChips .chip").forEach(function (b) { b.addEventListener("click", function () { filterKind = b.dataset.kind; render(); }); });
    var e = document.getElementById("emptyPub"); if (e) e.addEventListener("click", openPublish);
    host.querySelectorAll(".open-file").forEach(function (b) { b.addEventListener("click", function () { openFile(b.dataset.id); }); });
    host.querySelectorAll(".del-res").forEach(function (b) { b.addEventListener("click", function () { UI.confirm("Retirer cette ressource ?", "Elle ne sera plus visible des parents.", "Retirer").then(function (ok) { if (ok) api.fetch("/resources/" + b.dataset.id, { method: "DELETE" }).then(function (r) { if (!r.ok) return UI.toast(r.body.error || "Impossible.", "error"); UI.toast("Ressource retirée.", "success"); load(); }); }); }); });
  }

  function openFile(id) {
    api.fetch("/resources/" + id + "/file").then(function (res) {
      if (!res.ok || !res.body.file_data) return UI.toast(res.body.error || "Fichier indisponible.", "error");
      var w = window.open("", "_blank");
      if (!w) return UI.toast("Autorisez les fenêtres pop-up pour ouvrir le fichier.", "error");
      w.document.write('<!doctype html><title>' + UI.escapeHtml(res.body.title) + '</title><body style="margin:0;background:#111"><' + (res.body.file_data.indexOf("data:application/pdf") === 0 ? 'iframe src="' + res.body.file_data + '" style="border:0;width:100vw;height:100vh"></iframe' : 'img src="' + res.body.file_data + '" style="max-width:100%;display:block;margin:0 auto"') + "></body>");
      w.document.close();
    });
  }

  function openPublish() {
    if (!classes.length) return UI.toast("Aucune classe rattachée.", "error");
    var m = UI.modal({ title: "Publier une ressource", size: "lg", body: '<form id="pubForm" class="form-grid">' +
      '<div class="field"><label for="pClass">Classe</label><select id="pClass">' + classes.map(function (c) { return '<option value="' + c.id + '"' + (c.id === filterClass ? " selected" : "") + ">" + UI.escapeHtml(c.name) + "</option>"; }).join("") + "</select></div>" +
      '<div class="field"><label for="pKind">Type</label><select id="pKind">' + Object.keys(KINDS).map(function (k) { return '<option value="' + k + '">' + KINDS[k][0] + "</option>"; }).join("") + "</select></div>" +
      '<div class="field full"><label for="pTitle">Titre</label><input id="pTitle" required maxlength="160" placeholder="Ex. Leçon 4 — Les fractions" /></div>' +
      '<div class="field"><label for="pSubject">Matière</label><input id="pSubject" maxlength="80" /></div><div class="field" id="pDueWrap" hidden><label for="pDue">À rendre le</label><input id="pDue" type="date" min="' + UI.todayIso() + '" /></div>' +
      '<div class="field full"><label for="pDesc">Consignes / description</label><textarea id="pDesc" maxlength="2000"></textarea></div>' +
      '<div class="field full"><label>Fichier (PDF ou image, 3 Mo max)</label><div class="brand-upload"><div class="bu-preview" id="pPreview">' + UI.icon("file", 22) + '</div><div class="bu-text"><strong id="pFileName">Aucun fichier</strong>Le fichier est facultatif pour un devoir avec consignes.<br><button type="button" class="link-btn" id="pPick">Choisir</button></div><input type="file" id="pFile" accept="application/pdf,image/png,image/jpeg" hidden></div></div>' +
      '<p class="form-error full" id="pErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="pCancel">Annuler</button><button type="submit" form="pubForm" class="btn btn-lime btn-sm" id="pSubmit">Publier</button>' });
    m.querySelector("#pCancel").addEventListener("click", UI.closeModal);
    var fileData = null, fileName = null;
    m.querySelector("#pKind").addEventListener("change", function () { m.querySelector("#pDueWrap").hidden = this.value !== "devoir"; });
    m.querySelector("#pPick").addEventListener("click", function () { m.querySelector("#pFile").click(); });
    m.querySelector("#pFile").addEventListener("change", function () {
      var f = this.files[0]; if (!f) return;
      UI.fileToDataUrl(f, 3 * 1024 * 1024).then(function (d) { fileData = d; fileName = f.name; m.querySelector("#pFileName").textContent = f.name + " (" + Math.round(f.size / 1024) + " Ko)"; m.querySelector("#pPreview").innerHTML = d.indexOf("data:image") === 0 ? '<img src="' + d + '" alt="">' : UI.icon("file", 22); }).catch(function (e) { UI.toast(e.message, "error"); });
    });
    m.querySelector("#pubForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#pSubmit"), err = m.querySelector("#pErr"); err.hidden = true;
      UI.btnState(btn, "loading", "Publication…");
      api.fetch("/resources", { method: "POST", body: JSON.stringify({ class_id: m.querySelector("#pClass").value, kind: m.querySelector("#pKind").value, title: m.querySelector("#pTitle").value.trim(), subject: m.querySelector("#pSubject").value.trim(), description: m.querySelector("#pDesc").value.trim(), due_date: m.querySelector("#pDue").value || null, file_name: fileName, file_data: fileData }) }).then(function (res) {
        if (!res.ok) { UI.btnState(btn, "error"); err.textContent = res.body.error || "Impossible de publier."; err.hidden = false; return; }
        UI.btnState(btn, "success", "Publié"); UI.toast("Ressource publiée — les parents de la classe sont informés.", "success");
        setTimeout(function () { UI.closeModal(); load(); }, 500);
      }).catch(function () { UI.btnState(btn, "error"); });
    });
  }
})();
