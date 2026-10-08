"""KLASSIO backend — School Data Ingestion & Bootstrap Engine.

Transforme des données brutes (Excel/CSV/tableaux) en un établissement
scolaire complètement structuré dans le SaaS.
Garantit l'intégrité du Financial Core, l'auditabilité et la validation humaine.
"""
import csv
import io
import re
import time
from security import new_id, audit
import financial
import events as events_module
from validation import positive_amount, ValidationError

# Règles de détection heuristique et IA de colonnes
COLUMN_PATTERNS = {
    "student_name": {
        "patterns": [r"nom", r"prenom", r"eleve", r"étudiant", r"apprenant", r"student"],
        "confidence": 0.98,
        "label": "Identité Élève (Nom / Prénom)"
    },
    "student_first_name": {
        "patterns": [r"prenom", r"prénom", r"first_name"],
        "confidence": 0.96,
        "label": "Prénom de l'Élève"
    },
    "student_last_name": {
        "patterns": [r"^nom$", r"nom_famille", r"postnom", r"last_name"],
        "confidence": 0.96,
        "label": "Nom de Famille / Postnom"
    },
    "class_name": {
        "patterns": [r"classe", r"section", r"niveau", r"grade", r"promotion"],
        "confidence": 0.95,
        "label": "Classe / Section"
    },
    "guardian_phone": {
        "patterns": [r"tel", r"tél", r"telephone", r"téléphone", r"contact", r"phone", r"mobile"],
        "confidence": 0.92,
        "label": "Téléphone Parent / Responsable"
    },
    "guardian_name": {
        "patterns": [r"parent", r"tuteur", r"responsable", r"pere", r"mere", r"guardian"],
        "confidence": 0.88,
        "label": "Nom du Responsable Légal"
    },
    "fee_total": {
        "patterns": [r"total", r"frais", r"minerval", r"montant", r"scolarite", r"scolarité", r"du", r"dû"],
        "confidence": 0.91,
        "label": "Montant Total des Frais"
    },
    "payment_amount": {
        "patterns": [r"paye", r"payé", r"versement", r"acompte", r"tranche", r"deja_paye", r"regle", r"réglé"],
        "confidence": 0.89,
        "label": "Montant Déjà Encaissé"
    }
}


def select_best_sheet(workbook):
    """Choisit la feuille la plus probable pour contenir des données élèves.

    Bug réel trouvé : un classeur multi-feuilles (ex. une feuille "Lisez-moi"
    explicative + une feuille de données "Élèves") faisait échouer l'analyse
    silencieusement — openpyxl marque une feuille "active" selon l'état
    d'enregistrement du fichier, pas selon ce qu'elle contient. Si le fichier a
    été sauvegardé alors que "Lisez-moi" était affichée, `workbook.active`
    renvoie cette feuille de texte au lieu de la feuille de données, l'analyse
    ne trouve aucune colonne connue, et 0 élève est détecté. On score donc
    chaque feuille sur ses en-têtes plutôt que de faire confiance à ce flag.
    """
    best_ws, best_score, best_rows = None, -1, -1
    for ws in workbook.worksheets:
        first_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
        if not first_row:
            continue
        headers = [str(h).strip().lower() for h in first_row if h]
        score = 0
        for h in headers:
            for cfg in COLUMN_PATTERNS.values():
                if any(re.search(pat, h) for pat in cfg["patterns"]):
                    score += 1
                    break
        row_count = ws.max_row or 0
        if score > best_score or (score == best_score and row_count > best_rows):
            best_ws, best_score, best_rows = ws, score, row_count
    return best_ws or workbook.active


def normalize_class_name(val):
    """Normalise les variantes de classes (ex. '6ème A', '6 A', '6eme-a' -> '6e A')."""
    if not val:
        return "Non affecté"
    val = str(val).strip()
    val = re.sub(r"(?i)(\d+)\s*(?:ème|eme|er|ère)\s*", r"\1e ", val)
    # Coquille fréquente dans les fichiers saisis à la main : un « ème »
    # collé à un mot (« Primairème », « Maternellème », « Secondairème »)
    # — sans cette correction, ces variantes créaient des classes fantômes.
    val = re.sub(r"(?i)(?<=[a-zàâäéèêëïîôöùûüç])ème\b", "e", val)
    val = re.sub(r"[-_]", " ", val)
    val = re.sub(r"\s+", " ", val).strip()
    # Casse homogène : « 6e primaire b », « 6E PRIMAIRE B » et « 6e Primaire B »
    # désignent la même classe — sans cette étape l'import créait des
    # doublons de classes (64 détectées pour 42 réelles sur le fichier de
    # simulation). Les ordinaux (6e, 1re) restent en minuscules.
    words = []
    for w in val.split(" "):
        if re.match(r"^\d+(?:e|re)$", w, re.I):
            words.append(w.lower())
        elif len(w) <= 1:
            words.append(w.upper())
        else:
            words.append(w[0].upper() + w[1:].lower())
    return " ".join(words)


