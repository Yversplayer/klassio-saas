"""KLASSIO — sortir les données de l'établissement.

Klassio savait importer depuis Excel ; rien n'en sortait. Pour un logiciel
qu'on fait payer, c'est d'abord une question de confiance : « et si j'arrête de
payer, je perds tout ? » est la première question d'un directeur prudent.

TROIS RÈGLES QUI GOUVERNENT CE MODULE

1. AUCUNE DONNÉE INVENTÉE. Chaque ligne vient d'un SELECT sur les tables
   réelles. Une feuille vide reste vide — on ne fabrique pas de contenu pour
   faire joli, et on n'ajoute pas un fichier au ZIP juste pour ressembler à un
   exemple de documentation.

2. LE PÉRIMÈTRE EST DANS LE SQL. Chaque requête porte `tenant_id` et, quand la
   donnée appartient à une année, `academic_year_id`. Un filtre venu du
   navigateur n'est jamais une autorisation : il restreint, il n'élargit pas.

3. EXPORTER N'EST PAS SUPPRIMER. Ce module ne fait que lire. L'archivage d'une
   année est une stratégie de stockage, jamais un effacement déguisé.
"""
import io
import json
import os
import time
import zipfile

import db

VERSION_FORMAT = "1.0"

# Où sont posées les archives. PAS dans un dossier servi par le web : le
# frontend est un site statique distinct, `backend/` n'est jamais exposé. Le
# téléchargement passe par une route qui revérifie l'authentification et
# l'appartenance à l'établissement.
DOSSIER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exports_store")

CONSERVATION_SECONDES = 7 * 24 * 3600


# ---------------------------------------------------------------------------
# Jeux de données — un SELECT réel par feuille
# ---------------------------------------------------------------------------

def _valeurs(ligne):
    """Les VALEURS d'une ligne, quel que soit le moteur.

    `sqlite3.Row` se convertit en tuple de VALEURS. `psycopg` est configuré
    avec `dict_row` : `tuple()` sur un dict donne ses CLÉS. Sans cette
    distinction, l'archive produite en PostgreSQL contenait les noms de
    colonnes répétés à la place des données — « code, last_name, first_name »
    sur chaque ligne, autant de fois qu'il y a d'élèves.

    Invisible en développement, où tout tourne sur SQLite. Attrapé par la
    campagne PostgreSQL, qui existe exactement pour ça.
    """
    if hasattr(ligne, "values") and callable(getattr(ligne, "values")):
        return tuple(ligne.values())
    return tuple(ligne)


def _annee(colonne, aid):
    """Construit le filtre d'année — SANS le paramétrer avec NULL.

    `WHERE (? IS NULL OR colonne = ?)` fonctionne en SQLite et ÉCHOUE en
    PostgreSQL : « could not determine data type of parameter ». Le moteur ne
    peut pas déduire le type d'un paramètre comparé à NULL. C'est la catégorie
    de défaut que REPRISE signale comme la plus traître — invisible en
    développement, fatale en production.

    On assemble donc la clause en Python et on ne passe en paramètre que des
    valeurs réelles. Aucune valeur externe n'entre dans le SQL : `colonne` est
    une constante écrite ici, `aid` reste un paramètre lié.
    """
    return (f" AND {colonne}=?", (aid,)) if aid else ("", ())


def _eleves(conn, tid, aid, f):
    return ["Identifiant", "Nom", "Prénom", "Classe", "Statut", "Créé le"], conn.execute(
        f"""SELECT s.code, s.last_name, s.first_name, COALESCE(c.name,''), s.status, s.created_at
            FROM students s LEFT JOIN classes c ON c.id = s.class_id
            WHERE s.tenant_id=?{_annee('s.academic_year_id', aid)[0]}
            ORDER BY c.name, s.last_name, s.first_name""", (tid,) + _annee('s.academic_year_id', aid)[1]).fetchall()


