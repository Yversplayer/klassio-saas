"""KLASSIO backend — School Core : l'élève au centre.

Ce module est LA source de vérité des périmètres d'accès aux données
scolaires. Toute route qui touche un élève, une classe, une présence, un
incident ou une note passe par ces fonctions — jamais par une condition
frontend, jamais par un tenant_id/role envoyé par le client.

    Direction   : tout l'établissement.
    DD          : classes du cycle secondaire (configurable classe par classe).
    Professeur  : classes auxquelles il est explicitement rattaché
                  (class_teachers) ; titulaire = flag explicite, jamais implicite.
    Parent      : uniquement les élèves liés à son compte (student_guardians).
"""
import json
import re
import secrets
import time
from datetime import date

from security import new_id

# Caractères sans ambiguïté visuelle (pas de 0/O, 1/I/L) — cet identifiant
# est lu à voix haute, recopié sur WhatsApp, tapé dans une recherche.
_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


STAFF_ROLE_PREFIXES = {"professeur": "TCH", "discipline": "DIS", "directeur": "DIR"}


def generate_staff_code(conn, tenant_id, role):
    """Identifiant interne d'un membre du personnel : TCH-8K4P-72XM.

    Généré par le SERVEUR, jamais choisi par l'utilisateur, et distinct du
    compte de connexion : un enseignant peut changer de numéro ou d'e-mail,
    son identifiant dans l'établissement ne bouge pas. Ce n'est pas un secret —
    il identifie un profil, l'authentification reste ailleurs.

    Même alphabet sans ambiguïté visuelle que les identifiants élèves : ce code
    est lu à voix haute et recopié à la main.
    """
    prefix = STAFF_ROLE_PREFIXES.get(role, "STF")
    part = lambda: "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
    for _ in range(50):
        code = f"{prefix}-{part()}-{part()}"
        if not conn.execute("SELECT 1 FROM memberships WHERE tenant_id = ? AND staff_code = ?",
                            (tenant_id, code)).fetchone():
            return code
    raise RuntimeError("Impossible de générer un identifiant de personnel unique.")


