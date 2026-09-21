// KLASSIO — Passage d'année et répartition.
//
// L'écran d'un BROUILLON de rentrée. Rien de ce qui s'y fait n'a d'effet tant
// que la Direction n'applique pas le plan : on peut tout y préparer, tout y
// corriger, et revenir le lendemain.
//
// Deux choses n'y apparaissent jamais. Aucune décision pré-cochée : un élève
// dont personne n'a parlé s'affiche « En attente », en rouge, et bloque la
// rentrée jusqu'à ce qu'une personne tranche. Aucune classe d'arrivée devinée :
// Klassio ne sait pas ce qui vient après la 5e A, et ne fait pas semblant.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var ctx = null, annees = [], plans = [], plan = null, detail = null;
  var classeCourante = null;

  var TON = {
    PASSAGE: ["ok", "Passage"],
    REDOUBLEMENT: ["warn", "Redoublement"],
    DEPART: ["muted", "Départ"],
    EN_ATTENTE: ["error", "En attente"],
  };
  var ETATS_PLAN = {
    BROUILLON: ["warn", "Brouillon"],
    EN_REVUE: ["warn", "En relecture"],
    VALIDE: ["ok", "Validé"],
    APPLIQUE: ["ok", "Appliqué"],
  };

  function ton(action) {
    var t = TON[action] || TON.EN_ATTENTE;
    return UI.badge(t[0], t[1]);
  }

  function erreur(res, defaut) {
    var b = res && res.body;
    if (!b) return defaut;
    return (b.error || defaut) + (b.detail ? " " + b.detail : "");
  }

  // ---- Liste des plans -------------------------------------------------

  function rendreListe() {
    var actives = annees.filter(function (a) { return a.is_active; });
    var optSource = annees.map(function (a) {
      return '<option value="' + a.id + '"' + (a.is_active ? " selected" : "") + ">"
        + UI.escapeHtml(a.label) + "</option>";
    }).join("");

    var lignes = plans.length ? plans.map(function (p) {
      var e = ETATS_PLAN[p.status] || ETATS_PLAN.BROUILLON;
      return '<tr data-open="' + p.id + '" style="cursor:pointer">'
        + "<td><strong>" + UI.escapeHtml(p.source_year_label) + "</strong> → "
        + UI.escapeHtml(p.target_year_label) + "</td>"
        + "<td>" + p.student_count + " élève(s)</td>"
        + "<td>" + UI.badge(e[0], e[1]) + "</td></tr>";
    }).join("") : '<tr><td colspan="3" class="muted" style="padding:18px 0">'
      + "Aucune rentrée en préparation.</td></tr>";

    var suggestion = actives.length
      ? UI.escapeHtml(prochaine(actives[0].label))
      : "";

    document.getElementById("passageContent").innerHTML =
      '<div class="panel"><div class="panel-head"><h2>Préparer une rentrée</h2>'
      + '<span class="sub">La nouvelle année reste en préparation : elle n\'apparaît nulle part '
      + "dans l'établissement tant que vous ne l'avez pas ouverte.</span></div>"
      + '<div class="row" style="gap:10px;flex-wrap:wrap;align-items:center">'
      + '<select id="pSource" style="min-width:190px">' + optSource + "</select>"
      + '<span class="muted">vers</span>'
      + '<input type="text" id="pCible" placeholder="Nom de la nouvelle année" value="' + suggestion + '" '
      + 'style="min-width:190px;border:1px solid var(--line);border-radius:10px;padding:10px 12px;font:inherit;background:var(--surface);color:var(--ink)" />'
      + '<button type="button" class="btn btn-lime btn-sm" id="pCreer">Ouvrir le plan</button>'
      + '</div><p class="form-msg" id="pMsg" style="margin-top:10px"></p></div>'
      + '<div class="panel" style="margin-top:16px"><div class="panel-head"><h2>Plans de passage</h2></div>'
      + '<div class="table-wrap"><table class="table"><thead><tr><th>Années</th><th>Effectif</th>'
      + "<th>État</th></tr></thead><tbody>" + lignes + "</tbody></table></div></div>";

    document.getElementById("pCreer").addEventListener("click", creer);
    Array.prototype.forEach.call(document.querySelectorAll("[data-open]"), function (tr) {
      tr.addEventListener("click", function () { ouvrir(tr.dataset.open); });
    });
  }

  // « 2026-2027 » → « 2027-2028 ». Une suggestion modifiable, pas une règle :
  // les établissements ne nomment pas tous leurs années de la même façon, et
  // le champ reste libre.
  function prochaine(label) {
    var m = /(\d{4})\s*[-–/]\s*(\d{4})/.exec(label || "");
    if (!m) return "";
    return (parseInt(m[1], 10) + 1) + "-" + (parseInt(m[2], 10) + 1);
  }

  function creer() {
    var msg = document.getElementById("pMsg");
    var label = document.getElementById("pCible").value.trim();
    if (!label) { msg.textContent = "Donnez un nom à la nouvelle année."; msg.className = "form-msg error"; return; }
    api.fetch("/promotion-plans", { method: "POST", body: JSON.stringify({
      source_year_id: document.getElementById("pSource").value,
      target_year_label: label,
    }) }).then(function (res) {
      if (!res.ok) { msg.textContent = erreur(res, "Impossible d'ouvrir le plan."); msg.className = "form-msg error"; return; }
      ouvrir(res.body.id);
    });
  }

  // ---- Un plan ---------------------------------------------------------

  function ouvrir(planId) {
    var url = "/promotion-plans/" + planId + (classeCourante ? "?source_class_id=" + classeCourante : "");
    api.fetch(url).then(function (res) {
      if (!res.ok) { UI.toast(erreur(res, "Plan introuvable."), "error"); return; }
      detail = res.body;
      plan = detail.plan;
      rendrePlan();
    });
  }

  function rendrePlan() {
    var e = detail.etat, st = ETATS_PLAN[plan.status] || ETATS_PLAN.BROUILLON;
    var fige = !detail.modifiable;

    document.getElementById("passageContent").innerHTML =
      '<div class="row" style="justify-content:space-between;align-items:flex-start;gap:14px;flex-wrap:wrap">'
      + "<div><h2 style=\"margin:0\">" + UI.escapeHtml(detail.source_year.label) + " → "
      + UI.escapeHtml(detail.target_year.label) + " " + UI.badge(st[0], st[1]) + "</h2>"
      + '<p class="muted" style="margin:4px 0 0">' + e.total + " élève(s) concerné(s).</p></div>"
      + '<button type="button" class="btn btn-ghost btn-sm" id="pRetour">Tous les plans</button></div>'
      + carteEtat(e, fige)
      + bandeauClasses()
      + tableau(fige);

    document.getElementById("pRetour").addEventListener("click", function () {
      classeCourante = null; plan = null; charger();
    });
    cabler(fige);
  }

  function carteEtat(e, fige) {
    // Trois compteurs distincts, parce que ce sont trois personnes
    // différentes qui doivent agir : le conseil de classe pour les décisions,
    // la Direction pour les placements, le secrétariat pour les oubliés.
    var manques = [];
    if (e.sans_decision) manques.push(e.sans_decision + " sans décision");
    if (e.sans_classe) manques.push(e.sans_classe + " sans classe d'arrivée");
    if (e.non_couverts) manques.push(e.non_couverts + " absent(s) du plan");

    var liste = (detail.bloquants || []).slice(0, 8).map(function (b) {
      return "<li><strong>" + UI.escapeHtml(b.nom) + "</strong> "
        + '<span class="muted">(' + UI.escapeHtml(b.classe || "sans classe") + ")</span> — "
        + UI.escapeHtml(b.manque) + "</li>";
    }).join("");
    var reste = (detail.bloquants_total || 0) - Math.min(8, (detail.bloquants || []).length);

    var corps = manques.length
      ? '<p style="margin:0 0 8px">Il reste <strong>' + UI.escapeHtml(manques.join(", "))
        + "</strong>. Tant qu'un élève n'a pas de sort clair, la rentrée ne peut pas s'ouvrir — "
        + "elle le laisserait derrière elle.</p>"
        + '<ul style="margin:0;padding-left:18px">' + liste
        + (reste > 0 ? '<li class="muted">et ' + reste + " autre(s)…</li>" : "") + "</ul>"
      : '<p style="margin:0">Chaque élève a un sort et, s\'il revient, une classe. '
        + "Le plan peut être validé puis appliqué.</p>";

    var actions = [];
    if (!fige) {
      actions.push('<button type="button" class="btn btn-ghost btn-sm" id="pClasses">'
        + "Copier les classes de l'an dernier</button>");
      actions.push('<button type="button" class="btn btn-ghost btn-sm" id="pRefresh">'
        + "Reprendre les décisions</button>");
    }
    if (plan.status === "BROUILLON" || plan.status === "EN_REVUE") {
      actions.push('<button type="button" class="btn btn-lime btn-sm" id="pValider"'
        + (e.applicable ? "" : " disabled") + ">Valider le plan</button>");
    }
    if (plan.status === "VALIDE") {
      actions.push('<button type="button" class="btn btn-ghost btn-sm" id="pRouvrir">Rouvrir</button>');
      actions.push('<button type="button" class="btn btn-lime btn-sm" id="pAppliquer">'
        + "Ouvrir la nouvelle année</button>");
    }
    if (plan.status === "APPLIQUE") {
      actions.push('<span class="muted">Ce plan a été appliqué : l\'année '
        + UI.escapeHtml(detail.target_year.label) + " est ouverte.</span>");
    }

    return '<div class="panel" style="margin-top:16px"><div class="panel-head"><h2>Où en est la rentrée</h2></div>'
      + corps + '<div class="row" style="gap:10px;flex-wrap:wrap;margin-top:12px">'
      + actions.join("") + "</div></div>";
  }

  function bandeauClasses() {
    var opts = '<option value="">— Toutes les classes —</option>'
      + detail.classes_source.map(function (c) {
        return '<option value="' + c.id + '"' + (c.id === classeCourante ? " selected" : "") + ">"
          + UI.escapeHtml(c.name) + " (" + c.total + ")"
          + (c.a_placer ? " — " + c.a_placer + " à placer" : "") + "</option>";
      }).join("");

    var cibles = detail.classes_cible.length
      ? detail.classes_cible.map(function (c) {
          return '<label class="row" style="gap:6px;align-items:center;margin:0">'
            + '<input type="checkbox" class="pCible" value="' + c.id + '" />'
            + "<span>" + UI.escapeHtml(c.name) + ' <span class="muted">(' + c.planned + ")</span></span></label>";
        }).join("")
      : '<span class="muted">Aucune classe dans l\'année d\'arrivée. '
        + "Copiez celles de l'an dernier, ou créez-les depuis Élèves &amp; classes.</span>";

    // CRÉER UNE CLASSE DANS L'ANNÉE D'ARRIVÉE.
    //
    // Sans cela, la répartition A/B/C était impossible : la page Élèves &
    // classes ne travaille que sur l'année EN COURS, et l'année d'arrivée est
    // en préparation. On ne pouvait donc que recopier les classes de l'an
    // dernier — jamais en ouvrir une nouvelle, ce qui est pourtant le cas le
    // plus fréquent quand un effectif grossit.
    var creation = detail.modifiable
      ? '<div class="row" style="gap:10px;flex-wrap:wrap;align-items:center;margin-top:12px">'
        + '<input type="text" id="pNouvelle" placeholder="Nouvelle classe (ex. 6e A)" '
        + 'style="min-width:190px;border:1px solid var(--line);border-radius:10px;padding:9px 12px;font:inherit;background:var(--surface);color:var(--ink)" />'
        + '<input type="text" id="pNiveau" placeholder="Niveau (facultatif)" '
        + 'style="min-width:150px;border:1px solid var(--line);border-radius:10px;padding:9px 12px;font:inherit;background:var(--surface);color:var(--ink)" />'
        + '<button type="button" class="btn btn-ghost btn-sm" id="pAjouterClasse">Ajouter à '
        + UI.escapeHtml(detail.target_year.label) + "</button></div>"
      : "";

    var repartition = detail.modifiable && classeCourante
      ? '<div class="panel" style="margin-top:16px"><div class="panel-head"><h2>Répartir cette classe</h2>'
        + '<span class="sub">Cochez les classes d\'arrivée. Klassio équilibre les effectifs entre '
        + "elles — il ne choisit pas lesquelles.</span></div>"
        + '<div class="row" style="gap:14px;flex-wrap:wrap;align-items:center">' + cibles + "</div>" + creation
        + '<div class="row" style="gap:10px;margin-top:12px;flex-wrap:wrap">'
        + '<button type="button" class="btn btn-lime btn-sm" id="pRepartir">Répartir les non placés</button>'
        + '<button type="button" class="btn btn-ghost btn-sm" id="pRepartirTout">Tout reprendre</button>'
        + "</div></div>"
      : "";

    return '<div class="panel" style="margin-top:16px"><div class="panel-head"><h2>Classe de départ</h2>'
      + '<span class="sub">Choisissez une classe pour répartir ses élèves.</span></div>'
      + '<select id="pClasse" style="min-width:240px">' + opts + "</select>"
      + (repartition ? "" : creation) + "</div>" + repartition;
  }

  function tableau(fige) {
    var optCibles = detail.classes_cible.map(function (c) {
      return '<option value="' + c.id + '">' + UI.escapeHtml(c.name) + "</option>";
    }).join("");

    var lignes = detail.assignments.map(function (a) {
      // L'ORIGINE EST AFFICHÉE. Une décision reprise de la délibération, un
      // placement proposé par la répartition et un arbitrage de la Direction
      // n'ont pas le même poids : les confondre rendrait impossible de savoir
      // ce qui a été décidé par un humain.
      var source = a.origin === "DELIBERATION" ? "Délibération"
        : a.origin === "BULLETIN" ? "Décision de fin d'année"
        : a.origin === "PROPOSITION" ? "Proposé" : a.origin === "MANUEL" ? "Vous" : "—";
      var sel = fige
        ? ton(a.action)
        : '<select data-action="' + a.student_id + '">'
          + (detail.actions_ordre || Object.keys(detail.actions)).map(function (k) {
              return '<option value="' + k + '"' + (k === a.action ? " selected" : "") + ">"
                + UI.escapeHtml(detail.actions[k]) + "</option>";
            }).join("") + "</select>";
      var cible = fige
        ? UI.escapeHtml(a.target_class_name || "—")
        : (a.action === "PASSAGE" || a.action === "REDOUBLEMENT"
            ? '<select data-cible="' + a.student_id + '"><option value="">— à placer —</option>'
              + optCibles.replace('value="' + a.target_class_id + '"',
                                  'value="' + a.target_class_id + '" selected') + "</select>"
            : '<span class="muted">—</span>');

      return "<tr>"
        + "<td><strong>" + UI.escapeHtml(a.last_name + " " + a.first_name) + "</strong>"
        + '<div class="muted" style="font-size:12px">' + UI.escapeHtml(a.code || "") + "</div></td>"
        + "<td>" + UI.escapeHtml(a.source_class_name || "—") + "</td>"
        + "<td>" + sel + "</td>"
        + "<td>" + cible + "</td>"
        + '<td class="muted">' + UI.escapeHtml(source) + "</td>"
        + '<td class="muted">' + UI.escapeHtml(a.note || "") + "</td></tr>";
    }).join("");

    if (!lignes) {
      lignes = '<tr><td colspan="6" class="muted" style="padding:18px 0">Aucun élève.</td></tr>';
    }
    return '<div class="panel" style="margin-top:16px"><div class="panel-head"><h2>Élèves</h2>'
      + '<span class="sub">Chaque élève de l\'année qui se termine, sans exception.</span></div>'
      + '<div class="table-wrap"><table class="table"><thead><tr><th>Élève</th><th>Classe actuelle</th>'
      + "<th>Situation</th><th>Classe d'arrivée</th><th>Origine</th><th>Note</th></tr></thead><tbody>"
      + lignes + "</tbody></table></div></div>";
  }

  // ---- Câblage ---------------------------------------------------------

  function cabler(fige) {
    var sel = document.getElementById("pClasse");
    if (sel) sel.addEventListener("change", function () {
      classeCourante = sel.value || null;
      ouvrir(plan.id);
    });

    var boutons = {
      pClasses: function () {
        api.fetch("/promotion-plans/" + plan.id + "/copy-classes", { method: "POST" })
          .then(function (res) {
            if (!res.ok) { UI.toast(erreur(res, "Impossible."), "error"); return; }
            UI.toast(res.body.creees + " classe(s) créée(s) dans la nouvelle année.", "ok");
            ouvrir(plan.id);
          });
      },
      pRefresh: function () {
        api.fetch("/promotion-plans/" + plan.id + "/refresh", { method: "POST" })
          .then(function (res) {
            if (!res.ok) { UI.toast(erreur(res, "Impossible."), "error"); return; }
            var b = res.body;
            UI.toast(b.ajoutes + " élève(s) ajouté(s), " + b.repris + " décision(s) reprise(s).", "ok");
            ouvrir(plan.id);
          });
      },
      pValider: function () { statut("VALIDE", "Plan validé."); },
      pRouvrir: function () { statut("BROUILLON", "Plan rouvert."); },
      pAppliquer: appliquer,
      pAjouterClasse: function () {
        var nom = document.getElementById("pNouvelle").value.trim();
        if (!nom) { UI.toast("Donnez un nom à la classe.", "warn"); return; }
        api.fetch("/classes", { method: "POST", body: JSON.stringify({
          academic_year_id: detail.target_year.id, name: nom,
          level: document.getElementById("pNiveau").value.trim() || null,
        }) }).then(function (res) {
          if (!res.ok) { UI.toast(erreur(res, "Création refusée."), "error"); return; }
          UI.toast(nom + " ajoutée à " + detail.target_year.label + ".", "ok");
          ouvrir(plan.id);
        });
      },
      pRepartir: function () { repartir(false); },
      pRepartirTout: function () { repartir(true); },
    };
    Object.keys(boutons).forEach(function (id) {
      var b = document.getElementById(id);
      if (b) b.addEventListener("click", boutons[id]);
    });

    if (fige) return;
    Array.prototype.forEach.call(document.querySelectorAll("[data-action]"), function (s) {
      s.addEventListener("change", function () {
        enregistrer(s.dataset.action, { action: s.value });
      });
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-cible]"), function (s) {
      s.addEventListener("change", function () {
        enregistrer(s.dataset.cible, { target_class_id: s.value || null });
      });
    });
  }

  function enregistrer(studentId, patch) {
    api.fetch("/promotion-plans/" + plan.id + "/assignments/" + studentId,
              { method: "PATCH", body: JSON.stringify(patch) })
      .then(function (res) {
        if (!res.ok) { UI.toast(erreur(res, "Refusé."), "error"); ouvrir(plan.id); return; }
        ouvrir(plan.id);
      });
  }

  function repartir(remplacer) {
    var cibles = Array.prototype.map.call(
      document.querySelectorAll(".pCible:checked"), function (c) { return c.value; });
    if (!cibles.length) { UI.toast("Cochez au moins une classe d'arrivée.", "warn"); return; }
    var suite = remplacer
      ? UI.confirm("Tout reprendre",
          "Les élèves déjà placés à la main dans cette classe seront replacés par l'équilibrage. "
          + "Vos corrections seront perdues.", "Reprendre")
      : Promise.resolve(true);
    suite.then(function (ok) {
      if (!ok) return;
      api.fetch("/promotion-plans/" + plan.id + "/distribute", { method: "POST", body: JSON.stringify({
        source_class_id: classeCourante, target_class_ids: cibles, replace: remplacer,
      }) }).then(function (res) {
        if (!res.ok) { UI.toast(erreur(res, "Répartition impossible."), "error"); return; }
        UI.toast(res.body.places + " élève(s) placé(s).", "ok");
        ouvrir(plan.id);
      });
    });
  }

  function statut(cible, message) {
    api.fetch("/promotion-plans/" + plan.id + "/status",
              { method: "POST", body: JSON.stringify({ status: cible }) })
      .then(function (res) {
        if (!res.ok) { UI.toast(erreur(res, "Refusé."), "error"); ouvrir(plan.id); return; }
        UI.toast(message, "ok");
        ouvrir(plan.id);
      });
  }

  function appliquer() {
    var e = detail.etat;
    // L'acte le plus lourd du logiciel : il déplace tous les élèves et change
    // l'année de tout l'établissement. La confirmation dit exactement ce qui
    // va se passer, en chiffres, et qu'on ne revient pas en arrière.
    UI.confirm(
      "Ouvrir " + detail.target_year.label,
      (e.par_action.PASSAGE || 0) + " élève(s) passent, "
      + (e.par_action.REDOUBLEMENT || 0) + " redoublent, "
      + (e.par_action.DEPART || 0) + " ne reviennent pas. "
      + detail.source_year.label + " sera archivée — consultable, jamais supprimée — et "
      + detail.target_year.label + " deviendra l'année en cours pour tout l'établissement. "
      + "Cette opération ne s'annule pas.",
      "Ouvrir la nouvelle année"
    ).then(function (ok) {
      if (!ok) return;
      api.fetch("/promotion-plans/" + plan.id + "/apply",
                { method: "POST", body: JSON.stringify({ confirm: true }) })
        .then(function (res) {
          if (!res.ok) { UI.toast(erreur(res, "Application refusée."), "error"); ouvrir(plan.id); return; }
          UI.toast(res.body.deplaces + " élève(s) inscrit(s) dans la nouvelle année.", "ok");
          ouvrir(plan.id);
        });
    });
  }

  // ---- Démarrage -------------------------------------------------------

  function charger() {
    return api.fetch("/promotion-plans").then(function (res) {
      if (!res.ok) { UI.toast(erreur(res, "Chargement impossible."), "error"); return; }
      plans = res.body.plans || [];
      annees = res.body.academic_years || [];
      rendreListe();
    });
  }

  admin.initShell("passage").then(function (c) {
    ctx = c;
    if (c.role !== "directeur") {
      document.getElementById("passageContent").innerHTML = UI.emptyState(
        "Réservé à la Direction",
        "Le passage d'année engage toute l'école. Votre contribution au sort de vos élèves se "
        + "dépose en délibération, sous forme d'avis.",
        '<a href="' + UI.homeFor(c.role) + '" class="btn btn-ghost btn-sm">Retour à l\'accueil</a>', "lock");
      return;
    }
    charger();
  });
})();
