"""Génère les pages app/*.html de Klassio à partir d'une coquille commune.
Les fichiers produits sont statiques (aucune dépendance à ce script au
runtime) ; il sert uniquement à garder une seule source pour la topbar, la
sidebar et les en-têtes de sécurité."""
import os, re, time

ROOT = "/Users/macbookpro/klassio-saas/app"


def _version_cache():
    """Le numéro anti-cache, garanti STRICTEMENT CROISSANT.

    L'horodatage seul ne suffisait pas. Trouvé le 18/09 : des versions posées à
    la main dans les pages étaient datées dans le futur (elles avaient été
    recopiées d'une page à l'autre sans vérifier qu'elles correspondaient à une
    vraie date). Une exécution de ce script les faisait donc RECULER — et une
    version qui recule est exactement ce qu'un anti-cache ne doit jamais faire :
    un navigateur qui a déjà vu ce numéro ressort son ancienne copie du fichier,
    et l'utilisateur garde du JavaScript périmé sans aucun moyen de s'en rendre
    compte.

    On prend donc le plus grand des deux : l'heure actuelle, ou le plus haut
    numéro déjà présent dans les pages, plus un. Quoi qu'il arrive à l'horloge
    ou aux valeurs posées à la main, le numéro monte.
    """
    plus_haut = 0
    for nom in os.listdir(ROOT):
        if not nom.endswith(".html"):
            continue
        with open(os.path.join(ROOT, nom), encoding="utf-8") as f:
            for m in re.finditer(r"\?v=(\d+)", f.read()):
                plus_haut = max(plus_haut, int(m.group(1)))
    return str(max(int(time.time()), plus_haut + 1))


V = _version_cache()

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self' http://localhost:5001; base-uri 'self'; form-action 'self'")

HEAD = """<!doctype html>
<html lang="fr">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{title} — Klassio</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,500;0,600;1,500;1,600&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="../assets/css/style.css?v={v}" />
<meta http-equiv="Content-Security-Policy" content="{csp}">
<script src="../assets/js/theme.js?v={v}"></script>
</head>
"""

THEME_TOGGLE = ('<div class="theme-toggle" id="themeToggle" role="group" aria-label="Thème">'
  '<button type="button" data-theme-choice="light" aria-label="Thème clair"><svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg></button>'
  '<button type="button" data-theme-choice="dark" aria-label="Thème sombre"><svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor"><path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5z"/></svg></button></div>')

SHELL = """<body data-page="{page}">

<div class="app-shell">
  <aside class="sidebar" id="sidebar" aria-label="Navigation principale">
    <div class="s-brand"><img src="../assets/logo.png?v={v}" class="brand-mark" alt="">Klassio</div>
    <nav id="sidebarNav"></nav>
    <div class="s-role" id="roleTag"></div>
  </aside>
  <div class="sidebar-scrim" id="sidebarScrim" hidden></div>

  <div class="main-col">
    <div class="topbar">
      <div class="topbar-left">
        <button class="icon-btn" id="sidebarToggle" aria-label="Afficher ou masquer le menu"></button>
        <a href="../index.html" class="brand" style="font-size:14.5px;"><img src="../assets/logo.png?v={v}" class="brand-mark" style="width:22px;height:22px;" alt="">Klassio</a>
        <div class="school-badge" id="schoolBadge" hidden><span class="sb-kicker">Établissement</span><span class="sb-name" id="schoolBadgeName"></span></div>
      </div>
      <div class="topbar-right">
        {theme}
        <button class="icon-btn bell" id="bellBtn" aria-label="Notifications" aria-haspopup="true"></button>
        <div class="avatar" id="avatarInitial">U</div>
      </div>
    </div>

    <div class="dash-body{bodycls}">
{body}
    </div>
  </div>
</div>

<script src="../assets/js/ui.js?v={v}"></script>
<script src="../assets/js/loader.js?v={v}"></script>
<script src="../assets/js/app.js?v={v}"></script>
<script src="../assets/js/admin.js?v={v}"></script>
<script src="../assets/js/page-{page}.js?v={v}"></script>
</body>
</html>
"""

PAGES = {}

PAGES["dashboard"] = ("Mon espace", "", """
      <div class="page-header">
        <div><h1 id="greeting">Bienvenue.</h1><p id="dashSub">Chargement de votre espace…</p></div>
        <div class="row" id="dashActions"></div>
      </div>
      <div id="dashContent"></div>
""")

