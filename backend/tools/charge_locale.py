"""Rejoue les scénarios de charge de tools/k6/ sans dépendre de K6.

K6 mesure mieux et monte plus haut. Mais il faut l'installer, et une régression
d'isolation ou de double comptage ne devrait pas attendre ça pour être vue.
Ce script exécute les mêmes quatre scénarios avec la bibliothèque standard.

    python backend/tools/charge_locale.py                      # tout
    python backend/tools/charge_locale.py --scenario isolation
    python backend/tools/charge_locale.py --utilisateurs 40 --duree 30

Il lit tools/k6/env.json, produit par seed_charge.py, et vise le serveur qui y
est déclaré. Comme les scripts K6, il ne se contente jamais d'un code 200 : il
regarde ce que la réponse contient.
"""
import argparse
import json
import os
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request

RACINE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
CHEMIN_ENV = os.path.join(RACINE, "..", "tools", "k6", "env.json")


class Resultats:
    """Collecte sûre entre threads."""

    def __init__(self):
        self._verrou = threading.Lock()
        self.durees = {}
        self.echecs = []
        self.fuites = []
        self.compteurs = {}

    def mesure(self, nom, ms):
        with self._verrou:
            self.durees.setdefault(nom, []).append(ms)

    def echec(self, message):
        with self._verrou:
            self.echecs.append(message)

    def fuite(self, message):
        with self._verrou:
            self.fuites.append(message)

    def incremente(self, nom, n=1):
        with self._verrou:
            self.compteurs[nom] = self.compteurs.get(nom, 0) + n


def appel(base, chemin, entetes=None, methode="GET", corps=None, timeout=30):
    donnees = json.dumps(corps).encode() if corps is not None else None
    requete = urllib.request.Request(base + chemin, data=donnees, method=methode)
    requete.add_header("Accept-Encoding", "gzip")
    if donnees is not None:
        requete.add_header("Content-Type", "application/json")
    for cle, valeur in (entetes or {}).items():
        requete.add_header(cle, valeur)
    debut = time.perf_counter()
    try:
        with urllib.request.urlopen(requete, timeout=timeout) as reponse:
            brut = reponse.read()
            if reponse.headers.get("Content-Encoding") == "gzip":
                import gzip
                brut = gzip.decompress(brut)
            statut = reponse.status
    except urllib.error.HTTPError as e:
        brut, statut = e.read(), e.code
    except Exception as e:
        return (time.perf_counter() - debut) * 1000, 0, {"error": str(e)}
    ms = (time.perf_counter() - debut) * 1000
    try:
        return ms, statut, json.loads(brut)
    except Exception:
        return ms, statut, None


def connexion(base, courriel, mot_de_passe):
    _, statut, corps = appel(base, "/api/auth/login", methode="POST",
                             corps={"email": courriel, "password": mot_de_passe})
    if statut != 200:
        raise SystemExit(f"Connexion refusée pour {courriel} : {statut} {corps}")
    return {"Authorization": "Bearer " + corps["token"]}


# ---------------------------------------------------------------------------
# Scénarios
# ---------------------------------------------------------------------------

