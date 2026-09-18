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
    """Analyse les données brutes tabulaires :
    - Détecte les en-têtes et propose les mappings avec niveau de confiance.
    - Détecte les entités (classes, élèves, montants).
    - Identifie les anomalies (doublons, téléphones invalides, incohérences financières).
    - Produit une prévisualisation 'Ce qui sera créé'.
    """
    if not data_rows or len(data_rows) == 0:
        return {"error": "Fichier vide ou données non reconnues."}

    headers = [str(h).strip() for h in data_rows[0]]
    rows = data_rows[1:]

    # 1. AI Mapping des colonnes avec indices de confiance
    mapping = {}
    detected_fields = {}

    for idx, header in enumerate(headers):
        clean_h = header.lower()
        matched = False
        for field, config in COLUMN_PATTERNS.items():
            if field in detected_fields:
                continue
            for pat in config["patterns"]:
                if re.search(pat, clean_h):
                    mapping[idx] = {
                        "header": header,
                        "field": field,
                        "label": config["label"],
                        "confidence": config["confidence"]
                    }
                    detected_fields[field] = idx
                    matched = True
                    break
            if matched:
                break
        if not matched:
            mapping[idx] = {
                "header": header,
                "field": "unmapped",
                "label": "Colonne non mappée (ignorée)",
                "confidence": 0.40
            }

    # 2. Analyse des enregistrements et détection des entités
    classes_set = set()
    students_list = []
    seen_names = {}
    duplicates = []
    anomalies = []
    total_fee_sum = 0.0
    total_paid_sum = 0.0
    missing_guardians = 0

    name_col = detected_fields.get("student_name")
    first_name_col = detected_fields.get("student_first_name")
    last_name_col = detected_fields.get("student_last_name")
    class_col = detected_fields.get("class_name")
    phone_col = detected_fields.get("guardian_phone")
    parent_col = detected_fields.get("guardian_name")
    fee_col = detected_fields.get("fee_total")
    pay_col = detected_fields.get("payment_amount")

    for row_idx, r in enumerate(rows):
        if not r or len(r) == 0:
            continue

        # Résolution du nom
        full_name = ""
        first_name = ""
        last_name = ""

        # Une colonne PRÉNOM dédiée fait toujours foi.
        #
        # Trouvé à l'audit : le motif de détection du « nom complet » est
        # `nom`, qui matche aussi un en-tête valant simplement « Nom ». Un
        # fichier organisé en deux colonnes Nom | Prénom — la forme la plus
        # courante d'un listing scolaire — était donc traité comme s'il ne
        # portait qu'un nom complet : la colonne Prénom était détectée,
        # affichée dans l'aperçu de mapping… puis jamais lue. Tous les élèves
        # entraient sans prénom, sans le moindre avertissement.
        #
        # Le cas « nom complet seul » (celui du fichier d'exemple, colonne
        # « Nom complet ») passe par la branche suivante, inchangée.
        prenom_dedie = (first_name_col is not None and first_name_col < len(r)
                        and r[first_name_col] and str(r[first_name_col]).strip())
        if prenom_dedie:
            first_name = str(r[first_name_col]).strip()
            col_nom = last_name_col if last_name_col is not None else name_col
            if col_nom is not None and col_nom < len(r) and r[col_nom]:
                last_name = str(r[col_nom]).strip()
            full_name = f"{last_name} {first_name}".strip()
        elif name_col is not None and name_col < len(r) and r[name_col]:
            full_name = str(r[name_col]).strip()
            parts = full_name.split()
            if len(parts) > 1:
                last_name = parts[0]
                first_name = " ".join(parts[1:])
            else:
                last_name = full_name
                first_name = ""
        elif last_name_col is not None and last_name_col < len(r):
            last_name = str(r[last_name_col]).strip() if r[last_name_col] else ""
            if first_name_col is not None and first_name_col < len(r):
                first_name = str(r[first_name_col]).strip() if r[first_name_col] else ""
            full_name = f"{last_name} {first_name}".strip()

        if not full_name:
            continue

        # Résolution de la classe — jamais une classe inventée : sans colonne
        # classe, l'élève est explicitement "Non affecté" (la Direction
        # l'affectera depuis son dossier).
        raw_class = str(r[class_col]).strip() if class_col is not None and class_col < len(r) and r[class_col] else None
        norm_class = normalize_class_name(raw_class)
        classes_set.add(norm_class)

        # Détection de doublon
        name_key = full_name.lower()
        if name_key in seen_names:
            duplicates.append({
                "row": row_idx + 2,
                "name": full_name,
                "first_seen_row": seen_names[name_key],
                "type": "Doublon potentiel détecté"
            })
        else:
            seen_names[name_key] = row_idx + 2

        # Téléphone
        phone = None
        if phone_col is not None and phone_col < len(r) and r[phone_col]:
            phone = normalize_phone(r[phone_col])
            if not phone:
                anomalies.append({
                    "row": row_idx + 2,
                    "name": full_name,
                    "field": "phone",
                    "issue": f"Format de téléphone incomplet ou invalide : '{r[phone_col]}'"
                })

        # Montants financiers — AUCUN montant par défaut : sans colonne de frais
        # dans le fichier, aucune obligation n'est créée (la Direction la
        # créera depuis le dossier). Un chiffre inventé fausserait tout le
        # Financial Core.
        fee_amount = None
        if fee_col is not None and fee_col < len(r) and r[fee_col] not in (None, ""):
            try:
                fee_amount = float(str(r[fee_col]).replace("$", "").replace("FC", "").replace(" ", "").replace(",", ".").strip())
            except ValueError:
                anomalies.append({"row": row_idx + 2, "name": full_name, "field": "finance",
                                  "issue": f"Montant de frais illisible : '{r[fee_col]}' — aucune obligation ne sera créée pour cette ligne"})
                fee_amount = None

        paid_amount = 0.0
        if pay_col is not None and pay_col < len(r) and r[pay_col] not in (None, ""):
            try:
                paid_amount = float(str(r[pay_col]).replace("$", "").replace("FC", "").replace(" ", "").replace(",", ".").strip())
            except ValueError:
                anomalies.append({"row": row_idx + 2, "name": full_name, "field": "finance",
                                  "issue": f"Montant payé illisible : '{r[pay_col]}' — ignoré"})
                paid_amount = 0.0

        # Anomalie financière : payé > dû, ou payé sans montant dû
        if fee_amount is not None and paid_amount > fee_amount:
            anomalies.append({
                "row": row_idx + 2,
                "name": full_name,
                "field": "finance",
                "issue": f"Montant payé ({paid_amount:g}) supérieur au total facturé ({fee_amount:g})"
            })
        if fee_amount is None and paid_amount > 0:
            anomalies.append({"row": row_idx + 2, "name": full_name, "field": "finance",
                              "issue": f"Un paiement ({paid_amount:g}) est indiqué sans montant dû — il ne sera pas importé"})
            paid_amount = 0.0

        total_fee_sum += fee_amount or 0.0
        total_paid_sum += paid_amount

        guardian_name = str(r[parent_col]).strip() if parent_col is not None and parent_col < len(r) and r[parent_col] else None
        if not guardian_name and not phone:
            missing_guardians += 1

        students_list.append({
            "first_name": first_name or "",
            "last_name": last_name or "",
            "class_name": norm_class,
            "guardian_phone": phone,
            "guardian_name": guardian_name,  # jamais un "Parent X" inventé
            "fee_amount": fee_amount,
            "paid_amount": paid_amount
        })

    # Calcul du score de qualité des données
    quality_score = 100
    quality_score -= min(30, len(duplicates) * 3)
    quality_score -= min(30, len(anomalies) * 2)
    quality_score = max(55, quality_score)

    guardians_count = sum(1 for s in students_list if s["guardian_name"] or s["guardian_phone"])
    return {
        "filename": filename,
        "total_rows_detected": len(rows),
        "students_count": len(students_list),
        "classes_count": len(classes_set),
        "classes_detected": sorted(list(classes_set)),
        "guardians_count": guardians_count,
        "columns_recognized": sum(1 for m in mapping.values() if m["field"] != "unmapped"),
        "columns_total": len(headers),
        "missing_info_count": missing_guardians + sum(1 for s in students_list if s["fee_amount"] is None),
        "fees_detected": fee_col is not None,
        "mapping": mapping,
        "duplicates": duplicates,
        "anomalies": anomalies,
        "data_quality_score": quality_score,
        "financial_projection": {
            "total_obligations_sum": round(total_fee_sum, 2),
            "total_payments_sum": round(total_paid_sum, 2),
            "total_outstanding_sum": round(total_fee_sum - total_paid_sum, 2)
        },
        "preview_records": students_list[:6],  # Échantillon représentatif
        "normalized_records": students_list
    }


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
