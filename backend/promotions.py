"""KLASSIO — le passage d'année : préparer la rentrée sans jamais la décider.

CE QUE FAIT CE MODULE

Il construit un PLAN : pour chaque élève de l'année qui se termine, ce qu'il
advient de lui l'année prochaine. Le plan se relit, se corrige, se valide, et
ne produit d'effet qu'au moment où la Direction l'applique.

CE QU'IL NE FAIT PAS, ET POURQUOI

Il ne décide pas qui passe. L'action de chaque élève est REPRISE d'une décision
déjà prise ailleurs — la délibération, ou la décision de fin d'année — et vaut
`EN_ATTENTE` quand il n'y en a aucune. Un logiciel qui ferait passer par défaut
les élèves non délibérés transformerait un oubli administratif en décision
pédagogique, silencieusement, pour toute une école.

Il ne devine pas non plus la classe d'arrivée. Klassio ne sait pas ce qui vient
après la « 5e Scientifique A » : cela dépend de l'établissement, de la section,
des options et du nombre de classes ouvertes. La Direction désigne les
destinations ; la répartition ne fait qu'ÉQUILIBRER LES EFFECTIFS entre celles
qu'elle a désignées. C'est une tâche de logistique, pas de pédagogie.

CE QU'IL NE RECONSTRUIT PAS

L'identité de l'élève ne change pas au passage : `students` garde le même
`student_id`, seules son année et sa classe avancent. Les notes, incidents,
présences, frais et responsables restent donc attachés à l'élève sans qu'une
seule ligne soit recopiée. Ce qui disparaîtrait — la classe qu'il quittait —
est consigné dans `student_enrollments` à l'instant où il la quitte.
"""
import time

import school
from security import new_id

# Ce qu'il advient d'un élève. EN_ATTENTE n'est pas un quatrième sort : c'est
# l'aveu qu'on n'en sait rien, et il BLOQUE l'application du plan.
PASSAGE, REDOUBLEMENT, DEPART, EN_ATTENTE = "PASSAGE", "REDOUBLEMENT", "DEPART", "EN_ATTENTE"
ACTIONS = {
    PASSAGE: "Passage en classe supérieure",
    REDOUBLEMENT: "Redoublement",
    DEPART: "Départ / non-réinscription",
    EN_ATTENTE: "En attente de décision",
}
# Les deux seules actions qui amènent l'élève dans la nouvelle année — et donc
# les deux seules qui exigent une classe d'arrivée.
ACTIONS_AVEC_CLASSE = (PASSAGE, REDOUBLEMENT)

BROUILLON, EN_REVUE, VALIDE, APPLIQUE = "BROUILLON", "EN_REVUE", "VALIDE", "APPLIQUE"
MODIFIABLE = (BROUILLON, EN_REVUE)

DELIBERATION, BULLETIN, PROPOSITION, MANUEL = "DELIBERATION", "BULLETIN", "PROPOSITION", "MANUEL"

# Décision de délibération → sort dans le plan. « AUTRE » et « A_EXAMINER »
# tombent volontairement en EN_ATTENTE : ce sont des décisions de NE PAS
# trancher, et les traduire en passage serait trancher à la place du conseil.
DEPUIS_DELIBERATION = {
    "PASSAGE": PASSAGE,
    "REDOUBLEMENT": REDOUBLEMENT,
    "DEPART": DEPART,
    "A_EXAMINER": EN_ATTENTE,
    "AUTRE": EN_ATTENTE,
}
# `bulletin_decisions`, pour les établissements qui arrêtent la décision de fin
# d'année sans tenir de délibération dans Klassio.
DEPUIS_BULLETIN = {"admis": PASSAGE, "doublant": REDOUBLEMENT, "ajourne": EN_ATTENTE}


def _maintenant():
    return str(time.time())


# ---------------------------------------------------------------------------
# Les décisions déjà prises — jamais inventées
# ---------------------------------------------------------------------------

