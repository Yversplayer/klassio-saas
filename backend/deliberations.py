"""KLASSIO — les délibérations : réunir les éléments, jamais décider à la place.

CE QUE CE MODULE FAIT ET NE FAIT PAS

Il rassemble, pour chaque élève d'une classe, ce que le conseil doit avoir sous
les yeux : résultats, présence, discipline, conduite, appréciations. Il
SIGNALE ce que les règles de l'établissement désignent comme méritant un
examen. Il ne conclut rien.

La distinction n'est pas de la prudence rhétorique, elle est structurelle :
aucune fonction ici ne renvoie « passe » ou « redouble ». Les indicateurs
valent `ok`, `attention` ou `examiner` — trois mots qui décrivent un DOSSIER,
pas un élève, et qui n'ont pas d'équivalent dans la liste des décisions.

CE QUI N'EST PAS RECONSTRUIT ICI

Les résultats viennent de `school.bulletin()`, la présence de `attendance`, la
discipline de `incidents`, la conduite de `school.conduct_for()`. Aucune
seconde base de notes, aucun second système de présence ou de discipline —
seulement une couche de lecture au-dessus de ce qui existe.
"""
import time

import school
from security import new_id

OK, ATTENTION, EXAMINER = "ok", "attention", "examiner"

DRAFT, IN_PROGRESS, CLOSED = "DRAFT", "IN_PROGRESS", "CLOSED"
PERIOD, ANNUAL = "PERIOD", "ANNUAL"

OBSERVATION, AVIS, DECISION = "OBSERVATION", "AVIS", "DECISION"

# Les décisions possibles. EXTENSIBLE : l'établissement qui a besoin d'un cas
# supplémentaire l'ajoute ici, sans toucher au reste. « AUTRE » n'est pas un
# fourre-tout sans structure — il exige un commentaire, sinon la trace ne dit
# rien à qui la relira dans deux ans.
DECISIONS = {
    "PASSAGE": "Passage en classe supérieure",
    "REDOUBLEMENT": "Redoublement",
    "DEPART": "Départ / non-réinscription",
    "A_EXAMINER": "Situation à examiner (décision différée)",
    "AUTRE": "Autre décision",
}
DECISIONS_EXIGEANT_MOTIF = {"AUTRE", "DEPART", "A_EXAMINER"}

# Correspondance vers `bulletin_decisions`, qui existait AVANT ce module et que
# le bulletin lit déjà. On ne crée pas une seconde vérité : la délibération
# garde l'historique, `bulletin_decisions` porte la décision courante.
VERS_BULLETIN = {"PASSAGE": "admis", "REDOUBLEMENT": "doublant", "A_EXAMINER": "ajourne"}


def _maintenant():
    return str(time.time())


# ---------------------------------------------------------------------------
# Indicateurs — des signaux, pas des verdicts
# ---------------------------------------------------------------------------