def scenario_fumee(env, res, args):
    """Un passage sur chaque parcours critique. Vérifie le CONTENU."""
    base = env["base_url"]
    alpha = env["etablissements"][0]
    mdp = env["mot_de_passe"]

    controles = []

    h = connexion(base, alpha["comptes"]["directeur"], mdp)
    ms, s, c = appel(base, "/api/dashboard", h); res.mesure("tableau de bord", ms)
    controles.append(("tableau de bord renvoie un rôle", s == 200 and c.get("role") == "directeur"))

    ms, s, c = appel(base, "/api/students", h); res.mesure("liste élèves", ms)
    controles.append((f"liste élèves non vide ({len(c) if isinstance(c, list) else 0})",
                      s == 200 and isinstance(c, list) and len(c) == alpha["eleves_count"]))
    controles.append(("les élèves portent un identifiant lisible",
                      s == 200 and isinstance(c, list) and c and c[0].get("code", "").startswith("STU-")))

    ms, s, c = appel(base, f"/api/students/{alpha['exemples']['eleve_id']}", h); res.mesure("dossier élève", ms)
    controles.append(("dossier élève complet", s == 200 and bool(c.get("student", {}).get("code"))))

    ms, s, c = appel(base, f"/api/students/{alpha['exemples']['eleve_id']}/financial-summary", h)
    res.mesure("finance élève", ms)
    coherent = s == 200 and abs(c["balance"] - (c["total_due"] - c["total_paid"])) < 0.01
    controles.append(("solde = dû − encaissé", coherent))

    ms, s, c = appel(base, "/api/reports/summary", h); res.mesure("rapports", ms)
    controles.append(("rapports : agrégats financiers présents",
                      s == 200 and "financial" in c and "monthly_collections" in c))
    if s == 200:
        somme = round(sum(m["total"] for m in c["monthly_collections"]), 2)
        controles.append((f"somme des mois = total encaissé ({somme})",
                          abs(somme - c["financial"]["total_paid"]) < 0.01))

    hp = connexion(base, alpha["comptes"]["professeur"], mdp)
    _, s, c = appel(base, "/api/classes", hp)
    controles.append((f"professeur : {len(c) if isinstance(c, list) else 0} classes sur {alpha['classes_count']}",
                      s == 200 and 0 < len(c) < alpha["classes_count"]))

    hpar = connexion(base, alpha["comptes"]["parent"], mdp)
    _, s, c = appel(base, "/api/students", hpar)
    controles.append((f"parent : périmètre réduit ({len(c) if isinstance(c, list) else 0} enfants)",
                      s == 200 and 0 < len(c) <= 3))
    _, s, _ = appel(base, "/api/reports/summary", hpar)
    controles.append(("parent : rapports d'établissement refusés", s == 403))

    hdd = connexion(base, alpha["comptes"]["discipline"], mdp)
    _, s, c = appel(base, "/api/discipline/overview", hdd)
    controles.append(("discipline : aperçu disponible", s == 200 and "incidents_week" in c))

    for libelle, ok in controles:
        print(f"    {'OK  ' if ok else 'ÉCHEC'}  {libelle}")
        if not ok:
            res.echec(libelle)
    return len(controles)


def scenario_charge(env, res, args):
    """Montée en charge sur les parcours de lecture."""
    base = env["base_url"]
    alpha = env["etablissements"][0]
    mdp = env["mot_de_passe"]
    sessions = {r: connexion(base, alpha["comptes"][r], mdp)
                for r in ("directeur", "professeur", "parent")}
    fin = time.time() + args.duree
    arret = threading.Event()

    def travailler(indice):
        """Chaque utilisateur simulé joue la MÊME ronde, quel que soit leur
        nombre. Sans cela, faire varier le nombre de threads ferait aussi
        varier le mélange des rôles, et les débits ne seraient pas comparables
        d'un palier à l'autre — une erreur de métrologie facile à commettre.
        """
        while time.time() < fin and not arret.is_set():
            for chemin, nom in (
                    ("/api/dashboard", "tableau de bord"),
                    ("/api/students", "liste élèves"),
                    (f"/api/students/{alpha['exemples']['eleve_id']}", "dossier élève"),
                    ("/api/reports/summary", "rapports")):
                ms, s, _ = appel(base, chemin, sessions["directeur"])
                res.mesure(nom, ms)
                if s != 200:
                    res.echec(f"{nom} -> {s}")
            for chemin, nom in (("/api/classes", "classes"),
                                (f"/api/classes/{alpha['exemples']['class_id']}/students",
                                 "élèves d'une classe")):
                ms, s, _ = appel(base, chemin, sessions["professeur"])
                res.mesure(nom, ms)
                if s != 200:
                    res.echec(f"{nom} -> {s}")
            ms, s, _ = appel(base, "/api/students", sessions["parent"])
            res.mesure("élèves (parent)", ms)
            if s != 200:
                res.echec(f"élèves (parent) -> {s}")
            res.incremente("rondes complètes")

    fils = [threading.Thread(target=travailler, args=(i,), daemon=True)
            for i in range(args.utilisateurs)]
    print(f"    {args.utilisateurs} utilisateurs simultanés pendant {args.duree}s…")
    for f in fils:
        f.start()
    for f in fils:
        f.join(timeout=args.duree + 60)
    arret.set()
    return res.compteurs.get("itérations", 0)