def normalize_phone(val):
    """Nettoie et valide un numéro de téléphone."""
    if not val:
        return None
    val = str(val).strip()
    cleaned = re.sub(r"[^\d+]", "", val)
    return cleaned if len(cleaned) >= 8 else None


def parse_uploaded_table(file_storage):
    """Lit un fichier .xlsx ou .csv envoyé et le transforme en liste de lignes
    brutes (la première étant les en-têtes). Ne fait AUCUNE hypothèse sur le
    contenu — c'est ingestion.analyze_raw_data qui interprète les colonnes.
    """
    filename = (file_storage.filename or "").lower()
    raw = file_storage.read()
    if filename.endswith(".csv"):
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        return list(csv.reader(io.StringIO(text)))
    if filename.endswith(".xlsx"):
        import openpyxl
        try:
            wb = openpyxl.load_workbook(filename=io.BytesIO(raw), data_only=True, read_only=True)
        except Exception:
            # Un .xlsx n'est qu'une archive ZIP. openpyxl lève BadZipFile — ou
            # une poignée d'autres exceptions selon la façon dont le fichier est
            # abîmé — et aucune n'est une ValidationError : la route répondait
            # donc « Erreur interne du serveur » (500).
            #
            # Les deux cas sont ordinaires, pas exotiques : un CSV renommé en
            # .xlsx (réflexe courant), et un téléchargement interrompu. La
            # personne doit savoir que c'est SON fichier qui pose problème,
            # pas Klassio — sinon elle réessaie, ou appelle au secours.
            raise ValidationError(
                "Ce fichier n'est pas un classeur Excel valide. S'il s'agit d'un CSV, "
                "renommez-le en .csv ; sinon, ré-enregistrez-le depuis Excel ou "
                "téléchargez-le à nouveau.")
        # Bug réel trouvé : `wb.active` reflète la feuille affichée au moment de
        # l'enregistrement du fichier, pas celle qui contient les données — un
        # classeur avec une feuille "Lisez-moi" devant la feuille de données
        # faisait analyser du texte libre et détecter 0 élève. On sélectionne
        # la feuille dont les en-têtes correspondent le mieux à des colonnes
        # élève/classe/frais connues (voir ingestion.select_best_sheet).
        ws = select_best_sheet(wb)
        return [list(row) for row in ws.iter_rows(values_only=True)]
    raise ValidationError("Format non pris en charge — envoyez un fichier .xlsx ou .csv")


def analyze_raw_data(data_rows, filename="import.xlsx"):
    """Une seule feuille déjà lue : même moteur que le classeur entier
    (analyze_workbook, plus bas). Deux moteurs auraient divergé au premier
    correctif — c'est arrivé avec la colonne Prénom."""
    if not data_rows:
        return {"error": "Fichier vide ou données non reconnues."}
    return analyze_workbook([("Fichier", data_rows)], filename)


def _valider_tous_les_enregistrements(records):
    """Valide la TOTALITÉ du fichier avant d'écrire la moindre ligne.

    Trouvé à l'audit, et reproduit : la validation se faisait au fil de la
    boucle d'écriture. Un fichier de 2 340 élèves dont la ligne 1 500 portait
    un montant négatif écrivait les 1 499 premières — élèves, responsables,
    obligations, paiements et reçus compris — puis renvoyait une erreur 400.
    L'école voyait « échec », corrigeait son fichier, relançait, et obtenait
    des doublons de tout ce qui était déjà passé.

    L'atomicité complète n'est pas atteignable ici sans réécrire le Financial
    Core : `financial.create_payment()` et `confirm_payment()` valident chacun
    leur écriture par un `commit()`, par construction — un paiement confirmé
    ne doit pas dépendre de la transaction de son appelant. Ce que fait cette
    passe, c'est supprimer la cause réelle : une donnée du fichier qui casse
    au milieu. Après elle, seule une panne de base peut encore interrompre
    l'import en cours de route.

    Les règles reprises ici sont exactement celles de la boucle d'écriture —
    si l'une change là-bas, elle doit changer ici.
    """
    for position, r in enumerate(records, start=1):
        premier = (r.get("first_name") or "").strip()
        nom = (r.get("last_name") or "").strip()
        if not premier and not nom:
            raise ValidationError(f"Ligne {position} : ni nom ni prénom — relancez l'analyse.")
        identite = f"{premier} {nom}".strip()
        if r.get("fee_amount") not in (None, ""):
            try:
                positive_amount(float(r.get("fee_amount")), "fee_amount")
            except (TypeError, ValueError) as e:
                raise ValidationError(f"Ligne {position} — montant invalide pour {identite} : {e}")
        try:
            paye = float(r.get("paid_amount") or 0.0)
        except (TypeError, ValueError) as e:
            raise ValidationError(f"Ligne {position} — montant payé invalide pour {identite} : {e}")
        if paye < 0:
            raise ValidationError(f"Ligne {position} — montant payé négatif pour {identite}.")
        if paye > 0 and r.get("fee_amount") in (None, ""):
            # Un versement sans dette à laquelle le rattacher : la boucle
            # d'écriture l'ignorait silencieusement (`continue` avant le
            # paiement). Le dire plutôt que de perdre l'information.
            raise ValidationError(
                f"Ligne {position} — {identite} : un montant payé est indiqué sans montant dû. "
                "Renseignez les frais, ou retirez le paiement.")


