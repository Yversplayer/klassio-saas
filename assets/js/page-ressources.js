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

  // Refonte du 08/10/2026, sur le modèle « librairie » du propriétaire :
  // une couverture par ressource, la couleur dit le type, un signet dit
  // qu'un devoir attend. Mêmes données qu'avant (GET /resources, /classes).
  var COULEURS = { livre: "var(--kb-livre)", lecon: "var(--kb-lecon)", fiche: "var(--kb-fiche)", devoir: "var(--kb-devoir)", autre: "var(--kb-autre)" };
  function format(nom) {
    var m = /\.([a-z0-9]{1,5})$/i.exec(nom || "");
    return m ? m[1].toUpperCase() : "";
  }
  function render() {
    var host = document.getElementById("resContent");
    var today = UI.todayIso(), parent = ctx.role === "parent", editeur = ctx.role === "directeur" || ctx.role === "professeur";
    var due = items.filter(function (i) { return i.kind === "devoir" && i.due_date && i.due_date >= today; }).sort(function (a, b) { return a.due_date < b.due_date ? -1 : 1; });
    var list = items.filter(function (i) { return (!filterClass || i.class_id === filterClass) && (!filterKind || i.kind === filterKind); });
    var parType = {}; items.forEach(function (i) { parType[i.kind] = (parType[i.kind] || 0) + 1; });

    var vitrine = '<section class="kb-vitrine"><div class="kb-pile" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><b></b></div><div>' +
      "<h2>" + (parent ? "La bibliothèque de vos enfants" : "La bibliothèque de vos classes") + "</h2>" +
      "<p>" + (parent ? "Livres, leçons, fiches et devoirs publiés par les enseignants. Touchez une couverture pour ouvrir le fichier." : "Ce que vous publiez ici apparaît dans l'espace « Livres & devoirs » des parents de la classe, jamais ailleurs.") + "</p>" +
      '<div class="kb-chiffres"><span>' + UI.plural(items.length, "ressource") + "</span><span>" + UI.plural(due.length, "devoir à rendre", "devoirs à rendre") + "</span><span>" + UI.plural(classes.length, "classe") + "</span></div></div></section>";

    var arendre = '<section class="kb-carte"><div class="kb-tete"><h2>À rendre</h2><span class="sub">' + (due.length ? "par date" : "") + "</span></div>" +
      (due.length ? '<div class="kb-arendre">' + due.slice(0, 5).map(function (r) {
        var d = new Date(r.due_date + "T00:00:00");
        return '<div class="kb-ar"><span class="kb-mini" style="--c:var(--kb-devoir)"></span><span><strong>' + UI.escapeHtml(r.title) + "</strong><span>" + UI.escapeHtml(r.class_name) + (r.subject ? " · " + UI.escapeHtml(r.subject) : "") + '</span></span><span class="kb-jour"><b>' + d.getDate() + "</b>" + UI.escapeHtml(d.toLocaleDateString(window.KLASSIO_LOCALE || "fr-FR", { month: "short" })) + "</span></div>";
      }).join("") + "</div>" : '<p class="kb-vide">Aucun devoir à rendre pour le moment.</p>') + "</section>";

    var cats = '<div class="kb-cats" role="group" aria-label="Types de ressources">' + [""].concat(Object.keys(KINDS)).map(function (k) {
      return '<button type="button" class="kb-cat" data-kind="' + k + '" aria-pressed="' + (k === filterKind) + '"><span class="kb-mini' + (k ? "" : " tout") + '"' + (k ? ' style="--c:' + COULEURS[k] + '"' : "") + "></span>" + (k ? KINDS[k][0] + "s" : "Tout") + (k && parType[k] ? " · " + parType[k] : "") + "</button>";
    }).join("") + "</div>";

    var filtres = '<div class="kb-filtres"><select id="fClass" aria-label="Classe"><option value="">Toutes les classes</option>' + classes.map(function (c) { return '<option value="' + c.id + '"' + (c.id === filterClass ? " selected" : "") + ">" + UI.escapeHtml(c.name) + "</option>"; }).join("") + '</select><span class="count-label">' + UI.plural(list.length, "élément") + "</span></div>";

    var rayon;
    if (!items.length) rayon = UI.emptyState("Aucune ressource publiée", parent ? "Les enseignants publieront ici livres, leçons et devoirs." : "Publiez un livre, une leçon, une fiche ou un devoir pour une classe.", editeur ? '<button type="button" class="btn btn-lime btn-sm" id="emptyPub">' + UI.icon("upload", 15) + "Publier</button>" : "", "book");
    else if (!list.length) rayon = UI.emptyState("Aucun résultat", "Modifiez vos filtres.", "", "search");
    else rayon = '<div class="kb-rayon">' + list.map(function (r) {
      var k = KINDS[r.kind] || KINDS.autre, passe = r.kind === "devoir" && r.due_date && r.due_date < today, fmt = format(r.file_name);
      var couv = '<' + (r.file_name ? 'button type="button" class="kb-couv ouvrable open-file' : 'div class="kb-couv') + (r.kind === "devoir" ? " clair" : "") + '" style="--c:' + COULEURS[r.kind] + '"' + (r.file_name ? ' data-id="' + r.id + '" aria-label="Ouvrir ' + UI.escapeHtml(r.title) + '"' : "") + ">" +
        (r.kind === "devoir" ? '<span class="kb-signet' + (passe ? " passe" : "") + '" aria-hidden="true"></span>' : "") +
        "<small>" + UI.escapeHtml(r.subject || k[0]) + "</small><strong>" + UI.escapeHtml(r.title) + "</strong><em>" + UI.escapeHtml(r.class_name) + "</em>" +
        (fmt ? '<span class="kb-format">' + UI.escapeHtml(fmt) + "</span>" : "") + "</" + (r.file_name ? "button" : "div") + ">";
      return '<article class="kb-livre">' + couv + '<div class="kb-legende"><strong>' + UI.escapeHtml(r.title) + "</strong><span>" + UI.escapeHtml(k[0]) + " · " + UI.escapeHtml(r.author || "") + "</span>" +
        (r.due_date ? '<span class="' + (passe ? "" : "kb-due") + '">' + (passe ? "Échéance passée " : "À rendre le ") + UI.fmtDate(r.due_date) + "</span>" : "") +
        (r.description ? "<span>" + UI.escapeHtml(r.description.slice(0, 90)) + "</span>" : "") + "</div>" +
        (editeur ? '<div class="kb-actions"><button type="button" class="link-btn del-res" data-id="' + r.id + '">Retirer</button></div>' : "") + "</article>";
    }).join("") + "</div>";

    host.innerHTML = '<div class="kb-haut">' + vitrine + arendre + "</div>" + '<section class="kb-carte">' + cats + filtres + rayon + "</section>";
    document.getElementById("fClass").addEventListener("change", function () { filterClass = this.value; render(); });
    host.querySelectorAll(".kb-cat").forEach(function (b) { b.addEventListener("click", function () { filterKind = b.dataset.kind; render(); }); });
    var e = document.getElementById("emptyPub"); if (e) e.addEventListener("click", openPublish);
    host.querySelectorAll(".open-file").forEach(function (b) { b.addEventListener("click", function () { openFile(b.dataset.id); }); });
    host.querySelectorAll(".del-res").forEach(function (b) { b.addEventListener("click", function () { UI.confirm("Retirer cette ressource ?", "Elle ne sera plus visible des parents.", "Retirer").then(function (ok) { if (ok) api.fetch("/resources/" + b.dataset.id, { method: "DELETE" }).then(function (r) { if (!r.ok) return UI.toast(r.body.error || "Impossible.", "error"); UI.toast("Ressource retirée.", "success"); load(); }); }); }); });
  }

  function openFile(id) {
    api.fetch("/resources/" + id + "/file").then(function (res) {
      if (!res.ok || !res.body.file_data) return UI.toast(res.body.error || "Fichier indisponible.", "error");
      // PDF et images s'affichent ; Word, PowerPoint, audio… se téléchargent.
      // Un HTML ou un SVG publié n'est jamais rendu dans la page (ui.js).
      UI.openFile(res.body.file_data, res.body.file_name, res.body.title);
    }).catch(function () { UI.toast("Le serveur Klassio est injoignable.", "error"); });
  }

  function openPublish() {
    if (!classes.length) return UI.toast("Aucune classe rattachée.", "error");
    var m = UI.modal({ title: "Publier une ressource", size: "lg", body: '<form id="pubForm" class="form-grid">' +
      '<div class="field"><label for="pClass">Classe</label><select id="pClass">' + classes.map(function (c) { return '<option value="' + c.id + '"' + (c.id === filterClass ? " selected" : "") + ">" + UI.escapeHtml(c.name) + "</option>"; }).join("") + "</select></div>" +
      '<div class="field"><label for="pKind">Type</label><select id="pKind">' + Object.keys(KINDS).map(function (k) { return '<option value="' + k + '">' + KINDS[k][0] + "</option>"; }).join("") + "</select></div>" +
      '<div class="field full"><label for="pTitle">Titre</label><input id="pTitle" required maxlength="160" placeholder="Ex. Leçon 4 — Les fractions" /></div>' +
      '<div class="field"><label for="pSubject">Matière</label><input id="pSubject" maxlength="80" /></div><div class="field" id="pDueWrap" hidden><label for="pDue">À rendre le</label><input id="pDue" type="date" min="' + UI.todayIso() + '" /></div>' +
      '<div class="field full"><label for="pDesc">Consignes / description</label><textarea id="pDesc" maxlength="2000"></textarea></div>' +
      '<div class="field full"><label>Fichier (PDF, Word, PowerPoint, Excel, image, audio… 10 Mo max)</label><div class="brand-upload"><div class="bu-preview" id="pPreview">' + UI.icon("file", 22) + '</div><div class="bu-text"><strong id="pFileName">Aucun fichier</strong>Le fichier est facultatif pour un devoir avec consignes.<br><button type="button" class="link-btn" id="pPick">Choisir</button></div><input type="file" id="pFile" hidden></div></div>' +
      '<p class="form-error full" id="pErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="pCancel">Annuler</button><button type="submit" form="pubForm" class="btn btn-lime btn-sm" id="pSubmit">Publier</button>' });
    m.querySelector("#pCancel").addEventListener("click", UI.closeModal);
    var fileData = null, fileName = null;
    m.querySelector("#pKind").addEventListener("change", function () { m.querySelector("#pDueWrap").hidden = this.value !== "devoir"; });
    m.querySelector("#pPick").addEventListener("click", function () { m.querySelector("#pFile").click(); });
    m.querySelector("#pFile").addEventListener("change", function () {
      var f = this.files[0]; if (!f) return;
      UI.fileToDataUrl(f, 10 * 1024 * 1024).then(function (d) { fileData = d; fileName = f.name; m.querySelector("#pFileName").textContent = f.name + " (" + Math.round(f.size / 1024) + " Ko)"; m.querySelector("#pPreview").innerHTML = d.indexOf("data:image") === 0 ? '<img src="' + d + '" alt="">' : UI.icon("file", 22); }).catch(function (e) { UI.toast(e.message, "error"); });
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