def decisions_existantes(conn, tenant_id, year_id):
    """{student_id: (action, origine, motif)} pour l'année qui se termine.

    La délibération PRIME sur `bulletin_decisions` quand les deux existent :
    non par préférence technique, mais parce que la délibération est l'acte,
    et `bulletin_decisions` sa projection. En cas de divergence — décision
    corrigée en séance après une première saisie — c'est la séance qui fait foi.

    Les élèves absents du dictionnaire n'ont AUCUNE décision. Ils ne sont pas
    omis : l'appelant leur attribue EN_ATTENTE, qui bloquera l'application.
    """
    trouve = {}
    # `bulletin_decisions` d'abord : la délibération écrasera au besoin.
    for r in conn.execute(
        """SELECT student_id, decision, note FROM bulletin_decisions
           WHERE tenant_id=? AND academic_year_id=?""", (tenant_id, year_id)):
        action = DEPUIS_BULLETIN.get(r["decision"])
        if action:
            trouve[r["student_id"]] = (action, BULLETIN, r["note"])

    for r in conn.execute(
        """SELECT e.student_id, e.value, e.comment
             FROM deliberation_entries e
             JOIN deliberations d ON d.id = e.deliberation_id
            WHERE e.tenant_id=? AND d.academic_year_id=? AND e.kind='DECISION'
              AND e.superseded_at IS NULL
            ORDER BY e.created_at""", (tenant_id, year_id)):
        action = DEPUIS_DELIBERATION.get(r["value"])
        if action:
            trouve[r["student_id"]] = (action, DELIBERATION, r["comment"])
    return trouve


# ---------------------------------------------------------------------------
# Construction du plan
# ---------------------------------------------------------------------------