def bootstrap_school(conn, tenant_id, user_id, bootstrap_payload):
    """Effectue l'ingestion atomique complète et construit l'environnement scolaire :
    1. Année scolaire
    2. Classes
    3. Catalogue financier
    4. Élèves
    5. Responsables
    6. Obligations financières
    7. Enregistrement des règlements historiques certifiés via Financial Core
    """
    school_name = bootstrap_payload.get("school_name", "Nouvel Établissement")
    academic_year_label = bootstrap_payload.get("academic_year", "Année Académique 2026-2027")
    records = bootstrap_payload.get("records", [])

    if not records:
        raise ValueError("Aucun enregistrement valide à intégrer.")

    _valider_tous_les_enregistrements(records)

    now = str(time.time())

    # 1. Année scolaire
    existing_year = conn.execute("SELECT id FROM academic_years WHERE tenant_id = ? LIMIT 1", (tenant_id,)).fetchone()
    if existing_year:
        year_id = existing_year["id"]
    else:
        year_id = new_id()
        conn.execute("INSERT INTO academic_years (id, tenant_id, label, is_active, created_at) VALUES (?,?,?,1,?)",
                     (year_id, tenant_id, academic_year_label, now))

    import school  # import tardif : évite un cycle db → school → ingestion
    settings = school.get_settings(conn, tenant_id)
    currency = settings["currency"]

    # 2. Classes uniques
    class_ids_by_name = {}
    classes_needed = set(r.get("class_name") or "Non affecté" for r in records)
    for cname in classes_needed:
        row = conn.execute("SELECT id FROM classes WHERE tenant_id = ? AND name = ?", (tenant_id, cname)).fetchone()
        if row:
            class_ids_by_name[cname] = row["id"]
        else:
            cid = new_id()
            level = cname.split()[0] if " " in cname else None
            conn.execute("INSERT INTO classes (id, tenant_id, academic_year_id, name, level, cycle, created_at) VALUES (?,?,?,?,?,?,?)",
                         (cid, tenant_id, year_id, cname, level, school.infer_cycle(level, cname), now))
            class_ids_by_name[cname] = cid

    # 3. Article de catalogue standard pour les frais importés (créé seulement
    # si au moins une ligne porte un montant réel)
    cat_item_id = None
    if any(r.get("fee_amount") not in (None, "") for r in records):
        cat_item_id = new_id()
        conn.execute("INSERT INTO catalog_items (id, tenant_id, name, category, amount, currency, created_at) VALUES (?,?,?,?,?,?,?)",
                     (cat_item_id, tenant_id, "Frais de scolarité (import)", "Scolarité", 0.0, currency, now))

    created_students = 0
    created_obligations = 0
    created_payments = 0
    created_guardians = 0

    for r in records:
        first = (r.get("first_name") or "").strip()
        last = (r.get("last_name") or "").strip()
        if not first and not last:
            raise ValidationError("Une ligne ne comporte ni nom ni prénom — relancez l'analyse.")
        cname = r.get("class_name") or "Non affecté"
        cid = class_ids_by_name.get(cname)
        phone = r.get("guardian_phone")
        parent_name = (r.get("guardian_name") or "").strip() or None
        # Audit de sécurité : ce chemin (confirm-import) écrivait fee_amount
        # directement en SQL sans passer par positive_amount() — contrairement
        # à POST /api/obligations qui l'applique déjà. Un montant négatif/NaN
        # envoyé ici fabriquait une dette négative affichée comme "payée" et
        # faussait tous les agrégats financiers du tenant.
        fee_amount = None
        if r.get("fee_amount") not in (None, ""):
            try:
                fee_amount = positive_amount(float(r.get("fee_amount")), "fee_amount")
            except (TypeError, ValueError) as e:
                raise ValidationError(f"Montant invalide pour {first} {last} : {e}")
        try:
            paid_amount = float(r.get("paid_amount") or 0.0)
        except (TypeError, ValueError) as e:
            raise ValidationError(f"Montant payé invalide pour {first} {last} : {e}")
        if paid_amount < 0:
            raise ValidationError(f"Montant payé négatif pour {first} {last}.")

        # Créer élève — avec son identifiant unique Klassio
        sid = new_id()
        conn.execute(
            "INSERT INTO students (id, tenant_id, academic_year_id, class_id, first_name, last_name, code, status, created_at) VALUES (?,?,?,?,?,?,?, 'active', ?)",
            (sid, tenant_id, year_id, cid, first or "—", last or "—", school.generate_student_code(conn, tenant_id), now)
        )
        created_students += 1

        # Créer responsable UNIQUEMENT si le fichier en fournit un (nom ou téléphone)
        if phone or parent_name:
            gid = new_id()
            parts = (parent_name or "").split(" ", 1)
            g_first, g_last = (parts[0], parts[1]) if len(parts) > 1 else (parent_name or "", "")
            conn.execute(
                "INSERT INTO guardians (id, tenant_id, first_name, last_name, phone, created_at) VALUES (?,?,?,?,?,?)",
                (gid, tenant_id, g_first, g_last, phone, now)
            )
            conn.execute(
                "INSERT INTO student_guardians (id, tenant_id, student_id, guardian_id, relationship) VALUES (?,?,?,?, 'Parent')",
                (new_id(), tenant_id, sid, gid)
            )
            created_guardians += 1

        if fee_amount is None:
            continue  # aucune obligation inventée

        # Créer obligation financière
        ob_id = new_id()
        conn.execute(
            "INSERT INTO obligations (id, tenant_id, student_id, academic_year_id, catalog_item_id, amount, currency, due_date, status, created_at) VALUES (?,?,?,?,?,?,?,?, 'ISSUED', ?)",
            (ob_id, tenant_id, sid, year_id, cat_item_id, fee_amount, currency, None, now)
        )
        created_obligations += 1

        # Enregistrer paiement certifié si déjà versé
        if paid_amount > 0:
            # Reprise d'historique : l'école déclare ce qu'elle a déjà encaissé.
            # `allow_overpayment` laisse passer un « payé > dû » — l'analyse l'a
            # signalé à la Direction avant confirmation, et la refuser ici ferait
            # échouer toute la migration pour une ligne du fichier.
            payment, _ = financial.create_payment(
                conn, tenant_id, ob_id, paid_amount, "cash", f"bootstrap-{ob_id}-{int(time.time())}", user_id,
                allow_overpayment=True,
            )
            # Le passe-droit vaut aussi à la CONFIRMATION : depuis le 18/09,
            # c'est là que le dépassement est refusé (course entre guichets).
            # Sans le repasser ici, la migration d'une école dont l'historique
            # porte un trop-perçu échouerait à la dernière étape.
            financial.confirm_payment(conn, tenant_id, payment["id"], "HISTORICAL_IMPORT", user_id,
                                      allow_overpayment=True)
            created_payments += 1

    conn.commit()

    audit(tenant_id, user_id, "school.bootstrapped", "tenant", tenant_id, "success",
          after={
              "students": created_students,
              "classes": len(class_ids_by_name),
              "guardians": created_guardians,
              "obligations": created_obligations,
              "payments": created_payments
          })

    return {
        "status": "success",
        "message": f"Établissement configuré : {created_students} élèves, {len(class_ids_by_name)} classes, "
                   f"{created_guardians} responsables et {created_payments} règlements intégrés.",
        "students_count": created_students,
        "classes_count": len(class_ids_by_name),
        "guardians_count": created_guardians,
        "obligations_count": created_obligations,
        "payments_count": created_payments
    }


