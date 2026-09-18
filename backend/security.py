"""KLASSIO backend — authentification, contexte tenant, RBAC, audit.

Principes appliqués ici (docs/SECURITE.md, docs/MULTI_TENANT.md) :
- Le mot de passe n'est jamais stocké en clair (PBKDF2-HMAC-SHA256, sel aléatoire).
- Le tenant_id d'une requête vient TOUJOURS de la session serveur (table `sessions`),
  jamais d'un champ envoyé par le client — même si le client en envoie un, il est ignoré.
- Chaque route sensible passe par `require_auth` puis `require_permission`.
- Toute action sensible est journalisée dans `audit_logs`, y compris les refus.
"""
import hashlib
import hmac
import os
import secrets
import time
import uuid
import json
from functools import wraps
from flask import request, g, jsonify

import db

SESSION_TTL_SECONDS = 60 * 60 * 12  # 12h — cohérent avec docs/SECURITE.md §4.3 (courte durée)

# ---------------------------------------------------------------------------
# Limitation des tentatives (docs/SECURITE.md §4.4)
#
# Trouvé par pentest : 10 tentatives de mot de passe en ~2 s, aucun
# ralentissement. Puis, à l'audit de production : les compteurs vivaient dans un
# dictionnaire en mémoire de processus. Cela marchait — à condition de ne jamais
# lancer plus d'un worker. Avec `gunicorn -w 4`, chaque worker tient ses propres
# compteurs et un attaquant obtient quatre fois la limite ; avec N workers, N
# fois. La protection s'affaiblissait donc exactement au moment où l'on montait
# en charge, sans que rien ne le signale.
#
# Les tentatives sont maintenant enregistrées en base. La limite est la même
# quel que soit le nombre de workers, et elle survit au redémarrage d'un dyno.
# Coût : deux ou trois requêtes, uniquement sur les sept routes publiques.
#
# La fenêtre reste glissante (on garde chaque tentative, pas un compteur par
# tranche) : c'est le comportement d'origine, et il ne laisse pas passer une
# rafale à cheval sur deux tranches.
# ---------------------------------------------------------------------------

LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300  # 5 minutes
_LOGIN_BUCKET = "login"

# Au-delà de cette durée, une tentative n'intéresse plus aucune fenêtre : elle
# est balayée. Le balayage global est amorti — au plus une fois par minute et
# par processus — pour ne pas ajouter une écriture à chaque connexion.
_PURGE_APRES_SECONDES = 3600
_PURGE_INTERVALLE = 60
_derniere_purge = 0.0


def _purge_globale(conn):
    """Efface les tentatives trop vieilles pour compter, toutes routes confondues.

    Sans elle, la table grossirait indéfiniment : les tentatives d'un attaquant
    qui change d'adresse à chaque essai ne seraient jamais relues, donc jamais
    nettoyées par le chemin normal.
    """
    global _derniere_purge
    maintenant = time.time()
    if maintenant - _derniere_purge < _PURGE_INTERVALLE:
        return
    _derniere_purge = maintenant
    conn.execute("DELETE FROM rate_limit_attempts WHERE attempted_at < ?",
                 (maintenant - _PURGE_APRES_SECONDES,))


def check_rate_limit(bucket: str, key: str, max_attempts: int, window_seconds: int):
    """Retourne (autorisé: bool, secondes_avant_reessai: int).

    N'enregistre rien : appeler record_attempt() séparément pour chaque essai.
    """
    maintenant = time.time()
    debut_fenetre = maintenant - window_seconds
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM rate_limit_attempts WHERE bucket=? AND subject=? AND attempted_at < ?",
                     (bucket, key, debut_fenetre))
        _purge_globale(conn)
        conn.commit()
        ligne = conn.execute(
            "SELECT COUNT(*) AS n, MIN(attempted_at) AS plus_ancienne FROM rate_limit_attempts "
            "WHERE bucket=? AND subject=? AND attempted_at >= ?",
            (bucket, key, debut_fenetre),
        ).fetchone()
    finally:
        conn.close()
    if (ligne["n"] or 0) < max_attempts:
        return True, 0
    retry_after = int(window_seconds - (maintenant - float(ligne["plus_ancienne"])))
    return False, max(retry_after, 1)