def construire(conn, tenant_id, plan_id, source_year_id, auteur_id):
    """Crée une ligne par élève actif de l'année source. Rien de plus.

    Appelée aussi pour RAFRAÎCHIR un plan : les élèves déjà présents ne sont
    pas retouchés — leur ligne porte peut-être un arbitrage de la Direction,
    qu'une reprise des décisions écraserait. Seuls les élèves manquants sont
    ajoutés, ce qui rattrape une inscription tardive sans défaire le travail
    déjà fait.
    """
    decisions = decisions_existantes(conn, tenant_id, source_year_id)
    deja = {r["student_id"] for r in conn.execute(
        "SELECT student_id FROM promotion_assignments WHERE tenant_id=? AND plan_id=?",
        (tenant_id, plan_id))}
    eleves = conn.execute(
        """SELECT id, class_id FROM students
            WHERE tenant_id=? AND academic_year_id=? AND status='active'""",
        (tenant_id, source_year_id)).fetchall()
    ajoutes = repris = 0
    for e in eleves:
        if e["id"] in deja:
            # Un élève DÉJÀ dans le plan n'est pas retouché… sauf s'il y
            # attend encore une décision que personne n'avait prise à
            # l'ouverture. Une ligne EN_ATTENTE sans origine ne porte aucun
            # arbitrage de la Direction : il n'y a rien à préserver, et la
            # délibération qui vient d'avoir lieu doit s'y refléter. Sans cela,
            # délibérer APRÈS avoir ouvert le plan ne servait à rien.
            decision = decisions.get(e["id"])
            if decision:
                repris += conn.execute(
                    """UPDATE promotion_assignments SET action=?, origin=?, note=?
                        WHERE tenant_id=? AND plan_id=? AND student_id=?
                          AND action=? AND origin IS NULL""",
                    (decision[0], decision[1], decision[2], tenant_id, plan_id,
                     e["id"], EN_ATTENTE)).rowcount or 0
            continue
        action, origine, motif = decisions.get(e["id"], (EN_ATTENTE, None, None))
        conn.execute(
            """INSERT INTO promotion_assignments
               (id, tenant_id, plan_id, student_id, source_class_id, action,
                target_class_id, origin, note, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (new_id(), tenant_id, plan_id, e["id"], e["class_id"], action,
             None, origine, motif, _maintenant()))
        ajoutes += 1
    conn.commit()
    return {"ajoutes": ajoutes, "repris": repris}


def lignes(conn, tenant_id, plan_id, class_ids=None):
    """Le plan, élève par élève, avec de quoi le relire sans ouvrir dix écrans."""
    sql = ["""SELECT a.*, s.first_name, s.last_name, s.code,
                     sc.name AS source_class_name, sc.level AS source_class_level,
                     tc.name AS target_class_name, tc.level AS target_class_level
                FROM promotion_assignments a
                JOIN students s ON s.id = a.student_id
                LEFT JOIN classes sc ON sc.id = a.source_class_id
                LEFT JOIN classes tc ON tc.id = a.target_class_id
               WHERE a.tenant_id=? AND a.plan_id=?"""]
    params = [tenant_id, plan_id]
    if class_ids is not None:
        if not class_ids:
            return []
        sql.append(f"AND a.source_class_id IN ({','.join('?' for _ in class_ids)})")
        params.extend(class_ids)
    sql.append("ORDER BY sc.name, s.last_name, s.first_name")
    return [dict(r) for r in conn.execute(" ".join(sql), tuple(params)).fetchall()]


def _non_couverts(conn, tenant_id, plan, classes=None):
    """Élèves actifs de l'année source ABSENTS du plan.

    Trouvé en écrivant les tests : un élève inscrit après l'ouverture du plan
    n'y figure pas, et `etat()` — qui ne regardait que les lignes du plan —
    déclarait celui-ci complet. L'établissement pouvait donc basculer d'année
    en laissant un enfant derrière, sans aucun signal.

    Le rattrapage manuel (`/refresh`) ne suffit pas comme garde-fou : il
    suppose qu'on ait pensé à le faire. La couverture est donc revérifiée à
    chaque lecture de l'état, et bloque la validation comme l'application.
    """
    filtre, extra = "", []
    if classes is not None:
        if not classes:
            return []
        filtre = f" AND s.class_id IN ({','.join('?' for _ in classes)})"
        extra = list(classes)
    return conn.execute(
        f"""SELECT s.id, s.first_name, s.last_name, c.name AS source_class_name
             FROM students s
             LEFT JOIN classes c ON c.id = s.class_id
            WHERE s.tenant_id=? AND s.academic_year_id=? AND s.status='active'
              AND NOT EXISTS (SELECT 1 FROM promotion_assignments a
                               WHERE a.plan_id=? AND a.student_id=s.id){filtre}
            ORDER BY c.name, s.last_name""",
        tuple([tenant_id, plan["source_year_id"], plan["id"]] + extra)).fetchall()


def etat(conn, tenant_id, plan, classes=None):
    """Ce qui manque encore, en clair, avant de pouvoir appliquer.

    Trois comptes séparés, parce que ce sont trois problèmes différents avec
    trois responsables différents : `sans_decision` relève du conseil de
    classe, `sans_classe` de la Direction, `non_couverts` du secrétariat qui a
    inscrit un élève depuis. Les confondre dans un seul « 20 élèves
    incomplets » n'aiderait personne à savoir qui doit agir.
    """
    par_action = {a: 0 for a in ACTIONS}
    sans_decision = sans_classe = 0
    # `classes` restreint l'état au périmètre du lecteur : un titulaire voit
    # où en est SA classe, pas où en est l'école.
    filtre, extra = "", []
    if classes is not None:
        if not classes:
            return {"total": 0, "par_action": par_action, "sans_decision": 0,
                    "sans_classe": 0, "non_couverts": 0, "applicable": False}
        filtre = f" AND source_class_id IN ({','.join('?' for _ in classes)})"
        extra = list(classes)
    for r in conn.execute(
        f"""SELECT action, target_class_id FROM promotion_assignments
            WHERE tenant_id=? AND plan_id=?{filtre}""",
            tuple([tenant_id, plan["id"]] + extra)):
        par_action[r["action"]] = par_action.get(r["action"], 0) + 1
        if r["action"] == EN_ATTENTE:
            sans_decision += 1
        elif r["action"] in ACTIONS_AVEC_CLASSE and not r["target_class_id"]:
            sans_classe += 1
    total = sum(par_action.values())
    non_couverts = len(_non_couverts(conn, tenant_id, plan, classes))
    return {
        "total": total,
        "par_action": par_action,
        "sans_decision": sans_decision,
        "sans_classe": sans_classe,
        "non_couverts": non_couverts,
        "applicable": (sans_decision == 0 and sans_classe == 0
                       and non_couverts == 0 and total > 0),
    }


def bloquants(conn, tenant_id, plan, limite=50, classes=None):
    """Les élèves qui empêchent l'application, nommés. Un compte ne suffit pas :
    la Direction doit savoir QUI aller chercher, et pour quoi faire."""
    filtre, extra = "", []
    if classes is not None:
        if not classes:
            return [], 0
        filtre = f" AND a.source_class_id IN ({','.join('?' for _ in classes)})"
        extra = list(classes)
    rows = conn.execute(
        f"""SELECT a.student_id, a.action, a.target_class_id, s.first_name, s.last_name,
                  c.name AS source_class_name
             FROM promotion_assignments a
             JOIN students s ON s.id = a.student_id
             LEFT JOIN classes c ON c.id = a.source_class_id
            WHERE a.tenant_id=? AND a.plan_id=?
              AND (a.action=? OR (a.action IN (?,?) AND a.target_class_id IS NULL)){filtre}
            ORDER BY c.name, s.last_name""",
        tuple([tenant_id, plan["id"], EN_ATTENTE, PASSAGE, REDOUBLEMENT] + extra)).fetchall()
    sortie = []
    for r in rows[:limite]:
        sortie.append({
            "student_id": r["student_id"],
            "nom": f"{r['first_name']} {r['last_name']}".strip(),
            "classe": r["source_class_name"],
            "manque": "décision" if r["action"] == EN_ATTENTE else "classe d'arrivée",
        })
    absents = _non_couverts(conn, tenant_id, plan, classes)
    for r in absents[:max(0, limite - len(sortie))]:
        sortie.append({
            "student_id": r["id"],
            "nom": f"{r['first_name']} {r['last_name']}".strip(),
            "classe": r["source_class_name"],
            "manque": "absent du plan",
        })
    return sortie, len(rows) + len(absents)


# ---------------------------------------------------------------------------
# Répartition — équilibrer des effectifs, pas arbitrer des dossiers
# ---------------------------------------------------------------------------

def repartir(conn, tenant_id, plan_id, source_class_id, destinations, auteur_id,
             remplacer=False):
    """Répartit les élèves d'une classe source entre les destinations CHOISIES.

    La seule règle appliquée est l'équilibre des effectifs, et elle compte les
    élèves DÉJÀ placés dans chaque destination — y compris ceux venus d'une
    autre classe source, sans quoi répartir la 5e A puis la 5e B remplirait
    deux fois la même 6e A.

    L'ordre est alphabétique, donc reproductible : deux exécutions donnent le
    même résultat, et la Direction peut relire ce qui a changé. Un tirage
    aléatoire aurait été impossible à vérifier.

    `remplacer=False` ne touche QUE les élèves non placés. C'est le défaut :
    relancer la répartition après avoir corrigé trois élèves à la main ne doit
    pas effacer ces trois corrections.
    """
    if not destinations:
        raise ValueError("Aucune classe de destination.")

    # Effectifs déjà engagés dans chaque destination, toutes classes sources
    # confondues.
    charge = {d: 0 for d in destinations}
    for r in conn.execute(
        """SELECT target_class_id, COUNT(*) AS n FROM promotion_assignments
            WHERE tenant_id=? AND plan_id=? AND target_class_id IS NOT NULL
            GROUP BY target_class_id""", (tenant_id, plan_id)):
        if r["target_class_id"] in charge:
            charge[r["target_class_id"]] = r["n"]

    conditions = ["a.tenant_id=?", "a.plan_id=?", "a.source_class_id=?",
                  f"a.action IN ({','.join('?' for _ in ACTIONS_AVEC_CLASSE)})"]
    params = [tenant_id, plan_id, source_class_id, *ACTIONS_AVEC_CLASSE]
    if not remplacer:
        conditions.append("a.target_class_id IS NULL")
    candidats = conn.execute(
        f"""SELECT a.id, a.target_class_id FROM promotion_assignments a
             JOIN students s ON s.id = a.student_id
            WHERE {' AND '.join(conditions)}
            ORDER BY s.last_name, s.first_name, s.id""", tuple(params)).fetchall()

    if remplacer:
        # Les places qu'on va libérer ne doivent pas rester comptées.
        for c in candidats:
            if c["target_class_id"] in charge:
                charge[c["target_class_id"]] -= 1

    maintenant = _maintenant()
    places = 0
    for c in candidats:
        cible = min(destinations, key=lambda d: (charge[d], destinations.index(d)))
        conn.execute(
            """UPDATE promotion_assignments
                  SET target_class_id=?, origin=?, updated_by=?, updated_at=?
                WHERE id=? AND tenant_id=?""",
            (cible, PROPOSITION, auteur_id, maintenant, c["id"], tenant_id))
        charge[cible] += 1
        places += 1
    conn.commit()
    return places


# ---------------------------------------------------------------------------
# Application — le seul moment où quelque chose bouge
# ---------------------------------------------------------------------------

def consigner_inscription(conn, tenant_id, student_id, academic_year_id, class_id,
                          source="PROMOTION"):
    """Note où l'élève était cette année-là. Sans écraser ce qui s'y trouve.

    `DO NOTHING` sur conflit : une inscription déjà consignée — par un passage
    d'année, ou par une correction et son motif — ne doit pas être réécrite
    par un déplacement ultérieur.
    """
    if not academic_year_id:
        return
    conn.execute(
        """INSERT INTO student_enrollments
           (id, tenant_id, student_id, academic_year_id, class_id, source, created_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(tenant_id, student_id, academic_year_id) DO NOTHING""",
        (new_id(), tenant_id, student_id, academic_year_id, class_id, source, _maintenant()))


def appliquer(conn, tenant_id, plan, auteur_id):
    """Exécute le plan. Aucune donnée n'est supprimée, aucune n'est recopiée.

    Pour chaque élève, dans cet ordre :
      1. on consigne l'inscription de l'année QUI SE TERMINE — c'est la seule
         information que la suite ferait disparaître ;
      2. on avance l'élève : même `student_id`, nouvelle année, nouvelle classe.

    Un DÉPART ne fait pas entrer l'élève dans la nouvelle année : son dossier
    passe en `archived` et reste rattaché à son année de sortie. Archivé ne
    veut jamais dire supprimé — le dossier, les notes et les frais restent
    consultables.
    """
    maintenant = _maintenant()
    source, cible = plan["source_year_id"], plan["target_year_id"]
    deplaces = archives = 0

    for a in conn.execute(
        """SELECT student_id, action, source_class_id, target_class_id
             FROM promotion_assignments WHERE tenant_id=? AND plan_id=?""",
            (tenant_id, plan["id"])).fetchall():
        # 1. L'inscription qui se termine.
        consigner_inscription(conn, tenant_id, a["student_id"], source, a["source_class_id"])

        if a["action"] == DEPART:
            conn.execute(
                "UPDATE students SET status='archived' WHERE id=? AND tenant_id=?",
                (a["student_id"], tenant_id))
            archives += 1
            continue
        if a["action"] not in ACTIONS_AVEC_CLASSE or not a["target_class_id"]:
            # Ne devrait pas survenir : `etat()` l'interdit en amont. On ne
            # déplace surtout pas « au mieux » — un élève sans classe d'arrivée
            # atterrirait n'importe où.
            continue

        # 2. L'élève avance. Son identité ne change pas.
        conn.execute(
            """UPDATE students SET academic_year_id=?, class_id=?
                WHERE id=? AND tenant_id=?""",
            (cible, a["target_class_id"], a["student_id"], tenant_id))
        consigner_inscription(conn, tenant_id, a["student_id"], cible, a["target_class_id"])
        deplaces += 1

    # LA BASCULE, dans la même opération que le déplacement des élèves.
    #
    # Elle n'est pas une étape suivante qu'on pourrait oublier : entre des
    # élèves déjà passés dans l'année cible et une année active restée sur la
    # source, l'établissement se retrouverait devant ses anciennes classes
    # vidées de leurs élèves. Cet état intermédiaire ne doit pas exister, donc
    # il n'existe pas — appliquer un plan, c'est ouvrir la nouvelle année.
    conn.execute("UPDATE academic_years SET is_active=0, status=? WHERE tenant_id=? AND status=?",
                 ("ARCHIVED", tenant_id, "ACTIVE"))
    conn.execute("UPDATE academic_years SET is_active=0 WHERE tenant_id=?", (tenant_id,))
    conn.execute("UPDATE academic_years SET is_active=1, status=? WHERE id=? AND tenant_id=?",
                 ("ACTIVE", cible, tenant_id))
    conn.execute(
        """UPDATE promotion_plans SET status=?, applied_by=?, applied_at=?
            WHERE id=? AND tenant_id=?""",
        (APPLIQUE, auteur_id, maintenant, plan["id"], tenant_id))
    conn.commit()
    return {"deplaces": deplaces, "archives": archives}


# ---------------------------------------------------------------------------
# Préparer la structure de la nouvelle année
# ---------------------------------------------------------------------------

def copier_classes(conn, tenant_id, source_year_id, target_year_id):
    """Recrée dans la nouvelle année les classes de l'ancienne, à l'identique.

    Sans cela, une école de vingt classes les ressaisit une à une avant de
    pouvoir répartir quoi que ce soit. La copie porte le nom, le niveau et le
    cycle — rien d'autre : ni les élèves, ni les titulaires, ni l'horaire, qui
    sont des choix de la nouvelle année.

    LE CYCLE EST RECOPIÉ, JAMAIS REDEVINÉ. Le déduire à nouveau à partir du
    nom rejouerait l'approximation d'origine à chaque rentrée — et effacerait
    une correction que la Direction aurait faite entre-temps. `cycle_source`
    voyage avec lui : une classe déclarée reste déclarée, une classe déduite
    reste signalée comme à confirmer.

    Idempotent : une classe dont le nom existe déjà dans l'année cible est
    laissée en place. Relancer la copie ne crée pas de doublons.
    """
    existantes = {r["name"] for r in conn.execute(
        "SELECT name FROM classes WHERE tenant_id=? AND academic_year_id=?",
        (tenant_id, target_year_id))}
    maintenant = _maintenant()
    creees = 0
    for c in conn.execute(
        """SELECT name, level, cycle, cycle_source FROM classes
            WHERE tenant_id=? AND academic_year_id=? ORDER BY name""",
            (tenant_id, source_year_id)).fetchall():
        if c["name"] in existantes:
            continue
        conn.execute(
            """INSERT INTO classes (id, tenant_id, academic_year_id, name, level, cycle,
                                    cycle_source, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (new_id(), tenant_id, target_year_id, c["name"], c["level"], c["cycle"],
             c["cycle_source"] or "deduit", maintenant))
        creees += 1
    conn.commit()
    return creees


def inscriptions(conn, tenant_id, student_id):
    """Le parcours d'un élève : où il est, et où il était.

    L'année courante vient de `students` (elle fait foi), les précédentes de
    `student_enrollments`. On les fusionne ici plutôt que de dupliquer l'année
    courante dans la table d'historique, qui deviendrait une seconde vérité à
    maintenir synchronisée.
    """
    parcours = {}
    for r in conn.execute(
        """SELECT e.academic_year_id, e.class_id, c.name AS class_name, y.label AS year_label,
                  y.created_at AS year_created, e.previous_class_id, e.corrected_reason,
                  e.corrected_at, pc.name AS previous_class_name, u.name AS corrected_by_name
             FROM student_enrollments e
             LEFT JOIN classes c ON c.id = e.class_id
             LEFT JOIN classes pc ON pc.id = e.previous_class_id
             LEFT JOIN users u ON u.id = e.corrected_by
             JOIN academic_years y ON y.id = e.academic_year_id
            WHERE e.tenant_id=? AND e.student_id=?""", (tenant_id, student_id)):
        parcours[r["academic_year_id"]] = {
            "academic_year_id": r["academic_year_id"], "year_label": r["year_label"],
            "class_id": r["class_id"], "class_name": r["class_name"],
            "year_created": r["year_created"], "courante": False,
            # La correction se lit dans le parcours : une classe changée en
            # cours d'année sans explication visible serait une anomalie de
            # plus pour qui relit le dossier.
            "previous_class_name": r["previous_class_name"],
            "corrected_reason": r["corrected_reason"],
            "corrected_at": r["corrected_at"],
            "corrected_by_name": r["corrected_by_name"]}
    actuel = conn.execute(
        """SELECT s.academic_year_id, s.class_id, c.name AS class_name, y.label AS year_label,
                  y.created_at AS year_created
             FROM students s
             LEFT JOIN classes c ON c.id = s.class_id
             JOIN academic_years y ON y.id = s.academic_year_id
            WHERE s.id=? AND s.tenant_id=?""", (student_id, tenant_id)).fetchone()
    if actuel:
        # `students` fait foi pour l'année courante ; la trace de correction,
        # elle, vient de l'inscription et doit survivre à cette fusion.
        garde = parcours.get(actuel["academic_year_id"], {})
        parcours[actuel["academic_year_id"]] = {
            "academic_year_id": actuel["academic_year_id"], "year_label": actuel["year_label"],
            "class_id": actuel["class_id"], "class_name": actuel["class_name"],
            "year_created": actuel["year_created"], "courante": True,
            "previous_class_name": garde.get("previous_class_name"),
            "corrected_reason": garde.get("corrected_reason"),
            "corrected_at": garde.get("corrected_at"),
            "corrected_by_name": garde.get("corrected_by_name")}
    return sorted(parcours.values(), key=lambda p: p["year_created"] or "", reverse=True)


# ---------------------------------------------------------------------------
# Correction après coup — locale, motivée, tracée
# ---------------------------------------------------------------------------

def corriger_affectation(conn, tenant_id, student_id, eleve, nouvelle_classe,
                         motif, auteur_id):
    """Change la classe d'un élève DANS SON ANNÉE COURANTE, et garde la trace.

    Ce n'est pas un retour en arrière sur la rentrée. Une rentrée appliquée ne
    se défait pas : elle a produit des inscriptions, des listes d'appel, des
    bulletins en cours. Ce qui se corrige, c'est UNE affectation — « cet élève
    devait aller en 6e B » — sans rien toucher d'autre.

    Ce qui n'est jamais modifié :
      - l'élève lui-même, qui garde son `student_id` et tout ce qui y pend ;
      - les inscriptions des ANNÉES PASSÉES, qui sont de l'histoire ;
      - les résultats, présences, incidents et frais déjà enregistrés, qui
        portent leur propre année.

    La classe quittée est conservée dans `previous_class_id` : corriger sans
    elle effacerait précisément ce qu'on corrige. Les corrections successives
    s'empilent dans `audit_logs` ; l'inscription ne porte que la dernière,
    celle qui se lit dans le dossier.
    """
    maintenant = _maintenant()
    ancienne = eleve["class_id"]
    annee = eleve["academic_year_id"]

    conn.execute("UPDATE students SET class_id=? WHERE id=? AND tenant_id=?",
                 (nouvelle_classe, student_id, tenant_id))
    # L'inscription de l'année COURANTE uniquement. Le WHERE porte l'année :
    # sans lui, une correction réécrirait aussi le passé de l'élève.
    modifiees = conn.execute(
        """UPDATE student_enrollments
              SET class_id=?, previous_class_id=?, corrected_reason=?,
                  corrected_by=?, corrected_at=?, source='CORRECTION'
            WHERE tenant_id=? AND student_id=? AND academic_year_id=?""",
        (nouvelle_classe, ancienne, motif, auteur_id, maintenant,
         tenant_id, student_id, annee)).rowcount or 0
    if not modifiees:
        # Aucune inscription pour cette année : l'élève n'est pas passé par un
        # plan (inscription directe). On en crée une plutôt que de perdre la
        # correction — c'est le même fait, il mérite la même trace.
        conn.execute(
            """INSERT INTO student_enrollments
               (id, tenant_id, student_id, academic_year_id, class_id, source, created_at,
                previous_class_id, corrected_reason, corrected_by, corrected_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (new_id(), tenant_id, student_id, annee, nouvelle_classe, "CORRECTION",
             maintenant, ancienne, motif, auteur_id, maintenant))
    conn.commit()
    return {"ancienne_classe_id": ancienne, "nouvelle_classe_id": nouvelle_classe,
            "academic_year_id": annee, "corrected_at": maintenant}
