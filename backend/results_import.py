"""KLASSIO — import des RÉSULTATS OFFICIELS.

Klassio ne calcule pas les notes : l'établissement les calcule avec ses propres
outils, puis remet à Klassio un fichier de résultats officiels. Ce module lit ce
fichier, rapproche chaque ligne d'un élève réel, et signale tout ce qui ne se
rapproche pas proprement. Il n'écrit rien : la confirmation est une étape
séparée, dans `api_academics`.

Trois principes gouvernent ce fichier.

**Le nom n'est pas un identifiant.** Deux « Mukendi Audrey » existent dans
beaucoup d'écoles. Le rapprochement se fait d'abord sur le code élève
(STU-XXXX-XXXX), stable et généré par Klassio. Le nom ne sert qu'à défaut, et
une correspondance par nom seul est signalée comme À VÉRIFIER — jamais comme
sûre.

**Une anomalie bloquante empêche la validation.** Un élève introuvable, une note
hors barème, une ligne en double : rien de tout cela ne se devine. Le fichier
revient à la Direction, qui corrige.

**Un élève absent du fichier n'a pas zéro.** Il n'a pas de résultat, ce qui est
une information différente, et elle est remontée telle quelle.
"""
import re

import ingestion

# Colonnes reconnues dans un fichier de résultats. Les motifs sont volontairement
# larges : un fichier réel s'appelle « Cote », « Points », « Moyenne » ou
# « Résultat » selon l'école, et personne ne va renommer ses colonnes pour
# Klassio.
COLONNES_RESULTATS = {
    "student_code": {
        "patterns": [r"\bid\b", r"identifiant", r"code", r"matricule", r"student_?id", r"n°\s*élève"],
        "label": "Identifiant de l'élève", "confidence": 0.99,
    },
    "student_name": {
        "patterns": [r"nom", r"prenom", r"prénom", r"eleve", r"élève", r"etudiant", r"étudiant", r"student"],
        "label": "Nom de l'élève", "confidence": 0.90,
    },
    "class_name": {
        "patterns": [r"classe", r"section", r"promotion", r"\bclass\b"],
        "label": "Classe", "confidence": 0.92,
    },
    "subject": {
        "patterns": [r"matiere", r"matière", r"cours", r"discipline", r"branche", r"subject"],
        "label": "Matière", "confidence": 0.95,
    },
    "period": {
        "patterns": [r"periode", r"période", r"trimestre", r"semestre", r"bimestre", r"cycle", r"period"],
        "label": "Période", "confidence": 0.93,
    },
    "score": {
        "patterns": [r"resultat", r"résultat", r"note", r"cote", r"moyenne", r"points?", r"score", r"total"],
        "label": "Résultat", "confidence": 0.94,
    },
    "max_score": {
        "patterns": [r"bareme", r"barème", r"sur\b", r"max", r"maximum", r"/\s*\d+"],
        "label": "Barème (note maximale)", "confidence": 0.90,
    },
}

# Ordre de détection. Deux collisions réelles le dictent :
#
# - « ID Élève » contient « élève » : le code doit être cherché avant le nom.
# - « Cote /20 » contient « /20 » : la colonne de NOTE doit être cherchée avant
#   celle de barème, sinon le barème s'empare de la colonne de note et le
#   fichier devient illisible. Le barème inscrit dans le titre est récupéré
#   séparément par _bareme_depuis_entete().
PRIORITE = ("student_code", "score", "max_score", "subject", "period", "class_name", "student_name")

SEVERITE_OK = "matched"
SEVERITE_ALERTE = "warning"
SEVERITE_ERREUR = "error"


def detecter_colonnes(headers):
    """Associe chaque en-tête du fichier à un champ connu.

    Un en-tête non reconnu n'est pas une erreur : les fichiers d'école portent
    souvent des colonnes de travail (rang, appréciation, signature) qui ne
    concernent pas Klassio. Elles sont simplement ignorées, et rapportées pour
    que la Direction voie ce qui n'a pas été lu.
    """
    mapping, pris = {}, {}
    for champ in PRIORITE:
        config = COLONNES_RESULTATS[champ]
        for idx, header in enumerate(headers):
            if idx in mapping:
                continue
            propre = str(header or "").strip().lower()
            if not propre:
                continue
            if any(re.search(p, propre) for p in config["patterns"]):
                mapping[idx] = {"header": str(header).strip(), "field": champ,
                                "label": config["label"], "confidence": config["confidence"]}
                pris[champ] = idx
                break
    ignorees = [{"header": str(h).strip(), "field": "unmapped", "label": "Colonne ignorée",
                 "confidence": 0.0}
                for i, h in enumerate(headers) if i not in mapping and str(h or "").strip()]
    return pris, mapping, ignorees


def _nombre(valeur):
    """Lit un nombre écrit à la française comme à l'anglaise : « 14,5 » et
    « 14.5 » désignent la même note. Renvoie None si ce n'est pas un nombre."""
    if valeur is None:
        return None
    if isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
        return float(valeur)
    texte = str(valeur).strip().replace(" ", "").replace(",", ".")
    if not texte:
        return None
    texte = re.sub(r"/\s*\d+(?:\.\d+)?$", "", texte)   # « 14/20 » → « 14 »
    try:
        return float(texte)
    except ValueError:
        return None


