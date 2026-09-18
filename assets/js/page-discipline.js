// KLASSIO — Discipline. Poste de travail du Directeur des disciplines :
// aujourd'hui, incidents, signalements des enseignants, justifications,
// convocations, règles et seuils, import du règlement (Direction).
// Klassio enregistre, alerte et informe — il ne décide jamais d'une sanction.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var ctx = null, incidents = [], rules = [], students = [], overview = null, today = null;
  var reports = [], justifs = [], convs = [], thresholds = null, tabsCtl = null;

  admin.initShell("discipline").then(function (c) {
    ctx = c;
    if (c.role === "parent") { document.getElementById("disciplineContent").innerHTML = UI.emptyState("Consultez le dossier de votre enfant", "Les informations que l'établissement décide de vous communiquer figurent dans l'onglet Discipline de chaque dossier.", '<a href="eleves.html" class="btn btn-ghost btn-sm">Mes enfants</a>', "discipline"); return; }
    if (c.role === "professeur") {
      document.getElementById("pageTitle").textContent = "Suivi élèves";
      document.getElementById("pageSub").textContent = "Ce que l'établissement vous communique pour vos classes, et vos signalements au Directeur des disciplines.";
      document.getElementById("pageActions").innerHTML = '<button type="button" class="btn btn-lime btn-sm" id="newRepBtn">' + UI.icon("plus", 15) + "Signaler un fait</button>";
      document.getElementById("newRepBtn").addEventListener("click", function () { openReportModal(UI.qs("student")); });
    } else if (c.role === "directeur") {
      // La Direction arrive sur l'état de l'établissement. Ses actions le
      // disent : consulter et imprimer, pas pointer un retard au portail —
      // le pointage reste accessible, depuis l'onglet du poste de travail.
      document.getElementById("pageSub").textContent = "Vue de l'établissement : volumes, récurrences, élèves sous un seuil. Le traitement quotidien est tenu par le Directeur des disciplines.";
      document.getElementById("pageActions").innerHTML = '<a href="registres.html" class="btn btn-ghost btn-sm">' + UI.icon("print", 15) + 'Registres</a><button type="button" class="btn btn-lime btn-sm" id="newIncBtn">' + UI.icon("plus", 15) + "Enregistrer un incident</button>";
      document.getElementById("newIncBtn").addEventListener("click", function () { openIncidentModal(UI.qs("student")); });
    } else {
      document.getElementById("pageSub").textContent = "Présences, faits, points, convocations — chaque décision est humaine et tracée.";
      document.getElementById("pageActions").innerHTML = '<a href="pointage.html" class="btn btn-ghost btn-sm">' + UI.icon("clock", 15) + 'Pointage</a><a href="registres.html" class="btn btn-ghost btn-sm">' + UI.icon("print", 15) + 'Registres</a><button type="button" class="btn btn-lime btn-sm" id="newIncBtn">' + UI.icon("plus", 15) + "Enregistrer un incident</button>";
      document.getElementById("newIncBtn").addEventListener("click", function () { openIncidentModal(UI.qs("student")); });
    }
    load();
  });

  function isDD() { return ctx.role === "directeur" || ctx.role === "discipline"; }

  function load() {
    var host = document.getElementById("disciplineContent");
    host.innerHTML = '<div class="kpi-grid">' + UI.skeleton("kpi", 4) + "</div>" + UI.skeleton("row", 5);
    var calls = [api.fetch("/incidents?limit=300"), api.fetch("/students"), api.fetch("/incident-reports")];
    if (isDD()) calls.push(api.fetch("/discipline/overview"), api.fetch("/discipline/rules"), api.fetch("/discipline/today"), api.fetch("/justifications"), api.fetch("/convocations"), api.fetch("/discipline/thresholds"));
    else calls.push(null, null, null, api.fetch("/justifications"));
    Promise.all(calls.map(function (c) { return c || Promise.resolve({ ok: false, body: {} }); })).then(function (r) {
      if (!r[0].ok) return admin.loadError(host, load, "Impossible de charger le suivi");
      incidents = r[0].body; students = r[1].body || []; reports = r[2].ok ? r[2].body : [];
      overview = r[3] && r[3].ok ? r[3].body : null; rules = r[4] && r[4].ok ? r[4].body : [];
      today = r[5] && r[5].ok ? r[5].body : null; justifs = r[6] && r[6].ok ? r[6].body : [];
      convs = r[7] && r[7].ok ? r[7].body : []; thresholds = r[8] && r[8].ok ? r[8].body : null;
      render();
      if (UI.qs("new") && isDD()) { history.replaceState(null, "", "discipline.html"); openIncidentModal(UI.qs("student")); }
    }).catch(function () { admin.loadError(host, load, "Le serveur Klassio est injoignable"); });
  }

  function render() {
    var host = document.getElementById("disciplineContent");
    if (!isDD()) { host.innerHTML = teacherView(); wireCommon(); UI.wireHrefs(host); return; }
    // La Direction et le DD ne viennent pas ici pour la même chose.
    //
    // Le DD y tient son POSTE DE TRAVAIL : qui n'est pas là ce matin, quels
    // appels manquent, quels signalements attendent une qualification. Son
    // écran s'ouvre donc sur « Aujourd'hui ».
    //
    // La Direction y cherche l'ÉTAT DE L'ÉTABLISSEMENT : les volumes, ce qui
    // se répète, quelles classes concentrent les faits, qui approche d'un
    // seuil. Son écran s'ouvre sur « Vue d'ensemble ».
    //
    // Aucun onglet n'est retiré à personne : la Direction garde accès au poste
    // de travail, elle n'y atterrit simplement plus par défaut. Séparer les
    // deux vues ne veut pas dire amputer l'une d'elles.
    var estDirection = ctx.role === "directeur";
    var defs = [["aujourdhui", "Aujourd'hui", "home"], ["incidents", "Incidents", "discipline"], ["signalements", "Signalements", "inbox"], ["justifications", "Justifications", "file"], ["convocations", "Convocations", "users"], ["regles", "Règles & seuils", "settings"]];
    if (estDirection) defs.unshift(["ensemble", "Vue d'ensemble", "reports"]);
    var counts = { signalements: reports.filter(function (x) { return x.status === "pending"; }).length, justifications: justifs.filter(function (x) { return x.status === "pending"; }).length, convocations: convs.filter(function (x) { return x.status === "planned"; }).length, incidents: incidents.length };
    host.innerHTML = '<div class="tabs" id="discTabs" role="tablist">' + defs.map(function (d) { return '<button type="button" class="tab-btn" data-tab="' + d[0] + '">' + UI.icon(d[2], 15) + d[1] + (counts[d[0]] ? '<span class="cnt">' + counts[d[0]] + "</span>" : "") + "</button>"; }).join("") + "</div>" +
      '<div id="discPanels">' + defs.map(function (d) { return '<div data-tab-panel="' + d[0] + '" hidden></div>'; }).join("") + "</div>";
    defs.forEach(function (d) { document.querySelector('[data-tab-panel="' + d[0] + '"]').innerHTML = views[d[0]](); });
    tabsCtl = UI.tabs(document.getElementById("discTabs"), function (n) { history.replaceState(null, "", "discipline.html?tab=" + n); });
    var wanted = UI.qs("tab"), names = defs.map(function (d) { return d[0]; });
    tabsCtl.activate(names.indexOf(wanted) >= 0 ? wanted : (estDirection ? "ensemble" : "aujourdhui"), true);
    wireCommon(); wireDD();
    UI.wireHrefs(host);
  }

  // ---------------- Vue enseignant ----------------
  function teacherView() {
    var mine = reports;
    return '<div class="kpi-grid cols-3">' + UI.kpi("Mes signalements", String(mine.length), { icon: "inbox", sub: mine.filter(function (r) { return r.status === "pending"; }).length + " en attente du DD" }) +
      UI.kpi("Événements communiqués", String(incidents.length), { icon: "discipline" }) +
      UI.kpi("Justifications à décider", String(justifs.filter(function (j) { return j.status === "pending"; }).length), { icon: "file", tone: justifs.filter(function (j) { return j.status === "pending"; }).length ? "warn" : "" }) + "</div>" +
      '<div class="panel"><div class="panel-head"><h2>Mes signalements</h2><span class="sub">Vous décrivez, le DD qualifie et décide</span></div>' +
      (mine.length ? '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Date</th><th>Élève</th><th>Fait signalé</th><th>Statut</th><th>Suite</th></tr></thead><tbody>' + mine.map(function (r) {
        return '<tr><td data-label="Date">' + UI.fmtDate(r.occurred_at) + '</td><td data-label="Élève"><span class="cell-main">' + UI.escapeHtml(r.first_name + " " + r.last_name) + '</span><span class="cell-sub">' + UI.escapeHtml(r.class_name || "") + '</span></td><td data-label="Fait">' + UI.escapeHtml(r.description) + '</td><td data-label="Statut">' + UI.badge({ pending: "warn", qualified: "ok", dismissed: "neutral" }[r.status], { pending: "En attente", qualified: "Retenu", dismissed: "Classé" }[r.status]) + '</td><td data-label="Suite">' + UI.escapeHtml(r.handling_note || (r.handler ? "Traité par " + r.handler : "—")) + "</td></tr>";
      }).join("") + "</tbody></table></div>" : UI.emptyState("Aucun signalement", "Quand un fait mérite d'être tracé, signalez-le : le Directeur des disciplines décide de la suite et vous informe.", "", "inbox")) + "</div>" +
      justifsPanel(true) +
      '<div class="panel"><div class="panel-head"><h2>Événements communiqués pour vos classes</h2><span class="sub">Informations communicables uniquement — jamais les notes internes</span></div><div id="incTable"></div></div>';
  }

  // ---------------- Vues DD ----------------
  var views = {
    // ---- Vue institutionnelle (Direction) --------------------------------
    //
    // Ce que la Direction doit pouvoir dire après dix secondes ici : est-ce
    // que ça se dégrade, où, et qui est en train de décrocher. Pas « quel
    // signalement dois-je traiter maintenant » — c'est le métier du DD.
    //
    // Aucune interprétation n'est ajoutée aux chiffres : Klassio ne dit pas
    // qu'une classe « va mal », il dit combien de faits y ont été enregistrés.
    // La lecture appartient à l'établissement.
    ensemble: function () {
      if (!overview) return '<div class="panel">' + UI.emptyState("Vue d'ensemble indisponible", "", "", "reports") + "</div>";
      var o = overview;
      var enAttente = reports.filter(function (r) { return r.status === "pending"; }).length;
      var justifsEnAttente = justifs.filter(function (j) { return j.status === "pending"; }).length;

      // Répartition par classe, agrégée depuis les incidents déjà chargés —
      // un simple comptage d'affichage, sur des données que cet écran a le
      // droit de voir. Aucune décision d'autorisation ne se prend ici.
      var parClasse = {};
      incidents.forEach(function (i) { var n = i.class_name || "Sans classe"; parClasse[n] = (parClasse[n] || 0) + 1; });
      var lignesClasses = Object.keys(parClasse)
        .map(function (n) { return { label: n, value: parClasse[n] }; })
        .sort(function (a, b) { return b.value - a.value; }).slice(0, 12);

      // Pas de pourcentage de « tendance » ici. Comparer les 7 derniers jours à
      // une moyenne mensuelle qui CONTIENT ces mêmes jours produit un chiffre
      // circulaire : un établissement qui vient d'enregistrer ses six premiers
      // faits lisait « +330 % », comme si quelque chose se dégradait. Klassio
      // enregistre et informe, il n'interprète pas — on donne donc la part,
      // qui est un fait vérifiable, et la lecture appartient à l'école.
      var part = o.incidents_month
        ? o.incidents_week + " des " + o.incidents_month + " faits du mois"
        : "Aucun fait enregistré sur 30 jours";

      return '<div class="kpi-grid cols-4">' +
        UI.kpi("Incidents (7 jours)", String(o.incidents_week), { icon: "discipline", tone: o.incidents_week ? "warn" : "ok", sub: part }) +
        UI.kpi("Incidents (30 jours)", String(o.incidents_month), { icon: "reports" }) +
        UI.kpi("Élèves sous un seuil", String(o.students_below_threshold.length), { icon: "alert", tone: o.students_below_threshold.length ? "bad" : "ok",
          sub: o.capital ? "Capital " + o.capital + " points" : "" }) +
        UI.kpi("En attente de décision", String(enAttente + justifsEnAttente), { icon: "inbox", tone: (enAttente + justifsEnAttente) ? "warn" : "ok",
          sub: enAttente + " signalement(s) · " + justifsEnAttente + " justification(s)" }) +
        "</div>" +

        '<div class="two-col">' +
        '<div class="panel"><div class="panel-head"><h2>Ce qui se répète</h2><span class="sub">30 derniers jours</span></div>' +
        UI.barRows((o.by_category || []).map(function (c) { return { label: c.category, value: c.n }; }), { empty: "Aucun incident enregistré sur la période." }) + "</div>" +
        '<div class="panel"><div class="panel-head"><h2>Où cela se passe</h2><span class="sub">Incidents enregistrés, par classe</span></div>' +
        UI.barRows(lignesClasses, { empty: "Aucun incident enregistré." }) + "</div></div>" +

        '<div class="panel"><div class="panel-head"><h2>Élèves sous un seuil</h2><div class="row"><span class="sub">Franchir un seuil n\'est pas une sanction — c\'est un signal</span><a class="link-btn" href="discipline.html?tab=regles">Règles & seuils</a></div></div>' +
        (o.students_below_threshold.length
          ? '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Élève</th><th>Classe</th><th>Palier atteint</th><th class="num">Points restants</th></tr></thead><tbody>' +
            o.students_below_threshold.map(function (e) {
              return '<tr class="clickable" data-href="eleve-dossier.html?id=' + e.id + '&tab=discipline">' +
                '<td data-label="Élève"><span class="cell-main">' + UI.escapeHtml(e.last_name + " " + e.first_name) + '</span><span class="cell-sub">' + UI.escapeHtml(e.code || "") + "</span></td>" +
                '<td data-label="Classe">' + UI.escapeHtml(e.class_name || "—") + "</td>" +
                '<td data-label="Palier">' + (e.step ? UI.badge("bad", e.step) : '<span class="muted">—</span>') + "</td>" +
                '<td data-label="Points restants" class="num">' + UI.badge(e.remaining >= e.capital * 0.4 ? "warn" : "bad", e.remaining + " / " + e.capital) + "</td></tr>";
            }).join("") + "</tbody></table></div>"
          : UI.emptyState("Aucun élève sous un seuil", "Le capital de conduite de chaque élève reste au-dessus du premier palier configuré.", "", "check")) + "</div>" +

        '<p class="note-inline">' + UI.icon("info", 15) + "<span>Cette vue rassemble ce qui a été <strong>enregistré</strong> par le Directeur des disciplines. " +
        "Le traitement quotidien — appels manquants, signalements à qualifier, convocations du jour — se tient dans les onglets suivants.</span></p>";
    },

    aujourdhui: function () {
      if (!today) return '<div class="panel">' + UI.emptyState("Vue du jour indisponible", "", "", "calendar") + "</div>";
      var t = today;
      return '<div class="kpi-grid cols-5">' +
        UI.kpi("Appels manquants", String(t.classes_pending_roll.length), { icon: "clipboard", tone: t.classes_pending_roll.length ? "warn" : "ok" }) +
        UI.kpi("Absents", String(t.absent_today.length), { icon: "calendar", tone: t.absent_today.length ? "bad" : "ok" }) +
        UI.kpi("Retards", String(t.late_today.length), { icon: "clock", tone: t.late_today.length ? "warn" : "", href: "pointage.html" }) +
        UI.kpi("Incidents ouverts", String(t.open_incidents.length), { icon: "discipline", tone: t.open_incidents.length ? "warn" : "" }) +
        UI.kpi("Seuils atteints", String(t.alerts.length), { icon: "alert", tone: t.alerts.length ? "bad" : "ok", sub: "capital " + t.capital + " pts" }) + "</div>" +
        '<div class="two-col"><div class="panel"><div class="panel-head"><h2>Qui n\'est pas là</h2><span class="sub">' + UI.fmtDate(t.date) + "</span></div>" +
        (t.absent_today.length || t.late_today.length ? '<div class="roll-list">' + t.absent_today.map(function (s) {
          return '<div class="roll-row">' + UI.avatar(s, 32) + '<div class="roll-name"><a href="eleve-dossier.html?id=' + s.id + '&tab=presence" style="color:inherit">' + UI.escapeHtml(s.last_name + " " + s.first_name) + "</a><span>" + UI.escapeHtml(s.class_name || "") + " · " + s.absences_30d + " absence(s) sur 30 jours" + (s.note ? " · " + UI.escapeHtml(s.note) : "") + "</span></div>" + UI.badge("bad", "Absent") + "</div>";
        }).join("") + t.late_today.map(function (s) {
          return '<div class="roll-row">' + UI.avatar(s, 32) + '<div class="roll-name"><a href="eleve-dossier.html?id=' + s.id + '&tab=presence" style="color:inherit">' + UI.escapeHtml(s.last_name + " " + s.first_name) + "</a><span>" + UI.escapeHtml(s.class_name || "") + (s.source === "gate" ? " · pointé au portail" : " · signalé en classe") + "</span></div>" + UI.badge("warn", s.arrival_time || "Retard") + "</div>";
        }).join("") + "</div>" : '<p class="muted">Personne n\'est absent ni en retard pour l\'instant.</p>') + "</div>" +
        '<div class="panel"><div class="panel-head"><h2>Appels non envoyés</h2><a class="link-btn" href="classes.html">Classes</a></div>' +
        (t.classes_pending_roll.length ? '<div class="roll-list">' + t.classes_pending_roll.map(function (c) {
          return '<div class="roll-row"><span class="avatar-init soft" style="width:34px;height:34px;font-size:11px">' + UI.icon("classes", 15) + '</span><div class="roll-name"><a href="classe.html?id=' + c.id + '&tab=presence" style="color:inherit">' + UI.escapeHtml(c.name) + "</a><span>" + c.student_count + " élèves · " + (c.titulaire ? UI.escapeHtml(c.titulaire) : "sans titulaire") + '</span></div><button type="button" class="btn btn-ghost btn-xs remind" data-id="' + c.id + '">Relancer</button></div>';
        }).join("") + "</div>" : '<p class="muted">Toutes les classes de votre périmètre ont envoyé leur appel.</p>') + "</div></div>" +
        (t.alerts.length ? '<div class="panel"><div class="panel-head"><h2>Élèves ayant franchi un seuil</h2><span class="sub">Une décision humaine est attendue — Klassio ne sanctionne pas</span></div><div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Élève</th><th>Classe</th><th>Capital restant</th><th>Étape</th><th class="actions"></th></tr></thead><tbody>' + t.alerts.map(function (s) {
          return '<tr><td data-label="Élève"><a href="eleve-dossier.html?id=' + s.id + '&tab=discipline" style="color:inherit"><span class="cell-main">' + UI.escapeHtml(s.last_name + " " + s.first_name) + '</span></a></td><td data-label="Classe">' + UI.escapeHtml(s.class_name || "") + '</td><td data-label="Capital">' + UI.badge(s.remaining <= s.capital * 0.3 ? "bad" : "warn", s.remaining + " / " + s.capital) + '</td><td data-label="Étape">' + UI.escapeHtml(s.step || "—") + '</td><td class="actions"><button type="button" class="btn btn-ghost btn-xs conv-student" data-id="' + s.id + '" data-name="' + UI.escapeHtml(s.first_name + " " + s.last_name) + '">Convoquer</button></td></tr>';
        }).join("") + "</tbody></table></div></div>" : "") +
        (t.convocations.length ? '<div class="panel"><div class="panel-head"><h2>Convocations du jour</h2></div><div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Heure</th><th>Élève</th><th>Motif</th><th class="actions"></th></tr></thead><tbody>' + t.convocations.map(function (c) {
          return '<tr><td data-label="Heure">' + UI.escapeHtml(c.scheduled_time || "—") + '</td><td data-label="Élève"><span class="cell-main">' + UI.escapeHtml(c.first_name + " " + c.last_name) + '</span><span class="cell-sub">' + UI.escapeHtml(c.class_name || "") + '</span></td><td data-label="Motif">' + UI.escapeHtml(c.motif) + '</td><td class="actions"><button type="button" class="btn btn-lime btn-xs cv-st" data-id="' + c.id + '" data-status="held">Tenue</button> <button type="button" class="btn btn-ghost btn-xs cv-st" data-id="' + c.id + '" data-status="missed">Manquée</button></td></tr>';
        }).join("") + "</tbody></table></div></div>" : "");
    },

    incidents: function () {
      var classNames = {}; incidents.forEach(function (i) { if (i.class_name) classNames[i.class_name] = 1; });
      return (overview ? '<div class="kpi-grid cols-4">' + UI.kpi("Incidents (7 j)", String(overview.incidents_week), { icon: "discipline", tone: overview.incidents_week ? "warn" : "" }) + UI.kpi("Incidents (30 j)", String(overview.incidents_month)) + UI.kpi("Absents aujourd'hui", String(overview.absences_today), { icon: "calendar", tone: overview.absences_today ? "bad" : "" }) + UI.kpi("Sous un seuil", String(overview.students_below_threshold.length), { icon: "alert", tone: overview.students_below_threshold.length ? "bad" : "ok" }) + "</div>" +
        '<div class="panel"><div class="panel-head"><h2>Par catégorie</h2><span class="sub">30 derniers jours</span></div>' + UI.barRows(overview.by_category.map(function (c) { return { label: c.category, value: c.n }; }), { empty: "Aucun incident sur la période." }) + "</div>" : "") +
        '<div class="panel"><div class="toolbar" style="margin-bottom:12px"><label class="search" for="incSearch">' + UI.icon("search", 16) + '<input id="incSearch" type="search" placeholder="Rechercher un élève, un incident…" /></label><select id="incClass"><option value="">Toutes les classes</option>' + Object.keys(classNames).sort().map(function (n) { return '<option value="' + UI.escapeHtml(n) + '">' + UI.escapeHtml(n) + "</option>"; }).join("") + '</select><select id="incSev"><option value="">Toute gravité</option><option value="high">Grave</option><option value="medium">Modéré</option><option value="low">Mineur</option></select><select id="incStatus"><option value="">Tout statut</option><option value="open">Ouvert</option><option value="convocation">Convocation</option><option value="decided">Décidé</option><option value="closed">Clos</option></select><span class="count-label" id="incCount"></span></div><div id="incTable"></div></div>';
    },

    signalements: function () {
      var pending = reports.filter(function (r) { return r.status === "pending"; }), done = reports.filter(function (r) { return r.status !== "pending"; });
      return '<div class="panel"><div class="panel-head"><h2>Signalements à qualifier</h2><span class="sub">Un enseignant décrit un fait ; vous décidez s\'il devient un incident, avec ou sans points</span></div>' +
        (pending.length ? pending.map(function (r) {
          return '<div class="obligation-card"><div class="ob-head"><span class="ob-label">' + UI.escapeHtml(r.first_name + " " + r.last_name) + " — " + UI.escapeHtml(r.class_name || "") + "</span>" + UI.badge("warn", "En attente") + '</div><div class="ob-amounts">Signalé par ' + UI.escapeHtml(r.reporter) + " · faits du " + UI.fmtDate(r.occurred_at) + " · reçu " + UI.relTime(r.created_at) + '</div><p style="font-size:13.5px;margin:8px 0 0">' + UI.escapeHtml(r.description) + '</p><div class="row mt-16"><button type="button" class="btn btn-lime btn-sm qualify" data-id="' + r.id + '" data-student="' + r.student_id + '" data-desc="' + UI.escapeHtml(r.description) + '" data-date="' + r.occurred_at + '">Qualifier en incident</button><button type="button" class="btn btn-ghost btn-sm dismiss" data-id="' + r.id + '">Classer sans suite</button><a class="btn btn-ghost btn-sm" href="eleve-dossier.html?id=' + r.student_id + '&tab=discipline">Voir le dossier</a></div></div>';
        }).join("") : UI.emptyState("Aucun signalement en attente", "Les faits signalés par les enseignants arrivent ici.", "", "inbox")) + "</div>" +
        (done.length ? '<div class="panel"><div class="panel-head"><h2>Signalements traités</h2></div><div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Date</th><th>Élève</th><th>Fait</th><th>Signalé par</th><th>Décision</th></tr></thead><tbody>' + done.map(function (r) {
          return '<tr><td data-label="Date">' + UI.fmtDate(r.occurred_at) + '</td><td data-label="Élève"><span class="cell-main">' + UI.escapeHtml(r.first_name + " " + r.last_name) + '</span></td><td data-label="Fait">' + UI.escapeHtml(r.description) + '</td><td data-label="Signalé par">' + UI.escapeHtml(r.reporter) + '</td><td data-label="Décision">' + UI.badge(r.status === "qualified" ? "ok" : "neutral", r.status === "qualified" ? "Retenu" : "Classé") + (r.handling_note ? '<span class="cell-sub">' + UI.escapeHtml(r.handling_note) + "</span>" : "") + "</td></tr>";
        }).join("") + "</tbody></table></div></div>" : "");
    },

    justifications: function () { return justifsPanel(false); },

    convocations: function () {
      var planned = convs.filter(function (c) { return c.status === "planned"; }), past = convs.filter(function (c) { return c.status !== "planned"; });
      return '<div class="panel"><div class="panel-head"><h2>Convocations prévues</h2><button type="button" class="btn btn-lime btn-sm" id="newConvBtn">' + UI.icon("plus", 15) + "Convoquer</button></div>" +
        (planned.length ? '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Date</th><th>Élève</th><th>Motif</th><th>Incident lié</th><th class="actions"></th></tr></thead><tbody>' + planned.map(function (c) {
          return '<tr><td data-label="Date">' + UI.fmtDate(c.scheduled_on) + (c.scheduled_time ? " " + UI.escapeHtml(c.scheduled_time) : "") + '</td><td data-label="Élève"><a href="eleve-dossier.html?id=' + c.student_id + '&tab=discipline" style="color:inherit"><span class="cell-main">' + UI.escapeHtml(c.first_name + " " + c.last_name) + '</span></a><span class="cell-sub">' + UI.escapeHtml(c.class_name || "") + '</span></td><td data-label="Motif">' + UI.escapeHtml(c.motif) + '</td><td data-label="Incident">' + UI.escapeHtml(c.incident_title || "—") + '</td><td class="actions"><button type="button" class="btn btn-lime btn-xs cv-st" data-id="' + c.id + '" data-status="held">Tenue</button> <button type="button" class="btn btn-ghost btn-xs cv-st" data-id="' + c.id + '" data-status="missed">Manquée</button> <button type="button" class="btn btn-danger btn-xs cv-st" data-id="' + c.id + '" data-status="cancelled">Annuler</button></td></tr>';
        }).join("") + "</tbody></table></div>" : UI.emptyState("Aucune convocation prévue", "Convoquez les responsables depuis un incident, un seuil franchi ou directement ici.", "", "users")) + "</div>" +
        (past.length ? '<div class="panel"><div class="panel-head"><h2>Historique</h2></div><div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Date</th><th>Élève</th><th>Motif</th><th>Statut</th><th>Parent présent</th><th>Notes</th></tr></thead><tbody>' + past.map(function (c) {
          return '<tr><td data-label="Date">' + UI.fmtDate(c.scheduled_on) + '</td><td data-label="Élève">' + UI.escapeHtml(c.first_name + " " + c.last_name) + '</td><td data-label="Motif">' + UI.escapeHtml(c.motif) + '</td><td data-label="Statut">' + UI.badge({ held: "ok", missed: "bad", cancelled: "neutral" }[c.status], { held: "Tenue", missed: "Manquée", cancelled: "Annulée" }[c.status]) + '</td><td data-label="Parent présent">' + (c.parent_attended == null ? "—" : c.parent_attended ? "Oui" : "Non") + '</td><td data-label="Notes">' + UI.escapeHtml(c.notes || "—") + "</td></tr>";
        }).join("") + "</tbody></table></div></div>" : "");
    },

    regles: function () {
      var canEdit = ctx.role === "directeur";
      var active = rules.filter(function (r) { return r.active; });
      var th = thresholds || { capital: 100, thresholds: [], conduct_scale: [] };
      return '<div class="panel"><div class="panel-head"><h2>Capital de conduite et seuils</h2>' + (canEdit ? '<button type="button" class="btn btn-ghost btn-sm" id="editThBtn">' + UI.icon("edit", 15) + "Modifier</button>" : '<span class="sub">Fixés par la Direction</span>') + "</div>" +
        '<p class="muted" style="margin-bottom:12px">Chaque élève commence l\'année avec <strong>' + th.capital + " points</strong>. Les faits en retirent ; les corrections peuvent en rendre. Quand un élève franchit un seuil, vous êtes alerté — <strong>Klassio ne sanctionne jamais tout seul</strong>.</p>" +
        '<div class="threshold-list">' + (th.thresholds.length ? th.thresholds.map(function (t) { return '<div class="th"><strong>' + t.remaining_points + "</strong><span>" + UI.escapeHtml(t.label) + (t.action ? " — " + UI.escapeHtml(t.action) : "") + "</span></div>"; }).join("") : '<p class="muted">Aucun seuil défini.</p>') + "</div>" +
        '<div class="panel-head" style="margin-top:20px"><h2>Cotes de conduite</h2></div><div class="pill-row">' + (th.conduct_scale || []).map(function (s) { return UI.badge(s[0] >= 75 ? "ok" : s[0] >= 50 ? "warn" : "bad", s[1] + " — à partir de " + s[0] + " %"); }).join("") + "</div></div>" +
        '<div class="panel" id="rulesPanel"><div class="panel-head"><h2>Règles disciplinaires</h2>' + (canEdit ? '<div class="row"><button type="button" class="btn btn-ghost btn-sm" id="importRegBtn">' + UI.icon("upload", 15) + 'Importer le règlement</button><button type="button" class="btn btn-lime btn-sm" id="addRuleBtn">' + UI.icon("plus", 15) + "Ajouter une règle</button></div>" : '<span class="sub">Configurées par la Direction</span>') + "</div>" +
        (active.length ? '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Règle</th><th>Catégorie</th><th class="num">Points</th>' + (canEdit ? '<th class="actions"></th>' : "") + "</tr></thead><tbody>" + active.map(function (r) { return '<tr><td data-label="Règle"><span class="cell-main">' + UI.escapeHtml(r.label) + '</span></td><td data-label="Catégorie">' + UI.escapeHtml(r.category) + '</td><td data-label="Points" class="num">' + UI.badge(r.points < 0 ? "warn" : "ok", (r.points > 0 ? "+" : "") + r.points) + "</td>" + (canEdit ? '<td class="actions"><button type="button" class="btn btn-danger btn-xs del-rule" data-id="' + r.id + '">Désactiver</button></td>' : "") + "</tr>"; }).join("") + "</tbody></table></div>" : '<p class="muted">Aucune règle configurée' + (canEdit ? " — importez votre règlement intérieur ou ajoutez vos règles une par une." : ".") + "</p>") + "</div>" +
        '<div class="panel"><div class="panel-head"><h2>Registres</h2><span class="sub">Documents imprimables pour l\'inspection et les conseils</span></div><div class="row"><a class="btn btn-ghost btn-sm" href="registres.html?type=attendance">' + UI.icon("print", 15) + 'Registre de présence</a><a class="btn btn-ghost btn-sm" href="registres.html?type=discipline">' + UI.icon("print", 15) + "Registre de discipline</a></div></div>";
    },
  };

  function justifsPanel(compact) {
    var pending = justifs.filter(function (j) { return j.status === "pending"; }), done = justifs.filter(function (j) { return j.status !== "pending"; });
    return '<div class="panel"><div class="panel-head"><h2>Justifications d\'absence</h2><span class="sub">' + UI.plural(pending.length, "en attente") + '</span></div>' +
      (pending.length ? pending.map(function (j) {
        return '<div class="obligation-card"><div class="ob-head"><span class="ob-label">' + UI.escapeHtml(j.first_name + " " + j.last_name) + " — absence du " + UI.fmtDate(j.date) + "</span>" + UI.badge(j.attendance_status === "absent" ? "bad" : "neutral", j.attendance_status ? ({ absent: "Absent", late: "Retard", excused: "Excusé", present: "Présent" })[j.attendance_status] : "Sans appel") + '</div><div class="ob-amounts">' + UI.escapeHtml(j.class_name || "") + " · demandée " + UI.relTime(j.created_at) + '</div><p style="font-size:13.5px;margin:8px 0 0">' + UI.escapeHtml(j.reason) + '</p><div class="row mt-16"><button type="button" class="btn btn-lime btn-sm j-dec" data-id="' + j.id + '" data-status="accepted">Accepter</button><button type="button" class="btn btn-danger btn-sm j-dec" data-id="' + j.id + '" data-status="refused">Refuser</button>' + (j.has_attachment ? '<button type="button" class="btn btn-ghost btn-sm j-att" data-id="' + j.id + '">' + UI.icon("file", 14) + UI.escapeHtml(j.attachment_name || "Pièce jointe") + "</button>" : "") + "</div></div>";
      }).join("") : '<p class="muted">Aucune justification en attente.</p>') +
      (!compact && done.length ? '<div class="panel-head" style="margin-top:20px"><h2>Traitées</h2></div><div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Date</th><th>Élève</th><th>Motif</th><th>Décision</th><th>Réponse</th></tr></thead><tbody>' + done.map(function (j) {
        return '<tr><td data-label="Date">' + UI.fmtDate(j.date) + '</td><td data-label="Élève">' + UI.escapeHtml(j.first_name + " " + j.last_name) + '</td><td data-label="Motif">' + UI.escapeHtml(j.reason) + '</td><td data-label="Décision">' + UI.badge(j.status === "accepted" ? "ok" : "bad", j.status === "accepted" ? "Acceptée" : "Refusée") + '</td><td data-label="Réponse">' + UI.escapeHtml(j.decision_note || "—") + "</td></tr>";
      }).join("") + "</tbody></table></div>" : "") + "</div>";
  }

  // ---------------- Tableau des incidents ----------------
  function renderTable() {
    var host = document.getElementById("incTable"); if (!host) return;
    var q = (document.getElementById("incSearch") || {}).value || "", cls = (document.getElementById("incClass") || {}).value || "", sev = (document.getElementById("incSev") || {}).value || "", st = (document.getElementById("incStatus") || {}).value || "";
    q = q.trim().toLowerCase();
    var rows = incidents.filter(function (i) {
      if (cls && i.class_name !== cls) return false;
      if (sev && i.severity !== sev) return false;
      if (st && (i.status || "open") !== st) return false;
      if (!q) return true;
      return (i.first_name + " " + i.last_name + " " + i.title + " " + (i.description || "") + " " + (i.code || "")).toLowerCase().indexOf(q) !== -1;
    });
    var cnt = document.getElementById("incCount"); if (cnt) cnt.textContent = UI.plural(rows.length, "incident");
    if (!incidents.length) { host.innerHTML = UI.emptyState("Aucun incident enregistré", ctx.role === "professeur" ? "Les événements communicables concernant vos classes apparaîtront ici." : "Enregistrez un incident lorsqu'un fait doit être tracé — le titulaire et la Direction seront informés.", "", "discipline"); return; }
    if (!rows.length) { host.innerHTML = UI.emptyState("Aucun résultat", "Modifiez vos filtres.", "", "search"); return; }
    host.innerHTML = '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Date</th><th>Élève</th><th>Incident</th><th>Gravité</th><th class="num">Points</th><th>Mesure</th>' + (isDD() ? "<th>Statut</th><th>Parent</th>" : "") + '<th class="actions"></th></tr></thead><tbody>' + rows.map(function (i) {
      return '<tr><td data-label="Date">' + UI.fmtDate(i.occurred_at) + '</td><td data-label="Élève"><a href="eleve-dossier.html?id=' + i.student_id + '&tab=discipline" style="color:inherit"><span class="cell-main">' + UI.escapeHtml(i.first_name + " " + i.last_name) + '</span></a><span class="cell-sub">' + UI.escapeHtml(i.class_name || "") + '</span></td><td data-label="Incident"><span class="cell-main">' + UI.escapeHtml(i.title) + '</span><span class="cell-sub">' + UI.escapeHtml(i.category) + (i.rule_label ? " · " + UI.escapeHtml(i.rule_label) : "") + '</span></td><td data-label="Gravité">' + UI.badge(i.severity) + '</td><td data-label="Points" class="num">' + (i.points ? (i.points > 0 ? "+" : "") + i.points : "—") + '</td><td data-label="Mesure">' + UI.escapeHtml(i.action_taken || "—") + "</td>" +
        (isDD() ? '<td data-label="Statut">' + UI.badge({ open: "warn", convocation: "warn", decided: "ok", closed: "neutral" }[i.status || "open"], { open: "Ouvert", convocation: "Convocation", decided: "Décidé", closed: "Clos" }[i.status || "open"]) + '</td><td data-label="Parent">' + (i.notify_parent ? UI.badge("ok", "Informé") : UI.badge("neutral", "Non")) + "</td>" : "") +
        '<td class="actions">' + (isDD() ? '<button type="button" class="btn btn-ghost btn-xs status-inc" data-id="' + i.id + '">Suite</button> ' : "") + '<a class="link-btn" href="eleve-dossier.html?id=' + i.student_id + '&tab=discipline">Dossier</a></td></tr>';
    }).join("") + "</tbody></table></div>";
    UI.wireHrefs(host);
  }

  // ---------------- Câblage ----------------
  function wireCommon() {
    ["incSearch", "incClass", "incSev", "incStatus"].forEach(function (id) { var el = document.getElementById(id); if (el) el.addEventListener(id === "incSearch" ? "input" : "change", UI.debounce(renderTable, 100)); });
    renderTable();
    document.querySelectorAll(".j-dec").forEach(function (b) { b.addEventListener("click", function () { decideJustification(b.dataset.id, b.dataset.status); }); });
    document.querySelectorAll(".j-att").forEach(function (b) {
      b.addEventListener("click", function () {
        api.fetch("/justifications/" + b.dataset.id + "/attachment").then(function (r) {
          if (!r.ok || !r.body.file_data) return UI.toast("Pièce jointe indisponible.", "error");
          var m = UI.modal({ title: r.body.file_name || "Pièce jointe", size: "lg", body: r.body.file_data.indexOf("data:image/") === 0 ? '<img src="' + UI.escapeHtml(r.body.file_data) + '" alt="" style="max-width:100%;border-radius:12px" />' : '<iframe src="' + UI.escapeHtml(r.body.file_data) + '" style="width:100%;height:60vh;border:0;border-radius:12px"></iframe>', footer: '<button type="button" class="btn btn-ghost btn-sm" id="aClose">Fermer</button>' });
          m.querySelector("#aClose").addEventListener("click", UI.closeModal);
        });
      });
    });
  }

  function wireDD() {
    document.querySelectorAll(".remind").forEach(function (b) {
      b.addEventListener("click", function () {
        UI.btnState(b, "loading", "…");
        api.fetch("/discipline/remind-roll", { method: "POST", body: JSON.stringify({ class_id: b.dataset.id }) }).then(function (r) {
          if (!r.ok) { UI.btnState(b, "error"); return UI.toast(r.body.error || "Impossible.", "error"); }
          UI.btnState(b, "success", "Relancé"); UI.toast(r.body.notified + " enseignant(s) relancé(s).", "success");
        });
      });
    });
    document.querySelectorAll(".qualify").forEach(function (b) { b.addEventListener("click", function () { openQualifyModal(b.dataset.id, b.dataset.student, b.dataset.desc, b.dataset.date); }); });
    document.querySelectorAll(".dismiss").forEach(function (b) {
      b.addEventListener("click", function () {
        var m = UI.modal({ title: "Classer sans suite", body: '<form id="dsForm" class="form-grid"><p class="modal-text full">L\'enseignant sera informé que le signalement a été classé. Aucun point n\'est retiré.</p><div class="field full"><label for="dsNote">Motif (facultatif)</label><input id="dsNote" maxlength="300" /></div></form>',
          footer: '<button type="button" class="btn btn-ghost btn-sm" id="dsCancel">Annuler</button><button type="submit" form="dsForm" class="btn btn-lime btn-sm" id="dsSubmit">Classer</button>' });
        m.querySelector("#dsCancel").addEventListener("click", UI.closeModal);
        m.querySelector("#dsForm").addEventListener("submit", function (e) {
          e.preventDefault();
          var btn = m.querySelector("#dsSubmit"); UI.btnState(btn, "loading");
          api.fetch("/incident-reports/" + b.dataset.id + "/dismiss", { method: "POST", body: JSON.stringify({ note: m.querySelector("#dsNote").value.trim() }) }).then(function (r) {
            if (!r.ok) { UI.btnState(btn, "error"); return UI.toast(r.body.error || "Impossible.", "error"); }
            UI.btnState(btn, "success"); UI.toast("Signalement classé — l'enseignant est informé.", "success");
            setTimeout(function () { UI.closeModal(); load(); }, 500);
          });
        });
      });
    });
    document.querySelectorAll(".cv-st").forEach(function (b) {
      b.addEventListener("click", function () {
        api.fetch("/convocations/" + b.dataset.id + "/status", { method: "POST", body: JSON.stringify({ status: b.dataset.status, parent_attended: b.dataset.status === "held" }) }).then(function (r) {
          if (!r.ok) return UI.toast(r.body.error || "Impossible.", "error");
          UI.toast("Convocation mise à jour.", "success"); load();
        });
      });
    });
    document.querySelectorAll(".conv-student").forEach(function (b) { b.addEventListener("click", function () { openConvocationModal(b.dataset.id, b.dataset.name); }); });
    document.querySelectorAll(".status-inc").forEach(function (b) { b.addEventListener("click", function () { openStatusModal(b.dataset.id); }); });
    var nc = document.getElementById("newConvBtn"); if (nc) nc.addEventListener("click", function () { openConvocationModal(null, null); });
    var ar = document.getElementById("addRuleBtn"); if (ar) ar.addEventListener("click", openRuleModal);
    var ir = document.getElementById("importRegBtn"); if (ir) ir.addEventListener("click", openReglementModal);
    var et = document.getElementById("editThBtn"); if (et) et.addEventListener("click", openThresholdsModal);
    document.querySelectorAll(".del-rule").forEach(function (b) { b.addEventListener("click", function () { UI.confirm("Désactiver cette règle ?", "Les incidents passés la référençant sont conservés.", "Désactiver").then(function (ok) { if (ok) api.fetch("/discipline/rules/" + b.dataset.id, { method: "DELETE" }).then(function () { UI.toast("Règle désactivée.", "success"); load(); }); }); }); });
  }

  function decideJustification(id, status) {
    var accepted = status === "accepted";
    var m = UI.modal({ title: accepted ? "Accepter la justification" : "Refuser la justification", body: '<form id="jdForm" class="form-grid"><p class="modal-text full">' + (accepted ? "L'absence sera enregistrée comme <strong>excusée</strong> et le parent informé." : "Le parent sera informé du refus ; l'absence reste non justifiée.") + '</p><div class="field full"><label for="jdNote">Message au parent (facultatif)</label><input id="jdNote" maxlength="300" /></div></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="jdCancel">Annuler</button><button type="submit" form="jdForm" class="btn ' + (accepted ? "btn-lime" : "btn-danger") + ' btn-sm" id="jdSubmit">' + (accepted ? "Accepter" : "Refuser") + "</button>" });
    m.querySelector("#jdCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#jdForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#jdSubmit"); UI.btnState(btn, "loading");
      api.fetch("/justifications/" + id + "/decide", { method: "POST", body: JSON.stringify({ status: status, note: m.querySelector("#jdNote").value.trim() }) }).then(function (r) {
        if (!r.ok) { UI.btnState(btn, "error"); return UI.toast(r.body.error || "Impossible.", "error"); }
        UI.btnState(btn, "success"); UI.toast(accepted ? "Absence désormais justifiée." : "Justification refusée.", "success");
        setTimeout(function () { UI.closeModal(); load(); }, 500);
      });
    });
  }

  function ruleOptions() {
    return rules.filter(function (r) { return r.active; }).map(function (r) { return '<option value="' + r.id + '" data-points="' + r.points + '" data-cat="' + UI.escapeHtml(r.category) + '">' + UI.escapeHtml(r.label) + " (" + (r.points > 0 ? "+" : "") + r.points + ")</option>"; }).join("");
  }

  function openQualifyModal(reportId, studentId, description, date) {
    var m = UI.modal({ title: "Qualifier le signalement", size: "lg", body: '<form id="qForm" class="form-grid">' +
      '<p class="modal-text full">Fait signalé : « ' + UI.escapeHtml(description) + ' »</p>' +
      '<div class="field"><label for="qRule">Règle appliquée</label><select id="qRule"><option value="">Aucune (libre)</option>' + ruleOptions() + "</select></div>" +
      '<div class="field"><label for="qCat">Catégorie</label><select id="qCat"><option value="comportement">Comportement</option><option value="retard">Retard</option><option value="absence">Absence</option><option value="autre">Autre</option></select></div>' +
      '<div class="field full"><label for="qTitle">Intitulé retenu</label><input id="qTitle" required maxlength="160" value="' + UI.escapeHtml(description.slice(0, 80)) + '" /></div>' +
      '<div class="field"><label for="qSev">Gravité</label><select id="qSev"><option value="low">Mineur</option><option value="medium" selected>Modéré</option><option value="high">Grave</option></select></div>' +
      '<div class="field"><label for="qPoints">Points retirés</label><input id="qPoints" type="number" min="-100" max="100" placeholder="Ex. -5" /></div>' +
      '<div class="field full"><label for="qAction">Mesure décidée (communicable)</label><input id="qAction" maxlength="500" placeholder="Ex. Avertissement, entretien" /></div>' +
      '<div class="field full"><label for="qNote">Note interne (DD / Direction)</label><input id="qNote" maxlength="300" /></div>' +
      '<label class="check full"><input type="checkbox" id="qNotify" /> Informer le parent</label>' +
      '<div class="field full"><label for="qHandling">Retour à l\'enseignant (facultatif)</label><input id="qHandling" maxlength="300" placeholder="Ex. Merci, entretien fait avec l\'élève" /></div>' +
      '<p class="form-error full" id="qErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="qCancel">Annuler</button><button type="submit" form="qForm" class="btn btn-lime btn-sm" id="qSubmit">Enregistrer l\'incident</button>' });
    m.querySelector("#qCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#qRule").addEventListener("change", function () { var o = this.selectedOptions[0]; if (o.dataset.points) { m.querySelector("#qPoints").value = o.dataset.points; m.querySelector("#qCat").value = o.dataset.cat; } });
    m.querySelector("#qForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#qSubmit"), err = m.querySelector("#qErr"); err.hidden = true; UI.btnState(btn, "loading");
      api.fetch("/incident-reports/" + reportId + "/qualify", { method: "POST", body: JSON.stringify({
        rule_id: m.querySelector("#qRule").value || null, category: m.querySelector("#qCat").value, title: m.querySelector("#qTitle").value.trim(),
        severity: m.querySelector("#qSev").value, points: m.querySelector("#qPoints").value === "" ? null : parseInt(m.querySelector("#qPoints").value, 10),
        action_taken: m.querySelector("#qAction").value.trim(), internal_note: m.querySelector("#qNote").value.trim(),
        notify_parent: m.querySelector("#qNotify").checked, occurred_at: date, handling_note: m.querySelector("#qHandling").value.trim(),
      }) }).then(function (r) {
        if (!r.ok) { UI.btnState(btn, "error"); err.textContent = r.body.error || "Impossible."; err.hidden = false; return; }
        UI.btnState(btn, "success", "Enregistré");
        UI.toast("Incident enregistré — il reste " + r.body.balance.remaining + " points." + (r.body.crossed && r.body.crossed.length ? " Seuil franchi : " + r.body.crossed[0].label + "." : ""), r.body.crossed && r.body.crossed.length ? "error" : "success", 5000);
        setTimeout(function () { UI.closeModal(); load(); }, 600);
      });
    });
  }

  function openConvocationModal(studentId, name) {
    var picker = studentId ? '<p class="modal-text full">Élève : <strong>' + UI.escapeHtml(name || "") + "</strong></p>" :
      '<div class="field full"><label for="cvStudent">Élève</label><input id="cvStudent" list="cvDl" required placeholder="Nom, prénom ou identifiant…" autocomplete="off" /><datalist id="cvDl">' + students.map(function (s) { return '<option value="' + UI.escapeHtml(s.last_name + " " + s.first_name + " — " + (s.code || "")) + '">' + UI.escapeHtml(s.class_name || "") + "</option>"; }).join("") + "</datalist></div>";
    var m = UI.modal({ title: "Convoquer les responsables", body: '<form id="cvForm" class="form-grid">' + picker +
      '<div class="field"><label for="cvDate">Date</label><input id="cvDate" type="date" required min="' + UI.todayIso() + '" value="' + UI.todayIso() + '" /></div>' +
      '<div class="field"><label for="cvTime">Heure</label><input id="cvTime" type="time" value="09:00" /></div>' +
      '<div class="field full"><label for="cvMotif">Motif</label><input id="cvMotif" required maxlength="300" placeholder="Ex. Entretien suite aux faits du 8 septembre" /></div>' +
      '<p class="note-inline full">' + UI.icon("info", 15) + "<span>Les responsables reçoivent une notification immédiate avec la date, l'heure et le motif.</span></p><p class=\"form-error full\" id=\"cvErr\" hidden></p></form>",
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="cvCancel">Annuler</button><button type="submit" form="cvForm" class="btn btn-lime btn-sm" id="cvSubmit">Convoquer</button>' });
    m.querySelector("#cvCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#cvForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#cvSubmit"), err = m.querySelector("#cvErr"); err.hidden = true;
      var sid = studentId;
      if (!sid) {
        var val = m.querySelector("#cvStudent").value;
        var st = students.find(function (s) { return (s.last_name + " " + s.first_name + " — " + (s.code || "")) === val; });
        if (!st) { err.textContent = "Choisissez un élève dans la liste."; err.hidden = false; return; }
        sid = st.id;
      }
      UI.btnState(btn, "loading");
      api.fetch("/convocations", { method: "POST", body: JSON.stringify({ student_id: sid, scheduled_on: m.querySelector("#cvDate").value, scheduled_time: m.querySelector("#cvTime").value, motif: m.querySelector("#cvMotif").value.trim() }) }).then(function (r) {
        if (!r.ok) { UI.btnState(btn, "error"); err.textContent = r.body.error || "Impossible."; err.hidden = false; return; }
        UI.btnState(btn, "success"); UI.toast("Convocation envoyée aux responsables.", "success");
        setTimeout(function () { UI.closeModal(); load(); }, 500);
      });
    });
  }

  function openStatusModal(incidentId) {
    var inc = incidents.find(function (i) { return i.id === incidentId; }) || {};
    var m = UI.modal({ title: "Suite donnée", body: '<form id="isForm" class="form-grid"><p class="modal-text full">' + UI.escapeHtml(inc.title || "") + " — " + UI.escapeHtml((inc.first_name || "") + " " + (inc.last_name || "")) + "</p>" +
      '<div class="field"><label for="isStatus">Statut</label><select id="isStatus">' + ["open", "convocation", "decided", "closed"].map(function (s) { return '<option value="' + s + '"' + ((inc.status || "open") === s ? " selected" : "") + ">" + ({ open: "Ouvert", convocation: "Convocation", decided: "Décidé", closed: "Clos" })[s] + "</option>"; }).join("") + "</select></div>" +
      '<div class="field full"><label for="isAction">Mesure décidée (communicable)</label><input id="isAction" maxlength="500" value="' + UI.escapeHtml(inc.action_taken || "") + '" /></div><p class="form-error full" id="isErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="isCancel">Annuler</button><button type="submit" form="isForm" class="btn btn-lime btn-sm" id="isSubmit">Enregistrer</button>' });
    m.querySelector("#isCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#isForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#isSubmit"), err = m.querySelector("#isErr"); err.hidden = true; UI.btnState(btn, "loading");
      api.fetch("/incidents/" + incidentId + "/status", { method: "POST", body: JSON.stringify({ status: m.querySelector("#isStatus").value, action_taken: m.querySelector("#isAction").value.trim() }) }).then(function (r) {
        if (!r.ok) { UI.btnState(btn, "error"); err.textContent = r.body.error || "Impossible."; err.hidden = false; return; }
        UI.btnState(btn, "success"); UI.toast("Suite enregistrée.", "success");
        setTimeout(function () { UI.closeModal(); load(); }, 500);
      });
    });
  }

  function openThresholdsModal() {
    var th = thresholds || { capital: 100, thresholds: [], conduct_scale: [] };
    var rowHtml = function (t) {
      return '<div class="row th-row" style="gap:8px;margin-bottom:8px"><input type="number" class="grade-input th-pts" value="' + (t ? t.remaining_points : "") + '" style="width:80px" placeholder="pts" /><input class="th-label grow" value="' + UI.escapeHtml(t ? t.label : "") + '" placeholder="Ex. Convocation des parents" style="padding:8px 10px;border-radius:8px;border:1px solid var(--line);background:var(--surface-soft);font:inherit;font-size:13px;color:var(--ink)" /><input class="th-action grow" value="' + UI.escapeHtml(t && t.action ? t.action : "") + '" placeholder="Ce qui se passe alors" style="padding:8px 10px;border-radius:8px;border:1px solid var(--line);background:var(--surface-soft);font:inherit;font-size:13px;color:var(--ink)" /><button type="button" class="btn btn-danger btn-xs th-del">Retirer</button></div>';
    };
    var m = UI.modal({ title: "Capital et seuils", size: "lg", body: '<form id="thForm" class="form-grid">' +
      '<div class="field"><label for="thCap">Capital de points en début d\'année</label><input id="thCap" type="number" min="10" max="1000" value="' + th.capital + '" required /><span class="hint">Chaque élève démarre avec ce total.</span></div>' +
      '<div class="field full"><label>Seuils d\'alerte</label><div id="thRows">' + (th.thresholds.length ? th.thresholds.map(rowHtml).join("") : rowHtml(null)) + '</div><button type="button" class="btn btn-ghost btn-xs" id="thAdd">' + UI.icon("plus", 13) + "Ajouter un seuil</button><span class=\"hint\">Le seuil se déclenche quand il RESTE ce nombre de points. Klassio alerte ; vous décidez.</span></div>" +
      '<p class="note-inline full">' + UI.icon("info", 15) + "<span>Vous pouvez ajouter autant d'étapes que votre règlement en prévoit. Les cotes de conduite se calculent en pourcentage du capital.</span></p><p class=\"form-error full\" id=\"thErr\" hidden></p></form>",
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="thCancel">Annuler</button><button type="submit" form="thForm" class="btn btn-lime btn-sm" id="thSubmit">Enregistrer</button>' });
    m.querySelector("#thCancel").addEventListener("click", UI.closeModal);
    var wireRows = function () { m.querySelectorAll(".th-del").forEach(function (b) { b.onclick = function () { if (m.querySelectorAll(".th-row").length > 1) b.closest(".th-row").remove(); }; }); };
    wireRows();
    m.querySelector("#thAdd").addEventListener("click", function () { m.querySelector("#thRows").insertAdjacentHTML("beforeend", rowHtml(null)); wireRows(); });
    m.querySelector("#thForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#thSubmit"), err = m.querySelector("#thErr"); err.hidden = true;
      var items = Array.prototype.map.call(m.querySelectorAll(".th-row"), function (row) {
        return { remaining_points: parseInt(row.querySelector(".th-pts").value, 10), label: row.querySelector(".th-label").value.trim(), action: row.querySelector(".th-action").value.trim() };
      }).filter(function (x) { return x.label && !isNaN(x.remaining_points); });
      if (!items.length) { err.textContent = "Définissez au moins un seuil."; err.hidden = false; return; }
      UI.btnState(btn, "loading");
      api.fetch("/discipline/thresholds", { method: "PUT", body: JSON.stringify({ capital: parseInt(m.querySelector("#thCap").value, 10), thresholds: items }) }).then(function (r) {
        if (!r.ok) { UI.btnState(btn, "error"); err.textContent = r.body.error || "Impossible."; err.hidden = false; return; }
        UI.btnState(btn, "success"); UI.toast("Capital et seuils enregistrés.", "success");
        setTimeout(function () { UI.closeModal(); load(); }, 500);
      });
    });
  }

  function openReglementModal() {
    var m = UI.modal({ title: "Importer le règlement intérieur", size: "lg", body:
      '<p class="modal-text">Déposez votre règlement (PDF avec texte, ou fichier .txt). Klassio y repère les articles qui ressemblent à des règles et vous les propose — <strong>rien n\'est enregistré sans votre validation</strong>. Aucune règle n\'est inventée : chaque proposition cite votre texte.</p>' +
      '<div class="field" style="margin-top:12px"><input type="file" id="regFile" accept="application/pdf,text/plain" /></div>' +
      '<div id="regResult"></div>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="regCancel">Fermer</button><button type="button" class="btn btn-lime btn-sm" id="regAnalyze">Analyser</button>' });
    m.querySelector("#regCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#regAnalyze").addEventListener("click", function () {
      var file = m.querySelector("#regFile").files[0];
      if (!file) return UI.toast("Choisissez un fichier.", "error");
      var btn = this; UI.btnState(btn, "loading", "Lecture…");
      var fd = new FormData(); fd.append("file", file);
      api.fetch("/discipline/reglement/analyze", { method: "POST", body: fd }).then(function (r) {
        if (!r.ok) { UI.btnState(btn, "error", "Réessayer"); m.querySelector("#regResult").innerHTML = '<p class="form-error" style="display:block">' + UI.escapeHtml(r.body.error || "Lecture impossible.") + "</p>"; return; }
        UI.btnState(btn, "success", "Analysé");
        var p = r.body.proposals;
        if (!p.length) { m.querySelector("#regResult").innerHTML = '<p class="muted mt-16">Aucune règle chiffrable détectée dans ce document. Vous pouvez ajouter vos règles à la main.</p>'; return; }
        m.querySelector("#regResult").innerHTML = '<p class="muted mt-16">' + UI.plural(p.length, "règle proposée", "règles proposées") + ' — décochez ce que vous ne voulez pas, ajustez les points, puis validez.</p><div class="table-wrap" style="max-height:46vh"><table class="data-table"><thead><tr><th style="width:34px"></th><th>Règle proposée</th><th>Catégorie</th><th class="num">Points</th></tr></thead><tbody>' + p.map(function (x, i) {
          return '<tr' + (x.already_exists ? ' style="opacity:0.5"' : "") + '><td><input type="checkbox" class="reg-chk" data-i="' + i + '"' + (x.already_exists ? "" : " checked") + ' /></td><td><span class="cell-main">' + UI.escapeHtml(x.label) + '</span><span class="cell-sub">' + UI.escapeHtml(x.source.slice(0, 120)) + (x.already_exists ? " · déjà enregistrée" : "") + '</span></td><td><select class="reg-cat">' + ["retard", "absence", "comportement", "bonus", "autre"].map(function (c) { return '<option value="' + c + '"' + (x.category === c ? " selected" : "") + ">" + c + "</option>"; }).join("") + '</select></td><td class="num"><input type="number" class="grade-input reg-pts" value="' + x.points + '" style="width:70px" /></td></tr>';
        }).join("") + "</tbody></table></div>";
        var foot = m.querySelector(".modal-foot");
        if (!foot.querySelector("#regConfirm")) foot.insertAdjacentHTML("beforeend", '<button type="button" class="btn btn-lime btn-sm" id="regConfirm">Enregistrer les règles cochées</button>');
        foot.querySelector("#regConfirm").onclick = function () {
          var b2 = this;
          var rows = Array.prototype.filter.call(m.querySelectorAll("#regResult tbody tr"), function (tr) { return tr.querySelector(".reg-chk").checked; });
          if (!rows.length) return UI.toast("Cochez au moins une règle.", "error");
          UI.btnState(b2, "loading");
          var payload = rows.map(function (tr) { var i = parseInt(tr.querySelector(".reg-chk").dataset.i, 10); return { label: p[i].label, category: tr.querySelector(".reg-cat").value, points: parseInt(tr.querySelector(".reg-pts").value, 10) }; });
          api.fetch("/discipline/reglement/confirm", { method: "POST", body: JSON.stringify({ rules: payload }) }).then(function (rr) {
            if (!rr.ok) { UI.btnState(b2, "error"); return UI.toast(rr.body.error || "Impossible.", "error"); }
            UI.btnState(b2, "success"); UI.toast(rr.body.created + " règle(s) enregistrée(s).", "success");
            setTimeout(function () { UI.closeModal(); load(); }, 600);
          });
        };
      }).catch(function () { UI.btnState(btn, "error", "Réessayer"); });
    });
  }

  function openReportModal(presetStudentId) {
    if (!students.length) return UI.toast("Aucun élève dans votre périmètre.", "error");
    var preset = students.find(function (s) { return s.id === presetStudentId; });
    var m = UI.modal({ title: "Signaler un fait au Directeur des disciplines", body: '<form id="rpForm" class="form-grid"><p class="modal-text full">Vous décrivez ; le DD qualifie, décide des points et vous informe de la suite.</p>' +
      '<div class="field full"><label for="rpStudent">Élève</label><input id="rpStudent" list="rpDl" required placeholder="Nom, prénom ou identifiant…" autocomplete="off" value="' + (preset ? UI.escapeHtml(preset.last_name + " " + preset.first_name + " — " + (preset.code || "")) : "") + '" /><datalist id="rpDl">' + students.map(function (s) { return '<option value="' + UI.escapeHtml(s.last_name + " " + s.first_name + " — " + (s.code || "")) + '">' + UI.escapeHtml(s.class_name || "") + "</option>"; }).join("") + "</datalist></div>" +
      '<div class="field"><label for="rpDate">Date des faits</label><input id="rpDate" type="date" required max="' + UI.todayIso() + '" value="' + UI.todayIso() + '" /></div>' +
      '<div class="field full"><label for="rpDesc">Description</label><textarea id="rpDesc" required maxlength="1500" placeholder="Ce qui s\'est passé, où, quand, qui était présent."></textarea></div><p class="form-error full" id="rpErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="rpCancel">Annuler</button><button type="submit" form="rpForm" class="btn btn-lime btn-sm" id="rpSubmit">Envoyer</button>' });
    m.querySelector("#rpCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#rpForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#rpSubmit"), err = m.querySelector("#rpErr"); err.hidden = true;
      var val = m.querySelector("#rpStudent").value;
      var student = students.find(function (s) { return (s.last_name + " " + s.first_name + " — " + (s.code || "")) === val; });
      if (!student) { err.textContent = "Choisissez un élève dans la liste."; err.hidden = false; return; }
      UI.btnState(btn, "loading");
      api.fetch("/incident-reports", { method: "POST", body: JSON.stringify({ student_id: student.id, description: m.querySelector("#rpDesc").value.trim(), occurred_at: m.querySelector("#rpDate").value }) }).then(function (r) {
        if (!r.ok) { UI.btnState(btn, "error"); err.textContent = r.body.error || "Impossible."; err.hidden = false; return; }
        UI.btnState(btn, "success", "Envoyé"); UI.toast("Signalement transmis au Directeur des disciplines.", "success");
        setTimeout(function () { UI.closeModal(); load(); }, 600);
      });
    });
  }

  function openIncidentModal(presetStudentId) {
    if (!students.length) return UI.toast("Aucun élève dans votre périmètre.", "error");
    var preset = students.find(function (s) { return s.id === presetStudentId; });
    var m = UI.modal({ title: "Enregistrer un incident", size: "lg", body: '<form id="incForm" class="form-grid">' +
      '<div class="field full"><label for="iStudent">Élève</label><input id="iStudent" list="stDl" placeholder="Nom, prénom ou identifiant…" autocomplete="off" required value="' + (preset ? UI.escapeHtml(preset.last_name + " " + preset.first_name + " — " + (preset.code || "")) : "") + '" /><datalist id="stDl">' + students.map(function (s) { return '<option value="' + UI.escapeHtml(s.last_name + " " + s.first_name + " — " + (s.code || "")) + '">' + UI.escapeHtml(s.class_name || "") + "</option>"; }).join("") + "</datalist></div>" +
      '<div class="field"><label for="iRule">Règle appliquée</label><select id="iRule"><option value="">Aucune (libre)</option>' + ruleOptions() + "</select></div>" +
      '<div class="field"><label for="iCat">Catégorie</label><select id="iCat"><option value="comportement">Comportement</option><option value="retard">Retard</option><option value="absence">Absence</option><option value="bonus">Bonne conduite</option><option value="autre">Autre</option></select></div>' +
      '<div class="field full"><label for="iTitle">Intitulé</label><input id="iTitle" required maxlength="160" placeholder="Ex. Bagarre dans la cour" /></div>' +
      '<div class="field full"><label for="iDesc">Description / contexte</label><textarea id="iDesc" maxlength="2000"></textarea></div>' +
      '<div class="field"><label for="iSev">Gravité</label><select id="iSev"><option value="low">Mineur</option><option value="medium" selected>Modéré</option><option value="high">Grave</option></select></div>' +
      '<div class="field"><label for="iPoints">Points</label><input id="iPoints" type="number" min="-100" max="100" placeholder="Selon la règle" /></div>' +
      '<div class="field"><label for="iDate">Date</label><input id="iDate" type="date" value="' + UI.todayIso() + '" max="' + UI.todayIso() + '" required /></div>' +
      '<div class="field"><label for="iAction">Mesure décidée (communicable)</label><input id="iAction" maxlength="500" placeholder="Ex. Avertissement, entretien avec la Direction" /></div>' +
      '<div class="field full"><label for="iNote">Note interne (DD / Direction uniquement)</label><textarea id="iNote" maxlength="2000" placeholder="Jamais visible par le titulaire ni le parent"></textarea></div>' +
      '<label class="check full"><input type="checkbox" id="iNotify" /> Informer le parent (effectif seulement si l\'établissement l\'autorise dans ses réglages)</label>' +
      '<p class="form-error full" id="iErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="iCancel">Annuler</button><button type="submit" form="incForm" class="btn btn-lime btn-sm" id="iSubmit">Enregistrer l\'incident</button>' });
    m.querySelector("#iCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#iRule").addEventListener("change", function () { var o = this.selectedOptions[0]; if (o.dataset.points) { m.querySelector("#iPoints").value = o.dataset.points; m.querySelector("#iCat").value = o.dataset.cat; if (!m.querySelector("#iTitle").value) m.querySelector("#iTitle").value = o.textContent.replace(/\s*\(.*\)$/, ""); } });
    m.querySelector("#incForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#iSubmit"), err = m.querySelector("#iErr"); err.hidden = true;
      var val = m.querySelector("#iStudent").value;
      var student = students.find(function (s) { return (s.last_name + " " + s.first_name + " — " + (s.code || "")) === val; }) || students.find(function (s) { return (s.first_name + " " + s.last_name).toLowerCase() === val.toLowerCase() || (s.last_name + " " + s.first_name).toLowerCase() === val.toLowerCase() || s.code === val.trim(); });
      if (!student) { err.textContent = "Choisissez un élève dans la liste."; err.hidden = false; return; }
      UI.btnState(btn, "loading", "Enregistrement…");
      api.fetch("/incidents", { method: "POST", body: JSON.stringify({ student_id: student.id, rule_id: m.querySelector("#iRule").value || null, category: m.querySelector("#iCat").value, title: m.querySelector("#iTitle").value.trim(), description: m.querySelector("#iDesc").value.trim(), severity: m.querySelector("#iSev").value, points: m.querySelector("#iPoints").value === "" ? null : parseInt(m.querySelector("#iPoints").value, 10), occurred_at: m.querySelector("#iDate").value, action_taken: m.querySelector("#iAction").value.trim(), internal_note: m.querySelector("#iNote").value.trim(), notify_parent: m.querySelector("#iNotify").checked }) }).then(function (res) {
        if (!res.ok) { UI.btnState(btn, "error"); err.textContent = res.body.error || "Impossible d'enregistrer."; err.hidden = false; return; }
        UI.btnState(btn, "success", "Enregistré");
        UI.toast("Incident enregistré — titulaire et Direction informés." + (res.body.threshold_reached ? " Seuil atteint : une décision humaine est attendue." : ""), res.body.threshold_reached ? "error" : "success", 5000);
        setTimeout(function () { UI.closeModal(); load(); }, 600);
      }).catch(function () { UI.btnState(btn, "error"); err.textContent = "Le serveur Klassio est injoignable."; err.hidden = false; });
    });
  }

  function openRuleModal() {
    var m = UI.modal({ title: "Ajouter une règle", body: '<form id="ruleForm" class="form-grid"><div class="field full"><label for="rLabel">Libellé</label><input id="rLabel" required placeholder="Ex. Retard injustifié" /></div><div class="field"><label for="rCat">Catégorie</label><select id="rCat"><option value="retard">Retard</option><option value="absence">Absence</option><option value="comportement">Comportement</option><option value="bonus">Bonne conduite</option><option value="autre">Autre</option></select></div><div class="field"><label for="rPts">Points</label><input id="rPts" type="number" min="-100" max="100" value="-2" required /><span class="hint">Négatif pour une pénalité, positif pour un bonus.</span></div><p class="form-error full" id="rErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="rCancel">Annuler</button><button type="submit" form="ruleForm" class="btn btn-lime btn-sm" id="rSubmit">Ajouter</button>' });
    m.querySelector("#rCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#ruleForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#rSubmit"), err = m.querySelector("#rErr"); UI.btnState(btn, "loading");
      api.fetch("/discipline/rules", { method: "POST", body: JSON.stringify({ label: m.querySelector("#rLabel").value.trim(), category: m.querySelector("#rCat").value, points: parseInt(m.querySelector("#rPts").value, 10) }) }).then(function (res) {
        if (!res.ok) { UI.btnState(btn, "error"); err.textContent = res.body.error || "Erreur."; err.hidden = false; return; }
        UI.btnState(btn, "success"); UI.toast("Règle ajoutée.", "success"); setTimeout(function () { UI.closeModal(); load(); }, 400);
      });
    });
  }
})();
