"""Retire d'un export k6 ce qui ne doit jamais atteindre un dépôt public.

    python tools/k6/nettoyer_export.py tools/k6/resultats/*.json

`k6 run --summary-export` recopie dans le fichier ce que renvoie `setup()`,
sous la clé `setup_data`. Dans Klassio, `setup()` connecte les comptes de
chaque rôle et renvoie leurs en-têtes `Authorization: Bearer …` : l'export
transporte donc des jetons de session. Ils ne valaient rien jusqu'ici — bases
jetables, serveur local, produit jamais déployé — mais le jour où la campagne
sera rejouée contre un vrai serveur, ce seront des sessions vivantes dans un
dépôt que tout le monde peut lire.

Les mesures sont toutes sous `metrics` et `root_group` : retirer `setup_data`
ne fait perdre aucun chiffre. `backend/tests/test_depot_public.py` échoue si
un export versionné en contient encore.
"""
import json
import sys


def nettoyer(chemin):
    with open(chemin, encoding="utf-8") as f:
        donnees = json.load(f)
    if donnees.pop("setup_data", None) is None:
        return False
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(json.dumps(donnees, indent=4, ensure_ascii=False) + "\n")
    return True


if __name__ == "__main__":
    for chemin in sys.argv[1:]:
        if nettoyer(chemin):
            print(f"  nettoyé : {chemin}")