def generate_student_code(conn, tenant_id):
    """Identifiant élève unique par établissement. Ce n'est PAS un secret ni
    un mot de passe : il identifie un dossier, l'authentification reste
    séparée. Format choisi par la Direction (tenants.code_prefix / code_mode) :
      - random     : PREFIX-XXXX-XXXX (défaut STU-…) — impossible à deviner
      - sequential : PREFIX-0001, 0002… — lisible, dans l'ordre d'arrivée
    """
    row = conn.execute("SELECT code_prefix, code_mode FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    prefix = (row["code_prefix"] if row and row["code_prefix"] else "STU").strip().upper()
    mode = row["code_mode"] if row and row["code_mode"] else "random"
    if mode == "sequential":
        n = conn.execute("SELECT COUNT(*) AS n FROM students WHERE tenant_id = ?", (tenant_id,)).fetchone()["n"]
        for i in range(n + 1, n + 5000):
            code = f"{prefix}-{i:04d}"
            if not conn.execute("SELECT 1 FROM students WHERE tenant_id = ? AND code = ?", (tenant_id, code)).fetchone():
                return code
        raise RuntimeError("Impossible de générer un identifiant élève unique.")
    for _ in range(50):
        part = lambda: "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
        code = f"{prefix}-{part()}-{part()}"
        exists = conn.execute("SELECT 1 FROM students WHERE tenant_id = ? AND code = ?", (tenant_id, code)).fetchone()
        if not exists:
            return code
    raise RuntimeError("Impossible de générer un identifiant élève unique.")


# ---------------------------------------------------------------------------
# Portail par établissement : adresse (slug) et habillage
# ---------------------------------------------------------------------------

_SLUG_MAP = str.maketrans("àâäáãåçéèêëíìîïñóòôöõúùûüýÿ", "aaaaaaceeeeiiiinooooouuuuyy")


def slugify(name):
    base = (name or "").lower().translate(_SLUG_MAP)
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base[:40] or "ecole"


def unique_slug(conn, name, exclude_tenant_id=None):
    base = slugify(name)
    slug = base
    i = 2
    while True:
        row = conn.execute("SELECT id FROM tenants WHERE slug = ?", (slug,)).fetchone()
        if not row or row["id"] == exclude_tenant_id:
            return slug
        slug = f"{base}-{i}"
        i += 1


def branding(tenant_row):
    """Ce que le portail public affiche — jamais de donnée métier ici."""
    if not tenant_row:
        return None
    keys = tenant_row.keys() if hasattr(tenant_row, "keys") else tenant_row
    get = lambda k: tenant_row[k] if k in keys else None
    return {
        "slug": get("slug"), "name": get("name"), "tagline": get("tagline"),
        "logo_data": get("logo_data"), "cover_data": get("cover_data"),
        "accent_color": get("accent_color"), "show_flag": bool(get("show_flag")),
    }


def hidden_email(email):
    """Un compte créé avec un téléphone seul porte un email technique
    (tel+<numéro>@klassio.invalid) parce que la colonne est NOT NULL — il
    n'est jamais affiché ni utilisable pour se connecter par email."""
    return bool(email) and email.endswith("@klassio.invalid")


def display_email(email):
    return None if hidden_email(email) else email


def infer_cycle(level, name=""):
    """Devine le cycle d'une classe à partir de son niveau — révisable par la
    Direction depuis la page Classes (jamais figé). Convention RDC : primaire
    1re→6e, secondaire à partir de la 7e (ou humanités 1re→4e sur libellé)."""
    text = f"{level or ''} {name or ''}".lower()
    if re.search(r"matern|pr[ée]-?scol|jardin", text):
        return "maternelle"
    if re.search(r"humanit|secondaire|\b(7|8)e?\b|\b[1-4](?:re|e|ème)?\s*(?:sc|lit|péd|ped|com|tech)", text):
        return "secondaire"
    m = re.search(r"\b(\d{1,2})", text)
    if m:
        n = int(m.group(1))
        return "primaire" if n <= 6 else "secondaire"
    if re.search(r"primaire", text):
        return "primaire"
    return "secondaire"


def today_iso():
    return date.today().isoformat()


# ---------------------------------------------------------------------------
# Réglages d'établissement (visibilité financière des professeurs, etc.)
# ---------------------------------------------------------------------------

SETTINGS_DEFAULTS = {
    "currency": "USD", "teacher_sees_finance": 0, "parent_notify_attendance": 1,
    "parent_notify_incidents": 0, "parent_notify_grades": 1, "discipline_alert_threshold": -10,
    "school_phone": None, "school_address": None, "school_email": None,
    # Lots 2–5
    "discipline_capital": 100,          # capital de points de conduite en début d'année
    "conduct_scale": None,              # JSON [[min_restant, "Libellé"], …] — voir DEFAULT_CONDUCT_SCALE
    "pass_threshold": 50.0,             # % pour « admis » en fin d'année
    "store_cutoff_time": "20:00",       # commande avant cette heure → retrait le lendemain
    "parent_notify_present": 1,         # notification quotidienne « votre enfant est à l'école »
    "exam_period_starts": None, "exam_period_ends": None,
    "teacher_contact_visible": 0,       # le téléphone des enseignants est-il visible des parents ?
    # Politique de diffusion des résultats — CONFIGURABLE, jamais écrite en dur.
    # JSON : {"mode": "always" | "balance", "max_balance": 0, "exempt_class_ids": []}
    #   always  : les résultats proclamés sont accessibles à tous les parents autorisés.
    #   balance : accessibles si le solde de l'élève ne dépasse pas max_balance.
    # `None` vaut "always" : une école qui n'a rien configuré ne retient les
    # bulletins de personne.
    #
    # Cette politique gouverne la DIFFUSION, jamais le dossier : un résultat non
    # diffusé existe, reste au dossier de l'élève, et reste visible du personnel.
    "results_policy": None,
}
DEFAULT_CONDUCT_SCALE = [[90, "Très bien"], [75, "Bien"], [60, "Assez bien"], [40, "Passable"], [0, "Insuffisant"]]
BOOL_SETTINGS = {"teacher_sees_finance", "parent_notify_attendance", "parent_notify_incidents", "parent_notify_grades",
                 "parent_notify_present", "teacher_contact_visible"}
INT_SETTINGS = {"discipline_alert_threshold", "discipline_capital"}


def get_settings(conn, tenant_id):
    row = conn.execute("SELECT * FROM tenant_settings WHERE tenant_id = ?", (tenant_id,)).fetchone()
    if not row:
        return dict(SETTINGS_DEFAULTS)
    d = dict(SETTINGS_DEFAULTS)
    for k in SETTINGS_DEFAULTS:
        if k in row.keys() and row[k] is not None:
            d[k] = row[k]
    return d


def save_settings(conn, tenant_id, patch):
    current = get_settings(conn, tenant_id)
    for key in SETTINGS_DEFAULTS:
        if key in patch:
            current[key] = patch[key]
    cols = list(SETTINGS_DEFAULTS.keys())
    values = []
    for k in cols:
        v = current[k]
        if k in BOOL_SETTINGS:
            v = int(bool(v))
        elif k in INT_SETTINGS:
            v = int(v)
        values.append(v)
    conn.execute(
        f"""INSERT INTO tenant_settings (tenant_id, {', '.join(cols)}, updated_at) VALUES (?, {', '.join('?' for _ in cols)}, ?)
            ON CONFLICT(tenant_id) DO UPDATE SET {', '.join(f'{c}=excluded.{c}' for c in cols)}, updated_at=excluded.updated_at""",
        [tenant_id, *values, str(time.time())],
    )
    conn.commit()
    return current


def conduct_scale(settings):
    import json
    raw = settings.get("conduct_scale")
    if raw:
        try:
            scale = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(scale, list) and scale:
                return sorted([[int(a), str(b)] for a, b in scale], key=lambda x: -x[0])
        except (ValueError, TypeError):
            pass
    return [list(x) for x in DEFAULT_CONDUCT_SCALE]


def conduct_label(remaining, capital, scale):
    pct = round(remaining / capital * 100) if capital else 0
    for floor, label in scale:
        if pct >= floor:
            return label
    return scale[-1][1] if scale else "—"


# ---------------------------------------------------------------------------
# Périmètres — classes visibles / élèves visibles selon le rôle
# ---------------------------------------------------------------------------

def discipline_scope_cycles(conn, ctx):
    """Cycles couverts par ce DD (memberships.scope_cycles, JSON) — par défaut
    le secondaire. Un DD du primaire et un DD du secondaire peuvent coexister."""
    import json
    row = conn.execute("SELECT scope_cycles FROM memberships WHERE tenant_id=? AND user_id=? AND role='discipline'",
                       (ctx["tenant_id"], ctx["user_id"])).fetchone()
    if row and row["scope_cycles"]:
        try:
            cycles = [c for c in json.loads(row["scope_cycles"]) if c in ("maternelle", "primaire", "secondaire")]
            if cycles:
                return cycles
        except ValueError:
            pass
    return ["secondaire"]


def teacher_class_rows(conn, ctx):
    return conn.execute(
        """SELECT c.*, ct.subject, ct.is_titulaire FROM class_teachers ct
           JOIN classes c ON c.id = ct.class_id
           WHERE ct.tenant_id = ? AND ct.user_id = ? ORDER BY c.name""",
        (ctx["tenant_id"], ctx["user_id"]),
    ).fetchall()


def teacher_class_ids(conn, ctx):
    return [r["id"] for r in teacher_class_rows(conn, ctx)]


def is_titulaire_of(conn, ctx, class_id):
    row = conn.execute(
        "SELECT is_titulaire FROM class_teachers WHERE tenant_id=? AND user_id=? AND class_id=?",
        (ctx["tenant_id"], ctx["user_id"], class_id),
    ).fetchone()
    return bool(row and row["is_titulaire"])


def own_children_ids(conn, ctx):
    rows = conn.execute(
        """SELECT sg.student_id FROM student_guardians sg JOIN guardians g ON g.id = sg.guardian_id
           WHERE sg.tenant_id = ? AND g.user_id = ?""",
        (ctx["tenant_id"], ctx["user_id"]),
    ).fetchall()
    return [r["student_id"] for r in rows]


def visible_class_ids(conn, ctx):
    """None = toutes les classes du tenant (Direction). Liste sinon."""
    role = ctx["role"]
    if role == "directeur":
        return None
    if role == "discipline":
        cycles = discipline_scope_cycles(conn, ctx)
        placeholders = ",".join("?" for _ in cycles)
        rows = conn.execute(f"SELECT id FROM classes WHERE tenant_id=? AND cycle IN ({placeholders})", (ctx["tenant_id"], *cycles)).fetchall()
        return [r["id"] for r in rows]
    if role == "professeur":
        return teacher_class_ids(conn, ctx)
    if role == "parent":
        ids = own_children_ids(conn, ctx)
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(f"SELECT DISTINCT class_id FROM students WHERE class_id IS NOT NULL AND id IN ({placeholders})", tuple(ids)).fetchall()
        return [r["class_id"] for r in rows]
    return []


def can_access_class(conn, ctx, class_id):
    cls = conn.execute("SELECT * FROM classes WHERE id=? AND tenant_id=?", (class_id, ctx["tenant_id"])).fetchone()
    if not cls:
        return None
    allowed = visible_class_ids(conn, ctx)
    if allowed is None or class_id in allowed:
        return cls
    return None


def can_manage_class_attendance(conn, ctx, class_id):
    """Direction, DD (secondaire) ou professeur RATTACHÉ à cette classe."""
    if ctx["role"] not in ("directeur", "discipline", "professeur"):
        return False
    return can_access_class(conn, ctx, class_id) is not None


def resolve_student_access(conn, ctx, student_id):
    """Retourne la ligne élève si l'utilisateur courant peut voir CE dossier,
    sinon None. Unique point de décision — utilisé par toutes les routes."""
    student = conn.execute(
        """SELECT s.*, c.name AS class_name, c.level AS class_level, c.cycle AS class_cycle
           FROM students s LEFT JOIN classes c ON c.id = s.class_id
           WHERE s.id = ? AND s.tenant_id = ?""",
        (student_id, ctx["tenant_id"]),
    ).fetchone()
    if not student:
        return None
    role = ctx["role"]
    if role == "directeur":
        return student
    if role == "discipline":
        return student if student["class_cycle"] in discipline_scope_cycles(conn, ctx) else None
    if role == "professeur":
        return student if student["class_id"] and student["class_id"] in teacher_class_ids(conn, ctx) else None
    if role == "parent":
        return student if student_id in own_children_ids(conn, ctx) else None
    return None


def students_where_clause(conn, ctx):
    """(clause SQL sur alias s, params) restreignant la liste d'élèves au
    périmètre du rôle. Retourne (None, None) si aucun élève n'est visible."""
    role = ctx["role"]
    if role == "directeur":
        return "s.tenant_id = ?", (ctx["tenant_id"],)
    if role == "parent":
        ids = own_children_ids(conn, ctx)
        if not ids:
            return None, None
        return f"s.tenant_id = ? AND s.id IN ({','.join('?' for _ in ids)})", (ctx["tenant_id"], *ids)
    class_ids = visible_class_ids(conn, ctx)
    if not class_ids:
        return None, None
    return f"s.tenant_id = ? AND s.class_id IN ({','.join('?' for _ in class_ids)})", (ctx["tenant_id"], *class_ids)


def finance_visible(conn, ctx):
    """Le professeur ne voit la situation financière de sa classe que si la
    Direction l'a explicitement autorisé (tenant_settings.teacher_sees_finance)."""
    if ctx["role"] in ("directeur", "parent"):
        return True
    if ctx["role"] == "professeur":
        return bool(get_settings(conn, ctx["tenant_id"])["teacher_sees_finance"])
    return False


# ---------------------------------------------------------------------------
# Lectures du dossier central
# ---------------------------------------------------------------------------

def guardians_of(conn, tenant_id, student_id):
    rows = conn.execute(
        """SELECT g.id, g.first_name, g.last_name, g.phone, g.email, sg.relationship,
                  CASE WHEN g.user_id IS NULL THEN 0 ELSE 1 END AS has_account
           FROM student_guardians sg JOIN guardians g ON g.id = sg.guardian_id
           WHERE sg.tenant_id = ? AND sg.student_id = ?""",
        (tenant_id, student_id),
    ).fetchall()
    return [dict(r) for r in rows]


def attendance_summary(conn, tenant_id, student_id, since=None):
    params = [tenant_id, student_id]
    where = "tenant_id = ? AND student_id = ?"
    if since:
        where += " AND date >= ?"
        params.append(since)
    row = conn.execute(
        f"""SELECT SUM(CASE WHEN status='present' THEN 1 ELSE 0 END) AS present, SUM(CASE WHEN status='absent' THEN 1 ELSE 0 END) AS absent,
                   SUM(CASE WHEN status='late' THEN 1 ELSE 0 END) AS late, SUM(CASE WHEN status='excused' THEN 1 ELSE 0 END) AS excused, COUNT(*) AS total
            FROM attendance WHERE {where}""",
        params,
    ).fetchone()
    total = row["total"] or 0
    present_like = (row["present"] or 0) + (row["late"] or 0)
    return {
        "present": row["present"] or 0, "absent": row["absent"] or 0,
        "late": row["late"] or 0, "excused": row["excused"] or 0, "total": total,
        "rate": round(present_like / total * 100) if total else None,
    }


def attendance_recent(conn, tenant_id, student_id, limit=30):
    rows = conn.execute(
        "SELECT date, status, note FROM attendance WHERE tenant_id=? AND student_id=? ORDER BY date DESC LIMIT ?",
        (tenant_id, student_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def attendance_today(conn, tenant_id, student_id):
    row = conn.execute("SELECT status, note FROM attendance WHERE tenant_id=? AND student_id=? AND date=?",
                       (tenant_id, student_id, today_iso())).fetchone()
    return dict(row) if row else None


def incidents_for_student(conn, ctx, student_id):
    """Champs communicables pour tous ; internal_note seulement DD/Direction ;
    un parent ne voit que les incidents que l'établissement a décidé de lui
    communiquer (notify_parent = 1)."""
    role = ctx["role"]
    where = "i.tenant_id = ? AND i.student_id = ?"
    params = [ctx["tenant_id"], student_id]
    if role == "parent":
        where += " AND i.notify_parent = 1"
    rows = conn.execute(
        f"""SELECT i.*, u.name AS recorded_by_name, r.label AS rule_label FROM incidents i
            LEFT JOIN users u ON u.id = i.recorded_by LEFT JOIN discipline_rules r ON r.id = i.rule_id
            WHERE {where} ORDER BY i.occurred_at DESC""",
        params,
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if role not in ("directeur", "discipline"):
            d.pop("internal_note", None)
        result.append(d)
    return result


def discipline_points(conn, tenant_id, student_id, academic_year_id=None):
    """Somme des points (négatifs = retraits, positifs = bonus/corrections) de
    l'année scolaire courante de l'élève — le capital repart chaque année."""
    row = conn.execute("SELECT COALESCE(SUM(points),0) AS pts FROM incidents WHERE tenant_id=? AND student_id=?",
                       (tenant_id, student_id)).fetchone()
    return int(row["pts"] or 0)


def discipline_balance(conn, tenant_id, student_id, settings=None):
    """Capital, retraits, solde restant et cote de conduite calculée."""
    settings = settings or get_settings(conn, tenant_id)
    capital = int(settings.get("discipline_capital") or 100)
    delta = discipline_points(conn, tenant_id, student_id)
    remaining = max(0, min(capital, capital + delta))
    scale = conduct_scale(settings)
    return {"capital": capital, "delta": delta, "remaining": remaining,
            "conduct": conduct_label(remaining, capital, scale), "percent": round(remaining / capital * 100) if capital else 0}


DEFAULT_THRESHOLDS = [(70, "Convocation des parents", "Le titulaire et le DD convoquent les parents."),
                      (50, "Conseil de discipline", "Le dossier passe en conseil de discipline."),
                      (30, "Exclusion possible", "Décision réservée à la Direction, après le conseil.")]


def thresholds(conn, tenant_id):
    rows = conn.execute("SELECT * FROM discipline_thresholds WHERE tenant_id=? ORDER BY remaining_points DESC", (tenant_id,)).fetchall()
    if rows:
        return [dict(r) for r in rows]
    now = str(time.time())
    for i, (pts, label, action) in enumerate(DEFAULT_THRESHOLDS):
        conn.execute("INSERT INTO discipline_thresholds (id, tenant_id, remaining_points, label, action, sort) VALUES (?,?,?,?,?,?)",
                     (new_id(), tenant_id, pts, label, action, i))
    conn.commit()
    return [dict(r) for r in conn.execute("SELECT * FROM discipline_thresholds WHERE tenant_id=? ORDER BY remaining_points DESC", (tenant_id,))]


def crossed_thresholds(conn, tenant_id, before_remaining, after_remaining):
    """Seuils franchis vers le bas entre deux soldes (alerte humaine)."""
    return [t for t in thresholds(conn, tenant_id) if before_remaining > t["remaining_points"] >= after_remaining]


# ---------------------------------------------------------------------------
# CALENDRIER ACADÉMIQUE
#
# Aucun nombre de périodes n'est écrit ici. Une école peut en déclarer trois,
# six ou dix, et en déclarer un nombre différent par division — le code ne
# fait que lire ce qu'elle a configuré. Il ne connaît ni « trimestre » ni
# « semestre » : seulement des périodes ordonnées, avec des dates.
# ---------------------------------------------------------------------------

DIVISIONS = ("maternelle", "primaire", "secondaire")

# États explicites, décidés par la Direction et stockés (admin_state).
ETATS_ADMIN = ("DRAFT", "READY", "LOCKED", "ARCHIVED")


def period_state(period, today=None):
    """État d'une période : ce que la Direction a décidé, croisé avec les dates.

    Deux sources, et l'ordre compte. Un état administratif explicite —
    brouillon, verrouillé, archivé — prime toujours : il traduit une décision
    humaine que le calendrier ne doit pas contredire. À défaut, l'état se
    DÉDUIT des dates, pour que personne n'ait à cliquer quoi que ce soit le
    1er novembre pour que la période 2 commence.

    Une période sans dates est simplement OPEN : l'établissement ne les a pas
    renseignées, on ne les invente pas.
    """
    admin = (period.get("admin_state") or "READY").upper()
    if admin in ("DRAFT", "LOCKED", "ARCHIVED"):
        return admin
    jour = today or today_iso()
    debut, fin = period.get("starts_on"), period.get("ends_on")
    if debut and jour < debut:
        return "UPCOMING"
    if fin and jour > fin:
        # Terminée, mais tant que l'échéance de saisie court, l'établissement
        # a encore quelque chose à faire : CLOSING le dit, CLOSED le nierait.
        limite = period.get("result_entry_deadline") or period.get("validation_deadline")
        return "CLOSING" if (limite and jour <= limite) else "CLOSED"
    return "OPEN"


def periods_for_year(conn, tenant_id, academic_year_id, division=None):
    """Périodes d'une année, éventuellement filtrées sur une division.

    `division IS NULL` en base signifie « toutes les divisions » : ces périodes
    remontent donc quelle que soit la division demandée. C'est ce qui rend la
    migration silencieuse — les périodes créées avant la notion de division
    continuent de s'appliquer partout.
    """
    sql = "SELECT * FROM academic_periods WHERE tenant_id=? AND academic_year_id=?"
    params = [tenant_id, academic_year_id]
    if division:
        sql += " AND (division IS NULL OR division = ?)"
        params.append(division)
    rows = [dict(r) for r in conn.execute(sql + " ORDER BY sort, label", params)]
    for r in rows:
        r["state"] = period_state(r)
        r["is_published"] = bool(r.get("published_at"))
        r["is_locked"] = bool(r.get("locked_at"))
    return rows


def current_period(conn, tenant_id, academic_year_id, division=None, today=None):
    """La période en cours, déduite des DATES configurées — jamais d'une
    horloge frontend ni d'un drapeau posé à la main.

    Si aucune période n'englobe aujourd'hui (vacances, trou dans le
    calendrier), on renvoie la prochaine à venir : c'est ce que la Direction
    veut voir hors période, et cela évite un écran vide.
    """
    jour = today or today_iso()
    periodes = periods_for_year(conn, tenant_id, academic_year_id, division)
    for p in periodes:
        if p["starts_on"] and p["ends_on"] and p["starts_on"] <= jour <= p["ends_on"]:
            return p
    a_venir = [p for p in periodes if p["starts_on"] and p["starts_on"] > jour]
    return a_venir[0] if a_venir else None


def resolve_period(conn, tenant_id, academic_year_id, label, division=None):
    """Retrouve la période déclarée qui porte ce libellé, pour cette année.

    Renvoie None si l'établissement n'a pas déclaré cette période. L'appelant
    écrit alors le libellé sans clé : le résultat reste consultable par le
    personnel, et invisible du parent tant qu'aucune période ne le porte. Mieux
    vaut un résultat non proclamable qu'un résultat rattaché au hasard.

    La division est préférée quand elle est connue : une école peut nommer
    « Période 1 » à la fois au primaire et au secondaire, avec des dates
    différentes. À défaut, la période « toutes divisions » fait foi.
    """
    if not (academic_year_id and label):
        return None
    if division:
        row = conn.execute(
            """SELECT * FROM academic_periods
               WHERE tenant_id=? AND academic_year_id=? AND label=? AND division=?""",
            (tenant_id, academic_year_id, label, division)).fetchone()
        if row:
            return dict(row)
    row = conn.execute(
        """SELECT * FROM academic_periods
           WHERE tenant_id=? AND academic_year_id=? AND label=? AND division IS NULL""",
        (tenant_id, academic_year_id, label)).fetchone()
    if row:
        return dict(row)
    # Dernier recours : le libellé est unique par (tenant, année) dans les bases
    # d'avant les divisions.
    row = conn.execute(
        "SELECT * FROM academic_periods WHERE tenant_id=? AND academic_year_id=? AND label=?",
        (tenant_id, academic_year_id, label)).fetchone()
    return dict(row) if row else None


def period_accepts_results(period):
    """Une période verrouillée ou archivée n'accepte plus d'écriture.

    C'est le verrou du §6 : une fois les résultats validés et proclamés, la
    Direction ferme la période. Modifier une note demande alors une réouverture
    explicite, tracée et motivée — pas une requête bien tournée.
    """
    if not period:
        return True, None
    etat = period_state(period)
    if etat == "LOCKED":
        return False, "Cette période est verrouillée. Une réouverture par la Direction est nécessaire."
    if etat == "ARCHIVED":
        return False, "Cette période est archivée : ses résultats ne sont plus modifiables."
    return True, None


def results_policy(conn, tenant_id):
    """Politique de diffusion de l'établissement, normalisée.

    Une configuration illisible ou absente retombe sur « toujours diffuser » :
    en cas de doute, on ne retient pas les résultats d'un élève. Retenir par
    accident est une faute plus grave que diffuser.
    """
    brut = get_settings(conn, tenant_id).get("results_policy")
    defaut = {"mode": "always", "max_balance": 0.0, "exempt_class_ids": []}
    if not brut:
        return defaut
    try:
        p = json.loads(brut) if isinstance(brut, str) else dict(brut)
    except (ValueError, TypeError):
        return defaut
    mode = p.get("mode") if p.get("mode") in ("always", "balance") else "always"
    try:
        plafond = float(p.get("max_balance") or 0)
    except (TypeError, ValueError):
        plafond = 0.0
    exempts = [c for c in (p.get("exempt_class_ids") or []) if isinstance(c, str)]
    return {"mode": mode, "max_balance": plafond, "exempt_class_ids": exempts}


def compute_publication_audience(conn, tenant_id, period, audience_filter=None):
    """Qui verra les résultats de cette période — calculé PAR LE SERVEUR.

    Le navigateur envoie un filtre (des classes, des niveaux, des élèves) ;
    il n'envoie jamais la liste des destinataires. Cette fonction repart des
    élèves réels de l'établissement, applique le filtre, puis la politique de
    diffusion, et renvoie les deux listes avec le motif de chaque exclusion.

    Le même appel sert à l'APERÇU et à la PUBLICATION : l'aperçu ne peut donc
    pas différer de ce qui sera réellement publié.
    """
    f = audience_filter or {}
    division = f.get("division") or period.get("division")

    sql = """SELECT s.id, s.first_name, s.last_name, s.class_id, c.name AS class_name,
                    c.level AS class_level, c.cycle AS class_cycle
             FROM students s
             LEFT JOIN classes c ON c.id = s.class_id AND c.tenant_id = s.tenant_id
             WHERE s.tenant_id = ? AND s.status = 'active' AND s.academic_year_id = ?"""
    params = [tenant_id, period["academic_year_id"]]
    if division:
        sql += " AND c.cycle = ?"
        params.append(division)
    eleves = [dict(r) for r in conn.execute(sql + " ORDER BY c.name, s.last_name, s.first_name", params)]

    classes = set(f.get("class_ids") or [])
    niveaux = set(f.get("levels") or [])
    choisis = set(f.get("student_ids") or [])
    politique = results_policy(conn, tenant_id)
    exempts = set(politique["exempt_class_ids"])

    inclus, exclus = [], []
    for e in eleves:
        if classes and e["class_id"] not in classes:
            exclus.append({**e, "reason": "hors des classes sélectionnées"})
            continue
        if niveaux and (e["class_level"] or "") not in niveaux:
            exclus.append({**e, "reason": "hors des niveaux sélectionnés"})
            continue
        if choisis and e["id"] not in choisis:
            exclus.append({**e, "reason": "hors de la sélection d'élèves"})
            continue
        if politique["mode"] == "balance" and e["class_id"] not in exempts:
            # Import tardif : financial importe school.
            import financial
            solde = financial.financial_summary(conn, tenant_id, e["id"])["balance"]
            if solde > politique["max_balance"]:
                exclus.append({**e, "reason": "solde supérieur au plafond de diffusion",
                               "balance": solde})
                continue
        inclus.append(e)
    return {"included": inclus, "excluded": exclus,
            "included_count": len(inclus), "excluded_count": len(exclus),
            "total": len(eleves), "policy": politique}


def tenant_has_periods(conn, tenant_id):
    """L'établissement a-t-il déclaré la moindre période officielle ?

    Sinon, il n'a pas de calendrier : tout reste visible, comme avant
    l'introduction des périodes. C'est la seule rétro-compatibilité admise —
    dès qu'une période existe, la règle de proclamation s'applique.
    """
    return conn.execute("SELECT 1 FROM academic_periods WHERE tenant_id=? LIMIT 1",
                        (tenant_id,)).fetchone() is not None


def published_period_ids_for_student(conn, tenant_id, student_id):
    """Périodes réellement consultables par le parent de CET élève.

    Deux conditions, toutes deux vérifiées ici et jamais par le navigateur :

    1. la période est proclamée (`published_at`) ;
    2. l'élève fait partie de l'AUDIENCE de cette proclamation.

    La seconde est ce qui permet à une Direction de proclamer pour certaines
    classes seulement. Une proclamation sans audience enregistrée — celles
    faites avant que les audiences existent — vaut pour tout l'établissement :
    c'était alors son sens, et le rétro-remplissage ne doit pas priver des
    parents de résultats qu'ils voyaient déjà.

    Une proclamation retirée (`unpublished_at`) ne compte plus.
    """
    rows = conn.execute(
        """SELECT p.id FROM academic_periods p
           WHERE p.tenant_id = ? AND p.published_at IS NOT NULL
             AND (
               NOT EXISTS (SELECT 1 FROM period_publications pp
                           WHERE pp.tenant_id = p.tenant_id AND pp.period_id = p.id
                             AND pp.unpublished_at IS NULL)
               OR EXISTS (SELECT 1 FROM period_publications pp
                          JOIN publication_students ps ON ps.publication_id = pp.id
                          WHERE pp.tenant_id = p.tenant_id AND pp.period_id = p.id
                            AND pp.unpublished_at IS NULL AND ps.student_id = ?)
             )""",
        (tenant_id, student_id),
    ).fetchall()
    return {r["id"] for r in rows}


def visible_results_for_student(conn, ctx, student_id, lignes):
    """Filtre des résultats (notes ou appréciations) pour le portail parent.

    Fermeture par défaut : une ligne sans `period_id` n'appartient à aucune
    période proclamée et reste invisible. Un résultat qu'on n'a pas su
    rattacher ne doit pas se retrouver publié par accident.
    """
    if ctx["role"] != "parent":
        return lignes
    if not tenant_has_periods(conn, ctx["tenant_id"]):
        return lignes
    autorisees = published_period_ids_for_student(conn, ctx["tenant_id"], student_id)
    return [l for l in lignes if l.get("period_id") and l["period_id"] in autorisees]


def grades_visible_for(conn, ctx, grades):
    """Un parent ne voit que les périodes proclamées ET dont il fait partie de
    l'audience ; le personnel voit tout."""
    if ctx["role"] != "parent" or not grades:
        return grades
    if not tenant_has_periods(conn, ctx["tenant_id"]):
        return grades
    # Les notes peuvent couvrir plusieurs élèves (vue multi-enfants) : on
    # résout l'audience élève par élève, jamais globalement.
    par_eleve = {}
    sortie = []
    for g in grades:
        sid = g.get("student_id")
        if sid not in par_eleve:
            par_eleve[sid] = published_period_ids_for_student(conn, ctx["tenant_id"], sid)
        if g.get("period_id") and g["period_id"] in par_eleve[sid]:
            sortie.append(g)
    return sortie


def grades_for_student(conn, tenant_id, student_id):
    # is_current=1 : seules les versions COURANTES. Sans ce filtre, un second
    # import de résultats faisait apparaître DEUX notes pour la même matière —
    # l'ancienne et la nouvelle — dans le dossier de l'élève, dans son bulletin,
    # et donc chez le parent. L'historique complet reste accessible au personnel
    # par /api/results/history.
    rows = conn.execute(
        """SELECT g.*, u.name AS recorded_by_name FROM grades g LEFT JOIN users u ON u.id = g.recorded_by
           WHERE g.tenant_id=? AND g.student_id=? AND g.is_current=1
           ORDER BY g.period, g.subject, g.created_at""",
        (tenant_id, student_id),
    ).fetchall()
    return [dict(r) for r in rows]


def bulletin(conn, tenant_id, student, period=None, only_published=False):
    """Bulletin CALCULÉ : moyenne par matière (sur 20 normalisé), moyenne
    générale, rang dans la classe pour la période, cote de conduite. Aucun
    chiffre stocké. `only_published` : périodes proclamées uniquement (parent)."""
    grades = grades_for_student(conn, tenant_id, student["id"])
    if only_published and tenant_has_periods(conn, tenant_id):
        # Le bulletin d'un parent ne se construit QUE sur des résultats
        # proclamés dont son enfant fait partie de l'audience. Un bulletin
        # calculé sur des résultats non validés serait un faux document.
        autorisees = published_period_ids_for_student(conn, tenant_id, student["id"])
        grades = [g for g in grades if g.get("period_id") and g["period_id"] in autorisees]
    periods = sorted({g["period"] for g in grades})
    if period is None and periods:
        period = periods[-1]
    lines = {}
    for g in grades:
        if period and g["period"] != period:
            continue
        pct = (g["score"] / g["max_score"]) if g["max_score"] else 0
        lines.setdefault(g["subject"], []).append(pct)
    subjects = [{"subject": s, "average_20": round(sum(v) / len(v) * 20, 2), "count": len(v)} for s, v in sorted(lines.items())]
    general = round(sum(s["average_20"] for s in subjects) / len(subjects), 2) if subjects else None

    # Rang dans la classe.
    #
    # Deux défauts corrigés ici, trouvés à l'audit et reproduits :
    #
    # 1. Le rang se calculait par `AVG(score / max_score)` sur TOUTES les notes
    #    à plat, alors que la moyenne affichée juste au-dessus est la moyenne
    #    des moyennes PAR MATIÈRE. Les deux ne coïncident que si chaque élève a
    #    le même nombre de notes dans chaque matière. Cas réel reproduit :
    #    Alice (cinq notes de maths à 18, une de français à 6) et Bruno (12 en
    #    maths, 12 en français) affichaient tous deux 12,0 de moyenne — et
    #    Alice sortait 1re, Bruno 2e. Le rang ne correspondait pas à la
    #    moyenne imprimée sur le même bulletin.
    #
    # 2. Deux moyennes égales donnaient deux rangs différents, décidés par
    #    l'ordre de la base. Un élève pouvait être « 2e sur 2 » avec exactement
    #    la moyenne du premier.
    #
    # On recalcule donc le classement avec EXACTEMENT la même règle que la
    # moyenne affichée, et on applique le classement standard : à égalité,
    # même rang, et le rang suivant saute d'autant (1, 1, 3).
    rank, class_size = None, None
    if student["class_id"] and period and general is not None:
        # 3. `is_current=1` — troisième défaut, trouvé le 17/09. La moyenne de
        #    l'élève se lit sur la version courante (grades_for_student filtre),
        #    mais le CLASSEMENT relisait toute la classe sans ce filtre : une
        #    note corrigée continuait de peser à côté de celle qui l'a
        #    remplacée. Reproduit : Bruno corrigé de 4 à 18 était moyenné à
        #    (4+18)/2 = 11 et sortait 2e derrière Alice (14), alors que son
        #    bulletin imprimait bien 18. Le rang contredisait sa propre moyenne.
        notes_classe = conn.execute(
            """SELECT student_id, subject, score, max_score FROM grades
               WHERE tenant_id=? AND class_id=? AND period=? AND is_current=1""",
            (tenant_id, student["class_id"], period),
        ).fetchall()
        par_eleve = {}
        for n in notes_classe:
            if not n["max_score"]:
                continue
            par_eleve.setdefault(n["student_id"], {}).setdefault(n["subject"], []).append(
                n["score"] / n["max_score"])
        moyennes = {}
        for eleve_id, matieres in par_eleve.items():
            par_matiere = [sum(v) / len(v) * 20 for v in matieres.values()]
            moyennes[eleve_id] = round(sum(par_matiere) / len(par_matiere), 2)
        class_size = len(moyennes)
        if student["id"] in moyennes:
            ma_moyenne = moyennes[student["id"]]
            # Rang = nombre d'élèves STRICTEMENT au-dessus, plus un.
            rank = sum(1 for m in moyennes.values() if m > ma_moyenne) + 1
    settings = get_settings(conn, tenant_id)
    bal = discipline_balance(conn, tenant_id, student["id"], settings)
    override = conn.execute("SELECT label, note FROM conduct_overrides WHERE tenant_id=? AND student_id=? AND period=?",
                            (tenant_id, student["id"], period or "")).fetchone() if period else None
    decision = conn.execute("SELECT decision, mention, note FROM bulletin_decisions WHERE tenant_id=? AND student_id=? AND academic_year_id=?",
                            (tenant_id, student["id"], student["academic_year_id"])).fetchone()
    percent = round(general / 20 * 100, 1) if general is not None else None
    return {"period": period, "periods": periods, "subjects": subjects, "general_average_20": general, "percent": percent,
            "rank": rank, "class_size": class_size,
            "conduct": {"label": override["label"] if override else bal["conduct"], "computed": bal["conduct"], "remaining": bal["remaining"],
                        "capital": bal["capital"], "overridden": bool(override), "note": override["note"] if override else None},
            "decision": dict(decision) if decision else None, "pass_threshold": settings.get("pass_threshold")}


def schedule_for_class(conn, tenant_id, class_id):
    rows = conn.execute(
        """SELECT sl.*, u.name AS teacher_name FROM schedule_slots sl LEFT JOIN users u ON u.id = sl.teacher_user_id
           WHERE sl.tenant_id=? AND sl.class_id=? ORDER BY sl.weekday, sl.start_time""",
        (tenant_id, class_id),
    ).fetchall()
    return [dict(r) for r in rows]


def exams_for_class(conn, tenant_id, class_id, upcoming_only=False):
    where = "tenant_id=? AND class_id=?"
    params = [tenant_id, class_id]
    if upcoming_only:
        where += " AND date >= ?"
        params.append(today_iso())
    rows = conn.execute(f"SELECT * FROM exams WHERE {where} ORDER BY date, start_time", params).fetchall()
    return [dict(r) for r in rows]


def receipts_for_student(conn, tenant_id, student_id):
    rows = conn.execute(
        "SELECT * FROM receipts WHERE tenant_id=? AND student_id=? ORDER BY created_at DESC",
        (tenant_id, student_id),
    ).fetchall()
    return [dict(r) for r in rows]


def orders_for_student(conn, tenant_id, student_id):
    rows = conn.execute("SELECT * FROM orders WHERE tenant_id=? AND student_id=? ORDER BY created_at DESC",
                        (tenant_id, student_id)).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["items"] = [dict(i) for i in conn.execute("SELECT * FROM order_items WHERE order_id=?", (r["id"],)).fetchall()]
        result.append(d)
    return result


def titulaire_of_class(conn, tenant_id, class_id):
    if not class_id:
        return None
    row = conn.execute(
        """SELECT u.id, u.name FROM class_teachers ct JOIN users u ON u.id = ct.user_id
           WHERE ct.tenant_id=? AND ct.class_id=? AND ct.is_titulaire=1 LIMIT 1""",
        (tenant_id, class_id),
    ).fetchone()
    return dict(row) if row else None


def _visible_appreciations(conn, ctx, student_id):
    rows = [dict(r) for r in conn.execute("SELECT * FROM appreciations WHERE tenant_id=? AND student_id=? ORDER BY period, domain", (ctx["tenant_id"], student_id))]
    return visible_results_for_student(conn, ctx, student_id, rows)


def build_dossier(conn, ctx, student, financial_module):
    """Le dossier central, filtré par rôle. `sections` dit à l'interface
    quels onglets afficher — le backend a DÉJÀ retiré ce qui n'est pas
    autorisé, l'interface ne fait que refléter."""
    tenant_id = ctx["tenant_id"]
    role = ctx["role"]
    sid = student["id"]

    dossier = {
        "student": {
            "id": sid, "code": student["code"], "first_name": student["first_name"], "last_name": student["last_name"],
            "gender": student["gender"], "birth_date": student["birth_date"], "photo_data": student["photo_data"],
            "status": student["status"], "created_at": student["created_at"],
            "class": ({"id": student["class_id"], "name": student["class_name"], "level": student["class_level"], "cycle": student["class_cycle"]}
                      if student["class_id"] else None),
            "titulaire": titulaire_of_class(conn, tenant_id, student["class_id"]),
        },
        "guardians": guardians_of(conn, tenant_id, sid),
        "attendance": {"summary": attendance_summary(conn, tenant_id, sid), "today": attendance_today(conn, tenant_id, sid),
                       "recent": attendance_recent(conn, tenant_id, sid)},
        "discipline": {"points": discipline_points(conn, tenant_id, sid), "incidents": incidents_for_student(conn, ctx, sid),
                       "balance": discipline_balance(conn, tenant_id, sid), "thresholds": thresholds(conn, tenant_id) if role != "parent" else []},
        "grades": grades_visible_for(conn, ctx, grades_for_student(conn, tenant_id, sid)),
        "bulletin": bulletin(conn, tenant_id, student, only_published=(role == "parent")),
        "appreciations": _visible_appreciations(conn, ctx, sid),
        "justifications": [dict(r) for r in conn.execute("SELECT id, date, reason, status, decision_note, created_at, decided_at, attachment_name FROM attendance_justifications WHERE tenant_id=? AND student_id=? ORDER BY date DESC", (tenant_id, sid))],
        "convocations": [dict(r) for r in conn.execute("SELECT * FROM convocations WHERE tenant_id=? AND student_id=? ORDER BY scheduled_on DESC", (tenant_id, sid))] if role != "professeur" else [],
        "resources_count": conn.execute("SELECT COUNT(*) n FROM resources WHERE tenant_id=? AND class_id=?", (tenant_id, student["class_id"])).fetchone()["n"] if student["class_id"] else 0,
        "schedule": schedule_for_class(conn, tenant_id, student["class_id"]) if student["class_id"] else [],
        "exams": exams_for_class(conn, tenant_id, student["class_id"], upcoming_only=False) if student["class_id"] else [],
        "finance": None, "receipts": [], "orders": [],
        "finance_visible": finance_visible(conn, ctx),
        "sections": ["profil", "scolarite", "presence", "discipline", "horaire", "documents", "messages"],
    }
    if dossier["finance_visible"]:
        dossier["finance"] = financial_module.financial_summary(conn, tenant_id, sid)
        dossier["sections"].append("finance")
        if role in ("directeur", "parent"):
            dossier["receipts"] = receipts_for_student(conn, tenant_id, sid)
            dossier["orders"] = orders_for_student(conn, tenant_id, sid)
            dossier["sections"].append("recus")
    if role == "discipline":
        # Le DD ne gère pas les finances — l'onglet n'apparaît pas et la donnée n'est pas envoyée.
        dossier["finance_visible"] = False
    if role == "parent":
        # Le parent ne reçoit pas les coordonnées des autres responsables ni la note interne.
        dossier["guardians"] = [{"first_name": g["first_name"], "last_name": g["last_name"], "relationship": g["relationship"]} for g in dossier["guardians"]]
    return dossier