# ===========================================================================
# LECTURE D'UN CLASSEUR RÉEL — 08/10/2026
#
# Le propriétaire a déposé le classeur d'une école : plusieurs feuilles
# (classes, élèves, paiements…), un titre au-dessus de chaque tableau. Klassio
# a répondu « Aucune ligne exploitable ». Sa phrase : « c'est comme si on
# demandait aux écoles de s'adapter à notre logiciel — inacceptable ».
#
# Reproduit sur deux classeurs fictifs typiques (0 élève détecté sur chacun).
# Trois causes, toutes dans l'hypothèse d'un fichier « propre » :
#   1. les titres de colonnes étaient attendus en LIGNE 1 — or une école écrit
#      d'abord son nom, l'année, « LISTE DES ÉLÈVES », puis le tableau ;
#   2. UNE SEULE feuille était lue — or beaucoup d'écoles tiennent une feuille
#      par classe, ou séparent élèves et paiements ;
#   3. le nom de la feuille (« 6e A ») et la ligne « CLASSE : 6e A » au-dessus
#      du tableau étaient ignorés : sans colonne Classe, tout devenait
#      « Non affecté ».
#
# Ce qui suit lit TOUTES les feuilles, trouve le tableau dans chacune, sait ce
# qu'est une feuille de paiements et rattache ses lignes aux élèves. La règle
# de toujours tient : rien n'est inventé, tout ce qui n'est pas sûr est
# signalé, et c'est la Direction qui confirme.
# ===========================================================================

import unicodedata

