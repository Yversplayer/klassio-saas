"""KLASSIO — Assistant IA conversationnel, STRICTEMENT en lecture seule.

Architecture (voir docs et le prompt de conception) :

    Conversation UI -> AI Orchestrator -> Permission Layer -> Context Engine
    -> READ-ONLY TOOL LAYER -> Business Services (financial.py, etc.) -> DB

Principe non négociable : le catalogue d'outils exposé ici ne contient QUE des
fonctions get_*/search_*/explain_*. Il n'existe aucune fonction create_*,
update_* ou delete_* dans ce module, et il ne peut donc structurellement pas en
appeler une — la garantie ne repose pas sur un prompt système, mais sur le fait
que ces fonctions n'existent tout simplement pas dans ce fichier.

Aucun fournisseur de langage externe n'est connecté à ce projet (pas de clé
OPENAI/ANTHROPIC configurée pour le produit). Plutôt que de simuler un appel à
un LLM, ce module fait de la compréhension réelle mais déterministe : détection
d'intention par motifs (regex/mots-clés) sur des questions en français, jamais
une réponse inventée. Si aucune intention connue ne correspond, l'assistant le
dit honnêtement plutôt que d'halluciner.
"""
import re
import time
from datetime import datetime, timedelta, date

import financial
import school

# ---------------------------------------------------------------------------
# Garde-fou architectural (docs point 16) — vérifié AVANT toute tentative de
# compréhension de la question. Si un verbe d'action rencontre un nom de
# domaine métier, on refuse immédiatement : pas d'exécution, jamais.
# ---------------------------------------------------------------------------
ACTION_VERBS = (
    r"cr[ée]e?r?|ajout(?:e|er|ez)|modifi(?:e|er|ez)|chang(?:e|er|ez)|"
    r"supprim(?:e|er|ez)|effac(?:e|er|ez)|enregistr(?:e|er|ez)|annul(?:e|er|ez)|"
    r"rembours(?:e|er|ez)|envoi(?:e|er|ez)|invit(?:e|er|ez)|configur(?:e|er|ez)|"
    r"d[ée]sactiv(?:e|er|ez)|activ(?:e|er|ez)|r[ée]init|export(?:e|er|ez)|"
    r"confirm(?:e|er|ez)|valid(?:e|er|ez)|sanctionn(?:e|er|ez)|exclu(?:s|re|ez)|"
    r"renvo(?:ie|yer|yez)|punir|punis|marqu(?:e|er|ez)|not(?:e|er|ez)\s+(?:l|un)|"
    r"mets?|mettre|mettez|pass(?:e|er|ez)\s+en|"
    r"pass(?:e|er|ez)\s+\S+\s+en\s+(?:pay|r[ée]gl|valid|activ|inactiv)"
)
ENTITY_WORDS = {
    "eleve": r"[ée]l[èe]ves?",
    "classe": r"classes?",
    "parent": r"parents?|responsables?",
    "enseignant": r"enseignants?|professeurs?|titulaires?",
    "paiement": r"paiements?|transactions?|re[çc]us?",
    "obligation": r"obligations?|frais|montants?\s+d[uû]s?",
    "notification": r"notifications?|sms|whatsapp|rappels?",
    "parametre": r"param[èe]tres?|permissions?|configuration",
    "utilisateur": r"utilisateurs?|comptes?|invitations?",
    "etablissement": r"[ée]tablissement",
    "abonnement": r"abonnements?|souscriptions?|formule\s+klassio|facture\s+klassio",
    "presence": r"pr[ée]sences?|absences?|absent|retards?|appel",
    "discipline": r"incidents?|sanctions?|discipline|avertissements?|points?|exclusion|renvoi",
    "note": r"notes?|bulletins?|r[ée]sultats?|moyennes?",
    "commande": r"commandes?|boutique|produits?|stock",
}
REFUSAL_BY_ENTITY = {
    "eleve": "Je ne peux pas créer, modifier ou supprimer un élève. Cette opération doit être effectuée directement depuis la page Élèves.",
    "classe": "Je ne peux pas créer, modifier ou supprimer une classe. Rendez-vous dans Classes pour effectuer cette opération.",
    "parent": "Je ne peux pas créer, modifier ou inviter un parent. Cette opération se fait depuis Établissement.",
    "enseignant": "Je ne peux pas créer, modifier ou inviter un enseignant. Cette opération se fait depuis Établissement.",
    "paiement": "Je ne peux pas enregistrer, confirmer, modifier ou rembourser un paiement. Cette opération doit être effectuée directement depuis l'espace approprié.",
    "obligation": "Je ne peux pas créer ou modifier un montant dû. Cette opération se fait depuis le dossier de l'élève concerné.",
    "notification": "Je ne peux pas envoyer de notification, SMS ou WhatsApp à votre place.",
    "parametre": "Je ne peux pas modifier les paramètres ou les permissions de votre établissement.",
    "utilisateur": "Je ne peux pas créer, modifier, supprimer ou inviter un utilisateur. Cette opération se fait depuis Établissement.",
    "etablissement": "Je ne peux pas modifier les données de votre établissement.",
    "abonnement": "Je ne peux pas modifier l'abonnement de votre établissement à Klassio — ni le marquer payé, ni changer de formule. Cela se règle depuis Paramètres, section Abonnement. À ne pas confondre avec les frais scolaires des élèves : ce sont deux circuits distincts.",
    "presence": "Je ne peux pas enregistrer ni modifier une présence. L'appel se fait depuis la page de la classe, par une personne habilitée.",
    "discipline": "Je ne décide jamais d'une sanction et je ne peux pas créer ou modifier un incident. Les décisions disciplinaires restent humaines — depuis l'espace Discipline.",
    "note": "Je ne peux pas saisir ni modifier une note. Les résultats se saisissent depuis la page de la classe.",
    "commande": "Je ne peux pas créer, modifier ou annuler une commande ni un produit. Cette opération se fait depuis Boutique.",
}
GENERIC_REFUSAL = ("Je peux vous aider à retrouver ou analyser des informations, mais je ne peux "
                    "pas créer, modifier ou supprimer des données dans Klassio. Cette opération doit "
                    "être effectuée directement depuis l'espace approprié.")


def _is_write_intent(text):
    if not re.search(ACTION_VERBS, text, re.I):
        return None
    for entity, pattern in ENTITY_WORDS.items():
        if re.search(pattern, text, re.I):
            return entity
    return None


# ---------------------------------------------------------------------------
# Contexte / permissions — reproduit exactement les règles déjà appliquées
# ailleurs dans le produit (security.ROLE_PERMISSIONS, _resolve_student_access
# dans app.py) : l'IA ne voit jamais plus que ce que l'utilisateur verrait en
# naviguant lui-même dans Klassio.
# ---------------------------------------------------------------------------

