"""KLASSIO — lecture d'un règlement intérieur (08/10/2026).

Le propriétaire a montré le règlement d'une vraie école : un tableau
« Article | Faute ou manquement | Sanction » (« Dérangement → 10 points en
conduite + travail manuel »), une liste de fautes à « renvoi définitif
immédiat », une échelle « De 80 à 100 points : Excellente conduite (E) » et
des « sanctions positives ». Ce module en tire des PROPOSITIONS : la
Direction relit, corrige, coche, et rien n'est enregistré sans elle.

Formats : Word (.docx, tableaux compris), PDF avec texte, texte brut. Une
photo ou un scan sans texte n'est pas lisible ici — aucun service de
reconnaissance de caractères n'est branché, et on le dit plutôt que de
deviner. Aucun modèle de langage : des règles de lecture explicites.
"""
import io
import re
import zipfile
from xml.etree import ElementTree

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

SANCTION = re.compile(
    r"points?|exclu|renvoi|renvoy|confisca|convoca|convoqu|travail|z[ée]ro|retour [àa] la maison|"
    r"perdre|demande de pardon|retenu|payer|d[ée]cline|attendre", re.I)
CATEGORIES = [
    (r"retard", "retard"), (r"absence|absent", "absence"),
    (r"m[ée]rite|f[ée]licit|initiative|propret[ée]|am[ée]lioration|distingu", "bonus"),
    (r"devoir|cahier|document|journal|mat[ée]riel|copie", "autre"),
]
GRAVES = re.compile(r"renvoi d[ée]finitif|exclusion d[ée]finitive", re.I)


class Illisible(Exception):
    """Le fichier ne contient pas de texte exploitable."""


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------

