// KLASSIO — le récit de la démonstration.
//
// CE QUE CETTE COUCHE AJOUTE, ET CE QU'ELLE NE TOUCHE PAS
//
// La démonstration montrait déjà les bons écrans, dans le bon ordre. Ce qui
// lui manquait, c'est une VOIX : rien ne disait pourquoi on passait de la
// caisse aux bulletins, ni ce qu'on devait regarder. Un visiteur voyait
// défiler dix captures d'un logiciel sans comprendre l'histoire qu'elles
// racontent ensemble.
//
// Cette couche est donc uniquement narrative. Elle n'invente aucune donnée,
// ne modifie aucun écran, ne déclenche aucun appel : elle pose, en face de
// chaque étape, un numéro de chapitre et une phrase qui dit ce qui se joue.
// Le défilement fait avancer le récit — c'est le lecteur qui tourne les
// pages, jamais une minuterie.
//
// ESTHÉTIQUE : instrumentation. Libellés en chasse fixe très espacés,
// chiffres en `tabular-nums`, grain léger, accent employé comme ponctuation
// et jamais comme décor. L'identité reste celle de Klassio — le vert est
// l'accent, pas l'ambre de la référence.
(function () {
  "use strict";

  var M = window.KlassioMotion;

  // Le récit, étape par étape. Le texte est ici et nulle part ailleurs : une
  // phrase de démonstration n'a pas à vivre dans le balisage, où elle serait
  // recopiée à chaque retouche de mise en page.
  //
  // Chaque entrée dit CE QUI SE JOUE, pas ce que l'écran contient. « Un
  // tableau des élèves » ne raconte rien ; « le jour où le fichier Excel
  // cesse d'être la vérité » situe l'écran dans une histoire.
  var RECIT = {
    establishment: {
      n: "01",
      titre: "Une école existe déjà avant le logiciel",
      texte: "Deux mille trois cent quarante élèves, quarante-deux classes, "
           + "quatre-vingt-six enseignants. Rien de tout cela n'a été créé par "
           + "Klassio — c'est l'établissement tel qu'il est le jour où il arrive.",
    },
    import: {
      n: "02",
      titre: "Le fichier Excel cesse d'être la vérité",
      texte: "Ce que l'école possède déjà entre tel quel. Klassio lit, propose "
           + "une correspondance, et n'écrit rien tant que la Direction n'a pas "
           + "confirmé. Un import n'est pas une publication.",
    },
    dashboard: {
      n: "03",
      titre: "Ce qu'on voit en ouvrant les yeux le matin",
      texte: "Les appels non faits, l'argent attendu, les signalements à "
           + "qualifier. Pas un tableau de bord d'indicateurs : la liste de ce "
           + "qui demande une décision aujourd'hui.",
    },
    students: {
      n: "04",
      titre: "L'élève est au centre, pas dans une table",
      texte: "Un dossier réunit sa scolarité, ses présences, sa discipline, ses "
           + "frais et ses responsables. L'élève n'a jamais de compte : son "
           + "identifiant sert au pointage, jamais à se connecter.",
    },
    finance: {
      n: "05",
      titre: "L'argent laisse une trace, toujours",
      texte: "Chaque paiement confirmé produit un reçu numéroté. Deux caissiers "
           + "qui encaissent la même minute ne créent jamais deux fois le même "
           + "numéro — c'est vérifié sous concurrence réelle.",
    },
    attendance: {
      n: "06",
      titre: "La discipline se compte, elle ne s'improvise pas",
      texte: "Un capital de points, des règles que l'établissement écrit "
           + "lui-même, des seuils qu'il choisit. Klassio applique ; il ne "
           + "décide pas de ce qui mérite combien.",
    },
    results: {
      n: "07",
      titre: "Saisir n'est pas proclamer",
      texte: "Les notes existent dès la saisie pour le personnel. Les parents "
           + "ne les voient qu'après la proclamation de la période — une "
           + "décision distincte, avec son audience, calculée par le serveur.",
    },
    notifications: {
      n: "08",
      titre: "Prévenir sans inonder",
      texte: "Une absence, un incident, un reçu, une proclamation. Le parent "
           + "reçoit ce qui concerne son enfant, et rien d'autre.",
    },
    roles: {
      n: "09",
      titre: "Quatre rôles, quatre horizons",
      texte: "Direction, Directeur des disciplines, professeur, parent. Le "
           + "périmètre n'est pas un affichage : le serveur refuse ce qui sort "
           + "du rôle, bouton masqué ou non.",
    },
    trust: {
      n: "10",
      titre: "Vos données restent les vôtres",
      texte: "Exportables à tout moment, isolées de tout autre établissement, "
           + "et jamais écrasées : un résultat corrigé crée une version, "
           + "l'ancienne est datée et conservée.",
    },
  };

  function el(tag, cls, texte) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (texte != null) n.textContent = texte;
    return n;
  }

  // ---------------------------------------------------------------------
  // Le chapitre, posé devant chaque étape
  // ---------------------------------------------------------------------

  function poserChapitres() {
    var etapes = document.querySelectorAll(".demo-step[data-step]");
    Array.prototype.forEach.call(etapes, function (section) {
      var r = RECIT[section.dataset.step];
      if (!r) return;

      var bloc = el("div", "rc-chapitre");
      var ligne = el("div", "rc-ligne");

      var num = el("span", "rc-num", r.n);
      var tiret = el("span", "rc-tiret", "—");
      var titre = el("h2", "rc-titre", r.titre);
      titre.setAttribute("data-mo", "words");

      ligne.appendChild(num);
      ligne.appendChild(tiret);
      ligne.appendChild(titre);

      var texte = el("p", "rc-texte", r.texte);
      texte.setAttribute("data-mo", "words");
      texte.setAttribute("data-mo-delay", "180");

      bloc.appendChild(ligne);
      bloc.appendChild(texte);
      section.insertBefore(bloc, section.firstChild);
    });
  }

  // ---------------------------------------------------------------------
  // Le rail : où l'on en est dans l'histoire
  // ---------------------------------------------------------------------

  /**
   * Un rail vertical de pastilles, à droite.
   *
   * Il double la barre de progression existante plutôt que de la remplacer :
   * celle du haut nomme les étapes, celle-ci dit à quelle profondeur du récit
   * on se trouve, d'un coup d'œil et sans lire. Les deux restent cliquables.
   *
   * Masqué sous 820 px : sur un téléphone, une colonne fixe à droite mange
   * une largeur qu'on n'a pas, et le pouce atteint déjà la barre du haut.
   */
  function poserRail() {
    var etapes = Array.prototype.slice.call(document.querySelectorAll(".demo-step[data-step]"));
    if (etapes.length < 2) return null;

    var rail = el("nav", "rc-rail");
    rail.setAttribute("aria-label", "Progression du récit");
    var pastilles = etapes.map(function (section, i) {
      var r = RECIT[section.dataset.step];
      var b = el("button", "rc-pastille");
      b.type = "button";
      b.setAttribute("aria-label", (r ? r.n + " — " + r.titre : "Étape " + (i + 1)));
      b.appendChild(el("span", "rc-p-point"));
      b.appendChild(el("span", "rc-p-nom", r ? r.n : String(i + 1)));
      b.addEventListener("click", function () {
        section.scrollIntoView({ behavior: M && M.reduit ? "auto" : "smooth", block: "start" });
      });
      rail.appendChild(b);
      return b;
    });
    document.body.appendChild(rail);

    // L'étape courante est celle dont le haut est passé au-dessus du tiers
    // supérieur : un simple « la plus visible » fait clignoter le rail au
    // moment où deux sections se partagent l'écran.
    var io = new IntersectionObserver(function (entrees) {
      entrees.forEach(function (e) {
        var i = etapes.indexOf(e.target);
        if (i < 0) return;
        if (e.isIntersecting) {
          pastilles.forEach(function (p, j) {
            p.classList.toggle("rc-actif", j === i);
            p.setAttribute("aria-current", j === i ? "step" : "false");
          });
        }
      });
    }, { rootMargin: "-33% 0px -60% 0px", threshold: 0 });
    etapes.forEach(function (s) { io.observe(s); });
    return rail;
  }

  // ---------------------------------------------------------------------
  // Grain
  // ---------------------------------------------------------------------

  /**
   * Un grain fixe, très faible, en `overlay`.
   *
   * Sur un fond sombre presque uni, un dégradé pur montre des bandes sur la
   * plupart des écrans. Le grain casse ces bandes et donne au fond une
   * matière — c'est le seul rôle qu'il a ici, et il ne doit jamais devenir
   * visible en tant que tel.
   *
   * Dessiné une fois dans un canvas hors écran, puis répété en fond : un
   * SVG de turbulence recalculé à chaque image coûterait cher pour rien.
   */
  function poserGrain() {
    if (M && M.reduit) return;
    var taille = 128;
    var c = document.createElement("canvas");
    c.width = c.height = taille;
    var ctx = c.getContext("2d");
    if (!ctx) return;
    var img = ctx.createImageData(taille, taille);
    for (var i = 0; i < img.data.length; i += 4) {
      var v = (Math.random() * 255) | 0;
      img.data[i] = img.data[i + 1] = img.data[i + 2] = v;
      img.data[i + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
    var couche = el("div", "rc-grain");
    couche.setAttribute("aria-hidden", "true");
    couche.style.backgroundImage = "url(" + c.toDataURL("image/png") + ")";
    document.body.appendChild(couche);
  }

  // ---------------------------------------------------------------------

  function demarrer() {
    if (!document.querySelector(".demo-step[data-step]")) return;
    poserChapitres();
    poserRail();
    poserGrain();
    // Le moteur observe APRÈS que les chapitres existent, sinon il n'a rien
    // à préparer.
    if (M) {
      M.observer(document.getElementById("demoContent") || document);
      M.typographieCinetique();
      M.curseur();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", demarrer);
  } else {
    demarrer();
  }
})();
