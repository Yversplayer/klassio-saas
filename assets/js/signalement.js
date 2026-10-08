// KLASSIO — signaler un fait au Directeur des disciplines (08/10/2026).
//
// Le propriétaire : l'enseignant ne rédige plus « ce qu'il veut » ; il CHOISIT
// le fait parmi les règles que la Direction a définies (règlement importé ou
// saisi), ajoute une précision s'il le souhaite, et le DD analyse et décide.
// Le serveur impose la même règle (api_discipline.create_report) : cette
// fenêtre ne fait que la rendre lisible. Une école sans aucune règle garde la
// description libre — sinon personne ne pourrait signaler avant l'import.
//
// Utilisé par la page d'une classe et par le dossier d'un élève.
(function () {
  "use strict";
  var UI = window.KlassioUI, api = window.KlassioApi;
  var FAMILLES = { comportement: "Comportement", retard: "Retards", absence: "Absences", autre: "Autres faits" };

  // `options.eleves` : sans élève désigné, la fenêtre propose de le choisir
  // (page Discipline du professeur). `options.apres` : rappel après envoi.
  function ouvrir(studentId, nom, options) {
    options = options || {};
    var choix = !studentId && options.eleves;
    var libelle = function (s) { return s.last_name + " " + s.first_name + " — " + (s.code || ""); };
    var m = UI.modal({
      title: "Signaler au Directeur des disciplines",
      body: '<form id="rpForm" class="form-grid">' +
        (nom ? '<p class="modal-text full">Élève : <strong>' + UI.escapeHtml(nom) + "</strong>.</p>" : "") +
        (choix ? '<div class="field full"><label for="rpStudent">Élève</label><input id="rpStudent" list="rpDl" required placeholder="Nom, prénom ou identifiant…" autocomplete="off" /><datalist id="rpDl">' + options.eleves.map(function (s) { return '<option value="' + UI.escapeHtml(libelle(s)) + '">' + UI.escapeHtml(s.class_name || "") + "</option>"; }).join("") + "</datalist></div>" : "") +
        '<div class="full" id="rpRegles">' + UI.skeleton("row", 2) + "</div>" +
        '<div class="field"><label for="rpDate">Date des faits</label><input id="rpDate" type="date" required max="' + UI.todayIso() + '" value="' + UI.todayIso() + '" /></div>' +
        '<div class="field full"><label for="rpDesc" id="rpDescLabel">Précision (facultative)</label><textarea id="rpDesc" maxlength="500" placeholder="Où, quand, qui était présent."></textarea></div>' +
        '<p class="form-error full" id="rpErr" hidden></p></form>',
      footer: '<button type="button" class="btn btn-ghost btn-sm" id="rpCancel">Annuler</button><button type="submit" form="rpForm" class="btn btn-lime btn-sm" id="rpSubmit" disabled>Envoyer au DD</button>'
    });
    var regles = [];
    m.querySelector("#rpCancel").addEventListener("click", UI.closeModal);

    api.fetch("/incident-reports/rules").then(function (r) {
      var hote = m.querySelector("#rpRegles"), btn = m.querySelector("#rpSubmit");
      if (!r.ok) { hote.innerHTML = '<p class="form-error">' + UI.escapeHtml(r.body.error || "Règles indisponibles.") + "</p>"; return; }
      regles = r.body || [];
      if (!regles.length) {
        // Aucune règle : la description redevient obligatoire, et on le dit.
        hote.innerHTML = '<p class="note-inline">' + UI.icon("info", 15) + "<span>La Direction n'a pas encore défini les règles de l'établissement : décrivez le fait. Le DD le qualifiera.</span></p>";
        m.querySelector("#rpDescLabel").textContent = "Description";
        var d = m.querySelector("#rpDesc"); d.required = true; d.maxLength = 1500; d.placeholder = "Ce qui s'est passé, où, quand, qui était présent.";
        btn.disabled = false;
        return;
      }
      var groupes = {};
      regles.forEach(function (x) { (groupes[x.category] = groupes[x.category] || []).push(x); });
      hote.innerHTML = '<fieldset class="kg-regles"><legend>Quel fait signalez-vous ?</legend>' +
        Object.keys(FAMILLES).concat(Object.keys(groupes).filter(function (c) { return !FAMILLES[c]; })).filter(function (c) { return groupes[c]; }).map(function (cat) {
          return '<div class="kg-groupe"><span>' + UI.escapeHtml(FAMILLES[cat] || cat) + "</span><div>" +
            groupes[cat].map(function (x) {
              return '<label class="kg-regle"><input type="radio" name="rpRegle" value="' + UI.escapeHtml(x.id) + '" required><span>' + UI.escapeHtml(x.label) + "</span></label>";
            }).join("") + "</div></div>";
        }).join("") +
        '<p class="kg-note">Règles fixées par la Direction. Le DD qualifie et décide des suites ; vous serez informé(e).</p></fieldset>';
      btn.disabled = false;
    }).catch(function () { m.querySelector("#rpRegles").innerHTML = '<p class="form-error">Le serveur Klassio est injoignable.</p>'; });

    m.querySelector("#rpForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = m.querySelector("#rpSubmit"), err = m.querySelector("#rpErr"); err.hidden = true;
      var regle = m.querySelector('input[name="rpRegle"]:checked');
      if (regles.length && !regle) { err.textContent = "Choisissez le fait dans la liste."; err.hidden = false; return; }
      var eleveId = studentId;
      if (choix) {
        var v = m.querySelector("#rpStudent").value, e2 = options.eleves.find(function (s) { return libelle(s) === v; });
        if (!e2) { err.textContent = "Choisissez un élève dans la liste."; err.hidden = false; return; }
        eleveId = e2.id;
      }
      UI.btnState(btn, "loading");
      api.fetch("/incident-reports", { method: "POST", body: JSON.stringify({
        student_id: eleveId, rule_id: regle ? regle.value : null,
        description: m.querySelector("#rpDesc").value.trim(), occurred_at: m.querySelector("#rpDate").value
      }) }).then(function (r) {
        if (!r.ok) { UI.btnState(btn, "error"); err.textContent = r.body.error || "Impossible."; err.hidden = false; return; }
        UI.btnState(btn, "success", "Envoyé"); UI.toast("Signalement transmis au Directeur des disciplines.", "success");
        setTimeout(function () { UI.closeModal(); if (options.apres) options.apres(); }, 600);
      }).catch(function () { UI.btnState(btn, "error"); err.textContent = "Le serveur Klassio est injoignable."; err.hidden = false; });
    });
  }

  window.KlassioSignalement = { ouvrir: ouvrir };
})();
