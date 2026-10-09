"""KLASSIO — IA générative, palier 1 (décisions du propriétaire, 09/10/2026).

CE QUE FAIT CE MODULE, ET RIEN D'AUTRE
    Quand l'assistant déterministe (ai_assistant.py) n'a PAS compris une
    question d'une Direction, un modèle de langage la REFORMULE en l'une des
    questions types que l'assistant sait traiter. Puis c'est l'assistant
    déterministe qui répond, avec les vrais chiffres de l'école.

POURQUOI CETTE FORME (séminaire « L'IA générative dans Klassio »)
    - Aucune donnée de l'école ne part chez le fournisseur. Il reçoit la
      question, noms masqués (« Élève 1 »), et le catalogue des questions
      types. Jamais un solde, une note, une absence, une liste d'élèves.
    - Le modèle ne peut rien inventer : il choisit une ligne d'un catalogue
      FERMÉ. Un choix hors catalogue, un « Élève 7 » qui n'a pas été masqué,
      une classe trop longue : ignorés, on garde la réponse d'origine.
    - Le modèle n'a aucun outil d'écriture, et ce module ne contient aucune
      écriture en base (test_ia_generative le vérifie, comme pour
      ai_assistant.py). Les demandes d'écriture sont refusées AVANT d'arriver
      ici : answer_question les arrête en premier.
    - Toute panne, lenteur, clé absente ou plafond atteint rend la réponse
      d'origine, telle quelle. L'assistant ne dépend jamais du fournisseur.

QUI EN PROFITE (décision 4 : Direction d'abord ; décision 1 : école pilote)
    Le rôle `directeur`, dans les écoles listées par KLASSIO_IA_ECOLES
    (identifiants séparés par des virgules, ou `*`), si la Direction n'a pas
    coupé l'IA dans ses Paramètres (`ai_generative`). Plafond mensuel par
    école : KLASSIO_IA_PLAFOND_MENSUEL (300 par défaut, décision 5).

LA CLÉ (décision 6)
    OPENAI_API_KEY, saisie par le propriétaire dans Render. Jamais dans le
    code, jamais dans le dépôt. Sans elle, ce module ne fait rien.
"""
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime

import ai_assistant
import school

URL_OPENAI = "https://api.openai.com/v1/chat/completions"
MODELE_PAR_DEFAUT = "gpt-4o-mini"
PLAFOND_PAR_DEFAUT = 300
DELAI_SECONDES = 8
PREFIXE_INTENTION = "gen:"

