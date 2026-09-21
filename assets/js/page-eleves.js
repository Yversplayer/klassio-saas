// KLASSIO — Élèves : dossiers 3D (ou tableau), recherche instantanée
// (nom, prénom, identifiant, classe), filtres réels, pagination, ajout
// (Direction). Le périmètre vient du backend : un professeur ne reçoit que
// ses classes, un parent que ses enfants, le DD que le secondaire.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var ctx = null, all = [], classes = [], classesById = {}, view = "folders", page = 1, PAGE_SIZE = 24, financeVisible = false;
  var sortKey = "last_name", sortDir = "asc";

  admin.initShell("eleves").then(function (c) {
    ctx = c;
    financeVisible = c.role === "directeur" || c.role === "parent" || (c.role === "professeur" && c.finance_visible);
    if (c.role === "parent") { document.getElementById("pageTitle").textContent = "Mes enfants"; document.getElementById("studentToolbar").hidden = true; }
    if (c.role === "professeur") document.getElementById("pageTitle").textContent = "Mes élèves";
    if (c.role === "directeur") {
      document.getElementById("financeFilter").hidden = false;
      document.getElementById("statusFilter").hidden = false;
      // Élèves et Classes ne font plus qu'une entrée de menu : le lien vers les
      // classes doit donc exister ICI, sinon la page devient inatteignable.
      // Règle tenue depuis les onglets du dossier et le menu latéral coupé :
      // on ne retire du menu que ce qui reste joignable ailleurs.
      document.getElementById("pageActions").innerHTML =
        '<a href="classes.html" class="btn btn-ghost btn-sm">' + UI.icon("classes", 15) + "Classes</a>" +
        // Même règle : le passage d'année n'a pas d'entrée de menu, il doit
        // donc avoir un lien entrant depuis le domaine auquel il appartient.
        '<a href="passage.html" class="btn btn-ghost btn-sm">' + UI.icon("calendar", 15) + "Passage d'année</a>" +
        '<a href="inscription.html#import" class="btn btn-ghost btn-sm">' + UI.icon("upload", 15) + "Importer</a>" +
        '<button type="button" class="btn btn-lime btn-sm" id="addStudentBtn">' + UI.icon("plus", 15) + "Ajouter un élève</button>";
      document.getElementById("addStudentBtn").addEventListener("click", openAddModal);
      if (UI.qs("new")) setTimeout(openAddModal, 300);
    }
    document.getElementById("viewToggle").innerHTML = '<button type="button" data-view="folders" class="active" aria-label="Dossiers">' + UI.icon("grid", 16) + '</button><button type="button" data-view="table" aria-label="Tableau">' + UI.icon("list", 16) + "</button>";
    document.getElementById("searchWrap").insertAdjacentHTML("afterbegin", UI.icon("search", 16));
    try { view = localStorage.getItem("klassio_students_view") || "folders"; } catch (e) {}
    document.querySelectorAll("#viewToggle button").forEach(function (b) {
      b.classList.toggle("active", b.dataset.view === view);
      b.addEventListener("click", function () { view = b.dataset.view; try { localStorage.setItem("klassio_students_view", view); } catch (e) {} document.querySelectorAll("#viewToggle button").forEach(function (x) { x.classList.toggle("active", x === b); }); render(); });
    });
    load();
  });

  function load() {
    document.getElementById("studentsView").innerHTML = view === "folders" ? '<div class="sfolder-grid">' + UI.skeleton("folder", 8) + "</div>" : UI.skeleton("row", 8);
    Promise.all([api.fetch("/students"), api.fetch("/classes")]).then(function (r) {
      if (!r[0].ok) return admin.loadError(document.getElementById("studentsView"), load, "Impossible de charger les élèves");
      all = r[0].body; classes = r[1].ok ? r[1].body : [];
      classesById = {}; classes.forEach(function (c) { classesById[c.id] = c; });
      var sel = document.getElementById("classFilter");
      sel.innerHTML = '<option value="">Toutes les classes</option>' + classes.map(function (c) { return '<option value="' + c.id + '">' + UI.escapeHtml(c.name) + "</option>"; }).join("");
      var wanted = UI.qs("class");
      if (wanted) { var m = classes.find(function (c) { return c.name === wanted || c.id === wanted; }); if (m) sel.value = m.id; }
      document.getElementById("studentCountLabel").textContent = ctx.role === "parent" ? UI.plural(all.length, "enfant rattaché", "enfants rattachés") + " à votre compte" : UI.plural(all.length, "élève", "élèves") + (ctx.role === "professeur" ? " dans vos classes" : " enregistrés");
      renderKpis();
      applyFilters();
    }).catch(function () { admin.loadError(document.getElementById("studentsView"), load, "Le serveur Klassio est injoignable"); });
  }

  function renderKpis() {
    if (ctx.role === "parent" || !all.length) return;
    var active = all.filter(function (s) { return s.status === "active"; });
    var absent = active.filter(function (s) { return s.today_status === "absent"; }).length;
    var late = active.filter(function (s) { return s.today_status === "late"; }).length;
    var called = active.filter(function (s) { return s.today_status; }).length;
    var html = UI.kpi("Élèves actifs", active.length.toLocaleString("fr-FR"), { icon: "students", sub: classes.length + " classes" }) +
      UI.kpi("Appelés aujourd'hui", called.toLocaleString("fr-FR"), { icon: "clipboard", sub: active.length ? Math.round(called / active.length * 100) + " % des élèves" : "" }) +
      UI.kpi("Absents / retards", absent + " / " + late, { icon: "calendar", tone: absent ? "bad" : "" });
    if (financeVisible) {
      var due = active.filter(function (s) { return (s.balance || 0) > 0; }).length;
      html += UI.kpi("Avec solde restant", due.toLocaleString("fr-FR"), { icon: "finance", tone: due ? "warn" : "ok", sub: active.length ? Math.round((active.length - due) / active.length * 100) + " % à jour" : "" });
    } else {
      var byGender = active.reduce(function (acc, s) { acc[s.gender || "?"] = (acc[s.gender || "?"] || 0) + 1; return acc; }, {});
      html += UI.kpi("Filles / garçons", (byGender.F || 0) + " / " + (byGender.M || 0), { icon: "users", sub: byGender["?"] ? byGender["?"] + " non renseigné(s)" : "" });
    }
    var el = document.getElementById("studentKpis"); el.innerHTML = html; el.hidden = false;
  }

  var filtered = [];
  function applyFilters() {
    var q = document.getElementById("studentSearch").value.trim().toLowerCase();
    var classId = document.getElementById("classFilter").value, cycle = document.getElementById("cycleFilter").value;
    var fin = document.getElementById("financeFilter").value, status = document.getElementById("statusFilter").value || "active";
    filtered = all.filter(function (s) {
      if (status !== "all" && s.status !== status) return false;
      if (classId && s.class_id !== classId) return false;
      if (cycle && s.class_cycle !== cycle) return false;
      if (fin === "due" && !((s.balance || 0) > 0)) return false;
      if (fin === "paid" && (s.balance || 0) > 0) return false;
      if (!q) return true;
      return (s.first_name + " " + s.last_name + " " + s.last_name + " " + s.first_name + " " + (s.code || "") + " " + (s.class_name || "")).toLowerCase().indexOf(q) !== -1;
    });
    filtered.sort(function (a, b) {
      var va = a[sortKey], vb = b[sortKey];
      if (typeof va === "string") { va = va.toLowerCase(); vb = (vb || "").toLowerCase(); }
      if (va == null) va = -Infinity; if (vb == null) vb = -Infinity;
      return (va < vb ? -1 : va > vb ? 1 : 0) * (sortDir === "asc" ? 1 : -1);
    });
    page = 1;
    render();
  }

  function render() {
    var host = document.getElementById("studentsView");
    var pager = document.getElementById("studentsPager");
    if (!all.length) {
      pager.hidden = true;
      host.innerHTML = ctx.role === "directeur"
        ? UI.emptyState("Aucun élève pour le moment", "Importez votre fichier Excel ou ajoutez votre premier élève : chaque dossier obtient un identifiant unique.", '<div class="row"><button type="button" class="btn btn-lime btn-sm" id="emptyAdd">' + UI.icon("plus", 15) + 'Ajouter un élève</button><a href="inscription.html#import" class="btn btn-ghost btn-sm">Importer un fichier</a></div>', "students")
        : ctx.role === "professeur" ? UI.emptyState("Aucune classe rattachée", "La Direction doit vous rattacher à vos classes pour que vos élèves apparaissent ici.", "", "students")
        : ctx.role === "parent" ? UI.emptyState("Aucun enfant rattaché", "L'accès à un dossier vient uniquement d'une invitation de l'établissement.", "", "students")
        : UI.emptyState("Aucun élève dans le cycle secondaire", "Vérifiez le cycle des classes avec la Direction (Classes → modifier).", "", "students");
      var b = document.getElementById("emptyAdd"); if (b) b.addEventListener("click", openAddModal);
      return;
    }
    if (!filtered.length) {
      pager.hidden = true;
      host.innerHTML = UI.emptyState("Aucun élève trouvé", "Essayez de modifier votre recherche ou vos filtres.", '<button type="button" class="btn btn-ghost btn-sm" id="resetFilters">Réinitialiser les filtres</button>', "search");
      document.getElementById("resetFilters").addEventListener("click", function () {
        document.getElementById("studentSearch").value = ""; ["classFilter", "cycleFilter", "financeFilter"].forEach(function (id) { document.getElementById(id).value = ""; }); applyFilters();
      });
      return;
    }
    var pages = Math.ceil(filtered.length / PAGE_SIZE);
    var slice = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
    host.innerHTML = view === "folders" ? renderFolders(slice) : renderTable(slice);
    UI.wireHrefs(host);
    pager.hidden = pages <= 1;
    pager.innerHTML = "<span>" + ((page - 1) * PAGE_SIZE + 1) + "–" + Math.min(page * PAGE_SIZE, filtered.length) + " sur " + filtered.length.toLocaleString("fr-FR") + "</span>" +
      '<div class="pg-btns"><button type="button" id="pgPrev" aria-label="Page précédente"' + (page <= 1 ? " disabled" : "") + ">" + UI.icon("chevronLeft", 16) + "</button><span style=\"align-self:center;padding:0 6px;\">Page " + page + " / " + pages + '</span><button type="button" id="pgNext" aria-label="Page suivante"' + (page >= pages ? " disabled" : "") + ">" + UI.icon("chevronRight", 16) + "</button></div>";
    var prev = document.getElementById("pgPrev"), next = document.getElementById("pgNext");
    if (prev) prev.addEventListener("click", function () { page--; render(); window.scrollTo({ top: 0, behavior: "smooth" }); });
    if (next) next.addEventListener("click", function () { page++; render(); window.scrollTo({ top: 0, behavior: "smooth" }); });
    if (view === "table") wireSort();
  }

  function renderFolders(list) {
    return '<div class="sfolder-grid">' + list.map(function (s) {
      var status = s.today_status ? '<span class="sf-status">' + UI.badge(s.today_status) + "</span>" : "";
      var foot = "";
      if (financeVisible && s.balance != null) foot += UI.badge(s.balance > 0 ? "warn" : "ok", s.balance > 0 ? UI.compactMoney(s.balance) + " restant" : "À jour");
      if (s.status !== "active") foot += UI.badge(s.status);
      return '<a class="sfolder" href="eleve-dossier.html?id=' + s.id + '" aria-label="Ouvrir le dossier de ' + UI.escapeHtml(UI.fullName(s)) + '">' + status +
        '<div class="sf-scene"><div class="sf-back"></div><div class="sf-doc d1">Profil</div><div class="sf-doc d2">Scolarité</div><div class="sf-doc d3">Présence</div><div class="sf-doc d4">' + (financeVisible ? "Finance" : "Suivi") + '</div><div class="sf-front"></div>' + UI.avatar(s, 46, "sf-avatar") + "</div>" +
        '<div class="sf-name">' + UI.escapeHtml(s.first_name) + "<br>" + UI.escapeHtml(s.last_name) + '</div><div class="sf-class">' + UI.escapeHtml(s.class_name || "Classe non affectée") + '</div>' +
        '<span class="chip-code sf-code">' + UI.escapeHtml(s.code || "—") + "</span>" + (foot ? '<div class="sf-foot">' + foot + "</div>" : "") + "</a>";
    }).join("") + "</div>";
  }

  function th(key, label, cls) {
    var c = "sortable" + (sortKey === key ? " " + sortDir : "") + (cls ? " " + cls : "");
    return '<th class="' + c + '" data-sort="' + key + '">' + label + "</th>";
  }
  function renderTable(list) {
    var head = th("last_name", "Élève") + th("class_name", "Classe") + "<th>Identifiant</th><th>Aujourd'hui</th>" + (financeVisible ? th("balance", "Solde", "num") : "") + '<th class="actions"></th>';
    return '<div class="panel compact"><div class="table-wrap"><table class="data-table responsive"><thead><tr>' + head + "</tr></thead><tbody>" + list.map(function (s) {
      return '<tr class="clickable" data-href="eleve-dossier.html?id=' + s.id + '"><td data-label="Élève"><span class="cell-main">' + UI.avatar(s, 30) + UI.escapeHtml(s.last_name + " " + s.first_name) + "</span></td>" +
        '<td data-label="Classe">' + UI.escapeHtml(s.class_name || "—") + '</td><td data-label="Identifiant"><span class="chip-code">' + UI.escapeHtml(s.code || "—") + "</span></td>" +
        '<td data-label="Aujourd\'hui">' + (s.today_status ? UI.badge(s.today_status) : '<span class="muted">—</span>') + "</td>" +
        (financeVisible ? '<td data-label="Solde" class="num ' + (s.balance > 0 ? "text-warn" : "text-lime") + '">' + UI.money(s.balance) + "</td>" : "") +
        '<td class="actions">' + UI.icon("chevronRight", 16) + "</td></tr>";
    }).join("") + "</tbody></table></div></div>";
  }
  function wireSort() {
    document.querySelectorAll("th.sortable").forEach(function (h) {
      h.addEventListener("click", function () { if (sortKey === h.dataset.sort) sortDir = sortDir === "asc" ? "desc" : "asc"; else { sortKey = h.dataset.sort; sortDir = "asc"; } applyFilters(); });
    });
  }

  function openAddModal() {
    var m = UI.modal({ title: "Ajouter un élève", body:
      '<form id="addForm" class="form-grid">' +
      '<div class="field"><label for="fFirst">Prénom</label><input id="fFirst" required maxlength="100" /></div>' +
      '<div class="field"><label for="fLast">Nom</label><input id="fLast" required maxlength="100" /></div>' +
      '<div class="field"><label for="fClass">Classe</label><select id="fClass"><option value="">Non affecté</option>' + classes.map(function (c) { return '<option value="' + c.id + '">' + UI.escapeHtml(c.name) + "</option>"; }).join("") + "</select></div>" +
      '<div class="field"><label for="fGender">Genre</label><select id="fGender"><option value="">—</option><option value="F">Fille</option><option value="M">Garçon</option></select></div>' +
      '<div class="field"><label for="fBirth">Date de naissance</label><input id="fBirth" type="date" /></div>' +
      '<div class="field"><label>Identifiant</label><input value="Généré automatiquement (STU-XXXX-XXXX)" disabled /></div>' +
      '<p class="form-error full" id="addErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="addCancel">Annuler</button><button type="submit" form="addForm" class="btn btn-lime btn-sm" id="addSubmit">Créer le dossier</button>' });
    m.querySelector("#addCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#addForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#addSubmit"), err = m.querySelector("#addErr");
      err.hidden = true;
      UI.btnState(btn, "loading", "Création…");
      api.fetch("/academic-years").then(function (y) {
        var yearId = y.body[0] && y.body[0].id;
        return api.fetch("/students", { method: "POST", body: JSON.stringify({ first_name: m.querySelector("#fFirst").value.trim(), last_name: m.querySelector("#fLast").value.trim(), academic_year_id: yearId,
          class_id: m.querySelector("#fClass").value || null, gender: m.querySelector("#fGender").value || null, birth_date: m.querySelector("#fBirth").value || null }) });
      }).then(function (res) {
        if (!res.ok) { UI.btnState(btn, "error", "Réessayer"); err.textContent = res.body.error || "Impossible de créer l'élève."; err.hidden = false; return; }
        UI.btnState(btn, "success", "Créé");
        UI.toast("Dossier créé — identifiant " + res.body.code, "success");
        setTimeout(function () { UI.closeModal(); window.location.href = "eleve-dossier.html?id=" + res.body.id; }, 500);
      }).catch(function () { UI.btnState(btn, "error", "Réessayer"); err.textContent = "Le serveur Klassio est injoignable."; err.hidden = false; });
    });
  }

  document.getElementById("studentSearch").addEventListener("input", UI.debounce(applyFilters, 120));
  ["classFilter", "cycleFilter", "financeFilter", "statusFilter"].forEach(function (id) { document.getElementById(id).addEventListener("change", applyFilters); });
})();