PAGES["eleves"] = ("Élèves", "", """
      <div class="page-header">
        <div><h1 id="pageTitle">Élèves</h1><p id="studentCountLabel">Chargement…</p></div>
        <div class="row" id="pageActions"></div>
      </div>
      <div class="kpi-grid" id="studentKpis" hidden></div>
      <div class="toolbar" id="studentToolbar">
        <label class="search" for="studentSearch" id="searchWrap"><input type="search" id="studentSearch" placeholder="Rechercher par nom, prénom ou identifiant…" autocomplete="off" /></label>
        <select id="classFilter" aria-label="Filtrer par classe"><option value="">Toutes les classes</option></select>
        <select id="cycleFilter" aria-label="Filtrer par cycle"><option value="">Tous les cycles</option><option value="maternelle">Maternelle</option><option value="primaire">Primaire</option><option value="secondaire">Secondaire</option></select>
        <select id="financeFilter" aria-label="Situation financière" hidden><option value="">Toute situation</option><option value="paid">À jour</option><option value="due">Solde restant</option></select>
        <select id="statusFilter" aria-label="Statut" hidden><option value="active">Actifs</option><option value="all">Tous</option><option value="archived">Archivés</option></select>
        <div class="view-toggle" id="viewToggle" role="group" aria-label="Affichage"><button type="button" data-view="folders" class="active" aria-label="Dossiers"></button><button type="button" data-view="table" aria-label="Tableau"></button></div>
      </div>
      <div id="studentsView"></div>
      <div class="pagination" id="studentsPager" hidden></div>
""")

PAGES["eleve-dossier"] = ("Dossier élève", "", """
      <a href="eleves.html" class="page-back" id="backLink"></a>
      <div id="dossierHead"></div>
      <div class="tabs" id="dossierTabs" role="tablist"></div>
      <div id="dossierPanels"></div>
""")

PAGES["classes"] = ("Classes", "", """
      <div class="page-header">
        <div><h1 id="pageTitle">Classes</h1><p id="pageSub">Chargement…</p></div>
        <div class="row" id="pageActions"></div>
      </div>
      <div class="kpi-grid" id="classKpis" hidden></div>
      <div id="classesView"></div>
""")

PAGES["classe"] = ("Classe", "", """
      <a href="classes.html" class="page-back" id="backLink"></a>
      <div id="classHead"></div>
      <div class="tabs" id="classTabs" role="tablist"></div>
      <div id="classPanels"></div>
""")

PAGES["etablissement"] = ("Établissement", "", """
      <div class="page-header">
        <div><h1 id="schoolTitle">Établissement</h1><p id="schoolSub">Chargement…</p></div>
        <div class="row" id="pageActions"></div>
      </div>
      <div id="etabContent"></div>
""")

PAGES["finance"] = ("Finance", "", """
      <div class="page-header">
        <div><h1>Finance</h1><p>Vision globale : attendu, encaissé, restant, évolution — jamais un chiffre stocké, toujours recalculé.</p></div>
        <div class="row" id="pageActions"></div>
      </div>
      <div id="financeContent"></div>
""")

PAGES["paiements"] = ("Paiements", "", """
      <div class="page-header">
        <div><h1 id="pageTitle">Paiements</h1><p id="pageSub">Historique opérationnel : chaque transaction, son moyen, son statut, son reçu.</p></div>
        <div class="row" id="pageActions"></div>
      </div>
      <div id="paymentsContent"></div>
""")

PAGES["discipline"] = ("Discipline", "", """
      <div class="page-header">
        <div><h1 id="pageTitle">Discipline</h1><p id="pageSub">Suivi humain — Klassio enregistre, alerte et informe, mais ne décide jamais d'une sanction.</p></div>
        <div class="row" id="pageActions"></div>
      </div>
      <div id="disciplineContent"></div>
""")

PAGES["boutique"] = ("Boutique", "", """
      <div class="page-header">
        <div><h1 id="pageTitle">Boutique</h1><p id="pageSub">Chargement…</p></div>
        <div class="row" id="pageActions"></div>
      </div>
      <div id="storeContent"></div>
""")

PAGES["notifications"] = ("Notifications", " narrow", """
      <div class="page-header">
        <div><h1>Notifications</h1><p id="pageSub">Tout ce qui vous concerne, dans les limites de votre rôle.</p></div>
        <div class="row" id="pageActions"></div>
      </div>
      <div class="notif-page-list" id="notifPageList"></div>
""")

PAGES["rapports"] = ("Rapports", "", """
      <div class="page-header">
        <div><h1>Rapports</h1><p>Vue d'ensemble réelle de votre établissement — calculée à partir de vos données actuelles.</p></div>
        <div class="row no-print"><button type="button" class="btn btn-ghost btn-sm" id="printBtn"></button></div>
      </div>
      <div id="reportContent"></div>
""")

PAGES["ia"] = ("Assistant", " ia-page", """
      <div class="page-header">
        <div><h1>Assistant Klassio</h1><p>Posez une question sur votre établissement — Klassio lit et analyse, mais n'exécute jamais d'action à votre place.</p></div>
      </div>
      <div class="ia-layout">
        <aside class="ia-history-panel">
          <button class="btn btn-ghost btn-sm" id="newConvBtn" style="width:100%;">Nouvelle conversation</button>
          <div class="ia-history-list" id="convList"></div>
        </aside>
        <div class="ia-chat">
          <div class="ia-thread" id="iaThread">
            <div class="ia-empty-state" id="iaEmptyState">
              <p class="ia-empty-title">Comment puis-je vous aider ?</p>
              <div class="ia-suggestions" id="iaSuggestions"></div>
            </div>
          </div>
          <form class="ia-composer" id="iaComposer">
            <input type="text" id="iaInput" placeholder="Posez une question à Klassio…" autocomplete="off" />
            <button type="submit" class="ia-send-btn" id="iaSendBtn" aria-label="Envoyer">↑</button>
          </form>
        </div>
      </div>
""")

