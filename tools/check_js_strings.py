#!/usr/bin/env python3
"""Klassio — garde-fou statique sur assets/js.

Le frontend construit son HTML par concaténation de chaînes. Le piège
classique : une chaîne JS en guillemets doubles qui contient un attribut
HTML lui aussi en guillemets doubles (class="…"). La chaîne se ferme trop
tôt, le reste du HTML devient du code, et la page entière ne se charge plus
— sans autre symptôme qu'une erreur de syntaxe dans la console.

Ce script tokenise chaînes, gabarits, commentaires et littéraux d'expression
régulière, puis vérifie qu'aucun fragment de HTML ne subsiste dans le code.

    python3 tools/check_js_strings.py        # 0 si tout va bien, 1 sinon
"""
import pathlib
import re
import sys

SUSPECT = re.compile(
    r'(?<![\w$])(class|id|type|href|style|data-[a-z]+)=|</[a-z]+>|/>|[A-Za-z_$][\w$]*-[a-z]+\s*(?:full|"|>)'
)
PREV_REGEX_OK = set("(,=:[!&|?{};+-*%~^\n\t ")


def code_segments(src):
    """Renvoie les portions de code (hors chaînes/commentaires/regex) et leur ligne."""
    i, line, buf, seg_start, out, prev = 0, 1, [], 1, [], "\n"
    while i < len(src):
        c = src[i]
        if c == "\n":
            line += 1
        if c in "'\"`":
            out.append(("".join(buf), seg_start))
            buf = []
            quote = c
            i += 1
            while i < len(src):
                if src[i] == "\\":
                    i += 2
                    continue
                if src[i] == "\n":
                    line += 1
                if src[i] == quote:
                    break
                i += 1
            i += 1
            seg_start, prev = line, quote
            continue
        if c == "/" and i + 1 < len(src) and src[i + 1] == "/":
            while i < len(src) and src[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < len(src) and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            line += src.count("\n", i, j)
            i = j + 2
            continue
        if c == "/" and prev in PREV_REGEX_OK:
            i += 1
            while i < len(src) and src[i] != "\n":
                if src[i] == "\\":
                    i += 2
                    continue
                if src[i] == "[":
                    while i < len(src) and src[i] != "]":
                        i += 1
                if src[i] == "/":
                    break
                i += 1
            i += 1
            continue
        if not buf:
            seg_start = line
        buf.append(c)
        if not c.isspace():
            prev = c
        i += 1
    out.append(("".join(buf), seg_start))
    return out


def main():
    root = pathlib.Path(__file__).resolve().parent.parent / "assets" / "js"
    failures = 0
    for path in sorted(root.glob("*.js")):
        hits = []
        for text, line in code_segments(path.read_text()):
            for m in SUSPECT.finditer(text):
                hits.append((line, text[max(0, m.start() - 40):m.start() + 50].replace("\n", " ").strip()))
        if hits:
            failures += 1
            print(f"{path.relative_to(root.parent.parent)} — {len(hits)} fragment(s) HTML hors chaîne")
            for line, frag in hits[:5]:
                print(f"   ~ligne {line} : …{frag}…")
    if failures:
        print(f"\n{failures} fichier(s) à corriger — probablement une chaîne \"…\" contenant class=\"…\".")
        return 1
    print(f"OK — {len(list(root.glob('*.js')))} fichiers JavaScript, aucun HTML hors chaîne.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
