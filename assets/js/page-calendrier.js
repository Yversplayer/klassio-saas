// KLASSIO — Calendrier : un agenda complet (08/10/2026).
//
// Le propriétaire : « la partie calendrier n'est pas suffisamment travaillée ;
// je veux un calendrier géant, qu'on fait passer de mois en mois, avec les
// années, les jours, les dates, à partir duquel on entre événements et
// périodes — comme un agenda virtuel, mais Klassio ». Modèle fourni : un
// agenda à mini-calendrier, catégories et vues Mois / Semaine / Jour ; et un
// composant React « glass calendar » (bande de jours, mois animé). Klassio
// n'a ni React ni bundler (AGENTS.md §10, piège 1) : l'effet est porté ici en
// JavaScript natif, sans bibliothèque.
//
// Les DONNÉES n'ont pas changé : GET /api/calendar (par mois, déjà filtré par
// rôle côté serveur) et GET /api/academic-calendar (les périodes de l'année).
// L'agenda n'invente rien : un élément sans heure s'affiche « toute la
// journée », un élément avec heure à son heure, sans durée inventée au-delà
// d'un créneau d'une heure pour le dessiner.
//
// Direction et DD publient événements et communiqués ; la Direction déclare
// les périodes (POST /api/periods) et, pour une année neuve, reprend le
// calendrier de l'année précédente (POST /api/periods/copy-previous).
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi, admin = window.KlassioAdmin;
  var ctx = null, classes = [];
  var curseur = UI.qs("date") || UI.todayIso();          // jour sélectionné (AAAA-MM-JJ)
  var vue = "mois";
  try { vue = localStorage.getItem("klassio_agenda_vue") || "mois"; } catch (e) {}
  if (["mois", "semaine", "jour"].indexOf(vue) < 0) vue = "mois";
  var feeds = {};                                        // AAAA-MM → réponse /calendar
  var periodes = [], anneeLabel = "", precedent = null, examen = {};
  var filtres = { evenements: true, examens: true, devoirs: true, echeances: true, convocations: true, presences: true, periodes: true };
  var sens = 0;                                          // -1 / +1 : direction de la dernière navigation

  var MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];
  var JOURS_COURTS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
  var HEURE_DEBUT = 7, HEURE_FIN = 18;

  // Chaque type d'élément appartient à une famille (filtre) et à une couleur.
  var FAMILLE = { evenement: "evenements", communique: "evenements", reunion: "evenements", fete: "evenements", deuil: "evenements", conge: "evenements",
                  examens: "examens", examen: "examens", devoir: "devoirs", echeance: "echeances", convocation: "convocations",
                  presence_present: "presences", presence_late: "presences", presence_absent: "presences", presence_excused: "presences" };
  var TEINTE = { evenement: "lime", fete: "lime", conge: "ciel", communique: "lavande", reunion: "lavande", deuil: "gris",
                 examens: "corail", examen: "corail", convocation: "corail", devoir: "ciel", echeance: "or",
                 presence_present: "lime", presence_late: "or", presence_absent: "corail", presence_excused: "ciel" };
  var FAMILLES = [["evenements", "Événements & communiqués", "lavande"], ["examens", "Examens", "corail"], ["devoirs", "Devoirs", "ciel"],
                  ["echeances", "Échéances de frais", "or"], ["convocations", "Convocations", "corail"], ["presences", "Présences", "lime"], ["periodes", "Périodes de l'année", "foret"]];

  function publie() { return ctx && (ctx.role === "directeur" || ctx.role === "discipline"); }
  function direction() { return ctx && ctx.role === "directeur"; }

  // ---------------- Dates (sans fuseau : AAAA-MM-JJ partout) ----------------
  function iso(d) { return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); }
  function dateDe(s) { return new Date(s.slice(0, 4), parseInt(s.slice(5, 7), 10) - 1, parseInt(s.slice(8, 10), 10)); }
  function plusJours(s, n) { var d = dateDe(s); d.setDate(d.getDate() + n); return iso(d); }
  function lundiDe(s) { var d = dateDe(s); var dow = (d.getDay() + 6) % 7; d.setDate(d.getDate() - dow); return iso(d); }
  function moisDe(s) { return s.slice(0, 7); }
  function titreMois(s) { var d = dateDe(s); return MOIS[d.getMonth()] + " " + d.getFullYear(); }

  document.getElementById("calContent").innerHTML = UI.skeleton("card", 2);

  admin.initShell("calendrier").then(function (c) {
    ctx = c;
    if (publie()) api.fetch("/classes").then(function (r) { classes = r.ok ? r.body : []; });
    var appels = [api.fetch("/academic-calendar")];
    if (direction()) appels.push(api.fetch("/periods/previous-calendar"));
    Promise.all(appels).then(function (r) {
      lirePeriodes(r[0] && r[0].ok ? r[0].body : null);
      precedent = r[1] && r[1].ok && r[1].body.available ? r[1].body : null;
      charger();
    });
  });

  function lirePeriodes(cal) {
    periodes = []; anneeLabel = "";
    if (!cal) return;
    anneeLabel = cal.academic_year ? cal.academic_year.label : "";
    var vues = {};
    (cal.divisions || []).forEach(function (d) {
      (d.periods || []).forEach(function (p) {
        if (vues[p.id] || !p.starts_on) return;
        vues[p.id] = 1;
        periodes.push({ id: p.id, label: p.label, debut: p.starts_on, fin: p.ends_on || p.starts_on, poids: p.weight, examen: !!p.is_exam });
      });
    });
    periodes.sort(function (a, b) { return a.debut < b.debut ? -1 : 1; });
  }

  // Les mois nécessaires à la vue (une semaine peut chevaucher deux mois).
  function moisUtiles() {
    if (vue === "mois") return [moisDe(curseur)];
    var l = lundiDe(curseur);
    return vue === "semaine" ? [moisDe(l), moisDe(plusJours(l, 6))] : [moisDe(curseur)];
  }

  function charger() {
    var hote = document.getElementById("calContent");
    var manquants = moisUtiles().filter(function (m, i, t) { return !feeds[m] && t.indexOf(m) === i; });
    if (!manquants.length) return rendre();
    if (!hote.querySelector(".ka-ag")) hote.innerHTML = UI.skeleton("card", 2);
    Promise.all(manquants.map(function (m) { return api.fetch("/calendar?month=" + m); })).then(function (r) {
      if (r.some(function (x) { return !x.ok; })) return admin.loadError(hote, charger, "Impossible de charger le calendrier");
      r.forEach(function (x, i) { feeds[manquants[i]] = x.body; examen = x.body.exam_period || examen; });
      rendre();
    }).catch(function () { admin.loadError(hote, charger, "Le serveur Klassio est injoignable"); });
  }

  // Tous les éléments d'un jour, filtres appliqués.
  function elementsDu(jour) {
    var f = feeds[moisDe(jour)];
    if (!f) return [];
    return f.items.filter(function (i) {
      if (!i.date) return false;
      var fin = i.end || i.date;
      return i.date <= jour && fin >= jour && filtres[FAMILLE[i.kind] || "evenements"] !== false;
    });
  }
  function periodesDu(jour) {
    if (!filtres.periodes) return [];
    return periodes.filter(function (p) { return p.debut <= jour && p.fin >= jour; });
  }

  // ---------------- Rendu d'ensemble ----------------
  function rendre() {
    var hote = document.getElementById("calContent");
    var premiere = !hote.querySelector(".ka-ag");
    if (premiere) {
      hote.innerHTML = '<div class="ka-ag">' +
        '<aside class="ka-ag-side" id="agSide"></aside>' +
        '<section class="ka-ag-main"><header class="ka-ag-head" id="agHead"></header>' +
        '<div class="ka-ag-bande" id="agBande" role="listbox" aria-label="Jours du mois"></div>' +
        '<div class="ka-ag-scene"><div class="ka-ag-vue" id="agVue"></div></div></section></div>' +
        (publie() ? '<div class="panel"><div class="panel-head"><h2>Publications</h2><span class="sub">Vos événements et communiqués</span></div><div id="myEvents">' + UI.skeleton("row", 2) + "</div></div>" : "");
      if (publie()) loadMine();
    }
    rendreTete();
    rendreBande();
    rendreCote();
    var cible = document.getElementById("agVue");
    cible.innerHTML = vue === "mois" ? vueMois() : vueGrille(vue === "semaine" ? 7 : 1);
    // Le « tourner de page » 3D : rejoué à chaque navigation, dans le sens du
    // déplacement. Sans mouvement (préférence système), il n'est jamais posé.
    cible.classList.remove("ka-ag-avant", "ka-ag-arriere");
    if (sens) { void cible.offsetWidth; cible.classList.add(sens > 0 ? "ka-ag-avant" : "ka-ag-arriere"); }
    sens = 0;
    brancherVue(cible);
    var sel = document.querySelector('#agBande [aria-selected="true"]');
    if (sel && sel.scrollIntoView) sel.scrollIntoView({ block: "nearest", inline: "center" });
  }

  function rendreTete() {
    var titre = vue === "mois" ? titreMois(curseur)
      : vue === "semaine" ? semaineTitre(lundiDe(curseur))
      : UI.fmtDate(curseur);
    var courante = periodes.filter(function (p) { return p.debut <= UI.todayIso() && p.fin >= UI.todayIso(); })[0];
    var h = document.getElementById("agHead");
    h.innerHTML =
      '<div class="ka-ag-titre-bloc"><button type="button" class="ka-ag-titre" id="agPicker" aria-haspopup="dialog" title="Choisir un mois ou une année">' +
        '<span class="ka-ag-titre-txt" key="' + UI.escapeHtml(titre) + '">' + UI.escapeHtml(titre) + "</span>" + UI.icon("chevronDown", 18) + "</button>" +
        '<span class="ka-ag-sous">' + (anneeLabel ? "Année scolaire " + UI.escapeHtml(anneeLabel) : "") + (courante ? " · " + UI.escapeHtml(courante.label) + " en cours" : "") + "</span></div>" +
      '<div class="ka-ag-nav"><div class="ka-ag-fleches"><button type="button" class="icon-btn" id="agPrev" aria-label="Précédent">' + UI.icon("chevronLeft", 16) + '</button>' +
        '<button type="button" class="btn btn-ghost btn-sm" id="agToday">Aujourd\'hui</button>' +
        '<button type="button" class="icon-btn" id="agNext" aria-label="Suivant">' + UI.icon("chevronRight", 16) + "</button></div>" +
        '<div class="ka-ag-vues" role="tablist" aria-label="Affichage">' + [["mois", "Mois"], ["semaine", "Semaine"], ["jour", "Jour"]].map(function (v) {
          return '<button type="button" role="tab" data-vue="' + v[0] + '" aria-selected="' + (vue === v[0]) + '">' + v[1] + "</button>";
        }).join("") + "</div>" +
        (publie() ? '<button type="button" class="btn btn-lime btn-sm" id="agNew">' + UI.icon("plus", 15) + "Nouveau</button>" : "") + "</div>";
    h.querySelector("#agPrev").addEventListener("click", function () { naviguer(-1); });
    h.querySelector("#agNext").addEventListener("click", function () { naviguer(1); });
    h.querySelector("#agToday").addEventListener("click", function () { sens = curseur < UI.todayIso() ? 1 : -1; curseur = UI.todayIso(); charger(); });
    h.querySelectorAll("[data-vue]").forEach(function (b) {
      b.addEventListener("click", function () {
        vue = b.dataset.vue;
        try { localStorage.setItem("klassio_agenda_vue", vue); } catch (e) {}
        charger();
      });
    });
    h.querySelector("#agPicker").addEventListener("click", ouvrirSelecteur);
    var n = h.querySelector("#agNew"); if (n) n.addEventListener("click", function () { menuNouveau(curseur); });
  }

  function semaineTitre(lundi) {
    var dim = plusJours(lundi, 6), a = dateDe(lundi), b = dateDe(dim);
    if (a.getMonth() === b.getMonth()) return a.getDate() + " – " + b.getDate() + " " + MOIS[b.getMonth()] + " " + b.getFullYear();
    return a.getDate() + " " + MOIS[a.getMonth()].slice(0, 4) + ". – " + b.getDate() + " " + MOIS[b.getMonth()].slice(0, 4) + ". " + b.getFullYear();
  }

  function naviguer(n) {
    sens = n;
    if (vue === "mois") { var d = dateDe(curseur); d.setDate(1); d.setMonth(d.getMonth() + n); curseur = iso(d); }
    else curseur = plusJours(curseur, vue === "semaine" ? 7 * n : n);
    charger();
  }

  // La bande de jours du mois (inspirée du « glass calendar ») : on fait
  // défiler les jours, on en touche un pour le voir.
  function rendreBande() {
    var d = dateDe(curseur), n = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate(), html = "";
    for (var j = 1; j <= n; j++) {
      var jour = moisDe(curseur) + "-" + String(j).padStart(2, "0");
      var dow = (dateDe(jour).getDay() + 6) % 7;
      var nb = elementsDu(jour).length + periodesDu(jour).length;
      html += '<button type="button" role="option" class="ka-ag-puce' + (dow > 4 ? " we" : "") + (jour === UI.todayIso() ? " auj" : "") + '" aria-selected="' + (jour === curseur) + '" data-jour="' + jour + '" aria-label="' + UI.fmtDate(jour) + '">' +
        "<small>" + JOURS_COURTS[dow].charAt(0) + "</small><b>" + j + "</b>" + (elementsDu(jour).length ? "<i></i>" : "") + "</button>";
      void nb;
    }
    var b = document.getElementById("agBande");
    b.innerHTML = html;
    b.querySelectorAll("[data-jour]").forEach(function (x) {
      x.addEventListener("click", function () { sens = x.dataset.jour > curseur ? 1 : -1; curseur = x.dataset.jour; if (vue === "mois") vue = "jour"; charger(); });
    });
  }

  // ---------------- Colonne de gauche ----------------
  function rendreCote() {
    var s = document.getElementById("agSide");
    var aVenir = [];
    Object.keys(feeds).sort().forEach(function (m) {
      feeds[m].items.forEach(function (i) { if (i.date && i.date >= UI.todayIso() && filtres[FAMILLE[i.kind] || "evenements"] !== false) aVenir.push(i); });
    });
    aVenir.sort(function (a, b) { return (a.date + (a.time || "")) < (b.date + (b.time || "")) ? -1 : 1; });
    s.innerHTML =
      '<div class="ka-ag-carte">' + miniMois() + "</div>" +
      (publie() ? '<div class="ka-ag-carte ka-ag-actions">' +
        '<button type="button" class="btn btn-lime btn-sm" data-nouveau="evenement">' + UI.icon("plus", 15) + "Événement</button>" +
        '<button type="button" class="btn btn-ghost btn-sm" data-nouveau="communique">' + UI.icon("mail", 15) + "Communiqué</button>" +
        (direction() ? '<button type="button" class="btn btn-ghost btn-sm" data-nouveau="periode">' + UI.icon("calendar", 15) + "Période</button>" : "") + "</div>" : "") +
      '<div class="ka-ag-carte"><h3>Catégories</h3><div class="ka-ag-filtres">' + FAMILLES.map(function (f) {
        return '<label class="ka-ag-filtre"><input type="checkbox" data-filtre="' + f[0] + '"' + (filtres[f[0]] ? " checked" : "") + '><span class="ka-ag-carre t-' + f[2] + '"></span>' + f[1] + "</label>";
      }).join("") + "</div></div>" +
      '<div class="ka-ag-carte"><h3>Périodes de l\'année</h3>' + blocPeriodes() + "</div>" +
      '<div class="ka-ag-carte"><h3>À venir</h3>' + (aVenir.length ? '<ul class="ka-ag-avenir">' + aVenir.slice(0, 6).map(function (i) {
        return '<li><span class="ka-ag-carre t-' + (TEINTE[i.kind] || "lavande") + '"></span><div><strong>' + UI.escapeHtml(i.title) + "</strong><em>" + UI.fmtDate(i.date) + (i.time ? " · " + UI.escapeHtml(i.time) : "") + "</em></div></li>";
      }).join("") + "</ul>" : '<p class="muted">Rien de prévu dans les mois affichés.</p>') + "</div>";
    s.querySelectorAll("[data-filtre]").forEach(function (c) {
      c.addEventListener("change", function () { filtres[c.dataset.filtre] = c.checked; rendre(); });
    });
    s.querySelectorAll("[data-nouveau]").forEach(function (b) {
      b.addEventListener("click", function () { b.dataset.nouveau === "periode" ? ouvrirPeriode(curseur) : openEventModal(b.dataset.nouveau, curseur); });
    });
    s.querySelectorAll("[data-mini]").forEach(function (b) {
      b.addEventListener("click", function () { sens = b.dataset.mini > curseur ? 1 : -1; curseur = b.dataset.mini; charger(); });
    });
    s.querySelectorAll("[data-mini-nav]").forEach(function (b) {
      b.addEventListener("click", function () { naviguerMois(parseInt(b.dataset.miniNav, 10)); });
    });
    s.querySelectorAll("[data-periode]").forEach(function (b) {
      b.addEventListener("click", function () { var p = periodes.filter(function (x) { return x.id === b.dataset.periode; })[0]; if (p) { sens = p.debut > curseur ? 1 : -1; curseur = p.debut; vue = "mois"; charger(); } });
    });
    s.querySelectorAll(".reprise-btn").forEach(function (b) {
      b.addEventListener("click", function () { reprendre(b); });
    });
  }

  function naviguerMois(n) { sens = n; var d = dateDe(curseur); d.setDate(1); d.setMonth(d.getMonth() + n); curseur = iso(d); charger(); }

  function miniMois() {
    var d = dateDe(curseur), premier = new Date(d.getFullYear(), d.getMonth(), 1);
    var n = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate(), decal = (premier.getDay() + 6) % 7;
    var cases = "";
    for (var i = 0; i < decal; i++) cases += "<span></span>";
    for (var j = 1; j <= n; j++) {
      var jour = moisDe(curseur) + "-" + String(j).padStart(2, "0");
      var marque = elementsDu(jour).length ? " a" : "";
      cases += '<button type="button" data-mini="' + jour + '" class="' + (jour === curseur ? "sel" : "") + (jour === UI.todayIso() ? " auj" : "") + marque + '" aria-label="' + UI.fmtDate(jour) + '">' + j + "</button>";
    }
    return '<div class="ka-ag-mini-tete"><strong>' + UI.escapeHtml(titreMois(curseur)) + '</strong><span><button type="button" class="icon-btn" data-mini-nav="-1" aria-label="Mois précédent">' + UI.icon("chevronLeft", 14) +
      '</button><button type="button" class="icon-btn" data-mini-nav="1" aria-label="Mois suivant">' + UI.icon("chevronRight", 14) + "</button></span></div>" +
      '<div class="ka-ag-mini">' + JOURS_COURTS.map(function (x) { return "<small>" + x.charAt(0) + x.charAt(1) + "</small>"; }).join("") + cases + "</div>";
  }

  function blocPeriodes() {
    if (periodes.length) {
      var auj = UI.todayIso();
      return '<ul class="ka-ag-periodes">' + periodes.map(function (p) {
        var etat = p.fin < auj ? "passee" : p.debut <= auj ? "encours" : "avenir";
        return '<li><button type="button" data-periode="' + UI.escapeHtml(p.id) + '" class="' + etat + '"><strong>' + UI.escapeHtml(p.label) + (p.examen ? " · examen" : "") + "</strong><em>" +
          UI.fmtDate(p.debut) + " → " + UI.fmtDate(p.fin) + (p.poids != null ? " · pondération " + UI.escapeHtml(String(p.poids)) : "") + "</em></button></li>";
      }).join("") + "</ul>" + (direction() ? '<a class="link-btn" href="etablissement.html?tab=periodes">Gérer les périodes</a>' : "");
    }
    // Année neuve : la Direction reprend le calendrier de l'an dernier ici même.
    if (direction() && precedent) {
      return '<p class="muted">Nouvelle année : reprendre le calendrier de ' + UI.escapeHtml(precedent.source_year.label) + " (" + UI.plural(precedent.periods.length, "période") + ", dates décalées d'un an) ?</p>" +
        '<div class="ka-ag-reprise"><button type="button" class="btn btn-lime btn-xs reprise-btn" data-mode="garder">Garder le même</button>' +
        '<button type="button" class="btn btn-ghost btn-xs reprise-btn" data-mode="modifier">Reprendre pour modifier</button></div>';
    }
    return '<p class="muted">Aucune période datée pour cette année.</p>' + (direction() ? '<button type="button" class="link-btn" data-nouveau="periode">Déclarer une période</button>' : "");
  }

  function reprendre(btn) {
    UI.btnState(btn, "loading");
    api.fetch("/periods/copy-previous", { method: "POST", body: JSON.stringify({ mode: btn.dataset.mode }) }).then(function (r) {
      if (!r.ok) { UI.btnState(btn, "error"); return UI.toast(r.body.error || "Impossible de reprendre le calendrier.", "error"); }
      UI.toast(UI.plural(r.body.created, "période reprise", "périodes reprises") + (btn.dataset.mode === "modifier" ? " en brouillon." : "."), "success");
      precedent = null;
      api.fetch("/academic-calendar").then(function (x) { lirePeriodes(x.ok ? x.body : null); rendre(); });
    });
  }

  // ---------------- Vue Mois ----------------
  function vueMois() {
    var d = dateDe(curseur), premier = new Date(d.getFullYear(), d.getMonth(), 1);
    var debut = lundiDe(iso(premier)), auj = UI.todayIso(), html = "";
    for (var c = 0; c < 42; c++) {
      var jour = plusJours(debut, c), horsMois = moisDe(jour) !== moisDe(curseur);
      if (c >= 35 && horsMois && moisDe(plusJours(debut, 35)) !== moisDe(curseur)) break;
      var items = horsMois ? [] : elementsDu(jour), pers = periodesDu(jour);
      var dow = c % 7;
      var exam = examen.starts && examen.ends && jour >= examen.starts && jour <= examen.ends;
      html += '<div class="ka-ag-case' + (horsMois ? " hors" : "") + (jour === auj ? " auj" : "") + (jour === curseur ? " sel" : "") + (dow > 4 ? " we" : "") + (exam ? " exam" : "") + '" data-jour="' + jour + '">' +
        '<div class="ka-ag-case-tete"><button type="button" class="ka-ag-num" data-ouvrir="' + jour + '" aria-label="Voir le ' + UI.fmtDate(jour) + '">' + dateDe(jour).getDate() + "</button>" +
        (publie() && !horsMois ? '<button type="button" class="ka-ag-plus" data-ajout="' + jour + '" aria-label="Ajouter le ' + UI.fmtDate(jour) + '">' + UI.icon("plus", 13) + "</button>" : "") + "</div>" +
        pers.map(function (p) {
          var tete = p.debut === jour || dow === 0;
          // Le nom de la période au premier jour et chaque lundi ; ailleurs, un
          // simple trait de sa couleur, qui la prolonge sans encombrer la case.
          return '<span class="ka-ag-bandeau' + (p.examen ? " ex" : "") + (tete ? "" : " suite") + '" title="' + UI.escapeHtml(p.label) + '">' + (tete ? UI.escapeHtml(p.label) : "") + "</span>";
        }).join("") +
        items.slice(0, 3).map(function (i, k) { return pastille(i, jour + ":" + k); }).join("") +
        (items.length > 3 ? '<button type="button" class="ka-ag-encore" data-ouvrir="' + jour + '">+ ' + (items.length - 3) + " de plus</button>" : "") + "</div>";
    }
    return '<div class="ka-ag-mois"><div class="ka-ag-sem">' + JOURS_COURTS.map(function (x) { return "<span>" + x + "</span>"; }).join("") + '</div><div class="ka-ag-cases">' + html + "</div></div>";
  }

  var registre = {};   // clé → élément, pour retrouver ce qu'on a touché
  function pastille(i, cle) {
    registre[cle] = i;
    return '<button type="button" class="ka-ag-pastille t-' + (TEINTE[i.kind] || "lavande") + '" data-el="' + UI.escapeHtml(cle) + '" title="' + UI.escapeHtml(i.title) + '">' +
      (i.time ? "<b>" + UI.escapeHtml(i.time) + "</b> " : "") + UI.escapeHtml(i.title) + "</button>";
  }

  // ---------------- Vues Semaine et Jour (grille horaire) ----------------
  function vueGrille(nbJours) {
    var debut = nbJours === 7 ? lundiDe(curseur) : curseur, auj = UI.todayIso();
    var jours = []; for (var i = 0; i < nbJours; i++) jours.push(plusJours(debut, i));
    var tetes = jours.map(function (j) {
      var d = dateDe(j), dow = (d.getDay() + 6) % 7;
      return '<button type="button" class="ka-ag-col-tete' + (j === auj ? " auj" : "") + (j === curseur ? " sel" : "") + '" data-ouvrir="' + j + '"><small>' + JOURS_COURTS[dow] + "</small><b>" + d.getDate() + "</b></button>";
    }).join("");
    var journee = jours.map(function (j) {
      var sansHeure = elementsDu(j).filter(function (x) { return !x.time; });
      return '<div class="ka-ag-journee-col">' + periodesDu(j).map(function (p) {
        return '<span class="ka-ag-bandeau' + (p.examen ? " ex" : "") + '">' + UI.escapeHtml(p.label) + "</span>";
      }).join("") + sansHeure.map(function (x, k) { return pastille(x, j + ":j" + k); }).join("") + "</div>";
    }).join("");
    var heures = "";
    for (var h = HEURE_DEBUT; h <= HEURE_FIN; h++) heures += '<div class="ka-ag-heure"><span>' + h + " h</span></div>";
    var colonnes = jours.map(function (j) {
      var avecHeure = elementsDu(j).filter(function (x) { return x.time; });
      // Deux éléments à la même heure se partagent la largeur au lieu de se
      // recouvrir.
      var parHeure = {};
      avecHeure.forEach(function (x) { var hh = parseInt(x.time.slice(0, 2), 10) || HEURE_DEBUT; (parHeure[hh] = parHeure[hh] || []).push(x); });
      var blocs = "";
      Object.keys(parHeure).forEach(function (hh) {
        var groupe = parHeure[hh];
        groupe.forEach(function (x, k) {
          var heure = Math.min(Math.max(parseInt(hh, 10), HEURE_DEBUT), HEURE_FIN);
          var minutes = parseInt(x.time.slice(3, 5), 10) || 0;
          var haut = ((heure - HEURE_DEBUT) + minutes / 60) * 56;
          var cle = j + ":h" + hh + ":" + k; registre[cle] = x;
          blocs += '<button type="button" class="ka-ag-bloc t-' + (TEINTE[x.kind] || "lavande") + '" data-el="' + UI.escapeHtml(cle) + '" style="top:' + haut.toFixed(1) + "px;left:calc(" + (100 / groupe.length * k) + "% + 3px);width:calc(" + (100 / groupe.length) + '% - 6px)">' +
            "<strong>" + UI.escapeHtml(x.title) + "</strong><em>" + UI.escapeHtml(x.time) + (x.body ? " · " + UI.escapeHtml(x.body) : "") + "</em></button>";
        });
      });
      var maintenant = "";
      if (j === auj) {
        var t = new Date(), pos = (t.getHours() - HEURE_DEBUT + t.getMinutes() / 60) * 56;
        if (pos >= 0 && pos <= (HEURE_FIN - HEURE_DEBUT + 1) * 56) maintenant = '<span class="ka-ag-maintenant" style="top:' + pos.toFixed(1) + 'px"></span>';
      }
      return '<div class="ka-ag-col' + (j === auj ? " auj" : "") + '" data-jour="' + j + '">' + blocs + maintenant + "</div>";
    }).join("");
    return '<div class="ka-ag-grille ka-ag-n' + nbJours + '">' +
      '<div class="ka-ag-g-tete"><span class="ka-ag-coin">' + UI.icon("clock", 14) + "</span>" + tetes + "</div>" +
      '<div class="ka-ag-g-journee"><span class="ka-ag-coin">Journée</span>' + journee + "</div>" +
      '<div class="ka-ag-g-corps"><div class="ka-ag-heures">' + heures + '</div><div class="ka-ag-cols">' + colonnes + "</div></div></div>";
  }

  function brancherVue(v) {
    v.querySelectorAll("[data-el]").forEach(function (b) {
      b.addEventListener("click", function (e) { e.stopPropagation(); detail(registre[b.dataset.el]); });
    });
    v.querySelectorAll("[data-ouvrir]").forEach(function (b) {
      b.addEventListener("click", function (e) { e.stopPropagation(); sens = b.dataset.ouvrir > curseur ? 1 : -1; curseur = b.dataset.ouvrir; vue = "jour"; charger(); });
    });
    v.querySelectorAll("[data-ajout]").forEach(function (b) {
      b.addEventListener("click", function (e) { e.stopPropagation(); menuNouveau(b.dataset.ajout); });
    });
    v.querySelectorAll(".ka-ag-case[data-jour]").forEach(function (c) {
      c.addEventListener("click", function () {
        if (c.classList.contains("hors")) return;
        curseur = c.dataset.jour;
        document.querySelectorAll(".ka-ag-case.sel").forEach(function (x) { x.classList.remove("sel"); });
        c.classList.add("sel");
        rendreBande(); rendreCote();
      });
      c.addEventListener("dblclick", function () { if (publie() && !c.classList.contains("hors")) menuNouveau(c.dataset.jour); });
    });
  }

  // ---------------- Détail, sélecteur, création ----------------
  function detail(i) {
    if (!i) return;
    var corps = '<div class="ka-ag-detail"><span class="ka-ag-carre t-' + (TEINTE[i.kind] || "lavande") + '"></span>' + UI.badge(UI.EVENT_KIND_TONES[i.kind] || "neutral", UI.EVENT_KIND_LABELS[i.kind] || i.kind) + "</div>" +
      '<p class="ka-ag-quand">' + UI.icon("calendar", 15) + UI.fmtDate(i.date) + (i.end && i.end !== i.date ? " → " + UI.fmtDate(i.end) : "") + (i.time ? " · " + UI.escapeHtml(i.time) : " · toute la journée") + "</p>" +
      (i.body ? '<p class="modal-text">' + UI.escapeHtml(i.body) + "</p>" : "");
    UI.modal({ title: i.title, body: corps, footer: i.link && i.link !== "calendrier.html" ? '<a class="btn btn-lime btn-sm" href="' + UI.escapeHtml(i.link) + '">Ouvrir</a>' : "" });
  }

  function ouvrirSelecteur() {
    var annee = dateDe(curseur).getFullYear(), moisCourant = dateDe(curseur).getMonth();
    function corps() {
      return '<div class="ka-ag-annee"><button type="button" class="icon-btn" id="pkPrev" aria-label="Année précédente">' + UI.icon("chevronLeft", 16) + '</button><strong id="pkAn">' + annee +
        '</strong><button type="button" class="icon-btn" id="pkNext" aria-label="Année suivante">' + UI.icon("chevronRight", 16) + "</button></div>" +
        '<div class="ka-ag-mois-choix">' + MOIS.map(function (m, i) {
          return '<button type="button" data-m="' + i + '" class="' + (i === moisCourant && annee === dateDe(curseur).getFullYear() ? "sel" : "") + '">' + m.charAt(0).toUpperCase() + m.slice(1) + "</button>";
        }).join("") + "</div>";
    }
    var m = UI.modal({ title: "Aller à…", body: '<div id="pkCorps">' + corps() + "</div>" });
    function brancher() {
      m.querySelector("#pkPrev").addEventListener("click", function () { annee--; m.querySelector("#pkCorps").innerHTML = corps(); brancher(); });
      m.querySelector("#pkNext").addEventListener("click", function () { annee++; m.querySelector("#pkCorps").innerHTML = corps(); brancher(); });
      m.querySelectorAll("[data-m]").forEach(function (b) {
        b.addEventListener("click", function () {
          var cible = annee + "-" + String(parseInt(b.dataset.m, 10) + 1).padStart(2, "0") + "-01";
          sens = cible > curseur ? 1 : -1; curseur = cible; vue = "mois";
          UI.closeModal(); charger();
        });
      });
    }
    brancher();
  }

  function menuNouveau(jour) {
    if (!direction()) return openEventModal("evenement", jour);
    var m = UI.modal({ title: "Le " + UI.fmtDate(jour), body: '<div class="ka-ag-choix">' +
      '<button type="button" data-k="evenement">' + UI.icon("plus", 18) + "<strong>Événement</strong><span>Réunion, fête, congé, examens… notifié aux personnes concernées</span></button>" +
      '<button type="button" data-k="communique">' + UI.icon("mail", 18) + "<strong>Communiqué</strong><span>Une information envoyée aux parents ou au personnel</span></button>" +
      '<button type="button" data-k="periode">' + UI.icon("calendar", 18) + "<strong>Période</strong><span>Une période de l'année scolaire, avec sa pondération</span></button></div>" });
    m.querySelectorAll("[data-k]").forEach(function (b) {
      b.addEventListener("click", function () { UI.closeModal(); setTimeout(function () { b.dataset.k === "periode" ? ouvrirPeriode(jour) : openEventModal(b.dataset.k, jour); }, 230); });
    });
  }

  // Une période de l'année, déclarée depuis l'agenda : même route et mêmes
  // contrôles que dans Établissement → Périodes (dates cohérentes, libellé
  // unique par année, Direction seulement — vérifié par le serveur).
  function ouvrirPeriode(jour) {
    var m = UI.modal({ title: "Nouvelle période", body:
      '<form id="pdForm" class="form-grid">' +
      '<div class="field full"><label for="pdLabel">Libellé</label><input id="pdLabel" required maxlength="40" placeholder="Ex. Période 1, Examen 1er semestre" /></div>' +
      '<div class="field"><label for="pdDebut">Début</label><input id="pdDebut" type="date" value="' + UI.escapeHtml(jour || "") + '" required /></div>' +
      '<div class="field"><label for="pdFin">Fin</label><input id="pdFin" type="date" required /></div>' +
      '<div class="field"><label for="pdPoids">Pondération</label><input id="pdPoids" type="number" step="0.5" min="0.5" value="1" /></div>' +
      '<label class="check field"><input type="checkbox" id="pdExam"> C\'est une période d\'examen</label>' +
      '<p class="form-error full" id="pdErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="pdCancel">Annuler</button><button type="submit" form="pdForm" class="btn btn-lime btn-sm" id="pdOk">Créer la période</button>' });
    m.querySelector("#pdCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#pdForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#pdOk"), err = m.querySelector("#pdErr"); err.hidden = true;
      UI.btnState(btn, "loading", "Création…");
      api.fetch("/periods", { method: "POST", body: JSON.stringify({
        label: m.querySelector("#pdLabel").value.trim(), starts_on: m.querySelector("#pdDebut").value || null,
        ends_on: m.querySelector("#pdFin").value || null, weight: parseFloat(m.querySelector("#pdPoids").value) || 1,
        is_exam: m.querySelector("#pdExam").checked, sort: periodes.length }) }).then(function (r) {
        if (!r.ok) { UI.btnState(btn, "error"); err.textContent = r.body.error || "Impossible de créer la période."; err.hidden = false; return; }
        UI.btnState(btn, "success", "Créée"); UI.toast("Période créée.", "success");
        api.fetch("/academic-calendar").then(function (x) { lirePeriodes(x.ok ? x.body : null); precedent = null; UI.closeModal(); rendre(); });
      }).catch(function () { UI.btnState(btn, "error"); });
    });
  }

  function loadMine() {
    api.fetch("/calendar/events").then(function (res) {
      var host = document.getElementById("myEvents"); if (!host || !res.ok) return;
      var mine = res.body.filter(function (e) { return e.can_delete; });
      if (!mine.length) { host.innerHTML = '<p class="muted">Aucune publication pour le moment.</p>'; return; }
      host.innerHTML = '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Type</th><th>Titre</th><th>Date</th><th>Cible</th><th>Audience</th><th class="actions"></th></tr></thead><tbody>' + mine.slice(0, 40).map(function (e) {
        return '<tr><td data-label="Type">' + UI.badge(UI.EVENT_KIND_TONES[e.kind] || "neutral", UI.EVENT_KIND_LABELS[e.kind] || e.kind) + '</td><td data-label="Titre"><span class="cell-main">' + UI.escapeHtml(e.title) + '</span><span class="cell-sub">' + UI.escapeHtml((e.body || "").slice(0, 80)) + '</span></td><td data-label="Date">' + (e.starts_on ? UI.fmtDate(e.starts_on) + (e.ends_on && e.ends_on !== e.starts_on ? " → " + UI.fmtDate(e.ends_on) : "") : "—") + '</td><td data-label="Cible">' + UI.escapeHtml(e.target_label) + '</td><td data-label="Audience">' + ({ all: "Tous", parents: "Parents", staff: "Personnel" })[e.audience] + '</td><td class="actions"><button type="button" class="btn btn-danger btn-xs del-evt" data-id="' + e.id + '">Supprimer</button></td></tr>';
      }).join("") + "</tbody></table></div>";
      host.querySelectorAll(".del-evt").forEach(function (b) { b.addEventListener("click", function () { UI.confirm("Supprimer cette publication ?", "Elle disparaîtra des calendriers.", "Supprimer").then(function (ok) { if (ok) api.fetch("/calendar/events/" + b.dataset.id, { method: "DELETE" }).then(function () { UI.toast("Supprimé.", "success"); feeds = {}; charger(); loadMine(); }); }); }); });
    });
  }

  function openEventModal(kind, date) {
    if (!publie()) return;
    var isComm = kind === "communique";
    var scopeOpts = '<option value="all">' + (ctx.role === "discipline" ? "Mon périmètre" : "Toute l'école") + '</option><option value="cycle">Un cycle</option><option value="class">Une classe</option>';
    var m = UI.modal({ title: isComm ? "Publier un communiqué" : "Ajouter un événement", size: "lg", body:
      '<form id="evForm" class="form-grid">' +
      '<div class="field"><label for="evKind">Type</label><select id="evKind">' + ["evenement", "communique", "reunion", "fete", "deuil", "conge", "examens", "echeance"].map(function (k) { return '<option value="' + k + '"' + (k === kind ? " selected" : "") + ">" + UI.EVENT_KIND_LABELS[k] + "</option>"; }).join("") + "</select></div>" +
      '<div class="field"><label for="evTitle">Titre</label><input id="evTitle" required maxlength="160" placeholder="' + (isComm ? "Ex. Fermeture exceptionnelle vendredi" : "Ex. Réunion des parents de 6e") + '" /></div>' +
      '<div class="field full"><label for="evBody">Message</label><textarea id="evBody" maxlength="2000" placeholder="Le texte reçu par les destinataires"></textarea></div>' +
      '<div class="field"><label for="evStart">Date</label><input id="evStart" type="date" value="' + UI.escapeHtml(date || "") + '" /></div><div class="field"><label for="evEnd">Fin (si plusieurs jours)</label><input id="evEnd" type="date" /></div>' +
      '<div class="field"><label for="evTime">Heure</label><input id="evTime" type="time" /></div>' +
      '<div class="field"><label for="evAud">Audience</label><select id="evAud"><option value="all">Parents et personnel</option><option value="parents">Parents</option><option value="staff">Personnel</option></select></div>' +
      '<div class="field"><label for="evScope">Cible</label><select id="evScope">' + scopeOpts + "</select></div>" +
      '<div class="field" id="evValueWrap" hidden><label for="evValue">Précision</label><select id="evValue"></select></div>' +
      '<p class="note-inline full">' + UI.icon("info", 15) + "<span>Chaque destinataire autorisé reçoit une notification ; l'événement apparaît dans son calendrier. Les envois WhatsApp/SMS suivront le branchement du canal.</span></p>" +
      '<p class="form-error full" id="evErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="evCancel">Annuler</button><button type="submit" form="evForm" class="btn btn-lime btn-sm" id="evSubmit">Publier</button>' });
    m.querySelector("#evCancel").addEventListener("click", UI.closeModal);
    var scope = m.querySelector("#evScope"), valueWrap = m.querySelector("#evValueWrap"), value = m.querySelector("#evValue");
    scope.addEventListener("change", function () {
      valueWrap.hidden = scope.value === "all";
      if (scope.value === "cycle") value.innerHTML = ["maternelle", "primaire", "secondaire"].filter(function (c) { return ctx.role !== "discipline" || (ctx.scope_cycles || ["secondaire"]).indexOf(c) >= 0; }).map(function (c) { return '<option value="' + c + '">' + c.charAt(0).toUpperCase() + c.slice(1) + "</option>"; }).join("");
      if (scope.value === "class") value.innerHTML = classes.map(function (c) { return '<option value="' + UI.escapeHtml(c.id) + '">' + UI.escapeHtml(c.name) + "</option>"; }).join("");
    });
    m.querySelector("#evForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#evSubmit"), err = m.querySelector("#evErr"); err.hidden = true;
      UI.btnState(btn, "loading", "Publication…");
      api.fetch("/calendar/events", { method: "POST", body: JSON.stringify({ kind: m.querySelector("#evKind").value, title: m.querySelector("#evTitle").value.trim(), body: m.querySelector("#evBody").value.trim(), starts_on: m.querySelector("#evStart").value || null, ends_on: m.querySelector("#evEnd").value || null, starts_time: m.querySelector("#evTime").value || null, audience: m.querySelector("#evAud").value, target_scope: scope.value, target_value: scope.value === "all" ? null : value.value }) }).then(function (res) {
        if (!res.ok) { UI.btnState(btn, "error"); err.textContent = res.body.error || "Impossible de publier."; err.hidden = false; return; }
        UI.btnState(btn, "success", "Publié"); UI.toast("Publié — " + UI.plural(res.body.notified, "personne notifiée", "personnes notifiées") + ".", "success", 4500);
        setTimeout(function () { UI.closeModal(); feeds = {}; charger(); loadMine(); }, 500);
      }).catch(function () { UI.btnState(btn, "error"); });
    });
  }
})();
