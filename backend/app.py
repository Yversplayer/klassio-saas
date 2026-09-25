"""KLASSIO backend — API Flask.

Principe appliqué sur CHAQUE route qui touche une donnée métier : le tenant_id
vient exclusivement de g.ctx (résolu depuis la session serveur par
security.require_auth), jamais d'un champ envoyé dans le JSON ou l'URL — même
si le client en envoie un, il est purement et simplement ignoré.
"""
from flask import Flask, request, jsonify, g
import bisect
import datetime
import gzip
import json
import time
import csv
import io

import config
import db
import security
import financial
from urllib.parse import quote

import events as events_module
import deliveries as deliveries_module
import mailer
import notifications as notif_module
import ingestion
import ai_assistant
import school
import api_school
import api_life
import api_discipline
import api_academics
import api_billing
from security import require_auth, require_permission, new_id, audit
from validation import (
    ValidationError, json_object, positive_amount, required_text, valid_email, valid_password, valid_phone, valid_hex_color,
)

app = Flask(__name__)
# Dossier central de l'élève et domaines rattachés (présences, discipline,
# résultats, horaires, boutique, reçus, notifications, réglages).
app.register_blueprint(api_school.bp)
app.register_blueprint(api_life.bp)
app.register_blueprint(api_discipline.bp)
app.register_blueprint(api_academics.bp)
app.register_blueprint(api_billing.bp)

# Espace suspendu (abonnement impayé au-delà du délai de grâce) : lecture
# libre, écriture bloquée — jamais de suppression de données.
security.WRITE_GUARD = api_billing.write_blocked

# Audit de sécurité : aucune limite de taille n'était configurée — un fichier
# d'import de plusieurs Go était chargé intégralement en mémoire
# (file_storage.read()) sur ce serveur mono-processus qui sert TOUS les
# établissements. Un directeur (privilège normal, pas admin système) pouvait
# ainsi interrompre le service pour tous les autres tenants. 10 Mo est
# largement suffisant pour un tableur d'import.
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

# Durée de validité d'une analyse d'import. Assez longue pour relire
# tranquillement un aperçu de 2 000 élèves, assez courte pour qu'un fichier
# oublié ne soit pas confirmé des jours plus tard sur une base qui a changé.
IMPORT_SESSION_TTL_SECONDS = 2 * 60 * 60


@app.errorhandler(413)
def handle_file_too_large(err):
    return jsonify({"error": "Fichier trop volumineux (10 Mo maximum)."}), 413


# Trouvé par pentest : Access-Control-Allow-Origin: "*" n'a pas d'exploitation directe
# tant que l'authentification passe par un Bearer token en localStorage (pas de
# cookie), mais reste une mauvaise pratique — restreint à l'origine réelle du
# frontend plutôt qu'un joker.
#
# Trouvé à l'audit production : la liste était figée sur les deux origines de
# développement. Une fois le frontend servi depuis un domaine réel, tout appel
# navigateur aurait été refusé par le CORS, sans moyen de corriger autrement
# qu'en modifiant le code. Les origines supplémentaires se déclarent donc en
# variable d'environnement, séparées par des virgules :
#
#   KLASSIO_ALLOWED_ORIGINS=https://app.klassio.com,https://klassio.com
#
# Le joker "*" reste volontairement impossible : une valeur "*" est ignorée.
_DEV_ORIGINS = {"http://localhost:4173", "http://127.0.0.1:4173"}
ALLOWED_ORIGINS = _DEV_ORIGINS | {
    origine.strip().rstrip("/")
    for origine in (config.get("KLASSIO_ALLOWED_ORIGINS", "") or "").split(",")
    if origine.strip() and origine.strip() != "*"
}


@app.after_request
def add_security_headers(resp):
    origin = request.headers.get("Origin")
    if origin in ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    # PATCH manquait. Le préflight répondait 200 sans l'autoriser, donc le
    # navigateur bloquait la requête réelle : côté écran, un formulaire qui ne
    # fait rien, sans erreur, sans message. Trouvé en pilotant l'écran de
    # passage d'année — la première route PATCH du produit.
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    # Défense en profondeur (docs/SECURITE.md §14.4) — utile même pour une API JSON :
    # empêche un navigateur de "deviner" un type de contenu exécutable, et bloque
    # tout embarquement dans une frame tierce.
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.is_secure or request.headers.get("X-Forwarded-Proto") == "https":
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp


# ---------------------------------------------------------------------------
# Compression des réponses
#
# La liste des élèves d'un établissement de 2 340 élèves pèse 892 Ko de JSON.
# Le frontend la charge en une fois, volontairement : la recherche et les
# filtres sont ensuite instantanés, ce qui compte pour un secrétariat. Mais
# 892 Ko sur une connexion mobile congolaise, à chaque ouverture de la page,
# c'est un coût réel — et ni Flask ni le routeur Heroku ne compressent.
#
# Le JSON se compresse extrêmement bien (noms de champs répétés à chaque
# ligne). On le fait ici, sans dépendance et sans changer une seule réponse :
# le client reçoit exactement les mêmes octets une fois décompressés.
# ---------------------------------------------------------------------------

COMPRESSION_SEUIL_OCTETS = 1024   # en dessous, l'en-tête coûterait plus que le gain
COMPRESSION_NIVEAU = 6            # au-delà, le temps CPU dépasse le gain de transfert


@app.after_request
def compresser_les_reponses(resp):
    if resp.direct_passthrough or resp.status_code >= 300:
        return resp
    if "gzip" not in request.headers.get("Accept-Encoding", "").lower():
        return resp
    if resp.headers.get("Content-Encoding"):
        return resp
    type_contenu = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
    if type_contenu not in ("application/json", "text/html", "text/css",
                            "application/javascript", "text/plain"):
        return resp
    donnees = resp.get_data()
    if len(donnees) < COMPRESSION_SEUIL_OCTETS:
        return resp
    compresse = gzip.compress(donnees, COMPRESSION_NIVEAU)
    if len(compresse) >= len(donnees):
        return resp  # déjà compressé en amont, ou incompressible
    resp.set_data(compresse)
    resp.headers["Content-Encoding"] = "gzip"
    resp.headers["Content-Length"] = str(len(compresse))
    # Sans Vary, un cache intermédiaire servirait du gzip à un client qui n'en
    # veut pas — ou l'inverse.
    resp.headers["Vary"] = (resp.headers.get("Vary") + ", Accept-Encoding") if resp.headers.get("Vary") else "Accept-Encoding"
    return resp


@app.errorhandler(ValidationError)
def handle_validation_error(err):
    return jsonify({"error": str(err)}), 400


def handle_integrity_error(err):
    # Trouvé par pentest : une contrainte d'unicité violée (ex. idempotency_key,
    # email déjà pris dans une course concurrente) provoquait un 500 brut avec
    # trace potentielle. Toujours répondre proprement, jamais laisser fuiter la
    # trace d'exécution — cohérent avec docs/SECURITE.md §61 (statuts honnêtes,
    # jamais un comportement non maîtrisé exposé au client).
    return jsonify({"error": "Conflit de données — cette opération ne peut pas être appliquée telle quelle."}), 409


# Trouvé à l'audit production : le décorateur ne visait que sqlite3.IntegrityError.
# En mode Postgres, la même violation de contrainte est une psycopg IntegrityError
# — elle échappait donc au 409 et repartait en 500. Les deux moteurs sont
# maintenant enregistrés, quel que soit KLASSIO_DB_BACKEND.
for _classe_integrite in db.integrity_errors():
    app.register_error_handler(_classe_integrite, handle_integrity_error)


@app.errorhandler(Exception)
def handle_unexpected_error(err):
    """Dernier filet : une exception non prévue ne doit jamais renvoyer une
    trace d'exécution au client (chemins de fichiers, requêtes SQL, structure
    interne). La trace part dans les logs du serveur, le client reçoit un 500
    neutre.

    Les erreurs HTTP volontaires (404, 405, 413…) gardent leur propre réponse :
    elles portent déjà un statut correct et aucun détail interne.
    """
    from werkzeug.exceptions import HTTPException
    if isinstance(err, HTTPException):
        return err
    app.logger.exception("Erreur non gérée sur %s %s", request.method, request.path)
    return jsonify({"error": "Erreur interne du serveur."}), 500


@app.route("/api/<path:_any>", methods=["OPTIONS"])
def cors_preflight(_any):
    return ("", 204)


@app.route("/api/health")
def health():
    """Sonde de santé — elle VÉRIFIE la base, elle ne se contente pas de dire oui.

    Cette route répondait `{"status":"ok"}` sans rien interroger. Une sonde qui
    ne peut pas échouer ne surveille rien : avec la base injoignable — pooler
    Supabase saturé, réseau coupé, mot de passe tourné — elle aurait continué à
    annoncer « ok », l'hébergeur aurait continué à router du trafic vers un
    dyno incapable de répondre, et la panne n'aurait été signalée que par les
    utilisateurs.

    Le code HTTP est ce que lit la supervision : 200 quand tout répond, 503
    sinon. Le détail reste volontairement pauvre — une sonde est publique, elle
    ne révèle ni version, ni hôte, ni message d'erreur du moteur.
    """
    debut = time.time()
    try:
        conn = db.get_connection()
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
    except Exception:
        app.logger.exception("Sonde de santé : base de données injoignable")
        return jsonify({"status": "degraded", "database": "unreachable"}), 503
    return jsonify({
        "status": "ok",
        "database": "ok",
        "database_latency_ms": round((time.time() - debut) * 1000, 1),
    })


# ---------------------------------------------------------------------------
# Auth (docs/SECURITE.md §4)
# ---------------------------------------------------------------------------

@app.post("/api/auth/register-school")
def register_school():
    """Crée un nouvel établissement (tenant) + son compte Directeur.
    C'est le backend réel derrière le flux "Créer mon espace" déjà présent
    visuellement dans app/inscription.html.
    """
    allowed, retry_after = security.check_rate_limit("register", request.remote_addr, 5, 300)
    if not allowed:
        return jsonify({"error": f"Trop de tentatives. Réessayez dans {retry_after} secondes."}), 429
    security.record_attempt("register", request.remote_addr)

    data = json_object(request.get_json(force=True))
    email = valid_email(data.get("email", ""))
    password = valid_password(data.get("password", ""))
    name = required_text(data.get("name"), "name")
    school_name = required_text(data.get("school_name"), "school_name")
    phone = valid_phone(data.get("phone"))

    conn = db.get_connection()
    if conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
        conn.close()
        return jsonify({"error": "Un compte existe déjà avec cet email"}), 409
    if phone and conn.execute("SELECT id FROM users WHERE phone = ?", (phone,)).fetchone():
        conn.close()
        return jsonify({"error": "Un compte existe déjà avec ce numéro de téléphone"}), 409

    user_id, tenant_id, year_id, membership_id = new_id(), new_id(), new_id(), new_id()
    now = str(time.time())
    slug = school.unique_slug(conn, school_name)
    conn.execute("INSERT INTO users (id, email, phone, password_hash, name, created_at) VALUES (?,?,?,?,?,?)",
                 (user_id, email, phone, security.hash_password(password), name, now))
    conn.execute("INSERT INTO tenants (id, name, status, slug, created_at) VALUES (?,?, 'active', ?, ?)",
                 (tenant_id, school_name, slug, now))
    conn.execute("INSERT INTO memberships (id, user_id, tenant_id, role, created_at) VALUES (?,?,?,'directeur',?)",
                 (membership_id, user_id, tenant_id, now))
    conn.execute("INSERT INTO academic_years (id, tenant_id, label, created_at) VALUES (?,?,?,?)",
                 (year_id, tenant_id, "Année en cours", now))
    conn.commit()
    token = security.create_session(conn, user_id, tenant_id)
    conn.close()
    audit(tenant_id, user_id, "tenant.created", "tenant", tenant_id, "success", after={"school_name": school_name, "slug": slug})
    return jsonify({"token": token, "tenant_id": tenant_id, "role": "directeur", "name": name, "slug": slug}), 201


@app.post("/api/auth/login")
def login():
    data = json_object(request.get_json(force=True))
    # « Identifiant » = email ou numéro de téléphone (beaucoup de parents ont
    # un numéro mais pas d'adresse email). Le compte reste unique par les deux.
    identifier = (data.get("identifier") or data.get("email") or "").strip().lower()
    password = data.get("password", "")

    allowed, retry_after = security.check_login_rate_limit(identifier)
    if not allowed:
        return jsonify({"error": f"Trop de tentatives. Réessayez dans {retry_after} secondes."}), 429

    conn = db.get_connection()
    user = None
    if "@" in identifier:
        user = conn.execute("SELECT * FROM users WHERE email = ?", (identifier,)).fetchone()
    else:
        try:
            phone = valid_phone(identifier)
        except ValidationError:
            phone = None
        if phone:
            user = conn.execute("SELECT * FROM users WHERE phone = ?", (phone,)).fetchone()
    if not user or not security.verify_password(password, user["password_hash"]):
        conn.close()
        security.record_login_failure(identifier)
        # docs/SECURITE.md §15 : une tentative de connexion échouée est un signal de
        # sécurité à part entière, journalié même sans compte associé (email inconnu).
        audit(None, user["id"] if user else None, "auth.login_failed", "user", identifier, "denied")
        return jsonify({"error": "Identifiant ou mot de passe incorrect"}), 401
    membership = conn.execute(
        "SELECT * FROM memberships WHERE user_id = ? AND status='active' ORDER BY created_at LIMIT 1",
        (user["id"],),
    ).fetchone()
    if not membership:
        conn.close()
        return jsonify({"error": "Aucun établissement associé à ce compte"}), 403
    security.clear_login_attempts(identifier)
    token = security.create_session(conn, user["id"], membership["tenant_id"])
    tenant = conn.execute("SELECT slug FROM tenants WHERE id=?", (membership["tenant_id"],)).fetchone()
    conn.close()
    return jsonify({"token": token, "tenant_id": membership["tenant_id"], "role": membership["role"], "name": user["name"],
                    "slug": tenant["slug"] if tenant else None})


@app.post("/api/auth/logout")
@require_auth
def logout():
    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    conn = db.get_connection()
    conn.execute("DELETE FROM sessions WHERE token = ?", (security.hash_session_token(token),))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.get("/api/me")
@require_auth
def me():
    conn = db.get_connection()
    tenant = conn.execute("SELECT * FROM tenants WHERE id = ?", (g.ctx["tenant_id"],)).fetchone()
    settings = school.get_settings(conn, g.ctx["tenant_id"])
    unread = notif_module.summary_for_user(conn, g.ctx["tenant_id"], g.ctx["user_id"])["unread_count"]
    extra = {}
    if g.ctx["role"] == "professeur":
        extra["finance_visible"] = bool(settings["teacher_sees_finance"])
        extra["is_titulaire"] = any(r["is_titulaire"] for r in school.teacher_class_rows(conn, g.ctx))
    user = conn.execute("SELECT email, phone FROM users WHERE id=?", (g.ctx["user_id"],)).fetchone()
    membership = conn.execute("SELECT title, scope_cycles FROM memberships WHERE tenant_id=? AND user_id=?", (g.ctx["tenant_id"], g.ctx["user_id"])).fetchone()
    sub = api_billing.summary(conn, g.ctx["tenant_id"])
    extra["subscription"] = {"status": sub["status"], "attention": sub["attention"] if g.ctx["role"] == "directeur" else None,
                             "read_only": sub["read_only"], "days_left": sub["days_left"]}
    extra["is_platform_admin"] = api_billing.is_platform_admin(conn, g.ctx["user_id"])
    extra["title"] = membership["title"] if membership else None
    if g.ctx["role"] == "discipline":
        extra["scope_cycles"] = school.discipline_scope_cycles(conn, g.ctx)
    if g.ctx["role"] == "professeur":
        cycles = {r["cycle"] for r in school.teacher_class_rows(conn, g.ctx)}
        extra["teaching_level"] = "primaire" if cycles and cycles <= {"maternelle", "primaire"} else ("secondaire" if cycles else None)
    conn.close()
    return jsonify({**g.ctx, "tenant_name": tenant["name"] if tenant else None,
                    "email": school.display_email(user["email"]) if user else None, "phone": user["phone"] if user else None,
                    "branding": school.branding(tenant),
                    "currency": settings["currency"], "unread_notifications": unread, **extra,
                    "permissions": sorted(security.ROLE_PERMISSIONS.get(g.ctx["role"], []))})


