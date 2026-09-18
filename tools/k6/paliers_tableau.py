"""Assemble les résumés JSON des paliers en un seul tableau lisible.

k6 écrit un résumé par palier ; les comparer à l'œil dans six fichiers ne dit
rien. Mis côte à côte, on voit tout de suite où la courbe décroche.
"""
import json
import os
import sys


def lire(chemin):
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def cle(metriques, nom, stat):
    m = metriques.get(nom) or {}
    return m.get(stat)


def main():
    dossier, paliers = sys.argv[1], sys.argv[2:]
    lignes = []
    for n in paliers:
        chemin = os.path.join(dossier, f"palier-{n}.json")
        if not os.path.exists(chemin):
            continue
        d = lire(chemin)
        m = d.get("metrics", {})
        duree = m.get("http_req_duration", {})
        echecs = m.get("http_req_failed", {})
        reqs = m.get("http_reqs", {})
        checks = m.get("checks", {})
        lignes.append({
            "vus": n,
            "med": duree.get("med"),
            "p90": duree.get("p(90)"),
            "p95": duree.get("p(95)"),
            "p99": duree.get("p(99)"),
            "max": duree.get("max"),
            "err": (echecs.get("value") or 0) * 100,
            "rps": reqs.get("rate"),
            "checks": (checks.get("passes") or 0),
            "checks_ko": (checks.get("fails") or 0),
        })

    entete = (f"{'VUs':>5} | {'p50':>8} | {'p90':>8} | {'p95':>8} | {'p99':>9} | "
              f"{'max':>9} | {'erreurs':>8} | {'req/s':>7} | {'checks KO':>9}")
    print(entete)
    print("-" * len(entete))
    for l in lignes:
        f = lambda v: f"{v:.0f} ms" if isinstance(v, (int, float)) else "—"
        print(f"{l['vus']:>5} | {f(l['med']):>8} | {f(l['p90']):>8} | {f(l['p95']):>8} | "
              f"{f(l['p99']):>9} | {f(l['max']):>9} | {l['err']:>7.2f}% | "
              f"{(l['rps'] or 0):>7.1f} | {l['checks_ko']:>9}")


if __name__ == "__main__":
    main()
