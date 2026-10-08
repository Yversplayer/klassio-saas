// KLASSIO — tableau de bord orienté décision, par rôle. Chaque chiffre vient
// de GET /api/dashboard (et, pour le DD, GET /api/discipline/today) : données
// réelles du tenant, aucune valeur en dur.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var ctx = null;

  admin.initShell("dashboard").then(function (c) {
    // Le professeur n'a pas de tableau de bord : il entre par SES CLASSES.
    // Cette page n'est plus dans son menu, mais elle reste au bout de vieux
    // liens, de signets et des boutons « Retour » des écrans qui lui sont
    // fermés. On l'y renvoie plutôt que de laisser vivre une seconde page
    // d'accueil, qui redirait la même chose dans un autre cadrage.
    //
    // Le rôle vient de /me, jamais de localStorage. La chaîne de requête est
    // conservée : c'est elle qui porte `?bienvenue=1`, et la clôture de
    // l'accueil vit désormais dans la coquille — donc sur la page d'arrivée,
    // quelle qu'elle soit.
    if (c.role === "professeur") {
      window.location.replace(UI.homeFor(c.role) + window.location.search);
      return;
    }
    ctx = c;
    document.getElementById("greeting").textContent = (c.role === "discipline" ? "Aujourd'hui" : "Bienvenue") + (c.user_name ? ", " + api.firstName(c.user_name) : "") + ".";
    document.getElementById("dashSub").textContent = c.tenant_name ? c.tenant_name + " — " + (api.roleLabels[c.role] || c.role) + (c.title ? " · " + c.title : "") : "";
    load();
  });

  function load() {
    var host = document.getElementById("dashContent");
    host.innerHTML = '<div class="kpi-grid">' + UI.skeleton("kpi", 4) + "</div>" + UI.skeleton("card", 2);
    var calls = [api.fetch("/dashboard")];
    if (ctx.role === "discipline") calls.push(api.fetch("/discipline/today"));
    Promise.all(calls).then(function (r) {
      if (!r[0].ok) return admin.loadError(host, load, "Impossible de charger votre tableau de bord");
      var d = r[0].body;
      if (d.role === "directeur") renderDirecteur(d);
      else if (d.role === "discipline") renderDiscipline(d, r[1] && r[1].ok ? r[1].body : null);
      else if (d.role === "parent") renderParent(d);
      UI.wireHrefs(host);
    }).catch(function () { admin.loadError(host, load, "Le serveur Klassio est injoignable"); });
  }

  function actions(list) {
    document.getElementById("dashActions").innerHTML = list.map(function (a) {
      return '<a href="' + a.href + '" class="btn ' + (a.primary ? "btn-lime" : "btn-ghost") + ' btn-sm">' + UI.icon(a.icon, 15) + a.label + "</a>";
    }).join("");
  }

  function attendancePanel(att, extra) {
    var total = att.recorded || 0;
    var body;
    if (!total) body = '<p class="muted">Aucun appel enregistré aujourd\'hui pour le moment.</p>';
    else body = UI.stackedBar([{ value: att.present, cls: "ok", label: "Présents" }, { value: att.late, cls: "warn", label: "Retards" }, { value: att.absent, cls: "bad", label: "Absents" }, { value: att.excused, cls: "neutral", label: "Excusés" }], total) +
      '<div class="legend"><span class="ok">' + att.present + " présents</span><span class=\"warn\">" + att.late + " retards</span><span class=\"bad\">" + att.absent + " absents</span><span>" + att.excused + " excusés</span></div>";
    return '<div class="panel"><div class="panel-head"><h2>Présence aujourd\'hui</h2><span class="sub">' + UI.escapeHtml(extra || "") + "</span></div>" + body + "</div>";
  }

  function eventsPanel(events, title) {
    return '<div class="panel"><div class="panel-head"><h2>' + (title || "À venir") + '</h2><a class="link-btn" href="calendrier.html">Calendrier</a></div>' +
      (events && events.length ? '<div class="timeline">' + events.map(function (e) {
        return '<div class="tl-item"><span class="tl-dot ' + ({ ok: "", warn: "warn", bad: "bad", info: "", neutral: "" })[UI.EVENT_KIND_TONES[e.kind] || "neutral"] + '"></span><div class="tl-body"><strong>' + UI.escapeHtml(e.title) + " " + UI.badge(UI.EVENT_KIND_TONES[e.kind] || "neutral", UI.EVENT_KIND_LABELS[e.kind] || e.kind) + "</strong><em>" + UI.fmtDate(e.starts_on) + (e.starts_time ? " · " + UI.escapeHtml(e.starts_time) : "") + (e.target_scope === "class" ? " · une classe" : e.target_scope === "cycle" ? " · " + UI.escapeHtml(e.target_value || "") : "") + "</em></div></div>";
      }).join("") + "</div>" : '<p class="muted">Aucun événement planifié' + (ctx.role === "directeur" || ctx.role === "discipline" ? ' — <a class="link-btn" href="calendrier.html">publier un événement ou un communiqué</a>.' : ".") + "</p>") + "</div>";
  }

  // ---------------- DIRECTION ----------------
  //
  // Refonte du 08/10/2026, sur les modèles du propriétaire : « quelques
  // parties en gros, pas les détails ». L'accueil ne garde que ce qui se lit
  // d'un coup d'œil — l'école, l'argent, ce qui attend, ce qui vient. Les
  // détails (soldes par classe, derniers paiements, recouvrement) vivent dans
  // Finance, où ils ont désormais leur propre mise en scène.
  //
  // Le calcul ne bouge pas : chaque chiffre vient toujours de GET /api/dashboard.
  // Une carte « Période d'essai » n'y revient pas — l'abonnement est une
  // affaire entre Klassio et l'école, il vit dans Paramètres → Abonnement.
  var T = window.KlassioTableau;

  function renderDirecteur(d) {
    var a = d.attendance_today;
    // La carte d'en-tête porte le titre et les actions : l'en-tête générique
    // de la page les répéterait juste au-dessus.
    document.querySelector(".page-header").hidden = true;
    var todo = [
      { count: d.pending_reports || 0, label: "Signalements à qualifier", sub: "Incident ou classement", href: "discipline.html?tab=signalements", icon: "discipline" },
      { count: d.pending_justifications || 0, label: "Justifications d'absence", sub: "Demandes de parents", href: "discipline.html?tab=justifications", icon: "file" },
      { count: d.convocations_today || 0, label: "Convocations aujourd'hui", sub: "À tenir ou à reporter", href: "discipline.html?tab=convocations", icon: "users" },
      { count: d.pending_payments || 0, label: "Paiements Mobile Money à confirmer", sub: "Après vérification de la transaction", href: "paiements.html?filter=pending", icon: "phone" },
      { count: d.orders_to_prepare || 0, label: "Commandes boutique à préparer", sub: "Retrait par l'élève avec son code", href: "boutique.html", icon: "store" },
      { count: d.unread_messages || 0, label: "Messages non lus", sub: "Cahier de communication", href: "messages.html", icon: "mail" },
      { count: d.pending_invitations || 0, label: "Invitations non acceptées", sub: "Établissement → Équipe & accès", href: "etablissement.html?tab=equipe", icon: "users" },
    ].filter(function (t) { return t.count > 0; });
    var enAttente = todo.reduce(function (s, t) { return s + t.count; }, 0);

    var hero = '<section class="kt-hero kt-3d"><span class="kt-sur">' + UI.escapeHtml(new Date().toLocaleDateString((window.KLASSIO_LOCALE || "fr-FR"), { weekday: "long", day: "numeric", month: "long" })) + "</span>" +
      "<h1 class=\"kt-titre\">Bonjour" + (ctx.user_name ? ", " + UI.escapeHtml(api.firstName(ctx.user_name)) : "") + ".</h1>" +
      "<p>" + UI.escapeHtml(ctx.tenant_name || "") + (ctx.tenant_name ? " — " : "") + (enAttente ? UI.plural(todo.length, "sujet vous attend", "sujets vous attendent") + " aujourd'hui." : "tout est à jour ce matin.") + "</p>" +
      '<div class="kt-actions"><a class="kt-btn-lime" href="eleves.html?new=1">' + UI.icon("plus", 15) + 'Ajouter un élève</a><a class="kt-btn-clair" href="paiements.html?new=1">' + UI.icon("payments", 15) + 'Enregistrer un paiement</a><a class="kt-btn-clair" href="etablissement.html?tab=equipe">' + UI.icon("users", 15) + "Inviter</a></div>" +
      '<div class="kt-objets" aria-hidden="true">' + T.objet("cartable", "kt-objet-a") + T.objet("pieces", "kt-objet-b", 240) + T.objet("telephone", "kt-objet-c", 240) + "</div></section>";

    var appel = a.recorded ? T.donut([{ value: a.present, color: "#7BC400" }, { value: a.late, color: "#F0C070" }, { value: a.absent, color: "#D9643A" }, { value: a.excused, color: "#9AA59C" }], a.recorded, "appels reçus", a.classes_recorded + " / " + a.class_count) +
        '<div class="kt-legende"><span>' + a.present + " présents</span><span style=\"--c:#F0C070\" class=\"kt-l2\">" + a.late + " retards</span><span class=\"kt-l3\">" + a.absent + " absents</span></div>"
      : T.donut([], 0, "appels reçus", a.classes_recorded + " / " + a.class_count) + '<p class="kt-vide" style="text-align:center">Les titulaires n\'ont pas encore envoyé l\'appel.</p>';
    var aujourdhui = '<section class="kt-carte kt-3d"><div class="kt-tete"><h2>Présence du jour</h2><a class="link-btn" href="classes.html">Classes</a></div>' + appel + "</section>";

    var trio = '<div class="kt-trio">' +
      '<a class="kt-stat t1 kt-3d" href="eleves.html"><span class="kt-stat-ic">' + UI.icon("students", 20) + '</span><span class="kt-stat-lbl">Élèves</span><span class="kt-stat-val">' + d.student_count.toLocaleString((window.KLASSIO_LOCALE || "fr-FR")) + '</span><span class="kt-stat-sub">' + UI.plural(d.class_count, "classe") + " · " + UI.plural(d.teacher_count, "enseignant") + "</span>" + "</a>" +
      '<a class="kt-stat t2 kt-3d" href="finance.html"><span class="kt-stat-ic">' + UI.icon("payments", 20) + '</span><span class="kt-stat-lbl">Encaissé</span><span class="kt-stat-val">' + UI.compactMoney(d.total_paid, d.currency) + '</span><span class="kt-stat-sub">' + d.collection_rate + " % de " + UI.compactMoney(d.total_due, d.currency) + ' attendus</span><span class="kt-jauge"><span style="width:' + Math.max(0, Math.min(100, d.collection_rate)) + '%"></span></span>' + "</a>" +
      '<a class="kt-stat t3 kt-3d" href="finance.html#impayes"><span class="kt-stat-ic">' + UI.icon("alert", 20) + '</span><span class="kt-stat-lbl">Restant à encaisser</span><span class="kt-stat-val">' + UI.compactMoney(d.outstanding, d.currency) + '</span><span class="kt-stat-sub">' + (d.outstanding > 0 ? "Voir les impayés dans Finance" : "Aucun impayé") + "</span>" + "</a>" +
      "</div>";

    var attente = '<section class="kt-carte"><div class="kt-tete"><h2>À traiter</h2><span class="sub">' + (todo.length ? UI.plural(todo.length, "sujet en attente", "sujets en attente") : "Rien en attente") + "</span></div>" +
      (todo.length ? '<div class="kt-liste">' + todo.map(function (t) {
        return '<a class="kt-ligne" href="' + t.href + '"><span class="kt-rond">' + UI.icon(t.icon, 16) + "</span><span><strong>" + UI.escapeHtml(t.label) + "</strong><small>" + UI.escapeHtml(t.sub) + '</small></span><span class="kt-montant">' + t.count + "</span></a>";
      }).join("") + "</div>" : '<p class="kt-vide">Tout est à jour. Signalements, justifications, paiements à confirmer et commandes apparaîtront ici.</p>') + "</section>";

    var ev = d.upcoming_events || [];
    var avenir = '<section class="kt-carte"><div class="kt-tete"><h2>À venir</h2><a class="link-btn" href="calendrier.html">Calendrier</a></div>' +
      (ev.length ? '<div class="kt-liste">' + ev.slice(0, 5).map(function (e) {
        var j = new Date(e.starts_on + "T00:00:00");
        return '<a class="kt-ligne" href="calendrier.html"><span class="kt-rond clair">' + j.getDate() + "</span><span><strong>" + UI.escapeHtml(e.title) + "</strong><small>" + UI.escapeHtml(UI.EVENT_KIND_LABELS[e.kind] || e.kind) + " · " + UI.fmtDate(e.starts_on) + (e.starts_time ? " · " + UI.escapeHtml(e.starts_time) : "") + "</small></span><span></span></a>";
      }).join("") + "</div>" : '<p class="kt-vide">Aucun événement planifié — <a class="link-btn" href="calendrier.html">publier un événement</a>.</p>') + "</section>";

    var html = '<div class="kt-grille">' + hero + aujourdhui + "</div>" + trio + '<div class="kt-grille kt-egal">' + attente + avenir + "</div>";
    if (d.student_count === 0) {
      html = '<div class="panel"><div class="panel-head"><h2>Votre espace est prêt — il attend ses élèves</h2></div><p class="muted" style="font-size:14px;">Importez votre fichier Excel ou ajoutez vos premiers élèves ; les indicateurs se construiront à partir de données réelles.</p><div class="row mt-16"><a href="inscription.html#import" class="btn btn-lime btn-sm">' + UI.icon("upload", 15) + 'Importer un fichier</a><a href="eleves.html?new=1" class="btn btn-ghost btn-sm">' + UI.icon("plus", 15) + "Ajouter un élève</a></div></div>" + html;
    }
    document.getElementById("dashContent").innerHTML = html;
  }

  // ---------------- DIRECTEUR DES DISCIPLINES ----------------
  function renderDiscipline(d, t) {
    actions([{ href: "pointage.html", icon: "clock", label: "Pointer un retard", primary: true }, { href: "discipline.html?new=1", icon: "plus", label: "Enregistrer un incident" }, { href: "calendrier.html", icon: "calendar", label: "Événement" }]);
    var a = d.attendance_today;
    var host = document.getElementById("dashContent");
    if (!t) { host.innerHTML = attendancePanel(a); return; }
    var scope = ctx.scope_cycles && ctx.scope_cycles.length ? ctx.scope_cycles.join(", ") : "secondaire";
    var html = '<div class="kpi-grid cols-5">' +
      UI.kpi("Appels manquants", String(t.classes_pending_roll.length), { icon: "clipboard", tone: t.classes_pending_roll.length ? "warn" : "ok", sub: d.class_count + " classes · " + scope }) +
      UI.kpi("Absents", String(t.absent_today.length), { icon: "calendar", tone: t.absent_today.length ? "bad" : "ok", sub: t.late_today.length + " retard(s)" }) +
      UI.kpi("Signalements", String(t.reports.length), { icon: "discipline", href: "discipline.html?tab=signalements", tone: t.reports.length ? "warn" : "", sub: "à qualifier" }) +
      UI.kpi("Justifications", String(t.justifications.length), { icon: "file", href: "discipline.html?tab=justifications", tone: t.justifications.length ? "warn" : "" }) +
      UI.kpi("Seuils atteints", String(t.alerts.length), { icon: "alert", tone: t.alerts.length ? "bad" : "ok", sub: "capital " + t.capital + " pts" }) + "</div>";

    // Qui n'est pas là — appels manquants avec relance
    html += '<div class="two-col">' +
      '<div class="panel"><div class="panel-head"><h2>Appels non envoyés</h2><span class="sub">' + UI.fmtDate(t.date) + "</span></div>" +
      (t.classes_pending_roll.length ? '<div class="roll-list">' + t.classes_pending_roll.map(function (c) {
        return '<div class="roll-row"><span class="avatar-init soft" style="width:36px;height:36px;font-size:12px;">' + UI.icon("classes", 16) + '</span><div class="roll-name"><a href="classe.html?id=' + c.id + '&tab=presence" class="link-btn">' + UI.escapeHtml(c.name) + "</a><span>" + c.student_count + " élèves · " + (c.titulaire ? "titulaire : " + UI.escapeHtml(c.titulaire) : "sans titulaire") + '</span></div><button type="button" class="btn btn-ghost btn-xs remind" data-id="' + c.id + '">' + UI.icon("bell", 13) + "Relancer</button></div>";
      }).join("") + "</div>" : '<p class="muted">Toutes les classes de votre périmètre ont envoyé leur appel.</p>') + "</div>" +
      '<div class="panel"><div class="panel-head"><h2>Absents du jour</h2><a class="link-btn" href="registres.html?type=attendance">Registre</a></div>' +
      (t.absent_today.length ? '<div class="table-wrap"><table class="data-table"><tbody>' + t.absent_today.slice(0, 12).map(function (s) {
        return '<tr class="clickable" data-href="eleve-dossier.html?id=' + s.id + '&tab=presence"><td><span class="cell-main">' + UI.escapeHtml(s.last_name + " " + s.first_name) + '</span><span class="cell-sub">' + UI.escapeHtml(s.class_name || "") + (s.note ? " · " + UI.escapeHtml(s.note) : "") + '</span></td><td class="num">' + (s.absences_30d >= 3 ? UI.badge("bad", s.absences_30d + " abs. / 30 j") : '<span class="muted">' + s.absences_30d + " / 30 j</span>") + "</td></tr>";
      }).join("") + "</tbody></table></div>" + (t.absent_today.length > 12 ? '<p class="muted mt-8">' + (t.absent_today.length - 12) + " autre(s) — voir le registre.</p>" : "") : '<p class="muted">Aucun absent enregistré pour l\'instant.</p>') + "</div></div>";

    html += '<div class="two-col">' +
      UI.todoPanel([
        { count: t.reports.length, label: "Signalements d'enseignants à qualifier", sub: "Vous décidez : incident (avec points) ou classement", href: "discipline.html?tab=signalements", icon: "discipline" },
        { count: t.justifications.length, label: "Justifications d'absence à décider", sub: "Certificats et motifs envoyés par les parents", href: "discipline.html?tab=justifications", icon: "file" },
        { count: t.convocations.length, label: "Convocations prévues aujourd'hui ou en retard", sub: "À marquer tenue, manquée ou reportée", href: "discipline.html?tab=convocations", icon: "users", tone: "bad" },
        { count: t.open_incidents.length, label: "Incidents ouverts sans décision", sub: "Une mesure humaine reste à tracer", href: "discipline.html?tab=incidents&status=open", icon: "clock", tone: "neutral" },
        { count: d.unread_messages || 0, label: "Messages de parents non lus", sub: "Cahier de communication", href: "messages.html", icon: "mail" },
      ], "À traiter",
        "Tout est à jour. Les signalements, justifications, convocations et incidents à décider apparaîtront ici.") +
      '<div class="panel"><div class="panel-head"><h2>Retards pointés</h2><a class="link-btn" href="pointage.html">Pointage</a></div>' +
      (t.late_today.length ? '<div class="roll-list">' + t.late_today.slice(0, 10).map(function (s) { return '<div class="roll-row"><div class="roll-name">' + UI.escapeHtml(s.last_name + " " + s.first_name) + "<span>" + UI.escapeHtml(s.class_name || "") + (s.source === "gate" ? " · portail" : " · en classe") + "</span></div>" + UI.badge("warn", s.arrival_time || "retard") + "</div>"; }).join("") + "</div>" : '<p class="muted">Aucun retard aujourd\'hui.</p>') + "</div></div>";

    html += '<div class="two-col">' +
      '<div class="panel"><div class="panel-head"><h2>Élèves sous un seuil</h2><span class="sub">Décision humaine — jamais automatique</span></div>' +
      (t.alerts.length ? '<div class="table-wrap"><table class="data-table"><tbody>' + t.alerts.map(function (s) {
        return '<tr class="clickable" data-href="eleve-dossier.html?id=' + s.id + '&tab=discipline"><td><span class="cell-main">' + UI.escapeHtml(s.last_name + " " + s.first_name) + '</span><span class="cell-sub">' + UI.escapeHtml(s.class_name || "") + " · " + UI.escapeHtml(s.step || "") + '</span></td><td class="num">' + UI.badge("bad", "reste " + s.remaining + " / " + s.capital) + "</td></tr>";
      }).join("") + "</tbody></table></div>" : '<p class="muted">Aucun élève sous les seuils fixés par l\'établissement.</p>') + "</div>" +
      eventsPanel(d.upcoming_events) + "</div>";
    host.innerHTML = html;
    host.querySelectorAll(".remind").forEach(function (b) {
      b.addEventListener("click", function () {
        UI.btnState(b, "loading", "…");
        api.fetch("/discipline/remind-roll", { method: "POST", body: JSON.stringify({ class_id: b.dataset.id }) }).then(function (r) {
          if (!r.ok) { UI.btnState(b, "error", "Réessayer"); return UI.toast(r.body.error || "Impossible.", "error"); }
          UI.btnState(b, "success", "Relancé"); UI.toast(r.body.notified + " enseignant(s) relancé(s).", "success");
        });
      });
    });
  }

  // ---------------- PARENT ----------------
  // « Prochaine proclamation » — ce que le parent attend vraiment.
  //
  // Le serveur renvoie la période, et la date SEULEMENT si l'établissement en
  // a déclaré une (`_prochaine_proclamation`). L'écran ne comble pas ce vide :
  // sans date, il nomme la période et s'arrête là. Écrire « bientôt » ou
  // calculer une date à partir de la fin de période serait un engagement pris
  // au nom de l'école, à des familles qui le liraient comme une promesse.
  function prochaineProclamation(c) {
    var n = c.next_proclamation;
    if (!n) {
      return UI.kpi("Prochaine proclamation", "—", { icon: "book",
        sub: "Tous les résultats publiés par l'école sont déjà consultables." });
    }
    return UI.kpi("Prochaine proclamation", n.proclamation_at ? UI.fmtDate(n.proclamation_at) : "Date non annoncée",
      { icon: "book", href: "eleve-dossier.html?id=" + c.student.id + "&tab=scolarite",
        sub: n.label + (n.proclamation_at ? "" : " — l'école n'a pas encore fixé de date") });
  }

  function renderParent(d) {
    actions([{ href: "messages.html", icon: "mail", label: "Écrire à l'école" }, { href: "paiements.html", icon: "payments", label: "Frais & reçus" }, { href: "boutique.html", icon: "store", label: "Boutique", primary: true }]);
    var host = document.getElementById("dashContent");
    if (!d.children.length) {
      host.innerHTML = UI.emptyState("Aucun enfant n'est encore lié à votre compte", "Demandez à l'établissement une invitation rattachée à votre enfant — l'accès aux dossiers vient uniquement de l'école.", "", "students");
      return;
    }
    host.innerHTML = d.children.map(function (c) {
      var s = c.student, f = c.financial, att = c.attendance_today;
      var alerts = [];
      if (c.next_convocation) alerts.push('<a class="roll-row" href="eleve-dossier.html?id=' + s.id + '&tab=discipline" style="text-decoration:none;color:inherit"><span class="avatar-init soft" style="width:36px;height:36px">' + UI.icon("users", 16) + '</span><div class="roll-name">Convocation le ' + UI.fmtDate(c.next_convocation.scheduled_on) + (c.next_convocation.scheduled_time ? " à " + UI.escapeHtml(c.next_convocation.scheduled_time) : "") + "<span>" + UI.escapeHtml(c.next_convocation.motif) + "</span></div>" + UI.badge("bad", "À honorer") + "</a>");
      if (att && att.status === "absent") alerts.push('<a class="roll-row" href="eleve-dossier.html?id=' + s.id + '&tab=presence" style="text-decoration:none;color:inherit"><span class="avatar-init soft" style="width:36px;height:36px">' + UI.icon("calendar", 16) + '</span><div class="roll-name">Absence aujourd\'hui<span>Vous pouvez la justifier depuis le dossier</span></div>' + UI.badge("warn", "Justifier") + "</a>");
      if (c.pending_justifications) alerts.push('<div class="roll-row"><span class="avatar-init soft" style="width:36px;height:36px">' + UI.icon("file", 16) + '</span><div class="roll-name">' + UI.plural(c.pending_justifications, "justification en attente", "justifications en attente") + "<span>Le titulaire ou le DD décide</span></div>" + UI.badge("neutral", "En cours") + "</div>");
      if (c.homework_due) alerts.push('<a class="roll-row" href="ressources.html?class_id=' + s.class_id + '" style="text-decoration:none;color:inherit"><span class="avatar-init soft" style="width:36px;height:36px">' + UI.icon("book", 16) + '</span><div class="roll-name">' + UI.plural(c.homework_due, "devoir à rendre", "devoirs à rendre") + "<span>Livres et devoirs publiés par les enseignants</span></div>" + UI.badge("info", "Voir") + "</a>");
      if (c.pending_orders) alerts.push('<a class="roll-row" href="boutique.html" style="text-decoration:none;color:inherit"><span class="avatar-init soft" style="width:36px;height:36px">' + UI.icon("store", 16) + '</span><div class="roll-name">' + UI.plural(c.pending_orders, "commande boutique à régler", "commandes boutique à régler") + "<span>Retrait à l'école une fois payée</span></div>" + UI.badge("warn", "Payer") + "</a>");
      return '<div class="panel"><div class="row between" style="margin-bottom:14px;"><div class="row">' + UI.avatar(s, 48) + '<div><h2 style="margin:0;font-size:18px;">' + UI.escapeHtml(s.first_name + " " + s.last_name) + '</h2><span class="muted">' + UI.escapeHtml(s.class_name || "Classe non affectée") + ' · <span class="chip-code">' + UI.escapeHtml(s.code || "") + "</span></span></div></div>" +
        '<div class="row"><a href="messages.html?student=' + s.id + '" class="btn btn-ghost btn-sm">' + UI.icon("mail", 14) + 'Écrire</a><a href="eleve-dossier.html?id=' + s.id + '" class="btn btn-lime btn-sm">Ouvrir le dossier ' + UI.icon("chevronRight", 14) + "</a></div></div>" +
        '<div class="kpi-grid">' +
        UI.kpi("Aujourd'hui", att ? ({ present: "À l'école", late: "En retard", absent: "Absent(e)", excused: "Excusé(e)" })[att.status] : "Appel non envoyé", { icon: "calendar", href: "eleve-dossier.html?id=" + s.id + "&tab=presence", tone: att ? (att.status === "absent" ? "bad" : att.status === "late" ? "warn" : "ok") : "", sub: c.attendance_summary.total ? c.attendance_summary.rate + " % de présence" : "" }) +
        UI.kpi("Dernier résultat", c.last_grade ? c.last_grade.score + "/" + c.last_grade.max_score : "—", { icon: "book", href: "eleve-dossier.html?id=" + s.id + "&tab=scolarite", sub: c.last_grade ? c.last_grade.subject + " · " + c.last_grade.period : "Aucun résultat proclamé" }) +
        UI.kpi("Prochaine évaluation", c.next_exam ? UI.fmtDate(c.next_exam.date) : "—", { icon: "clock", href: "eleve-dossier.html?id=" + s.id + "&tab=horaire", sub: c.next_exam ? c.next_exam.subject + (c.next_exam.room ? " · " + c.next_exam.room : "") : "Aucune évaluation planifiée" }) +
        prochaineProclamation(c) +
        UI.kpi("Reste à payer", UI.money(f.balance, f.currency), { icon: "finance", href: "eleve-dossier.html?id=" + s.id + "&tab=finance", tone: f.balance > 0 ? "warn" : "ok", sub: UI.money(f.total_paid, f.currency) + " payés sur " + UI.money(f.total_due, f.currency) }) +
        "</div>" + (alerts.length ? '<div class="roll-list" style="margin-top:12px">' + alerts.join("") + "</div>" : "") + "</div>";
    }).join("") + '<div class="two-col">' + eventsPanel(d.upcoming_events, "Agenda de l'école") +
      '<div class="panel"><div class="panel-head"><h2>Messages</h2><a class="link-btn" href="messages.html">Ouvrir</a></div><p class="muted">' + (d.unread_messages ? "<strong>" + UI.plural(d.unread_messages, "message non lu", "messages non lus") + "</strong> de l'école." : "Aucun message non lu. Le cahier de communication reste ouvert avec le titulaire et le DD.") + "</p></div></div>";
  }
})();