LIBELLES_CHAMPS = {
    "student_name": "Identité Élève (Nom / Prénom)",
    "student_first_name": "Prénom de l'Élève",
    "student_last_name": "Nom de Famille",
    "student_middle_name": "Postnom de l'Élève",
    "class_name": "Classe / Section",
    "guardian_phone": "Téléphone Parent / Responsable",
    "guardian_name": "Nom du Responsable Légal",
    "fee_total": "Montant Total des Frais",
    "payment_amount": "Montant Déjà Encaissé",
    "payment_date": "Date du paiement (repère)",
}
CHAMPS_NOM = ("student_name", "student_first_name", "student_last_name", "student_middle_name")

# Une feuille dont le NOM parle d'argent se lit comme une feuille de paiements :
# ses lignes ne sont pas de nouveaux élèves, ce sont les versements des élèves
# déjà listés ailleurs.
TITRE_FINANCIER = re.compile(r"paie|paiement|versement|caisse|recette|encaiss|recu|transaction|finance|comptab|frais|minerval|tranche")


def _sans_accents(texte):
    texte = unicodedata.normalize("NFD", str(texte))
    return "".join(c for c in texte if unicodedata.category(c) != "Mn")


def _norm(texte):
    return re.sub(r"\s+", " ", _sans_accents(texte).lower().replace("_", " ")).strip()


def _texte(valeur):
    """Une cellule en texte. Excel range « 0812345678 » en NOMBRE 812345678.0 :
    lu tel quel, le « .0 » devenait un chiffre de plus dans le téléphone."""
    if valeur is None:
        return ""
    if isinstance(valeur, float) and valeur.is_integer():
        valeur = int(valeur)
    if hasattr(valeur, "strftime"):
        return valeur.strftime("%d/%m/%Y")
    return str(valeur).strip()


def classer_entete(entete):
    """Ce que désigne un titre de colonne, ou None. Les mots du parent passent
    AVANT ceux de l'élève : « Nom du parent » contient « nom », et le motif
    élève l'emportait — la colonne du parent devenait le nom de l'élève."""
    h = _norm(entete)
    if not h or re.fullmatch(r"n ?[°o]?\.?|no|num(ero)?|#|n°", h):
        return None
    parent = re.search(r"parent|tuteur|responsable|\bpere\b|\bmere\b|guardian|famille", h)
    if re.search(r"\btel\b|tel\.|telephone|phone|contact|mobile|gsm|whatsapp|portable|numero", h):
        return "guardian_phone"
    if parent:
        return "guardian_name"
    if re.search(r"reste|solde|restant|arriere", h):
        return None  # un solde n'est ni un dû ni un payé : on ne le devine pas
    if re.search(r"date|jour", h):
        return "payment_date"
    if re.search(r"(?<!a )(?<!a\s)\bpaye[es]?\b|deja|verse|versement|acompte|tranche|regle|encaiss|percu|avance|montant paye", h) and not re.search(r"a payer", h):
        return "payment_amount"
    if re.search(r"total|frais|minerval|montant|scolarit|a payer|\bdu\b|prix|cout", h):
        return "fee_total"
    if re.search(r"classe|section|niveau|promotion|grade|option|\bclass\b", h):
        return "class_name"
    sans_post = re.sub(r"post ?-? ?noms?", " ", h)
    a_post = sans_post != h
    a_prenom = re.search(r"prenom|first", h)
    a_nom = re.search(r"\bnoms?\b", sans_post)
    if a_prenom and a_nom:
        return "student_name"           # « Nom et prénom », « Noms, postnoms et prénoms »
    if a_prenom:
        return "student_first_name"
    if a_post and not a_nom:
        return "student_middle_name"    # « Post-nom », « Postnoms »
    if re.search(r"nom complet|identite|eleve|etudiant|apprenant|student", h):
        return "student_name"
    if re.search(r"nom de famille|last ?name", h):
        return "student_last_name"
    if a_nom:
        return "nom_ambigu"             # « Nom », « Noms et post-noms » : tranché plus bas
    return None


def _lire_entetes(ligne):
    """Colonne → champ, pour une ligne candidate. Un champ ne prend que sa
    PREMIÈRE colonne. « Nom » seul vaut nom de famille s'il existe une colonne
    Prénom à côté, nom complet sinon."""
    champs, vus = {}, set()
    remplies = [_texte(c) for c in ligne if _texte(c)]
    # Un TITRE de document n'est pas une ligne de titres de colonnes : une
    # seule cellule remplie, une phrase ou une année (« LISTE DES ÉLÈVES —
    # 2025-2026 » contient « élèves » et passait pour l'en-tête du tableau).
    if len(remplies) == 1 and (len(remplies[0].split()) > 3 or re.search(r"(19|20)\d\d", remplies[0])):
        return {}
    for i, cellule in enumerate(ligne):
        champ = classer_entete(_texte(cellule))
        if champ and champ not in vus:
            champs[i] = champ
            vus.add(champ)
    for i, champ in list(champs.items()):
        if champ == "nom_ambigu":
            cible = "student_last_name" if "student_first_name" in vus else "student_name"
            if cible in vus:
                del champs[i]
            else:
                champs[i] = cible
                vus.add(cible)
    return champs