def _own_children_ids(conn, ctx):
    rows = conn.execute(
        """SELECT s.id FROM students s
           JOIN student_guardians sg ON sg.student_id = s.id
           JOIN guardians g ON g.id = sg.guardian_id
           WHERE sg.tenant_id = ? AND g.user_id = ?""",
        (ctx["tenant_id"], ctx["user_id"]),
    ).fetchall()
    return [r["id"] for r in rows]


def _find_own_child(conn, ctx, name_fragment):
    ids = _own_children_ids(conn, ctx)
    if not ids:
        return None
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT * FROM students WHERE id IN ({placeholders})", tuple(ids)
    ).fetchall()
    frag = name_fragment.lower().strip()
    for s in rows:
        full = (s["first_name"] + " " + s["last_name"]).lower()
        if frag and (frag in full or s["first_name"].lower() in frag or s["last_name"].lower() in frag):
            return s
    return rows[0] if len(rows) == 1 else None


# ---------------------------------------------------------------------------
# Outils de lecture — chaque fonction lit, ne modifie jamais rien.
# ---------------------------------------------------------------------------

def get_student_count(conn, ctx):
    if ctx["role"] == "parent":
        return len(_own_children_ids(conn, ctx))
    # Un professeur ou un DD compte les élèves de SON périmètre : l'effectif
    # de toute l'école n'est pas une donnée de son espace (08/10/2026).
    ids = school.visible_class_ids(conn, ctx)
    if ids is not None:
        if not ids:
            return 0
        return conn.execute(f"SELECT COUNT(*) n FROM students WHERE tenant_id=? AND status='active' AND class_id IN ({','.join('?' for _ in ids)})",
                            (ctx["tenant_id"], *ids)).fetchone()["n"]
    return conn.execute("SELECT COUNT(*) n FROM students WHERE tenant_id=?", (ctx["tenant_id"],)).fetchone()["n"]


def get_class_count(conn, ctx):
    return conn.execute("SELECT COUNT(*) n FROM classes WHERE tenant_id=?", (ctx["tenant_id"],)).fetchone()["n"]


def get_tenant_financial_summary(conn, ctx):
    row = conn.execute(
        """SELECT COALESCE(SUM(o.amount),0) as total_due,
                  COALESCE((SELECT SUM(p.amount) FROM payments p JOIN obligations o2 ON o2.id=p.obligation_id
                            WHERE p.tenant_id=? AND o2.tenant_id=? AND p.status='CONFIRMED'),0) as total_paid
           FROM obligations o WHERE o.tenant_id=?""",
        (ctx["tenant_id"], ctx["tenant_id"], ctx["tenant_id"]),
    ).fetchone()
    due, paid = row["total_due"] or 0.0, row["total_paid"] or 0.0
    return {"total_due": round(due, 2), "total_paid": round(paid, 2), "outstanding": round(due - paid, 2)}


def get_period_collections(conn, ctx, start_ts, end_ts):
    row = conn.execute(
        """SELECT COALESCE(SUM(p.amount),0) as total FROM payments p
           WHERE p.tenant_id=? AND p.status='CONFIRMED'
             AND CAST(p.confirmed_at AS REAL) >= ? AND CAST(p.confirmed_at AS REAL) < ?""",
        (ctx["tenant_id"], start_ts, end_ts),
    ).fetchone()
    return round(row["total"] or 0.0, 2)


def month_bounds(offset_months=0):
    now = datetime.now()
    year, month = now.year, now.month + offset_months
    while month < 1:
        month += 12; year -= 1
    while month > 12:
        month -= 12; year += 1
    start = datetime(year, month, 1)
    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1; next_year += 1
    end = datetime(next_year, next_month, 1)
    return start.timestamp(), end.timestamp()


def get_biggest_unpaid(conn, ctx, limit=5):
    rows = conn.execute(
        """SELECT s.id, s.first_name, s.last_name, c.name as class_name,
                  COALESCE(ob.total_due,0) - COALESCE(pay.total_paid,0) as balance
           FROM students s
           LEFT JOIN classes c ON c.id = s.class_id
           LEFT JOIN (SELECT student_id, SUM(amount) total_due FROM obligations WHERE tenant_id=? GROUP BY student_id) ob ON ob.student_id=s.id
           LEFT JOIN (SELECT o.student_id, SUM(p.amount) total_paid FROM payments p JOIN obligations o ON o.id=p.obligation_id
                      WHERE p.tenant_id=? AND p.status='CONFIRMED' GROUP BY o.student_id) pay ON pay.student_id=s.id
           WHERE s.tenant_id=?
           ORDER BY balance DESC LIMIT ?""",
        (ctx["tenant_id"], ctx["tenant_id"], ctx["tenant_id"], limit),
    ).fetchall()
    return [dict(r) for r in rows if (r["balance"] or 0) > 0]


def get_students_without_payment(conn, ctx):
    rows = conn.execute(
        """SELECT s.id, s.first_name, s.last_name, c.name as class_name,
                  COALESCE(ob.total_due,0) as total_due, COALESCE(pay.total_paid,0) as total_paid
           FROM students s
           LEFT JOIN classes c ON c.id = s.class_id
           LEFT JOIN (SELECT student_id, SUM(amount) total_due FROM obligations WHERE tenant_id=? GROUP BY student_id) ob ON ob.student_id=s.id
           LEFT JOIN (SELECT o.student_id, SUM(p.amount) total_paid FROM payments p JOIN obligations o ON o.id=p.obligation_id
                      WHERE p.tenant_id=? AND p.status='CONFIRMED' GROUP BY o.student_id) pay ON pay.student_id=s.id
           WHERE s.tenant_id=?""",
        (ctx["tenant_id"], ctx["tenant_id"], ctx["tenant_id"]),
    ).fetchall()
    return [dict(r) for r in rows if (r["total_due"] or 0) > 0 and (r["total_paid"] or 0) == 0]


def get_students_by_class(conn, ctx, class_name_fragment):
    rows = conn.execute(
        """SELECT s.id, s.first_name, s.last_name, c.name as class_name
           FROM students s JOIN classes c ON c.id = s.class_id
           -- LIKE : SQLite ignore la casse sur l'ASCII, PostgreSQL non. Sans
           -- LOWER() des deux côtés, la recherche cessait de trouver quoi que
           -- ce soit dès que la casse différait — sans la moindre erreur.
           WHERE s.tenant_id=? AND LOWER(c.name) LIKE ?""",
        (ctx["tenant_id"], "%" + class_name_fragment.strip().lower() + "%"),
    ).fetchall()
    return [dict(r) for r in rows]


