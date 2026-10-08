"""KLASSIO — faits en lot (08/10/2026).

Le propriétaire : « si plusieurs élèves ont un retard ou ont fait quelque
chose de mal, on saisit leurs faits sur un document Word, papier… on le met
dans le logiciel, il analyse les noms et ce qu'ils ont mal fait, et le DD
décide en une fois de leur tâche, de leur punition ».

Ce module LIT un texte (une ligne par fait, ou plusieurs élèves par ligne) et
PROPOSE : pour chaque élève reconnu, la règle de l'école qui ressemble le
plus au fait. Il ne décide rien : le DD relit, corrige, puis confirme. Les
élèves cherchés sont ceux du PÉRIMÈTRE de l'acteur (school.students_where_
clause) — un nom d'une autre école ou d'un autre cycle n'est jamais reconnu.
"""
import re
import unicodedata

MOTS_VIDES = {"de", "du", "des", "la", "le", "les", "un", "une", "et", "en", "au", "aux", "a", "pour", "par", "dans",
              "sur", "avec", "son", "sa", "ses", "il", "elle", "ils", "elles", "qui", "que", "est", "sont", "ont", "fait",
              "classe", "eleve", "eleves", "pendant", "cours", "ce", "cette", "matin", "jour", "aujourd", "hui"}
SYNONYMES = {
    "retard": {"retard", "retards", "tard", "arrive", "arrivee"},
    "derangement": {"derange", "derangement", "bavard", "bavardage", "bruit", "chahut", "perturbe", "dissipe"},
    "telephone": {"telephone", "portable", "smartphone", "phone"},
    "bagarre": {"bagarre", "bataille", "battu", "frappe", "coup", "coups", "violence"},
    "absence": {"absent", "absente", "absence", "absents"},
    "tenue": {"tenue", "uniforme", "chaussettes", "ketch", "cravate"},
    "insolence": {"insolent", "insolence", "injure", "insulte", "impoli", "irrespect"},
    "tricherie": {"triche", "tricherie", "copie", "copier", "fraude"},
    "devoir": {"devoir", "devoirs", "cahier", "cahiers", "document", "documents", "journal"},
}


def normaliser(texte):
    t = unicodedata.normalize("NFD", (texte or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _mots(texte):
    return [m for m in normaliser(texte).split() if len(m) >= 3 and m not in MOTS_VIDES]


def _racine(m):
    # « bavardé », « bavardent », « bavardage » → « bavar » : les conjugaisons
    # et les dérivés se retrouvent sans dictionnaire.
    return m[:5] if len(m) >= 5 else m


def _familles(mots):
    racines = {_racine(m) for m in mots}
    return {f for f, syn in SYNONYMES.items() if racines & {_racine(x) for x in syn}}


def eleves_de_la_ligne(ligne, eleves):
    """Élèves dont le prénom ET le nom figurent dans la ligne (dans n'importe
    quel ordre). Un homonyme parfait dans le périmètre donne deux candidats :
    le DD tranche."""
    mots = set(normaliser(ligne).split())
    trouves = []
    for e in eleves:
        prenom, nom = normaliser(e["first_name"]).split(), normaliser(e["last_name"]).split()
        if prenom and nom and set(prenom) <= mots and set(nom) <= mots:
            trouves.append(e)
    return trouves


def regle_la_plus_proche(ligne, regles, noms_a_ignorer):
    mots = [m for m in _mots(ligne) if m not in noms_a_ignorer]
    if not mots:
        return None
    fam_ligne = _familles(mots)
    meilleur, score_max = None, 0
    for r in regles:
        mots_r = _mots(r["label"])
        score = 2 * len({_racine(m) for m in mots} & {_racine(m) for m in mots_r}) + 3 * len(fam_ligne & _familles(mots_r))
        if score > score_max:
            meilleur, score_max = r, score
    return meilleur


def analyser(texte, eleves, regles):
    lignes = [" ".join(l.split()) for l in re.split(r"[\n ;]+", texte or "") if l.strip()]
    propositions, inconnues = [], []
    for ligne in lignes[:300]:
        if len(ligne) < 3:
            continue
        trouves = eleves_de_la_ligne(ligne, eleves)
        if not trouves:
            inconnues.append(ligne[:200])
            continue
        noms = set()
        for e in trouves:
            noms |= set(normaliser(e["first_name"] + " " + e["last_name"]).split())
        regle = regle_la_plus_proche(ligne, regles, noms)
        for e in trouves:
            propositions.append({
                "line": ligne[:200], "student_id": e["id"],
                "student": f"{e['first_name']} {e['last_name']}", "class_name": e.get("class_name"),
                "rule_id": regle["id"] if regle else None, "rule_label": regle["label"] if regle else None,
                "ambiguous": len([x for x in trouves if normaliser(x["first_name"] + x["last_name"]) == normaliser(e["first_name"] + e["last_name"])]) > 1,
            })
    return {"items": propositions, "unmatched": inconnues[:50], "lines": len(lignes)}
