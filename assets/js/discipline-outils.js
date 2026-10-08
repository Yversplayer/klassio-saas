// KLASSIO — outils de discipline (08/10/2026) : le règlement, les faits en
// lot, l'explication du système de points, les élèves qui reviennent.
//
// Le propriétaire, après avoir montré le règlement d'une vraie école :
//   - la Direction dépose son règlement (Word, PDF) et Klassio en tire les
//     fautes, les points, la sanction prévue et l'échelle de conduite ;
//   - « si plusieurs élèves ont fait quelque chose de mal, on saisit leurs
//     faits sur un document, le logiciel analyse les noms et ce qu'ils ont
//     fait, et le DD décide en une fois » ;
//   - « le système de soustraction de points doit être expliqué pour une
//     première utilisation » ;
//   - « la liste des dérangeurs qui revient de beaucoup de classes ».
// Rien n'est écrit sans validation humaine : chaque fenêtre propose, la
// personne coche et confirme. Le serveur refait toutes les vérifications.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi;
  var CATS = ["comportement", "retard", "absence", "autre", "bonus"];
  var NOM_CAT = { comportement: "Comportement", retard: "Retard", absence: "Absence", autre: "Autre", bonus: "Bonus" };

  function chargement(texte) {
    if (window.KlassioLoader) window.KlassioLoader.show(texte, [{ label: "Lecture du document", state: "doing" }]);
  }
  function finChargement() { if (window.KlassioLoader) window.KlassioLoader.hide(); }

  // ------------------------------------------------------------------
  // 1. Comment fonctionne la conduite — pour une première utilisation
  // ------------------------------------------------------------------
  function explication(th, nbRegles, direction) {
    th = th || { capital: 100, thresholds: [], conduct_scale: [] };
    var cap = th.capital || 100;
    var echelle = (th.conduct_scale || []).map(function (s) {
      return "<li><b>" + Math.round(s[0] * cap / 100) + " pts et plus</b><span>" + UI.escapeHtml(s[1]) + "</span></li>";
    }).join("");
    return '<section class="kq-explique"><div class="kq-explique-tete"><span class="kq-sur">Comment ça marche</span><h2>Le capital de conduite, en quatre temps</h2></div>' +
      '<ol class="kq-etapes">' +
      '<li><span class="kq-num">1</span><div><strong>Chaque élève commence avec ' + cap + " points.</strong><span>C'est son capital de conduite pour l'année.</span></div></li>" +
      "<li><span class=\"kq-num\">2</span><div><strong>Chaque faute retire des points.</strong><span>Le barème vient du règlement de l'école : par exemple, un dérangement retire 10 points. " + (nbRegles ? UI.plural(nbRegles, "règle définie", "règles définies") + "." : "Aucune règle n'est encore définie — " + (direction ? "importez votre règlement." : "la Direction doit importer le règlement.")) + "</span></div></li>" +
      '<li><span class="kq-num">3</span><div><strong>Les points restants donnent la cote de conduite.</strong><span>Elle figure sur le bulletin.</span>' + (echelle ? '<ul class="kq-echelle">' + echelle + "</ul>" : "") + "</div></li>" +
      '<li><span class="kq-num">4</span><div><strong>Un seuil franchi est un signal, pas une sanction.</strong><span>Le DD et la Direction sont alertés ; une personne décide toujours de la suite. Une bonne action ou une erreur corrigée peut rendre des points.</span></div></li>' +
      "</ol></section>";
  }

  // ------------------------------------------------------------------
  // 2. Importer le règlement (Direction)
  // ------------------------------------------------------------------
  function reglement(apres) {
    var m = UI.modal({ title: "Importer le règlement intérieur", size: "lg", body:
      '<p class="modal-text">Déposez votre règlement en <strong>Word (.docx)</strong> ou en <strong>PDF avec texte</strong>. Klassio y repère les fautes, les points retirés, la sanction prévue et l\'échelle de conduite — <strong>rien n\'est enregistré sans votre validation</strong>.</p>' +
      '<p class="note-inline note-garde mt-8">' + UI.icon("info", 15) + "<span>Une photo du règlement ne peut pas être lue automatiquement : enregistrez-le en Word ou en PDF, ou ajoutez les règles à la main.</span></p>" +
      '<div class="field" style="margin-top:12px"><input type="file" id="regFile" accept=".docx,.pdf,.txt,application/pdf,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document" /></div><div id="regResult"></div>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="regCancel">Fermer</button><button type="button" class="btn btn-lime btn-sm" id="regAnalyze">Analyser</button>' });
    m.querySelector("#regCancel").addEventListener("click", UI.closeModal);
    m.querySelector("#regAnalyze").addEventListener("click", function () {
      var file = m.querySelector("#regFile").files[0];
      if (!file) return UI.toast("Choisissez un fichier.", "error");
      var btn = this; UI.btnState(btn, "loading", "Lecture…");
      var fd = new FormData(); fd.append("file", file);
      chargement("Lecture de votre règlement");
      api.fetch("/discipline/reglement/analyze", { method: "POST", body: fd }).then(function (r) {
        finChargement();
        var hote = m.querySelector("#regResult");
        if (!r.ok) { UI.btnState(btn, "error", "Réessayer"); hote.innerHTML = '<p class="form-error" style="display:block">' + UI.escapeHtml(r.body.error || "Lecture impossible.") + "</p>"; return; }
        UI.btnState(btn, "success", "Analysé");
        var p = r.body.proposals || [], echelle = r.body.conduct_scale, cap = r.body.capital;
        if (!p.length && !echelle) { hote.innerHTML = '<p class="muted mt-16">Aucune règle chiffrable détectée dans ce document. Vous pouvez ajouter vos règles à la main.</p>'; return; }
        hote.innerHTML =
          (echelle ? '<div class="kq-echelle-lue"><label class="check"><input type="checkbox" id="regScale" checked> Reprendre l\'échelle de conduite du règlement' + (cap ? " (capital de " + cap + " points)" : "") + "</label><div class=\"pill-row\">" + echelle.map(function (e) { return UI.badge("neutral", e[1] + " — dès " + e[0] + " pts"); }).join("") + "</div></div>" : "") +
          (p.length ? '<p class="muted mt-16">' + UI.plural(p.length, "règle proposée", "règles proposées") + ' — décochez ce que vous ne voulez pas, ajustez les points et la sanction, puis validez.</p><div class="table-wrap" style="max-height:46vh"><table class="data-table"><thead><tr><th style="width:34px"></th><th>Faute</th><th>Catégorie</th><th class="num">Points</th><th>Sanction prévue</th></tr></thead><tbody>' + p.map(function (x, i) {
            return "<tr" + (x.already_exists ? ' style="opacity:0.5"' : "") + '><td><input type="checkbox" class="reg-chk" data-i="' + i + '"' + (x.already_exists ? "" : " checked") + ' /></td><td><span class="cell-main">' + UI.escapeHtml(x.label) + '</span>' + (x.already_exists ? '<span class="cell-sub">déjà enregistrée</span>' : "") + '</td><td><select class="reg-cat">' + CATS.map(function (c) { return '<option value="' + c + '"' + (x.category === c ? " selected" : "") + ">" + NOM_CAT[c] + "</option>"; }).join("") + '</select></td><td class="num"><input type="number" class="grade-input reg-pts" value="' + x.points + '" min="-100" max="100" style="width:70px" /></td><td><input class="reg-mes" maxlength="300" value="' + UI.escapeHtml(x.measure || "") + '" style="min-width:180px" /></td></tr>';
          }).join("") + "</tbody></table></div>" : "");
        var foot = m.querySelector(".modal-foot");
        if (!foot.querySelector("#regConfirm")) foot.insertAdjacentHTML("beforeend", '<button type="button" class="btn btn-lime btn-sm" id="regConfirm">Enregistrer</button>');
        foot.querySelector("#regConfirm").onclick = function () {
          var b2 = this;
          var rows = Array.prototype.filter.call(m.querySelectorAll("#regResult tbody tr"), function (tr) { return tr.querySelector(".reg-chk").checked; });
          var garderEchelle = echelle && m.querySelector("#regScale") && m.querySelector("#regScale").checked;
          if (!rows.length && !garderEchelle) return UI.toast("Cochez au moins une règle.", "error");
          UI.btnState(b2, "loading");
          var corps = { rules: rows.map(function (tr) { var i = parseInt(tr.querySelector(".reg-chk").dataset.i, 10); return { label: p[i].label, category: tr.querySelector(".reg-cat").value, points: parseInt(tr.querySelector(".reg-pts").value, 10), measure: tr.querySelector(".reg-mes").value.trim() }; }) };
          if (garderEchelle) { corps.conduct_scale = echelle; if (cap) corps.capital = cap; }
          if (!corps.rules.length) corps.rules = [];
          api.fetch("/discipline/reglement/confirm", { method: "POST", body: JSON.stringify(corps) }).then(function (rr) {
            if (!rr.ok) { UI.btnState(b2, "error"); return UI.toast(rr.body.error || "Impossible.", "error"); }
            UI.btnState(b2, "success"); UI.toast(UI.plural(rr.body.created, "règle enregistrée", "règles enregistrées") + (garderEchelle ? " · échelle de conduite reprise." : "."), "success");
            setTimeout(function () { UI.closeModal(); if (apres) apres(); }, 600);
          });
        };
      }).catch(function () { finChargement(); UI.btnState(btn, "error", "Réessayer"); });
    });
  }

  // ------------------------------------------------------------------
  // 3. Faits en lot : une liste → élèves reconnus → une décision commune
  // ------------------------------------------------------------------
  function lot(eleves, regles, apres, prerempli) {
    regles = (regles || []).filter(function (r) { return r.active !== 0 && r.active !== false; });
    var lignes = (prerempli || []).slice();
    var m = UI.modal({ title: "Faits en lot — plusieurs élèves, une décision", size: "lg", body:
      '<div id="lotEtape1"' + (lignes.length ? " hidden" : "") + '><p class="modal-text">Collez la liste ou déposez un document (Word, PDF, texte) : <strong>une ligne par fait</strong>, avec le prénom et le nom de l\'élève — « Grace Mbuyi : dérangement ». Klassio retrouve les élèves de votre périmètre et propose la règle ; vous décidez ensuite pour tous.</p>' +
      '<div class="field full mt-8"><label for="lotTexte">Liste des faits</label><textarea id="lotTexte" rows="6" placeholder="Grace Mbuyi : dérangement pendant le cours&#10;Jean Kabeya et Ruth Tshala : retard"></textarea></div>' +
      '<div class="field full"><label for="lotFichier">Ou un document</label><input type="file" id="lotFichier" accept=".docx,.pdf,.txt,application/pdf,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document" /></div></div>' +
      '<div id="lotEtape2"' + (lignes.length ? "" : " hidden") + "></div>",
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="lotFermer">Fermer</button><button type="button" class="btn btn-lime btn-sm" id="lotAnalyser"' + (lignes.length ? " hidden" : "") + '>Analyser</button><button type="button" class="btn btn-lime btn-sm" id="lotValider"' + (lignes.length ? "" : " hidden") + ">Enregistrer pour tous</button>" });
    m.querySelector("#lotFermer").addEventListener("click", UI.closeModal);

    function optionsRegles(sel) {
      return '<option value="">— Choisir —</option>' + regles.map(function (r) { return '<option value="' + UI.escapeHtml(r.id) + '"' + (r.id === sel ? " selected" : "") + ">" + UI.escapeHtml(r.label) + " (" + (r.points > 0 ? "+" : "") + r.points + ")</option>"; }).join("");
    }
    function afficher(inconnues) {
      var hote = m.querySelector("#lotEtape2");
      hote.innerHTML = '<p class="muted">' + UI.plural(lignes.length, "élève retenu", "élèves retenus") + ". Vérifiez la règle de chacun ; décochez qui ne doit pas être sanctionné.</p>" +
        '<div class="table-wrap" style="max-height:38vh"><table class="data-table"><thead><tr><th style="width:34px"></th><th>Élève</th><th>Fait</th><th>Règle appliquée</th></tr></thead><tbody>' +
        lignes.map(function (l, i) {
          return '<tr><td><input type="checkbox" class="lot-chk" data-i="' + i + '" checked></td><td><span class="cell-main">' + UI.escapeHtml(l.student) + '</span><span class="cell-sub">' + UI.escapeHtml(l.class_name || "") + (l.ambiguous ? " · homonyme : vérifiez" : "") + '</span></td><td><span class="cell-sub">' + UI.escapeHtml(l.line || "") + '</span></td><td><select class="lot-regle" data-i="' + i + '">' + optionsRegles(l.rule_id) + "</select></td></tr>";
        }).join("") + "</tbody></table></div>" +
        (inconnues && inconnues.length ? '<p class="note-inline mt-8">' + UI.icon("info", 15) + "<span>" + UI.plural(inconnues.length, "ligne sans élève reconnu", "lignes sans élève reconnu") + " (orthographe, autre classe, hors de votre périmètre) : " + inconnues.slice(0, 5).map(UI.escapeHtml).join(" · ") + (inconnues.length > 5 ? "…" : "") + "</span></p>" : "") +
        '<div class="field full mt-8"><label for="lotAjout">Ajouter un élève</label><input id="lotAjout" list="lotDl" placeholder="Nom, prénom ou identifiant…" autocomplete="off" /><datalist id="lotDl">' + (eleves || []).map(function (s) { return '<option value="' + UI.escapeHtml(s.last_name + " " + s.first_name + " — " + (s.code || s.id)) + '">' + UI.escapeHtml(s.class_name || "") + "</option>"; }).join("") + "</datalist></div>" +
        '<div class="kq-decision"><h3>Décision commune</h3><div class="form-grid">' +
        '<div class="field"><label for="lotDate">Date des faits</label><input id="lotDate" type="date" max="' + UI.todayIso() + '" value="' + UI.todayIso() + '"></div>' +
        '<div class="field"><label for="lotSev">Gravité</label><select id="lotSev"><option value="low">Mineur</option><option value="medium" selected>Modéré</option><option value="high">Grave</option></select></div>' +
        '<div class="field full"><label for="lotMesure">Mesure décidée (tâche, punition) — vide = la sanction prévue par chaque règle</label><input id="lotMesure" maxlength="500" placeholder="Ex. Travail manuel pendant 3 jours de 13 h 00 à 14 h 30"></div>' +
        '<div class="field"><label for="lotPts">Points (facultatif, remplace ceux des règles)</label><input id="lotPts" type="number" min="-100" max="100" placeholder="Barème des règles"></div>' +
        '<label class="check full"><input type="checkbox" id="lotParent"> Informer les parents (si l\'école l\'autorise)</label>' +
        '<p class="form-error full" id="lotErr" hidden></p></div></div>';
      hote.querySelectorAll(".lot-regle").forEach(function (s) { s.addEventListener("change", function () { lignes[+s.dataset.i].rule_id = s.value || null; }); });
      hote.querySelector("#lotAjout").addEventListener("change", function () {
        var v = this.value, s = (eleves || []).find(function (x) { return v === x.last_name + " " + x.first_name + " — " + (x.code || x.id); });
        if (!s) return;
        if (lignes.some(function (l) { return l.student_id === s.id; })) { this.value = ""; return UI.toast("Cet élève est déjà dans la liste.", "error"); }
        lignes.push({ student_id: s.id, student: s.first_name + " " + s.last_name, class_name: s.class_name, line: "", rule_id: lignes.length ? lignes[0].rule_id : null });
        afficher(inconnues);
      });
    }

    m.querySelector("#lotAnalyser").addEventListener("click", function () {
      var btn = this, f = m.querySelector("#lotFichier").files[0], texte = m.querySelector("#lotTexte").value.trim();
      if (!f && !texte) return UI.toast("Collez la liste ou choisissez un document.", "error");
      var corps;
      if (f) { corps = new FormData(); corps.append("file", f); } else corps = JSON.stringify({ text: texte });
      UI.btnState(btn, "loading", "Analyse…");
      chargement("Analyse des noms et des faits");
      api.fetch("/discipline/lot/analyze", { method: "POST", body: corps }).then(function (r) {
        finChargement();
        if (!r.ok) { UI.btnState(btn, "error", "Réessayer"); return UI.toast(r.body.error || "Analyse impossible.", "error"); }
        lignes = r.body.items || [];
        m.querySelector("#lotEtape1").hidden = true; btn.hidden = true; m.querySelector("#lotValider").hidden = false;
        m.querySelector("#lotEtape2").hidden = false;
        afficher(r.body.unmatched || []);
        if (!lignes.length) UI.toast("Aucun élève reconnu : ajoutez-les à la main ci-dessous.", "error");
      }).catch(function () { finChargement(); UI.btnState(btn, "error", "Réessayer"); });
    });

    m.querySelector("#lotValider").addEventListener("click", function () {
      var btn = this, err = m.querySelector("#lotErr");
      var choisis = Array.prototype.filter.call(m.querySelectorAll(".lot-chk"), function (c) { return c.checked; }).map(function (c) { return lignes[+c.dataset.i]; });
      if (!choisis.length) { err.textContent = "Cochez au moins un élève."; err.hidden = false; return; }
      var sansRegle = choisis.filter(function (l) { return !l.rule_id; });
      if (sansRegle.length) { err.textContent = "Choisissez la règle pour : " + sansRegle.map(function (l) { return l.student; }).join(", ") + "."; err.hidden = false; return; }
      err.hidden = true; UI.btnState(btn, "loading");
      var pts = m.querySelector("#lotPts").value;
      api.fetch("/discipline/lot/confirm", { method: "POST", body: JSON.stringify({
        items: choisis.map(function (l) { return { student_id: l.student_id, rule_id: l.rule_id, line: l.line || null }; }),
        common: { occurred_at: m.querySelector("#lotDate").value, severity: m.querySelector("#lotSev").value, action_taken: m.querySelector("#lotMesure").value.trim(),
                  points: pts === "" ? null : parseInt(pts, 10), notify_parent: m.querySelector("#lotParent").checked }
      }) }).then(function (r) {
        if (!r.ok) { UI.btnState(btn, "error"); err.textContent = r.body.error || "Impossible."; err.hidden = false; return; }
        UI.btnState(btn, "success", "Enregistré");
        UI.toast(UI.plural(r.body.created, "incident enregistré", "incidents enregistrés") + (r.body.crossed.length ? " · seuil franchi : " + r.body.crossed.map(function (x) { return x.student; }).join(", ") : "."), r.body.crossed.length ? "error" : "success", 6000);
        setTimeout(function () { UI.closeModal(); if (apres) apres(); }, 700);
      }).catch(function () { UI.btnState(btn, "error"); err.textContent = "Le serveur Klassio est injoignable."; err.hidden = false; });
    });
    if (lignes.length) afficher([]);
  }

  // ------------------------------------------------------------------
  // 4. Les élèves qui reviennent
  // ------------------------------------------------------------------
  function recurrents(hote, eleves, regles, apres) {
    hote.innerHTML = '<section class="panel"><div class="panel-head"><h2>Élèves qui reviennent</h2><span class="sub">Même fait au moins deux fois en 30 jours, toutes classes confondues</span></div>' + UI.skeleton("row", 3) + "</section>";
    api.fetch("/discipline/recurrents?days=30&min=2").then(function (r) {
      var rows = r.ok ? r.body : [];
      var corps = rows.length ? '<div class="table-wrap"><table class="data-table responsive"><thead><tr><th>Élève</th><th>Classe</th><th>Fait</th><th class="num">Fois</th><th>Dernière</th></tr></thead><tbody>' + rows.slice(0, 25).map(function (x) {
        return '<tr class="clickable" data-href="eleve-dossier.html?id=' + x.student_id + '&tab=discipline"><td data-label="Élève"><span class="cell-main">' + UI.escapeHtml(x.first_name + " " + x.last_name) + '</span></td><td data-label="Classe">' + UI.escapeHtml(x.class_name || "—") + '</td><td data-label="Fait">' + UI.escapeHtml(x.fait) + '</td><td data-label="Fois" class="num">' + UI.badge(x.n >= 3 ? "bad" : "warn", String(x.n)) + '</td><td data-label="Dernière">' + UI.fmtDate(x.dernier) + "</td></tr>";
      }).join("") + "</tbody></table></div>" + '<div class="row mt-16"><button type="button" class="btn btn-ghost btn-sm" id="kqEnsemble">' + UI.icon("users", 15) + "Décider pour ces élèves ensemble</button></div>"
        : '<p class="muted">Aucun élève n\'a répété le même fait ces 30 derniers jours.</p>';
      hote.innerHTML = '<section class="panel"><div class="panel-head"><h2>Élèves qui reviennent</h2><span class="sub">Même fait au moins deux fois en 30 jours, toutes classes confondues</span></div>' + corps + "</section>";
      UI.wireHrefs(hote);
      var b = hote.querySelector("#kqEnsemble");
      if (b) b.addEventListener("click", function () {
        var vus = {};
        var pre = rows.filter(function (x) { if (vus[x.student_id]) return false; vus[x.student_id] = 1; return true; }).map(function (x) {
          var regle = (regles || []).find(function (rr) { return rr.label === x.fait; });
          return { student_id: x.student_id, student: x.first_name + " " + x.last_name, class_name: x.class_name, line: x.fait + " — " + x.n + " fois en 30 jours", rule_id: regle ? regle.id : null };
        });
        lot(eleves, regles, apres, pre);
      });
    });
  }

  window.KlassioDisciplineOutils = { explication: explication, reglement: reglement, lot: lot, recurrents: recurrents };
})();
