// KLASSIO — démonstration interactive publique (/demo.html).
// Entièrement client-side : aucune requête réseau, aucune écriture, données
// fictives et cohérentes définies une seule fois dans demo-data.js.
(function () {
  "use strict";
  var D = window.KlassioDemoData;

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function money(v) { return (Number(v) || 0).toLocaleString("fr-FR") + " $"; }

  var STEPS = [
    { id: "establishment", label: "01 Établissement" },
    { id: "import", label: "02 Import" },
    { id: "dashboard", label: "03 Tableau de bord" },
    { id: "students", label: "04 Élèves & classes" },
    { id: "finance", label: "05 Finance & paiements" },
    { id: "attendance", label: "06 Présences & discipline" },
    { id: "results", label: "07 Résultats" },
    { id: "notifications", label: "08 Notifications" },
    { id: "roles", label: "09 Les 4 rôles" },
    { id: "trust", label: "10 Vos données" },
  ];
  var SIDEBAR_ITEMS = [
    ["🏠", "Accueil", "dashboard"], ["🏫", "Établissement", "establishment"],
    ["🎓", "Élèves", "students"], ["📚", "Classes", "students"],
    ["🛡️", "Discipline", "attendance"], ["📄", "Résultats", "results"],
    ["🔔", "Notifications", "notifications"],
    ["💰", "Finance", "finance"], ["💳", "Paiements", "finance"],
    ["📊", "Rapports", null], ["✨", "Assistant", null], ["⚙️", "Paramètres", null],
  ];

  function renderSidebar() {
    document.getElementById("sidebarNav").innerHTML = SIDEBAR_ITEMS.map(function (item, i) {
      var locked = item[2] === null;
      return '<a href="#" class="s-item' + (i === 0 ? " active" : "") + '" data-jump="' + (item[2] || "") + '"' +
             (locked ? ' data-locked="1" title="Disponible dans votre espace établissement"' : "") +
             '><span class="s-ic">' + item[0] + "</span>" + item[1] + "</a>";
    }).join("");
    document.getElementById("roleTag").innerHTML = "<strong>Jean</strong>Directeur / Administrateur — démo";
  }

  document.getElementById("demoProgress").innerHTML = STEPS.map(function (s, i) {
    return '<button type="button" class="dp-step' + (i === 0 ? " active" : "") + '" data-step-index="' + i + '">' + s.label + "</button>";
  }).join("");

  function scrollToStep(stepId) {
    var el = document.querySelector('.demo-step[data-step="' + stepId + '"]');
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // L'écran d'entrée furtif a été retiré (30/09) : l'ouverture cinématique
  // de demo.html joue ce rôle, sans faire attendre deux secondes devant un
  // carton. Il n'y a donc plus rien à escamoter ici.

  // ---------------- Défilement = navigation. La barre de progression et les
  // liens de la sidebar font défiler jusqu'à la section, ils ne l'affichent
  // plus/masquent plus rien (il n'y a plus qu'un seul long flux). ----------
  document.getElementById("demoProgress").addEventListener("click", function (e) {
    var btn = e.target.closest("[data-step-index]");
    if (btn) scrollToStep(STEPS[parseInt(btn.dataset.stepIndex, 10)].id);
  });
  document.getElementById("restartTourBtn").addEventListener("click", function () {
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  document.getElementById("sidebarNav").addEventListener("click", function (e) {
    var a = e.target.closest("[data-jump]");
    if (!a) return;
    e.preventDefault();
    if (a.dataset.locked) {
      a.classList.add("locked-flash");
      setTimeout(function () { a.classList.remove("locked-flash"); }, 900);
      return;
    }
    scrollToStep(a.dataset.jump);
  });

  document.getElementById("demoContent").addEventListener("click", function (e) {
    var jumpBtn = e.target.closest("[data-jump]");
    if (jumpBtn && !jumpBtn.closest("#sidebarNav")) scrollToStep(jumpBtn.dataset.jump);
  });

  var sidebar = document.getElementById("sidebar");
  document.getElementById("sidebarToggle").addEventListener("click", function () { sidebar.classList.toggle("collapsed"); });

  // Sous 860 px, la barre latérale passe en position fixe (règle de
  // l'application) : elle flotte donc AU-DESSUS de tout, y compris de
  // l'ouverture cinématique qui la précède dans la page. Elle démarre repliée
  // sur petit écran ; le bouton ☰ de la visite la fait apparaître.
  if (window.matchMedia("(max-width: 860px)").matches) sidebar.classList.add("collapsed");

  renderSidebar();
  renderDashboard();
  renderStudentsAndClasses();

  // ---------------- Repère actif pendant le défilement (sidebar + barre de
  // progression) + révélation des sections au scroll (mêmes classes .reveal
  // /.in-view que la landing page). ----------------
  var stepEls = Array.prototype.slice.call(document.querySelectorAll(".demo-step"));
  var revealObserver = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        entry.target.classList.add("in-view");
        revealObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });
  document.querySelectorAll(".reveal").forEach(function (el) { revealObserver.observe(el); });

  var tickingActive = false;
  function updateActiveStep() {
    tickingActive = false;
    // La section active est celle dont le haut est le plus proche, juste
    // au-dessus, du bas de l'en-tête sticky (topbar + barre de progression).
    var headerBottom = document.getElementById("demoProgress").getBoundingClientRect().bottom;
    var bestId = stepEls[0].dataset.step, bestTop = -Infinity;
    stepEls.forEach(function (el) {
      var top = el.getBoundingClientRect().top;
      if (top - headerBottom <= 1 && top > bestTop) { bestTop = top; bestId = el.dataset.step; }
    });
    document.querySelectorAll(".s-item[data-jump]").forEach(function (a) {
      a.classList.toggle("active", a.dataset.jump === bestId);
    });
    var bestIndex = STEPS.findIndex(function (s) { return s.id === bestId; });
    document.querySelectorAll(".dp-step").forEach(function (btn, i) {
      btn.classList.toggle("active", i === bestIndex);
      btn.classList.toggle("done", i < bestIndex);
    });
  }
  window.addEventListener("scroll", function () {
    if (tickingActive) return;
    tickingActive = true;
    requestAnimationFrame(updateActiveStep);
  }, { passive: true });
  updateActiveStep();

  // ---------------- 02 — Import ----------------
  document.getElementById("importPreviewBody").innerHTML = D.importPreviewRows.map(function (r) {
    return "<tr><td>" + escapeHtml(r.student) + "</td><td>" + escapeHtml(r.class) + "</td><td>" + escapeHtml(r.guardian) +
           "</td><td>" + money(r.fee) + "</td><td>" + money(r.paid) + "</td></tr>";
  }).join("");

  document.getElementById("runAnalysisBtn").addEventListener("click", function () {
    document.getElementById("importAnalyzePanel").hidden = true;
    var resultPanel = document.getElementById("importResultPanel");
    resultPanel.hidden = false;
    document.getElementById("importResultTitle").textContent = "Analyse du fichier…";

    var checklistSteps = [
      "Structure du fichier reconnue", "Colonnes identifiées", "Élèves détectés",
      "Classes détectées", "Responsables détectés", "Données financières détectées",
    ];
    var checklistEl = document.getElementById("importChecklist");
    checklistEl.innerHTML = "";
    checklistSteps.forEach(function (label, i) {
      setTimeout(function () {
        var div = document.createElement("div");
        div.className = "dc-item done";
        div.innerHTML = '<span class="dc-mark">✓</span>' + escapeHtml(label);
        checklistEl.appendChild(div);
      }, i * 260);
    });

    setTimeout(function () {
      document.getElementById("importResultTitle").textContent = "Analyse terminée";
      var summary = document.getElementById("importSummary");
      summary.hidden = false;
      summary.innerHTML =
        '<div class="info-card"><div class="k">Élèves détectés</div><div class="v lime">' + D.establishment.studentCount.toLocaleString("fr-FR") + "</div></div>" +
        '<div class="info-card"><div class="k">Classes détectées</div><div class="v">' + D.establishment.classCount + "</div></div>" +
        '<div class="info-card"><div class="k">Responsables détectés</div><div class="v">' + D.establishment.guardianCount.toLocaleString("fr-FR") + "</div></div>" +
        '<div class="info-card"><div class="k">Paiements détectés</div><div class="v">' + D.establishment.paymentCount.toLocaleString("fr-FR") + "</div></div>";

      var mapping = document.getElementById("importMapping");
      mapping.hidden = false;
      document.getElementById("mappingList").innerHTML = D.columnMapping.map(function (m) {
        return '<div class="dm-row">' + escapeHtml(m.source) + '<span class="dm-arrow">→</span><span class="dm-target">' + escapeHtml(m.target) + "</span></div>";
      }).join("");

      var quality = document.getElementById("importQuality");
      quality.hidden = false;
      document.getElementById("qualityScoreText").textContent = D.establishment.qualityScore + " %";
      document.getElementById("qualityGood").innerHTML = D.importQualityReasons.good.map(function (r) { return "<li>" + escapeHtml(r) + "</li>"; }).join("");
      document.getElementById("qualityWarn").innerHTML =
        D.importQualityReasons.warn.map(function (r) { return "<li>" + escapeHtml(r) + "</li>"; }).join("") +
        D.importAnomalies.map(function (a) { return "<li>" + escapeHtml(a) + "</li>"; }).join("");
    }, checklistSteps.length * 260 + 300);
  });

  // ---------------- 03 — Dashboard ----------------
  function renderDashboard() {
    document.getElementById("dashInfoGrid").innerHTML =
      '<div class="info-card"><div class="k">Élèves</div><div class="v lime">' + D.establishment.studentCount.toLocaleString("fr-FR") + "</div></div>" +
      '<div class="info-card"><div class="k">Classes</div><div class="v">' + D.establishment.classCount + "</div></div>" +
      '<div class="info-card"><div class="k">Enseignants</div><div class="v">' + D.establishment.teacherCount + "</div></div>" +
      '<div class="info-card"><div class="k">Responsables</div><div class="v">' + D.establishment.guardianCount.toLocaleString("fr-FR") + "</div></div>";
  }

  // ---------------- 04 — Élèves & classes ----------------
  function renderStudentsAndClasses() {
    document.getElementById("classesBody").innerHTML = D.classes.map(function (c) {
      return "<tr><td>" + escapeHtml(c.name) + "</td><td>" + escapeHtml(c.level) + "</td><td>" + c.studentCount + "</td></tr>";
    }).join("");

    document.getElementById("studentsBody").innerHTML = D.students.map(function (s, i) {
      var balance = s.fee - s.paid;
      return '<tr class="clickable" data-student-index="' + i + '"><td>' + escapeHtml(s.name) + "</td><td>" + escapeHtml(s.className) +
             '</td><td class="' + (balance > 0 ? "text-warn" : "text-lime") + '">' + money(balance) + "</td></tr>";
    }).join("");

    document.getElementById("studentsBody").addEventListener("click", function (e) {
      var row = e.target.closest("[data-student-index]");
      if (!row) return;
      ouvrirDossier(parseInt(row.dataset.studentIndex, 10));
    });

    document.getElementById("closeDossier").addEventListener("click", function (e) {
      e.preventDefault();
      document.getElementById("studentDossier").hidden = true;
    });
  }

  // ---------------- Dossier élève — mêmes onglets que le vrai produit -------
  // Les composants sont ceux de l'application (.tabs, .tab-btn, .panel,
  // .summary-strip, .info-card, .data-table, .badge) : la démo doit ressembler
  // à Klassio, pas être une seconde interface.
  var ONGLETS = [
    { id: "profil", label: "Profil" },
    { id: "presence", label: "Présence" },
    { id: "discipline", label: "Discipline" },
    { id: "resultats", label: "Résultats" },
    { id: "finance", label: "Finance" },
    { id: "recus", label: "Reçus" },
  ];
  var dossierIndex = 0, dossierOnglet = "profil";

  function ouvrirDossier(i) {
    dossierIndex = i;
    dossierOnglet = "profil";
    peindreDossier();
    var el = document.getElementById("studentDossier");
    el.hidden = false;
    el.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function ligne(k, v) {
    return '<div class="info-card"><div class="k">' + escapeHtml(k) +
           '</div><div class="v" style="font-size:16px;">' + v + "</div></div>";
  }

  function peindreDossier() {
    var s = D.students[dossierIndex];
    var solde = s.fee - s.paid;

    document.getElementById("dossierName").textContent = s.name;

    var entete =
      '<div class="summary-strip">' +
        ligne("Classe", escapeHtml(s.className)) +
        ligne("Responsable", escapeHtml(s.guardian)) +
        ligne("Conduite", '<span class="' + (s.conduct >= 95 ? "text-lime" : "text-warn") + '">' + s.conduct + " / 100</span>") +
        ligne("Reste à payer", '<span class="' + (solde > 0 ? "text-warn" : "text-lime") + '">' + money(solde) + "</span>") +
      "</div>";

    var barre = '<div class="tabs" role="tablist">' + ONGLETS.map(function (o) {
      return '<button type="button" role="tab" class="tab-btn' + (o.id === dossierOnglet ? " active" : "") +
             '" aria-selected="' + (o.id === dossierOnglet) + '" data-dossier-tab="' + o.id + '">' +
             escapeHtml(o.label) + "</button>";
    }).join("") + "</div>";

    document.getElementById("dossierBody").innerHTML = entete + barre +
      '<div class="panel">' + panneauOnglet(s) + "</div>";
  }

  function panneauOnglet(s) {
    if (dossierOnglet === "profil") {
      return "<h2>Identité</h2><div class=\"info-grid\">" +
        ligne("Identifiant", '<span class="chip-code">' + escapeHtml(s.code) + "</span>") +
        ligne("Genre", escapeHtml(s.sex)) +
        ligne("Date de naissance", escapeHtml(s.birth)) +
        ligne("Classe", escapeHtml(s.className)) +
        "</div><p class=\"note-inline\">Un identifiant élève sert au pointage, aux documents et aux registres. " +
        "Il ne donne <strong>jamais</strong> accès à un compte : les élèves n'en ont pas.</p>";
    }

    if (dossierOnglet === "presence") {
      var total = s.present + s.absent;
      var taux = total ? Math.round((s.present / total) * 100) : 0;
      return "<h2>Présence — période en cours</h2><div class=\"summary-strip\">" +
        ligne("Présences", s.present) + ligne("Absences", s.absent) +
        ligne("Retards", s.late) +
        ligne("Taux", '<span class="' + (taux >= 95 ? "text-lime" : "text-warn") + '">' + taux + " %</span>") +
        "</div><p style=\"font-size:13px;color:var(--ink-faint);margin:0;\">L'appel est fait par classe, par l'enseignant ou la discipline. " +
        "Chaque absence peut être justifiée, et la justification reste attachée au dossier.</p>";
    }

    if (dossierOnglet === "discipline") {
      if (!s.incidents.length) {
        return "<h2>Discipline</h2><p style=\"font-size:13.5px;color:var(--ink-soft);margin:0;\">" +
          "Aucun incident enregistré. Conduite : <strong>" + s.conduct + " / 100</strong>.</p>";
      }
      return "<h2>Discipline</h2><table class=\"data-table responsive\"><thead><tr>" +
        "<th>Date</th><th>Incident</th><th>Effet sur la conduite</th></tr></thead><tbody>" +
        s.incidents.map(function (x) {
          return "<tr><td>" + escapeHtml(x.date) + "</td><td>" + escapeHtml(x.label) +
                 '</td><td class="text-warn">' + x.impact + " pts</td></tr>";
        }).join("") + "</tbody></table>" +
        "<p style=\"font-size:13px;color:var(--ink-faint);margin:12px 0 0;\">Les règles et les seuils sont ceux définis par l'établissement. " +
        "Klassio applique la décision de l'école et en garde la trace.</p>";
    }

    if (dossierOnglet === "resultats") {
      return "<h2>Résultats</h2><table class=\"data-table responsive\"><thead><tr>" +
        "<th>Période</th><th>Matière</th><th>Note</th><th>Visible du parent</th></tr></thead><tbody>" +
        s.grades.map(function (g) {
          return "<tr><td>" + escapeHtml(g.period) + "</td><td>" + escapeHtml(g.subject) + "</td><td>" + escapeHtml(g.value) +
                 "</td><td>" + (g.published
                   ? '<span class="badge paid">Proclamé</span>'
                   : '<span class="badge">Non proclamé</span>') + "</td></tr>";
        }).join("") + "</tbody></table>" +
        "<p style=\"font-size:13px;color:var(--ink-faint);margin:12px 0 0;\">Importer une note ne la publie pas. " +
        "Tant qu'une période n'est pas proclamée, <strong>aucun parent ne la voit</strong>.</p>";
    }

    if (dossierOnglet === "finance") {
      return "<h2>Obligations et paiements</h2><table class=\"data-table responsive\"><thead><tr>" +
        "<th>Motif</th><th>Facturé</th><th>Payé</th><th>Reste</th><th>Échéance</th></tr></thead><tbody>" +
        s.obligations.map(function (o) {
          var r = o.due - o.paid;
          return "<tr><td>" + escapeHtml(o.label) + "</td><td>" + money(o.due) + "</td><td>" + money(o.paid) +
                 '</td><td class="' + (r > 0 ? "text-warn" : "text-lime") + '">' + money(r) +
                 "</td><td>" + escapeHtml(o.deadline) + "</td></tr>";
        }).join("") + "</tbody></table>" +
        "<p style=\"font-size:13px;color:var(--ink-faint);margin:12px 0 0;\">Le solde n'est jamais stocké : il est " +
        "recalculé à partir des obligations et des paiements confirmés.</p>";
    }

    // Reçus
    if (!s.receipts.length) {
      return "<h2>Reçus</h2><p style=\"font-size:13.5px;color:var(--ink-soft);margin:0;\">" +
        "Aucun paiement enregistré pour cet élève. Un reçu est émis automatiquement dès qu'un paiement est confirmé.</p>";
    }
    return "<h2>Reçus</h2><table class=\"data-table responsive\"><thead><tr>" +
      "<th>Reçu</th><th>Motif</th><th>Moyen</th><th>Date</th><th>Montant</th></tr></thead><tbody>" +
      s.receipts.map(function (r) {
        return '<tr><td><span class="chip-code">' + escapeHtml(r.number) + "</span></td><td>" + escapeHtml(r.label) +
               "</td><td>" + escapeHtml(r.method) + "</td><td>" + escapeHtml(r.date) +
               '</td><td class="text-lime">' + money(r.amount) + "</td></tr>";
      }).join("") + "</tbody></table>" +
      "<p style=\"font-size:13px;color:var(--ink-faint);margin:12px 0 0;\">Chaque reçu porte un numéro unique par établissement, " +
      "traçable depuis le dossier de l'élève comme depuis le journal.</p>";
  }

  // Un seul écouteur pour toute la zone : la barre d'onglets est reconstruite
  // à chaque peinture, y attacher des écouteurs les multiplierait.
  document.getElementById("studentDossier").addEventListener("click", function (e) {
    var btn = e.target.closest("[data-dossier-tab]");
    if (!btn) return;
    dossierOnglet = btn.dataset.dossierTab;
    peindreDossier();
  });

  // ---------------- Notifications ----------------
  function renderNotifications() {
    var hote = document.getElementById("demoNotifs");
    if (!hote) return;
    hote.innerHTML = D.notifications.map(function (n) {
      return '<div class="demo-notif"><span class="dn-ic" aria-hidden="true">' + n.icon + "</span>" +
        "<div class=\"dn-body\"><div class=\"dn-title\">" + escapeHtml(n.title) + "</div>" +
        '<div class="dn-text">' + escapeHtml(n.body) + "</div>" +
        '<div class="dn-meta">' + escapeHtml(n.when) + " · destinataires : " + escapeHtml(n.audience) + "</div></div></div>";
    }).join("");
  }
  renderNotifications();

  // ---------------- 06 — Les 3 espaces ----------------

  // L'OUVERTURE CINÉMATIQUE vit désormais dans assets/js/cine.js (moteur
  // partagé avec la landing) et assets/css/cine.css. Le lien « Commencer la
  // visite » est une ancre simple vers #demoShell : il marche sans script.

  document.getElementById("roleSwitch").addEventListener("click", function (e) {
    var btn = e.target.closest("button[data-role]");
    if (!btn) return;
    document.querySelectorAll("#roleSwitch button").forEach(function (b) { b.classList.toggle("active", b === btn); });
    ["directeur", "discipline", "professeur", "parent"].forEach(function (r) {
      var vue = document.getElementById("roleView" + r.charAt(0).toUpperCase() + r.slice(1));
      if (vue) vue.hidden = r !== btn.dataset.role;
    });
  });
})();
