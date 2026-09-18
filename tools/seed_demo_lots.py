"""KLASSIO — données de démonstration pour les lots 2 à 5, créées via l'API
réelle avec les bons acteurs (Direction, professeurs, DD, parent). Aucune
écriture directe en base : tout passe par les mêmes règles que la production.
Idempotent : relancer ne duplique pas (vérifications avant création)."""
import json, urllib.request, urllib.error, sys, datetime, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from demo_pdfs import PDFS

API = "http://localhost:5001/api"


def call(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def login(email, pw):
    s, b = call("POST", "/auth/login", {"email": email, "password": pw})
    if s != 200:
        print("LOGIN FAIL", email, b); sys.exit(1)
    return b["token"]


def ok(label, s, b, accept=(200, 201)):
    print(("  OK  " if s in accept else "  --  ") + label + ("" if s in accept else f" [{s} {b.get('error','')[:70]}]"))
    return s in accept


D = login("direction@reference.test", "Direction2026!")
PROF = login("prof@reference.test", "Professeur2026!")
PROF2 = login("prof2@reference.test", "Professeur2026!")
DD = login("dd@reference.test", "Discipline2026!")
PARENT = login("parent@reference.test", "Parent2026!")
today = datetime.date.today()
iso = today.isoformat()

_, classes = call("GET", "/classes", token=D)
_, prof_classes = call("GET", "/classes", token=PROF)
_, prof2_classes = call("GET", "/classes", token=PROF2)
cls_a = prof_classes[0]
cls_b = prof2_classes[0]
_, students_a = call("GET", f"/classes/{cls_a['id']}/students", token=PROF)
_, students_b = call("GET", f"/classes/{cls_b['id']}/students", token=PROF2)
students_a = students_a["students"]; students_b = students_b["students"]
_, my_children = call("GET", "/students", token=PARENT)
mat = [c for c in classes if c["cycle"] == "maternelle"]
print(f"Classe A {cls_a['name']} ({len(students_a)}) · Classe B {cls_b['name']} ({len(students_b)}) · maternelle : {len(mat)}")

# 1. Périodes officielles + proclamation de la Période 1 -------------------
print("\n[1] Périodes & proclamation")
s, b = call("POST", "/periods", {"preset": "standard"}, token=D)
ok(f"périodes standard ({b.get('created', 0)} créée(s))", s, b)
_, pd = call("GET", "/periods", token=D)
p1 = next((p for p in pd["periods"] if p["label"] == "Période 1"), None)
if p1 and not p1["published_at"]:
    s, b = call("POST", f"/periods/{p1['id']}/publish", {}, token=D)
    ok(f"Période 1 proclamée ({b.get('students', 0)} élève(s) concernés)", s, b)

# 2. Calendrier : événements et communiqués -------------------------------
print("\n[2] Calendrier")
_, existing = call("GET", "/calendar/events", token=D)
have = {e["title"] for e in existing}
events = [
    {"kind": "fete", "title": "Fête de l'école", "description": "Journée portes ouvertes, spectacles des classes et remise des prix.", "starts_on": (today + datetime.timedelta(days=9)).isoformat(), "starts_time": "09:00", "target_scope": "all"},
    {"kind": "reunion", "title": "Réunion des parents — bulletins", "description": "Remise des bulletins de la Période 1 et échange avec les titulaires.", "starts_on": (today + datetime.timedelta(days=4)).isoformat(), "starts_time": "15:00", "target_scope": "all"},
    {"kind": "deuil", "title": "Journée de deuil national", "description": "Établissement fermé. Les cours reprennent le lendemain à l'horaire habituel.", "starts_on": (today + datetime.timedelta(days=6)).isoformat(), "target_scope": "all"},
    {"kind": "conge", "title": "Congé de mi-trimestre", "description": "Pas de cours du lundi au vendredi.", "starts_on": (today + datetime.timedelta(days=20)).isoformat(), "ends_on": (today + datetime.timedelta(days=24)).isoformat(), "target_scope": "all"},
    {"kind": "communique", "title": "Uniformes : nouvelle livraison à l'économat", "description": "Les tailles 8 et 10 ans sont de nouveau disponibles à la boutique. Commandez avant 20 h pour un retrait le lendemain.", "starts_on": iso, "target_scope": "all"},
    {"kind": "examens", "title": "Examens du 1er semestre", "description": "Horaire détaillé publié par classe.", "starts_on": (today + datetime.timedelta(days=30)).isoformat(), "ends_on": (today + datetime.timedelta(days=37)).isoformat(), "target_scope": "cycle", "target_value": "secondaire"},
]
for e in events:
    if e["title"] in have:
        print("  --  déjà présent : " + e["title"]); continue
    s, b = call("POST", "/calendar/events", e, token=D)
    ok(e["title"], s, b)

# 3. Documents de l'établissement -----------------------------------------
print("\n[3] Documents")
TXT = PDFS["livre"]
_, docs = call("GET", "/documents", token=D)
have = {d["title"] for d in docs}
for d in [
    {"kind": "reglement", "title": "Règlement intérieur 2026", "visible_to": "all", "pdf": "reglement"},
    {"kind": "autre", "title": "Circulaire — frais scolaires et modalités de paiement", "visible_to": "all", "pdf": "circulaire"},
    {"kind": "autre", "title": "Procédure interne — conseil de discipline", "visible_to": "staff", "pdf": "procedure"},
]:
    if d["title"] in have:
        print("  --  déjà présent : " + d["title"]); continue
    body = {k: v for k, v in d.items() if k != "pdf"}
    s, b = call("POST", "/documents", {**body, "file_name": d["title"].lower().replace(" ", "-")[:40] + ".pdf", "file_data": PDFS[d["pdf"]]}, token=D)
    ok(d["title"], s, b)

# 4. Livres & devoirs publiés par les enseignants -------------------------
print("\n[4] Livres & devoirs")
_, res = call("GET", "/resources", token=PROF)
have = {r["title"] for r in res}
for r in [
    {"class_id": cls_a["id"], "kind": "livre", "title": "Manuel de lecture — chapitre 4", "subject": "Français", "description": "À lire avant le cours de jeudi.", "file_name": "lecture-ch4.txt", "file_data": TXT},
    {"class_id": cls_a["id"], "kind": "devoir", "title": "Exercices de calcul — série 3", "subject": "Mathématiques", "description": "Exercices 1 à 12, à faire sur le cahier de devoirs.", "due_date": (today + datetime.timedelta(days=3)).isoformat()},
    {"class_id": cls_a["id"], "kind": "fiche", "title": "Fiche de conjugaison — présent de l'indicatif", "subject": "Français", "description": "Support à coller dans le cahier."},
]:
    if r["title"] in have:
        print("  --  déjà présent : " + r["title"]); continue
    s, b = call("POST", "/resources", r, token=PROF)
    ok(r["title"], s, b)
for r in [
    {"class_id": cls_b["id"], "kind": "devoir", "title": "Dissertation — l'eau dans la ville", "subject": "Géographie", "description": "Deux pages maximum, introduction et conclusion obligatoires.", "due_date": (today + datetime.timedelta(days=5)).isoformat()},
]:
    if r["title"] in have:
        print("  --  déjà présent : " + r["title"]); continue
    s, b = call("POST", "/resources", r, token=PROF2)
    ok(r["title"], s, b)

# 5. Appel finalisé (notification « votre enfant est à l'école ») ----------
print("\n[5] Appel du jour finalisé")
recs = [{"student_id": x["id"], "status": "present"} for x in students_a]
if len(recs) > 4:
    recs[1]["status"] = "absent"; recs[2]["status"] = "late"; recs[3]["status"] = "excused"; recs[3]["note"] = "Certificat médical"
s, b = call("POST", f"/classes/{cls_a['id']}/attendance", {"date": iso, "records": recs, "finalize": True}, token=PROF)
ok(f"classe A — {b.get('saved')} élèves, {b.get('present_notified')} parent(s) informé(s) « à l'école »", s, b)
recs_b = [{"student_id": x["id"], "status": "present"} for x in students_b]
if len(recs_b) > 3:
    recs_b[0]["status"] = "absent"; recs_b[2]["status"] = "late"
s, b = call("POST", f"/classes/{cls_b['id']}/attendance", {"date": iso, "records": recs_b, "finalize": True}, token=PROF2)
ok(f"classe B — {b.get('saved')} élèves", s, b)

# 6. Pointage au portail (retard constaté) --------------------------------
print("\n[6] Pointage au portail")
late_kid = students_b[4] if len(students_b) > 4 else students_b[-1]
s, b = call("POST", "/attendance/gate", {"student_id": late_kid["id"], "arrival_time": "08:25"}, token=DD)
ok(f"{late_kid['first_name']} {late_kid['last_name']} — retard 08:25", s, b)

# 7. Signalements d'enseignants (en attente du DD) ------------------------
print("\n[7] Signalements")
_, reps = call("GET", "/incident-reports", token=DD)
if not [r for r in reps if r["status"] == "pending"]:
    s, b = call("POST", "/incident-reports", {"student_id": students_b[1]["id"], "description": "A refusé de rendre son devoir et a répondu de manière irrespectueuse devant la classe.", "occurred_at": iso}, token=PROF2)
    ok("signalement 1 (prof titulaire classe B)", s, b)
    s, b = call("POST", "/incident-reports", {"student_id": students_b[2]["id"], "description": "Utilisation du téléphone pendant l'interrogation malgré deux rappels.", "occurred_at": (today - datetime.timedelta(days=1)).isoformat()}, token=PROF2)
    ok("signalement 2", s, b)
else:
    print("  --  signalements déjà en attente")

# 8. Justification d'absence par le parent --------------------------------
print("\n[8] Justification d'absence")
kid = my_children[0]
# Marquer l'enfant du parent absent hier (par son titulaire) pour qu'il y ait quelque chose à justifier.
yesterday = (today - datetime.timedelta(days=1)).isoformat()
kid_class = kid.get("class_id")
tok = PROF if any(x["id"] == kid["id"] for x in students_a) else PROF2
if kid_class:
    call("POST", f"/classes/{kid_class}/attendance", {"date": yesterday, "records": [{"student_id": kid["id"], "status": "absent"}]}, token=tok)
_, att = call("GET", f"/students/{kid['id']}", token=PARENT)
absences = [r for r in att["attendance"]["recent"] if r["status"] == "absent"]
_, js = call("GET", f"/students/{kid['id']}", token=PARENT)
existing_j = {j["date"] for j in js["justifications"]}
if absences and absences[0]["date"] not in existing_j:
    s, b = call("POST", f"/students/{kid['id']}/justifications", {"date": absences[0]["date"], "reason": "Consultation médicale — certificat du centre de santé joint sur demande."}, token=PARENT)
    ok(f"justification pour {kid['first_name']} le {absences[0]['date']}", s, b)
else:
    print("  --  aucune absence à justifier ou justification déjà envoyée")

# 9. Convocation des parents ----------------------------------------------
print("\n[9] Convocation")
_, cv = call("GET", "/convocations", token=DD)
if not [c for c in cv if c["status"] == "planned"]:
    s, b = call("POST", "/convocations", {"student_id": students_b[0]["id"], "scheduled_on": (today + datetime.timedelta(days=2)).isoformat(), "scheduled_time": "10:00", "motif": "Entretien au sujet des absences répétées et du comportement en classe."}, token=DD)
    ok("convocation des responsables", s, b)
else:
    print("  --  convocation déjà planifiée")

# 10. Cahier de communication ---------------------------------------------
print("\n[10] Cahier de communication")
_, th = call("GET", f"/messages/{kid['id']}", token=PARENT)
if not th["messages"]:
    s, b = call("POST", f"/messages/{kid['id']}", {"body": "Bonjour, mon enfant a été souffrant hier. Je vous remercie de m'indiquer les devoirs à rattraper."}, token=PARENT)
    ok("message du parent", s, b)
    s, b = call("POST", f"/messages/{kid['id']}", {"body": "Bonjour, bien noté. Les exercices de calcul série 3 sont publiés dans Livres & devoirs, à rendre vendredi. Bon rétablissement."}, token=PROF)
    ok("réponse du titulaire", s, b)
else:
    print("  --  fil déjà ouvert")

# 11. Boutique : produit avec variantes ------------------------------------
print("\n[11] Boutique")
_, prods = call("GET", "/store/products", token=D)
have = {p["name"] for p in prods}
for p in [
    {"name": "Uniforme — chemise", "category": "uniformes", "price": 12.0, "stock": 60, "options": ["6 ans", "8 ans", "10 ans", "12 ans", "14 ans"]},
    {"name": "Uniforme — jupe / pantalon", "category": "uniformes", "price": 14.5, "stock": 45, "options": ["6 ans", "8 ans", "10 ans", "12 ans"]},
    {"name": "Tablier de laboratoire", "category": "matériel", "price": 9.0, "stock": 25, "options": ["S", "M", "L"]},
]:
    if p["name"] in have:
        print("  --  déjà présent : " + p["name"]); continue
    s, b = call("POST", "/store/products", p, token=D)
    ok(p["name"], s, b)

# 12. Appréciations de maternelle -----------------------------------------
print("\n[12] Appréciations (maternelle)")
if mat:
    mc = mat[0]
    _, ms = call("GET", f"/classes/{mc['id']}/students", token=D)
    ms = ms["students"][:20]
    _, ex = call("GET", f"/classes/{mc['id']}/appreciations", token=D)
    if not ex and ms:
        for domain, base in (("Langage", 3), ("Motricité", 3), ("Socialisation", 2), ("Autonomie", 3)):
            entries = [{"student_id": x["id"], "level": base if i % 3 else min(4, base + 1)} for i, x in enumerate(ms)]
            s, b = call("POST", f"/classes/{mc['id']}/appreciations", {"period": "Période 1", "domain": domain, "entries": entries}, token=D)
            ok(f"{mc['name']} — {domain} ({b.get('saved', 0)})", s, b)
    else:
        print("  --  appréciations déjà saisies" if ex else "  --  classe maternelle vide")
else:
    print("  --  aucune classe maternelle")

# 13. Conduite et décision de fin d'année ---------------------------------
print("\n[13] Conseil de classe")
s, b = call("PUT", f"/students/{students_a[0]['id']}/conduct", {"period": "Période 1", "label": "Très bien", "note": "Élève moteur dans la classe."}, token=D)
ok("cote de conduite fixée par le conseil", s, b)
s, b = call("PUT", f"/students/{students_a[0]['id']}/decision", {"decision": "admis", "mention": "Distinction", "notify": False}, token=D)
ok("décision de fin d'année", s, b)

print("\nTerminé.")