def _docx(raw):
    """Paragraphes et tableaux d'un .docx, sans dépendance : c'est un ZIP de XML.
    Un tableau devient des lignes « cellule ¦ cellule ¦ cellule »."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            xml = z.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError):
        raise Illisible("Ce fichier Word n'a pas pu être ouvert.")
    root = ElementTree.fromstring(xml)
    body = root.find(W + "body")
    out = []

    def texte(el):
        lignes = []
        for p in el.iter(W + "p"):
            t = "".join(x.text or "" for x in p.iter(W + "t")).strip()
            if t:
                lignes.append(t)
        return lignes

    for el in list(body if body is not None else []):
        if el.tag == W + "tbl":
            for tr in el.iter(W + "tr"):
                # Les paragraphes d'une cellule restent sur la MÊME ligne (séparés
                # par U+2028) : un retour à la ligne couperait la ligne du tableau.
                cells = ["\u2028".join(texte(tc)) for tc in tr.findall(W + "tc")]
                out.append(" ¦ ".join(cells))
        elif el.tag == W + "p":
            out.extend(texte(el))
    return "\n".join(out)


def extraire(nom, raw):
    nom = (nom or "").lower()
    if re.search(r"\.(jpe?g|png|webp|heic|gif|bmp)$", nom):
        raise Illisible("Une photo ne peut pas être lue automatiquement : aucun service de lecture d'image n'est branché. "
                        "Envoyez le document en Word (.docx) ou en PDF avec texte, ou saisissez-le à la main.")
    if nom.endswith(".docx"):
        return _docx(raw)
    if nom.endswith(".pdf"):
        from pypdf import PdfReader
        try:
            reader = PdfReader(io.BytesIO(raw))
            return "\n".join((p.extract_text() or "") for p in reader.pages)
        except Exception:
            raise Illisible("Ce PDF n'a pas pu être ouvert.")
    if nom.endswith(".doc"):
        raise Illisible("L'ancien format Word (.doc) n'est pas lisible : enregistrez le fichier en .docx, puis réessayez.")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


# ---------------------------------------------------------------------------
# Analyse
# ---------------------------------------------------------------------------

def _puces(bloc):
    """Découpe une cellule ou un passage en éléments (« - Retard », lignes)."""
    morceaux = re.split(r"[\n\u2028]|(?:^|\s)[-–•]\s+", bloc)
    return [" ".join(m.split()).strip(" -–•;,.") for m in morceaux if m and m.strip(" -–•;,.")]


def _categorie(texte):
    low = texte.lower()
    return next((cat for pat, cat in CATEGORIES if re.search(pat, low)), "comportement")


def _points(sanction):
    m = re.search(r"(\d{1,3})\s*points?", sanction, re.I)
    return -int(m.group(1)) if m else None


def _proposer(faute, sanction, source):
    faute = faute.strip()
    if len(faute) < 3 or len(faute) > 160:
        return None
    pts = _points(sanction or "")
    grave = bool(GRAVES.search(sanction or ""))
    if pts is None:
        pts = -20 if grave else -5
    cat = _categorie(faute)
    if cat == "bonus":
        pts = abs(pts) if pts else 2
    return {"label": faute[:120], "category": cat, "points": max(-100, min(100, pts)),
            "measure": (sanction or "").strip()[:300] or None, "severity": "high" if grave else ("medium" if pts <= -10 else "low"),
            "source": source[:400]}


def analyser(texte):
    texte = (texte or "").replace("\r", "")
    propositions, vus = [], set()

    def ajouter(p):
        if not p:
            return
        cle = p["label"].lower()[:60]
        if cle in vus:
            return
        vus.add(cle)
        propositions.append(p)

    # 1. Tableaux (Word) : « Article ¦ fautes ¦ sanctions ». Les fautes et les
    #    sanctions d'une même ligne sont appariées dans l'ordre ; s'il y a
    #    moins de sanctions que de fautes, la dernière vaut pour les suivantes.
    for ligne in texte.split("\n"):
        if "¦" not in ligne:
            continue
        cells = [c.strip() for c in ligne.split("¦")]
        if len(cells) < 2:
            continue
        if re.match(r"^\s*article\s*\d+", cells[0], re.I) or len(cells) >= 3:
            fautes_txt, sanctions_txt = (cells[1], cells[2]) if len(cells) >= 3 else (cells[0], cells[1])
            if re.search(r"faute|manquement|sanction", fautes_txt, re.I) and len(fautes_txt) < 40:
                continue  # ligne d'en-tête
            fautes, sanctions = _puces(fautes_txt), _puces(sanctions_txt)
            for i, f in enumerate(fautes):
                s = sanctions[i] if i < len(sanctions) else (sanctions[-1] if sanctions else "")
                ajouter(_proposer(f, s, ligne))

    # 2. Texte linéaire (PDF) : « Article N » … ; dans chaque bloc, les puces
    #    qui ressemblent à une sanction sont des sanctions, les autres des fautes.
    blocs = re.split(r"\n(?=\s*article\s*\d+)", texte, flags=re.I)
    for b in blocs:
        if "¦" in b or not re.match(r"\s*article\s*\d+", b, re.I):
            continue
        corps = re.sub(r"^\s*article\s*\d+\s*[:.\-]?", "", b, flags=re.I)
        puces = _puces(corps)
        fautes = [p for p in puces if not SANCTION.search(p)]
        sanctions = [p for p in puces if SANCTION.search(p)]
        if not fautes or not sanctions:
            continue  # un article du règlement en prose, pas une ligne du barème
        for i, f in enumerate(fautes):
            ajouter(_proposer(f, sanctions[i] if i < len(sanctions) else sanctions[-1], b))

    # 3. « Les fautes qui nécessitent un renvoi définitif immédiat : » + puces.
    m = re.search(r"renvoi d[ée]finitif imm[ée]diat\s*:?(.*?)(?:\n\s*\n|appr[ée]ciation de la conduite|n\.\s*b\.|$)", texte, re.I | re.S)
    if m:
        for f in _puces(m.group(1)):
            p = _proposer(f, "Renvoi définitif immédiat (décision du conseil de discipline)", f)
            if p:
                p["points"], p["severity"] = -100, "high"
                ajouter(p)

    # 4. Sanctions positives : « Sera félicité publiquement : - Tout élève qui… »
    m = re.search(r"sanctions? positives?\s*:?(.*?)(?:\n\s*titre|\Z)", texte, re.I | re.S)
    if m:
        for f in _puces(re.sub(r"^.*?:", "", m.group(1), count=1, flags=re.S)):
            if len(f) > 12:
                p = _proposer(f, "Félicitations publiques", f)
                if p:
                    p["category"], p["points"], p["severity"] = "bonus", 2, "low"
                    ajouter(p)

    # 5. Échelle de conduite : « De 80 à 100 points : Excellente conduite (E) »,
    #    « A partir de 28 points : Mauvaise conduite (Ma) ».
    echelle = []
    for a, b, lib in re.findall(r"de\s+(\d{1,3})\s+[àa]\s+(\d{1,3})\s+points?\s*:\s*([^\n]+)", texte, re.I):
        echelle.append([min(int(a), int(b)), " ".join(lib.split()).strip(" .*")[:40]])
    for _a, lib in re.findall(r"[àa] partir de\s+(\d{1,3})\s+points?\s*:\s*([^\n]+)", texte, re.I):
        echelle.append([0, " ".join(lib.split()).strip(" .*")[:40]])
    echelle = sorted({e[0]: e for e in echelle}.values(), key=lambda e: -e[0])
    plafond = max([int(x) for x in re.findall(r"[àa]\s+(\d{2,3})\s+points?", texte, re.I)] or [0])
    return {"proposals": propositions[:80], "conduct_scale": echelle if len(echelle) >= 2 else None,
            "capital": plafond if 50 <= plafond <= 1000 and echelle else None}