def search_students(conn, ctx, query):
    """Recherche par nom, DANS LE PÉRIMÈTRE DU RÔLE.

    Cette fonction ne filtrait que sur `tenant_id`. Toutes les autres lectures
    de ce module passent par `school.students_where_clause()` — celle-ci était
    la seule à l'oublier, et c'est justement celle qui prend un nom en entrée.

    Mesuré le 20/09 sur la base de test : un professeur dont le périmètre
    compte 67 élèves sur 400 demandait « trouve Esther » et recevait DIX
    résultats, dont SEPT hors de ses classes — nom et classe compris. Ce n'était
    pas une fuite entre établissements (le `tenant_id` tenait), mais une fuite
    entre RÔLES à l'intérieur de l'école, c'est-à-dire exactement la promesse du
    produit : chaque rôle ne voit que ce qui le regarde.

    L'appelant écarte déjà le parent. Ce filtre-ci protège le professeur et le
    DD, dont le périmètre est réel et restreint — et il protégera le parent
    aussi le jour où quelqu'un lèvera cette condition en amont.
    """
    where, params = school.students_where_clause(conn, ctx)
    if where is None:
        return []
    motif = "%" + query.lower() + "%"
    rows = conn.execute(
        f"""SELECT s.id, s.first_name, s.last_name, c.name as class_name
            FROM students s LEFT JOIN classes c ON c.id = s.class_id
            -- LOWER() des deux côtés : voir get_students_by_class ci-dessus.
            WHERE {where} AND (LOWER(s.first_name) LIKE ? OR LOWER(s.last_name) LIKE ?)""",
        params + (motif, motif),
    ).fetchall()
    return [dict(r) for r in rows]


FEATURE_EXPLANATIONS = {
    "import": ("L'import Excel/CSV analyse réellement votre fichier : il détecte les colonnes "
               "(élèves, classes, frais, paiements), calcule un score de qualité et vous montre un "
               "aperçu complet de ce qui sera créé. Rien n'est écrit dans votre espace avant que "
               "vous ne confirmiez explicitement — l'analyse et l'import sont deux étapes séparées."),
    "finance_vs_paiements": ("Finance montre la vue globale — frais, obligations, catégories, soldes "
               "attendus. Paiements montre les opérations — chaque transaction reçue, son statut et "
               "sa méthode. Finance répond à « combien devrait-on avoir ? », Paiements répond à "
               "« qu'est-ce qui a réellement été encaissé, et comment ? »."),
    "invitations": ("Les professeurs et les parents ne créent jamais de compte librement. Depuis "
               "Établissement, vous générez un lien d'invitation à usage unique, valable 7 jours, "
               "que vous partagez par copie ou WhatsApp. Le rôle est toujours déterminé par "
               "l'invitation, jamais choisi par la personne qui l'accepte."),
}


# ---------------------------------------------------------------------------
# Moteur d'intention — motifs ordonnés, le premier qui correspond gagne.
# ---------------------------------------------------------------------------

def _money(v, currency="USD"):
    symbol = {"USD": "$", "CDF": "FC", "EUR": "€"}.get(currency, currency)
    return f"{v:,.2f}".replace(",", " ").replace(".", ",") + " " + symbol


# ---------------------------------------------------------------------------
# Outils de lecture — dossier central (présences, discipline, reçus) : chaque
# fonction applique school.py, donc EXACTEMENT le même périmètre que l'UI.
# ---------------------------------------------------------------------------

_CLASS_STOP_WORDS = {"sont", "est", "ont", "a", "qui", "aujourd", "ce", "cette", "en", "de", "la", "le", "les", "classe", "mes", "ma", "mon"}


def _extract_class_fragment(low):
    """« … de la 6e A sont absents … » → "6e a" ; « … en 4e sciences ? » → "4e sciences"."""
    m = re.search(r"(?:de|en|dans)\s+(?:la\s+|l['’]\s*)?(?:classe\s+(?:de\s+)?)?(\d{1,2}\s*(?:e|ème|eme|re|ère)?(?:\s+[a-z0-9àâäéèêëïîôöùûüç]+){0,3})", low)
    if not m:
        m = re.search(r"(?:de|en|dans)\s+(?:la\s+)?classe\s+([a-zàâäéèêëïîôöùûüç0-9]+(?:\s+[a-zàâäéèêëïîôöùûüç0-9]+)?)", low)
    if not m:
        return None
    words = [w for w in re.split(r"\s+", m.group(1).strip()) if w]
    kept = []
    for w in words:
        if w.strip("?.!") in _CLASS_STOP_WORDS:
            break
        kept.append(w.strip("?.!"))
    return " ".join(kept) if kept else None


def find_visible_student(conn, ctx, name_fragment):
    where, params = school.students_where_clause(conn, ctx)
    if where is None:
        return None
    frag = name_fragment.strip().lower()
    rows = conn.execute(f"SELECT s.* FROM students s WHERE {where} AND s.status='active'", params).fetchall()
    for s in rows:
        full = (s["first_name"] + " " + s["last_name"]).lower()
        rev = (s["last_name"] + " " + s["first_name"]).lower()
        if frag == full or frag == rev or (s["code"] or "").lower() == frag:
            return s
    for s in rows:
        full = (s["first_name"] + " " + s["last_name"]).lower()
        if frag in full or s["first_name"].lower() == frag or s["last_name"].lower() == frag:
            return s
    return None


def get_class_attendance_today(conn, ctx, class_fragment):
    allowed = school.visible_class_ids(conn, ctx)
    where, params = "tenant_id=? AND LOWER(name) LIKE ?", [ctx["tenant_id"], "%" + class_fragment.strip().lower() + "%"]
    if allowed is not None:
        if not allowed:
            return None
        where += f" AND id IN ({','.join('?' for _ in allowed)})"
        params += allowed
    # Correspondance exacte d'abord (« 1e primaire c » ≠ « 1e primaire a »), puis partielle.
    exact_params = list(params)
    exact_params[1] = class_fragment.strip().lower()
    cls = conn.execute(f"SELECT * FROM classes WHERE {where.replace('LIKE', '=')} LIMIT 1", exact_params).fetchone()
    if not cls:
        cls = conn.execute(f"SELECT * FROM classes WHERE {where} ORDER BY name LIMIT 1", params).fetchone()
    if not cls:
        return None
    recs = conn.execute(
        """SELECT a.status, s.first_name, s.last_name FROM attendance a JOIN students s ON s.id=a.student_id
           WHERE a.tenant_id=? AND a.class_id=? AND a.date=? ORDER BY s.last_name""",
        (ctx["tenant_id"], cls["id"], school.today_iso()),
    ).fetchall()
    return cls, [dict(r) for r in recs]


