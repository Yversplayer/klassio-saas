// KLASSIO — proposer un mot de passe solide, au moment où on le crée.
//
// POURQUOI UNE PHRASE DE PASSE, ET PAS « x7#Kp!2qR9 ». Un mot de passe
// aléatoire est solide, mais un parent sur un petit Android ne sait ni le
// retenir ni le taper : il le note n'importe où, ou l'oublie — et chaque oubli
// coûte un lien de réinitialisation à la Direction (aucun e-mail ne part). Ici :
// quatre mots français simples, SANS ACCENT (rien à chercher sur le clavier,
// rien qui paraisse mal orthographié), et un nombre. Par exemple
// « Mangue-Fleuve-Craie-Pirogue-472 ».
//
// SOLIDITÉ. 792 mots, quatre tirés sans répétition, un nombre de 100 à 999 :
// environ 48 bits. Les mots de passe sont stockés en PBKDF2-SHA256 à 200 000
// itérations, et la connexion se bloque après cinq échecs : deviner une telle
// phrase demanderait des années de calcul par compte. La phrase respecte
// d'office les règles du serveur (8 caractères, majuscule, minuscule, chiffre,
// caractère spécial — le tiret).
//
// CE QUE CE FICHIER NE FAIT JAMAIS. Il tire au sort avec crypto.getRandomValues
// (jamais Math.random, prévisible), sans biais de modulo ; il ne stocke rien,
// n'écrit rien dans la console, n'envoie rien : la phrase part avec le
// formulaire, comme si l'utilisateur l'avait tapée. Sans crypto.getRandomValues,
// le bouton n'apparaît pas — on ne propose pas de mot de passe faible.
//
// Autonome (aucune dépendance) : la page d'invitation ne charge pas app.js.
// Branchement : <input type="password" data-kx-suggere data-kx-confirme="idDuChampDeConfirmation">
(function () {
  "use strict";

  var MOTS = (
    "abeille abricot acacia affiche agenda agile agneau agrafe aider aigle aimant albatros alouette alpaga " +
    "amande amarante ambre ampoule anaconda ananas anis anneau antenne antilope apprendre arachide argent " +
    "argile arroser arrosoir artichaut artiste assiette astre atlas aube aubergine aurore automne autruche " +
    "avion avocat avoine baignoire balai balcon baleine baleineau ballet ballon bambou banane bananier banc " +
    "banjo baobab barque basilic bassine bateau batterie bavoir beau beige berceau bergamote berger beurre " +
    "biche biscuit bison blanc blette bleu bobine bocal boire bonbon bonobo boue bougeoir bougie boulanger " +
    "bouquet bourdon boussole bouteille bouton bracelet branche brave bretelle briller brindille brise " +
    "brocoli bronze brosse brouette brume buffle bulletin bureau cabane cacao cactus cadenas cadre cahier " +
    "caille caillou cajou calcul calepin calme camion canard canari canif cannelle canot cantine canyon cape " +
    "capucin capucine cardinal carnet carotte carpe cartable carte carton cascade casque casquette casserole " +
    "cassis castor cave caverne ceinture cerf cerise chacal chaise chambre chameau chamois champ chant " +
    "chanter chanteur chapeau chardon chasseur chat chaud chaussure chemin chemise chercher cheval chevreuil " +
    "chien chiffre chocolat choisir chorale chou chouette ciel cigale cigogne circuit ciseaux citerne citron " +
    "clair classe classeur climat cloche clou cobalt cobra cochon coco cocotier colibri colle collier colline " +
    "colorier compas compter concert concombre condor conte coquille corail corbeau corde cordon corneille " +
    "cosmos coton coudre couloir coupe courge courir couronne course coussin couteau crabe craie crapaud " +
    "cravate crayon crevette criquet cristal crocodile cueillir cuisine cuisiner cuivre cultiver cumin " +
    "curieux cuvette cyan cygne danse danser danseur datte dattier dauphin delta dentelle dessin dessiner " +
    "devoir diamant dinde dindon docteur domino donner dormir dossier doux drapeau dune duo endive entonnoir " +
    "escalier escargot estragon examen explorer facteur faisan falaise fanfare farine faucon fauteuil fenouil " +
    "fermer fermier feuille ficelle fiche fier figue filet film flacon flamant fleur fleurir fleuve fontaine " +
    "forgeron fort fougasse foulard four fourmi fourneau frais fraise framboise frigo froid fromage furet " +
    "fusain gagner galaxie gant garage garder gare gazelle gazon gecko gentil gerbille gilet gingembre girafe " +
    "girafon givre glace glacier glisser globe gnou gobelet gomme gorille gourde goyave goyavier graine grand " +
    "grandir granit gravier grelot grenier grillage grillon grimper gris grive groseille grotte guirlande " +
    "guitare habile hamac hamster hareng haricot harpe haut herbe hermine heure hibiscus hibou histoire hiver " +
    "homard horaire horloge ibis igname iguane image impala indigo iris jade jaguar jardin jardinier jasmin " +
    "jaune jonquille jouer jouet jour journal joyeux jupiter kaki kiwi koala lac lacet lagune lait laitue " +
    "lama lamantin lampe lanterne lapin laurier lecture lemming lentille lettre libellule libre lierre lilas " +
    "lion lire lisse litchi livre loquet lotus louche loup loupe loutre loyal lune lunette lynx macaque " +
    "magenta maillet malin mallette manchot mandarine manger mangouste mangue manguier manioc mante manteau " +
    "maracas marais marbre marcher marin marmite marmotte marron marteau matin melon menthe menuisier mercure " +
    "merle mesurer midi miel millet mimosa minuit minute miroir moineau mois montagne montre morse moteur " +
    "moto mouche mouchoir mouette moufle moule mousse moustique mouton muguet mulet musique myrtille nager " +
    "napperon narval navet navire neige neptune nickel noble noir noisette noix nombre nuage nuit oasis ocre " +
    "offrir oignon okapi olive olivier opale orage orange orbite orchestre oreiller orge orque oseille " +
    "ouistiti ours ouvrir page pain palette palmier panda pangolin panier panneau paon papaye papillon " +
    "paprika parapluie parler partager passoire patate patient peigne peintre peinture pelle pendule penser " +
    "perche perdrix perle perroquet persil petit phare phoque photo phrase piano pichet pigeon pilote piment " +
    "pince pinceau pingouin pinson piranha pirogue pistache piste placard plage plaine planter plateau " +
    "platine plonger pluie plumeau pluton poire poireau poivre poli pomme pommier pompe poney pont port " +
    "portail porte porter poster potager poterie potier potiron poubelle poule poulie poulpe pourpre poussin " +
    "prairie printemps prune puits puma punaise puzzle python quai quartz quatuor question quille rabot " +
    "racine radio radis raie rail raisin rapide rasoir raton recevoir refrain renard renne requin rhubarbe " +
    "rideau rire robinet robot rocher romarin rond rose roseau rossignol roue rouge rouget rouler route ruban " +
    "rubis ruisseau rumba rythme sable sablier sachet safran sage saison salade salon sandale sanglier saphir " +
    "sapin sardine sarrasin satellite saturne sauce saucier saule saumon saut sauter savane savoir savon " +
    "sceau scie science scorpion seau seconde seigle selle semaine semer sentier serpent serviette sifflet " +
    "signal singe soir soja sole soleil solide solo sommet sonnette sorgho soucoupe souffler soupe source " +
    "sourire souris sport stylo sucre suricate table tableau tablier tabouret taille tamarin tambour tamis " +
    "tapis tasse tasseau taupe taureau taxi tempo tenaille termite terrasse texte thermos thon thym tige " +
    "tigre tilapia tilleul timbale tiroir tisser titane toile toit tomate tonneau tonnerre torchon tortue " +
    "toucan toupie tourner tournesol tournevis tracer tracteur train treuil tricot trio triton trombone " +
    "trompette tronc trousse trousseau trouver truite tulipe tunique turban turquoise tuyau vache vague " +
    "valise vallon vanille varan vase vaste vautour veau vent verger verre verrou vert veste vigne violet " +
    "violon vison voilier voiture volant volcan voler voyager wagon wapiti yaourt zinc "
  ).trim().split(" ");

  var crypto = window.crypto || window.msCrypto;
  var disponible = !!(crypto && crypto.getRandomValues);

  // Entier uniforme dans [0, n) — rejet des tirages au-delà du plus grand
  // multiple de n, sinon les premiers mots sortiraient un peu plus souvent.
  function hasard(n) {
    var limite = Math.floor(4294967296 / n) * n, t = new Uint32Array(1);
    do { crypto.getRandomValues(t); } while (t[0] >= limite);
    return t[0] % n;
  }

  function proposer() {
    var choisis = [];
    while (choisis.length < 4) {
      var m = MOTS[hasard(MOTS.length)];
      if (choisis.indexOf(m) === -1) choisis.push(m);
    }
    return choisis.map(function (m) { return m.charAt(0).toUpperCase() + m.slice(1); }).join("-") + "-" + (100 + hasard(900));
  }

  var ICONE_CLE = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="8" cy="15" r="4"/><path d="M10.8 12.2 20 3M16 7l3 3M14 9l2 2"/></svg>';

  function signaler(champ) {
    // Les listes de règles (« 8 caractères minimum »…) écoutent « input ».
    champ.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function copier(texte) {
    // Hors contexte sécurisé (adresse http://192.168… sur le Wi-Fi de l'école),
    // l'API presse-papiers n'existe pas ; et même quand elle existe, le
    // navigateur peut la refuser. Dans les deux cas : l'ancienne méthode. On ne
    // dit « copié » que si l'une des deux a vraiment réussi.
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(texte).catch(function () { return copierAncienne(texte); });
    }
    return copierAncienne(texte);
  }

  function copierAncienne(texte) {
    return new Promise(function (ok, ko) {
      var zone = document.createElement("textarea");
      zone.value = texte;
      zone.setAttribute("readonly", "");
      zone.style.position = "fixed";
      zone.style.opacity = "0";
      document.body.appendChild(zone);
      zone.select();
      var reussi = false;
      try { reussi = document.execCommand("copy"); } catch (e) { reussi = false; }
      document.body.removeChild(zone);
      if (reussi) ok(); else ko();
    });
  }

  function brancher(champ) {
    if (!champ || champ.dataset.kxSuggereBranche || !disponible) return;
    champ.dataset.kxSuggereBranche = "1";
    var confirmation = champ.dataset.kxConfirme ? document.getElementById(champ.dataset.kxConfirme) : null;

    var barre = document.createElement("div");
    barre.className = "pws-bar";
    barre.innerHTML =
      '<button type="button" class="pws-btn pws-proposer">' + ICONE_CLE + "Proposer un mot de passe</button>" +
      '<button type="button" class="pws-btn pws-voir" aria-pressed="false">Afficher</button>';
    var panneau = document.createElement("div");
    panneau.className = "pws-panel";
    panneau.hidden = true;
    panneau.setAttribute("role", "status");
    panneau.setAttribute("aria-live", "polite");
    panneau.innerHTML =
      '<span class="pws-kicker">Mot de passe proposé</span>' +
      '<code class="pws-valeur"></code>' +
      '<div class="pws-actions"><button type="button" class="pws-btn pws-copier">Copier</button>' +
      '<button type="button" class="pws-btn pws-autre">Un autre</button><span class="pws-msg"></span></div>' +
      "<p>Facile à retenir, difficile à deviner. Notez-le maintenant, ou laissez votre navigateur l'enregistrer : Klassio ne pourra pas vous le redonner.</p>";
    champ.insertAdjacentElement("afterend", barre);
    barre.insertAdjacentElement("afterend", panneau);

    var boutonVoir = barre.querySelector(".pws-voir");
    var valeur = panneau.querySelector(".pws-valeur");
    var msg = panneau.querySelector(".pws-msg");
    var enCours = false;

    function montrer(visible) {
      [champ, confirmation].forEach(function (c) { if (c) c.type = visible ? "text" : "password"; });
      boutonVoir.textContent = visible ? "Masquer" : "Afficher";
      boutonVoir.setAttribute("aria-pressed", visible ? "true" : "false");
    }
    function remplir() {
      var p = proposer();
      enCours = true;
      champ.value = p;
      signaler(champ);
      if (confirmation) { confirmation.value = p; signaler(confirmation); }
      enCours = false;
      valeur.textContent = p;
      msg.textContent = "";
      panneau.hidden = false;
      montrer(true);
    }
    barre.querySelector(".pws-proposer").addEventListener("click", remplir);
    panneau.querySelector(".pws-autre").addEventListener("click", remplir);
    boutonVoir.addEventListener("click", function () { montrer(champ.type === "password"); });
    panneau.querySelector(".pws-copier").addEventListener("click", function () {
      copier(valeur.textContent).then(function () { msg.textContent = "Copié."; },
        function () { msg.textContent = "Copie impossible ici : sélectionnez-le et copiez-le à la main."; });
    });
    // L'utilisateur reprend la main : la proposition n'est plus la sienne.
    champ.addEventListener("input", function () {
      if (!enCours && champ.value !== valeur.textContent) panneau.hidden = true;
    });
  }

  function init() {
    [].forEach.call(document.querySelectorAll("input[data-kx-suggere]"), brancher);
  }

  window.KlassioMotDePasse = { proposer: proposer, brancher: brancher, nombreDeMots: MOTS.length };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
