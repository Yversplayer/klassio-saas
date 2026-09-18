"""KLASSIO — vérification de l'intégration Supabase.

Dit ce qui est configuré, ce qui répond, et ce qui manque. Aucune clé n'est
affichée en clair.

    python backend/tools/supabase_check.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import config  # noqa: E402
import supabase_client  # noqa: E402


def main():
    print("Configuration")
    for label, value in (
        ("URL du projet", config.SUPABASE_URL or "absente"),
        ("Clé publiable (anon)", config.mask(config.SUPABASE_ANON_KEY)),
        ("Clé de service", config.mask(config.SUPABASE_SERVICE_KEY)),
        ("Connexion Postgres", "configurée" if config.SUPABASE_DB_URL else "absente"),
        ("Moteur de données actif", config.DB_BACKEND),
        ("Fichier .env", config.ENV_PATH if os.path.exists(config.ENV_PATH) else "absent"),
    ):
        print(f"  {label:<24} {value}")

    print("\nConnexion")
    try:
        st = supabase_client.status()
    except Exception as e:  # pragma: no cover - diagnostic
        print(f"  Échec : {e}")
        return 1
    print(f"  Projet joignable        {'oui' if st['reachable'] else 'non'}")
    print(f"  Clé acceptée            {'oui' if st['authenticated'] else 'non'}")
    print(f"  Clé utilisée            {st['key_used'] or '—'}")
    print(f"  Détail                  {st['detail']}")
    if st["tables"]:
        print(f"  Tables exposées         {len(st['tables'])} : {', '.join(st['tables'][:12])}")
    elif st["authenticated"]:
        print("  Tables exposées         aucune (base vide côté Supabase)")

    manquant = []
    if not config.SUPABASE_URL:
        manquant.append("SUPABASE_URL")
    if not config.SUPABASE_ANON_KEY:
        manquant.append("SUPABASE_ANON_KEY")
    if not config.SUPABASE_DB_URL:
        manquant.append("SUPABASE_DB_URL (indispensable pour migrer les données)")
    if manquant:
        print("\nIl manque :")
        for m in manquant:
            print(f"  - {m}")
        print(f"\nRenseignez-les dans {config.ENV_PATH} (modèle : backend/.env.example).")
        return 1
    print("\nConfiguration complète.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