def get_students_repeated(conn, ctx, status, min_count=2):
    where, params = school.students_where_clause(conn, ctx)
    if where is None:
        return []
    since = (date.today() - timedelta(days=30)).isoformat()
    rows = conn.execute(
        f"""SELECT s.id, s.first_name, s.last_name, c.name AS class_name, COUNT(a.id) AS n
            FROM attendance a JOIN students s ON s.id=a.student_id LEFT JOIN classes c ON c.id=s.class_id
            WHERE {where} AND a.status=? AND a.date>=?
            -- GROUP BY : PostgreSQL n'accepte une colonne nue que si elle appartient à la
            -- table dont la clé primaire est groupée. c.name vient de `classes`, pas de
            -- `students` : elle doit être listée explicitement (SQLite, lui, l'acceptait).
            GROUP BY s.id, s.first_name, s.last_name, c.name
            HAVING COUNT(a.id) >= ? ORDER BY n DESC""",
        params + (status, since, min_count),
    ).fetchall()
    return [dict(r) for r in rows]


def get_recent_incidents(conn, ctx):
    where, params = school.students_where_clause(conn, ctx)
    if where is None:
        return []
    since = (date.today() - timedelta(days=30)).isoformat()
    rows = conn.execute(
        f"""SELECT i.occurred_at, i.title, s.first_name, s.last_name, c.name AS class_name FROM incidents i
            JOIN students s ON s.id=i.student_id LEFT JOIN classes c ON c.id=i.class_id
            WHERE {where} AND i.occurred_at >= ? ORDER BY i.occurred_at DESC""",
        params + (since,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_class_finance_for_teacher(conn, ctx):
    result = []
    tid = ctx["tenant_id"]
    for c in school.teacher_class_rows(conn, ctx):
        # `tenant_id` partout, y compris là où la classe suffirait à borner.
        # Ce n'est pas une précaution d'isolation — les classes viennent déjà
        # de `teacher_class_rows`, qui est borné — c'est ce qui rend les index
        # utilisables : tous commencent par tenant_id, et une colonne de tête
        # absente du filtre fait retomber le moteur sur un balayage complet.
        row = conn.execute(
            """SELECT COUNT(DISTINCT s.id) n, COALESCE(SUM(o.amount),0) due,
                      COALESCE((SELECT SUM(p.amount) FROM payments p JOIN obligations o2 ON o2.id=p.obligation_id
                                JOIN students s2 ON s2.id=o2.student_id
                                 WHERE s2.tenant_id=? AND s2.class_id=? AND p.status='CONFIRMED'),0) paid
               FROM students s LEFT JOIN obligations o ON o.student_id=s.id
              WHERE s.tenant_id=? AND s.class_id=? AND s.status='active'""",
            (tid, c["id"], tid, c["id"]),
        ).fetchone()
        result.append({"name": c["name"], "n": row["n"], "due": row["due"] or 0, "paid": row["paid"] or 0})
    return result


def student_overview(conn, ctx, student):
    """Analyse transversale — présence, discipline, résultats, finances — avec
    les mêmes restrictions que le dossier lui-même (school.build_dossier)."""
    tenant_id = ctx["tenant_id"]
    full_student = school.resolve_student_access(conn, ctx, student["id"])
    dossier = school.build_dossier(conn, ctx, full_student, financial)
    att = dossier["attendance"]["summary"]
    parts = [f"**{student['first_name']} {student['last_name']}** ({dossier['student']['code']}) — "
             + (f"classe {dossier['student']['class']['name']}." if dossier["student"]["class"] else "sans classe.")]
    if att["total"]:
        parts.append(f"Présence : {att['rate']} % de présence sur {att['total']} jour(s) appelé(s), {att['absent']} absence(s), {att['late']} retard(s).")
    else:
        parts.append("Présence : aucun appel enregistré pour le moment.")
    inc = dossier["discipline"]["incidents"]
    if inc:
        parts.append(f"Discipline : {len(inc)} incident(s) enregistré(s), total {dossier['discipline']['points']} points.")
    elif ctx["role"] != "parent":
        parts.append("Discipline : aucun incident enregistré.")
    b = dossier["bulletin"]
    if b["general_average_20"] is not None:
        parts.append(f"Résultats ({b['period']}) : moyenne générale {b['general_average_20']}/20" + (f", rang {b['rank']}/{b['class_size']}." if b["rank"] else "."))
    if dossier["finance"]:
        f = dossier["finance"]
        parts.append(f"Finances : {_money(f['total_paid'], f['currency'] or 'USD')} payés sur {_money(f['total_due'], f['currency'] or 'USD')}, reste {_money(f['balance'], f['currency'] or 'USD')}.")
    return _result("\n\n".join(parts), intent="student_overview",
                    actions=[{"label": "Ouvrir le dossier", "target": "eleve-dossier.html?id=" + student["id"]}])


# ===========================================================================
# PROFESSEUR (08/10/2026) — le propriétaire : « l'assistant du professeur me
# répond qu'il n'a pas assez d'informations ». Il ne connaissait que des
# questions de Direction. Voici les questions d'un enseignant, toutes
# calculées sur SES classes (school.teacher_class_rows) et en lecture seule.
# ===========================================================================
JOURS_FR = ["", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _mes_classes(conn, ctx):
    rows = school.teacher_class_rows(conn, ctx)
    out = []
    for r in rows:
        n = conn.execute("SELECT COUNT(*) n FROM students WHERE tenant_id=? AND class_id=? AND status='active'", (ctx["tenant_id"], r["id"])).fetchone()["n"]
        out.append({"id": r["id"], "name": r["name"], "n": n, "titulaire": bool(r["is_titulaire"]), "subject": r["subject"]})
    return out


def _ids_sql(ids):
    return ",".join("?" for _ in ids)


def answer_teacher(conn, ctx, low):
    """Réponses propres au professeur, ou None si la question n'en relève pas."""
    classes = _mes_classes(conn, ctx)
    if not classes:
        if re.search(r"classe|[ée]l[èe]ve|appel|devoir|horaire|cours|[ée]valuation|absent|retard", low):
            return _result("Aucune classe n'est encore rattachée à votre compte. La Direction le fait depuis **Établissement → Équipe & accès** ; vos élèves apparaîtront ensuite ici.",
                           intent="teacher_no_class")
        return None
    ids = [c["id"] for c in classes]
    today = date.today()
    t_iso = today.isoformat()

    # Mes classes / mes élèves / combien d'élèves
    if re.search(r"mes classes|mes [ée]l[èe]ves|combien.{0,20}[ée]l[èe]ves|ma classe$", low) and not re.search(r"absent|retard|pay|financ|appel|devoir|[àa] rendre|horaire|cours|[ée]valuation|examen|interro|signalement", low):
        total = sum(c["n"] for c in classes)
        rich = {"type": "table", "columns": ["Classe", "Élèves", "Rôle"],
                "rows": [[c["name"], str(c["n"]), "Titulaire" if c["titulaire"] else (c["subject"] or "Enseignant")] for c in classes]}
        return _result(f"Vous suivez **{total}** élève(s) dans **{len(classes)}** classe(s).", intent="teacher_classes", rich=rich,
                       actions=[{"label": "Ouvrir mes classes", "target": "classes.html"}])

    # L'appel du jour
    if re.search(r"\bappels?\b", low):
        lignes, manquants = [], []
        for c in classes:
            fait = conn.execute("SELECT COUNT(*) n FROM attendance WHERE tenant_id=? AND class_id=? AND date=?", (ctx["tenant_id"], c["id"], t_iso)).fetchone()["n"]
            lignes.append([c["name"], f"{fait} / {c['n']}" if fait else "Pas encore fait"])
            if not fait and c["n"]:
                manquants.append(c["name"])
        texte = ("L'appel est fait dans toutes vos classes aujourd'hui." if not manquants
                 else f"Appel **pas encore fait** aujourd'hui en : {', '.join(manquants)}.")
        return _result(texte, intent="teacher_roll", rich={"type": "table", "columns": ["Classe", "Appel du jour"], "rows": lignes},
                       actions=[{"label": "Faire l'appel", "target": "classe.html?id=" + (next((c["id"] for c in classes if c["name"] in manquants), classes[0]["id"])) + "&tab=presence"}])

    # Absents / retards d'aujourd'hui, toutes mes classes
    if re.search(r"absents?|retards?|en retard", low) and re.search(r"aujourd|ce matin|du jour", low) and not _extract_class_fragment(low):
        rows = conn.execute(f"""SELECT s.first_name, s.last_name, c.name AS class_name, a.status FROM attendance a
                                JOIN students s ON s.id=a.student_id JOIN classes c ON c.id=a.class_id
                                WHERE a.tenant_id=? AND a.date=? AND a.status IN ('absent','late') AND a.class_id IN ({_ids_sql(ids)})
                                ORDER BY c.name, s.last_name""", (ctx["tenant_id"], t_iso, *ids)).fetchall()
        if not rows:
            return _result("Aucun absent ni retard enregistré aujourd'hui dans vos classes.", intent="teacher_absents")
        rich = {"type": "table", "columns": ["Élève", "Classe", "Statut"],
                "rows": [[r["first_name"] + " " + r["last_name"], r["class_name"], "Absent" if r["status"] == "absent" else "Retard"] for r in rows[:20]]}
        na = sum(1 for r in rows if r["status"] == "absent")
        return _result(f"Aujourd'hui dans vos classes : **{na}** absent(s) et **{len(rows) - na}** retard(s).", intent="teacher_absents", rich=rich)

    # Devoirs à rendre
    if re.search(r"devoirs?|[àa] rendre", low):
        rows = conn.execute(f"""SELECT r.title, r.due_date, c.name AS class_name, r.subject FROM resources r JOIN classes c ON c.id=r.class_id
                                WHERE r.tenant_id=? AND r.kind='devoir' AND r.due_date>=? AND r.class_id IN ({_ids_sql(ids)})
                                ORDER BY r.due_date LIMIT 15""", (ctx["tenant_id"], t_iso, *ids)).fetchall()
        if not rows:
            return _result("Aucun devoir à rendre dans vos classes. Vous pouvez en publier un depuis **Livres & devoirs**.", intent="teacher_homework",
                           actions=[{"label": "Livres & devoirs", "target": "ressources.html"}])
        rich = {"type": "table", "columns": ["Devoir", "Classe", "À rendre le"],
                "rows": [[r["title"], r["class_name"], r["due_date"]] for r in rows]}
        return _result(f"**{len(rows)}** devoir(s) à rendre dans vos classes.", intent="teacher_homework", rich=rich,
                       actions=[{"label": "Livres & devoirs", "target": "ressources.html"}])

    # Emploi du temps : aujourd'hui / demain
    if re.search(r"horaire|emploi du temps|cours|programme", low):
        jour = today + timedelta(days=1) if "demain" in low else today
        wd = jour.isoweekday()
        rows = conn.execute(f"""SELECT sl.start_time, sl.end_time, sl.subject, sl.room, c.name AS class_name FROM schedule_slots sl JOIN classes c ON c.id=sl.class_id
                                WHERE sl.tenant_id=? AND sl.weekday=? AND sl.class_id IN ({_ids_sql(ids)})
                                AND (sl.teacher_user_id IS NULL OR sl.teacher_user_id=?) ORDER BY sl.start_time""",
                            (ctx["tenant_id"], wd, *ids, ctx["user_id"])).fetchall()
        quand = "demain" if "demain" in low else "aujourd'hui"
        if not rows:
            return _result(f"Aucun cours planifié {quand} ({JOURS_FR[wd]}) dans vos classes. L'horaire est saisi par la Direction.", intent="teacher_schedule")
        rich = {"type": "table", "columns": ["Heure", "Classe", "Matière", "Salle"],
                "rows": [[f"{r['start_time']}–{r['end_time']}", r["class_name"], r["subject"], r["room"] or "—"] for r in rows]}
        return _result(f"**{len(rows)}** cours {quand} ({JOURS_FR[wd]}).", intent="teacher_schedule", rich=rich)

    # Évaluations à venir
    if re.search(r"[ée]valuations?|examens?|interro", low):
        rows = conn.execute(f"""SELECT e.subject, e.date, e.start_time, e.exam_type, c.name AS class_name FROM exams e JOIN classes c ON c.id=e.class_id
                                WHERE e.tenant_id=? AND e.date>=? AND e.class_id IN ({_ids_sql(ids)}) ORDER BY e.date LIMIT 15""",
                            (ctx["tenant_id"], t_iso, *ids)).fetchall()
        if not rows:
            return _result("Aucune évaluation planifiée dans vos classes.", intent="teacher_exams")
        rich = {"type": "table", "columns": ["Date", "Classe", "Matière", "Type"],
                "rows": [[r["date"] + (" " + r["start_time"] if r["start_time"] else ""), r["class_name"], r["subject"], r["exam_type"]] for r in rows]}
        return _result(f"**{len(rows)}** évaluation(s) à venir dans vos classes.", intent="teacher_exams", rich=rich)

    # Mes signalements
    if re.search(r"signalements?", low):
        rows = conn.execute("""SELECT r.status, r.description, r.occurred_at, s.first_name, s.last_name FROM incident_reports r JOIN students s ON s.id=r.student_id
                               WHERE r.tenant_id=? AND r.reported_by=? ORDER BY r.created_at DESC LIMIT 15""", (ctx["tenant_id"], ctx["user_id"])).fetchall()
        if not rows:
            return _result("Vous n'avez fait aucun signalement. Depuis la page d'une classe, le bouton **Signaler** transmet un fait au Directeur des disciplines.", intent="teacher_reports")
        etat = {"pending": "En attente du DD", "qualified": "Retenu", "dismissed": "Classé"}
        rich = {"type": "table", "columns": ["Date", "Élève", "Fait", "Suite"],
                "rows": [[r["occurred_at"], r["first_name"] + " " + r["last_name"], r["description"][:60], etat.get(r["status"], r["status"])] for r in rows]}
        attente = sum(1 for r in rows if r["status"] == "pending")
        return _result(f"**{len(rows)}** signalement(s), dont **{attente}** en attente du Directeur des disciplines.", intent="teacher_reports", rich=rich)
    return None


# Questions qu'on sait traiter, par rôle — proposées quand une question
# n'est pas comprise, plutôt qu'un simple « je ne sais pas ».
EXEMPLES = {
    "professeur": ["Quels élèves sont absents aujourd'hui ?", "L'appel est-il fait dans mes classes ?", "Quels devoirs sont à rendre ?",
                   "Quels sont mes cours aujourd'hui ?", "Quelles évaluations arrivent ?", "Où en sont mes signalements ?"],
    "directeur": ["Analyse ma situation financière", "Quels sont les plus gros impayés ?", "Quels élèves ont plusieurs absences ?", "Montre-moi les incidents récents"],
    "discipline": ["Montre-moi les incidents récents", "Quels élèves ont plusieurs retards ?", "Combien d'élèves de la 7e sont absents aujourd'hui ?"],
    "parent": ["Quelle est la situation de mes enfants ?", "Que reste-t-il à payer ?", "Montre-moi le reçu de mon enfant"],
}


def answer_question(conn, ctx, message, previous_intent=None):
    """Point d'entrée unique. Retourne un dict {text, rich, actions, intent, refused}."""
    text = (message or "").strip()
    if not text:
        return _result("Posez-moi une question sur votre établissement.", intent="empty")

    write_entity = _is_write_intent(text)
    if write_entity:
        return _result(REFUSAL_BY_ENTITY.get(write_entity, GENERIC_REFUSAL), intent="refused", refused=True)
    # Filet générique : un verbe d'action sans nom de domaine reconnu reste suspect.
    if re.search(ACTION_VERBS, text, re.I) and not re.search(r"analys|explique|montre|combien|quel", text, re.I):
        return _result(GENERIC_REFUSAL, intent="refused", refused=True)

    low = text.lower()

    # --- Navigation ---
    nav_match = re.search(r"o[uù].{0,15}(voir|trouver|se trouve)", low)
    if nav_match:
        for label, path in [("paiements", "paiements.html"), ("finance", "finance.html"),
                             ("élèves", "eleves.html"), ("classes", "classes.html"),
                             ("établissement", "etablissement.html"), ("rapports", "rapports.html")]:
            if label.rstrip("s") in low or label in low:
                # Les rapports ne sont plus une entrée du menu (08/10/2026) :
                # ils vivent dans Établissement → onglet Rapports.
                ou = "dans **Établissement**, onglet Rapports" if label == "rapports" else f"dans **{label.capitalize()}**, dans le menu principal"
                return _result(f"Vous trouverez cela {ou}.",
                                intent="navigate", actions=[{"label": "Ouvrir " + label.capitalize(), "target": path}])

    # --- Explications produit (ne dépendent d'aucune permission) ---
    if re.search(r"import(er)?\b.*(excel|fonctionne)|comment.*import", low):
        return _result(FEATURE_EXPLANATIONS["import"], intent="explain_import")
    if re.search(r"diff[ée]rence.*(finance|paiement)", low):
        return _result(FEATURE_EXPLANATIONS["finance_vs_paiements"], intent="explain_finance_vs_paiements")
    if re.search(r"invitation|comment.*(inviter|rejoindre)", low):
        return _result(FEATURE_EXPLANATIONS["invitations"], intent="explain_invitations")

    if ctx["role"] == "professeur":
        prof = answer_teacher(conn, ctx, low)
        if prof:
            return prof

    # --- Présences (données centrales, périmètre du rôle) ---
    absent_class = None
    if re.search(r"absents?|pr[ée]sents?|en retard|retards?", low) and re.search(r"combien|quels?|qui|liste", low) and ctx["role"] != "parent":
        absent_class = _extract_class_fragment(low)
    if absent_class:
        rows = get_class_attendance_today(conn, ctx, absent_class)
        if rows is None:
            return _result(f"Aucune classe visible depuis votre espace ne correspond à « {absent_class} ».", intent="attendance_class")
        cls, recs = rows
        absent = [r for r in recs if r["status"] == "absent"]
        late = [r for r in recs if r["status"] == "late"]
        if not recs:
            return _result(f"L'appel de **{cls['name']}** n'a pas encore été enregistré aujourd'hui.", intent="attendance_class",
                            actions=[{"label": "Ouvrir la classe", "target": "classe.html?id=" + cls["id"]}])
        rich = {"type": "table", "columns": ["Élève", "Statut"],
                "rows": [[r["first_name"] + " " + r["last_name"], "Absent" if r["status"] == "absent" else "Retard"] for r in absent + late]} if (absent or late) else None
        return _result(f"Aujourd'hui en **{cls['name']}** : **{len(absent)}** absent(s), **{len(late)}** retard(s) sur {len(recs)} élèves appelés.",
                        intent="attendance_class", rich=rich, actions=[{"label": "Ouvrir la classe", "target": "classe.html?id=" + cls["id"]}])

    late_repeat = re.search(r"(?:quels?|qui).{0,40}(?:plusieurs|beaucoup de|des|trop de) (?:retards?|absences?)", low)
    if late_repeat and ctx["role"] != "parent":
        kind = "late" if "retard" in low else "absent"
        rows = get_students_repeated(conn, ctx, kind, min_count=2)
        label = "retards" if kind == "late" else "absences"
        if not rows:
            return _result(f"Aucun élève de votre périmètre ne cumule plusieurs {label} ce mois-ci.", intent="attendance_repeat")
        rich = {"type": "table", "columns": ["Élève", "Classe", label.capitalize()],
                "rows": [[r["first_name"] + " " + r["last_name"], r["class_name"] or "—", str(r["n"])] for r in rows[:15]]}
        return _result(f"**{len(rows)} élève(s)** cumulent au moins 2 {label} sur les 30 derniers jours.", intent="attendance_repeat", rich=rich)

    student_att = re.search(r"combien (?:d.)?(?:absences?|retards?).{0,20}\b([a-zàâäéèêëïîôöùûüç]{2,}(?:\s+[a-zàâäéèêëïîôöùûüç-]{2,})?)\s*(?:a|à|-t-il|-t-elle|ce mois|$)", low)
    if student_att:
        student = find_visible_student(conn, ctx, student_att.group(1))
        if student:
            kind = "late" if "retard" in low else "absent"
            month_start = date.today().replace(day=1).isoformat()
            n = conn.execute("SELECT COUNT(*) n FROM attendance WHERE tenant_id=? AND student_id=? AND status=? AND date>=?",
                             (ctx["tenant_id"], student["id"], kind, month_start)).fetchone()["n"]
            label = "retard(s)" if kind == "late" else "absence(s)"
            return _result(f"{student['first_name']} {student['last_name']} compte **{n}** {label} ce mois-ci.", intent="attendance_student",
                            actions=[{"label": "Voir le dossier", "target": f"eleve-dossier.html?id={student['id']}&tab=presence"}])

    # --- Reçus ---
    receipt_match = re.search(r"re[çc]us?.{0,20}(?:de|pour) ([a-zàâäéèêëïîôöùûüç]{2,}(?:\s+[a-zàâäéèêëïîôöùûüç-]{2,})?)", low)
    if receipt_match and ctx["role"] != "discipline" and school.finance_visible(conn, ctx):
        student = find_visible_student(conn, ctx, receipt_match.group(1))
        if student:
            rows = school.receipts_for_student(conn, ctx["tenant_id"], student["id"])
            if not rows:
                return _result(f"Aucun reçu n'a encore été émis pour {student['first_name']} {student['last_name']}.", intent="receipts_student")
            rich = {"type": "table", "columns": ["Reçu", "Montant", "Motif"],
                    "rows": [[r["number"], _money(r["amount"], r["currency"]), r["label"]] for r in rows[:10]]}
            return _result(f"**{len(rows)} reçu(s)** pour {student['first_name']} {student['last_name']}.", intent="receipts_student", rich=rich,
                            actions=[{"label": "Ouvrir le dossier", "target": f"eleve-dossier.html?id={student['id']}&tab=recus"}])

    # --- Situation d'un élève (analyse transversale du dossier) ---
    analyse_match = re.search(r"(?:analys|situation|r[ée]sum)\w*\s+(?:la situation\s+)?(?:de|d')\s*([a-zàâäéèêëïîôöùûüç]{2,}(?:\s+[a-zàâäéèêëïîôöùûüç-]{2,})?)", low)
    if analyse_match and not re.search(r"mes enfants|[ée]tablissement|classe|financi", low):
        student = find_visible_student(conn, ctx, analyse_match.group(1))
        if student:
            return student_overview(conn, ctx, student)

    # --- Incidents d'un périmètre ---
    if re.search(r"incidents?|discipline", low) and re.search(r"combien|quels?|liste|montre|r[ée]cents?", low) and ctx["role"] in ("directeur", "discipline", "professeur"):
        rows = get_recent_incidents(conn, ctx)
        if not rows:
            return _result("Aucun incident enregistré dans votre périmètre sur les 30 derniers jours.", intent="incidents_recent")
        rich = {"type": "table", "columns": ["Date", "Élève", "Classe", "Incident"],
                "rows": [[r["occurred_at"], r["first_name"] + " " + r["last_name"], r["class_name"] or "—", r["title"]] for r in rows[:10]]}
        return _result(f"**{len(rows)} incident(s)** sur les 30 derniers jours.", intent="incidents_recent", rich=rich,
                        actions=[{"label": "Ouvrir Discipline", "target": "discipline.html"}] if ctx["role"] != "professeur" else [])

    # --- Situation financière de MA classe (professeur autorisé) ---
    if ctx["role"] == "professeur" and re.search(r"financi|impay|pay[ée]", low) and re.search(r"ma classe|mes classes|de la classe", low):
        if not school.finance_visible(conn, ctx):
            return _result("Votre établissement n'a pas activé la visibilité financière pour les professeurs — je n'ai pas accès à ces données depuis votre espace.",
                            intent="denied_financial_professeur")
        rows = get_class_finance_for_teacher(conn, ctx)
        if not rows:
            return _result("Aucune classe rattachée à votre compte pour le moment.", intent="class_finance")
        rich = {"type": "table", "columns": ["Classe", "Élèves", "Attendu", "Encaissé", "Restant"],
                "rows": [[r["name"], str(r["n"]), _money(r["due"]), _money(r["paid"]), _money(r["due"] - r["paid"])] for r in rows]}
        return _result("Situation financière de vos classes.", intent="class_finance", rich=rich)

    # --- Comptage ---
    if re.search(r"combien.*[ée]l[èe]ves?", low) and not re.search(r"pay[ée]|impay|absent|retard|pr[ée]sent", low):
        n = get_student_count(conn, ctx)
        if ctx["role"] == "parent":
            return _result(f"Vous avez **{n}** enfant(s) suivi(s) dans Klassio." if n else
                            "Aucun enfant n'est encore associé à votre compte.", intent="count_students")
        qui = "Votre établissement compte" if ctx["role"] == "directeur" else "Votre périmètre compte"
        return _result(f"{qui} actuellement **{n}** élèves.", intent="count_students",
                        actions=[{"label": "Voir les élèves", "target": "eleves.html"}])

    if re.search(r"combien.*classes?", low):
        n = get_class_count(conn, ctx)
        return _result(f"Votre établissement compte **{n}** classes.", intent="count_classes",
                        actions=[{"label": "Voir les classes", "target": "classes.html"}])

    # --- Financier (établissement) : jamais pour un parent ---
    financial_global = re.search(r"encaiss[ée]|impay[ée]|situation financi[èe]re|r[ée]sum[ée]|taux d.encaissement|pourcentage", low)
    if financial_global and ctx["role"] == "parent" and not re.search(r"mes enfants|pour \w|de mon enfant", low):
        return _result("Je n'ai pas accès aux données financières globales de l'établissement depuis votre espace.",
                        intent="denied_financial_global", refused=False)
    if financial_global and ctx["role"] in ("professeur", "discipline"):
        return _result("Je n'ai pas accès aux données financières globales de l'établissement depuis votre espace.",
                        intent="denied_financial_professeur", refused=False)

    # Le TAUX avant le MONTANT (trouvé le 09/10/2026) : « encaissement »
    # commence par « encaisse », et la branche du montant répondait « encaissé
    # 0 $ ce mois-ci » à qui demandait un pourcentage. test_assistant_taux.
    if re.search(r"taux d.encaissement|pourcentage", low):
        s = get_tenant_financial_summary(conn, ctx)
        rate = round((s["total_paid"] / s["total_due"]) * 100) if s["total_due"] else 0
        return _result(f"Le taux d'encaissement est de **{rate} %**.\n\n{_money(s['total_paid'])} encaissés sur {_money(s['total_due'])} attendus.",
                        intent="collection_rate")

    if re.search(r"encaiss[ée]", low):
        period = "this_month"
        if re.search(r"mois dernier|mois pr[ée]c[ée]dent", low):
            period = "last_month"
        elif previous_intent == "collected_this_month" and re.search(r"mois dernier|et (le )?avant|pr[ée]c[ée]dent", low):
            period = "last_month"
        offset = -1 if period == "last_month" else 0
        start, end = month_bounds(offset)
        total = get_period_collections(conn, ctx, start, end)
        label = "le mois dernier" if period == "last_month" else "ce mois-ci"
        return _result(f"Votre établissement a encaissé **{_money(total)}** {label}.",
                        intent="collected_last_month" if period == "last_month" else "collected_this_month",
                        actions=[{"label": "Voir Paiements", "target": "paiements.html"}])

    if re.search(r"situation financi[èe]re|r[ée]sum[ée].*[ée]tablissement|r[ée]sume mon [ée]tablissement", low):
        s = get_tenant_financial_summary(conn, ctx)
        rate = round((s["total_paid"] / s["total_due"]) * 100) if s["total_due"] else 0
        text_out = (f"**{_money(s['total_paid'])}** encaissés sur **{_money(s['total_due'])}** attendus "
                    f"— un taux d'encaissement de **{rate} %**. Il reste **{_money(s['outstanding'])}** à recevoir.")
        return _result(text_out, intent="financial_summary",
                        rich={"type": "stats", "items": [
                            {"label": "Attendu", "value": _money(s["total_due"])},
                            {"label": "Encaissé", "value": _money(s["total_paid"])},
                            {"label": "Restant", "value": _money(s["outstanding"])},
                        ]}, actions=[{"label": "Voir Finance", "target": "finance.html"}])

    if re.search(r"plus gros.{0,10}impay|plus grosses?.{0,10}dettes?|impay[ée]s? les plus", low):
        rows = get_biggest_unpaid(conn, ctx, 5)
        if not rows:
            return _result("Aucun impayé enregistré pour le moment.", intent="biggest_unpaid")
        rich = {"type": "table", "columns": ["Élève", "Classe", "Solde"],
                "rows": [[r["first_name"] + " " + r["last_name"], r["class_name"] or "—", _money(r["balance"])] for r in rows]}
        return _result("**Les plus gros impayés**", intent="biggest_unpaid", rich=rich,
                        actions=[{"label": "Voir les impayés", "target": "finance.html"}])

    if re.search(r"[ée]l[èe]ves?.{0,15}sans (aucun )?paiement|n.?ont? (encore )?rien pay[ée]|aucun paiement", low):
        rows = get_students_without_payment(conn, ctx)
        if not rows:
            return _result("Tous les élèves ont au moins un paiement enregistré.", intent="students_no_payment")
        rich = {"type": "table", "columns": ["Élève", "Classe", "Dû"],
                "rows": [[r["first_name"] + " " + r["last_name"], r["class_name"] or "—", _money(r["total_due"])] for r in rows[:10]]}
        more = f" (+{len(rows)-10} autres)" if len(rows) > 10 else ""
        return _result(f"**{len(rows)} élève(s)** n'ont encore effectué aucun paiement{more}.",
                        intent="students_no_payment", rich=rich,
                        actions=[{"label": "Voir les élèves", "target": "eleves.html"}])

    # --- Élèves d'une classe ---
    class_match = re.search(r"[ée]l[èe]ves? de (?:la )?(?:classe )?([a-zàâäéèêëïîôöùûüç0-9\s]+?)[\.\?!]?$", low)
    if class_match and ctx["role"] != "parent":
        class_name = class_match.group(1).strip()
        rows = get_students_by_class(conn, ctx, class_name)
        if not rows:
            return _result(f"Aucun élève trouvé pour « {class_name} ».", intent="students_by_class")
        rich = {"type": "table", "columns": ["Élève", "Classe"],
                "rows": [[r["first_name"] + " " + r["last_name"], r["class_name"]] for r in rows]}
        return _result(f"**{len(rows)} élève(s)** en {rows[0]['class_name']}.", intent="students_by_class", rich=rich,
                        actions=[{"label": "Voir la classe", "target": "eleves.html?class=" + rows[0]["class_name"]}])

    # --- Parent : situation d'un enfant précis ---
    if ctx["role"] == "parent":
        child_match = re.search(r"(?:reste.{0,15}payer pour|solde de|situation de) ([a-zàâäéèêëïîôöùûüç\s-]+)", low)
        child = None
        if child_match:
            child = _find_own_child(conn, ctx, child_match.group(1))
        elif re.search(r"mes enfants|situation de mes enfants", low):
            ids = _own_children_ids(conn, ctx)
            if len(ids) == 1:
                child = conn.execute("SELECT * FROM students WHERE id=?", (ids[0],)).fetchone()
        if child:
            summary = financial.financial_summary(conn, ctx["tenant_id"], child["id"])
            return _result(f"Il reste **{_money(summary['balance'])}** à payer pour {child['first_name']} {child['last_name']}.",
                            intent="child_balance", actions=[{"label": "Voir le dossier", "target": "eleve-dossier.html?id=" + child["id"]}])
        if re.search(r"mes enfants|situation", low):
            ids = _own_children_ids(conn, ctx)
            if not ids:
                return _result("Aucun enfant n'est encore associé à votre compte.", intent="my_children")
            rich = {"type": "table", "columns": ["Enfant", "Classe", "Solde"], "rows": []}
            for sid in ids:
                s = conn.execute("SELECT s.*, c.name as class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id=?", (sid,)).fetchone()
                summary = financial.financial_summary(conn, ctx["tenant_id"], sid)
                rich["rows"].append([s["first_name"] + " " + s["last_name"], s["class_name"] or "—", _money(summary["balance"])])
            return _result("Voici la situation de vos enfants.", intent="my_children", rich=rich)

    # --- Recherche d'un élève par nom (fallback avant l'échec) ---
    name_match = re.search(r"trouve[rz]?\s+([a-zàâäéèêëïîôöùûüç\s-]{3,})$", low) or \
                 re.search(r"montre[- ]?moi\s+([a-zàâäéèêëïîôöùûüç\s-]{3,})$", low)
    if name_match and ctx["role"] != "parent":
        rows = search_students(conn, ctx, name_match.group(1).strip())
        if rows:
            rich = {"type": "table", "columns": ["Élève", "Classe"],
                    "rows": [[r["first_name"] + " " + r["last_name"], r["class_name"] or "—"] for r in rows[:10]]}
            return _result(f"**{len(rows)} résultat(s)** trouvé(s).", intent="search_student", rich=rich)

    # L'aveu reste (test_api.test_20 : jamais de réponse inventée) ; il est
    # désormais suivi de ce que l'assistant sait vraiment faire pour ce rôle.
    return _result("Je n'ai pas suffisamment d'informations pour répondre à cette question. Voici ce que je peux vous dire tout de suite :",
                    intent="fallback", rich={"type": "suggestions", "items": EXEMPLES.get(ctx["role"], EXEMPLES["parent"])})


def _result(text, intent, rich=None, actions=None, refused=False):
    return {"text": text, "intent": intent, "rich": rich, "actions": actions or [], "refused": refused}