PAGES["parametres"] = ("Paramètres", " narrow", """
      <div class="page-header">
        <div><h1>Paramètres</h1><p>Votre compte, votre sécurité et — pour la Direction — les règles de votre établissement.</p></div>
      </div>
      <div class="panel">
        <div class="panel-head"><h2>Votre compte</h2></div>
        <dl class="dl"><dt>Nom</dt><dd id="pName">—</dd><dt>Rôle</dt><dd id="pRole">—</dd><dt>Établissement</dt><dd id="pSchool">—</dd></dl>
      </div>
      <div id="profilePanel"></div>
      <div class="panel">
        <div class="panel-head"><h2>Changer de mot de passe</h2></div>
        <form id="pwForm" class="form-grid">
          <div class="field"><label for="pwCurrent">Mot de passe actuel</label><input type="password" id="pwCurrent" required autocomplete="current-password" /></div>
          <div class="field"><label for="pwNew">Nouveau mot de passe</label><input type="password" id="pwNew" required autocomplete="new-password" />
            <ul class="pw-rules" id="pwRules"><li data-rule="length">8 caractères minimum</li><li data-rule="upper">Une majuscule</li><li data-rule="lower">Une minuscule</li><li data-rule="digit">Un chiffre</li><li data-rule="special">Un caractère spécial</li></ul>
          </div>
          <div class="full row between"><p class="form-msg" id="pwMsg"></p><button type="submit" class="btn btn-lime btn-sm" id="pwBtn">Mettre à jour</button></div>
        </form>
      </div>
      <div id="settingsPanels"></div>
""")

PAGES["calendrier"] = ("Calendrier", "", """
      <div class="page-header">
        <div><h1>Calendrier</h1><p id="pageSub">Événements de l'école, examens, devoirs, échéances et présences — tout ce qui a une date.</p></div>
        <div class="row" id="pageActions"></div>
      </div>
      <div id="calContent"></div>
""")

PAGES["messages"] = ("Messages", "", """
      <div class="page-header">
        <div><h1>Cahier de communication</h1><p id="pageSub">Un fil par élève entre ses parents, son titulaire, le DD et la Direction — tracé, jamais un numéro personnel.</p></div>
        <div class="row" id="pageActions"></div>
      </div>
      <div id="msgContent"></div>
""")

PAGES["ressources"] = ("Livres & devoirs", "", """
      <div class="page-header">
        <div><h1 id="pageTitle">Livres & devoirs</h1><p id="pageSub">Leçons, livres, fiches et devoirs publiés par les enseignants pour chaque classe.</p></div>
        <div class="row" id="pageActions"></div>
      </div>
      <div id="resContent"></div>
""")

PAGES["documents"] = ("Documents", "", """
      <div class="page-header">
        <div><h1>Documents</h1><p id="pageSub">Règlement, documents officiels de l'établissement, attestations et bulletins imprimables.</p></div>
        <div class="row" id="pageActions"></div>
      </div>
      <div id="docContent"></div>
""")

PAGES["pointage"] = ("Pointage", " narrow", """
      <div class="page-header">
        <div><h1>Pointage au portail</h1><p id="pageSub">L'élève arrive en retard : tapez son nom ou son identifiant, l'heure est enregistrée, le parent et le titulaire sont informés.</p></div>
      </div>
      <div id="gateContent"></div>
""")

PAGES["abonnement"] = ("Abonnement", "", """
      <div class="page-header">
        <div><h1>Abonnement Klassio</h1><p id="pageSub">Ce que votre établissement paie à Klassio — circuit séparé des frais scolaires de vos parents.</p></div>
      </div>
      <div id="subContent"></div>
""")

PAGES["plateforme"] = ("Plateforme", "", """
      <div class="page-header">
        <div><h1>Administration Klassio</h1><p id="pageSub">Établissements, abonnements, factures à confirmer, paliers.</p></div>
      </div>
      <div id="platContent"></div>
""")

PAGES["registres"] = ("Registres", "", """
      <div class="page-header no-print">
        <div><h1>Registres</h1><p id="pageSub">Registre de présence et registre de discipline — imprimables pour l'inspection.</p></div>
        <div class="row" id="pageActions"></div>
      </div>
      <div id="regContent"></div>
""")

def build():
    for page, (title, bodycls, body) in PAGES.items():
        html = HEAD.format(title=title, v=V, csp=CSP) + SHELL.format(page=page, v=V, theme=THEME_TOGGLE, body=body.rstrip("\n"), bodycls=bodycls)
        with open(os.path.join(ROOT, page + ".html"), "w") as f:
            f.write(html)
        print("wrote", page + ".html")

if __name__ == "__main__":
    build()