def _score(champs):
    return len(champs) if any(c in CHAMPS_NOM for c in champs.values()) else 0


def trouver_tableau(lignes, profondeur=30):
    """L'index de la ligne de titres et sa lecture. On cherche dans les
    premières lignes la mieux reconnue, à condition qu'elle désigne un nom
    d'élève ; à égalité, la plus haute."""
    meilleur, meilleurs_champs, meilleur_score = None, {}, 0
    for idx, ligne in enumerate(lignes[:profondeur]):
        champs = _lire_entetes(ligne or [])
        s = _score(champs)
        if s > meilleur_score:
            meilleur, meilleurs_champs, meilleur_score = idx, champs, s
    return meilleur, meilleurs_champs


CLASSE_EN_TITRE = re.compile(r"^\s*(?:classe|class|section)\s*[:\-–]\s*(.+)$", re.I)


def _classe_du_titre(ligne):
    """« CLASSE : 6e A », écrit au-dessus d'un tableau ou entre deux blocs."""
    remplies = [_texte(c) for c in (ligne or []) if _texte(c)]
    if not remplies or len(remplies) > 2:
        return None
    texte = " ".join(remplies)
    m = CLASSE_EN_TITRE.match(texte)
    if m and m.group(1).strip():
        return m.group(1).strip()
    if len(remplies) == 2 and _norm(remplies[0]).rstrip(" :") in ("classe", "class", "section"):
        return remplies[1]
    return None


def _classe_du_nom_de_feuille(titre):
    """« 6e A », « 1re Primaire B » : une feuille par classe. Pas « Feuil1 »,
    pas « 2025-2026 », pas « Élèves »."""
    t = (titre or "").strip()
    n = _norm(t)
    if not re.search(r"\d", n) or re.fullmatch(r"(feuil(le)?|sheet|tableau|onglet|page)\s*\d+", n) or re.search(r"(19|20)\d\d", n):
        return None
    if TITRE_FINANCIER.search(n):
        return None
    return t


def parse_uploaded_workbook(file_storage):
    """Toutes les feuilles d'un classeur : [(nom de feuille, lignes)]. Un CSV
    est un classeur d'une feuille. Mêmes refus que parse_uploaded_table."""
    filename = (file_storage.filename or "").lower()
    if filename.endswith(".xlsx"):
        import openpyxl
        raw = file_storage.read()
        try:
            wb = openpyxl.load_workbook(filename=io.BytesIO(raw), data_only=True, read_only=True)
        except Exception:
            raise ValidationError(
                "Ce fichier n'est pas un classeur Excel valide. S'il s'agit d'un CSV, "
                "renommez-le en .csv ; sinon, ré-enregistrez-le depuis Excel ou "
                "téléchargez-le à nouveau.")
        return [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]
    if filename.endswith(".xls"):
        raise ValidationError(
            "Ce fichier est au format Excel 97-2003 (.xls). Ouvrez-le dans Excel et choisissez "
            "« Enregistrer sous » → « Classeur Excel (.xlsx) », puis déposez la nouvelle version.")
    return [("Fichier", parse_uploaded_table(file_storage))]


def _montant(texte):
    t = re.sub(r"[^\d,.\-]", "", texte.replace("FC", "").replace("$", ""))
    if t.count(",") == 1 and t.count(".") == 0:
        t = t.replace(",", ".")
    elif t.count(",") and t.count("."):
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    return float(t)


def _telephone(texte):
    tel = normalize_phone(texte)
    # « 0812345678 » enregistré comme nombre perd son zéro : 812345678.
    if tel and re.fullmatch(r"[89]\d{8}", tel):
        tel = "0" + tel
    return tel


def _cle_nom(texte):
    return frozenset(re.findall(r"[a-z0-9]+", _norm(texte)))


def _lire_feuille(titre, lignes):
    """Les lignes d'une feuille, champ par champ, avec leur numéro Excel et
    leur classe. Gère les tableaux en plusieurs blocs (« CLASSE : 6e A »,
    tableau, « CLASSE : 6e B », tableau) et ignore les lignes de total."""
    debut, champs = trouver_tableau(lignes)
    if debut is None:
        return None
    classe_courante = None
    for ligne in lignes[:debut]:
        classe_courante = _classe_du_titre(ligne) or classe_courante
    classe_feuille = _classe_du_nom_de_feuille(titre)
    entetes = [_texte(c) for c in lignes[debut]]
    enregistrements = []
    for pos in range(debut + 1, len(lignes)):
        ligne = lignes[pos] or []
        cellules = [_texte(c) for c in ligne]
        if not any(cellules):
            continue
        nouvelle_classe = _classe_du_titre(ligne)
        if nouvelle_classe:
            classe_courante = nouvelle_classe
            continue
        nouveaux = _lire_entetes(ligne)
        if _score(nouveaux) >= 2:
            champs, entetes = nouveaux, cellules   # un second bloc, avec ses titres
            continue
        premieres = [c for c in cellules if c][:2]
        if any(re.match(r"(sous.?)?total|effectif|nombre", _norm(c)) for c in premieres):
            continue
        valeurs = {champ: cellules[i] if i < len(cellules) else "" for i, champ in champs.items()}
        enregistrements.append({"ligne": pos + 1, "valeurs": valeurs,
                                "classe_hors_colonne": classe_courante or classe_feuille})
    return {"titre": titre, "ligne_titres": debut + 1, "champs": champs, "entetes": entetes,
            "enregistrements": enregistrements}