@app.post("/api/me/password")
@require_auth
def change_password():
    data = json_object(request.get_json(force=True))
    current = data.get("current_password", "")
    new_password = valid_password(data.get("new_password", ""))

    conn = db.get_connection()
    user = conn.execute("SELECT * FROM users WHERE id=?", (g.ctx["user_id"],)).fetchone()
    if not user or not security.verify_password(current, user["password_hash"]):
        conn.close()
        audit(g.ctx["tenant_id"], g.ctx["user_id"], "user.password_changed", "user", g.ctx["user_id"], "denied")
        return jsonify({"error": "Mot de passe actuel incorrect."}), 401
    conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                 (security.hash_password(new_password), g.ctx["user_id"]))
    # Audit de sécurité : un token volé restait valide jusqu'à 12h après un
    # changement de mot de passe, alors que changer son mot de passe est
    # précisément ce qu'on fait quand on soupçonne une fuite. Toutes les
    # sessions de cet utilisateur sont révoquées ; une nouvelle est émise
    # immédiatement pour que l'onglet courant reste connecté.
    conn.execute("DELETE FROM sessions WHERE user_id=?", (g.ctx["user_id"],))
    new_token = security.create_session(conn, g.ctx["user_id"], g.ctx["tenant_id"])
    conn.commit()
    conn.close()
    audit(g.ctx["tenant_id"], g.ctx["user_id"], "user.password_changed", "user", g.ctx["user_id"], "success")
    return jsonify({"ok": True, "token": new_token})


# ---------------------------------------------------------------------------
# Audit de sécurité : POST /api/users (création directe professeur/parent/élève
# par le directeur) a été RETIRÉE ici. C'était une route morte — aucun code
# frontend ne l'appelait (vérifié par recherche complète) — laissée par
# inadvertance après la refonte vers le modèle "invitation obligatoire"
# (voir /api/invitations). Elle permettait de créer un compte rôle "eleve",
# ce que la décision produit interdit explicitement, et contournait
# entièrement le token d'invitation à usage unique/traçable/révocable.
# Le chemin réel de création est désormais uniquement : POST /api/invitations
# (docs point 14 : le rôle vient toujours de l'invitation, jamais du client).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# School Core : années, classes, élèves, responsables
# ---------------------------------------------------------------------------

@app.post("/api/academic-years")
@require_auth
@require_permission("academic_years.manage")
def create_academic_year():
    data = json_object(request.get_json(force=True))
    # Trouvé à l'audit : `data["label"]` sur un corps sans « label » levait un
    # KeyError, donc un 500. Un champ obligatoire absent est une faute du
    # client, pas une panne du serveur : c'est un 400 avec le nom du champ.
    label = required_text(data.get("label"), "label")
    conn = db.get_connection()
    yid = new_id()
    # Une SECONDE année ne prend pas la main sur celle qui tourne.
    #
    # `academic_years.is_active` vaut 1 par défaut, et `_active_year()` retient
    # la plus récente parmi les actives : créer 2027-2028 pour la préparer
    # faisait donc immédiatement basculer tout l'établissement dessus — classes
    # vides, élèves invisibles, en pleine année scolaire. La première année d'un
    # établissement reste ACTIVE ; les suivantes naissent en PRÉPARATION et
    # n'apparaissent qu'au passage d'année.
    premiere = not conn.execute("SELECT 1 FROM academic_years WHERE tenant_id=?",
                                (g.ctx["tenant_id"],)).fetchone()
    statut = "ACTIVE" if premiere else "PREPARATION"
    conn.execute(
        """INSERT INTO academic_years (id, tenant_id, label, is_active, status, created_at)
           VALUES (?,?,?,?,?,?)""",
        (yid, g.ctx["tenant_id"], label, 1 if premiere else 0, statut, str(time.time())))
    conn.commit()
    conn.close()
    return jsonify({"id": yid, "label": label, "status": statut}), 201