# ---------------------------------------------------------------------------
# Le catalogue FERMÉ. Chaque gabarit a été vérifié (test_ia_generative) : posé
# à answer_question, il mène à l'intention annoncée. Un gabarit qui dériverait
# vers une autre intention ferait répondre l'assistant à côté de la question.
# ---------------------------------------------------------------------------
CATALOGUE = {
    "situation_financiere": ("Vue d'ensemble des finances : attendu, encaissé, restant",
                             "Analyse ma situation financière", None),
    "encaisse_ce_mois": ("Montant encaissé depuis le début du mois",
                         "Combien avons-nous encaissé ce mois-ci ?", None),
    "encaisse_mois_dernier": ("Montant encaissé le mois précédent",
                              "Combien avons-nous encaissé le mois dernier ?", None),
    "taux_recouvrement": ("Pourcentage des frais déjà payés",
                          "Quel pourcentage des frais est payé ?", None),
    "plus_gros_impayes": ("Les élèves qui doivent le plus",
                          "Quels sont les plus gros impayés ?", None),
    "eleves_sans_paiement": ("Les élèves qui n'ont encore rien payé",
                             "Quels élèves n'ont rien payé ?", None),
    "nombre_eleves": ("Nombre d'élèves de l'école", "Combien d'élèves compte l'établissement ?", None),
    "nombre_classes": ("Nombre de classes de l'école", "Combien de classes avons-nous ?", None),
    "absences_repetees": ("Élèves qui cumulent plusieurs absences sur 30 jours",
                          "Quels élèves ont plusieurs absences ?", None),
    "retards_repetes": ("Élèves qui cumulent plusieurs retards sur 30 jours",
                        "Quels élèves ont plusieurs retards ?", None),
    "incidents_recents": ("Incidents de discipline des 30 derniers jours",
                          "Montre-moi les incidents récents", None),
    "absents_classe": ("Absents et retards du jour dans UNE classe (paramètre classe)",
                       "Combien d'élèves de la {classe} sont absents aujourd'hui ?", "classe"),
    "eleves_classe": ("Liste des élèves d'UNE classe (paramètre classe)",
                      "Élèves de la classe {classe}", "classe"),
    "situation_eleve": ("Dossier résumé d'UN élève : présences, discipline, finances (paramètre eleve)",
                        "Analyse la situation de {eleve}", "eleve"),
    "recus_eleve": ("Reçus de paiement d'UN élève (paramètre eleve)", "Reçus de {eleve}", "eleve"),
    "expliquer_import": ("Comment importer les fichiers Excel de l'école", "Comment importer un fichier Excel ?", None),
    "expliquer_finance_paiements": ("Différence entre les écrans Finance et Paiements",
                                    "Quelle différence entre Finance et Paiements ?", None),
    "expliquer_invitations": ("Comment fonctionnent les invitations des parents et du personnel",
                              "Comment fonctionnent les invitations ?", None),
}
AUCUNE = "aucune"

# Mots qu'on ne masque jamais même s'ils servent de prénom ou de nom : les
# masquer rendrait la question illisible pour le modèle sans rien protéger.
MOTS_COURANTS = {
    "les", "des", "une", "est", "pas", "que", "qui", "quoi", "pour", "dans", "avec", "sur", "par", "mon",
    "mes", "ses", "son", "nos", "vos", "leur", "classe", "classes", "eleve", "eleves", "ecole", "mois",
    "jour", "aujourd", "hui", "combien", "quel", "quels", "quelle", "quelles", "comment", "situation",
    "paiement", "paiements", "frais", "absent", "absents", "retard", "retards", "parent", "parents",
    "directeur", "direction", "professeur", "annee", "semaine", "trimestre", "periode", "notes", "note",
}


def _sans_accent(texte):
    return "".join(c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn").lower()


# ---------------------------------------------------------------------------
# Conditions d'accès
# ---------------------------------------------------------------------------

def _ecoles_autorisees():
    brut = (os.environ.get("KLASSIO_IA_ECOLES") or "").strip()
    if not brut:
        return set()
    return {e.strip() for e in brut.split(",") if e.strip()}


def _plafond():
    try:
        return max(0, int(os.environ.get("KLASSIO_IA_PLAFOND_MENSUEL", PLAFOND_PAR_DEFAUT)))
    except ValueError:
        return PLAFOND_PAR_DEFAUT


def appels_du_mois(conn, tenant_id):
    """Nombre d'appels au fournisseur ce mois-ci pour cette école. Chaque appel
    laisse une réponse d'intention `gen:…` dans ai_messages : on compte celles-là,
    qu'elles aient abouti ou non, puisque chacune a été facturée."""
    debut = datetime.combine(date.today().replace(day=1), datetime.min.time()).timestamp()
    # created_at est un horodatage en texte (str(time.time())) : dix chiffres
    # avant la virgule jusqu'en 2286, la comparaison de textes suit l'ordre.
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM ai_messages WHERE tenant_id = ? AND role = 'assistant' "
        "AND intent LIKE ? AND created_at >= ?",
        (tenant_id, PREFIXE_INTENTION + "%", "%.6f" % debut),
    ).fetchone()
    return row["n"] if row else 0