def _classes(conn, tid, aid, f):
    return ["Classe", "Niveau", "Effectif"], conn.execute(
        f"""SELECT c.name, COALESCE(c.level,''),
                  (SELECT COUNT(*) FROM students s WHERE s.class_id=c.id AND s.status='active')
            FROM classes c WHERE c.tenant_id=?{_annee('c.academic_year_id', aid)[0]}
            ORDER BY c.name""", (tid,) + _annee('c.academic_year_id', aid)[1]).fetchall()


def _enseignants(conn, tid, aid, f):
    return ["Nom", "E-mail", "Classe", "Titulaire"], conn.execute(
        f"""SELECT u.name, u.email, c.name, CASE WHEN ct.is_titulaire=1 THEN 'oui' ELSE 'non' END
           FROM class_teachers ct JOIN users u ON u.id = ct.user_id
           JOIN classes c ON c.id = ct.class_id
            WHERE ct.tenant_id=?{_annee('c.academic_year_id', aid)[0]}
            ORDER BY u.name, c.name""", (tid,) + _annee('c.academic_year_id', aid)[1]).fetchall()


def _responsables(conn, tid, aid, f):
    return ["Élève", "Identifiant élève", "Responsable", "Téléphone", "E-mail"], conn.execute(
        f"""SELECT s.last_name||' '||s.first_name, s.code,
                  g.last_name||' '||g.first_name, COALESCE(g.phone,''), COALESCE(g.email,'')
           FROM student_guardians sg
           JOIN guardians g ON g.id = sg.guardian_id
           JOIN students s ON s.id = sg.student_id
            WHERE sg.tenant_id=?{_annee('s.academic_year_id', aid)[0]}
            ORDER BY s.last_name, s.first_name""", (tid,) + _annee('s.academic_year_id', aid)[1]).fetchall()


def _resultats(conn, tid, aid, f):
    """Uniquement la version COURANTE de chaque note.

    `is_current` existe parce qu'une note corrigée crée une version au lieu
    d'écraser l'ancienne. Exporter tout l'historique livrerait plusieurs notes
    pour la même matière et ferait croire à une incohérence : l'archive d'une
    année doit refléter ce qui fait foi.
    """
    return ["Élève", "Identifiant", "Classe", "Période", "Matière", "Note", "Barème", "Appréciation"], conn.execute(
        f"""SELECT s.last_name||' '||s.first_name, s.code, COALESCE(c.name,''),
                  COALESCE(g.period,''), g.subject, g.score, g.max_score, COALESCE(g.comment,'')
           FROM grades g JOIN students s ON s.id = g.student_id
           LEFT JOIN classes c ON c.id = g.class_id
            WHERE g.tenant_id=? AND g.is_current=1{_annee('s.academic_year_id', aid)[0]}
            ORDER BY c.name, s.last_name, g.period, g.subject""", (tid,) + _annee('s.academic_year_id', aid)[1]).fetchall()


def _presences(conn, tid, aid, f):
    return ["Date", "Élève", "Identifiant", "Classe", "Statut", "Note"], conn.execute(
        f"""SELECT a.date, s.last_name||' '||s.first_name, s.code, COALESCE(c.name,''),
                  a.status, COALESCE(a.note,'')
           FROM attendance a JOIN students s ON s.id = a.student_id
           LEFT JOIN classes c ON c.id = a.class_id
            WHERE a.tenant_id=?{_annee('s.academic_year_id', aid)[0]}
            ORDER BY a.date DESC, c.name, s.last_name""", (tid,) + _annee('s.academic_year_id', aid)[1]).fetchall()


def _discipline(conn, tid, aid, f):
    """Sans `internal_note` : la note interne est réservée au DD et à la
    Direction dans le produit ; un fichier qui circule ne garde pas cette
    distinction."""
    return ["Date", "Élève", "Identifiant", "Classe", "Catégorie", "Titre", "Gravité", "Points", "Mesure"], conn.execute(
        f"""SELECT i.occurred_at, s.last_name||' '||s.first_name, s.code, COALESCE(c.name,''),
                  COALESCE(i.category,''), i.title, COALESCE(i.severity,''), COALESCE(i.points,0),
                  COALESCE(i.action_taken,'')
           FROM incidents i JOIN students s ON s.id = i.student_id
           LEFT JOIN classes c ON c.id = i.class_id
            WHERE i.tenant_id=?{_annee('s.academic_year_id', aid)[0]}
            ORDER BY i.occurred_at DESC""", (tid,) + _annee('s.academic_year_id', aid)[1]).fetchall()