def _bareme_depuis_entete(header):
    """« Note /20 », « Résultat sur 100 » : le barème est souvent dans le titre
    de la colonne plutôt que dans une colonne à lui."""
    m = re.search(r"(?:/|sur)\s*(\d{1,4})", str(header or ""), re.I)
    return float(m.group(1)) if m else None


def _texte(valeur):
    return str(valeur).strip() if valeur is not None and str(valeur).strip() else None


def analyser_fichier(data_rows, filename="resultats.xlsx", bareme_defaut=20.0):
    """Lit le tableau et produit des lignes normalisées + les colonnes détectées.

    Ne touche pas à la base : cette étape ne sait encore rien des élèves réels.
    """
    if not data_rows:
        raise ValueError("Fichier vide : aucune ligne à lire.")
    headers = [str(h).strip() if h is not None else "" for h in data_rows[0]]
    if not any(headers):
        raise ValueError("La première ligne du fichier doit contenir les noms de colonnes.")
    pris, mapping, ignorees = detecter_colonnes(headers)

    manquantes = [c for c in ("score",) if c not in pris]
    if manquantes:
        raise ValueError(
            "Aucune colonne de résultat n'a été reconnue. Le fichier doit comporter une colonne "
            "« Résultat », « Note », « Cote » ou « Moyenne ».")
    if "student_code" not in pris and "student_name" not in pris:
        raise ValueError(
            "Aucune colonne permettant d'identifier l'élève n'a été reconnue. Ajoutez une colonne "
            "« Identifiant » (recommandé) ou « Nom ».")

    bareme_entete = _bareme_depuis_entete(headers[pris["score"]])
    lignes = []
    for numero, brute in enumerate(data_rows[1:], start=2):
        if not any(c is not None and str(c).strip() for c in brute):
            continue   # ligne vide : ni erreur ni donnée
        lire = lambda champ: (brute[pris[champ]] if champ in pris and pris[champ] < len(brute) else None)
        bareme = _nombre(lire("max_score")) or bareme_entete or bareme_defaut
        lignes.append({
            "row": numero,
            "student_code": _texte(lire("student_code")),
            "student_name": _texte(lire("student_name")),
            "class_name": ingestion.normalize_class_name(lire("class_name")) if lire("class_name") else None,
            "subject": _texte(lire("subject")),
            "period": _texte(lire("period")),
            "score": _nombre(lire("score")),
            "max_score": bareme,
            "raw_score": _texte(lire("score")),
        })
    if not lignes:
        raise ValueError("Aucune ligne de résultat exploitable dans ce fichier.")
    return {"headers": headers, "mapping": list(mapping.values()) + ignorees,
            "fields": list(pris.keys()), "rows": lignes, "file_name": filename}


# ---------------------------------------------------------------------------
# Rapprochement avec les élèves réels de l'établissement
# ---------------------------------------------------------------------------

def _cle_nom(prenom, nom):
    brut = f"{nom or ''} {prenom or ''}".lower()
    brut = brut.translate(str.maketrans("àâäáãåçéèêëíìîïñóòôöõúùûüýÿ", "aaaaaaceeeeiiiinooooouuuuyy"))
    return " ".join(sorted(re.sub(r"[^a-z\s]", " ", brut).split()))


