"""KLASSIO — extraction des phrases françaises de l'application (08/10/2026).

Le logiciel est écrit en français, directement dans les pages et les scripts.
La traduction (assets/js/langue.js) prend la phrase française AFFICHÉE comme
clé : ce script dresse la liste de ces phrases, pour que chaque dictionnaire
(tools/i18n/<langue>.json → assets/i18n/<langue>.js) les couvre toutes.

Sources : le texte des pages app/*.html, les chaînes des scripts de
l'application (assets/js), et les messages d'erreur renvoyés par le serveur
(backend/*.py, champs "error" / "message"), qui s'affichent tels quels.

    python tools/i18n/extraire.py      # écrit tools/i18n/chaines.json
"""
import html
import json
import os
import re
from html.parser import HTMLParser

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = ["ui.js", "admin.js", "app.js", "app-visuel.js", "tableau.js", "facturation.js", "offres.js",
           "motdepasse.js", "loader.js", "langue.js"]
LETTRE = re.compile(r"[A-Za-zÀ-ÿ]")
FRANCAIS = re.compile(r"[a-zà-ÿ]{2,}")


def normaliser(s):
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def utile(s):
    if not s or len(s) < 2 or not LETTRE.search(s):
        return False
    if not FRANCAIS.search(s):            # sigles, codes, « OK »
        return False
    if re.fullmatch(r"[a-z0-9_.\-/?=&#:]+", s):   # identifiants, chemins, classes CSS
        return False
    if re.search(r"[{};]|=>|\bfunction\b|\.html\b|^[a-z]+\.[a-z]+", s):
        return False
    if s[0] in ".(:[" or "[data-" in s or re.fullmatch(r"(Arrow|Page)[A-Z][a-z]+|Escape|Enter|Tab", s):
        return False
    if (re.fullmatch(r"[a-z]{2}-[A-Z]{2}|use strict|tbody tr|url\(|px\"", s) or "=" in s
            or re.fullmatch(r"[a-z]+-[a-z0-9-]+(?: [a-z-]+)*", s) or re.search(r"\b(?:input|textarea|select|button)\b.*[,:\[]", s)
            or s.startswith("var(")):
        return False
    # Les listes de mots du générateur de mots de passe (motdepasse.js) : des
    # mots, pas des phrases — les traduire changerait les mots proposés.
    if s.islower() and len(s.split()) > 8 and not re.search(r"[.,:;'’()]", s):
        return False
    if s in ("hint hint-alerte", "popover notif-pop"):
        return False
    if s.startswith("#") or "@" in s or re.fullmatch(r"[a-z]+[A-Z][A-Za-z0-9]*", s):
        return False
    if re.fullmatch(r"[a-z]+(?:-[a-z0-9]+)+", s):      # classes CSS, clés
        return False
    return True


class Texte(HTMLParser):
    IGNORE = {"script", "style", "code"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pile, self.vus = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in ("br", "img", "input", "meta", "link", "hr"):
            self.pile.append(tag)
        for k, v in attrs:
            if k in ("placeholder", "title", "aria-label", "alt") and v:
                self.vus.append(v)

    def handle_endtag(self, tag):
        if tag in self.pile:
            while self.pile and self.pile.pop() != tag:
                pass

    def handle_data(self, data):
        if not (set(self.pile) & self.IGNORE):
            self.vus.append(data)


def morceaux_html(fragment):
    """Le texte d'un fragment HTML tenu dans une chaîne JS."""
    p = Texte()
    try:
        p.feed(fragment)
    except Exception:
        return [fragment]
    return p.vus


LITTERAL = re.compile(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'')


ATTRIBUT = re.compile(r'(?:placeholder|title|aria-label|alt)="([^"]+)"')


def sans_commentaires(source):
    """Les commentaires de ce dépôt racontent les bugs, apostrophes comprises :
    lus comme du code, ils fabriqueraient de faux littéraux."""
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    return "\n".join(l for l in source.split("\n") if not l.lstrip().startswith("//"))


def litteraux(source):
    """Les littéraux du script, et aussi ceux qu'un `+` colle bout à bout :
    une phrase coupée sur deux lignes ('… votre calendrier ' + 'académique…')
    s'affiche d'un seul tenant, c'est donc d'un seul tenant qu'il faut la
    traduire."""
    precedent, fin, cumul = None, -1, ""
    for m in LITTERAL.finditer(source):
        brut = m.group(1) if m.group(1) is not None else m.group(2)
        brut = brut.replace("\\'", "'").replace('\\"', '"').replace("\\n", " ")
        yield brut
        if precedent is not None and re.fullmatch(r"\s*\+\s*", source[fin:m.start()]):
            cumul += brut
            yield cumul
        else:
            cumul = brut
        precedent, fin = m, m.end()


def chaines_js(source):
    for brut in litteraux(sans_commentaires(source)):
        for a in ATTRIBUT.finditer(brut):
            yield a.group(1)
        # Un littéral coupe souvent une balise en deux : on retire la fin de
        # balise qui l'ouvre et le début de balise qui le ferme.
        if ">" in brut and ("<" not in brut or brut.index(">") < brut.index("<")):
            brut = brut[brut.index(">") + 1:]
        if "<" in brut and ">" not in brut[brut.rindex("<"):]:
            brut = brut[:brut.rindex("<")]
        for bout in morceaux_html(brut):
            if '="' in bout or "<" in bout or ">" in bout or bout.lstrip().startswith('"'):
                continue
            yield bout


def chaines_py(source):
    for m in re.finditer(r'(?:"error"|"message"|"detail")\s*:\s*(f?)"((?:[^"\\]|\\.)*)"', source):
        if m.group(1):          # f-string : on garde les morceaux fixes
            for bout in re.split(r"\{[^}]*\}", m.group(2)):
                yield bout
        else:
            yield m.group(2)
    for m in re.finditer(r"_denied\([^)]*\)|abort\(\d+, \"([^\"]+)\"\)", source):
        if m.group(1):
            yield m.group(1)


def main():
    vus = set()
    for nom in sorted(os.listdir(os.path.join(RACINE, "app"))):
        if nom.endswith(".html"):
            p = Texte()
            p.feed(open(os.path.join(RACINE, "app", nom), encoding="utf-8").read())
            vus.update(p.vus)
    dossier = os.path.join(RACINE, "assets", "js")
    for nom in sorted(os.listdir(dossier)):
        if nom.startswith("page-") or nom in SCRIPTS:
            vus.update(chaines_js(open(os.path.join(dossier, nom), encoding="utf-8").read()))
    for nom in sorted(os.listdir(os.path.join(RACINE, "backend"))):
        if nom.endswith(".py"):
            vus.update(chaines_py(open(os.path.join(RACINE, "backend", nom), encoding="utf-8").read()))
    cles = sorted({normaliser(v) for v in vus if utile(normaliser(v))})
    with open(os.path.join(os.path.dirname(__file__), "chaines.json"), "w", encoding="utf-8") as f:
        json.dump(cles, f, ensure_ascii=False, indent=0)
    print(len(cles), "phrases,", sum(len(c) for c in cles), "caractères")


if __name__ == "__main__":
    main()