def _obligations(conn, tid, aid, f):
    return ["Élève", "Identifiant", "Frais", "Montant", "Devise", "Échéance", "Statut"], conn.execute(
        f"""SELECT s.last_name||' '||s.first_name, s.code, COALESCE(ci.name,''),
                  o.amount, o.currency, COALESCE(o.due_date,''), COALESCE(o.status,'')
           FROM obligations o JOIN students s ON s.id = o.student_id
           LEFT JOIN catalog_items ci ON ci.id = o.catalog_item_id
            WHERE o.tenant_id=?{_annee('o.academic_year_id', aid)[0]}
            ORDER BY s.last_name, s.first_name""", (tid,) + _annee('o.academic_year_id', aid)[1]).fetchall()


def _paiements(conn, tid, aid, f):
    """Uniquement les paiements CONFIRMÉS : une intention non confirmée n'est
    pas de l'argent, et la faire figurer dans une archive comptable serait
    inexact."""
    return ["Date", "Élève", "Identifiant", "Montant", "Devise", "Méthode", "Reçu", "Référence"], conn.execute(
        f"""SELECT COALESCE(p.confirmed_at, p.created_at), s.last_name||' '||s.first_name, s.code,
                  p.amount, p.currency, p.method, COALESCE(r.number,''), COALESCE(p.provider_reference,'')
           FROM payments p JOIN obligations o ON o.id = p.obligation_id
           JOIN students s ON s.id = o.student_id
           LEFT JOIN receipts r ON r.payment_id = p.id
            WHERE p.tenant_id=? AND p.status='CONFIRMED'{_annee('o.academic_year_id', aid)[0]}
            ORDER BY p.confirmed_at DESC""", (tid,) + _annee('o.academic_year_id', aid)[1]).fetchall()


def _recus(conn, tid, aid, f):
    return ["Numéro", "Date", "Élève", "Identifiant", "Montant", "Devise", "Méthode", "Libellé"], conn.execute(
        f"""SELECT r.number, r.created_at, s.last_name||' '||s.first_name, s.code,
                  r.amount, r.currency, r.method, COALESCE(r.label,'')
           FROM receipts r JOIN students s ON s.id = r.student_id
           JOIN payments p ON p.id = r.payment_id
           JOIN obligations o ON o.id = p.obligation_id
            WHERE r.tenant_id=?{_annee('o.academic_year_id', aid)[0]}
            ORDER BY r.number""", (tid,) + _annee('o.academic_year_id', aid)[1]).fetchall()


JEUX = {
    "students": ("Eleves", _eleves),
    "classes": ("Classes", _classes),
    "teachers": ("Enseignants", _enseignants),
    "guardians": ("Responsables", _responsables),
    "results": ("Resultats", _resultats),
    "attendance": ("Presences", _presences),
    "discipline": ("Discipline", _discipline),
    "obligations": ("Obligations", _obligations),
    "payments": ("Paiements", _paiements),
    "receipts": ("Recus", _recus),
}


# ---------------------------------------------------------------------------
# Fabrication des fichiers
# ---------------------------------------------------------------------------

def ecrire_xlsx(colonnes, lignes):
    """Un classeur Excel en mémoire.

    `openpyxl` est déjà une dépendance — `ingestion.py` s'en sert pour LIRE les
    fichiers de l'école. L'écriture ne coûte donc aucun paquet supplémentaire.
    `write_only` garde la mémoire plate : une école de 2 000 élèves avec 80
    jours d'appel produit 160 000 lignes de présence, qu'on ne veut pas voir
    tenir en RAM d'un seul bloc.
    """
    import openpyxl
    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet(title="Données")
    ws.append(list(colonnes))
    for ligne in lignes:
        # Une valeur None devient une cellule vide, pas la chaîne « None ».
        ws.append(["" if v is None else v for v in ligne])
    tampon = io.BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