def scenario_isolation(env, res, args):
    """Deux établissements travaillent en même temps. Aucun ne doit voir l'autre."""
    base = env["base_url"]
    a, b = env["etablissements"][0], env["etablissements"][1]
    mdp = env["mot_de_passe"]
    hA = connexion(base, a["comptes"]["directeur"], mdp)
    hB = connexion(base, b["comptes"]["directeur"], mdp)
    hParentB = connexion(base, b["comptes"]["parent"], mdp)
    fin = time.time() + args.duree

    def croiser(entetes, cible, qui):
        while time.time() < fin:
            _, s, _ = appel(base, f"/api/students/{cible['exemples']['eleve_id']}", entetes)
            if s == 200:
                res.fuite(f"{qui} a obtenu le dossier d'un élève de {cible['etiquette']}")
            _, s, _ = appel(base, f"/api/classes/{cible['exemples']['class_id']}/students", entetes)
            if s == 200:
                res.fuite(f"{qui} a obtenu une classe de {cible['etiquette']}")
            _, s, c = appel(base, f"/api/students?q={cible['exemples']['eleve_nom']}", entetes)
            if s == 200 and isinstance(c, list):
                if any(e.get("last_name") == cible["exemples"]["eleve_nom"] for e in c):
                    res.fuite(f"{qui} a trouvé un élève de {cible['etiquette']} par la recherche")
            res.incremente("tentatives croisées", 3)

    def travailler(entetes, etab, qui):
        while time.time() < fin:
            _, s, c = appel(base, "/api/students", entetes)
            if s != 200 or not isinstance(c, list) or len(c) != etab["eleves_count"]:
                res.echec(f"{qui} ne voit plus ses propres élèves ({s}, "
                          f"{len(c) if isinstance(c, list) else '?'} au lieu de {etab['eleves_count']})")
            res.incremente("lectures légitimes")

    fils = []
    for _ in range(max(args.utilisateurs // 4, 2)):
        fils += [
            threading.Thread(target=travailler, args=(hA, a, "alpha"), daemon=True),
            threading.Thread(target=travailler, args=(hB, b, "beta"), daemon=True),
            threading.Thread(target=croiser, args=(hA, b, "directeur alpha"), daemon=True),
            threading.Thread(target=croiser, args=(hB, a, "directeur beta"), daemon=True),
            threading.Thread(target=croiser, args=(hParentB, a, "parent beta"), daemon=True),
        ]
    print(f"    {len(fils)} threads, deux établissements en parallèle, {args.duree}s…")
    for f in fils:
        f.start()
    for f in fils:
        f.join(timeout=args.duree + 60)
    return res.compteurs.get("tentatives croisées", 0)


def scenario_finance(env, res, args):
    """Guichets simultanés, clés d'idempotence rejouées."""
    base = env["base_url"]
    beta = env["etablissements"][1]
    h = connexion(base, beta["comptes"]["directeur"], env["mot_de_passe"])

    _, _, eleves = appel(base, "/api/students", h)
    cibles = [e["id"] for e in eleves if (e.get("balance") or 0) > 20][:40]
    obligations = []
    for eid in cibles:
        _, s, f = appel(base, f"/api/students/{eid}/financial-summary", h)
        if s != 200:
            continue
        obligations += [o["obligation_id"] for o in f["obligations"] if o["remaining"] > 20]
    if not obligations:
        raise SystemExit("Aucune obligation avec reste à payer — relancez seed_charge.py")

    _, _, avant = appel(base, "/api/reports/summary", h)
    encaisse_avant = avant["financial"]["total_paid"]
    MONTANT = 10
    distincts = threading.Lock()
    cles_reussies = set()

    def guichet(indice):
        for iteration in range(args.iterations_finance):
            obligation = obligations[(indice * 7 + iteration) % len(obligations)]
            cle = f"charge-{indice}-{iteration}"
            corps = {"obligation_id": obligation, "amount": MONTANT,
                     "method": "cash", "idempotency_key": cle}
            ms, s1, c1 = appel(base, "/api/payments", h, methode="POST", corps=corps)
            res.mesure("paiement", ms)
            if s1 == 201:
                with distincts:
                    cles_reussies.add(cle)
            elif s1 not in (200, 409):
                res.echec(f"paiement -> {s1} {c1}")
            # Rejeu immédiat de la MÊME clé : double clic.
            _, s2, c2 = appel(base, "/api/payments", h, methode="POST", corps=corps)
            res.incremente("rejeux")
            if s2 == 201:
                res.fuite(f"rejeu de {cle} a créé un SECOND paiement")
            elif s2 == 200 and s1 in (200, 201) and c2.get("id") != c1.get("id"):
                res.fuite(f"rejeu de {cle} a renvoyé un paiement différent")

    fils = [threading.Thread(target=guichet, args=(i,), daemon=True) for i in range(args.utilisateurs)]
    print(f"    {args.utilisateurs} guichets × {args.iterations_finance} paiements, chacun rejoué une fois…")
    for f in fils:
        f.start()
    for f in fils:
        f.join(timeout=300)

    _, _, apres = appel(base, "/api/reports/summary", h)
    encaisse_apres = apres["financial"]["total_paid"]
    ecart = round(encaisse_apres - encaisse_avant, 2)
    attendu = round(len(cles_reussies) * MONTANT, 2)
    print(f"    encaissé avant  : {encaisse_avant}")
    print(f"    encaissé après  : {encaisse_apres}")
    print(f"    écart constaté  : {ecart}")
    print(f"    écart attendu   : {attendu}  ({len(cles_reussies)} paiements distincts × {MONTANT})")
    if abs(ecart - attendu) > 0.01:
        res.fuite(f"INCOHÉRENCE FINANCIÈRE : écart {ecart} au lieu de {attendu}")
    else:
        print("    -> aucun paiement compté deux fois, aucun perdu")

    # Chaque paiement confirmé a-t-il son reçu ?
    _, s, recus = appel(base, "/api/receipts", h)
    if s == 200:
        print(f"    reçus émis dans l'établissement : {len(recus)}")
    return len(cles_reussies)


SCENARIOS = {
    "fumee": scenario_fumee,
    "charge": scenario_charge,
    "isolation": scenario_isolation,
    "finance": scenario_finance,
}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scenario", choices=list(SCENARIOS) + ["tout"], default="tout")
    p.add_argument("--utilisateurs", type=int, default=20)
    p.add_argument("--duree", type=int, default=20, help="secondes par scénario de durée")
    p.add_argument("--iterations-finance", type=int, default=6)
    p.add_argument("--env", default=CHEMIN_ENV)
    args = p.parse_args(argv)

    with open(args.env, encoding="utf-8") as f:
        env = json.load(f)

    _, statut, _ = appel(env["base_url"], "/api/health")
    if statut != 200:
        raise SystemExit(f"Serveur injoignable sur {env['base_url']} (santé : {statut}).\n"
                         "Démarrez-le sur la base de charge — voir tools/k6/README.md.")

    noms = list(SCENARIOS) if args.scenario == "tout" else [args.scenario]
    global_echecs, global_fuites = [], []
    for nom in noms:
        print(f"\n─── {nom.upper()} " + "─" * (56 - len(nom)))
        res = Resultats()
        debut = time.time()
        try:
            SCENARIOS[nom](env, res, args)
        except SystemExit:
            raise
        except Exception as e:
            res.echec(f"scénario interrompu : {e!r}")
        duree = time.time() - debut

        if res.durees:
            print(f"\n    {'opération':28s} {'n':>6s} {'médiane':>9s} {'p95':>8s} {'max':>8s}")
            for op in sorted(res.durees):
                xs = sorted(res.durees[op])
                p95 = xs[min(int(len(xs) * 0.95), len(xs) - 1)]
                print(f"    {op:28s} {len(xs):>6d} {statistics.median(xs):>8.0f}ms "
                      f"{p95:>7.0f}ms {xs[-1]:>7.0f}ms")
        for cle, valeur in sorted(res.compteurs.items()):
            print(f"    {cle:28s} {valeur}")
        print(f"    durée du scénario : {duree:.1f}s")
        if res.fuites:
            print(f"\n    !! {len(res.fuites)} FUITE(S) :")
            for f in sorted(set(res.fuites))[:10]:
                print(f"       {f}")
        if res.echecs:
            print(f"\n    !! {len(res.echecs)} ÉCHEC(S) :")
            for e in sorted(set(res.echecs))[:10]:
                print(f"       {e}")
        global_echecs += res.echecs
        global_fuites += res.fuites

    print("\n" + "═" * 62)
    if global_fuites:
        print(f"VERDICT : {len(global_fuites)} fuite(s) — INACCEPTABLE")
        return 2
    if global_echecs:
        print(f"VERDICT : {len(global_echecs)} échec(s) fonctionnel(s)")
        return 1
    print("VERDICT : aucun échec, aucune fuite.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