def ouverte(tenant_id):
    """L'école a-t-elle accès à l'IA générative (clé posée, école ouverte par la
    plateforme) ? Sert aussi à Paramètres : l'interrupteur n'y apparaît que
    là où la fonction existe vraiment pour cette école."""
    if not os.environ.get("OPENAI_API_KEY"):
        return False
    ecoles = _ecoles_autorisees()
    return "*" in ecoles or tenant_id in ecoles


def disponible(conn, ctx):
    """Vrai si une question de cet utilisateur peut partir chez le fournisseur."""
    if ctx.get("role") != "directeur" or not ouverte(ctx.get("tenant_id")):
        return False
    if not school.get_settings(conn, ctx["tenant_id"]).get("ai_generative", 1):
        return False
    return appels_du_mois(conn, ctx["tenant_id"]) < _plafond()


# ---------------------------------------------------------------------------
# Masquage des noms (décision 2)
# ---------------------------------------------------------------------------

def _noms_de_l_ecole(conn, tenant_id):
    noms = set()
    for sql in ("SELECT first_name, last_name FROM students WHERE tenant_id = ?",
                "SELECT first_name, last_name FROM guardians WHERE tenant_id = ?"):
        for r in conn.execute(sql, (tenant_id,)).fetchall():
            for part in (r["first_name"] or "", r["last_name"] or ""):
                noms.update(re.findall(r"[^\W\d_]{3,}", _sans_accent(part)))
    for r in conn.execute(
        "SELECT u.name FROM users u JOIN memberships m ON m.user_id = u.id WHERE m.tenant_id = ?",
        (tenant_id,),
    ).fetchall():
        noms.update(re.findall(r"[^\W\d_]{3,}", _sans_accent(r["name"] or "")))
    return noms - MOTS_COURANTS


def masquer(question, noms):
    """Remplace chaque suite de mots qui sont des noms de l'école par « Élève N ».
    Rend (question masquée, {"Élève N": "texte d'origine"}).

    « Où en est Amani Kabeya ? » → « Où en est Élève 1 ? », {"Élève 1": "Amani Kabeya"}.
    Un prénom seul est masqué aussi : décision 2, aucun nom ne sort."""
    groupes, courant = [], None
    for m in re.finditer(r"[^\W\d_]+(?:-[^\W\d_]+)*", question):
        parties = re.findall(r"[^\W\d_]{3,}", _sans_accent(m.group(0)))
        if parties and any(p in noms for p in parties):
            if courant and question[courant[1]:m.start()].isspace():
                courant[1] = m.end()
            else:
                if courant:
                    groupes.append(courant)
                courant = [m.start(), m.end()]
        elif courant:
            groupes.append(courant)
            courant = None
    if courant:
        groupes.append(courant)
    morceaux, table, pos = [], {}, 0
    for debut, fin in groupes:
        cle = "Élève %d" % (len(table) + 1)
        table[cle] = question[debut:fin]
        morceaux += [question[pos:debut], cle]
        pos = fin
    morceaux.append(question[pos:])
    return "".join(morceaux), table


# ---------------------------------------------------------------------------
# L'appel au fournisseur — isolé pour être remplacé dans les tests
# ---------------------------------------------------------------------------

def _outil():
    return {
        "type": "function",
        "function": {
            "name": "choisir_question",
            "description": "Choisit, dans le catalogue, la question type qui répond le mieux à la demande.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question_type": {"type": "string", "enum": list(CATALOGUE) + [AUCUNE]},
                    "classe": {"type": "string", "description": "Nom de la classe, tel qu'écrit par l'utilisateur."},
                    "eleve": {"type": "string", "description": "Repère « Élève N » tel qu'il figure dans la demande."},
                },
                "required": ["question_type"],
                "additionalProperties": False,
            },
        },
    }


