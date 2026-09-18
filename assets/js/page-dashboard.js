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
  function renderDirecteur(d) {
    actions([{ href: "eleves.html?new=1", icon: "plus", label: "Ajouter un élève", primary: true }, { href: "paiements.html?new=1", icon: "payments", label: "Enregistrer un paiement" }, { href: "calendrier.html", icon: "calendar", label: "Événement" }, { href: "etablissement.html?tab=equipe", icon: "users", label: "Inviter" }]);
    var a = d.attendance_today, sub = d.subscription || {};
    // Le tableau de bord est consacré à l'ACTIVITÉ DE L'ÉTABLISSEMENT.
    //
    // Une carte « Période d'essai — 22 jours restants » y trônait en tête, au
    // même rang que les élèves et l'encaissement. C'est de la gestion
    // commerciale entre Klassio et l'école : elle n'a rien à faire au-dessus du
    // travail scolaire de la journée, et elle y revenait chaque matin.
    //
    // Le calcul, lui, n'a pas bougé d'un iota : statut, dates, jours restants,
    // palier et montant estimé continuent d'être produits par `api_billing`.
    // Seule sa PRÉSENTATION a déménagé — Paramètres → Abonnement.
    //
    // Le bandeau de lecture seule (abonnement impayé) reste, lui, dans la
    // coquille : il ne vend rien, il explique pourquoi l'enregistrement est
    // suspendu. Sans lui, l'utilisateur verrait ses actions échouer sans savoir
    // pourquoi.
    var html =
      '<div class="kpi-grid">' +
      UI.kpi("Élèves", d.student_count.toLocaleString("fr-FR"), { icon: "students", href: "eleves.html", sub: d.class_count + " classes · " + d.teacher_count + " enseignants" }) +
      UI.kpi("Attendu", UI.compactMoney(d.total_due, d.currency), { icon: "finance", href: "finance.html", sub: "sur l'année en cours" }) +
      UI.kpi("Encaissé", UI.compactMoney(d.total_paid, d.currency), { icon: "payments", href: "paiements.html", tone: "ok", sub: d.collection_rate + " % de recouvrement" }) +
      UI.kpi("Restant à encaisser", UI.compactMoney(d.outstanding, d.currency), { icon: "alert", href: "finance.html#impayes", tone: d.outstanding > 0 ? "warn" : "ok" }) +
      "</div>" +
      '<div class="kpi-grid cols-5">' +
      UI.kpi("Appels faits", a.classes_recorded + " / " + a.class_count, { icon: "clipboard", href: "classes.html", sub: "classes appelées aujourd'hui", tone: a.class_count && a.classes_recorded < a.class_count ? "warn" : "ok" }) +
      UI.kpi("Absents aujourd'hui", String(a.absent), { icon: "calendar", tone: a.absent ? "bad" : "ok", href: "classes.html", sub: a.late + " retard(s)" }) +
      UI.kpi("Signalements", String(d.pending_reports || 0), { icon: "discipline", href: "discipline.html?tab=signalements", tone: d.pending_reports ? "warn" : "", sub: "à qualifier par le DD" }) +
      UI.kpi("Justifications", String(d.pending_justifications || 0), { icon: "file", href: "discipline.html?tab=justifications", tone: d.pending_justifications ? "warn" : "", sub: "demandes de parents" }) +
      UI.kpi("Messages non lus", String(d.unread_messages || 0), { icon: "mail", href: "messages.html", tone: d.unread_messages ? "warn" : "" }) +
      "</div>" +
      '<div class="two-col">' +
      UI.todoPanel([
        { count: d.pending_reports || 0, label: "Signalements d'enseignants à qualifier", sub: "Le DD ou vous décidez : incident ou classement", href: "discipline.html?tab=signalements", icon: "discipline" },
        { count: d.pending_justifications || 0, label: "Justifications d'absence à décider", sub: "Accepter transforme l'absence en « excusée »", href: "discipline.html?tab=justifications", icon: "file" },
        { count: d.convocations_today || 0, label: "Convocations de parents aujourd'hui", sub: "À tenir ou à reporter", href: "discipline.html?tab=convocations", icon: "users", tone: "bad" },
        { count: d.pending_payments, label: "Paiements Mobile Money à confirmer", sub: "Après vérification réelle de la transaction", href: "paiements.html?filter=pending", icon: "phone" },
        { count: d.orders_to_prepare || 0, label: "Commandes boutique payées à préparer", sub: "Retrait par l'élève avec son code", href: "boutique.html", icon: "store" },
        { count: d.pending_orders, label: "Commandes en attente de paiement", sub: "Aucune action requise de votre part", href: "boutique.html", icon: "cart", tone: "neutral" },
        { count: d.pending_invitations, label: "Invitations non encore acceptées", sub: "Relancez ou révoquez dans Établissement → Équipe & accès", href: "etablissement.html?tab=equipe", icon: "users", tone: "neutral" },
      ], "À traiter aujourd'hui",
        "Tout est à jour. Les signalements, justifications, convocations, commandes et paiements à traiter apparaîtront ici.") +
      eventsPanel(d.upcoming_events) +
      "</div>" +
      '<div class="two-col">' +
      attendancePanel(a, a.classes_recorded ? "" : "Les titulaires n'ont pas encore envoyé l'appel") +
      '<div class="panel"><div class="panel-head"><h2>Recouvrement</h2><a class="link-btn" href="finance.html">Voir Finance</a></div><div class="row" style="gap:22px;">' +
      UI.ring(d.collection_rate, "encaissé", d.collection_rate < 50 ? "warn" : "") +
      '<div class="grow"><dl class="dl"><dt>Attendu</dt><dd>' + UI.money(d.total_due, d.currency) + "</dd><dt>Encaissé</dt><dd>" + UI.money(d.total_paid, d.currency) + "</dd><dt>Restant</dt><dd>" + UI.money(d.outstanding, d.currency) + "</dd></dl></div></div></div>" +
      "</div>" +
      '<div class="two-col">' +
      '<div class="panel"><div class="panel-head"><h2>Classes — solde restant</h2><span class="sub">les plus élevés</span></div>' +
      UI.barRows(d.classes_outstanding.filter(function (c) { return c.student_count > 0; }).map(function (c) { return { label: c.name, value: c.outstanding, display: UI.compactMoney(c.outstanding, d.currency), cls: c.outstanding > 0 ? "warn" : "", href: "classe.html?id=" + c.id }; }), { empty: "Aucune classe avec élèves pour le moment." }) + "</div>" +
      '<div class="panel"><div class="panel-head"><h2>Derniers paiements</h2><a class="link-btn" href="paiements.html">Tout voir</a></div>' +
      (d.recent_payments.length ? '<div class="timeline">' + d.recent_payments.map(function (p) {
        return '<div class="tl-item"><span class="tl-dot ok"></span><div class="tl-body"><strong>' + UI.money(p.amount, p.currency) + " — " + UI.escapeHtml(p.first_name + " " + p.last_name) + "</strong><span>" + UI.escapeHtml(UI.METHODS[p.method] || p.method) + (p.receipt_number ? " · Reçu " + UI.escapeHtml(p.receipt_number) : "") + "</span><em>" + UI.fmtDateTime(p.confirmed_at) + "</em></div></div>";
      }).join("") + "</div>" : UI.emptyState("Aucun paiement confirmé", "Les paiements enregistrés apparaîtront ici.", "", "payments")) + "</div>" +
      "</div>";
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