def record_attempt(bucket: str, key: str):
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO rate_limit_attempts (id, bucket, subject, attempted_at) VALUES (?,?,?,?)",
                     (new_id(), bucket, key, time.time()))
        conn.commit()
    finally:
        conn.close()


def _oublier(bucket: str, key: str):
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM rate_limit_attempts WHERE bucket=? AND subject=?", (bucket, key))
        conn.commit()
    finally:
        conn.close()


def clear_attempts(bucket: str, key: str):
    """Une opération RÉUSSIE efface l'ardoise de cette clé.

    Même règle que pour la connexion (`clear_login_attempts`), étendue le 18/09
    aux routes publiques comptées PAR ADRESSE IP : invitation, réinitialisation
    de mot de passe.

    Pourquoi. Ces routes protègent un secret (un jeton) contre l'énumération.
    Mais elles comptaient TOUTES les tentatives, réussies comprises, et la clé
    est l'adresse IP. Or dans une école congolaise, les parents acceptent leur
    invitation depuis le wifi de l'établissement : ils partagent une seule
    adresse. Le jour de la rentrée, le onzième parent était refusé — non pas
    parce qu'il était suspect, mais parce que dix voisins avaient réussi avant
    lui. La protection frappait exactement les gens qu'elle devait servir.

    La correction ne desserre rien : le plafond reste le même, mais seul un
    ÉCHEC SUR LE SECRET le consomme. Un attaquant qui devine des jetons échoue
    à chaque coup et se fait couper aussi vite qu'avant ; deux cents parents qui
    réussissent ne consomment rien. C'est plus strict là où il faut et ouvert là
    où il faut.
    """
    _oublier(bucket, key)


# --- Connexion : même mécanique, comptée par adresse e-mail --------------

def check_login_rate_limit(email: str):
    return check_rate_limit(_LOGIN_BUCKET, email, LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SECONDS)


def record_login_failure(email: str):
    record_attempt(_LOGIN_BUCKET, email)


def clear_login_attempts(email: str):
    """Une connexion réussie efface l'ardoise de ce compte."""
    _oublier(_LOGIN_BUCKET, email)


def reset_rate_limits_for_tests():
    """Uniquement pour la suite de tests : elle appelle register-school des
    dizaines de fois depuis la même IP simulée (127.0.0.1 du client de test
    Flask) en quelques secondes — bien plus qu'un vrai visiteur, et plus que la
    limite ci-dessus. Sans ce reset, la limite anti-abus se déclencherait sur la
    suite elle-même."""
    global _derniere_purge
    _derniere_purge = 0.0
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM rate_limit_attempts")
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Mots de passe
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest_hex = stored.split("$")
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000)
    return hmac.compare_digest(candidate.hex(), digest_hex)


# ---------------------------------------------------------------------------
# Sessions / Tenant Context (docs/MULTI_TENANT.md §7)
# ---------------------------------------------------------------------------

def new_id() -> str:
    return uuid.uuid4().hex


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(conn, user_id: str, tenant_id: str) -> str:
    """Émet un token de session. Audit de sécurité : seul son hash SHA-256 est
    stocké (colonne `sessions.token`, malgré son nom) — jamais le token brut,
    même principe déjà appliqué aux invitations. Une fuite du fichier DB ne
    suffit donc plus, à elle seule, à usurper une session active."""
    token = secrets.token_urlsafe(32)
    now = time.time()
    conn.execute(
        "INSERT INTO sessions (token, user_id, tenant_id, created_at, expires_at) VALUES (?,?,?,?,?)",
        (hash_session_token(token), user_id, tenant_id, str(now), str(now + SESSION_TTL_SECONDS)),
    )
    conn.commit()
    return token