@app.get("/api/academic-years")
@require_auth
def list_academic_years():
    conn = db.get_connection()
    rows = conn.execute("SELECT * FROM academic_years WHERE tenant_id = ? ORDER BY created_at",
                         (g.ctx["tenant_id"],)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.post("/api/classes")
@require_auth
@require_permission("classes.manage")
def create_class():
    data = json_object(request.get_json(force=True))
    class_name = required_text(data.get("name"), "name", max_length=100)
    # Champ obligatoire, validé avant usage : sans cela un corps portant « name »
    # mais pas « academic_year_id » levait un KeyError, donc un 500.
    academic_year_id = required_text(data.get("academic_year_id"), "academic_year_id")
    conn = db.get_connection()
    # Vérifie que l'année scolaire référencée appartient bien à CE tenant (docs/MULTI_TENANT.md §10.4)
    year = conn.execute("SELECT id FROM academic_years WHERE id = ? AND tenant_id = ?",
                         (academic_year_id, g.ctx["tenant_id"])).fetchone()
    if not year:
        conn.close()
        return jsonify({"error": "Année scolaire introuvable pour cet établissement"}), 404
    cid = new_id()
    level = (data.get("level") or "").strip() or None
    # DÉCLARÉ ou DÉDUIT — la différence est enregistrée, pas seulement subie.
    # Un cycle choisi par l'établissement fait foi et ne sera jamais recalculé ;
    # un cycle deviné reste provisoire, s'affiche comme à confirmer, et se
    # recopie tel quel au passage d'année plutôt que d'être redeviné.
    if data.get("cycle") in ("maternelle", "primaire", "secondaire"):
        cycle, source = data["cycle"], "declare"
    else:
        cycle, source = school.infer_cycle(level, class_name), "deduit"
    conn.execute(
        """INSERT INTO classes (id, tenant_id, academic_year_id, name, level, cycle, cycle_source, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (cid, g.ctx["tenant_id"], academic_year_id, class_name, level, cycle, source, str(time.time())))
    conn.commit()
    conn.close()
    return jsonify({"id": cid, "name": class_name, "cycle": cycle, "cycle_source": source}), 201


@app.get("/api/classes")
@require_auth
def list_classes():
    """Classes VISIBLES par le rôle (Direction : toutes ; DD : secondaire ;
    professeur : rattachées ; parent : celles de ses enfants), enrichies des
    effectifs, du titulaire et de l'état de l'appel du jour."""
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    allowed = school.visible_class_ids(conn, g.ctx)
    where, params = "c.tenant_id = ?", [tenant_id]
    # LES CLASSES DE L'ANNÉE EN COURS, pas de toutes les années.
    #
    # Tant qu'aucun établissement n'avait franchi une année, la distinction
    # n'existait pas. Au premier passage d'année, la liste montrait côte à côte
    # la « 5e Scientifique A » de l'année écoulée — vidée de ses élèves — et
    # celle de la nouvelle : deux classes de même nom, dont une fantôme. Une
    # année précise reste consultable en la demandant explicitement.
    demandee = request.args.get("academic_year_id")
    if demandee:
        annee = conn.execute("SELECT id FROM academic_years WHERE id=? AND tenant_id=?",
                             (demandee, tenant_id)).fetchone()
        if not annee:
            conn.close()
            return jsonify({"error": "Année scolaire introuvable pour cet établissement"}), 404
        where += " AND c.academic_year_id = ?"
        params.append(demandee)
    else:
        courante = conn.execute(
            """SELECT id FROM academic_years WHERE tenant_id=?
                ORDER BY is_active DESC, created_at DESC LIMIT 1""", (tenant_id,)).fetchone()
        if courante:
            where += " AND c.academic_year_id = ?"
            params.append(courante["id"])
    if allowed is not None:
        if not allowed:
            conn.close()
            return jsonify([])
        where += f" AND c.id IN ({','.join('?' for _ in allowed)})"
        params += allowed
    today = school.today_iso()
    rows = conn.execute(
        f"""SELECT c.*,
                   -- Chaque sous-requête filtre sur tenant_id, colonne de TÊTE des
                   -- index concernés. Sans elle la table entière est balayée : sur
                   -- attendance, qui grossit d'environ 10 000 lignes par jour de
                   -- classe, cette page cessait de répondre vers janvier.
                   (SELECT COUNT(*) FROM students s WHERE s.tenant_id = c.tenant_id AND s.class_id = c.id AND s.status = 'active') AS student_count,
                   (SELECT u.name FROM class_teachers ct JOIN users u ON u.id = ct.user_id
                    WHERE ct.tenant_id = c.tenant_id AND ct.class_id = c.id AND ct.is_titulaire = 1 LIMIT 1) AS titulaire_name,
                   (SELECT COUNT(*) FROM class_teachers ct WHERE ct.tenant_id = c.tenant_id AND ct.class_id = c.id) AS teacher_count,
                   (SELECT COUNT(*) FROM attendance a WHERE a.tenant_id = c.tenant_id AND a.class_id = c.id AND a.date = ?) AS attendance_recorded_today,
                   (SELECT COUNT(*) FROM attendance a WHERE a.tenant_id = c.tenant_id AND a.class_id = c.id AND a.date = ? AND a.status = 'absent') AS absent_today
            FROM classes c WHERE {where} ORDER BY c.name""",
        [today, today] + params,
    ).fetchall()
    result = [dict(r) for r in rows]
    if g.ctx["role"] == "professeur":
        mine = {r["id"]: r for r in school.teacher_class_rows(conn, g.ctx)}
        for d in result:
            d["is_titulaire"] = bool(mine.get(d["id"]) and mine[d["id"]]["is_titulaire"])
            d["subject"] = mine[d["id"]]["subject"] if mine.get(d["id"]) else None
    conn.close()
    return jsonify(result)


@app.post("/api/students")
@require_auth
@require_permission("students.create")
def create_student():
    data = json_object(request.get_json(force=True))
    first_name = required_text(data.get("first_name"), "first_name", max_length=100)
    last_name = required_text(data.get("last_name"), "last_name", max_length=100)
    # Idem create_class : obligatoire, donc validé, jamais lu à cru.
    academic_year_id = required_text(data.get("academic_year_id"), "academic_year_id")
    conn = db.get_connection()
    year = conn.execute("SELECT id FROM academic_years WHERE id = ? AND tenant_id = ?",
                         (academic_year_id, g.ctx["tenant_id"])).fetchone()
    if not year:
        conn.close()
        return jsonify({"error": "Année scolaire introuvable pour cet établissement"}), 404
    class_id = data.get("class_id") or None
    if class_id and not conn.execute("SELECT 1 FROM classes WHERE id=? AND tenant_id=?", (class_id, g.ctx["tenant_id"])).fetchone():
        conn.close()
        return jsonify({"error": "Classe introuvable pour cet établissement"}), 404
    gender = data.get("gender") if data.get("gender") in ("F", "M") else None
    birth_date = data.get("birth_date") if isinstance(data.get("birth_date"), str) and api_school.ISO_DATE.match(data.get("birth_date")) else None
    sid = new_id()
    code = school.generate_student_code(conn, g.ctx["tenant_id"])
    conn.execute(
        """INSERT INTO students (id, tenant_id, academic_year_id, class_id, first_name, last_name, code, gender, birth_date, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (sid, g.ctx["tenant_id"], academic_year_id, class_id,
         first_name, last_name, code, gender, birth_date, str(time.time())),
    )
    conn.commit()
    conn.close()
    audit(g.ctx["tenant_id"], g.ctx["user_id"], "student.created", "student", sid, "success", after={"code": code})
    return jsonify({"id": sid, "code": code}), 201


# Le contrôle d'accès à UN élève précis vit dans school.resolve_student_access
# (Direction : tout ; DD : secondaire ; professeur : classes rattachées ;
# parent : ses enfants) — unique point de décision pour toutes les routes.
_resolve_student_access = school.resolve_student_access


@app.get("/api/students")
@require_auth
def list_students():
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    where, params = school.students_where_clause(conn, g.ctx)
    if where is None:
        conn.close()
        return jsonify([])
    show_finance = school.finance_visible(conn, g.ctx)
    today = school.today_iso()
    # Une seule requête agrégée pour le solde de chaque élève — jamais une boucle
    # N+1 côté serveur, important dès qu'un établissement compte des centaines
    # d'élèves (docs/FINANCE.md §16.1 : le solde vient toujours du Financial Core,
    # ici calculé en base plutôt qu'en Python pour rester performant à l'échelle).
    rows = conn.execute(
        f"""SELECT s.id, s.code, s.first_name, s.last_name, s.gender, s.birth_date, s.status, s.class_id, s.created_at,
                   s.photo_data IS NOT NULL AS has_photo,
                   c.name AS class_name, c.cycle AS class_cycle,
                   a.status AS today_status,
                   COALESCE(ob.total_due, 0) AS total_due,
                   COALESCE(pay.total_paid, 0) AS total_paid
            FROM students s
            LEFT JOIN classes c ON c.id = s.class_id
            LEFT JOIN attendance a ON a.student_id = s.id AND a.tenant_id = s.tenant_id AND a.date = ?
            LEFT JOIN (SELECT student_id, SUM(amount) AS total_due FROM obligations
                       WHERE tenant_id = ? GROUP BY student_id) ob ON ob.student_id = s.id
            LEFT JOIN (SELECT o.student_id AS student_id, SUM(p.amount) AS total_paid
                       FROM payments p JOIN obligations o ON o.id = p.obligation_id
                       WHERE p.tenant_id = ? AND p.status = 'CONFIRMED' GROUP BY o.student_id) pay
                   ON pay.student_id = s.id
            WHERE {where}
            ORDER BY s.last_name, s.first_name""",
        (today, tenant_id, tenant_id, *params),
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        if show_finance:
            d["balance"] = round((d["total_due"] or 0) - (d["total_paid"] or 0), 2)
        else:
            d.pop("total_due", None); d.pop("total_paid", None)
        result.append(d)
    return jsonify(result)


@app.get("/api/students/<student_id>/financial-summary")
@require_auth
def student_financial_summary(student_id):
    conn = db.get_connection()
    student = _resolve_student_access(conn, g.ctx, student_id)
    if not student or not school.finance_visible(conn, g.ctx):
        conn.close()
        audit(g.ctx["tenant_id"], g.ctx["user_id"], "student.financial_summary", "student", student_id, "denied")
        return jsonify({"error": "Élève introuvable ou accès non autorisé"}), 404
    summary = financial.financial_summary(conn, g.ctx["tenant_id"], student_id)
    summary["first_name"] = student["first_name"]
    summary["last_name"] = student["last_name"]
    conn.close()
    return jsonify(summary)


@app.post("/api/guardians")
@require_auth
@require_permission("students.create")
def create_guardian():
    data = json_object(request.get_json(force=True))
    first_name = required_text(data.get("first_name"), "first_name", max_length=100)
    last_name = required_text(data.get("last_name"), "last_name", max_length=100)
    conn = db.get_connection()
    link_user_id = data.get("link_user_id")
    if link_user_id:
        m = conn.execute("SELECT 1 FROM memberships WHERE user_id = ? AND tenant_id = ?",
                          (link_user_id, g.ctx["tenant_id"])).fetchone()
        if not m:
            conn.close()
            return jsonify({"error": "link_user_id ne correspond à aucun utilisateur de cet établissement"}), 400
    gid = new_id()
    conn.execute(
        """INSERT INTO guardians (id, tenant_id, first_name, last_name, phone, email, user_id, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (gid, g.ctx["tenant_id"], first_name, last_name,
         data.get("phone"), data.get("email"), link_user_id, str(time.time())),
    )
    conn.commit()
    conn.close()
    return jsonify({"id": gid}), 201


@app.post("/api/students/<student_id>/guardians")
@require_auth
@require_permission("students.create")
def link_guardian(student_id):
    data = json_object(request.get_json(force=True))
    guardian_id = required_text(data.get("guardian_id"), "guardian_id")  # sinon KeyError → 500
    conn = db.get_connection()
    student = conn.execute("SELECT id FROM students WHERE id=? AND tenant_id=?",
                            (student_id, g.ctx["tenant_id"])).fetchone()
    guardian = conn.execute("SELECT id FROM guardians WHERE id=? AND tenant_id=?",
                             (guardian_id, g.ctx["tenant_id"])).fetchone()
    if not student or not guardian:
        conn.close()
        return jsonify({"error": "Élève ou responsable introuvable pour cet établissement"}), 404
    conn.execute("INSERT INTO student_guardians (id, tenant_id, student_id, guardian_id, relationship) VALUES (?,?,?,?,?)",
                 (new_id(), g.ctx["tenant_id"], student_id, guardian_id, data.get("relationship")))
    conn.commit()
    conn.close()
    return jsonify({"ok": True}), 201


# ---------------------------------------------------------------------------
# Financial Core : catalogue, obligations, paiements
# ---------------------------------------------------------------------------

@app.post("/api/catalog-items")
@require_auth
@require_permission("catalog.manage")
def create_catalog_item():
    data = json_object(request.get_json(force=True))
    name = required_text(data.get("name"), "name")
    amount = positive_amount(data.get("amount"))
    conn = db.get_connection()
    cid = new_id()
    conn.execute("INSERT INTO catalog_items (id, tenant_id, name, category, amount, currency, created_at) VALUES (?,?,?,?,?,?,?)",
                 (cid, g.ctx["tenant_id"], name, data.get("category", "frais"),
                  amount, data.get("currency", "USD"), str(time.time())))
    conn.commit()
    conn.close()
    return jsonify({"id": cid}), 201


@app.get("/api/catalog-items")
@require_auth
@require_permission("store.read")
def list_catalog_items():
    """Catalogue des frais et articles de l'établissement.

    Cette route n'avait AUCUNE vérification de permission, seule de toutes les
    lectures financières : un professeur ou un DD y lisait la grille tarifaire
    complète, montants compris, alors que `school.finance_visible` reste fermé
    pour eux. Ce n'est pas la situation d'une famille, mais c'est bien de
    l'argent, et l'écart avec les autres routes n'était pas voulu.

    `store.read` colle exactement : la Direction et les parents l'ont — les
    parents en ont besoin pour la Boutique, où ces prix leur sont destinés —
    le professeur et le DD ne l'ont pas.
    """
    conn = db.get_connection()
    rows = conn.execute("SELECT * FROM catalog_items WHERE tenant_id = ?", (g.ctx["tenant_id"],)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.post("/api/obligations")
@require_auth
@require_permission("obligations.create")
def create_obligation():
    data = json_object(request.get_json(force=True))
    # Champs obligatoires validés avant toute requête : un corps incomplet est
    # un 400 nommant le champ, pas un 500. Route financière — voir aussi
    # /api/payments plus bas.
    student_id = required_text(data.get("student_id"), "student_id")
    catalog_item_id = required_text(data.get("catalog_item_id"), "catalog_item_id")
    academic_year_id = required_text(data.get("academic_year_id"), "academic_year_id")
    conn = db.get_connection()
    student = conn.execute("SELECT id FROM students WHERE id=? AND tenant_id=?",
                            (student_id, g.ctx["tenant_id"])).fetchone()
    item = conn.execute("SELECT * FROM catalog_items WHERE id=? AND tenant_id=?",
                         (catalog_item_id, g.ctx["tenant_id"])).fetchone()
    year = conn.execute("SELECT id FROM academic_years WHERE id=? AND tenant_id=?",
                         (academic_year_id, g.ctx["tenant_id"])).fetchone()
    if not student or not item or not year:
        conn.close()
        return jsonify({"error": "Élève, article de catalogue ou année scolaire introuvable pour cet établissement"}), 404
    oid = new_id()
    amount = positive_amount(data.get("amount", item["amount"]))
    conn.execute(
        """INSERT INTO obligations (id, tenant_id, student_id, academic_year_id, catalog_item_id, amount, currency, due_date, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (oid, g.ctx["tenant_id"], student_id, academic_year_id, catalog_item_id,
         amount, item["currency"], data.get("due_date"), str(time.time())),
    )
    conn.commit()
    conn.close()
    events_module.emit(db.get_connection(), g.ctx["tenant_id"], "obligation.created", "obligation", oid, g.ctx["user_id"],
                        payload={"student_id": student_id, "amount": amount})
    audit(g.ctx["tenant_id"], g.ctx["user_id"], "obligation.created", "obligation", oid, "success", after={"amount": amount})
    return jsonify({"id": oid, "amount": amount}), 201


@app.post("/api/obligations/schedule")
@require_auth
@require_permission("obligations.create")
def create_obligation_schedule():
    """Crée un frais RÉPARTI EN TRANCHES, en une seule transaction.

    Une tranche n'est pas un objet nouveau : c'est une obligation de plus, avec
    sa propre échéance. Cette route n'ajoute donc aucun modèle — elle apporte
    les deux choses que N appels séparés à /api/obligations ne peuvent pas
    donner :

    1. LA SOMME EST VÉRIFIÉE PAR LE SERVEUR. L'écran la contrôlait, et lui seul :
       un client modifié pouvait créer trois tranches de 100 pour un frais de
       1 000, et la dette de l'élève devenait 300 sans que rien ne proteste.
    2. C'EST TOUT OU RIEN. En N appels, la troisième tranche pouvait échouer
       après que les deux premières aient été écrites : l'échéancier restait
       incomplet en base, et l'écran devait raconter un demi-succès.

    Le nombre de tranches n'est pas fixé : de 1 à 24, c'est l'établissement qui
    décide. Une seule tranche est simplement un frais payable en une fois.
    """
    data = json_object(request.get_json(force=True))
    student_id = required_text(data.get("student_id"), "student_id")
    catalog_item_id = required_text(data.get("catalog_item_id"), "catalog_item_id")
    academic_year_id = required_text(data.get("academic_year_id"), "academic_year_id")
    tranches = data.get("installments")
    if not isinstance(tranches, list) or not tranches:
        raise ValidationError("installments doit être une liste d'au moins une tranche.")
    if len(tranches) > 24:
        raise ValidationError("Un frais ne peut pas être réparti en plus de 24 tranches.")

    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    student = conn.execute("SELECT id FROM students WHERE id=? AND tenant_id=?", (student_id, tenant_id)).fetchone()
    item = conn.execute("SELECT * FROM catalog_items WHERE id=? AND tenant_id=?", (catalog_item_id, tenant_id)).fetchone()
    year = conn.execute("SELECT id FROM academic_years WHERE id=? AND tenant_id=?", (academic_year_id, tenant_id)).fetchone()
    if not student or not item or not year:
        conn.close()
        return jsonify({"error": "Élève, article de catalogue ou année scolaire introuvable pour cet établissement"}), 404

    lignes = []
    for i, t in enumerate(tranches, start=1):
        if not isinstance(t, dict):
            conn.close()
            raise ValidationError(f"Tranche {i} invalide.")
        montant = positive_amount(t.get("amount"), f"amount (tranche {i})")
        echeance = t.get("due_date") or None
        if echeance is not None and not isinstance(echeance, str):
            conn.close()
            raise ValidationError(f"due_date invalide pour la tranche {i}.")
        lignes.append((montant, echeance))

    # Le total est celui de l'établissement s'il l'a précisé, sinon le prix du
    # catalogue. La somme des tranches doit tomber dessus au centime près : un
    # écart d'un cent laisserait une dette que personne ne peut solder.
    total = positive_amount(data.get("total"), "total") if data.get("total") is not None else float(item["amount"])
    somme = round(sum(m for m, _ in lignes), 2)
    if abs(somme - round(float(total), 2)) > 0.01:
        conn.close()
        raise ValidationError(
            f"La somme des tranches ({somme:g}) ne correspond pas au total du frais ({round(float(total), 2):g})."
        )

    now = str(time.time())
    ids = []
    try:
        for montant, echeance in lignes:
            oid = new_id()
            conn.execute(
                """INSERT INTO obligations (id, tenant_id, student_id, academic_year_id, catalog_item_id, amount, currency, due_date, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (oid, tenant_id, student_id, academic_year_id, catalog_item_id,
                 montant, item["currency"], echeance, now),
            )
            ids.append({"id": oid, "amount": montant, "due_date": echeance})
        conn.commit()
    except Exception:
        # Tout ou rien : un échéancier à moitié écrit est pire qu'aucun.
        conn.rollback()
        conn.close()
        raise
    conn.close()

    for o in ids:
        events_module.emit(db.get_connection(), tenant_id, "obligation.created", "obligation", o["id"], g.ctx["user_id"],
                           payload={"student_id": student_id, "amount": o["amount"]})
    audit(tenant_id, g.ctx["user_id"], "obligation.schedule_created", "student", student_id, "success",
          after={"installments": len(ids), "total": round(float(total), 2)})
    return jsonify({"installments": ids, "total": round(float(total), 2), "count": len(ids)}), 201


# ---------------------------------------------------------------------------
# Suppression de compte — l'utilisateur, pas l'établissement
# ---------------------------------------------------------------------------

@app.post("/api/me/delete")
@require_auth
def delete_my_account():
    """Suppression du COMPTE UTILISATEUR de la personne connectée.

    La distinction la plus importante de cette route, et la raison de chaque
    ligne qui suit :

        compte utilisateur  ≠  dossier élève  ≠  données de l'établissement
                            ≠  transaction    ≠  journal d'audit

    Ce qui est supprimé : l'identité de connexion de la personne — son nom, son
    email, son téléphone, son mot de passe, ses sessions, ses conversations
    avec l'assistant. Elle ne peut plus entrer, et Klassio ne conserve plus ses
    coordonnées personnelles.

    Ce qui n'est PAS supprimé, et ne doit jamais l'être :
      • les élèves, leurs dossiers, résultats, présences, incidents ;
      • les paiements, reçus et écritures comptables — un reçu est une pièce
        officielle émise par l'établissement, pas une donnée personnelle du
        parent qui l'a déclenché ; l'effacer falsifierait la comptabilité ;
      • le journal d'audit — il existe précisément pour survivre à la
        disparition de l'acteur ;
      • le membership, qui devient `deleted` et garde la trace du passage.

    Un DIRECTEUR ne peut pas se supprimer s'il est le dernier de son
    établissement : une école sans accès Direction devient inadministrable,
    et personne ne pourrait plus y rouvrir quoi que ce soit — ni pour les
    familles, ni pour les enseignants.
    """
    data = json_object(request.get_json(force=True))
    mot_de_passe = data.get("password")
    if not isinstance(mot_de_passe, str) or not mot_de_passe:
        raise ValidationError("Votre mot de passe est requis pour confirmer la suppression.")

    conn = db.get_connection()
    tenant_id, user_id = g.ctx["tenant_id"], g.ctx["user_id"]
    utilisateur = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not utilisateur or not security.verify_password(mot_de_passe, utilisateur["password_hash"]):
        conn.close()
        audit(tenant_id, user_id, "account.delete", "user", user_id, "denied")
        return jsonify({"error": "Mot de passe incorrect."}), 401

    if g.ctx["role"] == "directeur":
        autres = conn.execute(
            "SELECT COUNT(*) n FROM memberships WHERE tenant_id=? AND role='directeur' AND status='active' AND user_id<>?",
            (tenant_id, user_id)).fetchone()["n"]
        if not autres:
            conn.close()
            return jsonify({"error": "Vous êtes la seule Direction de cet établissement. "
                                     "Nommez d'abord une autre Direction — sans elle, l'espace deviendrait "
                                     "inadministrable pour les familles et les enseignants."}), 409

    maintenant = str(time.time())
    # Le membership garde la trace : qui a eu accès, et jusqu'à quand.
    conn.execute("UPDATE memberships SET status='deleted', revoked_at=? WHERE user_id=?",
                 (maintenant, user_id))
    conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    # Un responsable légal reste une personne de l'établissement (l'école a
    # besoin de savoir qui répond de l'élève) : on ne détache que le COMPTE.
    conn.execute("UPDATE guardians SET user_id=NULL WHERE user_id=?", (user_id,))
    # Les échanges avec l'assistant sont personnels : ils partent.
    conn.execute("DELETE FROM ai_messages WHERE conversation_id IN "
                 "(SELECT id FROM ai_conversations WHERE user_id=?)", (user_id,))
    conn.execute("DELETE FROM ai_conversations WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM password_resets WHERE user_id=?", (user_id,))
    # L'identité est neutralisée plutôt que la ligne supprimée : des clés
    # étrangères pointent dessus (paiements enregistrés, audits, invitations),
    # et les casser abîmerait des écritures que la loi et la comptabilité
    # obligent à conserver.
    conn.execute(
        "UPDATE users SET name='Compte supprimé', email=?, phone=NULL, password_hash=?, deleted_at=? WHERE id=?",
        ("supprime+" + user_id[:12] + "@klassio.invalid", "!", maintenant, user_id))
    conn.commit()
    conn.close()
    audit(tenant_id, user_id, "account.deleted", "user", user_id, "success",
          after={"role": g.ctx["role"]})
    return jsonify({"ok": True, "message": "Votre compte a été supprimé. Les données de l'établissement, "
                                           "les dossiers des élèves et les pièces comptables sont conservés "
                                           "par l'établissement, comme la loi l'exige."})


# ---------------------------------------------------------------------------
# Contact public — la seule route d'écriture SANS authentification
# ---------------------------------------------------------------------------

CONTACT_KINDS = ("question", "probleme", "suggestion", "commercial")


@app.post("/api/public/contact")
def public_contact():
    """Formulaire de contact du site public.

    C'est la seule route d'écriture accessible sans compte : elle est donc
    traitée comme telle. Quatre gardes, et aucune n'est décorative :

    1. LIMITE DE DÉBIT par adresse IP — 5 messages par heure. Sans elle, un
       formulaire public ouvert est une boîte à spam, et la table grossit
       jusqu'à ce que quelqu'un s'en aperçoive.
    2. TAILLES BORNÉES à l'écriture. Un message de 10 Mo n'est pas un message.
    3. AUCUN HTML n'est interprété : le contenu est stocké tel quel et
       ré-affiché via `UI.escapeHtml` côté administration. On ne « nettoie »
       pas le texte de quelqu'un, on refuse simplement de l'exécuter.
    4. AUCUNE DONNÉE D'ÉTABLISSEMENT n'est lue ni renvoyée. La réponse ne
       confirme que la réception — elle ne dit jamais si l'adresse correspond
       à un compte existant, ce qui révélerait qui est client de Klassio.
    """
    ip = (request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
          or request.remote_addr or "inconnu")
    autorise, retry = security.check_rate_limit("contact", ip, 5, 3600)
    if not autorise:
        return jsonify({"error": f"Trop de messages envoyés. Réessayez dans {retry // 60 + 1} minute(s)."}), 429

    data = json_object(request.get_json(force=True))
    nom = required_text(data.get("name"), "name", 120)
    email = required_text(data.get("email"), "email", 200)
    sujet = required_text(data.get("subject"), "subject", 200)
    message = required_text(data.get("message"), "message", 5000)
    if len(message.strip()) < 10:
        raise ValidationError("Votre message est trop court pour qu'on puisse y répondre utilement.")
    if "@" not in email or "." not in email.split("@")[-1]:
        raise ValidationError("Cette adresse email ne semble pas valide.")
    kind = data.get("kind") if data.get("kind") in CONTACT_KINDS else "question"
    ecole = (data.get("school") or "").strip()[:200] or None

    security.record_attempt("contact", ip)
    conn = db.get_connection()
    conn.execute(
        """INSERT INTO contact_requests (id, name, email, subject, kind, school, message, status, created_at)
           VALUES (?,?,?,?,?,?,?, 'new', ?)""",
        (new_id(), nom, email, sujet, kind, ecole, message, str(time.time())))
    conn.commit()
    conn.close()
    # Réponse volontairement neutre : elle ne révèle rien sur l'existence d'un
    # compte derrière cette adresse.
    return jsonify({"ok": True, "message": "Votre message a bien été reçu. Nous revenons vers vous par email."}), 201


@app.get("/api/platform/contact-requests")
@require_auth
def list_contact_requests():
    """Lecture des demandes publiques — administration Klassio uniquement."""
    conn = db.get_connection()
    if not api_billing.is_platform_admin(conn, g.ctx["user_id"]):
        conn.close()
        audit(g.ctx["tenant_id"], g.ctx["user_id"], "contact.list", status="denied")
        return jsonify({"error": "Réservé à l'administration Klassio."}), 403
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM contact_requests ORDER BY created_at DESC LIMIT 200")]
    conn.close()
    return jsonify(rows)


@app.post("/api/payments")
@require_auth
def create_payment_route():
    """Un paiement cash/banque enregistré par le personnel est confirmé
    immédiatement — c'est la personne qui l'enregistre qui EST la preuve
    (docs/FINANCE.md §7.1). Un paiement mobile_money reste en attente d'une
    vérification serveur séparée (POST /payments/:id/confirm), cohérent avec
    la règle "le clic sur Payer n'est jamais une preuve" pour un canal où la
    confirmation vient réellement d'un tiers.

    Un PARENT peut initier un paiement pour son propre enfant, uniquement en
    mobile_money : il reste CREATED jusqu'à confirmation par l'établissement
    (aucune intégration Mobile Money réelle n'existe — jamais de faux succès).
    """
    data = json_object(request.get_json(force=True))
    # Trouvé à l'audit : `data["obligation_id"]`, `data["amount"]` et
    # `data["idempotency_key"]` étaient lus sans garde — un corps incomplet
    # donnait un KeyError, donc un 500, sur la route la plus sensible du
    # produit. La clé d'idempotence en particulier ne doit JAMAIS être
    # facultative : sans elle, deux clics valent deux paiements.
    obligation_id = required_text(data.get("obligation_id"), "obligation_id")
    positive_amount(data.get("amount"), "amount")
    idempotency_key = required_text(data.get("idempotency_key"), "idempotency_key", max_length=200)
    method = data.get("method", "cash")
    role = g.ctx["role"]
    if role == "directeur":
        if not security.has_permission(role, "payments.create"):
            return jsonify({"error": "Vous n'avez pas l'autorisation d'effectuer cette action."}), 403
    elif role == "parent" and security.has_permission(role, "payments.create.own"):
        if method != "mobile_money":
            return jsonify({"error": "Depuis votre espace, seul un paiement Mobile Money peut être initié — les paiements en espèces ou banque sont enregistrés par l'établissement."}), 400
        conn_check = db.get_connection()
        ob = conn_check.execute("SELECT student_id FROM obligations WHERE id=? AND tenant_id=?", (obligation_id, g.ctx["tenant_id"])).fetchone()
        allowed = ob and school.resolve_student_access(conn_check, g.ctx, ob["student_id"])
        conn_check.close()
        if not allowed:
            audit(g.ctx["tenant_id"], g.ctx["user_id"], "payment.create", "obligation", data.get("obligation_id"), "denied")
            return jsonify({"error": "Obligation introuvable ou non rattachée à votre compte."}), 404
    else:
        audit(g.ctx["tenant_id"], g.ctx["user_id"], "permission_check:payments.create", status="denied")
        return jsonify({"error": "Vous n'avez pas l'autorisation d'effectuer cette action."}), 403
    conn = db.get_connection()
    try:
        payment, created = financial.create_payment(
            conn, g.ctx["tenant_id"], obligation_id, data["amount"],
            method, idempotency_key, g.ctx["user_id"],
        )
        # Toujours la méthode ENREGISTRÉE, jamais celle du JSON courant :
        # un rejeu d'idempotence (ou une clé réutilisée) ne doit pas pouvoir
        # confirmer un mobile_money encore CREATED en renvoyant method=cash.
        if role == "directeur" and payment["method"] in ("cash", "bank") and payment["status"] == "CREATED":
            payment = financial.confirm_payment(
                conn, g.ctx["tenant_id"], payment["id"], "RECORDED_IN_PERSON", g.ctx["user_id"]
            )
    except ValidationError:
        conn.close()
        raise  # trouvé par pentest : ValidationError hérite de ValueError — sans ce
               # cas séparé, il était avalé par le except générique ci-dessous et
               # renvoyait 404 au lieu de 400. Ici on le laisse remonter au handler
               # global @app.errorhandler(ValidationError).
    except ValueError as e:
        conn.close()
        return jsonify({"error": str(e)}), 404
    conn.close()
    return jsonify(payment), (201 if created else 200)


@app.post("/api/payments/<payment_id>/confirm")
@require_auth
@require_permission("payments.confirm")
def confirm_payment_route(payment_id):
    """Simule la vérification serveur d'un fournisseur de paiement (docs/FINANCE.md §9.4).
    Aucune intégration Mobile Money réelle n'existe encore — voir rapport final : cette
    route tient la place d'un webhook réel, elle applique déjà toutes les règles
    d'idempotence et de traçabilité qui s'appliqueront à un vrai webhook plus tard.
    """
    data = json_object(request.get_json(silent=True))
    conn = db.get_connection()
    try:
        payment = financial.confirm_payment(
            conn, g.ctx["tenant_id"], payment_id, data.get("provider_reference", "MANUAL"), g.ctx["user_id"]
        )
    except ValidationError:
        conn.close()
        raise  # même raison qu'à la création : ValidationError hérite de ValueError.
               # Sans ce cas séparé, « ce paiement dépasse ce qui reste dû » serait
               # renvoyé en 404 « introuvable » — un message faux pour le guichet.
    except ValueError as e:
        conn.close()
        return jsonify({"error": str(e)}), 404
    conn.close()
    return jsonify(payment)


# ---------------------------------------------------------------------------
# Dashboard (agrège le Financial Core — ne recalcule jamais rien lui-même)
# ---------------------------------------------------------------------------

def _attendance_totals(conn, tenant_id, day, class_ids=None):
    where, params = "a.tenant_id=? AND a.date=?", [tenant_id, day]
    if class_ids is not None:
        if not class_ids:
            return {"present": 0, "late": 0, "absent": 0, "excused": 0, "recorded": 0}
        where += f" AND a.class_id IN ({','.join('?' for _ in class_ids)})"
        params += class_ids
    r = conn.execute(f"""SELECT SUM(CASE WHEN status='present' THEN 1 ELSE 0 END) p, SUM(CASE WHEN status='late' THEN 1 ELSE 0 END) l, SUM(CASE WHEN status='absent' THEN 1 ELSE 0 END) a2, SUM(CASE WHEN status='excused' THEN 1 ELSE 0 END) e, COUNT(*) n
                         FROM attendance a WHERE {where}""", params).fetchone()
    return {"present": r["p"] or 0, "late": r["l"] or 0, "absent": r["a2"] or 0, "excused": r["e"] or 0, "recorded": r["n"] or 0}


def _prochaine_proclamation(conn, tenant_id, year_id, division):
    """La prochaine période dont les résultats seront proclamés, pour cette
    division — telle que l'établissement l'a déclarée.

    Deux règles, et elles disent la même chose : ne rien promettre au nom de
    l'école.

    1. On ne renvoie une DATE que si la Direction en a saisi une. Sans date, le
       parent apprend seulement quelle période vient — pas quand. Annoncer
       « bientôt » serait un engagement que personne n'a pris.
    2. Un brouillon ou une période archivée ne compte pas : le premier n'est
       pas proclamable, la seconde ne le sera plus.

    Renvoie None quand tout est déjà proclamé : il n'y a alors rien à attendre,
    et un encadré vide vaut mieux qu'un encadré qui invente.
    """
    if not year_id:
        return None
    for p in school.periods_for_year(conn, tenant_id, year_id, division):
        if p.get("published_at"):
            continue
        if (p.get("admin_state") or "READY").upper() in ("DRAFT", "ARCHIVED"):
            continue
        return {"label": p["label"], "proclamation_at": p.get("proclamation_at"),
                "ends_on": p.get("ends_on"), "state": p["state"]}
    return None


@app.get("/api/dashboard")
@require_auth
def dashboard():
    """Tableau de bord orienté DÉCISION, par rôle — chaque chiffre vient d'une
    requête réelle sur les données du tenant, rien n'est codé en dur."""
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    role = g.ctx["role"]
    today = school.today_iso()
    settings = school.get_settings(conn, tenant_id)
    week_ago = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()

    # L'ANNÉE EN COURS, pas toutes les années confondues.
    #
    # Le tableau de bord comptait les classes de tout l'établissement. Après un
    # passage d'année, il annonçait « 4 classes » là où l'écran Classes en
    # montrait 3 — la quatrième étant celle de l'année archivée, vidée de ses
    # élèves. Deux écrans qui se contredisent font douter des deux.
    annee_courante = conn.execute(
        """SELECT id FROM academic_years WHERE tenant_id=?
            ORDER BY is_active DESC, created_at DESC LIMIT 1""", (tenant_id,)).fetchone()
    annee_id = annee_courante["id"] if annee_courante else None

    # `? IS NULL` n'est pas du SQL portable : PostgreSQL refuse un marqueur dont
    # il ne peut pas déduire le type. La clause se construit, elle ne se
    # paramètre pas.
    filtre_annee = " AND academic_year_id=?" if annee_id else ""
    filtre_annee_c = " AND c.academic_year_id=?" if annee_id else ""
    p_annee = [annee_id] if annee_id else []

    if role == "directeur":
        counts = conn.execute(
            f"""SELECT (SELECT COUNT(*) FROM students WHERE tenant_id=? AND status='active') AS students,
                      (SELECT COUNT(*) FROM classes WHERE tenant_id=?{filtre_annee}) AS classes,
                      (SELECT COUNT(*) FROM memberships WHERE tenant_id=? AND role='professeur' AND status='active') AS teachers,
                      (SELECT COUNT(*) FROM memberships WHERE tenant_id=? AND role='parent' AND status='active') AS parents,
                      (SELECT COUNT(*) FROM guardians WHERE tenant_id=?) AS guardians,
                      (SELECT COUNT(*) FROM invitations WHERE tenant_id=? AND status='pending') AS pending_invitations,
                      (SELECT COUNT(*) FROM orders WHERE tenant_id=? AND status='pending') AS pending_orders,
                      (SELECT COUNT(*) FROM payments WHERE tenant_id=? AND status IN ('CREATED','PENDING')) AS pending_payments""",
            tuple([tenant_id, tenant_id] + p_annee + [tenant_id] * 6),
        ).fetchone()
        fin = ai_assistant.get_tenant_financial_summary(conn, g.ctx)
        rate = round(fin["total_paid"] / fin["total_due"] * 100) if fin["total_due"] else 0
        month_start, month_end = ai_assistant.month_bounds(0)
        paid_this_month = ai_assistant.get_period_collections(conn, g.ctx, month_start, month_end)
        total_receipts = conn.execute("SELECT COUNT(*) n FROM receipts WHERE tenant_id=?", (tenant_id,)).fetchone()["n"]
        att = _attendance_totals(conn, tenant_id, today)
        classes_recorded = conn.execute("SELECT COUNT(DISTINCT class_id) n FROM attendance WHERE tenant_id=? AND date=?", (tenant_id, today)).fetchone()["n"]
        incidents_week = conn.execute("SELECT COUNT(*) n FROM incidents WHERE tenant_id=? AND occurred_at>=?", (tenant_id, week_ago)).fetchone()["n"]
        recent_payments = conn.execute(
            """SELECT p.amount, p.currency, p.method, p.confirmed_at, s.first_name, s.last_name, s.id AS student_id, r.number AS receipt_number
               FROM payments p JOIN obligations o ON o.id=p.obligation_id JOIN students s ON s.id=o.student_id
               LEFT JOIN receipts r ON r.payment_id = p.id
               WHERE p.tenant_id=? AND p.status='CONFIRMED' ORDER BY p.confirmed_at DESC LIMIT 6""", (tenant_id,)).fetchall()
        by_class = conn.execute(
            f"""SELECT c.id, c.name, COUNT(s.id) AS student_count,
                      COALESCE(SUM(ob.total_due),0) AS total_due, COALESCE(SUM(pay.total_paid),0) AS total_paid
               FROM classes c LEFT JOIN students s ON s.class_id=c.id AND s.status='active'
               LEFT JOIN (SELECT student_id, SUM(amount) total_due FROM obligations WHERE tenant_id=? GROUP BY student_id) ob ON ob.student_id=s.id
               LEFT JOIN (SELECT o.student_id, SUM(p.amount) total_paid FROM payments p JOIN obligations o ON o.id=p.obligation_id
                          WHERE p.tenant_id=? AND p.status='CONFIRMED' GROUP BY o.student_id) pay ON pay.student_id=s.id
               WHERE c.tenant_id=?{filtre_annee_c} GROUP BY c.id
               ORDER BY (COALESCE(SUM(ob.total_due),0) - COALESCE(SUM(pay.total_paid),0)) DESC LIMIT 8""",
            tuple([tenant_id, tenant_id, tenant_id] + p_annee)).fetchall()
        result = {
            "role": "directeur", "currency": settings["currency"],
            "student_count": counts["students"], "class_count": counts["classes"], "teacher_count": counts["teachers"],
            "parent_count": counts["parents"], "guardian_count": counts["guardians"],
            "pending_invitations": counts["pending_invitations"], "pending_orders": counts["pending_orders"],
            "pending_payments": counts["pending_payments"],
            "total_due": fin["total_due"], "total_paid": fin["total_paid"], "outstanding": fin["outstanding"], "collection_rate": rate,
            "paid_this_month": paid_this_month, "total_receipts": total_receipts,
            "attendance_today": {**att, "classes_recorded": classes_recorded, "class_count": counts["classes"]},
            "incidents_week": incidents_week,
            "recent_payments": [dict(r) for r in recent_payments],
            "classes_outstanding": [{**dict(r), "outstanding": round((r["total_due"] or 0) - (r["total_paid"] or 0), 2)} for r in by_class],
            "recent_events": events_module.list_events(conn, tenant_id, limit=8),
        }

    elif role == "discipline":
        class_ids = school.visible_class_ids(conn, g.ctx)
        att = _attendance_totals(conn, tenant_id, today, class_ids)
        where, params = school.students_where_clause(conn, g.ctx)
        if where is None:
            incidents_week = 0; below = []; recent = []; student_count = 0
        else:
            student_count = conn.execute(f"SELECT COUNT(*) n FROM students s WHERE {where} AND s.status='active'", params).fetchone()["n"]
            incidents_week = conn.execute(f"SELECT COUNT(*) n FROM incidents i JOIN students s ON s.id=i.student_id WHERE {where} AND i.occurred_at>=?", params + (week_ago,)).fetchone()["n"]
            capital = int(settings.get("discipline_capital") or 100)
            ths = school.thresholds(conn, tenant_id)
            top_delta = (ths[0]["remaining_points"] - capital) if ths else -30
            below = conn.execute(
                f"""SELECT s.id, s.first_name, s.last_name, c.name AS class_name, SUM(i.points) AS points, ? + SUM(i.points) AS remaining FROM incidents i JOIN students s ON s.id=i.student_id
                    LEFT JOIN classes c ON c.id=s.class_id WHERE {where}
                    -- GROUP BY : PostgreSQL n'accepte une colonne nue que si elle appartient
                    -- à la table dont la clé primaire est groupée — c.name vient de `classes`.
                    GROUP BY s.id, s.first_name, s.last_name, c.name
                    HAVING SUM(i.points) <= ? ORDER BY points LIMIT 6""",
                (capital,) + params + (top_delta,)).fetchall()
            recent = conn.execute(
                f"""SELECT i.id, i.title, i.severity, i.occurred_at, i.points, s.first_name, s.last_name, s.id AS student_id, c.name AS class_name
                    FROM incidents i JOIN students s ON s.id=i.student_id LEFT JOIN classes c ON c.id=s.class_id WHERE {where}
                    ORDER BY i.occurred_at DESC, i.created_at DESC LIMIT 6""", params).fetchall()
        result = {
            "role": "discipline", "class_count": len(class_ids or []), "student_count": student_count,
            "attendance_today": att, "incidents_week": incidents_week, "threshold": school.thresholds(conn, tenant_id)[0]["remaining_points"] if school.thresholds(conn, tenant_id) else None,
            "capital": int(settings.get("discipline_capital") or 100),
            "students_below_threshold": [dict(r) for r in below], "recent_incidents": [dict(r) for r in recent],
        }

    elif role == "professeur":
        classes = [dict(c) for c in school.teacher_class_rows(conn, g.ctx)]
        class_ids = [c["id"] for c in classes]
        for c in classes:
            c["student_count"] = conn.execute("SELECT COUNT(*) n FROM students WHERE class_id=? AND status='active'", (c["id"],)).fetchone()["n"]
            a = _attendance_totals(conn, tenant_id, today, [c["id"]])
            c["attendance_today"] = a
        att = _attendance_totals(conn, tenant_id, today, class_ids)
        total_students = sum(c["student_count"] for c in classes)
        weekday = datetime.date.today().isoweekday()
        slots = []
        if class_ids:
            slots = [dict(r) for r in conn.execute(
                f"""SELECT sl.*, c.name AS class_name FROM schedule_slots sl JOIN classes c ON c.id=sl.class_id
                    WHERE sl.tenant_id=? AND sl.weekday=? AND sl.class_id IN ({','.join('?' for _ in class_ids)})
                    ORDER BY sl.start_time""", (tenant_id, weekday, *class_ids)).fetchall()]
        recent_incidents = []
        if class_ids:
            recent_incidents = [dict(r) for r in conn.execute(
                f"""SELECT i.id, i.title, i.severity, i.occurred_at, i.action_taken, s.first_name, s.last_name, s.id AS student_id, c.name AS class_name
                    FROM incidents i JOIN students s ON s.id=i.student_id LEFT JOIN classes c ON c.id=i.class_id
                    WHERE i.tenant_id=? AND i.class_id IN ({','.join('?' for _ in class_ids)}) ORDER BY i.occurred_at DESC LIMIT 5""",
                (tenant_id, *class_ids)).fetchall()]
        result = {
            "role": "professeur", "classes": classes, "student_count": total_students,
            "attendance_today": att, "today_slots": slots, "recent_incidents": recent_incidents,
            "finance_visible": bool(settings["teacher_sees_finance"]),
        }

    elif role == "parent":
        ids = school.own_children_ids(conn, g.ctx)
        children = []
        for sid in ids:
            s = conn.execute("SELECT s.*, c.name AS class_name, c.cycle AS class_cycle FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id=?", (sid,)).fetchone()
            # La tuile « dernière note » du parent lisait `grades` en direct :
            # ni proclamation, ni `is_current`. Elle affichait donc la note la
            # plus récemment SAISIE — y compris une période jamais proclamée.
            # C'est le P0 « notes non proclamées visibles du parent », réapparu
            # sur un autre chemin de code que le bulletin (qui, lui, passait
            # déjà par school.bulletin(only_published=True)).
            #
            # Fermeture par défaut : une note sans période rattachée reste
            # invisible du parent — on ne peut pas prouver qu'elle est proclamée.
            autorisees = school.published_period_ids_for_student(conn, tenant_id, sid)
            if autorisees:
                marques = ",".join("?" * len(autorisees))
                last_grade = conn.execute(
                    f"""SELECT subject, score, max_score, period, created_at FROM grades
                        WHERE tenant_id=? AND student_id=? AND is_current=1
                          AND period_id IN ({marques})
                        ORDER BY created_at DESC LIMIT 1""",
                    (tenant_id, sid, *autorisees)).fetchone()
            else:
                last_grade = None
            next_exam = None
            if s["class_id"]:
                next_exam = conn.execute("SELECT subject, date, start_time, room FROM exams WHERE tenant_id=? AND class_id=? AND date>=? ORDER BY date, start_time LIMIT 1",
                                         (tenant_id, s["class_id"], today)).fetchone()
            children.append({
                "student": {"id": s["id"], "code": s["code"], "first_name": s["first_name"], "last_name": s["last_name"],
                            "class_name": s["class_name"], "class_id": s["class_id"], "has_photo": bool(s["photo_data"])},
                "financial": financial.financial_summary(conn, tenant_id, sid),
                "attendance_today": school.attendance_today(conn, tenant_id, sid),
                "attendance_summary": school.attendance_summary(conn, tenant_id, sid),
                "last_grade": dict(last_grade) if last_grade else None,
                "next_exam": dict(next_exam) if next_exam else None,
                # Prochaine proclamation, calculée sur la division de l'élève :
                # une école peut donner six périodes au primaire et quatre au
                # secondaire, et le parent n'a que faire du calendrier des autres.
                "next_proclamation": _prochaine_proclamation(conn, tenant_id, s["academic_year_id"], s["class_cycle"]),
                "pending_orders": conn.execute("SELECT COUNT(*) n FROM orders WHERE tenant_id=? AND student_id=? AND status='pending'", (tenant_id, sid)).fetchone()["n"],
            })
        result = {"role": "parent", "children": children, "currency": settings["currency"]}
    else:
        result = {"role": role, "message": "Tableau de bord non disponible pour ce rôle."}
    # Le jour de référence vient du SERVEUR. « Échéance dépassée » est une
    # comparaison de dates : adossée à l'horloge du téléphone d'un parent, elle
    # annoncerait un retard qui n'existe pas — ou masquerait celui qui existe.
    result["today"] = today
    result["unread_notifications"] = notif_module.summary_for_user(conn, tenant_id, g.ctx["user_id"])["unread_count"]
    # Compléments transversaux (lots 2–5)
    where_s, params_s = school.students_where_clause(conn, g.ctx)
    result["unread_messages"] = conn.execute(
        f"""SELECT COUNT(*) n FROM messages m JOIN students s ON s.id=m.student_id WHERE {where_s} AND m.sender_id<>?
            AND NOT EXISTS (SELECT 1 FROM message_reads r WHERE r.message_id=m.id AND r.user_id=?)""", (*params_s, g.ctx["user_id"], g.ctx["user_id"])).fetchone()["n"] if where_s else 0
    upcoming = [dict(r) for r in conn.execute("SELECT id, kind, title, starts_on, starts_time, target_scope, target_value FROM calendar_events WHERE tenant_id=? AND starts_on >= ? ORDER BY starts_on LIMIT 5", (tenant_id, today))]
    result["upcoming_events"] = upcoming
    if role in ("directeur", "discipline") and where_s:
        result["pending_reports"] = conn.execute(f"SELECT COUNT(*) n FROM incident_reports r JOIN students s ON s.id=r.student_id WHERE {where_s} AND r.status='pending'", params_s).fetchone()["n"]
        result["pending_justifications"] = conn.execute(f"SELECT COUNT(*) n FROM attendance_justifications j JOIN students s ON s.id=j.student_id WHERE {where_s} AND j.status='pending'", params_s).fetchone()["n"]
        result["convocations_today"] = conn.execute(f"SELECT COUNT(*) n FROM convocations cv JOIN students s ON s.id=cv.student_id WHERE {where_s} AND cv.status='planned' AND cv.scheduled_on<=?", params_s + (today,)).fetchone()["n"]
    if role == "directeur":
        result["subscription"] = api_billing.summary(conn, tenant_id)
        result["orders_to_prepare"] = conn.execute("SELECT COUNT(*) n FROM orders WHERE tenant_id=? AND status='paid'", (tenant_id,)).fetchone()["n"]
    if role == "professeur":
        result["my_reports_pending"] = conn.execute("SELECT COUNT(*) n FROM incident_reports WHERE tenant_id=? AND reported_by=? AND status='pending'", (tenant_id, g.ctx["user_id"])).fetchone()["n"]
        result["pending_justifications"] = conn.execute(f"SELECT COUNT(*) n FROM attendance_justifications j JOIN students s ON s.id=j.student_id WHERE {where_s} AND j.status='pending'", params_s).fetchone()["n"] if where_s else 0
    if role == "parent":
        for c in result.get("children", []):
            sid = c["student"]["id"]
            c["pending_justifications"] = conn.execute("SELECT COUNT(*) n FROM attendance_justifications WHERE tenant_id=? AND student_id=? AND status='pending'", (tenant_id, sid)).fetchone()["n"]
            c["next_convocation"] = (lambda r: dict(r) if r else None)(conn.execute("SELECT scheduled_on, scheduled_time, motif FROM convocations WHERE tenant_id=? AND student_id=? AND status='planned' AND scheduled_on>=? ORDER BY scheduled_on LIMIT 1", (tenant_id, sid, today)).fetchone())
            c["homework_due"] = conn.execute("SELECT COUNT(*) n FROM resources WHERE tenant_id=? AND class_id=? AND kind='devoir' AND due_date>=?", (tenant_id, c["student"]["class_id"], today)).fetchone()["n"] if c["student"]["class_id"] else 0
    conn.close()
    return jsonify(result)


# ---------------------------------------------------------------------------
# Notifications, événements, audit
# ---------------------------------------------------------------------------

@app.get("/api/notifications")
@require_auth
def list_notifications():
    conn = db.get_connection()
    rows = notif_module.list_for_user(conn, g.ctx["tenant_id"], g.ctx["user_id"])
    conn.close()
    return jsonify(rows)


@app.post("/api/notifications/<notification_id>/read")
@require_auth
def read_notification(notification_id):
    conn = db.get_connection()
    marquee = notif_module.mark_read(conn, g.ctx["tenant_id"], g.ctx["user_id"], notification_id)
    conn.close()
    if not marquee:
        # Notification inexistante, d'un autre établissement, ou destinée à
        # quelqu'un d'autre : dans les trois cas, la même réponse — le client
        # n'apprend rien sur ce qui existe ailleurs.
        return jsonify({"error": "Notification introuvable."}), 404
    return jsonify({"ok": True})


@app.get("/api/events")
@require_auth
@require_permission("events.read")
def list_events_route():
    conn = db.get_connection()
    rows = events_module.list_events(conn, g.ctx["tenant_id"])
    conn.close()
    return jsonify(rows)


@app.get("/api/audit-logs")
@require_auth
@require_permission("audit.read")
def list_audit_logs():
    conn = db.get_connection()
    rows = conn.execute("SELECT * FROM audit_logs WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 100",
                         (g.ctx["tenant_id"],)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ---------------------------------------------------------------------------
# Onboarding — import Excel/CSV (docs point 6-7 : le directeur importe ses
# données réelles, Klassio les analyse et propose un mapping, RIEN n'est écrit
# en base avant confirmation explicite — voir backend/ingestion.py).
# ---------------------------------------------------------------------------

# _parse_uploaded_table a rejoint ingestion.py : deux routes en ont désormais
# besoin (import des élèves, import des résultats), et la lecture d'un fichier
# tabulaire est du ressort du module d'ingestion, pas de la couche HTTP.
_parse_uploaded_table = ingestion.parse_uploaded_table




@app.post("/api/onboarding/analyze-import")
@require_auth
@require_permission("import.run")
def analyze_import():
    if "file" not in request.files:
        return jsonify({"error": "Aucun fichier reçu."}), 400
    file_storage = request.files["file"]
    try:
        data_rows = _parse_uploaded_table(file_storage)
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
    analysis = ingestion.analyze_raw_data(data_rows, filename=file_storage.filename or "import")
    if not analysis.get("students_count"):
        # Échouer clairement ici plutôt que de renvoyer une analyse "réussie"
        # à 0 élève que l'étape de confirmation rejetterait ensuite sans
        # explication — la personne doit savoir tout de suite que le fichier
        # n'a livré aucune ligne exploitable, pas après avoir cliqué "confirmer".
        audit(g.ctx["tenant_id"], g.ctx["user_id"], "import.analyzed", "tenant", g.ctx["tenant_id"], "denied",
              after={"filename": file_storage.filename, "reason": "no_exploitable_rows"})
        return jsonify({
            "error": "Aucune ligne exploitable détectée dans ce fichier. Vérifiez qu'il contient une feuille "
                     "avec une colonne nom/prénom d'élève, et que ce n'est pas la première feuille du classeur "
                     "si celle-ci ne contient qu'un texte explicatif.",
        }), 400
    # L'analyse est PERSISTÉE. C'est elle, et rien d'autre, qui sera écrite à la
    # confirmation : ce que la personne a vu à l'écran est exactement ce qui
    # entrera en base. Avant, confirm-import acceptait la liste renvoyée par le
    # client — un aperçu de 100 élèves pouvait être confirmé par 500 lignes
    # différentes, sans que rien ne le signale.
    session_id = new_id()
    conn = db.get_connection()
    try:
        conn.execute(
            """INSERT INTO import_sessions (id, tenant_id, created_by, file_name, students_count,
                                            records, status, created_at)
               VALUES (?,?,?,?,?,?, 'analyzed', ?)""",
            (session_id, g.ctx["tenant_id"], g.ctx["user_id"], (file_storage.filename or "")[:200],
             int(analysis.get("students_count") or 0),
             json.dumps(analysis.get("normalized_records") or []), str(time.time())),
        )
        conn.commit()
    finally:
        conn.close()
    analysis["import_session_id"] = session_id
    audit(g.ctx["tenant_id"], g.ctx["user_id"], "import.analyzed", "import_session", session_id, "success",
          after={"filename": file_storage.filename, "students_detected": analysis.get("students_count")})
    return jsonify(analysis)


@app.post("/api/onboarding/confirm-import")
@require_auth
@require_permission("import.run")
def confirm_import():
    """Écrit EXACTEMENT ce que l'analyse avait retenu et montré.

    La liste d'enregistrements n'est plus acceptée du client : elle est relue
    depuis la session d'import créée par /analyze-import. Une confirmation sans
    analyse valide est donc impossible, et ce qui est écrit ne peut pas différer
    de l'aperçu validé.
    """
    data = json_object(request.get_json(force=True))
    session_id = required_text(data.get("import_session_id"), "import_session_id")
    conn = db.get_connection()
    session = conn.execute(
        "SELECT * FROM import_sessions WHERE id=? AND tenant_id=? AND created_by=?",
        (session_id, g.ctx["tenant_id"], g.ctx["user_id"]),
    ).fetchone()
    if not session:
        conn.close()
        audit(g.ctx["tenant_id"], g.ctx["user_id"], "import.confirmed", "import_session", session_id, "denied")
        return jsonify({"error": "Analyse introuvable — relancez l'analyse du fichier."}), 404
    if session["status"] != "analyzed":
        conn.close()
        # Rejouer une confirmation doublerait tout l'établissement.
        return jsonify({"error": "Cette analyse a déjà été confirmée. Relancez une analyse pour importer à nouveau."}), 409
    if time.time() - float(session["created_at"]) > IMPORT_SESSION_TTL_SECONDS:
        conn.close()
        return jsonify({"error": "Cette analyse a expiré. Relancez l'analyse du fichier."}), 410

    records = json.loads(session["records"])
    if not records:
        conn.close()
        return jsonify({"error": "Aucun enregistrement à importer — relancez l'analyse."}), 400

    # La session passe à 'confirmed' AVANT l'import : deux clics simultanés ne
    # peuvent pas déclencher deux imports du même fichier. La contrainte
    # `status='analyzed'` dans le WHERE fait office de verrou.
    verrou = conn.execute(
        "UPDATE import_sessions SET status='confirmed', confirmed_at=? WHERE id=? AND status='analyzed'",
        (str(time.time()), session_id))
    conn.commit()
    if not (verrou.rowcount or 0):
        conn.close()
        return jsonify({"error": "Cette analyse est déjà en cours de confirmation."}), 409

    try:
        result = ingestion.bootstrap_school(conn, g.ctx["tenant_id"], g.ctx["user_id"], {
            "school_name": data.get("school_name", ""),
            "academic_year": data.get("academic_year", "Année en cours"),
            "records": records,
        })
    except (ValueError, ValidationError) as e:
        # L'import n'a rien écrit (validation préalable) : la session redevient
        # confirmable après correction du fichier.
        conn.execute("UPDATE import_sessions SET status='analyzed', confirmed_at=NULL WHERE id=?", (session_id,))
        conn.commit()
        conn.close()
        return jsonify({"error": str(e)}), 400
    conn.close()
    audit(g.ctx["tenant_id"], g.ctx["user_id"], "import.confirmed", "import_session", session_id, "success",
          after={"students": result.get("students_count")})
    result["import_session_id"] = session_id
    return jsonify(result)


# ---------------------------------------------------------------------------
# Invitations (professeur / parent) — le rôle et l'établissement viennent
# TOUJOURS de l'invitation créée par le directeur, jamais d'un choix fait par
# la personne qui l'accepte (docs point 14).
# ---------------------------------------------------------------------------

@app.post("/api/invitations")
@require_auth
@require_permission("invitations.manage")
def create_invitation():
    data = json_object(request.get_json(force=True))
    role = data.get("role")
    if role not in ("professeur", "parent", "discipline"):
        return jsonify({"error": "role doit être 'professeur', 'parent' ou 'discipline'"}), 400
    student_ids = data.get("student_ids") or []
    class_ids = data.get("class_ids") or []
    titulaire_class_id = data.get("titulaire_class_id") or None
    member_title = (data.get("title") or "").strip()[:60] or None
    scope_cycles = [c for c in (data.get("scope_cycles") or []) if c in ("maternelle", "primaire", "secondaire")] if role == "discipline" else []
    if role == "parent" and not student_ids:
        return jsonify({"error": "Sélectionnez au moins un élève pour une invitation parent."}), 400
    label = required_text(data.get("label"), "label", max_length=120) if data.get("label") else None

    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    if role == "parent":
        placeholders = ",".join("?" for _ in student_ids)
        rows = conn.execute(
            f"SELECT id FROM students WHERE tenant_id = ? AND id IN ({placeholders})",
            (tenant_id, *student_ids),
        ).fetchall()
        if len(rows) != len(set(student_ids)):
            conn.close()
            return jsonify({"error": "Un ou plusieurs élèves sélectionnés n'appartiennent pas à cet établissement."}), 400
    if role == "professeur":
        if titulaire_class_id and titulaire_class_id not in class_ids:
            class_ids.append(titulaire_class_id)
        if class_ids:
            placeholders = ",".join("?" for _ in class_ids)
            rows = conn.execute(f"SELECT id FROM classes WHERE tenant_id = ? AND id IN ({placeholders})", (tenant_id, *class_ids)).fetchall()
            if len(rows) != len(set(class_ids)):
                conn.close()
                return jsonify({"error": "Une ou plusieurs classes sélectionnées n'appartiennent pas à cet établissement."}), 400

    token = security.generate_invitation_token()
    invitation_id = new_id()
    now = time.time()
    conn.execute(
        """INSERT INTO invitations (id, tenant_id, role, token_hash, status, label, created_by, created_at, expires_at)
           VALUES (?,?,?,?, 'pending', ?, ?, ?, ?)""",
        (invitation_id, tenant_id, role, security.hash_invitation_token(token), label,
         g.ctx["user_id"], str(now), str(now + security.INVITATION_TTL_SECONDS)),
    )
    if role == "parent":
        for sid in set(student_ids):
            conn.execute("INSERT INTO invitation_students (invitation_id, student_id) VALUES (?,?)", (invitation_id, sid))
    if role == "professeur":
        for cid in set(class_ids):
            conn.execute("INSERT INTO invitation_classes (invitation_id, class_id, is_titulaire) VALUES (?,?,?)",
                         (invitation_id, cid, 1 if cid == titulaire_class_id else 0))
    if member_title or scope_cycles:
        # Portés par le libellé de l'invitation (JSON) puis appliqués au membership à l'acceptation.
        import json as _json
        conn.execute("UPDATE invitations SET label=? WHERE id=?", (_json.dumps({"label": label, "title": member_title, "scope_cycles": scope_cycles}), invitation_id))
    conn.commit()
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "invitation.created", "invitation", invitation_id, "success", after={"role": role})
    return jsonify({
        "id": invitation_id,
        "token": token,  # retourné une seule fois — jamais stocké en clair
        "expires_at": now + security.INVITATION_TTL_SECONDS,
    }), 201


@app.get("/api/invitations")
@require_auth
@require_permission("invitations.manage")
def list_invitations():
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    now = time.time()
    conn.execute(
        "UPDATE invitations SET status='expired' WHERE tenant_id=? AND status='pending' AND CAST(expires_at AS REAL) < ?",
        (tenant_id, now),
    )
    conn.commit()
    rows = conn.execute(
        """SELECT i.id, i.role, i.status, i.label, i.created_at, i.expires_at, i.accepted_at,
                  i.revoked_at, i.revoked_reason, i.accepted_user_id,
                  u.name AS accepted_name, r.name AS revoked_by_name,
                  m.status AS membership_status
           FROM invitations i
           LEFT JOIN users u ON u.id = i.accepted_user_id
           LEFT JOIN users r ON r.id = i.revoked_by
           LEFT JOIN memberships m ON m.user_id = i.accepted_user_id AND m.tenant_id = i.tenant_id
           WHERE i.tenant_id=? ORDER BY i.created_at DESC""",
        (tenant_id,),
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if d.get("label") and str(d["label"]).startswith("{"):
            try:
                import json as _json
                meta = _json.loads(d["label"])
                d["label"] = meta.get("label")
                d["title"] = meta.get("title")
                d["scope_cycles"] = meta.get("scope_cycles")
            except ValueError:
                pass
        if r["role"] == "parent":
            students = conn.execute(
                """SELECT s.id, s.first_name, s.last_name FROM invitation_students inv_s
                   JOIN students s ON s.id = inv_s.student_id WHERE inv_s.invitation_id = ?""",
                (r["id"],),
            ).fetchall()
            d["students"] = [dict(s) for s in students]
        if r["role"] == "professeur":
            d["classes"] = [dict(c) for c in conn.execute(
                """SELECT c.id, c.name, ic.is_titulaire FROM invitation_classes ic JOIN classes c ON c.id = ic.class_id
                   WHERE ic.invitation_id = ?""", (r["id"],))]
        result.append(d)
    conn.close()
    return jsonify(result)


@app.post("/api/invitations/<invitation_id>/revoke")
@require_auth
@require_permission("invitations.manage")
def revoke_invitation(invitation_id):
    """Révoque une invitation — EN ATTENTE **ou déjà acceptée**.

    Avant, cette route ne faisait que réécrire un statut. Sur une invitation
    `pending`, cela suffisait : `_resolve_invitation` exige `status='pending'`,
    le lien devenait donc inutilisable. Sur une invitation **acceptée**, elle ne
    faisait rien du tout — la personne gardait son compte, sa session et son
    accès aux dossiers. Une Direction qui avait invité le mauvais parent lisait
    « révoquée » à l'écran pendant que le parent continuait de consulter
    l'enfant d'une autre famille.

    Révoquer un accès accepté fait donc trois choses, et rien de plus :

    1. l'invitation passe en `revoked`, horodatée, avec son auteur et le motif ;
    2. le **membership** de la personne dans cet établissement passe en
       `revoked` — `security.resolve_session` revérifie ce statut à CHAQUE
       requête, donc l'accès tombe immédiatement, y compris pour une session
       déjà ouverte ;
    3. ses **sessions** de cet établissement sont supprimées, pour que la
       coupure soit visible tout de suite plutôt qu'au prochain appel.

    Ce qui n'est PAS fait, et ne doit pas l'être : rien n'est supprimé du
    métier. Ni l'élève, ni son dossier, ni ses résultats, ni ses paiements, ni
    ses reçus, ni le responsable légal en tant que personne de l'établissement.
    On coupe un ACCÈS, on ne détruit pas une histoire. La ligne d'invitation et
    celle du membership restent en base, marquées et datées.
    """
    data = json_object(request.get_json(silent=True))
    motif = (data.get("reason") or "").strip()[:400] or None

    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    row = conn.execute("SELECT * FROM invitations WHERE id=? AND tenant_id=?", (invitation_id, tenant_id)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Invitation introuvable"}), 404
    if row["status"] == "revoked":
        # Idempotent : révoquer deux fois ne réécrit pas la date d'origine.
        conn.close()
        return jsonify({"ok": True, "status": "revoked", "access_revoked": False,
                        "already": True})

    etat_avant = row["status"]
    maintenant = str(time.time())
    conn.execute(
        "UPDATE invitations SET status='revoked', revoked_at=?, revoked_by=?, revoked_reason=? WHERE id=? AND tenant_id=?",
        (maintenant, g.ctx["user_id"], motif, invitation_id, tenant_id))

    acces_coupe = False
    personne = None
    sessions_fermees = 0
    if etat_avant == "accepted" and row["accepted_user_id"]:
        cible = row["accepted_user_id"]
        # On ne révoque JAMAIS la Direction par ce chemin : une école qui perd
        # son dernier accès Direction devient inadministrable, et personne ne
        # peut plus rien y rouvrir.
        membership = conn.execute(
            "SELECT * FROM memberships WHERE user_id=? AND tenant_id=?", (cible, tenant_id)).fetchone()
        if membership and membership["role"] == "directeur":
            conn.rollback()
            conn.close()
            audit(tenant_id, g.ctx["user_id"], "invitation.revoke", "invitation", invitation_id, "denied")
            return jsonify({"error": "L'accès de la Direction ne se révoque pas depuis les invitations."}), 409
        if membership and membership["status"] == "active":
            conn.execute(
                "UPDATE memberships SET status='revoked', revoked_at=?, revoked_by=? WHERE user_id=? AND tenant_id=?",
                (maintenant, g.ctx["user_id"], cible, tenant_id))
            acces_coupe = True
        curseur = conn.execute("DELETE FROM sessions WHERE user_id=? AND tenant_id=?", (cible, tenant_id))
        sessions_fermees = curseur.rowcount or 0
        u = conn.execute("SELECT name FROM users WHERE id=?", (cible,)).fetchone()
        personne = u["name"] if u else None

    conn.commit()
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "invitation.revoked", "invitation", invitation_id, "success",
          before={"status": etat_avant},
          after={"status": "revoked", "access_revoked": acces_coupe, "role": row["role"],
                 "user_id": row["accepted_user_id"], "sessions_closed": sessions_fermees,
                 "reason": motif})
    return jsonify({"ok": True, "status": "revoked", "previous_status": etat_avant,
                    "access_revoked": acces_coupe, "person": personne,
                    "sessions_closed": sessions_fermees})


def _resolve_invitation(conn, token):
    if not token:
        return None
    row = conn.execute("SELECT * FROM invitations WHERE token_hash = ?", (security.hash_invitation_token(token),)).fetchone()
    if not row or row["status"] != "pending":
        return None
    if float(row["expires_at"]) < time.time():
        conn.execute("UPDATE invitations SET status='expired' WHERE id=?", (row["id"],))
        conn.commit()
        return None
    return row


def _invitation_state(conn, token):
    """État d'une invitation, pour DIRE À L'UTILISATEUR ce qui se passe.

    `_resolve_invitation` répond None pour quatre situations très différentes :
    lien inconnu, expiré, révoqué, déjà utilisé. Les confondre produit le même
    message pour « votre établissement a annulé ce lien » et pour « vous venez
    de finir votre inscription, actualisez et connectez-vous » — le second cas
    arrivant à chaque rafraîchissement après une activation réussie.

    Ce n'est pas une divulgation : qui présente le jeton sait déjà qu'il a reçu
    cette invitation. Aucune donnée de l'établissement n'est renvoyée ici.
    """
    if not token:
        return "absent", None
    row = conn.execute("SELECT * FROM invitations WHERE token_hash = ?",
                       (security.hash_invitation_token(token),)).fetchone()
    if not row:
        return "inconnue", None
    if row["status"] == "accepted":
        return "utilisee", row
    if row["status"] == "revoked":
        return "revoquee", row
    if float(row["expires_at"]) < time.time():
        if row["status"] == "pending":
            conn.execute("UPDATE invitations SET status='expired' WHERE id=?", (row["id"],))
            conn.commit()
        return "expiree", row
    if row["status"] != "pending":
        return "expiree", row
    return "valide", row


ETAT_MESSAGES = {
    "absent": "Aucun lien d'invitation n'a été fourni.",
    "inconnue": "Ce lien d'invitation n'existe pas. Vérifiez qu'il a été copié en entier.",
    "utilisee": "Ce lien a déjà servi à créer un compte. Connectez-vous avec le numéro ou l'e-mail que vous avez choisi.",
    "revoquee": "Votre établissement a annulé ce lien. Demandez-lui-en un nouveau.",
    "expiree": "Ce lien a expiré. Demandez un nouveau lien à votre établissement.",
}


def _invitation_meta(invitation):
    """Métadonnées portées par `label` : soit un simple nom de destinataire,
    soit un JSON {label, title, scope_cycles}. Cette lecture était recopiée à
    trois endroits ; une seule version évite qu'elles divergent."""
    brut = invitation["label"]
    if not brut:
        return {"label": None, "title": None, "scope_cycles": None}
    if not brut.startswith("{"):
        return {"label": brut, "title": None, "scope_cycles": None}
    try:
        meta = json.loads(brut)
    except ValueError:
        return {"label": None, "title": None, "scope_cycles": None}
    return {"label": meta.get("label") or None, "title": meta.get("title") or None,
            "scope_cycles": meta.get("scope_cycles") or None}


@app.get("/api/invitations/lookup")
def lookup_invitation():
    # Publique et non authentifiée : sans limite de débit, un attaquant peut
    # tenter de deviner des tokens valides sans aucun ralentissement. Le
    # token a 256 bits d'entropie (le brute-force reste infaisable), mais
    # cette limite reste une défense en profondeur peu coûteuse.
    allowed, retry_after = security.check_rate_limit("invite_lookup", request.remote_addr, 20, 300)
    if not allowed:
        return jsonify({"error": f"Trop de tentatives. Réessayez dans {retry_after} secondes."}), 429

    token = request.args.get("token", "")
    conn = db.get_connection()
    etat, invitation = _invitation_state(conn, token)
    if etat != "valide":
        conn.close()
        # Seule une tentative sur un jeton INCONNU compte : c'est le signal
        # d'énumération. « utilisée », « révoquée », « expirée » veulent dire
        # que le jeton existe — donc que la personne l'a bien reçu. Un parent
        # qui rouvre son lien après activation ne doit pas être puni pour ça.
        if etat in ("absent", "inconnue"):
            security.record_attempt("invite_lookup", request.remote_addr)
        # `state` permet à l'accueil de dire ce qui s'est réellement passé —
        # notamment de proposer « Se connecter » après une activation réussie
        # plutôt que d'annoncer un lien invalide.
        return jsonify({"error": ETAT_MESSAGES[etat], "state": etat}), 404
    # Jeton valide présenté : cette adresse n'énumère pas. On efface son ardoise.
    security.clear_attempts("invite_lookup", request.remote_addr)
    meta = _invitation_meta(invitation)
    tenant = conn.execute("SELECT * FROM tenants WHERE id=?", (invitation["tenant_id"],)).fetchone()
    result = {"role": invitation["role"], "tenant_name": tenant["name"] if tenant else "", "expires_at": invitation["expires_at"],
              "branding": school.branding(tenant), "state": "valide",
              # Nom prévu par la Direction : un PRÉ-REMPLISSAGE de confort, jamais
              # une preuve d'identité (le champ reste modifiable, et le rôle comme
              # le périmètre viennent de l'invitation, pas de ce nom).
              "suggested_name": meta["label"], "title": meta["title"]}
    if invitation["role"] == "discipline":
        cycles = meta["scope_cycles"] or ["secondaire"]
        n = conn.execute(f"SELECT COUNT(*) n FROM classes WHERE tenant_id=? AND cycle IN ({','.join('?' for _ in cycles)})", (invitation["tenant_id"], *cycles)).fetchone()["n"]
        result["scope_cycles"] = cycles
        result["scope_classes"] = n
        result["scope_note"] = f"{'Adjoint — ' if meta['title'] else ''}Périmètre : {', '.join(cycles)} — {n} classe(s). Présences, retards, incidents, convocations ; aucun accès aux finances."
    if invitation["role"] == "parent":
        # Uniquement les enfants que la Direction a rattachés à CETTE invitation.
        # Il n'existe aucune route permettant à un parent d'en chercher d'autres :
        # un nom d'élève n'est pas une preuve de parenté.
        students = conn.execute(
            """SELECT s.id, s.first_name, s.last_name, c.name AS class_name, c.cycle AS class_cycle
               FROM invitation_students inv_s JOIN students s ON s.id = inv_s.student_id
               LEFT JOIN classes c ON c.id = s.class_id AND c.tenant_id = s.tenant_id
               WHERE inv_s.invitation_id = ?""",
            (invitation["id"],),
        ).fetchall()
        result["students"] = [dict(s) for s in students]
    if invitation["role"] == "professeur":
        # Affectations décidées par la Direction. L'enseignant ne les choisit
        # pas et ne peut pas les modifier ici : l'accueil ne fait que montrer
        # ce que le serveur a déjà enregistré.
        result["classes"] = [dict(c) for c in conn.execute(
            """SELECT c.name, c.level, c.cycle, ic.is_titulaire,
                      (SELECT COUNT(*) FROM students s
                       WHERE s.tenant_id = c.tenant_id AND s.class_id = c.id AND s.status = 'active') AS student_count
               FROM invitation_classes ic
               JOIN classes c ON c.id = ic.class_id AND c.tenant_id = ?
               WHERE ic.invitation_id = ?
               ORDER BY ic.is_titulaire DESC, c.name""",
            (invitation["tenant_id"], invitation["id"]))]
        result["titulaire_of"] = [c["name"] for c in result["classes"] if c["is_titulaire"]]
    conn.close()
    return jsonify(result)


def _lien_app(chemin):
    """Adresse publique d'un écran Klassio, pour un message qui sera ouvert
    ailleurs que sur cette machine. `localhost` dans un e-mail reçu sur un
    téléphone ne mène nulle part."""
    return mailer.APP_BASE_URL + chemin


def _nom_etablissement(conn, tenant_id):
    row = conn.execute("SELECT name FROM tenants WHERE id=?", (tenant_id,)).fetchone()
    return row["name"] if row else "Votre établissement"


@app.post("/api/invitations/send")
@require_auth
@require_permission("invitations.manage")
def send_invitation_email():
    """Achemine par e-mail une invitation DÉJÀ créée.

    POURQUOI LE JETON EST FOURNI PAR L'APPELANT. Il n'est stocké que haché —
    décision de sécurité antérieure, et bonne : une fuite de la base ne donne
    aucun lien utilisable. Il n'existe donc aucun moyen, pour le serveur, de
    reconstruire le lien d'une invitation passée. La Direction, elle, l'a entre
    les mains juste après l'avoir créée. C'est elle qui le repasse ici.

    Le jeton ne suffit pas à autoriser : il est revérifié contre CET
    établissement et doit être encore en attente. Un jeton d'une autre école ne
    donne rien, même présenté par une Direction authentifiée.

    L'adresse n'est pas non plus choisie librement : voir plus bas, elle doit
    correspondre à ce que l'invitation prévoit quand celle-ci vise une personne
    déjà connue.
    """
    data = json_object(request.get_json(force=True))
    token = required_text(data.get("token"), "token", max_length=200)
    destinataire = valid_email(data.get("email", ""))
    tenant_id = g.ctx["tenant_id"]

    conn = db.get_connection()
    invitation = conn.execute(
        "SELECT * FROM invitations WHERE token_hash=? AND tenant_id=?",
        (security.hash_invitation_token(token), tenant_id)).fetchone()
    if not invitation:
        conn.close()
        audit(tenant_id, g.ctx["user_id"], "invitation.send", "invitation", None, "denied")
        return jsonify({"error": "Invitation introuvable pour cet établissement."}), 404
    if invitation["status"] != "pending":
        conn.close()
        return jsonify({"error": "Cette invitation n'est plus en attente : elle a été "
                                 "utilisée, révoquée ou a expiré."}), 409
    if not mailer.adresse_utilisable(destinataire):
        conn.close()
        return jsonify({"error": "Cette adresse ne peut pas recevoir de courrier."}), 400

    etablissement = _nom_etablissement(conn, tenant_id)
    lien = _lien_app("/app/invitation.html?token=" + token)
    sujet, html, texte = mailer.gabarit_invitation(
        invitation["role"], data.get("name") or "", etablissement, lien)

    # Une invitation, une adresse, un message. Le double clic et le
    # rafraîchissement retombent sur la même livraison.
    livraison, _neuve = deliveries_module.creer(
        conn, tenant_id, canal=deliveries_module.CANAL_EMAIL,
        gabarit="invitation", adresse=destinataire, sujet=sujet,
        cle_idempotence=f"invitation:{invitation['id']}:{destinataire.lower()}")
    livraison = deliveries_module.envoyer_email(
        conn, tenant_id, livraison, sujet, html, texte, actor_id=g.ctx["user_id"])
    conn.close()

    reussi = livraison["status"] == deliveries_module.ACCEPTED
    return jsonify({
        "delivery_id": livraison["id"],
        "status": livraison["status"],
        "channel": livraison["channel"],
        # Le message d'erreur technique reste au serveur ; l'écran reçoit une
        # phrase utilisable, sans détail de fournisseur.
        "error": None if reussi else "L'envoi a échoué. Vous pouvez réessayer ou copier le lien.",
        "retryable": deliveries_module.rejouable(livraison),
    }), (200 if reussi else 502)


@app.post("/api/invitations/whatsapp")
@require_auth
@require_permission("invitations.manage")
def prepare_invitation_whatsapp():
    """Prépare un lien WhatsApp prérempli. N'ENVOIE RIEN.

    Klassio n'a pas d'API WhatsApp : ouvrir wa.me place le message dans
    l'application de l'utilisateur, qui décide ensuite de l'envoyer ou non. Le
    statut enregistré dit donc « préparé », et l'écran doit dire la même chose.
    Écrire « message envoyé » ici serait un mensonge que rien ne vient corriger
    si la Direction ferme WhatsApp sans appuyer sur envoyer.
    """
    data = json_object(request.get_json(force=True))
    token = required_text(data.get("token"), "token", max_length=200)
    telephone = valid_phone(data.get("phone")) if data.get("phone") else None
    tenant_id = g.ctx["tenant_id"]

    conn = db.get_connection()
    invitation = conn.execute(
        "SELECT * FROM invitations WHERE token_hash=? AND tenant_id=?",
        (security.hash_invitation_token(token), tenant_id)).fetchone()
    if not invitation:
        conn.close()
        return jsonify({"error": "Invitation introuvable pour cet établissement."}), 404
    etablissement = _nom_etablissement(conn, tenant_id)
    lien = _lien_app("/app/invitation.html?token=" + token)
    nom = (data.get("name") or "").strip()
    qualite = mailer.ROLE_LIBELLE.get(invitation["role"], "membre")
    message = (f"Bonjour {nom}," if nom else "Bonjour,") + "\n\n" + (
        f"{etablissement} vous invite à rejoindre son espace Klassio en tant que {qualite}.\n\n"
        f"Cliquez sur ce lien pour créer votre compte :\n{lien}")

    livraison, _neuve = deliveries_module.creer(
        conn, tenant_id, canal=deliveries_module.CANAL_WHATSAPP,
        gabarit="invitation", adresse=telephone or "(numéro saisi dans WhatsApp)",
        sujet="Invitation", cle_idempotence=None)
    # Statut honnête : le lien est prêt, rien n'est parti.
    conn.execute("UPDATE deliveries SET status=?, updated_at=? WHERE id=?",
                 ("CREATED", str(time.time()), livraison["id"]))
    conn.commit()
    conn.close()

    numero = (telephone or "").lstrip("+").replace(" ", "")
    return jsonify({
        "whatsapp_url": "https://wa.me/" + numero + "?text=" + quote(message),
        "message": message,
        "delivery_id": livraison["id"],
        "status": "PREPARED",
        "note": "Le lien est préparé. WhatsApp s'ouvrira : c'est vous qui envoyez le message.",
    })


@app.post("/api/invitations/accept")
def accept_invitation():
    allowed, retry_after = security.check_rate_limit("invite_accept", request.remote_addr, 10, 300)
    if not allowed:
        return jsonify({"error": f"Trop de tentatives. Réessayez dans {retry_after} secondes."}), 429

    data = json_object(request.get_json(force=True))
    token = data.get("token", "")
    name = required_text(data.get("name"), "name")
    password = valid_password(data.get("password", ""))
    phone = valid_phone(data.get("phone"))
    raw_email = (data.get("email") or "").strip()
    if not raw_email and not phone:
        raise ValidationError("Indiquez un email ou un numéro de téléphone.")
    # Compte au téléphone seul : email technique jamais affiché (colonne NOT NULL).
    email = valid_email(raw_email) if raw_email else f"tel+{phone.lstrip('+')}@klassio.invalid"

    conn = db.get_connection()
    invitation = _resolve_invitation(conn, token)
    if not invitation:
        # Le budget anti-énumération ne se consomme QUE sur un jeton inconnu.
        # `_resolve_invitation` confond quatre situations ; `_invitation_state`
        # les distingue. Un parent qui reclique son lien déjà utilisé présente
        # un jeton RÉEL : il n'énumère rien.
        etat, _ = _invitation_state(conn, token)
        if etat in ("absent", "inconnue"):
            security.record_attempt("invite_accept", request.remote_addr)
        conn.close()
        return jsonify({"error": "Invitation invalide, expirée ou déjà utilisée."}), 404
    if conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
        conn.close()
        return jsonify({"error": "Un compte existe déjà avec cet email. Connectez-vous puis contactez l'établissement."}), 409
    if phone and conn.execute("SELECT id FROM users WHERE phone=?", (phone,)).fetchone():
        conn.close()
        return jsonify({"error": "Un compte existe déjà avec ce numéro. Connectez-vous puis contactez l'établissement."}), 409

    tenant_id = invitation["tenant_id"]
    role = invitation["role"]
    user_id, membership_id = new_id(), new_id()
    now = str(time.time())
    conn.execute("INSERT INTO users (id, email, phone, password_hash, name, created_at) VALUES (?,?,?,?,?,?)",
                 (user_id, email, phone, security.hash_password(password), name, now))
    # Prise de l'invitation, AVANT tout rattachement. _resolve_invitation a lu
    # `status='pending'` plus haut : entre cette lecture et ici, une seconde
    # requête peut avoir lu la même chose. Mesuré : deux acceptations simultanées
    # du même lien créaient deux comptes parent rattachés au même enfant, et
    # l'usage unique annoncé à l'utilisateur ne tenait pas.
    #
    # La condition `status='pending'` porte donc sur l'UPDATE lui-même. SQLite
    # sérialise sur le verrou d'écriture, PostgreSQL verrouille la ligne puis
    # réévalue la condition après le commit du gagnant : dans les deux cas, le
    # perdant obtient rowcount=0 et repart sans rien avoir écrit.
    prise = conn.execute(
        "UPDATE invitations SET status='accepted', accepted_at=?, accepted_user_id=? WHERE id=? AND status='pending'",
        (now, user_id, invitation["id"]),
    )
    if not (prise.rowcount or 0):
        conn.rollback()
        conn.close()
        return jsonify({"error": "Invitation invalide, expirée ou déjà utilisée."}), 404
    meta = _invitation_meta(invitation)
    member_title = meta["title"]
    scope_cycles = json.dumps(meta["scope_cycles"]) if meta["scope_cycles"] else None
    # Identifiant interne, généré ici et jamais soumis par le client. Le parent
    # n'en reçoit pas : il n'est pas membre du personnel de l'établissement.
    staff_code = school.generate_staff_code(conn, tenant_id, role) if role in ("professeur", "discipline") else None
    conn.execute(
        """INSERT INTO memberships (id, user_id, tenant_id, role, created_at, title, scope_cycles, staff_code)
           VALUES (?,?,?,?,?,?,?,?)""",
        (membership_id, user_id, tenant_id, role, now, member_title, scope_cycles, staff_code))

    if role == "parent":
        students = conn.execute(
            "SELECT student_id FROM invitation_students WHERE invitation_id=?", (invitation["id"],)
        ).fetchall()
        parts = name.split(" ", 1)
        first, last = (parts[0], parts[1]) if len(parts) > 1 else (name, "")
        for s in students:
            existing = conn.execute(
                """SELECT g.id FROM guardians g JOIN student_guardians sg ON sg.guardian_id = g.id
                   WHERE sg.tenant_id=? AND sg.student_id=? AND g.user_id IS NULL LIMIT 1""",
                (tenant_id, s["student_id"]),
            ).fetchone()
            if existing:
                conn.execute("UPDATE guardians SET user_id=? WHERE id=?", (user_id, existing["id"]))
            else:
                gid = new_id()
                conn.execute(
                    "INSERT INTO guardians (id, tenant_id, first_name, last_name, email, phone, user_id, created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (gid, tenant_id, first, last, school.display_email(email), phone, user_id, now),
                )
                conn.execute(
                    "INSERT INTO student_guardians (id, tenant_id, student_id, guardian_id, relationship) VALUES (?,?,?,?, 'Parent')",
                    (new_id(), tenant_id, s["student_id"], gid),
                )

    if role == "professeur":
        # Rattachement aux classes décidé par la Direction à la création de
        # l'invitation — jamais choisi ici par la personne qui l'accepte.
        for c in conn.execute("SELECT class_id, is_titulaire FROM invitation_classes WHERE invitation_id=?", (invitation["id"],)).fetchall():
            if c["is_titulaire"]:
                conn.execute("UPDATE class_teachers SET is_titulaire=0 WHERE tenant_id=? AND class_id=?", (tenant_id, c["class_id"]))
            conn.execute(
                """INSERT INTO class_teachers (id, tenant_id, class_id, user_id, subject, is_titulaire, created_at) VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(class_id, user_id) DO UPDATE SET is_titulaire=excluded.is_titulaire""",
                (new_id(), tenant_id, c["class_id"], user_id, None, c["is_titulaire"], now),
            )

    # L'invitation a déjà été prise plus haut, dans la même transaction que les
    # rattachements : si ce commit échoue, rien n'est écrit et le lien reste
    # utilisable.
    conn.commit()
    session_token = security.create_session(conn, user_id, tenant_id)

    # Ce que l'écran de succès a le droit d'annoncer : uniquement ce qui vient
    # d'être RÉELLEMENT écrit, relu depuis la base après le commit. L'accueil
    # ne présente jamais un rattachement qui n'existe pas.
    confirme = {"children": [], "classes": [], "titulaire_of": []}
    if role == "parent":
        confirme["children"] = [dict(r) for r in conn.execute(
            """SELECT s.first_name, s.last_name, c.name AS class_name
               FROM student_guardians sg
               JOIN guardians gd ON gd.id = sg.guardian_id
               JOIN students s ON s.id = sg.student_id AND s.tenant_id = sg.tenant_id
               LEFT JOIN classes c ON c.id = s.class_id AND c.tenant_id = s.tenant_id
               WHERE sg.tenant_id=? AND gd.user_id=?
               ORDER BY s.last_name, s.first_name""", (tenant_id, user_id))]
    if role == "professeur":
        confirme["classes"] = [dict(r) for r in conn.execute(
            """SELECT c.name, ct.is_titulaire FROM class_teachers ct
               JOIN classes c ON c.id = ct.class_id AND c.tenant_id = ct.tenant_id
               WHERE ct.tenant_id=? AND ct.user_id=? ORDER BY ct.is_titulaire DESC, c.name""",
            (tenant_id, user_id))]
        confirme["titulaire_of"] = [c["name"] for c in confirme["classes"] if c["is_titulaire"]]
    tenant_row = conn.execute("SELECT * FROM tenants WHERE id=?", (tenant_id,)).fetchone()
    conn.close()
    audit(tenant_id, user_id, "invitation.accepted", "invitation", invitation["id"], "success", after={"role": role})
    # Activation réussie : cette adresse n'énumère pas. Sans cette ligne, les
    # parents d'une même école, qui partagent le wifi de l'établissement, se
    # bloquaient les uns les autres au onzième inscrit.
    security.clear_attempts("invite_accept", request.remote_addr)
    return jsonify({
        "token": session_token, "tenant_id": tenant_id, "role": role, "name": name,
        "staff_code": staff_code,
        "tenant_name": tenant_row["name"] if tenant_row else "",
        "portal": tenant_row["slug"] if tenant_row else None,
        # L'accueil complet ne se joue qu'ici, à la première activation.
        "onboarding_completed": False,
        "confirmed": confirme,
    }), 201


# ---------------------------------------------------------------------------
# Assistant IA — strictement en lecture seule (voir backend/ai_assistant.py).
# Accessible à tous les rôles authentifiés ; le scope des données répond
# uniquement à g.ctx, exactement comme le reste de l'API.
# ---------------------------------------------------------------------------

@app.get("/api/reports/summary")
@require_auth
@require_permission("reports.read")
def reports_summary():
    # Réutilise le même moteur de lecture que l'assistant IA plutôt que de
    # recalculer une seconde fois les mêmes agrégats (docs point 28 : ne pas
    # créer d'architecture parallèle inutile).
    conn = db.get_connection()
    financial_totals = ai_assistant.get_tenant_financial_summary(conn, g.ctx)
    biggest_unpaid = ai_assistant.get_biggest_unpaid(conn, g.ctx, limit=10)
    no_payment = ai_assistant.get_students_without_payment(conn, g.ctx)
    class_rows = conn.execute(
        """SELECT c.name, COUNT(s.id) as student_count FROM classes c
           LEFT JOIN students s ON s.class_id = c.id AND s.tenant_id = c.tenant_id
           WHERE c.tenant_id=? GROUP BY c.id ORDER BY student_count DESC""",
        (g.ctx["tenant_id"],),
    ).fetchall()
    tenant_id = g.ctx["tenant_id"]
    month_ago = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    att = conn.execute(
        """SELECT SUM(CASE WHEN status='present' THEN 1 ELSE 0 END) p, SUM(CASE WHEN status='late' THEN 1 ELSE 0 END) l, SUM(CASE WHEN status='absent' THEN 1 ELSE 0 END) a, SUM(CASE WHEN status='excused' THEN 1 ELSE 0 END) e, COUNT(*) n
           FROM attendance WHERE tenant_id=? AND date>=?""", (tenant_id, month_ago)).fetchone()
    by_cycle = conn.execute(
        """SELECT COALESCE(c.cycle,'non défini') AS cycle, COUNT(s.id) AS student_count FROM students s
           LEFT JOIN classes c ON c.id=s.class_id WHERE s.tenant_id=? AND s.status='active' GROUP BY c.cycle ORDER BY student_count DESC""",
        (tenant_id,)).fetchall()
    by_gender = conn.execute("SELECT COALESCE(gender,'—') AS gender, COUNT(*) n FROM students WHERE tenant_id=? AND status='active' GROUP BY gender", (tenant_id,)).fetchall()
    staff = conn.execute("SELECT role, COUNT(*) n FROM memberships WHERE tenant_id=? AND status='active' GROUP BY role", (tenant_id,)).fetchall()
    incidents = conn.execute("SELECT category, COUNT(*) n FROM incidents WHERE tenant_id=? AND occurred_at>=? GROUP BY category ORDER BY n DESC", (tenant_id, month_ago)).fetchall()
    # Regroupement mensuel fait en Python : les fonctions de date diffèrent d'un
    # moteur à l'autre, et le volume concerné (paiements confirmés) est faible.
    _paid_rows = conn.execute(
        "SELECT confirmed_at, amount FROM payments WHERE tenant_id=? AND status='CONFIRMED' AND confirmed_at IS NOT NULL",
        (tenant_id,)).fetchall()
    # Regroupement mensuel par BORNES de mois, calculées une seule fois.
    #
    # Mesuré à l'audit sur l'établissement de simulation (2 340 élèves, 2 534
    # paiements confirmés) : convertir chaque horodatage une par une prenait
    # 776 ms des 811 ms de la route — plus de 95 % du temps de réponse de la
    # page Rapports. `fromtimestamp()` puis `strftime()` consultent la base de
    # fuseaux du système à chaque appel ; dans un worker Gunicorn forké, cela
    # coûte environ 200 µs l'unité.
    #
    # Une première version mémorisait la conversion par tranche de 86 400 s.
    # C'était faux : ces tranches sont des jours UTC, et à la frontière d'un
    # mois une même tranche contient deux mois locaux — les paiements des
    # premières heures du 1er du mois auraient été comptés sur le mois
    # précédent. On calcule donc les bornes de chaque mois en heure locale
    # (autant de conversions qu'il y a de mois, pas de paiements), puis on
    # place chaque paiement par simple comparaison.
    _horodatages = []
    for _r in _paid_rows:
        try:
            _horodatages.append((float(_r["confirmed_at"]), _r["amount"] or 0))
        except (TypeError, ValueError):
            continue
    _by_month = {}
    if _horodatages:
        _premier = datetime.datetime.fromtimestamp(min(t for t, _ in _horodatages))
        _dernier = datetime.datetime.fromtimestamp(max(t for t, _ in _horodatages))
        _bornes = []  # [(début_epoch, "AAAA-MM")], croissant
        _an, _mois = _premier.year, _premier.month
        while (_an, _mois) <= (_dernier.year, _dernier.month):
            _bornes.append((datetime.datetime(_an, _mois, 1).timestamp(), f"{_an:04d}-{_mois:02d}"))
            _an, _mois = (_an + 1, 1) if _mois == 12 else (_an, _mois + 1)
        for _ts, _montant in _horodatages:
            _i = bisect.bisect_right(_bornes, (_ts, "\uffff")) - 1
            if _i < 0:
                continue
            _m = _bornes[_i][1]
            _by_month[_m] = _by_month.get(_m, 0) + _montant
    monthly = [{"month": m, "total": round(t, 2)} for m, t in sorted(_by_month.items(), reverse=True)[:6]]
    settings = school.get_settings(conn, tenant_id)
    conn.close()
    total = financial_totals["total_due"]
    rate = round((financial_totals["total_paid"] / total) * 100) if total else 0
    att_total = att["n"] or 0
    return jsonify({
        "currency": settings["currency"],
        "financial": financial_totals,
        "collection_rate": rate,
        "biggest_unpaid": biggest_unpaid,
        "students_without_payment_count": len(no_payment),
        "classes": [dict(r) for r in class_rows],
        "by_cycle": [dict(r) for r in by_cycle],
        "by_gender": [dict(r) for r in by_gender],
        "staff": [dict(r) for r in staff],
        "attendance_30d": {"present": att["p"] or 0, "late": att["l"] or 0, "absent": att["a"] or 0, "excused": att["e"] or 0, "total": att_total,
                           "rate": round(((att["p"] or 0) + (att["l"] or 0)) / att_total * 100) if att_total else None},
        "incidents_30d": [dict(r) for r in incidents],
        "monthly_collections": list(reversed(monthly)),
    })


@app.post("/api/ai/ask")
@require_auth
def ai_ask():
    data = json_object(request.get_json(force=True))
    message = required_text(data.get("message"), "message", max_length=500)
    conversation_id = data.get("conversation_id")
    previous_intent = data.get("previous_intent")
    tenant_id, user_id = g.ctx["tenant_id"], g.ctx["user_id"]

    conn = db.get_connection()
    now = str(time.time())

    if conversation_id:
        conv = conn.execute(
            "SELECT * FROM ai_conversations WHERE id=? AND tenant_id=? AND user_id=?",
            (conversation_id, tenant_id, user_id),
        ).fetchone()
        if not conv:
            conn.close()
            return jsonify({"error": "Conversation introuvable."}), 404
    else:
        conversation_id = new_id()
        title = message[:60]
        conn.execute("INSERT INTO ai_conversations (id, tenant_id, user_id, title, created_at) VALUES (?,?,?,?,?)",
                     (conversation_id, tenant_id, user_id, title, now))

    conn.execute("INSERT INTO ai_messages (id, conversation_id, tenant_id, role, content, created_at) VALUES (?,?,?,'user',?,?)",
                 (new_id(), conversation_id, tenant_id, message, now))

    result = ai_assistant.answer_question(conn, g.ctx, message, previous_intent=previous_intent)

    import json as _json
    conn.execute(
        "INSERT INTO ai_messages (id, conversation_id, tenant_id, role, content, rich_json, intent, created_at) VALUES (?,?,?,'assistant',?,?,?,?)",
        (new_id(), conversation_id, tenant_id, result["text"],
         _json.dumps(result["rich"]) if result["rich"] else None, result["intent"], str(time.time())),
    )
    conn.commit()
    conn.close()

    audit(tenant_id, user_id, "ai.ask", "ai_conversation", conversation_id,
          "denied" if result["refused"] else "success", after={"intent": result["intent"]})

    result["conversation_id"] = conversation_id
    return jsonify(result)


@app.get("/api/ai/conversations")
@require_auth
def ai_list_conversations():
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT id, title, created_at FROM ai_conversations WHERE tenant_id=? AND user_id=? ORDER BY created_at DESC LIMIT 50",
        (g.ctx["tenant_id"], g.ctx["user_id"]),
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.get("/api/ai/conversations/<conversation_id>/messages")
@require_auth
def ai_conversation_messages(conversation_id):
    conn = db.get_connection()
    conv = conn.execute(
        "SELECT * FROM ai_conversations WHERE id=? AND tenant_id=? AND user_id=?",
        (conversation_id, g.ctx["tenant_id"], g.ctx["user_id"]),
    ).fetchone()
    if not conv:
        conn.close()
        return jsonify({"error": "Conversation introuvable."}), 404
    rows = conn.execute(
        "SELECT role, content, rich_json, intent, created_at FROM ai_messages WHERE conversation_id=? ORDER BY created_at",
        (conversation_id,),
    ).fetchall()
    conn.close()
    import json as _json
    result = []
    for r in rows:
        d = dict(r)
        d["rich"] = _json.loads(d.pop("rich_json")) if d.get("rich_json") else None
        result.append(d)
    return jsonify(result)


def _startup_banner():
    """Dire au démarrage où vont réellement les données. Aucune clé affichée."""
    import supabase_client
    print(f"Klassio — moteur de données : {config.DB_BACKEND}")
    if config.DB_BACKEND == "sqlite":
        print(f"  base locale : {db.DB_PATH}")
    elif config.postgres_est_local():
        print(f"  base PostgreSQL locale ({config.hote_postgres() or 'socket'})")
    else:
        # Démarrer sur une base distante n'est pas interdit — c'est la
        # production elle-même. Mais on ne doit jamais le faire SANS LE SAVOIR :
        # un .env recopié d'une autre machine suffit à brancher un poste de
        # développement sur les données d'une école.
        print(f"  ⚠  BASE POSTGRESQL DISTANTE : {config.hote_postgres()}")
        print("     Chaque écriture de cette session touche cette base. Si vous pensiez")
        print("     travailler en local : arrêtez, et retirez KLASSIO_DB_BACKEND=postgres.")
    if config.supabase_configured():
        st = supabase_client.status()
        etat = "connecté" if st["authenticated"] else f"NON connecté ({st['detail']})"
        print(f"  Supabase ({config.SUPABASE_URL}) : {etat}, clé {st['key_used']}")
        if config.DB_BACKEND == "sqlite":
            print("  Supabase est configuré mais ne stocke encore rien : migration à faire.")
    else:
        print("  Supabase : non configuré (voir backend/.env.example)")


if __name__ == "__main__":
    db.init_db()
    _startup_banner()
    app.run(port=5001, debug=False, use_reloader=False)