def indicateurs(bulletin_eleve, presence, discipline, reglages):
    """Trois signaux, fondés sur les règles RÉELLEMENT configurées.

    Quand une règle n'est pas configurée, l'indicateur reste `ok` : Klassio ne
    signale rien que l'établissement n'ait demandé. Un logiciel qui invente ses
    propres seuils impose une pédagogie à l'école qui l'achète.
    """
    seuil = reglages.get("pass_threshold")
    # `school.bulletin()` expose ce champ sous le nom `percent`.
    pourcent = bulletin_eleve.get("percent")
    if pourcent is None:
        resultats = {"niveau": OK, "valeur": None, "motif": "Aucun résultat enregistré."}
    elif seuil is None:
        resultats = {"niveau": OK, "valeur": pourcent, "motif": None}
    elif pourcent < seuil * 0.8:
        resultats = {"niveau": EXAMINER, "valeur": pourcent,
                     "motif": f"Nettement sous le seuil de réussite ({seuil:g} %)."}
    elif pourcent < seuil:
        resultats = {"niveau": ATTENTION, "valeur": pourcent,
                     "motif": f"Sous le seuil de réussite ({seuil:g} %)."}
    else:
        resultats = {"niveau": OK, "valeur": pourcent, "motif": None}

    maxi = reglages.get("delib_max_absences")
    absences = presence.get("absent") or 0
    if maxi is None:
        pres = {"niveau": OK, "valeur": absences, "motif": None}
    elif absences > maxi * 2:
        pres = {"niveau": EXAMINER, "valeur": absences,
                "motif": f"{absences} absences, très au-delà du maximum fixé ({maxi})."}
    elif absences > maxi:
        pres = {"niveau": ATTENTION, "valeur": absences,
                "motif": f"{absences} absences, au-delà du maximum fixé ({maxi})."}
    else:
        pres = {"niveau": OK, "valeur": absences, "motif": None}

    # La discipline s'appuie sur le capital de points déjà en place : c'est la
    # même mécanique que les seuils affichés ailleurs dans le produit, pas une
    # règle inventée pour l'occasion.
    restant = discipline.get("remaining")
    alerte = reglages.get("discipline_alert_threshold")
    incidents = discipline.get("incidents") or 0
    if restant is None or alerte is None:
        disc = {"niveau": OK, "valeur": incidents, "motif": None}
    elif restant <= alerte:
        disc = {"niveau": EXAMINER, "valeur": incidents,
                "motif": f"Capital de conduite épuisé ({restant} points restants)."}
    elif incidents > 0:
        disc = {"niveau": ATTENTION, "valeur": incidents,
                "motif": f"{incidents} incident(s) enregistré(s)."}
    else:
        disc = {"niveau": OK, "valeur": incidents, "motif": None}

    niveaux = [resultats["niveau"], pres["niveau"], disc["niveau"]]
    if EXAMINER in niveaux:
        # Le libellé décrit le DOSSIER, jamais l'élève. « Situation nécessitant
        # un examen » invite le conseil à regarder ; « élève à faire redoubler »
        # aurait déjà tranché à sa place.
        global_ = {"niveau": EXAMINER, "libelle": "Situation nécessitant un examen"}
    elif ATTENTION in niveaux:
        global_ = {"niveau": ATTENTION, "libelle": "Plusieurs éléments à examiner"}
    else:
        global_ = {"niveau": OK, "libelle": "Rien à signaler"}

    return {"resultats": resultats, "presence": pres, "discipline": disc, "ensemble": global_}


# ---------------------------------------------------------------------------
# Lecture des dépôts
# ---------------------------------------------------------------------------

def entrees(conn, tenant_id, deliberation_id, student_id=None, kind=None, courantes=True):
    """Les dépôts d'une délibération. `courantes` écarte ce qui a été remplacé.

    L'historique reste lisible en passant `courantes=False` : c'est ce qui
    permet de répondre plus tard à « qui avait proposé quoi, et quand la
    position a-t-elle changé ».
    """
    sql = ["SELECT e.*, u.name AS author_name FROM deliberation_entries e",
           "LEFT JOIN users u ON u.id = e.author_id",
           "WHERE e.tenant_id=? AND e.deliberation_id=?"]
    params = [tenant_id, deliberation_id]
    if student_id:
        sql.append("AND e.student_id=?"); params.append(student_id)
    if kind:
        sql.append("AND e.kind=?"); params.append(kind)
    if courantes:
        sql.append("AND e.superseded_at IS NULL")
    sql.append("ORDER BY e.created_at DESC")
    return [dict(r) for r in conn.execute(" ".join(sql), tuple(params)).fetchall()]


def deposer(conn, tenant_id, deliberation_id, student_id, kind, value, comment,
            author_id, author_role):
    """Ajoute un dépôt. N'ÉCRASE JAMAIS.

    Un nouvel AVIS du même auteur remplace le sien — sa position a changé, pas
    celle des autres. Une OBSERVATION ne remplace jamais rien : le conseil
    ajoute, il ne réécrit pas ce qui a été dit.
    """
    maintenant = _maintenant()
    nouvel_id = new_id()
    # INSÉRER D'ABORD, marquer ensuite.
    #
    # `superseded_by` référence `deliberation_entries(id)` : pointer l'ancienne
    # entrée vers une ligne qui n'existe pas encore viole la clé étrangère, et
    # SQLite refuse toute l'opération. Le second dépôt échouait donc en 409, et
    # l'historique — la raison d'être de cette table — ne se constituait jamais.
    conn.execute(
        """INSERT INTO deliberation_entries
           (id, tenant_id, deliberation_id, student_id, kind, value, comment,
            author_id, author_role, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (nouvel_id, tenant_id, deliberation_id, student_id, kind, value, comment,
         author_id, author_role, maintenant))
    if kind in (AVIS, DECISION):
        conn.execute(
            """UPDATE deliberation_entries SET superseded_at=?, superseded_by=?
               WHERE tenant_id=? AND deliberation_id=? AND student_id=? AND kind=?
                 AND author_id=? AND superseded_at IS NULL AND id<>?""",
            (maintenant, nouvel_id, tenant_id, deliberation_id, student_id, kind,
             author_id, nouvel_id))
    conn.commit()
    return nouvel_id