# ---------------------------------------------------------------------------
# Invitations (professeur / parent) — refonte onboarding/rôles
# Le lien seul n'est jamais considéré comme une preuve d'identité suffisante :
# il établit uniquement "cette personne a reçu une invitation de cet établissement".
# Le token est court-durée, à usage unique (passe en 'accepted' dès l'acceptation)
# et révocable. Seul son hash est stocké — jamais le token brut.
# ---------------------------------------------------------------------------
INVITATION_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 jours


def generate_invitation_token() -> str:
    return secrets.token_urlsafe(32)


def hash_invitation_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def purger_sessions_expirees(conn):
    """Supprime les sessions dont la validité est passée. Retourne le nombre.

    Une session expirée est déjà refusée par resolve_session — mais elle n'est
    effacée que si quelqu'un présente son jeton. Personne ne repasse jamais
    avec un jeton périmé : la table grossit donc indéfiniment, et garde à
    demeure des secrets qui ne servent plus à rien.

    Relevé par verifier_invariants.py sur la base de développement : 16 jetons
    d'avant le passage au hachage y dormaient encore, en clair. Tous expirés,
    donc inexploitables — mais un secret périmé qui traîne reste un secret qui
    traîne.

    Appelé par la phase `release` du déploiement. N'efface jamais une session
    valide : la condition porte sur la date d'expiration, rien d'autre.
    """
    curseur = conn.execute("DELETE FROM sessions WHERE CAST(expires_at AS REAL) < ?", (time.time(),))
    conn.commit()
    return curseur.rowcount or 0


def resolve_session(conn, token: str):
    """Résout le contexte tenant/utilisateur UNIQUEMENT depuis la session serveur.

    C'est la fonction la plus critique de ce fichier : `tenant_id` ne provient
    jamais d'ailleurs que de cette table, quoi que le frontend envoie par ailleurs.
    """
    if not token:
        return None
    row = conn.execute("SELECT * FROM sessions WHERE token = ?", (hash_session_token(token),)).fetchone()
    if not row:
        return None
    if float(row["expires_at"]) < time.time():
        conn.execute("DELETE FROM sessions WHERE token = ?", (hash_session_token(token),))
        conn.commit()
        return None
    membership = conn.execute(
        "SELECT * FROM memberships WHERE user_id = ? AND tenant_id = ? AND status = 'active'",
        (row["user_id"], row["tenant_id"]),
    ).fetchone()
    if not membership:
        # Le membership a pu être révoqué depuis la création de la session — on refuse.
        return None
    user = conn.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
    return {
        "user_id": row["user_id"],
        "user_name": user["name"] if user else None,
        "tenant_id": row["tenant_id"],
        "role": membership["role"],
    }


# Garde d'écriture (abonnement suspendu) : fonction(conn, ctx, path, method) → bool,
# branchée par app.py. None = aucune garde (tests unitaires des modules isolés).
WRITE_GUARD = None


