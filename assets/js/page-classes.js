// KLASSIO — Classes.
//
// Deux écrans dans un fichier, parce que c'est la même adresse :
//
//   • Direction / DD : la LISTE des classes de leur périmètre, groupée par
//     cycle, avec l'ajout d'une classe pour la Direction.
//
//   • Professeur : son ACCUEIL. Il n'a pas de tableau de bord — son métier
//     commence à ses classes, et c'est ici qu'il atterrit en se connectant
//     (UI.homeFor). L'écran a donc absorbé ce que le tableau de bord lui
//     apportait vraiment : l'horaire du jour et sa file à traiter. Le reste
//     (événements disciplinaires communiqués, calendrier) vit dans les pages
//     dédiées, que son menu porte déjà — rien n'est devenu injoignable.
//
// Aucune donnée financière n'apparaît sur le chemin du professeur : ni ici, ni
// sur ses cartes de classe. Sa page de classe garde l'onglet « Situation
// financière », qui reste une décision explicite de la Direction
// (tenant_settings.teacher_sees_finance, vérifiée côté serveur par
// school.finance_visible) — cet écran-ci ne l'ouvre jamais.
//
// La liste est déjà réduite au périmètre par le backend : ce fichier n'a aucun
// filtrage de sécurité à faire, et ne doit pas faire semblant d'en avoir.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var ctx = null, classes = [];

  admin.initShell("classes").then(function (c) {
    ctx = c;
    if (c.role === "professeur") {
      document.getElementById("pageTitle").textContent = "Mes classes";
      // L'onglet du navigateur aussi : c'est la page d'arrivée du professeur,
      // souvent la seule ouverte de la journée, et « Classes » ne lui dit pas
      // qu'il est chez lui. La coquille a déjà posé le nom de l'établissement.
      document.title = "Mes classes — " + (c.tenant_name || "Klassio");
    }
    if (c.role === "discipline") { document.getElementById("pageSub").textContent = "Classes du cycle secondaire — votre périmètre."; }
    if (c.role === "directeur") {
      document.getElementById("pageActions").innerHTML =
        '<a href="eleves.html" class="btn btn-ghost btn-sm">' + UI.icon("students", 15) + "Élèves</a>" +
        '<button type="button" class="btn btn-lime btn-sm" id="addClassBtn">' + UI.icon("plus", 15) + "Ajouter une classe</button>";
      document.getElementById("addClassBtn").addEventListener("click", openAddModal);
    }
    load();
  });

  // Le professeur lit /dashboard, pas /classes : cette route lui renvoie DÉJÀ
  // ses classes (via school.teacher_class_rows — matière et titularité
  // comprises), plus l'horaire du jour et sa file à traiter. Une seule requête
  // au lieu de deux, et pas une ligne de backend ajoutée pour cet écran.
  function load() {
    document.getElementById("classesView").innerHTML = '<div class="class-grid">' + UI.skeleton("card", 6) + "</div>";
    var prof = ctx.role === "professeur";
    api.fetch(prof ? "/dashboard" : "/classes").then(function (res) {
      if (!res.ok) return admin.loadError(document.getElementById("classesView"), load, prof ? "Impossible de charger vos classes" : "Impossible de charger les classes");
      if (prof) { renderProfesseur(res.body); return; }
      classes = res.body;
      render();
    }).catch(function () { admin.loadError(document.getElementById("classesView"), load, "Le serveur Klassio est injoignable"); });
  }

  // ------------------------------------------------------------------
  // Accueil du professeur
  // ------------------------------------------------------------------
  function renderProfesseur(d) {
    var host = document.getElementById("classesView");
    var mesClasses = d.classes || [];

    if (!mesClasses.length) {
      document.getElementById("pageSub").textContent = "Aucune classe ne vous est encore rattachée.";
      host.innerHTML = UI.emptyState("Aucune classe rattachée à votre compte",
        "La Direction de l'établissement doit vous rattacher à vos classes depuis Établissement → Équipe. Vous verrez ensuite ici vos élèves, l'appel et votre horaire.",
        "", "classes");
      return;
    }

    var eleves = mesClasses.reduce(function (s, c) { return s + c.student_count; }, 0);
    var enAttente = mesClasses.filter(function (c) { return !c.attendance_today.recorded; });
    document.getElementById("pageSub").textContent =
      UI.plural(mesClasses.length, "classe") + " · " + UI.plural(eleves, "élève") +
      (enAttente.length ? " · " + UI.plural(enAttente.length, "appel à envoyer", "appels à envoyer") : " · tous les appels sont envoyés");

    // Bouton d'action : seulement quand il désigne UNE classe sans ambiguïté.
    // Avec deux appels en attente, « Faire l'appel » choisirait à sa place ;
    // les cartes ci-dessous disent déjà laquelle attend quoi.
    var actions = '<a href="ressources.html" class="btn btn-ghost btn-sm">' + UI.icon("book", 15) + "Publier un devoir</a>";
    if (enAttente.length === 1) {
      actions = '<a href="classe.html?id=' + encodeURIComponent(enAttente[0].id) + '&tab=presence" class="btn btn-lime btn-sm">' +
        UI.icon("clipboard", 15) + "Faire l'appel — " + UI.escapeHtml(enAttente[0].name) + "</a>" + actions;
    }
    document.getElementById("pageActions").innerHTML = actions;

    var aujourdhui = '<div class="panel"><div class="panel-head"><h2>Aujourd\'hui</h2><span class="sub">' + UI.WEEKDAYS[new Date().getDay() || 7] + "</span></div>" +
      ((d.today_slots || []).length
        ? d.today_slots.map(function (s) {
            return '<div class="slot"><strong>' + UI.escapeHtml(s.start_time + " – " + s.end_time + " · " + s.subject) + "</strong><span>" +
              UI.escapeHtml(s.class_name) + (s.room ? " · " + UI.escapeHtml(s.room) : "") + "</span></div>";
          }).join("")
        : '<p class="muted">Aucun cours planifié aujourd\'hui dans vos classes (l\'horaire est saisi par la Direction).</p>') + "</div>";

    var titulaire = mesClasses.some(function (c) { return c.is_titulaire; });
    var aTraiter = UI.todoPanel([
      { count: d.my_reports_pending || 0, label: "Mes signalements en attente du DD", sub: "Vous serez informé(e) de la suite donnée", href: "discipline.html", icon: "discipline", tone: "neutral" },
      // Décider d'une justification d'absence est un acte de titulaire. Un
      // professeur qui ne l'est d'aucune classe ne doit pas voir une file
      // qu'il ne peut pas traiter.
      { count: titulaire ? (d.pending_justifications || 0) : 0, label: "Justifications d'absence à décider", sub: "En tant que titulaire", href: "discipline.html", icon: "file" },
      { count: d.unread_messages || 0, label: "Messages de parents non lus", sub: "Cahier de communication", href: "messages.html", icon: "mail" },
    ], "À traiter", "Rien ne vous attend. Vos signalements, les justifications à décider et les messages des parents apparaîtront ici.");

    host.innerHTML =
      '<div class="class-grid">' + mesClasses.map(carteProf).join("") + "</div>" +
      '<div class="two-col">' + aTraiter + aujourdhui + "</div>" +
      '<p class="muted" style="margin-top:14px">Les événements disciplinaires communiqués pour vos classes sont dans <a class="link-btn" href="discipline.html">Suivi</a>, et les dates à venir dans le <a class="link-btn" href="calendrier.html">Calendrier</a>.</p>';
    UI.wireHrefs(host);
  }

  // Carte de classe vue par son enseignant : ce qu'il enseigne, combien
  // d'élèves, et si l'appel est parti. Ni titulaire (c'est souvent lui), ni
  // nombre d'enseignants, ni le moindre montant.
  function carteProf(c) {
    var at = c.attendance_today, fait = at.recorded > 0;
    return '<a class="class-card" href="classe.html?id=' + encodeURIComponent(c.id) + (fait ? "" : "&tab=presence") + '"><div class="cc-head"><h3>' + UI.escapeHtml(c.name) + "</h3>" +
      (c.is_titulaire ? UI.badge("ok", "Titulaire") : (c.subject ? UI.badge("neutral", c.subject) : "")) + "</div>" +
      '<div class="cc-meta"><span>' + UI.icon("students", 14) + UI.plural(c.student_count, "élève") + "</span><span>" + UI.icon("clipboard", 14) +
      (fait ? "Appel envoyé — " + at.absent + " absent(s), " + at.late + " retard(s)" : "Appel non envoyé") + "</span></div>" +
      '<div class="cc-foot"><span>' + (fait ? "À jour" : "En attente") + '</span><span class="link-btn">' + (fait ? "Ouvrir" : "Faire l'appel") + " " + UI.icon("chevronRight", 12) + "</span></div></a>";
  }

  // ------------------------------------------------------------------
  // Liste Direction / DD / parent
  // ------------------------------------------------------------------
  function render() {
    var host = document.getElementById("classesView");
    var total = classes.reduce(function (s, c) { return s + c.student_count; }, 0);
    var called = classes.filter(function (c) { return c.attendance_recorded_today > 0; }).length;
    document.getElementById("pageSub").textContent = UI.plural(classes.length, "classe") + " · " + UI.plural(total, "élève");
    if (!classes.length) {
      host.innerHTML = ctx.role === "directeur" ? UI.emptyState("Aucune classe", "Créez vos classes ou importez un fichier — chaque classe portera ensuite ses élèves, son titulaire, son horaire et ses présences.", '<button type="button" class="btn btn-lime btn-sm" id="emptyAdd">' + UI.icon("plus", 15) + "Ajouter une classe</button>", "classes")
        : UI.emptyState("Aucune classe dans votre périmètre", "Aucune classe n'est marquée « secondaire » — la Direction peut ajuster le cycle de chaque classe.", "", "classes");
      var b = document.getElementById("emptyAdd"); if (b) b.addEventListener("click", openAddModal);
      return;
    }
    if (classes.length > 1) {
      var k = document.getElementById("classKpis"); k.hidden = false;
      var absent = classes.reduce(function (s, c) { return s + (c.absent_today || 0); }, 0);
      k.innerHTML = UI.kpi("Classes", String(classes.length), { icon: "classes" }) + UI.kpi("Élèves", total.toLocaleString("fr-FR"), { icon: "students" }) +
        UI.kpi("Appels faits aujourd'hui", called + " / " + classes.length, { icon: "clipboard", tone: called === classes.length ? "ok" : "" }) + UI.kpi("Absents aujourd'hui", String(absent), { icon: "calendar", tone: absent ? "bad" : "ok" });
    }
    var groups = {};
    classes.forEach(function (c) { (groups[c.cycle || "autre"] = groups[c.cycle || "autre"] || []).push(c); });
    var order = ["maternelle", "primaire", "secondaire", "autre"];
    host.innerHTML = order.filter(function (g) { return groups[g]; }).map(function (g) {
      return '<div class="panel"><div class="panel-head"><h2>' + ({ maternelle: "Maternelle", primaire: "Primaire", secondaire: "Secondaire", autre: "Autres" })[g] + '</h2><span class="sub">' + UI.plural(groups[g].length, "classe") + '</span></div><div class="class-grid">' + groups[g].map(card).join("") + "</div></div>";
    }).join("");
  }

  function card(c) {
    var rec = c.attendance_recorded_today;
    // Un cycle DÉDUIT est provisoire : le signaler permet de le corriger avant
    // qu'il ne se recopie d'année en année.
    var aConfirmer = c.cycle_source === "deduit"
      ? ' <span class="badge warn" title="Cycle déduit du libellé — ouvrez la classe pour le confirmer">Cycle à confirmer</span>' : "";
    return '<a class="class-card" href="classe.html?id=' + c.id + '"><div class="cc-head"><h3>' + UI.escapeHtml(c.name) + "</h3>" + (c.is_titulaire ? UI.badge("ok", "Titulaire") : c.level ? UI.badge("neutral", c.level) : "") + aConfirmer + "</div>" +
      '<div class="cc-meta"><span>' + UI.icon("students", 14) + UI.plural(c.student_count, "élève") + "</span><span>" + UI.icon("user", 14) + (c.titulaire_name ? "Titulaire : " + UI.escapeHtml(c.titulaire_name) : "Sans titulaire") + "</span><span>" + UI.icon("clipboard", 14) + (rec ? "Appel fait — " + c.absent_today + " absent(s)" : "Appel non fait aujourd'hui") + "</span></div>" +
      '<div class="cc-foot"><span>' + UI.plural(c.teacher_count, "enseignant") + '</span><span class="link-btn">Ouvrir ' + UI.icon("chevronRight", 12) + "</span></div></a>";
  }

  function openAddModal() {
    var m = UI.modal({ title: "Ajouter une classe", body:
      '<form id="classForm" class="form-grid"><div class="field"><label for="cName">Nom</label><input id="cName" placeholder="Ex. 6e A" required maxlength="100" /></div><div class="field"><label for="cLevel">Niveau</label><input id="cLevel" placeholder="Ex. 6e" /></div>' +
      '<div class="field full"><label for="cCycle">Cycle</label><select id="cCycle"><option value="">À déduire du niveau — à confirmer ensuite</option><option value="maternelle">Maternelle</option><option value="primaire">Primaire</option><option value="secondaire">Secondaire</option></select><span class="hint">Le cycle définit le périmètre du Directeur des disciplines (secondaire). Deux systèmes coexistent en RDC : « 5e » est primaire dans l\'un, humanités dans l\'autre — le préciser ici évite une déduction approximative.</span></div><p class="form-error full" id="cErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="cCancel">Annuler</button><button type="submit" form="classForm" class="btn btn-lime btn-sm" id="cSubmit">Créer</button>' });
    m.querySelector("#cCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#classForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#cSubmit"), err = m.querySelector("#cErr");
      UI.btnState(btn, "loading", "Création…");
      api.fetch("/academic-years").then(function (y) {
        // L'ANNÉE ACTIVE, pas la première de la liste.
        //
        // `/academic-years` trie par date de création : après une rentrée, la
        // première est l'année ARCHIVÉE. La classe créée y atterrissait, donc
        // disparaissait de l'écran aussitôt créée — sans erreur, sans
        // explication. Invisible tant qu'une école n'avait qu'une année.
        var annees = (y.ok && y.body) || [];
        var active = annees.filter(function (a) { return a.is_active; })[0] || annees[annees.length - 1];
        if (!active) { UI.btnState(btn, "error"); err.textContent = "Aucune année scolaire."; err.hidden = false; return { ok: false, body: {} }; }
        return api.fetch("/classes", { method: "POST", body: JSON.stringify({ name: m.querySelector("#cName").value.trim(), level: m.querySelector("#cLevel").value.trim(), cycle: m.querySelector("#cCycle").value || undefined, academic_year_id: active.id }) });
      }).then(function (res) {
        if (!res) return;
        if (!res.ok) { UI.btnState(btn, "error"); err.textContent = res.body.error || "Erreur."; err.hidden = false; return; }
        UI.btnState(btn, "success", "Créée"); UI.toast("Classe créée.", "success");
        setTimeout(function () { UI.closeModal(); load(); }, 500);
      });
    });
  }
})();
