"""KLASSIO — client Supabase minimal (PostgREST + Auth), sans dépendance.

Ce module parle au projet Supabase en HTTP. Il sert à deux choses :
  1. vérifier que la configuration est bonne (`status()`), et le dire
     honnêtement — y compris quand ça ne marche pas ;
  2. servir de socle aux usages futurs (stockage de fichiers, lecture REST).

Ce qu'il ne fait PAS : il ne remplace pas la base de Klassio. Les règles de
périmètre (qui voit quel élève) vivent dans `school.py`, côté serveur. Y
accéder par PostgREST depuis le navigateur les contournerait toutes tant que
des politiques RLS équivalentes n'existent pas côté Postgres.
"""
import json
import urllib.error
import urllib.request

import config

TIMEOUT = 12


class SupabaseError(RuntimeError):
    pass


def _key(prefer_service=True):
    if prefer_service and config.SUPABASE_SERVICE_KEY:
        return config.SUPABASE_SERVICE_KEY
    return config.SUPABASE_ANON_KEY or config.SUPABASE_SERVICE_KEY


def request(path, method="GET", body=None, prefer_service=True, extra_headers=None):
    """Appel brut à l'API du projet. `path` commence par /rest/v1 ou /auth/v1."""
    if not config.SUPABASE_URL:
        raise SupabaseError("SUPABASE_URL n'est pas configurée.")
    key = _key(prefer_service)
    if not key:
        raise SupabaseError("Aucune clé Supabase configurée (SUPABASE_ANON_KEY ou SUPABASE_SERVICE_KEY).")
    url = config.SUPABASE_URL + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"apikey": key, "Authorization": "Bearer " + key}
    if data is not None:
        headers["Content-Type"] = "application/json"
    headers.update(extra_headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode() or "null"
            try:
                return resp.status, json.loads(raw)
            except ValueError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode() or "{}"
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw
    except urllib.error.URLError as e:
        raise SupabaseError(f"Projet Supabase injoignable : {e.reason}")


def status():
    """Diagnostic complet et honnête de l'intégration."""
    out = {
        "configured": config.supabase_configured(),
        "url": config.SUPABASE_URL,
        "key_used": "secrète" if config.SUPABASE_SERVICE_KEY else ("publiable" if config.SUPABASE_ANON_KEY else None),
        "reachable": False,
        "authenticated": False,
        "tables": [],
        "detail": None,
    }
    if not config.SUPABASE_URL:
        out["detail"] = "SUPABASE_URL absente."
        return out
    if not out["configured"]:
        out["detail"] = "Clé absente : impossible d'interroger le projet."
        return out
    # Sonde : /auth/v1/settings accepte la clé publiable comme la clé secrète.
    # (La racine /rest/v1/ ne répond qu'à une clé secrète : elle ne dit rien
    # sur la validité d'une clé publiable.)
    try:
        code, body = request("/auth/v1/settings", prefer_service=False)
    except SupabaseError as e:
        out["detail"] = str(e)
        return out
    out["reachable"] = True
    if code == 401:
        out["detail"] = "Clé refusée par Supabase : " + str((body or {}).get("message", "401"))
        return out
    if code >= 400:
        out["detail"] = f"Réponse inattendue ({code})."
        return out
    out["authenticated"] = True
    out["detail"] = "Connexion établie."
    # Inventaire des tables : PostgREST n'expose son schéma qu'à une clé secrète.
    if config.SUPABASE_SERVICE_KEY:
        try:
            code, body = request("/rest/v1/", extra_headers={"Accept": "application/openapi+json"})
            if code == 200 and isinstance(body, dict):
                out["tables"] = sorted(k.lstrip("/") for k in (body.get("paths") or {}) if k not in ("/", ""))
        except SupabaseError:
            pass
    else:
        out["tables_note"] = "inventaire indisponible sans clé secrète"
    return out