def construire_archive(conn, tenant_id, annee_id, nom_etablissement, libelle_annee,
                       demandeur, jeux=None):
    """L'archive annuelle : un .zip de classeurs, plus un manifeste.

    On n'ajoute QUE les feuilles qui ont des données. Un fichier vide dans une
    archive laisse croire qu'une donnée a été perdue alors qu'elle n'a jamais
    existé — la vérité est dans le manifeste, qui liste ce qui a été trouvé.
    """
    noms = jeux or list(JEUX)
    comptes = {}
    tampon = io.BytesIO()
    racine = f"Klassio_{_assainir(libelle_annee or 'annee')}"

    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as zf:
        for cle in noms:
            entree = JEUX.get(cle)
            if not entree:
                continue
            nom_feuille, constructeur = entree
            colonnes, lignes = constructeur(conn, tenant_id, annee_id, {})
            lignes = [_valeurs(r) for r in lignes]
            comptes[nom_feuille] = len(lignes)
            if not lignes:
                continue
            zf.writestr(f"{racine}/{nom_feuille}.xlsx", ecrire_xlsx(colonnes, lignes))

        manifeste = {
            "format_version": VERSION_FORMAT,
            "etablissement": nom_etablissement,
            "annee_scolaire": libelle_annee,
            "genere_le": time.strftime("%Y-%m-%d %H:%M:%S"),
            "genere_par": demandeur,
            "feuilles": comptes,
            "total_lignes": sum(comptes.values()),
            # Ce que le manifeste NE contient pas, volontairement : aucune clé
            # d'API, aucun jeton, aucun mot de passe, aucun chemin système. Une
            # archive se transmet, s'ouvre ailleurs, se conserve des années.
            "avertissement": "Cette archive contient des données personnelles d'élèves et de "
                             "familles. Conservez-la comme un document confidentiel.",
        }
        zf.writestr(f"{racine}/Manifest.json",
                    json.dumps(manifeste, ensure_ascii=False, indent=2))

    return tampon.getvalue(), comptes


def _assainir(nom):
    """Un nom de fichier sûr : ni séparateur, ni remontée de dossier."""
    garde = [c if (c.isalnum() or c in "-_") else "-" for c in str(nom or "")]
    return ("".join(garde).strip("-") or "export")[:60]


def chemin_archive(tenant_id, export_id):
    """Un chemin qui ne peut pas sortir du dossier prévu : les deux composants
    sont des identifiants hexadécimaux produits par le serveur, jamais des
    valeurs venues d'une requête."""
    dossier = os.path.join(DOSSIER, _assainir(tenant_id))
    os.makedirs(dossier, exist_ok=True)
    return os.path.join(dossier, _assainir(export_id) + ".zip")


def purger_expires(conn, tenant_id):
    """Les archives ne s'accumulent pas indéfiniment sur le serveur.

    Le fichier part, la LIGNE reste : l'historique doit continuer de dire
    qu'un export a eu lieu, quand et par qui. Effacer la trace en même temps
    que le fichier priverait la Direction de la seule information qui lui
    permet de savoir si l'année a déjà été sauvegardée.
    """
    maintenant = time.time()
    rows = conn.execute(
        "SELECT id, expires_at FROM exports WHERE tenant_id=? AND status='READY'",
        (tenant_id,)).fetchall()
    for r in rows:
        try:
            if r["expires_at"] and float(r["expires_at"]) < maintenant:
                chemin = chemin_archive(tenant_id, r["id"])
                if os.path.exists(chemin):
                    os.remove(chemin)
                conn.execute("UPDATE exports SET status='EXPIRED' WHERE id=?", (r["id"],))
        except (TypeError, ValueError, OSError):
            continue
    conn.commit()
