// KLASSIO — Welcome Experience : accueil, contexte réel, activation du compte.
//
// Page publique, sans session. Trois règles gouvernent ce fichier :
//
// 1. LE SERVEUR DÉCIDE, LA PAGE PRÉSENTE. Le rôle, l'établissement, les
//    classes, la titularité et les enfants viennent tous de l'invitation créée
//    par la Direction. Rien n'est affiché qui n'ait été confirmé par une
//    réponse du backend, et rien de ce qui est affiché n'est renvoyé comme une
//    décision : la route d'acceptation relit tout côté serveur.
//
// 2. AUCUN FAUX SUCCÈS. Le chargement dure exactement le temps de la requête.
//    La coche n'apparaît qu'après un 201 réel. Il n'existe dans ce fichier
//    aucun `setTimeout` qui fasse semblant qu'un traitement avance — les seuls
//    délais sont des transitions visuelles APRÈS la réponse, et ils tombent à
//    zéro si l'utilisateur a désactivé les animations.
//
// 3. CE QUI EST INTERROMPU DOIT POUVOIR REPRENDRE. Rafraîchissement, perte
//    réseau, double clic, retour arrière : chacun a un chemin explicite.
(function () {
  "use strict";
  // Page publique : elle ne charge pas app.js, mais bien ui.js — l'origine
  // vient donc de la même source que partout ailleurs, pas d'une seconde
  // constante qu'on oublierait de changer au déploiement.
  var API_BASE = (window.KlassioUI ? window.KlassioUI.apiOrigin() : "http://localhost:5001") + "/api";
  var UI = window.KlassioUI;

  // Les délais de mise en scène — jamais du travail simulé, seulement le temps
  // qu'une transition CSS a besoin pour être vue. Zéro si l'utilisateur a
  // demandé moins d'animations : le parcours reste alors entièrement
  // fonctionnel, simplement instantané.
  var REDUIT = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var BEAT = REDUIT ? 0 : 420;   // respiration entre deux états
  var BEAT_LONG = REDUIT ? 0 : 780;

  var ETAPES = ["stateLoading", "stateInvalid", "stateWelcome", "stateContext", "stateForm", "stateProcessing"];
  var AVEC_FIL = { stateContext: "context", stateForm: "form", stateProcessing: "processing" };

  var el = function (id) { return document.getElementById(id); };
  var attendre = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };

  function montrer(id) {
    ETAPES.forEach(function (s) { el(s).hidden = s !== id; });
    var fil = el("wxSteps"), courant = AVEC_FIL[id];
    fil.hidden = !courant;
    if (courant) {
      var ordre = ["context", "form", "processing"], i = ordre.indexOf(courant);
      fil.querySelectorAll(".wx-dot").forEach(function (d, n) {
        d.classList.toggle("is-done", n < i);
        d.classList.toggle("is-current", n === i);
      });
    }
    var carte = document.querySelector(".wx-card");
    if (carte && !REDUIT) { carte.classList.remove("wx-in"); void carte.offsetWidth; carte.classList.add("wx-in"); }
  }

  // --------------------------------------------------------------------
  // État de la page
  // --------------------------------------------------------------------
  var token = new URLSearchParams(window.location.search).get("token") || "";
  var invitation = null;
  var envoiEnCours = false;       // garde anti-double-soumission
  var dernierePayload = null;     // rejouée telle quelle par « Réessayer »

  var MOTS = {
    parent: {
      appel: "cher parent", espace: "votre espace familial", espaceCourt: "espace parent",
      contexteTitre: "Les enfants dont vous suivrez le dossier",
      contexteIntro: "Votre établissement a rattaché ces élèves à votre invitation.",
      pret: "Votre espace familial est prêt.", bienvenue: "Bienvenue dans votre espace parent.",
      preparation: "Préparation de votre espace familial…"
    },
    professeur: {
      appel: "cher professeur", espace: "votre espace enseignant", espaceCourt: "espace enseignant",
      contexteTitre: "Vos affectations", contexteIntro: "Votre Direction a déjà préparé votre rattachement.",
      pret: "Votre espace enseignant est prêt.", bienvenue: "Bienvenue dans votre espace enseignant.",
      preparation: "Préparation de votre espace enseignant…"
    },
    discipline: {
      appel: "cher directeur des disciplines", espace: "votre espace de discipline",
      espaceCourt: "espace de discipline", contexteTitre: "Votre périmètre",
      contexteIntro: "Votre Direction a défini l'étendue de vos accès.",
      pret: "Votre espace est prêt.", bienvenue: "Bienvenue dans votre espace.",
      preparation: "Préparation de votre espace…"
    }
  };
  var mots = function () { return MOTS[invitation && invitation.role] || MOTS.parent; };

  // --------------------------------------------------------------------
  // Lien inutilisable — le message dépend de la raison RÉELLE renvoyée par le
  // serveur. « Vous venez de finir votre inscription » et « votre école a
  // annulé ce lien » ne peuvent pas partager le même écran.
  // --------------------------------------------------------------------
  function lienInutilisable(etat, message) {
    var titres = {
      utilisee: "Ce compte est déjà activé", revoquee: "Lien annulé",
      expiree: "Lien expiré", inconnue: "Lien introuvable", absent: "Aucun lien fourni",
      reseau: "Serveur injoignable"
    };
    el("invalidTitle").textContent = titres[etat] || "Invitation introuvable";
    el("invalidMessage").textContent = message || "Ce lien n'est plus valide.";
    var action = el("invalidAction");
    if (etat === "utilisee") { action.textContent = "Se connecter"; action.href = "connexion.html"; action.hidden = false; }
    else if (etat === "reseau") { action.textContent = "Réessayer"; action.href = window.location.href; action.hidden = false; }
    else { action.textContent = "Déjà un compte ? Se connecter"; action.href = "connexion.html"; action.hidden = false; }
    montrer("stateInvalid");
  }

  // --------------------------------------------------------------------
  // 0. Vérification du lien
  // --------------------------------------------------------------------
  if (!token) { lienInutilisable("absent", "Aucun lien d'invitation n'a été fourni."); return; }

  fetch(API_BASE + "/invitations/lookup?token=" + encodeURIComponent(token))
    .then(function (r) { return r.json().then(function (b) { return { ok: r.ok, body: b }; }); })
    .then(function (res) {
      if (!res.ok) { lienInutilisable((res.body && res.body.state) || "inconnue", res.body && res.body.error); return; }
      invitation = res.body;
      appliquerHabillage(invitation);
      preparerAccueil();
      montrer("stateWelcome");
    })
    .catch(function () {
      lienInutilisable("reseau", "Le serveur Klassio est momentanément injoignable. Vérifiez votre connexion.");
    });

  function appliquerHabillage(inv) {
    var b = inv.branding || {};
    el("portalHead").hidden = false;
    el("pName").textContent = b.name || inv.tenant_name;
    el("pTagline").textContent = b.tagline || "";
    el("pLogo").innerHTML = b.logo_data
      ? '<img src="' + UI.escapeHtml(b.logo_data) + '" alt="">'
      : "<span>" + UI.escapeHtml((inv.tenant_name || "?").split(/\s+/).map(function (w) { return w[0]; }).join("").slice(0, 3).toUpperCase()) + "</span>";
    if (b.cover_data) el("pCover").style.backgroundImage = "url(" + b.cover_data + ")";
    if (b.accent_color) document.documentElement.style.setProperty("--accent", b.accent_color);
    document.title = "Invitation — " + inv.tenant_name;
  }

  // --------------------------------------------------------------------
  // 1. Accueil — court, et toujours franchissable d'un clic. Jamais un mur
  //    d'attente : les lignes s'enchaînent, le bouton est disponible d'emblée.
  // --------------------------------------------------------------------
  function preparerAccueil() {
    var m = mots();
    el("welcomeLine1").textContent = "Bienvenue sur Klassio, " + m.appel + ".";
    el("welcomeLine2").textContent = m.espace.charAt(0).toUpperCase() + m.espace.slice(1) + " est presque prêt.";
    el("welcomeLine3").textContent = invitation.role === "parent"
      ? "Nous allons vérifier les enfants associés à votre invitation."
      : "Voici ce que " + (invitation.tenant_name || "votre établissement") + " a préparé pour vous.";
  }

  el("welcomeNext").addEventListener("click", function () { preparerContexte(); montrer("stateContext"); });

  // --------------------------------------------------------------------
  // 2. Contexte réel. Chaque ligne vient d'une réponse du serveur ; la page
  //    n'invente ni classe, ni enfant, ni titularité.
  // --------------------------------------------------------------------
  function preparerContexte() {
    var m = mots(), liste = el("contextList"), note = el("contextNote");
    el("contextKicker").textContent = invitation.tenant_name || "Votre établissement";
    el("contextTitle").textContent = m.contexteTitre;
    el("contextIntro").textContent = m.contexteIntro;
    liste.innerHTML = "";
    note.textContent = "";

    if (invitation.role === "parent") {
      var enfants = invitation.students || [];
      if (!enfants.length) {
        liste.innerHTML = '<p class="muted">Aucun enfant n\'est encore rattaché à cette invitation. Votre établissement peut les ajouter.</p>';
      } else {
        liste.innerHTML = enfants.map(function (s) {
          return '<div class="wx-item">'
            + '<span class="wx-avatar">' + UI.escapeHtml(initiales(s.first_name, s.last_name)) + '</span>'
            + '<span class="wx-item-body"><strong>' + UI.escapeHtml(s.first_name + " " + s.last_name) + "</strong>"
            + (s.class_name ? '<span class="wx-item-sub">' + UI.escapeHtml(s.class_name) + "</span>" : "")
            + "</span></div>";
        }).join("");
        note.textContent = enfants.length > 1
          ? "Ces " + enfants.length + " enfants ont été rattachés par votre établissement. Pour en ajouter un autre, contactez-le : un enfant ne peut pas être rattaché depuis cette page."
          : "Pour rattacher un autre enfant, contactez votre établissement.";
      }
    } else if (invitation.role === "professeur") {
      var classes = invitation.classes || [];
      if (!classes.length) {
        liste.innerHTML = '<p class="muted">Aucune classe ne vous est encore rattachée. Votre Direction le fera depuis son espace.</p>';
      } else {
        liste.innerHTML = classes.map(function (c) {
          return '<div class="wx-item">'
            + '<span class="wx-avatar wx-avatar-class">' + UI.escapeHtml((c.name || "?").slice(0, 3)) + "</span>"
            + '<span class="wx-item-body"><strong>' + UI.escapeHtml(c.name) + "</strong>"
            + '<span class="wx-item-sub">' + (c.student_count === 1 ? "1 élève" : (c.student_count || 0) + " élèves")
            + (c.cycle ? " · " + UI.escapeHtml(c.cycle) : "") + "</span></span>"
            + (c.is_titulaire ? '<span class="wx-tag">Titulaire</span>' : "")
            + "</div>";
        }).join("");
        var t = invitation.titulaire_of || [];
        note.textContent = (classes.length === 1
          ? "Vous avez été affecté(e) à la " + classes[0].name + "."
          : "Vous enseignez dans " + classes.length + " classes.")
          + (t.length ? " Vous êtes titulaire de la " + t.join(" et de la ") + "." : "")
          + " Ces affectations ont été décidées par votre Direction et ne se modifient pas ici.";
      }
    } else {
      liste.innerHTML = '<div class="wx-item"><span class="wx-item-body">' + UI.escapeHtml(invitation.scope_note || "Périmètre défini par votre Direction.") + "</span></div>";
    }
  }

  function initiales(p, n) {
    return ((p || "?").charAt(0) + (n || "").charAt(0)).toUpperCase();
  }

  el("contextNext").addEventListener("click", function () { preparerFormulaire(); montrer("stateForm"); });
  el("contextWrong").addEventListener("click", function () {
    lienInutilisable("revoquee",
      "Ce lien a été préparé pour quelqu'un d'autre. Ne l'utilisez pas : prévenez votre établissement pour qu'il l'annule et en émette un nouveau.");
  });

  // --------------------------------------------------------------------
  // 3. Formulaire — pré-rempli de ce que l'établissement connaît déjà.
  //    Le nom suggéré reste modifiable : c'est un confort, pas une identité.
  // --------------------------------------------------------------------
  function preparerFormulaire() {
    var m = mots();
    el("formTitle").textContent = "Activez votre compte";
    el("formIntro").textContent = "Avant d'accéder à " + m.espace + ", créez le mot de passe qui vous servira à vous connecter.";
    if (invitation.suggested_name && !el("acceptName").value) el("acceptName").value = invitation.suggested_name;
    el("acceptName").focus();
  }

  var pwInput = el("acceptPassword"), pwRules = el("pwRules");
  function respecteRegles(v) {
    return v.length >= 8 && /[A-Z]/.test(v) && /[a-z]/.test(v) && /[0-9]/.test(v) && /[^A-Za-z0-9]/.test(v);
  }
  pwInput.addEventListener("input", function () {
    var v = pwInput.value;
    var checks = { length: v.length >= 8, upper: /[A-Z]/.test(v), lower: /[a-z]/.test(v), digit: /[0-9]/.test(v), special: /[^A-Za-z0-9]/.test(v) };
    pwRules.querySelectorAll("li").forEach(function (li) { li.classList.toggle("met", !!checks[li.dataset.rule]); });
  });

  el("activationForm").addEventListener("submit", function (e) {
    e.preventDefault();
    var erreur = el("acceptError");
    erreur.hidden = true;
    var nom = el("acceptName").value.trim(),
        email = el("acceptEmail").value.trim(),
        tel = el("acceptPhone").value.trim(),
        mdp = el("acceptPassword").value,
        mdp2 = el("acceptPassword2").value;

    function refuser(msg) { erreur.textContent = msg; erreur.hidden = false; }
    if (!nom) return refuser("Indiquez votre nom complet.");
    if (!email && !tel) return refuser("Indiquez un numéro de téléphone ou un email — c'est avec cela que vous vous connecterez.");
    if (!respecteRegles(mdp)) return refuser("Le mot de passe ne respecte pas encore toutes les règles listées ci-dessus.");
    if (mdp !== mdp2) return refuser("Les deux mots de passe ne sont pas identiques.");
    if (!el("acceptTerms").checked) return refuser("Merci de cocher la case d'acceptation pour continuer.");

    dernierePayload = { token: token, name: nom, password: mdp };
    if (email) dernierePayload.email = email;
    if (tel) dernierePayload.phone = tel;
    activer();
  });

  // --------------------------------------------------------------------
  // 4. Traitement réel → succès. Le cœur de la règle « aucun faux succès ».
  // --------------------------------------------------------------------
  function phase(nom) { el("wxStage").setAttribute("data-phase", nom); }

  function activer() {
    if (envoiEnCours) return;   // double clic, double Entrée, rejeu : une seule requête part
    envoiEnCours = true;

    var m = mots();
    el("processingError").hidden = true;
    el("processingLogin").hidden = true;
    el("processingTitle").textContent = m.preparation;
    el("processingSub").textContent = "Vérification de votre invitation et création de vos accès.";
    phase("working");
    montrer("stateProcessing");

    // Le chargement dure EXACTEMENT le temps de la requête. Pas de minimum
    // imposé, pas de maximum : si le serveur répond en 200 ms, l'utilisateur
    // passe à la suite en 200 ms.
    fetch(API_BASE + "/invitations/accept", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(dernierePayload)
    })
      .then(function (r) { return r.json().then(function (b) { return { ok: r.ok, status: r.status, body: b }; }); })
      .then(function (res) {
        if (!res.ok) { echec(res); return; }
        return succes(res.body);
      })
      .catch(function () {
        // Le réseau a lâché. On ne sait PAS si le serveur a traité la demande :
        // c'est exactement ce qu'il faut dire, et le réessai est sûr parce que
        // l'invitation est à usage unique côté serveur.
        echec({
          status: 0,
          body: { error: "Le serveur Klassio est injoignable. Votre compte n'a peut-être pas été créé — réessayez." }
        });
      });
  }

  function succes(corps) {
    // À partir d'ici, et seulement ici, le compte EXISTE : le serveur a
    // répondu 201 après avoir écrit le compte, les rattachements, la session
    // et l'audit. Ce qui suit n'est que de la mise en scène.
    var m = mots();
    try {
      localStorage.setItem("klassio_token", corps.token);
      localStorage.setItem("klassio_tenant_id", corps.tenant_id);
      localStorage.setItem("klassio_role", corps.role);
      localStorage.setItem("klassio_name", corps.name || "");
      if (corps.portal) localStorage.setItem("klassio_portal", corps.portal);
      if (corps.staff_code) localStorage.setItem("klassio_staff_code", corps.staff_code);
    } catch (e) {
      // Navigation privée ou stockage bloqué : le compte existe malgré tout.
      // On n'échoue pas là-dessus, on laisse la connexion reprendre la main.
    }

    el("processingTitle").textContent = "Vérification terminée.";
    el("processingSub").textContent = resumeConfirme(corps);

    return attendre(BEAT)
      .then(function () {
        phase("done");
        el("processingTitle").textContent = m.pret;
        return attendre(BEAT_LONG);
      })
      .then(function () {
        el("processingTitle").textContent = m.bienvenue;
        el("processingSub").textContent = corps.staff_code ? "Votre identifiant : " + corps.staff_code : "";
        return attendre(BEAT);
      })
      .then(function () { window.location.href = UI.homeFor(corps.role) + "?bienvenue=1"; });
  }

  // Ce que le serveur a RÉELLEMENT écrit — relu par lui après le commit, pas
  // recopié depuis ce que la page affichait à l'étape précédente.
  function resumeConfirme(corps) {
    var c = corps.confirmed || {};
    if (corps.role === "parent" && (c.children || []).length) {
      return c.children.length === 1
        ? "Dossier de " + c.children[0].first_name + " " + c.children[0].last_name + " rattaché."
        : c.children.length + " dossiers rattachés à votre compte.";
    }
    if (corps.role === "professeur" && (c.classes || []).length) {
      var t = c.titulaire_of || [];
      return c.classes.length + (c.classes.length === 1 ? " classe rattachée" : " classes rattachées")
        + (t.length ? ", titulaire de la " + t.join(" et de la ") : "") + ".";
    }
    return "Vos accès ont été créés.";
  }

  function echec(res) {
    envoiEnCours = false;
    phase("working");   // la coche n'apparaît JAMAIS sur un échec
    var m = mots();
    var dejaUtilisee = res.body && res.body.state === "utilisee";

    el("processingTitle").textContent = dejaUtilisee ? "Ce compte est déjà activé" : "Nous n'avons pas pu finaliser " + m.espace;
    el("processingSub").textContent = "";
    el("processingErrorText").textContent = (res.body && res.body.error) || "Une erreur est survenue.";
    el("processingError").hidden = false;

    // Cas subtil mais réel : la première tentative a abouti côté serveur et la
    // réponse s'est perdue. Le réessai reçoit alors « déjà utilisée ». Proposer
    // « Réessayer » à l'infini serait une impasse — on oriente vers la
    // connexion, qui est la bonne action.
    el("retryBtn").hidden = !!dejaUtilisee;
    el("processingLogin").hidden = !dejaUtilisee;
  }

  el("retryBtn").addEventListener("click", function () {
    if (!dernierePayload) { montrer("stateForm"); return; }
    activer();   // rejoue la MÊME demande ; l'usage unique est garanti côté serveur
  });
})();