def _identite(v):
    premier = v.get("student_first_name", "")
    nom = " ".join(x for x in (v.get("student_last_name", ""), v.get("student_middle_name", "")) if x)
    complet = v.get("student_name", "")
    if premier:
        if not nom and complet:
            nom = complet
        return premier, nom
    if complet:
        parts = complet.split()
        return (" ".join(parts[1:]), parts[0]) if len(parts) > 1 else ("", complet)
    return "", nom


def analyze_workbook(feuilles, filename="import.xlsx"):
    """Analyse un classeur entier. Même résultat qu'analyze_raw_data (l'écran
    et la confirmation n'ont pas à changer), plus `sheets` : ce qui a été lu
    dans chaque feuille, et pourquoi une feuille a été laissée de côté."""
    lues = []
    for titre, lignes in feuilles:
        lecture = _lire_feuille(titre, lignes or [])
        lues.append((titre, lecture))

    avec_noms = [(t, l) for t, l in lues if l and l["enregistrements"]]
    financieres = [(t, l) for t, l in avec_noms if TITRE_FINANCIER.search(_norm(t))]
    eleves = [(t, l) for t, l in avec_noms if (t, l) not in financieres]
    if not eleves:          # un seul tableau, quel que soit son nom : c'est la liste
        eleves, financieres = avec_noms, []

    plusieurs = len(feuilles) > 1
    mapping, cols_total, cols_reconnues = {}, 0, 0
    for n, (titre, lecture) in enumerate(lues):
        if not lecture or (titre, lecture) not in avec_noms:
            continue
        for i, entete in enumerate(lecture["entetes"]):
            if not entete:
                continue
            champ = lecture["champs"].get(i)
            cols_total += 1
            cols_reconnues += 1 if champ else 0
            mapping[f"{n}:{i}"] = {
                "header": f"{titre} › {entete}" if plusieurs else entete,
                "field": champ or "unmapped",
                "label": LIBELLES_CHAMPS.get(champ, "Colonne non mappée (ignorée)"),
                "confidence": 0.95 if champ else 0.40,
            }

    students, duplicates, anomalies = [], [], []
    vus, missing_guardians, fee_col_seen, pay_col_seen = {}, 0, False, False
    for titre, lecture in eleves:
        champs = set(lecture["champs"].values())
        fee_col_seen = fee_col_seen or "fee_total" in champs
        pay_col_seen = pay_col_seen or "payment_amount" in champs
        for enr in lecture["enregistrements"]:
            v, ligne = enr["valeurs"], enr["ligne"]
            premier, nom = _identite(v)
            complet = f"{nom} {premier}".strip()
            if not complet:
                continue
            ref = {"row": ligne, "sheet": titre if plusieurs else None, "name": complet}
            classe = normalize_class_name(v.get("class_name") or enr["classe_hors_colonne"])
            cle = (_cle_nom(complet), classe)
            if cle in vus:
                duplicates.append({**ref, "first_seen_row": vus[cle], "type": "Doublon potentiel détecté"})
            else:
                vus[cle] = f"{titre}, ligne {ligne}" if plusieurs else ligne
            tel = None
            if v.get("guardian_phone"):
                tel = _telephone(v["guardian_phone"])
                if not tel:
                    anomalies.append({**ref, "field": "phone",
                                      "issue": f"Format de téléphone incomplet ou invalide : '{v['guardian_phone']}'"})
            fee = None
            if v.get("fee_total"):
                try:
                    fee = _montant(v["fee_total"])
                except ValueError:
                    anomalies.append({**ref, "field": "finance",
                                      "issue": f"Montant de frais illisible : '{v['fee_total']}' — aucune obligation ne sera créée pour cette ligne"})
            paye = 0.0
            if v.get("payment_amount"):
                try:
                    paye = _montant(v["payment_amount"])
                except ValueError:
                    anomalies.append({**ref, "field": "finance", "issue": f"Montant payé illisible : '{v['payment_amount']}' — ignoré"})
            parent = v.get("guardian_name") or None
            if not parent and not tel:
                missing_guardians += 1
            students.append({"first_name": premier, "last_name": nom, "class_name": classe,
                             "guardian_phone": tel, "guardian_name": parent,
                             "fee_amount": fee, "paid_amount": paye, "_ref": ref})

    # Feuilles de paiements : chaque ligne se rattache à UN élève de la liste,
    # par son nom (ordre des mots indifférent : « KABONGO MUTOMBO Grace » et
    # « Grace KABONGO MUTOMBO » sont la même personne), départagé par la classe.
    # Rien n'est rattaché au hasard : un nom introuvable ou porté par deux
    # élèves est signalé, et son montant n'entre pas.
    notes_feuilles = {}
    par_nom = {}
    for s in students:
        par_nom.setdefault(_cle_nom(f"{s['last_name']} {s['first_name']}"), []).append(s)
    for titre, lecture in financieres:
        if pay_col_seen:
            notes_feuilles[titre] = ("La liste des élèves a déjà une colonne « payé » : "
                                     "les montants de cette feuille ne sont pas ajoutés (ils seraient comptés deux fois).")
            continue
        rattaches = 0
        for enr in lecture["enregistrements"]:
            v, ligne = enr["valeurs"], enr["ligne"]
            premier, nom = _identite(v)
            complet = f"{nom} {premier}".strip()
            if not complet:
                continue
            ref = {"row": ligne, "sheet": titre, "name": complet}
            candidats = par_nom.get(_cle_nom(complet), [])
            classe = v.get("class_name") or enr["classe_hors_colonne"]
            if len(candidats) > 1 and classe:
                candidats = [c for c in candidats if c["class_name"] == normalize_class_name(classe)]
            if len(candidats) != 1:
                anomalies.append({**ref, "field": "finance", "issue":
                                  "Paiement non rattaché : " + ("élève introuvable dans la liste" if not candidats
                                                                else "plusieurs élèves portent ce nom") + " — non importé"})
                continue
            eleve = candidats[0]
            try:
                if v.get("payment_amount"):
                    eleve["paid_amount"] += _montant(v["payment_amount"])
                if v.get("fee_total") and eleve["fee_amount"] is None:
                    eleve["fee_amount"] = _montant(v["fee_total"])
                    fee_col_seen = True
                rattaches += 1
            except ValueError:
                anomalies.append({**ref, "field": "finance", "issue": "Montant illisible — ignoré"})
        notes_feuilles[titre] = f"{rattaches} ligne(s) rattachée(s) à un élève."

    total_fee = total_paid = 0.0
    for s in students:
        ref = s.pop("_ref")
        if s["fee_amount"] is not None and s["paid_amount"] > s["fee_amount"]:
            anomalies.append({**ref, "field": "finance",
                              "issue": f"Montant payé ({s['paid_amount']:g}) supérieur au total facturé ({s['fee_amount']:g})"})
        if s["fee_amount"] is None and s["paid_amount"] > 0:
            anomalies.append({**ref, "field": "finance",
                              "issue": f"Un paiement ({s['paid_amount']:g}) est indiqué sans montant dû — il ne sera pas importé"})
            s["paid_amount"] = 0.0
        total_fee += s["fee_amount"] or 0.0
        total_paid += s["paid_amount"]

    sheets = []
    for titre, lecture in lues:
        if lecture and (titre, lecture) in eleves:
            role, detail = "eleves", f"{len(lecture['enregistrements'])} ligne(s) d'élèves, titres en ligne {lecture['ligne_titres']}"
        elif lecture and (titre, lecture) in financieres:
            role, detail = "paiements", notes_feuilles.get(titre, "")
        else:
            role, detail = "ignoree", "Aucune colonne de nom d'élève reconnue (liste de classes, texte explicatif…)"
        sheets.append({"name": titre, "role": role, "detail": detail})

    classes = sorted({s["class_name"] for s in students})
    quality = max(55, 100 - min(30, len(duplicates) * 3) - min(30, len(anomalies) * 2))
    return {
        "filename": filename,
        "total_rows_detected": sum(len(l["enregistrements"]) for _, l in eleves),
        "students_count": len(students),
        "classes_count": len(classes),
        "classes_detected": classes,
        "guardians_count": sum(1 for s in students if s["guardian_name"] or s["guardian_phone"]),
        "columns_recognized": cols_reconnues,
        "columns_total": cols_total,
        "missing_info_count": missing_guardians + sum(1 for s in students if s["fee_amount"] is None),
        "fees_detected": fee_col_seen,
        "mapping": mapping,
        "duplicates": duplicates,
        "anomalies": anomalies,
        "data_quality_score": quality,
        "financial_projection": {
            "total_obligations_sum": round(total_fee, 2),
            "total_payments_sum": round(total_paid, 2),
            "total_outstanding_sum": round(total_fee - total_paid, 2),
        },
        "sheets": sheets,
        "preview_records": students[:6],
        "normalized_records": students,
    }
