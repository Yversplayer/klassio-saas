"""Règle l'origine du backend dans TOUT le frontend, en une commande.

    python3 tools/configurer_origine.py                          # simulation
    python3 tools/configurer_origine.py --origine https://klassio.example --appliquer
    python3 tools/configurer_origine.py --meme-origine --appliquer
    python3 tools/configurer_origine.py --dev --appliquer         # revenir au local

POURQUOI CET OUTIL EXISTE
Le frontend est statique : aucun build, aucun bundler, donc aucune variable
d'environnement ne peut l'atteindre. Deux choses devaient pourtant changer au
déploiement, et elles étaient éparpillées :

  1. l'adresse de l'API, écrite en dur dans app.js ET page-invitation.js ;
  2. la directive `connect-src` de la CSP, répétée dans 36 pages HTML.

La CSP est une balise <meta> : elle ne peut pas lire une valeur calculée en
JavaScript. Il faut donc la réécrire dans les fichiers, et c'est exactement ce
que fait ce script. Sans lui, le navigateur refuse TOUS les appels en
production — pas une panne partielle, un produit muet.

LE CAS LE PLUS SIMPLE EST `--meme-origine` : un seul domaine, l'API servie sous
/api. `connect-src 'self'` suffit alors, et il n'y a plus aucune adresse à
maintenir. Ne passez `--origine` que si le frontend et l'API vivent réellement
sur deux domaines — un statique sur CDN et une API sur un dyno, par exemple.
"""
import argparse
import os
import re
import sys

RACINE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DEV = "http://localhost:5001"

# `connect-src` suivi de tout ce qui n'est pas un point-virgule.
CONNECT = re.compile(r"connect-src\s+[^;\"']*")
# La ligne qui pose l'origine explicite dans ui.js, si elle existe déjà.
MARQUEUR = "window.KLASSIO_API_ORIGIN"


def fichiers_html():
    ignores = {"backend_venv", ".git", "node_modules"}
    for dossier, sous, noms in os.walk(RACINE):
        sous[:] = [d for d in sous if d not in ignores and not d.startswith(".")]
        for n in noms:
            if n.endswith(".html"):
                yield os.path.join(dossier, n)


def valeur_connect_src(origine):
    """`'self'` couvre la même origine. On n'ajoute une adresse que si elle
    diffère réellement — une CSP qui autorise un domaine inutile est une
    permission qu'on a oublié de retirer."""
    if not origine:
        return "connect-src 'self'"
    return f"connect-src 'self' {origine}"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--origine", help="adresse de l'API (ex. https://api.klassio.cd)")
    g.add_argument("--meme-origine", action="store_true",
                   help="l'API est servie par le même domaine que les pages")
    g.add_argument("--dev", action="store_true", help=f"revenir à {DEV}")
    p.add_argument("--appliquer", action="store_true",
                   help="écrit réellement (sans ce drapeau, simulation seule)")
    args = p.parse_args(argv)

    if args.meme_origine:
        origine = ""
    elif args.dev:
        origine = DEV
    elif args.origine:
        origine = args.origine.rstrip("/")
        if not origine.startswith(("http://", "https://")):
            p.error("l'origine doit commencer par http:// ou https://")
        if origine.startswith("http://") and "localhost" not in origine and "127.0.0.1" not in origine:
            print("REFUS : une origine http:// non locale ferait transiter les jetons de\n"
                  "session en clair. Utilisez https://.", file=sys.stderr)
            return 2
    else:
        origine = DEV   # simulation par défaut : on montre l'état visé en dev

    cible = valeur_connect_src(origine)
    changes, inchanges = [], 0
    for chemin in sorted(fichiers_html()):
        texte = open(chemin, encoding="utf-8").read()
        if "connect-src" not in texte:
            continue
        nouveau = CONNECT.sub(cible, texte)
        if nouveau == texte:
            inchanges += 1
            continue
        changes.append(os.path.relpath(chemin, RACINE))
        if args.appliquer:
            open(chemin, "w", encoding="utf-8").write(nouveau)

    # L'origine explicite pour le JS : seulement quand elle diffère des règles
    # par défaut de KlassioUI.apiOrigin() — c'est-à-dire pour un frontend servi
    # ailleurs que l'API.
    besoin_marqueur = bool(origine) and origine != DEV
    print(f"Origine visée : {origine or '(même origine que les pages)'}")
    print(f"Directive posée : {cible}")
    print(f"Pages HTML à modifier : {len(changes)}  (déjà conformes : {inchanges})")
    for c in changes[:8]:
        print(f"  {c}")
    if len(changes) > 8:
        print(f"  … et {len(changes) - 8} autres")
    if besoin_marqueur:
        print(f"\nÀ poser AVANT ui.js dans les pages (frontend et API sur deux domaines) :")
        print(f'  <script>{MARQUEUR} = "{origine}";</script>')
    if not args.appliquer:
        print("\nSimulation — rien n'a été écrit. Relancez avec --appliquer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