def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        conn = db.get_connection()
        ctx = resolve_session(conn, token)
        blocked = bool(ctx and WRITE_GUARD and WRITE_GUARD(conn, ctx, request.path, request.method))
        conn.close()
        if not ctx:
            return jsonify({"error": "Non authentifié"}), 401
        if blocked:
            audit(ctx["tenant_id"], ctx["user_id"], "write.blocked_suspended", status="denied")
            return jsonify({"error": "Espace en lecture seule : l'abonnement de l'établissement est en attente de règlement. Vos données sont intactes."}), 402
        g.ctx = ctx
        return fn(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# RBAC — matrice de permissions (docs/SECURITE.md §6-8)
# ---------------------------------------------------------------------------

#
# Quatre rôles réels : directeur (Direction), discipline (Directeur des
# disciplines, "DD"), professeur, parent. Il n'existe AUCUN compte "élève" —
# l'élève est une entité scolaire centrale, jamais un utilisateur (décision
# produit : ÉLÈVE ≠ COMPTE UTILISATEUR).
#
# Les permissions suffixées ".assigned" (professeur) et ".own" (parent) ne
# donnent jamais accès à tout le tenant : le périmètre précis (classes
# rattachées, enfants liés) est résolu par backend/school.py à chaque requête.
ROLES = ("directeur", "discipline", "professeur", "parent")

ROLE_PERMISSIONS = {
    "directeur": {
        "students.read", "students.create", "students.manage", "academic_years.manage", "classes.manage",
        "catalog.manage", "obligations.create", "obligations.read",
        "payments.create", "payments.read", "payments.confirm",
        "dashboard.school", "audit.read", "events.read",
        "import.run", "invitations.manage", "reports.read",
        "team.manage", "settings.manage",
        "attendance.read", "attendance.manage",
        "discipline.read", "discipline.manage", "discipline.internal", "discipline.rules.manage",
        "grades.read", "grades.manage", "schedule.read", "schedule.manage",
        "store.read", "store.manage", "orders.read", "orders.manage", "receipts.read",
    },
    "discipline": {
        "students.read.secondary", "classes.read", "dashboard.discipline",
        "attendance.read", "attendance.manage",
        "discipline.read", "discipline.manage", "discipline.internal", "discipline.rules.read",
        "schedule.read", "reports.read.discipline",
    },
    "professeur": {
        "students.read.assigned", "classes.read.assigned", "dashboard.class",
        "attendance.read.assigned", "attendance.manage.assigned",
        "discipline.read.assigned",  # informations communicables uniquement
        "grades.read.assigned", "grades.manage.assigned",
        "schedule.read.assigned",
        "finance.read.assigned",  # effective seulement si tenant_settings.teacher_sees_finance = 1
    },
    "parent": {
        "students.read.own", "obligations.read.own", "payments.read.own", "payments.create.own",
        "attendance.read.own", "discipline.read.own", "grades.read.own",
        "schedule.read.own", "exams.read.own", "receipts.read.own",
        "store.read", "orders.create.own", "orders.read.own", "dashboard.parent",
    },
}


def has_permission(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())


def require_permission(permission: str):
    """Vérifie la permission, journalise ce qui mérite de l'être.

    Un REFUS est toujours journalisé : c'est la raison d'être du journal
    d'audit, et docs/SECURITE.md §11 exige qu'aucun refus ne soit silencieux.

    Une autorisation accordée sur une LECTURE ne l'est plus. Deux raisons, l'une
    et l'autre mesurées :

    - Lisibilité. Sur la base de simulation, 15 817 des 43 818 lignes d'audit
      étaient des « permission_check:students.read success », contre 2 refus.
      `/api/audit-logs` ne renvoie que les 100 dernières : les actions réelles
      d'un établissement — qui a modifié une note, qui a encaissé — étaient
      noyées sous le bruit. Un journal d'audit illisible ne sert à personne.
    - Coût. Chaque ligne est une écriture AVEC commit, sur une requête de
      lecture. Mesuré sous 30 utilisateurs simultanés, c'est ce qui sérialisait
      les lectures.

    Les écritures gardent leur trace d'autorisation : c'est le filet si une
    route oubliait son propre appel à audit(). Et chaque action métier continue
    de journaliser explicitement ce qu'elle a fait.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            ctx = g.ctx
            allowed = has_permission(ctx["role"], permission)
            if not allowed:
                audit(ctx["tenant_id"], ctx["user_id"], f"permission_check:{permission}",
                      status="denied")
                return jsonify({"error": "Vous n'avez pas l'autorisation d'effectuer cette action."}), 403
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                audit(ctx["tenant_id"], ctx["user_id"], f"permission_check:{permission}",
                      status="success")
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Audit (docs/SECURITE.md §11) — y compris les refus, jamais silencieux
# ---------------------------------------------------------------------------

def audit(tenant_id, actor_id, action, resource_type=None, resource_id=None,
          status="success", before=None, after=None):
    conn = db.get_connection()
    conn.execute(
        """INSERT INTO audit_logs
           (id, tenant_id, actor_id, action, resource_type, resource_id, status, before_json, after_json, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (new_id(), tenant_id, actor_id, action, resource_type, resource_id, status,
         json.dumps(before) if before is not None else None,
         json.dumps(after) if after is not None else None,
         str(time.time())),
    )
    conn.commit()
    conn.close()
