#!/bin/sh
# Klassio — prépare `dist/`, le SEUL dossier que Cloudflare publie.
#
# POURQUOI UNE LISTE BLANCHE, ET PAS UNE LISTE D'EXCLUSIONS. Le dépôt contient
# `backend/`, AGENTS.md, DEPLOIEMENT.md, render.yaml, .mcp.json… Publier la
# racine et « exclure ce qui ne doit pas sortir » échoue le jour où quelqu'un
# ajoute un fichier sans penser à l'exclure. C'est arrivé côté Flask : la
# première route de service de fichiers servait la racine, et
# `/assets/../backend/klassio.db` sortait en 200. On copie donc ce qui est
# public — exactement la règle de `_fichier_frontend` (backend/app.py) :
# les pages .html de premier niveau, trois fichiers publics, `app/` et `assets/`.
set -eu
cd "$(dirname "$0")/.."
rm -rf dist
mkdir -p dist
cp ./*.html dist/
cp robots.txt sitemap.xml favicon.ico dist/
cp -R app assets dist/
# Ce qui n'a rien à faire en ligne, même dans un dossier public.
find dist \( -name '.DS_Store' -o -name '_src' \) -prune -exec rm -rf {} +
echo "dist/ prêt : $(find dist -type f | wc -l | tr -d ' ') fichiers"
