// KLASSIO — Établissement (Direction) : identité, structure, année scolaire
// et périodes (proclamation des résultats), équipe (titres et périmètres,
// DD adjoint), invitations sécurisées.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var ctx = null, students = [], classes = [], team = [], settings = null, dash = null, invitations = [], years = [], calendrier = null, tabsCtl = null;
  var selectedStudentIds = {}, selectedClassIds = {}, selectedCycles = { secondaire: true };
  var CYCLES = ["maternelle", "primaire", "secondaire"];

  admin.initShell("etablissement").then(function (c) {
    ctx = c;
    if (c.role !== "directeur") {
      document.getElementById("etabContent").innerHTML = UI.emptyState("Réservé à la Direction", "Cette page gère l'établissement, l'équipe et les invitations.", '<a href="' + UI.homeFor(c.role) + '" class="btn btn-ghost btn-sm">Retour à l\'accueil</a>', "lock");
      return;
    }
    document.getElementById("schoolTitle").textContent = c.tenant_name || "Établissement";
    var slug = c.branding && c.branding.slug;
    document.getElementById("pageActions").innerHTML = (slug ? '<a href="portail.html?e=' + encodeURIComponent(slug) + '" target="_blank" rel="noopener" class="btn btn-ghost btn-sm">' + UI.icon("eye", 15) + "Voir le portail</a>" : "") + '<a href="parametres.html" class="btn btn-ghost btn-sm">' + UI.icon("settings", 15) + 'Réglages</a><button type="button" class="btn btn-lime btn-sm" id="inviteBtn">' + UI.icon("users", 15) + "Inviter</button>";
    // Avant le découpage en onglets, ce bouton faisait DÉFILER jusqu'au bas
    // d'un rouleau de sept panneaux. Il ouvre maintenant la rubrique, et
    // amène le formulaire sous les yeux plutôt que la fin de la page.
    document.getElementById("inviteBtn").addEventListener("click", function () {
      if (!tabsCtl) return;
      tabsCtl.activate("equipe");
      var form = document.getElementById("invitations");
      if (form) form.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    load();
  });

  function load() {
    document.getElementById("etabKpis").innerHTML = UI.skeleton("kpi", 4);
    document.getElementById("etabTabs").innerHTML = "";
    document.getElementById("etabContent").innerHTML = UI.skeleton("card", 3);
    Promise.all([api.fetch("/dashboard"), api.fetch("/students"), api.fetch("/classes"), api.fetch("/team"), api.fetch("/settings"), api.fetch("/invitations"), api.fetch("/academic-years"), api.fetch("/academic-calendar")]).then(function (r) {
      if (!r[0].ok) return admin.loadError(document.getElementById("etabContent"), load);
      dash = r[0].body; students = r[1].body || []; classes = r[2].body || []; team = r[3].body || []; settings = r[4].body || {}; invitations = r[5].body || [];
      years = r[6].ok ? r[6].body : [];
      // `/academic-calendar` plutôt que `/periods` : c'est le serveur qui sait
      // quel jour on est et quelle période court. Le navigateur ne déduit ni
      // l'état d'une période ni la période en cours — il les affiche.
      calendrier = r[7].ok ? r[7].body : { divisions: [], current_period: null, today: null };
      document.getElementById("schoolSub").textContent = UI.plural(dash.student_count, "élève") + " · " + UI.plural(dash.class_count, "classe") + " · " + UI.plural(dash.teacher_count, "enseignant") + " · " + UI.plural(dash.parent_count, "parent connecté", "parents connectés");
      render();
    }).catch(function () { admin.loadError(document.getElementById("etabContent"), load, "Le serveur Klassio est injoignable"); });
  }

  function render() {
    var byCycle = {}, byClass = {};
    students.forEach(function (s) { if (s.status !== "active") return; byCycle[s.class_cycle || "non défini"] = (byCycle[s.class_cycle || "non défini"] || 0) + 1; byClass[s.class_id] = (byClass[s.class_id] || 0) + 1; });
    var cycleRows = Object.keys(byCycle).map(function (k) { return { label: k.charAt(0).toUpperCase() + k.slice(1), value: byCycle[k] }; }).sort(function (a, b) { return b.value - a.value; });
    var classRows = classes.map(function (c) { return { label: c.name, value: byClass[c.id] || 0, href: "classe.html?id=" + c.id }; }).sort(function (a, b) { return b.value - a.value; }).slice(0, 12);
    var staffRows = [{ label: "Direction", value: Math.max(1, team.filter(function (t) { return t.role === "directeur"; }).length) }, { label: "Enseignants", value: team.filter(function (t) { return t.role === "professeur"; }).length }, { label: "Discipline (DD)", value: team.filter(function (t) { return t.role === "discipline"; }).length }, { label: "Parents connectés", value: team.filter(function (t) { return t.role === "parent"; }).length }];
    var activeYear = years.filter(function (y) { return y.is_active; })[0] || years[years.length - 1];

    var kpis = UI.kpi("Élèves", dash.student_count.toLocaleString("fr-FR"), { icon: "students", href: "eleves.html" }) + UI.kpi("Classes", String(dash.class_count), { icon: "classes", href: "classes.html", sub: classes.filter(function (c) { return c.titulaire_name; }).length + " avec titulaire" }) +
      UI.kpi("Enseignants", String(dash.teacher_count), { icon: "users", href: "etablissement.html?tab=equipe", sub: dash.pending_invitations + " invitation(s) en attente" }) + UI.kpi("Responsables", dash.guardian_count.toLocaleString("fr-FR"), { icon: "user", sub: dash.parent_count + " avec un compte" });

    var html = '<div class="two-col"><div class="panel"><div class="panel-head"><h2>Informations générales</h2><a class="link-btn" href="parametres.html">Modifier</a></div><dl class="dl"><dt>Nom</dt><dd>' + UI.escapeHtml(ctx.tenant_name || "") + "</dd><dt>Téléphone</dt><dd>" + UI.escapeHtml(settings.school_phone || "—") + "</dd><dt>Email</dt><dd>" + UI.escapeHtml(settings.school_email || "—") + "</dd><dt>Adresse</dt><dd>" + UI.escapeHtml(settings.school_address || "—") + "</dd><dt>Devise</dt><dd>" + UI.escapeHtml(settings.currency) + "</dd><dt>Année scolaire</dt><dd>" + UI.escapeHtml(activeYear ? activeYear.label : "—") + "</dd></dl>" +
      (years.length > 1 ? '<div class="field" style="margin-top:10px"><label for="yearSel">Année active</label><select id="yearSel">' + years.map(function (y) { return '<option value="' + y.id + '"' + (y.is_active ? " selected" : "") + ">" + UI.escapeHtml(y.label) + "</option>"; }).join("") + '</select><span class="hint">L\'année active porte les inscriptions et les décisions de fin d\'année.</span></div>' : "") + "</div>" +
      '<div class="panel"><div class="panel-head"><h2>Répartition par cycle</h2></div>' + UI.barRows(cycleRows, { empty: "Aucun élève actif." }) + '<div class="panel-head" style="margin-top:18px"><h2>Personnel & accès</h2></div>' + UI.barRows(staffRows) + "</div></div>" +
      '<div class="panel"><div class="panel-head"><h2>Répartition par classe</h2><div class="row"><a class="link-btn" href="classes.html">Toutes les classes</a><a class="link-btn" href="documents.html">Documents de l\'établissement</a></div></div>' + UI.barRows(classRows, { empty: "Aucune classe." }) + "</div>";

    // Les chiffres de tête restent visibles quel que soit l'onglet : ils disent
    // l'état de l'établissement, pas celui d'une rubrique.
    document.getElementById("etabKpis").innerHTML = kpis;

    // Trois rubriques, là où il y avait un seul rouleau de sept panneaux.
    // « Équipe & accès » réunit le rôster ET les invitations : c'est un seul
    // sujet — qui a accès à cette école. Séparés, ils passaient leur temps à
    // se renvoyer l'un à l'autre (l'état vide de l'Équipe dit « invitez vos
    // enseignants »), et inviter quelqu'un puis lui affecter ses classes
    // demandait de remonter la page.
    var defs = [
      ["identite", "Identité & structure", "building", html],
      ["periodes", "Périodes & proclamation", "calendar", renderPeriods(activeYear)],
      ["equipe", "Équipe & accès", "users", renderTeam() + renderInvitations()],
    ];
    document.getElementById("etabTabs").innerHTML = defs.map(function (d) {
      var compte = d[0] === "equipe" && dash.pending_invitations ? '<span class="cnt">' + dash.pending_invitations + "</span>" : "";
      return '<button type="button" class="tab-btn" data-tab="' + d[0] + '">' + UI.icon(d[2], 15) + d[1] + compte + "</button>";
    }).join("");
    document.getElementById("etabContent").innerHTML = defs.map(function (d) {
      return '<div data-tab-panel="' + d[0] + '" hidden>' + d[3] + "</div>";
    }).join("");

    tabsCtl = UI.tabs(document.getElementById("etabTabs"), function (n) {
      history.replaceState(null, "", "etablissement.html?tab=" + n);
    });
    tabsCtl.activate(ongletDemande(defs.map(function (d) { return d[0]; })), true);

    wire();
    UI.wireHrefs(document.getElementById("etabContent"));
  }

  // Quel onglet ouvrir en arrivant.
  //
  // `?tab=` est la forme courante, mais les ancres `#invitations`, `#equipe` et
  // `#periodes` restent honorées : elles vivent dans des signets, et trois
  // écrans y pointaient encore avant ce découpage. Une ancre qui ne mène plus
  // nulle part est une fonctionnalité perdue, pas un détail cosmétique.
  var ANCRES = { "#invitations": "equipe", "#equipe": "equipe", "#periodes": "periodes" };
  function ongletDemande(noms) {
    var parAncre = ANCRES[location.hash];
    if (parAncre) return parAncre;
    var voulu = UI.qs("tab");
    return noms.indexOf(voulu) >= 0 ? voulu : noms[0];
  }
  window.addEventListener("hashchange", function () {
    var cible = ANCRES[location.hash];
    if (cible && tabsCtl) tabsCtl.activate(cible);
  });

  // ---------------- Calendrier académique : périodes, échéances, verrou ------
  //
  // Cet écran montre l'année telle que l'établissement l'a DÉCLARÉE, division
  // par division, et l'état de chaque période tel que le SERVEUR le calcule
  // (`school.period_state`). Rien n'est déduit ici : ni la période en cours,
  // ni « terminée », ni « en retard ». Le navigateur n'a pas d'horloge digne
  // de confiance pour décider qu'une période scolaire est close.

  var ETATS = {
    DRAFT:    ["neutral", "Brouillon"],
    UPCOMING: ["neutral", "À venir"],
    OPEN:     ["ok", "En cours"],
    CLOSING:  ["warn", "Saisie en cours"],
    CLOSED:   ["neutral", "Terminée"],
    LOCKED:   ["info", "Verrouillée"],
    ARCHIVED: ["neutral", "Archivée"],
  };
  function badgeEtat(p) {
    var e = ETATS[p.state] || ["neutral", p.state || "—"];
    return UI.badge(e[0], e[1]);
  }

  var LIB_DIVISION = { maternelle: "Maternelle", primaire: "Primaire", secondaire: "Secondaire" };

  // Une échéance passée n'est pas une erreur : c'est une information. On la
  // signale sans la transformer en alarme, et seulement tant qu'elle a un sens
  // (une période verrouillée n'a plus d'échéance de saisie à respecter).
  function echeance(libelle, date, aujourdhui, encoreDue) {
    if (!date) return "";
    var passee = encoreDue && aujourdhui && date < aujourdhui;
    return '<span class="ech' + (passee ? " ech-passee" : "") + '">' + UI.escapeHtml(libelle) + " : " +
      UI.fmtDate(date) + (passee ? " — dépassée" : "") + "</span>";
  }

  function ligneEcheances(p, aujourdhui) {
    var due = p.state !== "LOCKED" && p.state !== "ARCHIVED";
    var parts = [
      echeance("Saisie", p.result_entry_deadline, aujourdhui, due),
      echeance("Validation", p.validation_deadline, aujourdhui, due),
      echeance("Proclamation", p.proclamation_at, aujourdhui, due && !p.published_at),
    ].filter(Boolean);
    return parts.length ? '<div class="ech-row">' + parts.join("") + "</div>" : '<span class="muted">Aucune échéance</span>';
  }

  function lignePeriode(p, courante, aujourdhui) {
    var estCourante = courante && courante.id === p.id;
    var verrouillee = p.state === "LOCKED";
    // Trois boutons, pas cinq. Les actions courantes — modifier, proclamer,
    // verrouiller — restent des boutons ; consulter l'historique et supprimer
    // deviennent des liens. Cinq boutons par ligne écrasaient la colonne des
    // dates jusqu'à casser « 1 sept. 2026 » sur quatre lignes.
    var actions =
      '<button type="button" class="btn btn-ghost btn-xs edit-period" data-id="' + p.id + '"' + (verrouillee ? " disabled" : "") +
        (verrouillee ? ' title="Période verrouillée — rouvrez-la pour la modifier"' : "") + ">Modifier</button> " +
      '<button type="button" class="btn ' + (p.published_at ? "btn-ghost" : "btn-lime") + ' btn-xs pub-period" data-id="' + p.id +
        '" data-label="' + UI.escapeHtml(p.label) + '" data-pub="' + (p.published_at ? "1" : "0") + '">' +
        (p.published_at ? "Retirer" : "Proclamer") + "</button> " +
      (verrouillee
        ? '<button type="button" class="btn btn-ghost btn-xs reopen-period" data-id="' + p.id + '" data-label="' + UI.escapeHtml(p.label) + '">Rouvrir</button>'
        : '<button type="button" class="btn btn-ghost btn-xs lock-period" data-id="' + p.id + '" data-label="' + UI.escapeHtml(p.label) + '">Verrouiller</button>') +
      '<div class="act-liens"><button type="button" class="link-btn hist-period" data-id="' + p.id + '" data-label="' + UI.escapeHtml(p.label) + '">Historique</button>' +
      (verrouillee ? "" : ' <button type="button" class="link-btn danger del-period" data-id="' + p.id + '" data-label="' + UI.escapeHtml(p.label) + '">Supprimer</button>') + "</div>";

    return '<tr' + (estCourante ? ' class="row-courante"' : "") + '>' +
      '<td data-label="Période"><span class="cell-main">' + UI.escapeHtml(p.label) +
        (p.is_exam ? " " + UI.badge("warn", "Examen") : "") + (estCourante ? " " + UI.badge("ok", "Période en cours") : "") + "</span>" +
        '<span class="cell-sub">' + (p.division ? "Propre à " + UI.escapeHtml(LIB_DIVISION[p.division] || p.division) : "Toutes divisions") +
        " · pondération " + p.weight + "</span></td>" +
      '<td data-label="État">' + badgeEtat(p) + (p.published_at ? " " + UI.badge("ok", "Proclamée le " + UI.fmtDate(p.published_at)) : "") + "</td>" +
      '<td data-label="Dates">' + (p.starts_on
        ? '<span class="cell-main nowrap">' + UI.fmtDate(p.starts_on) + '</span><span class="cell-sub nowrap">→ ' + UI.fmtDate(p.ends_on || p.starts_on) + "</span>"
        : '<span class="muted">Non datée</span>') + "</td>" +
      '<td data-label="Échéances">' + ligneEcheances(p, aujourdhui) + "</td>" +
      '<td class="actions">' + actions + "</td></tr>";
  }

  function tablePeriodes(periodes, courante, aujourdhui) {
    return '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Période</th><th>État</th><th>Dates</th><th>Échéances</th><th class="actions"></th></tr></thead><tbody>' +
      periodes.map(function (p) { return lignePeriode(p, courante, aujourdhui); }).join("") + "</tbody></table></div>";
  }

  function renderPeriods(activeYear) {
    var cal = calendrier || { divisions: [] };
    var divisions = cal.divisions || [];
    var aucune = divisions.every(function (d) { return !d.periods.length; });
    var courante = cal.current_period;

    // Le titre ne recopie pas le libellé de l'année dans sa phrase : une école
    // qui a nommé son année « Année en cours » obtenait « Calendrier de l'année
    // Année en cours ». Le libellé va en sous-titre, où il se suffit.
    var tete = '<div class="panel-head"><h2>Calendrier de l\'année scolaire</h2>' +
      (activeYear ? '<span class="sub">' + UI.escapeHtml(activeYear.label) + "</span>" : "") + '<div class="row">' +
      (aucune ? '<button type="button" class="btn btn-ghost btn-sm" id="presetBtn">Créer les périodes standard</button>' : "") +
      '<button type="button" class="btn btn-lime btn-sm" id="addPeriodBtn">' + UI.icon("plus", 15) + "Ajouter une période</button></div></div>";

    var intro = '<p class="muted" style="margin-bottom:12px">Les enseignants saisissent les notes quand ils veulent ; <strong>les parents ne voient une période qu\'une fois proclamée</strong>. La proclamation notifie les parents concernés — et reste réversible. ' +
      'Verrouiller une période ferme sa saisie ; la rouvrir exige une raison écrite, conservée au journal.</p>' +
      (courante ? '<p class="note-inline" style="margin-bottom:14px">' + UI.icon("calendar", 15) + "<span>Période en cours au " +
        UI.fmtDate(cal.today) + " : <strong>" + UI.escapeHtml(courante.label) + "</strong>" +
        (courante.ends_on ? " — jusqu'au " + UI.fmtDate(courante.ends_on) : "") + "</span></p>" : "");

    if (aucune) {
      return '<div class="panel" id="periodes">' + tete + intro +
        UI.emptyState("Aucune période définie",
          "Créez les périodes standard (P1, P2, Examen 1er semestre, P3, P4, Examen 2e semestre) ou les vôtres. Sans période déclarée, aucun résultat ne peut être proclamé.",
          "", "calendar") + "</div>";
    }

    // Une seule division utilisée : pas de sous-titres, la table suffit. Une
    // école qui n'a que du secondaire n'a pas à lire trois en-têtes.
    var corps;
    var utiles = divisions.filter(function (d) { return d.periods.length; });
    if (utiles.length === 1) {
      corps = tablePeriodes(utiles[0].periods, utiles[0].current_period || courante, cal.today);
    } else {
      corps = utiles.map(function (d) {
        return '<div class="panel-head" style="margin-top:18px"><h2>' + UI.escapeHtml(LIB_DIVISION[d.division] || d.division) +
          '</h2><span class="sub">' + UI.plural(d.period_count, "période") +
          (d.current_period ? " · en cours : " + UI.escapeHtml(d.current_period.label) : "") + "</span></div>" +
          tablePeriodes(d.periods, d.current_period, cal.today);
      }).join("");
    }
    return '<div class="panel" id="periodes">' + tete + intro + corps + "</div>";
  }

  // ---------------- Équipe ----------------
  function renderTeam() {
    var staff = team.filter(function (t) { return t.role !== "parent"; });
    var rows = staff.map(function (t) {
      var scope = "—";
      if (t.role === "professeur") scope = t.classes && t.classes.length ? t.classes.map(function (c) { return UI.badge(c.is_titulaire ? "ok" : "neutral", c.name + (c.is_titulaire ? " · titulaire" : "")); }).join(" ") : '<span class="muted">Aucune classe — <a class="link-btn" href="classes.html">rattacher</a></span>';
      else if (t.role === "discipline") {
        var cycles = [];
        try { cycles = t.scope_cycles ? JSON.parse(t.scope_cycles) : ["secondaire"]; } catch (e) { cycles = ["secondaire"]; }
        scope = cycles.map(function (c) { return UI.badge(c, c); }).join(" ");
      }
      var contact = [t.email, t.phone].filter(Boolean).join(" · ");
      var actions = "";
      if (t.role !== "directeur") {
        actions = '<button type="button" class="btn btn-ghost btn-xs edit-member" data-uid="' + t.id + '" data-role="' + t.role + '" data-name="' + UI.escapeHtml(t.name) + '" data-title="' + UI.escapeHtml(t.title || "") + '" data-cycles="' + UI.escapeHtml(t.scope_cycles || "") + '">' + UI.icon("edit", 13) + 'Rôle</button> <button type="button" class="btn btn-ghost btn-xs reset-link" data-uid="' + t.id + '" data-name="' + UI.escapeHtml(t.name) + '">' + UI.icon("lock", 13) + "Réinitialiser</button>";
      }
      return '<tr><td data-label="Membre"><span class="cell-main">' + UI.escapeHtml(t.name) + (t.title ? " " + UI.badge("info", t.title) : "") + '</span><span class="cell-sub">' + UI.escapeHtml(contact) + '</span></td><td data-label="Rôle">' + UI.escapeHtml(UI.ROLE_LABELS[t.role] || t.role) + '</td><td data-label="Périmètre">' + scope + '</td><td data-label="Depuis">' + UI.fmtDate(t.created_at) + '</td><td class="actions">' + actions + "</td></tr>";
    }).join("");
    return '<div class="panel" id="equipe"><div class="panel-head"><h2>Équipe</h2><span class="sub">Titres (« Adjoint »), périmètre des DD par cycle, rattachements de classes. Mot de passe oublié : lien de réinitialisation 24 h, usage unique.</span></div>' + (staff.length ? '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Membre</th><th>Rôle</th><th>Périmètre</th><th>Depuis</th><th class="actions"></th></tr></thead><tbody>' + rows + "</tbody></table></div>" : '<p class="muted">Vous êtes seul(e) pour le moment — invitez vos enseignants ci-dessous.</p>') +
      '<p class="note-inline mt-16">' + UI.icon("info", 15) + "<span>Au secondaire, seuls les <strong>titulaires</strong> reçoivent un accès. En maternelle et au primaire, l'enseignant de la classe voit tout ce qui la concerne.</span></p></div>";
  }

  // ---------------- Invitations ----------------
  //
  // Une invitation ACCEPTÉE se révoque aussi, et c'est le cas qui compte : la
  // Direction a invité le mauvais parent, il a déjà accepté, il faut couper.
  // Le bouton n'était proposé que sur les invitations en attente — pour les
  // autres, il n'y avait aucun moyen de reprendre l'accès depuis l'écran.
  //
  // Rien n'est supprimé : une invitation révoquée reste dans la liste, datée,
  // avec son auteur et son motif. C'est l'historique des accès de l'école.

  function portee(inv) {
    return inv.role === "parent" ? (inv.students || []).map(function (s) { return s.first_name + " " + s.last_name; }).join(", ")
      : inv.role === "professeur" ? (inv.classes || []).map(function (c) { return c.name + (c.is_titulaire ? " (titulaire)" : ""); }).join(", ")
      : (inv.scope_cycles || []).join(", ") + (inv.title ? " · " + inv.title : "");
  }

  function ligneInvitation(inv) {
    var actif = inv.status === "pending" || inv.status === "accepted";
    var libelle = inv.status === "accepted" ? "Révoquer l'accès" : "Révoquer";
    var sousTitre = inv.status === "accepted" && inv.accepted_name
      ? "Accepté par " + inv.accepted_name + (inv.accepted_at ? " le " + UI.fmtDate(inv.accepted_at) : "")
      : inv.status === "revoked" && inv.revoked_at
        ? "Révoquée le " + UI.fmtDate(inv.revoked_at) + (inv.revoked_by_name ? " par " + inv.revoked_by_name : "") +
          (inv.revoked_reason ? " — " + inv.revoked_reason : "")
        : portee(inv);
    return '<tr><td data-label="Type">' + UI.escapeHtml(UI.ROLE_LABELS[inv.role] || inv.role) + "</td>" +
      '<td data-label="Repère"><span class="cell-main">' + UI.escapeHtml(inv.label || "—") + '</span><span class="cell-sub">' + UI.escapeHtml(sousTitre) + "</span></td>" +
      '<td data-label="Statut">' + UI.badge(inv.status) + "</td>" +
      '<td data-label="Créée le">' + UI.fmtDate(inv.created_at) + "</td>" +
      '<td class="actions">' + (actif
        ? '<button type="button" class="btn btn-danger btn-xs" data-revoke="' + inv.id +
          '" data-etat="' + inv.status + '" data-qui="' + UI.escapeHtml(inv.accepted_name || inv.label || "") +
          '" data-role="' + UI.escapeHtml(UI.ROLE_LABELS[inv.role] || inv.role) + '">' + libelle + "</button>"
        : "") + "</td></tr>";
  }

  function tableInvitations(lignes, vide) {
    if (!lignes.length) return '<p class="muted">' + UI.escapeHtml(vide) + "</p>";
    return '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Type</th><th>Repère / périmètre</th><th>Statut</th><th>Créée le</th><th class="actions"></th></tr></thead><tbody>' +
      lignes.map(ligneInvitation).join("") + "</tbody></table></div>";
  }

  function renderInvitations() {
    var actives = invitations.filter(function (i) { return i.status === "pending" || i.status === "accepted"; });
    var closes = invitations.filter(function (i) { return i.status === "revoked" || i.status === "expired"; });
    var list = tableInvitations(actives, "Aucune invitation en cours.") +
      (closes.length
        ? '<details class="inv-historique"><summary>' + UI.plural(closes.length, "invitation révoquée ou expirée", "invitations révoquées ou expirées") +
          "</summary>" + tableInvitations(closes, "") + "</details>"
        : "");
    return '<div class="panel" id="invitations"><div class="panel-head"><h2>Inviter un professeur, un DD ou un parent</h2><span class="sub">Personne ne crée de compte librement — tout accès vient d\'ici. Lien unique, 7 jours, révocable.</span></div>' +
      '<div class="form-grid"><div class="field"><label for="inviteRole">Type de compte</label><select id="inviteRole"><option value="professeur">Professeur / enseignant</option><option value="discipline">Directeur des disciplines</option><option value="parent">Parent</option></select></div>' +
      '<div class="field"><label for="inviteLabel">Repère (facultatif)</label><input id="inviteLabel" placeholder="Ex. M. Kabongo — Mathématiques" /></div>' +
      '<div class="field full" id="teacherPicker"><label>Classes à rattacher</label><div class="chips" id="classChips">' + classes.map(function (c) { return '<button type="button" class="chip" data-cid="' + c.id + '">' + UI.escapeHtml(c.name) + "</button>"; }).join("") + (classes.length ? "" : '<span class="muted">Créez d\'abord des classes.</span>') + '</div><div class="field" style="margin-top:10px"><label for="titClass">Titulaire de</label><select id="titClass"><option value="">Aucune classe</option>' + classes.map(function (c) { return '<option value="' + c.id + '">' + UI.escapeHtml(c.name) + (c.titulaire_name ? " (actuellement " + UI.escapeHtml(c.titulaire_name) + ")" : "") + "</option>"; }).join("") + '</select><span class="hint">Au secondaire, seul le titulaire obtient un accès à la classe.</span></div></div>' +
      '<div class="field full" id="ddPicker" hidden><label>Périmètre du Directeur des disciplines</label><div class="chips" id="cycleChips">' + CYCLES.map(function (c) { return '<button type="button" class="chip' + (selectedCycles[c] ? " active" : "") + '" data-cycle="' + c + '">' + c.charAt(0).toUpperCase() + c.slice(1) + "</button>"; }).join("") + '</div><div class="field" style="margin-top:10px"><label for="ddTitle">Titre</label><input id="ddTitle" maxlength="60" placeholder="Ex. Adjoint" /><span class="hint">Un DD adjoint a exactement la même interface, limitée aux cycles cochés.</span></div></div>' +
      '<div class="field full" id="parentPicker" hidden><label for="studentSearchInvite">Enfant(s) concerné(s)</label><input id="studentSearchInvite" placeholder="Rechercher un élève par nom ou identifiant…" autocomplete="off" /><div id="studentCheckList" style="max-height:220px;overflow-y:auto;border:1px solid var(--line);border-radius:12px;padding:8px 12px;font-size:13.5px;margin-top:8px"></div></div>' +
      '<div class="full row between"><p class="form-msg" id="inviteMsg"></p><button type="button" class="btn btn-lime btn-sm" id="createInviteBtn">' + UI.icon("users", 15) + "Générer l'invitation</button></div></div>" +
      '<div class="panel" id="linkResultPanel" hidden style="margin-top:16px;background:var(--surface-soft)"><div class="panel-head"><h2>Invitation créée</h2></div><p class="muted" style="margin-bottom:10px">Ce lien est valable 7 jours et ne peut être utilisé qu\'une seule fois. Partagez-le uniquement avec la personne concernée.</p><div class="row"><input type="text" id="linkOutput" readonly style="flex:2;min-width:220px;font-size:12.5px;background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:10px 12px;font-family:inherit;color:var(--ink)" /><button class="btn btn-ghost btn-sm" id="copyLinkBtn" type="button">Copier</button><a class="btn btn-ghost btn-sm" id="whatsappShareBtn" href="#" target="_blank" rel="noopener">Partager via WhatsApp</a></div></div>' +
      '<div class="panel-head" style="margin-top:22px"><h2>Invitations envoyées</h2></div>' + list + "</div>";
  }

  function wire() {
    // --- Année scolaire ---
    var ys = document.getElementById("yearSel");
    if (ys) ys.addEventListener("change", function () {
      var id = this.value;
      UI.confirm("Changer l'année active ?", "Les nouvelles inscriptions, obligations et décisions porteront sur cette année.", "Activer").then(function (ok) {
        if (!ok) { load(); return; }
        api.fetch("/academic-years/" + id + "/activate", { method: "POST" }).then(function (r) {
          if (!r.ok) return UI.toast(r.body.error || "Impossible.", "error");
          UI.toast("Année active mise à jour.", "success"); load();
        });
      });
    });

    // --- Périodes ---
    var pb = document.getElementById("presetBtn");
    if (pb) pb.addEventListener("click", function () {
      var btn = this; UI.btnState(btn, "loading");
      api.fetch("/periods", { method: "POST", body: JSON.stringify({ preset: "standard" }) }).then(function (r) {
        if (!r.ok) { UI.btnState(btn, "error"); return UI.toast(r.body.error || "Impossible.", "error"); }
        UI.btnState(btn, "success"); UI.toast(r.body.created + " période(s) créée(s).", "success"); load();
      });
    });
    var ap = document.getElementById("addPeriodBtn"); if (ap) ap.addEventListener("click", function () { openPeriodModal(null); });
    document.querySelectorAll(".edit-period").forEach(function (b) {
      b.addEventListener("click", function () { openPeriodModal(trouverPeriode(b.dataset.id)); });
    });
    document.querySelectorAll(".pub-period").forEach(function (b) {
      b.addEventListener("click", function () {
        if (b.dataset.pub === "1") {
          // Retirer ne demande pas d'aperçu : on ne calcule pas une audience
          // pour lui ôter quelque chose, on la retire à qui l'avait.
          UI.confirm("Retirer la proclamation ?", "Les parents ne verront plus les résultats de cette période. Les résultats eux-mêmes ne sont pas effacés.", "Retirer").then(function (ok) {
            if (!ok) return;
            api.fetch("/periods/" + b.dataset.id + "/publish", { method: "POST", body: JSON.stringify({ unpublish: true }) }).then(function (r) {
              if (!r.ok) return UI.toast(r.body.error || "Impossible.", "error");
              UI.toast("Proclamation retirée.", "success"); load();
            });
          });
          return;
        }
        openPublishModal(b.dataset.id, b.dataset.label);
      });
    });
    document.querySelectorAll(".lock-period").forEach(function (b) {
      b.addEventListener("click", function () {
        UI.confirm("Verrouiller « " + b.dataset.label + " » ?", "La saisie des résultats de cette période sera fermée. La rouvrir ensuite exigera une raison écrite, conservée au journal d'audit.", "Verrouiller").then(function (ok) {
          if (!ok) return;
          api.fetch("/periods/" + b.dataset.id + "/lock", { method: "POST", body: JSON.stringify({}) }).then(function (r) {
            if (!r.ok) return UI.toast(r.body.error || "Impossible.", "error");
            UI.toast("Période verrouillée.", "success"); load();
          });
        });
      });
    });
    document.querySelectorAll(".reopen-period").forEach(function (b) {
      b.addEventListener("click", function () { openReopenModal(b.dataset.id, b.dataset.label); });
    });
    document.querySelectorAll(".hist-period").forEach(function (b) {
      b.addEventListener("click", function () { openHistoriqueModal(b.dataset.id, b.dataset.label); });
    });
    document.querySelectorAll(".del-period").forEach(function (b) {
      b.addEventListener("click", function () {
        UI.confirm("Supprimer « " + b.dataset.label + " » ?", "Impossible si des notes y sont déjà rattachées.", "Supprimer").then(function (ok) {
          if (!ok) return;
          api.fetch("/periods/" + b.dataset.id, { method: "DELETE" }).then(function (r) {
            if (!r.ok) return UI.toast(r.body.error || "Impossible.", "error");
            UI.toast("Période supprimée.", "success"); load();
          });
        });
      });
    });

    // --- Équipe ---
    document.querySelectorAll(".edit-member").forEach(function (b) { b.addEventListener("click", function () { openMemberModal(b.dataset); }); });
    document.querySelectorAll(".reset-link").forEach(function (b) {
      b.addEventListener("click", function () {
        UI.confirm("Générer un lien de réinitialisation ?", "Pour " + b.dataset.name + ". Le lien est valable 24 h, à usage unique, et déconnecte ses sessions actuelles dès utilisation. Envoyez-le uniquement à la personne concernée.", "Générer").then(function (ok) {
          if (!ok) return;
          api.fetch("/team/" + b.dataset.uid + "/reset-link", { method: "POST" }).then(function (res) {
            if (!res.ok) return UI.toast(res.body.error || "Impossible de générer le lien.", "error");
            var link = window.location.origin + "/app/portail.html?reset=" + encodeURIComponent(res.body.token);
            var m = UI.modal({ title: "Lien de réinitialisation — " + res.body.name, body: '<p class="modal-text" style="margin-bottom:10px">Valable 24 h, utilisable une seule fois.</p><input type="text" id="rlOut" readonly value="' + UI.escapeHtml(link) + '" style="width:100%;font-size:12.5px;background:var(--surface-soft);border:1px solid var(--line);border-radius:10px;padding:10px 12px;font-family:inherit;color:var(--ink)" />',
              footer: '<button type="button" class="btn btn-ghost btn-sm" id="rlCopy">Copier</button><a class="btn btn-lime btn-sm" href="https://wa.me/?text=' + encodeURIComponent("Bonjour " + res.body.name + ", voici votre lien pour choisir un nouveau mot de passe Klassio (valable 24 h) : " + link) + '" target="_blank" rel="noopener">Partager via WhatsApp</a>' });
            m.querySelector("#rlCopy").addEventListener("click", function () { var i = m.querySelector("#rlOut"); i.select(); (navigator.clipboard ? navigator.clipboard.writeText(i.value) : Promise.reject()).then(function () { UI.btnState(m.querySelector("#rlCopy"), "success", "Copié"); }, function () { document.execCommand("copy"); }); });
          });
        });
      });
    });

    wireInvitations();
  }

  // Câblage du seul bloc invitations, isolé parce qu'il est le seul rebranché
  // après la création d'une invitation.
  //
  // Auparavant `createInvitation` rappelait `wire()` en entier pour rafraîchir
  // ce bloc. Mesuré : chaque invitation créée ajoutait **un écouteur de plus**
  // sur `#addPeriodBtn`, `.reset-link` et `.edit-member`, nœuds déjà branchés
  // au premier rendu — donc N+1 écouteurs après N invitations.
  //
  // Aucun symptôme visible aujourd'hui, et il faut dire pourquoi : deux filets
  // indépendants l'absorbent. `UI.modal` commence par `closeModal()`, donc un
  // double déclenchement n'empile pas deux boîtes ; et le seul gestionnaire
  // sans modale, le préréglage des périodes, tape sur une route idempotente
  // par libellé (`api_academics.create_period`, branche `preset`). Le défaut
  // est donc latent, pas inoffensif par nature : le jour où l'on ajoute ici un
  // gestionnaire sans confirmation et sans idempotence côté serveur, il tire.
  // On rebranche ce qu'on redessine, rien d'autre.
  function wireInvitations() {
    var roleSel = document.getElementById("inviteRole");
    function syncRole() {
      document.getElementById("teacherPicker").hidden = roleSel.value !== "professeur";
      document.getElementById("parentPicker").hidden = roleSel.value !== "parent";
      document.getElementById("ddPicker").hidden = roleSel.value !== "discipline";
      if (roleSel.value === "parent") renderStudentList("");
    }
    roleSel.addEventListener("change", syncRole); syncRole();
    document.querySelectorAll("#classChips .chip").forEach(function (ch) { ch.addEventListener("click", function () { ch.classList.toggle("active"); if (ch.classList.contains("active")) selectedClassIds[ch.dataset.cid] = true; else delete selectedClassIds[ch.dataset.cid]; }); });
    document.querySelectorAll("#cycleChips .chip").forEach(function (ch) { ch.addEventListener("click", function () { ch.classList.toggle("active"); if (ch.classList.contains("active")) selectedCycles[ch.dataset.cycle] = true; else delete selectedCycles[ch.dataset.cycle]; }); });
    document.getElementById("studentSearchInvite").addEventListener("input", UI.debounce(function () { renderStudentList(this.value.trim().toLowerCase()); }, 120));
    document.getElementById("createInviteBtn").addEventListener("click", createInvitation);
    document.getElementById("copyLinkBtn").addEventListener("click", function () {
      var input = document.getElementById("linkOutput"); input.select();
      var self = this;
      (navigator.clipboard ? navigator.clipboard.writeText(input.value) : Promise.reject()).then(function () { UI.btnState(self, "success", "Copié"); }, function () { document.execCommand("copy"); UI.btnState(self, "success", "Copié"); });
    });
    document.querySelectorAll("[data-revoke]").forEach(function (b) {
      b.addEventListener("click", function () { openRevocationModal(b.dataset); });
    });
  }

  // Toutes les périodes de l'année, divisions confondues et sans doublon : le
  // calendrier les renvoie une fois par division quand elles sont communes.
  function toutesPeriodes() {
    var vues = {}, out = [];
    ((calendrier && calendrier.divisions) || []).forEach(function (d) {
      d.periods.forEach(function (p) { if (!vues[p.id]) { vues[p.id] = 1; out.push(p); } });
    });
    return out;
  }
  function trouverPeriode(id) {
    return toutesPeriodes().filter(function (p) { return p.id === id; })[0] || null;
  }

  function champDate(id, libelle, valeur, aide) {
    return '<div class="field"><label for="' + id + '">' + UI.escapeHtml(libelle) + '</label><input id="' + id + '" type="date" value="' + UI.escapeHtml(valeur || "") + '" />' +
      (aide ? '<span class="hint">' + UI.escapeHtml(aide) + "</span>" : "") + "</div>";
  }

  // Création ET modification. Les échéances sont ici et pas ailleurs : ce sont
  // des propriétés de la période, et le serveur refuse déjà tout calendrier
  // incohérent (`_valider_dates`) — l'écran n'a pas à redire cette règle, il
  // doit en revanche montrer son message d'erreur tel quel.
  // Révoquer un accès n'est pas « supprimer une ligne ». On dit donc exactement
  // ce qui se passe, et ce qui NE se passe PAS — parce que la crainte
  // légitime d'une Direction, c'est de perdre le dossier de l'élève en coupant
  // l'accès du parent.
  function openRevocationModal(d) {
    var accepte = d.etat === "accepted";
    var qui = d.qui || "cette personne";
    var m = UI.modal({
      title: accepte ? "Révoquer l'accès ?" : "Révoquer cette invitation ?",
      body: '<form id="revForm" class="form-grid">' +
        '<p class="modal-text full">' + (accepte
          ? "<strong>" + UI.escapeHtml(qui) + "</strong> (" + UI.escapeHtml(d.role || "") + ") perdra immédiatement l'accès à Klassio pour cet établissement. Les sessions ouvertes seront fermées, et la reconnexion sera impossible."
          : "Le lien d'invitation cessera immédiatement de fonctionner. Personne ne pourra plus créer de compte avec.") + "</p>" +
        (accepte
          ? '<p class="note-inline full">' + UI.icon("info", 15) +
            "<span><strong>Rien n'est supprimé.</strong> Les élèves, leurs dossiers, leurs résultats, leurs paiements et leurs reçus restent intacts. Vous coupez un accès, pas une histoire.</span></p>"
          : "") +
        '<div class="field full"><label for="revRaison">Motif (facultatif)</label>' +
        '<input id="revRaison" maxlength="400" placeholder="Ex. Invitation envoyée au mauvais parent." />' +
        '<span class="hint">Conservé au journal, avec votre nom et la date.</span></div>' +
        '<p class="form-error full" id="revErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="revCancel">Annuler</button>' +
              '<button type="submit" form="revForm" class="btn btn-danger btn-sm" id="revGo">' +
              (accepte ? "Révoquer l'accès" : "Révoquer") + "</button>"
    });
    m.querySelector("#revCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#revForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#revGo"), err = m.querySelector("#revErr");
      err.hidden = true;
      UI.btnState(btn, "loading", "Révocation…");
      api.fetch("/invitations/" + d.revoke + "/revoke", { method: "POST", body: JSON.stringify({
        reason: m.querySelector("#revRaison").value.trim() || undefined,
      }) }).then(function (res) {
        if (!res.ok) {
          UI.btnState(btn, "error");
          err.textContent = res.body.error || "Révocation impossible.";
          err.hidden = false;
          return;
        }
        UI.btnState(btn, "success", "Révoqué");
        // On annonce ce que le SERVEUR a fait, pas ce qu'on espérait.
        UI.toast(res.body.access_revoked
          ? "Accès révoqué" + (res.body.person ? " — " + res.body.person : "") + " ne peut plus se connecter."
          : "Invitation révoquée — le lien ne fonctionne plus.", "success", 5000);
        setTimeout(function () { UI.closeModal(); load(); }, 500);
      }).catch(function () {
        UI.btnState(btn, "error");
        err.textContent = "Le serveur Klassio est injoignable.";
        err.hidden = false;
      });
    });
  }

  function openPeriodModal(periode) {
    var edition = !!periode;
    var p = periode || {};
    var m = UI.modal({
      title: edition ? "Modifier « " + (p.label || "") + " »" : "Ajouter une période",
      body: '<form id="pForm" class="form-grid">' +
        '<div class="field full"><label for="pLabel">Libellé</label><input id="pLabel" required maxlength="40" placeholder="Ex. Période 5" value="' + UI.escapeHtml(p.label || "") + '" /></div>' +
        '<div class="field"><label for="pDivision">Division</label><select id="pDivision"><option value="">Toutes les divisions</option>' +
          CYCLES.map(function (c) { return '<option value="' + c + '"' + (p.division === c ? " selected" : "") + ">" + (LIB_DIVISION[c] || c) + "</option>"; }).join("") +
          '</select><span class="hint">Une période propre à une division remplace la période commune de même libellé.</span></div>' +
        '<div class="field"><label for="pState">État</label><select id="pState">' +
          [["DRAFT", "Brouillon — non proclamable"], ["READY", "Active"], ["ARCHIVED", "Archivée"]].map(function (o) {
            var courant = (p.admin_state || "READY").toUpperCase();
            return '<option value="' + o[0] + '"' + (courant === o[0] ? " selected" : "") + ">" + o[1] + "</option>";
          }).join("") + '</select><span class="hint">Le verrouillage ne passe pas par ici.</span></div>' +
        champDate("pStart", "Début", p.starts_on) + champDate("pEnd", "Fin", p.ends_on) +
        champDate("pDeadline", "Échéance de saisie", p.result_entry_deadline, "Date limite pour saisir les résultats.") +
        champDate("pValid", "Échéance de validation", p.validation_deadline, "Après la saisie, avant la proclamation.") +
        champDate("pProc", "Proclamation prévue", p.proclamation_at, "Indicatif : proclamer reste une décision.") +
        '<div class="field"><label for="pWeight">Pondération</label><input id="pWeight" type="number" step="0.5" min="0.5" max="10" value="' + (p.weight != null ? p.weight : 1) + '" /><span class="hint">Un examen pèse souvent 2.</span></div>' +
        '<div class="field"><label for="pSort">Ordre</label><input id="pSort" type="number" min="0" max="50" value="' + (p.sort != null ? p.sort : toutesPeriodes().length) + '" /></div>' +
        '<label class="check full"><input type="checkbox" id="pExam"' + (p.is_exam ? " checked" : "") + " /> C'est une session d'examen</label>" +
        '<p class="form-error full" id="pErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="pCancel">Annuler</button><button type="submit" form="pForm" class="btn btn-lime btn-sm" id="pSubmit">' + (edition ? "Enregistrer" : "Ajouter") + "</button>"
    });
    m.querySelector("#pCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#pForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#pSubmit"), err = m.querySelector("#pErr"); err.hidden = true; UI.btnState(btn, "loading");
      // `null` et non `undefined` : c'est ainsi qu'on EFFACE une échéance. Un
      // champ absent du corps n'est pas modifié côté serveur.
      var corps = {
        label: m.querySelector("#pLabel").value.trim(),
        division: m.querySelector("#pDivision").value || null,
        admin_state: m.querySelector("#pState").value,
        starts_on: m.querySelector("#pStart").value || null,
        ends_on: m.querySelector("#pEnd").value || null,
        result_entry_deadline: m.querySelector("#pDeadline").value || null,
        validation_deadline: m.querySelector("#pValid").value || null,
        proclamation_at: m.querySelector("#pProc").value || null,
        weight: parseFloat(m.querySelector("#pWeight").value),
        sort: parseInt(m.querySelector("#pSort").value, 10),
        is_exam: m.querySelector("#pExam").checked,
      };
      api.fetch(edition ? "/periods/" + p.id : "/periods", { method: edition ? "PUT" : "POST", body: JSON.stringify(corps) }).then(function (r) {
        if (!r.ok) { UI.btnState(btn, "error"); err.textContent = r.body.error || "Impossible."; err.hidden = false; return; }
        UI.btnState(btn, "success"); UI.toast(edition ? "Période mise à jour." : "Période ajoutée.", "success");
        setTimeout(function () { UI.closeModal(); load(); }, 400);
      });
    });
  }

  // ---- Aperçu d'audience AVANT proclamation --------------------------------
  //
  // Proclamer notifie des familles réelles. On ne le fait donc pas derrière un
  // « Êtes-vous sûr ? » : on montre d'abord QUI verra, qui ne verra pas, et
  // pourquoi. Les chiffres viennent de `/publication-preview`, qui appelle la
  // MÊME fonction que la publication (`school.compute_publication_audience`) —
  // l'aperçu ne peut donc pas annoncer autre chose que ce qui sera fait.
  function openPublishModal(periodId, label) {
    var m = UI.modal({
      title: "Proclamer « " + label + " »",
      size: "lg",
      body: '<div id="apContenu">' + UI.skeleton("row", 3) + "</div>",
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="apCancel">Annuler</button><button type="button" class="btn btn-lime btn-sm" id="apGo" disabled>Proclamer</button>'
    });
    m.querySelector("#apCancel").addEventListener("click", UI.closeModal);

    api.fetch("/periods/" + periodId + "/publication-preview", { method: "POST", body: JSON.stringify({}) }).then(function (r) {
      var hote = m.querySelector("#apContenu");
      if (!r.ok) {
        hote.innerHTML = UI.errorState("Aperçu indisponible", r.body.error || "");
        return;
      }
      var a = r.body, pol = a.policy || {};
      var motifs = {};
      (a.excluded_sample || []).forEach(function (e) { motifs[e.reason] = (motifs[e.reason] || 0) + 1; });

      hote.innerHTML =
        '<div class="kpi-grid cols-3" style="margin-bottom:14px">' +
          UI.kpi("Verront leurs résultats", String(a.included_count), { icon: "users", tone: a.included_count ? "ok" : "warn" }) +
          UI.kpi("Exclus", String(a.excluded_count), { icon: "lock", tone: a.excluded_count ? "warn" : "" }) +
          UI.kpi("Élèves de la période", String(a.total), { icon: "students" }) + "</div>" +
        '<p class="muted" style="margin-bottom:12px">Politique de diffusion : <strong>' +
          UI.escapeHtml(pol.mode === "balance" ? "sous condition de solde" : "ouverte à tous") + "</strong>" +
          (pol.mode === "balance" ? " — plafond " + UI.money(pol.max_balance) : "") + ". " +
          "Seuls les parents des élèves inclus seront notifiés.</p>" +
        (a.excluded_count
          ? '<div class="panel" style="background:var(--surface-soft);margin-bottom:12px"><div class="panel-head"><h2>Pourquoi des élèves sont exclus</h2></div>' +
            UI.barRows(Object.keys(motifs).map(function (k) { return { label: k, value: motifs[k] }; })) +
            (a.excluded_count > (a.excluded_sample || []).length
              ? '<p class="muted" style="margin-top:8px">Répartition établie sur les ' + (a.excluded_sample || []).length + " premiers exclus ; " + a.excluded_count + " au total.</p>"
              : "") + "</div>"
          : "") +
        (a.included_count
          ? '<div class="table-wrap" style="max-height:220px;overflow-y:auto"><table class="data-table"><thead><tr><th>Élève</th><th>Classe</th></tr></thead><tbody>' +
            (a.included_sample || []).map(function (e) {
              return "<tr><td>" + UI.escapeHtml(e.last_name + " " + e.first_name) + "</td><td>" + UI.escapeHtml(e.class_name || "—") + "</td></tr>";
            }).join("") + "</tbody></table></div>" +
            (a.included_count > (a.included_sample || []).length
              ? '<p class="muted" style="margin-top:8px">' + (a.included_sample || []).length + " affichés sur " + a.included_count + ".</p>" : "")
          : '<p class="form-msg error">Aucun élève ne recevrait cette proclamation. Vérifiez la politique de diffusion et les inscriptions avant de continuer.</p>');

      var go = m.querySelector("#apGo");
      // On n'arme le bouton que s'il y a quelqu'un à informer : proclamer pour
      // zéro destinataire n'est pas une proclamation.
      go.disabled = !a.included_count;
      go.addEventListener("click", function () {
        UI.btnState(go, "loading", "Proclamation…");
        api.fetch("/periods/" + periodId + "/publish", { method: "POST", body: JSON.stringify({}) }).then(function (res) {
          if (!res.ok) { UI.btnState(go, "error"); UI.toast(res.body.error || "Impossible.", "error"); return; }
          UI.btnState(go, "success", "Proclamée");
          UI.toast("Période proclamée — " + UI.plural(res.body.students, "élève concerné", "élèves concernés") + ".", "success", 5000);
          setTimeout(function () { UI.closeModal(); load(); }, 500);
        });
      });
    });
  }

  // ---- Réouverture motivée -------------------------------------------------
  //
  // Le serveur exige une raison d'au moins dix caractères. L'écran le dit
  // AVANT l'envoi plutôt que de laisser l'utilisateur écrire « ok » et se faire
  // refuser — mais c'est bien le serveur qui tranche.
  function openReopenModal(periodId, label) {
    var m = UI.modal({
      title: "Rouvrir « " + label + " »",
      body: '<form id="rForm" class="form-grid">' +
        '<p class="modal-text full">Rouvrir une période verrouillée est exceptionnel. Votre raison est conservée au journal d\'audit, avec votre nom et la date, et reste consultable par l\'établissement.</p>' +
        '<div class="field full"><label for="rReason">Raison de la réouverture</label><textarea id="rReason" rows="3" maxlength="400" placeholder="Ex. Deux notes de 4e B saisies dans la mauvaise période, correction demandée par le titulaire."></textarea>' +
        '<span class="hint" id="rCount">10 caractères minimum.</span></div>' +
        '<p class="form-error full" id="rErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="rCancel">Annuler</button><button type="submit" form="rForm" class="btn btn-lime btn-sm" id="rSubmit" disabled>Rouvrir</button>'
    });
    m.querySelector("#rCancel").addEventListener("click", UI.closeModal);
    var champ = m.querySelector("#rReason"), submit = m.querySelector("#rSubmit"), compte = m.querySelector("#rCount");
    champ.addEventListener("input", function () {
      var n = champ.value.trim().length;
      submit.disabled = n < 10;
      compte.textContent = n < 10 ? (10 - n) + " caractère(s) manquant(s)." : n + " caractères.";
    });
    m.querySelector("#rForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var err = m.querySelector("#rErr"); err.hidden = true; UI.btnState(submit, "loading");
      api.fetch("/periods/" + periodId + "/reopen", { method: "POST", body: JSON.stringify({ reason: champ.value.trim() }) }).then(function (r) {
        if (!r.ok) { UI.btnState(submit, "error"); err.textContent = r.body.error || "Impossible."; err.hidden = false; return; }
        UI.btnState(submit, "success"); UI.toast("Période rouverte — la raison est au journal.", "success");
        setTimeout(function () { UI.closeModal(); load(); }, 500);
      });
    });
  }

  // ---- Historique des réouvertures ----------------------------------------
  function openHistoriqueModal(periodId, label) {
    var m = UI.modal({ title: "Historique — " + label, body: '<div id="hContenu">' + UI.skeleton("row", 2) + "</div>",
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="hClose">Fermer</button>' });
    m.querySelector("#hClose").addEventListener("click", UI.closeModal);
    api.fetch("/periods/" + periodId + "/reopenings").then(function (r) {
      var hote = m.querySelector("#hContenu");
      if (!r.ok) { hote.innerHTML = UI.errorState("Historique indisponible", r.body.error || ""); return; }
      if (!r.body.length) {
        hote.innerHTML = UI.emptyState("Aucune réouverture", "Cette période n'a jamais été rouverte après verrouillage.", "", "lock");
        return;
      }
      hote.innerHTML = '<div class="timeline">' + r.body.map(function (o) {
        return '<div class="tl-item"><span class="tl-dot warn"></span><div class="tl-body"><strong>' +
          UI.escapeHtml(o.reopened_by_name || "Direction") + "</strong><span>" + UI.escapeHtml(o.reason) + "</span><em>" +
          UI.fmtDateTime(o.reopened_at) + (o.relocked_at ? " · refermée le " + UI.fmtDateTime(o.relocked_at) : " · encore ouverte") +
          "</em></div></div>";
      }).join("") + "</div>";
    });
  }

  function openMemberModal(d) {
    var cycles = [];
    try { cycles = d.cycles ? JSON.parse(d.cycles) : ["secondaire"]; } catch (e) { cycles = ["secondaire"]; }
    var isDD = d.role === "discipline";
    var m = UI.modal({ title: "Rôle de " + d.name, body: '<form id="mForm" class="form-grid">' +
      '<div class="field full"><label for="mTitle">Titre</label><input id="mTitle" maxlength="60" value="' + UI.escapeHtml(d.title || "") + '" placeholder="Ex. Adjoint, Préfet des études" /><span class="hint">Affiché à côté du nom. Ne change aucun droit.</span></div>' +
      (isDD ? '<div class="field full"><label>Périmètre par cycle</label><div class="chips" id="mCycles">' + CYCLES.map(function (c) { return '<button type="button" class="chip' + (cycles.indexOf(c) >= 0 ? " active" : "") + '" data-cycle="' + c + '">' + c.charAt(0).toUpperCase() + c.slice(1) + "</button>"; }).join("") + '</div><span class="hint">Le DD ne voit que les classes de ces cycles : présences, retards, incidents, convocations. Jamais les finances.</span></div>' : "") +
      '<p class="form-error full" id="mErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="mCancel">Annuler</button><button type="submit" form="mForm" class="btn btn-lime btn-sm" id="mSubmit">Enregistrer</button>' });
    m.querySelector("#mCancel").addEventListener("click", UI.closeModal);
    if (isDD) m.querySelectorAll("#mCycles .chip").forEach(function (ch) { ch.addEventListener("click", function () { ch.classList.toggle("active"); }); });
    m.querySelector("#mForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#mSubmit"), err = m.querySelector("#mErr"); err.hidden = true;
      var payload = { title: m.querySelector("#mTitle").value.trim() };
      if (isDD) {
        payload.scope_cycles = Array.prototype.map.call(m.querySelectorAll("#mCycles .chip.active"), function (c) { return c.dataset.cycle; });
        if (!payload.scope_cycles.length) { err.textContent = "Choisissez au moins un cycle."; err.hidden = false; return; }
      }
      UI.btnState(btn, "loading");
      api.fetch("/team/" + d.uid, { method: "PUT", body: JSON.stringify(payload) }).then(function (r) {
        if (!r.ok) { UI.btnState(btn, "error"); err.textContent = r.body.error || "Impossible."; err.hidden = false; return; }
        UI.btnState(btn, "success"); UI.toast("Rôle mis à jour.", "success"); setTimeout(function () { UI.closeModal(); load(); }, 400);
      });
    });
  }

  function renderStudentList(query) {
    var filtered = students.filter(function (s) { return !query || (s.first_name + " " + s.last_name + " " + (s.code || "")).toLowerCase().indexOf(query) !== -1; }).slice(0, 60);
    var list = document.getElementById("studentCheckList");
    if (!filtered.length) { list.innerHTML = '<p class="muted" style="margin:6px 0">Aucun élève ne correspond.</p>'; return; }
    list.innerHTML = filtered.map(function (s) { return '<label class="check"><input type="checkbox" data-sid="' + s.id + '"' + (selectedStudentIds[s.id] ? " checked" : "") + " />" + UI.escapeHtml(s.last_name + " " + s.first_name) + ' <span class="muted">' + UI.escapeHtml(s.class_name || "") + " · " + UI.escapeHtml(s.code || "") + "</span></label>"; }).join("");
    list.querySelectorAll("input").forEach(function (cb) { cb.addEventListener("change", function () { if (cb.checked) selectedStudentIds[cb.dataset.sid] = true; else delete selectedStudentIds[cb.dataset.sid]; }); });
  }

  function createInvitation() {
    var msg = document.getElementById("inviteMsg"); msg.className = "form-msg"; msg.textContent = "";
    var role = document.getElementById("inviteRole").value, label = document.getElementById("inviteLabel").value.trim();
    var payload = { role: role, label: label || undefined };
    if (role === "parent") { payload.student_ids = Object.keys(selectedStudentIds); if (!payload.student_ids.length) { msg.textContent = "Sélectionnez au moins un élève."; msg.className = "form-msg error"; return; } }
    if (role === "professeur") { payload.class_ids = Object.keys(selectedClassIds); payload.titulaire_class_id = document.getElementById("titClass").value || null; }
    if (role === "discipline") {
      payload.scope_cycles = Object.keys(selectedCycles);
      payload.title = document.getElementById("ddTitle").value.trim() || undefined;
      if (!payload.scope_cycles.length) { msg.textContent = "Choisissez au moins un cycle pour ce DD."; msg.className = "form-msg error"; return; }
    }
    var btn = document.getElementById("createInviteBtn");
    UI.btnState(btn, "loading", "Génération…");
    api.fetch("/invitations", { method: "POST", body: JSON.stringify(payload) }).then(function (res) {
      if (!res.ok) { UI.btnState(btn, "error"); msg.textContent = res.body.error || "Impossible de créer l'invitation."; msg.className = "form-msg error"; return; }
      UI.btnState(btn, "success", "Invitation créée");
      var link = window.location.origin + "/app/invitation.html?token=" + encodeURIComponent(res.body.token);
      document.getElementById("linkOutput").value = link;
      document.getElementById("whatsappShareBtn").href = "https://wa.me/?text=" + encodeURIComponent("Bonjour, voici votre invitation Klassio pour " + (ctx.tenant_name || "notre établissement") + " : " + link);
      document.getElementById("linkResultPanel").hidden = false;
      selectedStudentIds = {}; selectedClassIds = {};
      api.fetch("/invitations").then(function (r) {
        invitations = r.body || [];
        var panel = document.getElementById("invitations");
        panel.outerHTML = renderInvitations();
        document.getElementById("linkOutput").value = link;
        document.getElementById("whatsappShareBtn").href = "https://wa.me/?text=" + encodeURIComponent("Bonjour, voici votre invitation Klassio : " + link);
        document.getElementById("linkResultPanel").hidden = false;
        wireInvitations();
      });
    }).catch(function () { UI.btnState(btn, "error"); msg.textContent = "Le serveur Klassio est injoignable."; msg.className = "form-msg error"; });
  }
})();
