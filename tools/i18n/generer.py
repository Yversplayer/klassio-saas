"""KLASSIO — dictionnaires de l'interface (08/10/2026).

    python tools/i18n/generer.py                 # tools/i18n/<code>.json → assets/i18n/<code>.js
    python tools/i18n/generer.py fusionner en D  # intègre les lots D/en-*.json (indices de D/source.json)

Un dictionnaire (tools/i18n/<code>.json) associe la phrase française à sa
traduction ("d") et porte quelques motifs pour les phrases qui enveloppent
une donnée ("p" : expression régulière, remplacement). Le fichier produit
dans assets/i18n/ est ce que charge assets/js/langue.js.

La couverture est rapportée contre tools/i18n/chaines.json (extraire.py) :
une phrase ajoutée au logiciel sans traduction s'affiche en français, jamais
en blanc — mais elle se voit ici.
"""
import glob
import hashlib
import json
import os
import re
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.abspath(os.path.join(ICI, "..", ".."))
SORTIE = os.path.join(RACINE, "assets", "i18n")
EXCLUS = {"chaines.json"}


def charger(code):
    p = os.path.join(ICI, code + ".json")
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))
    return {"d": {}, "p": []}


def ecrire(code, dico):
    with open(os.path.join(ICI, code + ".json"), "w", encoding="utf-8") as f:
        json.dump({"d": dict(sorted(dico["d"].items())), "p": dico.get("p", [])}, f, ensure_ascii=False, indent=1)


def fusionner(code, dossier):
    source = json.load(open(os.path.join(dossier, "source.json"), encoding="utf-8"))
    dico = charger(code)
    n = 0
    for lot in sorted(glob.glob(os.path.join(dossier, code + "-*.json"))):
        for i, t in json.load(open(lot, encoding="utf-8")).items():
            if t and t.strip():
                dico["d"][source[int(i)]] = t
                n += 1
    ecrire(code, dico)
    print(code, ":", n, "traductions intégrées")


def generer():
    chaines = set(json.load(open(os.path.join(ICI, "chaines.json"), encoding="utf-8")))
    os.makedirs(SORTIE, exist_ok=True)
    for p in sorted(glob.glob(os.path.join(ICI, "*.json"))):
        nom = os.path.basename(p)
        if nom in EXCLUS:
            continue
        code = nom[:-5]
        dico = charger(code)
        # Une traduction identique à la clé n'apprend rien au navigateur.
        d = {k: v for k, v in dico["d"].items() if v and v != k}
        # Variantes sans la ponctuation qui colle un morceau au précédent :
        # « · signalé en classe » s'affiche aussi « 6e F · signalé en classe »,
        # que le navigateur découpe en « signalé en classe ».
        for k, v in list(d.items()):
            for pre in ("· ", "— ", ", "):
                if k.startswith(pre) and v.startswith(pre) and k[len(pre):] not in d:
                    d[k[len(pre):]] = v[len(pre):]
            if k.endswith(" :") and k[:-2] not in d and v.rstrip(" :") != v:
                d[k[:-2]] = v.rstrip(" :")
        corps = json.dumps({"code": code, "d": d, "p": dico.get("p", [])}, ensure_ascii=False, separators=(",", ":"))
        with open(os.path.join(SORTIE, code + ".js"), "w", encoding="utf-8") as f:
            f.write("// Généré par tools/i18n/generer.py — ne pas éditer à la main.\n")
            f.write("window.KLASSIO_I18N=" + corps + ";\n")
        couvert = len(chaines & set(dico["d"]))
        print(f"{code} : {couvert}/{len(chaines)} phrases ({100 * couvert // max(1, len(chaines))} %), {os.path.getsize(os.path.join(SORTIE, code + '.js')) // 1024} Ko")
    versionner()


def versionner():
    """Le navigateur garde un dictionnaire en cache tant que son ?v= ne change
    pas : la version suit le CONTENU des dictionnaires et de langue.js, et se
    reporte dans langue.js (chemin des dictionnaires) et dans chaque page."""
    langue = os.path.join(RACINE, "assets", "js", "langue.js")
    h = hashlib.sha256()
    for p in sorted(glob.glob(os.path.join(SORTIE, "*.js"))):
        h.update(open(p, "rb").read())
    src = open(langue, encoding="utf-8").read()
    h.update(re.sub(r'var VERSION = "\d+";', "", src).encode())
    v = str(1800000000 + int(h.hexdigest()[:7], 16))
    src = re.sub(r'var VERSION = "\d+";', f'var VERSION = "{v}";', src)
    open(langue, "w", encoding="utf-8").write(src)
    for page in glob.glob(os.path.join(RACINE, "app", "*.html")):
        html = open(page, encoding="utf-8").read()
        neuf = re.sub(r"assets/js/langue\.js\?v=\d+", f"assets/js/langue.js?v={v}", html)
        if neuf != html:
            open(page, "w", encoding="utf-8").write(neuf)
    print("version", v)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "fusionner":
        fusionner(sys.argv[2], sys.argv[3])
    else:
        generer()