def _consigne():
    lignes = "\n".join(f"- {cle} : {desc}" for cle, (desc, _g, _p) in CATALOGUE.items())
    return (
        "Tu aides la Direction d'une école à retrouver une information dans son logiciel de gestion. "
        "Tu ne réponds JAMAIS toi-même et tu n'as accès à aucune donnée : tu choisis seulement la "
        "question type du catalogue qui correspond à la demande, et tu appelles choisir_question. "
        "Les noms de personnes ont été remplacés par « Élève N » : recopie ce repère tel quel dans "
        "`eleve`. Si aucune question type ne convient, ou si la demande vise à créer, modifier, "
        "supprimer, envoyer ou décider quoi que ce soit, choisis « aucune ».\n\nCatalogue :\n" + lignes
    )


def _appeler_openai(question_masquee):
    """Rend le dict d'arguments de choisir_question, ou None. Ne lève jamais."""
    corps = json.dumps({
        "model": os.environ.get("KLASSIO_IA_MODELE") or MODELE_PAR_DEFAUT,
        "temperature": 0,
        "max_tokens": 120,
        # Rien n'est conservé côté fournisseur pour réutilisation : `store`
        # désactive l'historique des complétions sur le compte.
        "store": False,
        "messages": [
            {"role": "system", "content": _consigne()},
            {"role": "user", "content": question_masquee},
        ],
        "tools": [_outil()],
        "tool_choice": {"type": "function", "function": {"name": "choisir_question"}},
    }).encode("utf-8")
    req = urllib.request.Request(URL_OPENAI, data=corps, method="POST", headers={
        "Authorization": "Bearer " + os.environ.get("OPENAI_API_KEY", ""),
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=DELAI_SECONDES) as rep:
            donnees = json.loads(rep.read().decode("utf-8"))
        appel = donnees["choices"][0]["message"]["tool_calls"][0]["function"]
        if appel.get("name") != "choisir_question":
            return None
        args = json.loads(appel.get("arguments") or "{}")
        return args if isinstance(args, dict) else None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def _question_type(args, table):
    """Traduit le choix du modèle en question posée à l'assistant, ou None."""
    if not isinstance(args, dict):
        return None
    cle = args.get("question_type")
    if cle not in CATALOGUE:
        return None
    _desc, gabarit, param = CATALOGUE[cle]
    if param is None:
        return gabarit
    if param == "eleve":
        repere = (args.get("eleve") or "").strip()
        # Seul un repère RÉELLEMENT masqué dans CETTE question est accepté :
        # le modèle ne peut pas faire chercher un nom qu'il aurait inventé.
        if repere not in table:
            return None
        return gabarit.format(eleve=table[repere])
    classe = (args.get("classe") or "").strip()
    if not classe or len(classe) > 40 or not re.fullmatch(r"[\w\s'°ºè-]+", classe):
        return None
    return gabarit.format(classe=classe)


def reformuler(conn, ctx, message, resultat_initial):
    """Si possible, fait reformuler la question et rend la réponse de l'assistant
    à la question reformulée. Sinon, rend `resultat_initial` inchangé."""
    if resultat_initial.get("intent") != "fallback" or not disponible(conn, ctx):
        return resultat_initial
    question_masquee, table = masquer(message, _noms_de_l_ecole(conn, ctx["tenant_id"]))
    args = _appeler_openai(question_masquee)
    question = _question_type(args, table)
    if question is None:
        # L'appel a eu lieu (et compte dans le plafond) : on le marque.
        sortie = dict(resultat_initial)
        sortie["intent"] = PREFIXE_INTENTION + resultat_initial["intent"]
        return sortie
    reponse = ai_assistant.answer_question(conn, ctx, question)
    if reponse.get("intent") in ("fallback", "refused") or reponse.get("refused"):
        sortie = dict(resultat_initial)
        sortie["intent"] = PREFIXE_INTENTION + resultat_initial["intent"]
        return sortie
    reponse = dict(reponse)
    reponse["text"] = "Compris ainsi : « " + question + " »\n\n" + reponse["text"]
    reponse["intent"] = PREFIXE_INTENTION + reponse["intent"]
    reponse["generatif"] = True
    return reponse