def rapprocher(conn, tenant_id, academic_year_id, lignes, periode):
    """Rapproche chaque ligne du fichier d'un élève RÉEL de l'établissement.

    L'ordre est délibéré :

    1. le code élève, qui est la seule référence fiable ;
    2. à défaut, le nom — et le résultat est alors marqué À VÉRIFIER, jamais
       validé d'office. Si deux élèves portent le même nom, c'est une ERREUR :
       Klassio ne choisit pas à la place de la Direction.

    Le périmètre de recherche est borné à (tenant, année) : un code élève d'un
    autre établissement ne peut pas correspondre, même s'il existe ailleurs.
    """
    eleves = [dict(r) for r in conn.execute(
        """SELECT s.id, s.code, s.first_name, s.last_name, s.status, s.class_id,
                  c.name AS class_name, c.cycle AS class_cycle
           FROM students s
           LEFT JOIN classes c ON c.id = s.class_id AND c.tenant_id = s.tenant_id
           WHERE s.tenant_id = ? AND s.academic_year_id = ?""",
        (tenant_id, academic_year_id))]

    par_code = {e["code"]: e for e in eleves if e["code"]}
    par_nom = {}
    for e in eleves:
        par_nom.setdefault(_cle_nom(e["first_name"], e["last_name"]), []).append(e)

    vus = {}          # (student_id, subject) -> première ligne, pour les doublons
    resultats = []
    for l in lignes:
        ligne = dict(l)
        ligne["severity"] = SEVERITE_OK
        ligne["issues"] = []
        ligne["student_id"] = None
        ligne["match_by"] = None
        ligne["matched_name"] = None

        eleve = None
        if ligne["student_code"]:
            eleve = par_code.get(ligne["student_code"].strip().upper())
            if eleve:
                ligne["match_by"] = "code"
            else:
                ligne["severity"] = SEVERITE_ERREUR
                ligne["issues"].append(f"identifiant « {ligne['student_code']} » introuvable dans cet établissement")
        if eleve is None and not ligne["student_code"] and ligne["student_name"]:
            # Pas de code du tout : on tente le nom, en le signalant.
            parts = ligne["student_name"].split()
            candidats = par_nom.get(_cle_nom(" ".join(parts[1:]), parts[0] if parts else ""), [])
            if not candidats:
                candidats = par_nom.get(_cle_nom("", ligne["student_name"]), [])
            if len(candidats) == 1:
                eleve = candidats[0]
                ligne["match_by"] = "name"
                ligne["severity"] = SEVERITE_ALERTE
                ligne["issues"].append("rapproché par le NOM seul — à vérifier avant validation")
            elif len(candidats) > 1:
                ligne["severity"] = SEVERITE_ERREUR
                ligne["issues"].append(f"{len(candidats)} élèves portent ce nom — un identifiant est nécessaire")
            else:
                ligne["severity"] = SEVERITE_ERREUR
                ligne["issues"].append("aucun élève de cet établissement ne porte ce nom")

        if eleve:
            ligne["student_id"] = eleve["id"]
            ligne["matched_name"] = f"{eleve['first_name']} {eleve['last_name']}"
            ligne["student_code"] = ligne["student_code"] or eleve["code"]
            ligne["matched_class"] = eleve["class_name"]
            if eleve["status"] != "active":
                ligne["severity"] = SEVERITE_ALERTE
                ligne["issues"].append(f"élève au statut « {eleve['status']} » — inscrit mais plus actif")
            if ligne["class_name"] and eleve["class_name"] and \
                    ligne["class_name"].lower() != eleve["class_name"].lower():
                ligne["severity"] = SEVERITE_ALERTE
                ligne["issues"].append(
                    f"classe du fichier « {ligne['class_name'] } » ≠ classe enregistrée « {eleve['class_name']} »")

        # Matière et note : indispensables, et vérifiées même si l'élève est
        # introuvable — la Direction doit voir TOUS les problèmes d'un coup,
        # pas les découvrir un par un à chaque nouvel import.
        if not ligne["subject"]:
            ligne["severity"] = SEVERITE_ERREUR
            ligne["issues"].append("matière absente")
        if ligne["score"] is None:
            ligne["severity"] = SEVERITE_ERREUR
            ligne["issues"].append(
                f"résultat illisible « {ligne['raw_score'] or ''} »" if ligne["raw_score"] else "résultat absent")
        else:
            if not (0 < ligne["max_score"] <= 1000):
                ligne["severity"] = SEVERITE_ERREUR
                ligne["issues"].append(f"barème invalide ({ligne['max_score']})")
            elif ligne["score"] < 0 or ligne["score"] > ligne["max_score"]:
                ligne["severity"] = SEVERITE_ERREUR
                ligne["issues"].append(
                    f"résultat {ligne['score']:g} hors barème (0 à {ligne['max_score']:g})")

        # La période du fichier, si elle est renseignée, doit être celle de
        # l'import : importer des résultats de Période 2 dans la Période 1
        # serait une erreur silencieuse et irrattrapable.
        if ligne["period"] and periode and ligne["period"].strip().lower() != periode["label"].strip().lower():
            ligne["severity"] = SEVERITE_ERREUR
            ligne["issues"].append(
                f"période « {ligne['period']} » ≠ période de l'import « {periode['label']} »")

        if ligne["student_id"] and ligne["subject"]:
            cle = (ligne["student_id"], ligne["subject"].strip().lower())
            if cle in vus:
                ligne["severity"] = SEVERITE_ERREUR
                ligne["issues"].append(
                    f"doublon dans le fichier — même élève et même matière qu'à la ligne {vus[cle]}")
            else:
                vus[cle] = ligne["row"]

        resultats.append(ligne)

    couverts = {l["student_id"] for l in resultats if l["student_id"]}
    absents = [{"id": e["id"], "code": e["code"], "name": f"{e['first_name']} {e['last_name']}",
                "class_name": e["class_name"]}
               for e in eleves if e["status"] == "active" and e["id"] not in couverts]

    return {
        "rows": resultats,
        "matched": sum(1 for l in resultats if l["severity"] == SEVERITE_OK),
        "warnings": sum(1 for l in resultats if l["severity"] == SEVERITE_ALERTE),
        "errors": sum(1 for l in resultats if l["severity"] == SEVERITE_ERREUR),
        "total_rows": len(resultats),
        "students_in_file": len(couverts),
        "students_expected": sum(1 for e in eleves if e["status"] == "active"),
        # Volontairement explicite : ces élèves n'ont PAS zéro, ils n'ont pas de
        # résultat dans ce fichier. Les confondre fabriquerait des notes.
        "students_without_result": absents,
    }
