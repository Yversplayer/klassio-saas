"""KLASSIO — Générateur de bulletins scolaires imprimables (format A4 PDF 1.4).

Ce module produit l'artefact imprimable officiel attendu par les établissements
scolaires de RDC (écoles conventionnées, publiques et privées sous régime EPST).

Principes non négociables :
  1. AUCUN RECALCUL : il reçoit directement le dictionnaire composé par
     `school.bulletin()` et n'altère aucune moyenne, aucun rang, aucune cote.
     La source de vérité reste unique.
  2. ZÉRO DÉPENDANCE BINAIRE EXTERNE : généré selon la spécification PDF 1.4
     vectorielle avec les 14 polices Type 1 intégrées (Helvetica, Helvetica-Bold,
     Helvetica-Oblique). Rendu instantané, portable et lisible sur toute imprimante
     noir et blanc ou lecteur standard sans nécessiter de police externe.
  3. RESPECT DE LA PROCLAMATION : les résultats passés ici proviennent du
     serveur qui a déjà filtré les périodes proclamées pour le parent.
"""
import io
from datetime import date


def _escape_pdf(text):
    """Échappe une chaîne pour un littéral PDF (...) avec encodage WinAnsi/Latin-1."""
    if not text:
        return ""
    # Remplacement des caractères typographiques courants hors Latin-1
    t = str(text).replace("—", "-").replace("–", "-").replace("’", "'").replace("“", '"').replace("”", '"')
    out = []
    for ch in t.encode("latin-1", errors="replace").decode("latin-1"):
        if ch == "\\":
            out.append("\\\\")
        elif ch == "(":
            out.append("\\(")
        elif ch == ")":
            out.append("\\)")
        elif ord(ch) < 32 or ord(ch) > 126:
            out.append(f"\\{ord(ch):03o}")
        else:
            out.append(ch)
    return "".join(out)


def _mention_pour_note(cote_20):
    """Mention indicative pour une cote normalisée sur 20."""
    if cote_20 is None:
        return "—"
    try:
        val = float(cote_20)
    except (ValueError, TypeError):
        return "—"
    if val >= 18:
        return "Élite / Excellent"
    elif val >= 16:
        return "Très Bien"
    elif val >= 14:
        return "Bien"
    elif val >= 12:
        return "Satisfaction"
    elif val >= 10:
        return "Passable"
    elif val >= 8:
        return "Médiocre"
    return "Insuffisant"


class PDFDocument:
    """Moteur vectoriel léger produisant un document PDF 1.4 A4 standard."""

    PAGE_WIDTH = 595.28   # 210 mm en points (72 pt / pouce)
    PAGE_HEIGHT = 841.89  # 297 mm en points

    def __init__(self):
        self.pages = []  # Liste de listes de commandes (octets)

    def new_page(self):
        buf = io.BytesIO()
        self.pages.append(buf)
        return buf

    def render(self):
        """Compile l'ensemble des pages en octets PDF 1.4 valides avec table xref."""
        out = io.BytesIO()
        out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        
        total_pages = len(self.pages)
        if total_pages == 0:
            self.new_page()
            total_pages = 1

        offsets = {}
        page_obj_ids = []
        cur_id = 5
        page_info = []

        for p_buf in self.pages:
            p_obj_id = cur_id + 1
            c_obj_id = cur_id + 2
            cur_id += 2
            page_info.append((p_obj_id, c_obj_id, p_buf.getvalue()))
            page_obj_ids.append(p_obj_id)

        def write_obj(obj_id, data):
            offsets[obj_id] = out.tell()
            out.write(f"{obj_id} 0 obj\n".encode("ascii"))
            out.write(data)
            out.write(b"\nendobj\n")

        # 1: Catalogue racine
        write_obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")

        # 2: Arbre des pages
        kids_str = " ".join(f"{pid} 0 R" for pid in page_obj_ids)
        write_obj(2, f"<< /Type /Pages /Kids [{kids_str}] /Count {total_pages} /MediaBox [0 0 {self.PAGE_WIDTH} {self.PAGE_HEIGHT}] >>".encode("ascii"))

        # Polices standard 14 avec encodage WinAnsi (pour accents français parfaits)
        # 3: Helvetica Regular
        write_obj(3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        # 4: Helvetica Bold
        write_obj(4, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        # 5: Helvetica Oblique (Italic)
        write_obj(5, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique /Encoding /WinAnsiEncoding >>")

        # Pages et flux de contenu
        for p_obj_id, c_obj_id, raw_stream in page_info:
            page_dict = (
                f"<< /Type /Page /Parent 2 0 R "
                f"/Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> "
                f"/Contents {c_obj_id} 0 R >>"
            ).encode("ascii")
            write_obj(p_obj_id, page_dict)

            content_payload = b"q\n" + raw_stream + b"\nQ\n"
            c_dict = f"<< /Length {len(content_payload)} >>\nstream\n".encode("ascii") + content_payload + b"endstream"
            write_obj(c_obj_id, c_dict)

        # Table des références croisées (xref)
        xref_offset = out.tell()
        total_objs = cur_id
        out.write(f"xref\n0 {total_objs + 1}\n0000000000 65535 f \n".encode("ascii"))
        for i in range(1, total_objs + 1):
            offset = offsets.get(i, 0)
            out.write(f"{offset:010d} 00000 n \n".encode("ascii"))

        # Trailer
        out.write(f"trailer\n<< /Size {total_objs + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii"))
        return out.getvalue()


class PageDrawer:
    """Outil de dessin de primitives graphiques et textuelles pour une page."""

    def __init__(self, stream):
        self.stream = stream

    def _write(self, s):
        self.stream.write(s.encode("latin-1"))
        self.stream.write(b"\n")

    def stroke_color(self, gray_or_r, g=None, b=None):
        if g is None:
            self._write(f"{gray_or_r:.3f} G")
        else:
            self._write(f"{gray_or_r:.3f} {g:.3f} {b:.3f} RG")

    def fill_color(self, gray_or_r, g=None, b=None):
        if g is None:
            self._write(f"{gray_or_r:.3f} g")
        else:
            self._write(f"{gray_or_r:.3f} {g:.3f} {b:.3f} rg")

    def line_width(self, w):
        self._write(f"{w:.2f} w")

    def line(self, x1, y1, x2, y2):
        self._write(f"{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")

    def rect(self, x, y, w, h, fill=False, stroke=True):
        op = "B" if (fill and stroke) else ("f" if fill else "S")
        self._write(f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re {op}")

    def text(self, x, y, content, font="/F1", size=10, align="left", width=None):
        """Affiche un texte avec positionnement et alignement optionnel."""
        escaped = _escape_pdf(content)
        # Estimation approximative de largeur pour l'alignement
        char_w = size * 0.52 if font == "/F2" else size * 0.48
        text_w = len(content or "") * char_w
        pos_x = x
        if align == "center" and width is not None:
            pos_x = x + (width - text_w) / 2
        elif align == "right" and width is not None:
            pos_x = x + width - text_w
        self._write(f"BT {font} {size:.1f} Tf {pos_x:.2f} {y:.2f} Td ({escaped}) Tj ET")


def _draw_single_bulletin_page(drawer, tenant_name, school_year, class_name, titulaire_name, b, page_num=1, total_pages=1):
    """Dessine une page A4 complète de bulletin officiel pour un élève."""
    W = PDFDocument.PAGE_WIDTH
    H = PDFDocument.PAGE_HEIGHT
    M = 36.0  # Marge 36 pt (0.5 pouce)
    content_w = W - 2 * M

    # 1. Bordure extérieure d'encadrement officiel
    drawer.stroke_color(0.15)
    drawer.line_width(1.2)
    drawer.rect(M, M, content_w, H - 2 * M, fill=False, stroke=True)

    # Filet intérieur fin pour le cachet officiel
    drawer.stroke_color(0.65)
    drawer.line_width(0.5)
    drawer.rect(M + 3, M + 3, content_w - 6, H - 2 * M - 6, fill=False, stroke=True)

    y = H - M - 18

    # 2. En-tête national officiel EPST
    drawer.fill_color(0.1)
    drawer.text(M, y, "RÉPUBLIQUE DÉMOCRATIQUE DU CONGO", font="/F2", size=10, align="center", width=content_w)
    y -= 13
    drawer.text(M, y, "MINISTÈRE DE L'ENSEIGNEMENT PRIMAIRE, SECONDAIRE ET TECHNIQUE (EPST)", font="/F2", size=8.5, align="center", width=content_w)
    y -= 11
    drawer.text(M, y, "PROVINCE ÉDUCATIONNELLE DE KINSHASA", font="/F1", size=7.5, align="center", width=content_w)
    y -= 14

    # Ligne de séparation
    drawer.stroke_color(0.2)
    drawer.line_width(0.8)
    drawer.line(M + 12, y, W - M - 12, y)
    y -= 16

    # 3. Nom de l'établissement
    nom_etablissement = (tenant_name or "Établissement Scolaire").upper()
    drawer.text(M, y, nom_etablissement, font="/F2", size=14, align="center", width=content_w)
    y -= 14
    drawer.text(M, y, "BULLETIN OFFICIEL DE SCOLARITÉ ET DE CONDUITE", font="/F3", size=9, align="center", width=content_w)
    y -= 18

    # 4. Cartouche d'identification de l'élève et de la classe
    box_h = 56
    drawer.fill_color(0.96)
    drawer.stroke_color(0.3)
    drawer.line_width(0.6)
    drawer.rect(M + 8, y - box_h, content_w - 16, box_h, fill=True, stroke=True)

    # Informations élève (colonne gauche) et scolarité (colonne droite)
    student = b.get("student") or {}
    nom_complet = f"{student.get('last_name', '')} {student.get('first_name', '')}".strip() or "Élève"
    code_eleve = student.get("code") or student.get("id", "—")
    classe_libelle = class_name or student.get("class_name") or "—"
    periode_libelle = b.get("period") or "Période officielle"
    annee_libelle = school_year or date.today().strftime("%Y") + "-" + str(date.today().year + 1)
    titulaire_libelle = titulaire_name or "Non assigné"

    drawer.fill_color(0.1)
    # Ligne 1
    drawer.text(M + 16, y - 16, "Élève :", font="/F2", size=9)
    drawer.text(M + 56, y - 16, nom_complet.upper(), font="/F2", size=9.5)
    drawer.text(M + 280, y - 16, "Année scolaire :", font="/F2", size=9)
    drawer.text(M + 365, y - 16, annee_libelle, font="/F1", size=9)

    # Ligne 2
    drawer.text(M + 16, y - 32, "Matricule :", font="/F2", size=8.5)
    drawer.text(M + 72, y - 32, code_eleve, font="/F1", size=8.5)
    drawer.text(M + 280, y - 32, "Période :", font="/F2", size=8.5)
    drawer.text(M + 330, y - 32, periode_libelle, font="/F1", size=8.5)

    # Ligne 3
    drawer.text(M + 16, y - 48, "Classe :", font="/F2", size=8.5)
    drawer.text(M + 60, y - 48, classe_libelle, font="/F1", size=8.5)
    drawer.text(M + 280, y - 48, "Titulaire :", font="/F2", size=8.5)
    drawer.text(M + 335, y - 48, titulaire_libelle, font="/F1", size=8.5)

    y = y - box_h - 16

    # 5. Tableau des matières et résultats
    # Colonnes : Matière (200 pt) | Cote /20 (70 pt) | Pourcentage (75 pt) | Appréciation (content_w - 345 - 16 pt)
    col_x_mat = M + 8
    col_w_mat = 200.0
    col_x_cote = col_x_mat + col_w_mat
    col_w_cote = 70.0
    col_x_pct = col_x_cote + col_w_cote
    col_w_pct = 75.0
    col_x_app = col_x_pct + col_w_pct
    col_w_app = (content_w - 16) - (col_w_mat + col_w_cote + col_w_pct)

    header_h = 20.0
    drawer.fill_color(0.90)
    drawer.stroke_color(0.2)
    drawer.line_width(0.6)
    drawer.rect(col_x_mat, y - header_h, content_w - 16, header_h, fill=True, stroke=True)

    drawer.fill_color(0.1)
    drawer.text(col_x_mat + 6, y - 14, "DISCIPLINE / MATIÈRE", font="/F2", size=8)
    drawer.text(col_x_cote, y - 14, "COTE / 20", font="/F2", size=8, align="center", width=col_w_cote)
    drawer.text(col_x_pct, y - 14, "POURCENTAGE", font="/F2", size=8, align="center", width=col_w_pct)
    drawer.text(col_x_app + 8, y - 14, "APPRÉCIATION & MENTION", font="/F2", size=8)

    y -= header_h

    subjects = b.get("subjects") or []
    row_h = 17.0
    # Limiter le nombre de lignes affichables sur une seule page A4
    for idx, s in enumerate(subjects):
        bg = 0.98 if idx % 2 == 1 else 1.0
        drawer.fill_color(bg)
        drawer.stroke_color(0.8)
        drawer.line_width(0.4)
        drawer.rect(col_x_mat, y - row_h, content_w - 16, row_h, fill=True, stroke=True)

        matiere = s.get("subject", "Matière")
        cote = s.get("average_20")
        cote_txt = f"{cote:.2f}" if cote is not None else "—"
        pct_txt = f"{round(cote / 20 * 100, 1):.1f} %" if cote is not None else "—"
        mention = _mention_pour_note(cote)

        drawer.fill_color(0.1)
        drawer.text(col_x_mat + 6, y - 12, matiere, font="/F1", size=8)
        drawer.text(col_x_cote, y - 12, cote_txt, font="/F2", size=8.5, align="center", width=col_w_cote)
        drawer.text(col_x_pct, y - 12, pct_txt, font="/F1", size=8, align="center", width=col_w_pct)
        drawer.text(col_x_app + 8, y - 12, mention, font="/F3", size=7.5)

        y -= row_h

    if not subjects:
        drawer.fill_color(1.0)
        drawer.stroke_color(0.8)
        drawer.rect(col_x_mat, y - row_h, content_w - 16, row_h, fill=True, stroke=True)
        drawer.fill_color(0.4)
        drawer.text(col_x_mat, y - 12, "Aucune note enregistrée pour cette période.", font="/F3", size=8, align="center", width=content_w - 16)
        y -= row_h

    # 6. Synthèse des résultats (Moyenne générale, pourcentage, rang)
    sum_h = 24.0
    drawer.fill_color(0.92)
    drawer.stroke_color(0.2)
    drawer.line_width(0.8)
    drawer.rect(col_x_mat, y - sum_h, content_w - 16, sum_h, fill=True, stroke=True)

    gen_avg = b.get("general_average_20")
    gen_pct = b.get("percent")
    rank = b.get("rank")
    class_size = b.get("class_size")

    avg_txt = f"{gen_avg:.2f} / 20" if gen_avg is not None else "—"
    pct_txt = f"{gen_pct:.1f} %" if gen_pct is not None else "—"
    if rank is not None and class_size:
        suffix = "er" if rank == 1 else "e"
        rank_txt = f"{rank}{suffix} sur {class_size}"
    elif rank is not None:
        suffix = "er" if rank == 1 else "e"
        rank_txt = f"{rank}{suffix}"
    else:
        rank_txt = "—"

    drawer.fill_color(0.05)
    drawer.text(col_x_mat + 6, y - 15, "RÉSULTAT GLOBAL :", font="/F2", size=8.5)
    drawer.text(col_x_mat + 115, y - 15, f"Moyenne : {avg_txt}", font="/F2", size=8.5)
    drawer.text(col_x_mat + 235, y - 15, f"Pourcentage : {pct_txt}", font="/F2", size=8.5)
    drawer.text(col_x_mat + 365, y - 15, f"Rang : {rank_txt}", font="/F2", size=9)

    y = y - sum_h - 14

    # 7. Conduite & Discipline
    cond_h = 36.0
    drawer.fill_color(0.98)
    drawer.stroke_color(0.3)
    drawer.line_width(0.5)
    drawer.rect(M + 8, y - cond_h, content_w - 16, cond_h, fill=True, stroke=True)

    conduct = b.get("conduct") or {}
    cote_conduite = conduct.get("label") or "Conduite satisfaisante"
    obs_conduite = conduct.get("note") or (
        f"Capital points restant : {conduct.get('remaining', 100)} / {conduct.get('capital', 100)}"
        if conduct.get("capital") else "Observation de discipline conforme au règlement intérieur."
    )

    drawer.fill_color(0.1)
    drawer.text(M + 16, y - 14, "CONDUITE & DISCIPLINE :", font="/F2", size=8.5)
    drawer.text(M + 145, y - 14, cote_conduite.upper(), font="/F2", size=8.5)
    drawer.text(M + 16, y - 27, f"Observations : {obs_conduite}", font="/F3", size=7.5)

    y = y - cond_h - 12

    # 8. Décision du conseil (si disponible)
    decision = b.get("decision")
    if decision:
        dec_h = 34.0
        drawer.fill_color(0.95)
        drawer.stroke_color(0.2)
        drawer.line_width(0.7)
        drawer.rect(M + 8, y - dec_h, content_w - 16, dec_h, fill=True, stroke=True)

        dec_titre = decision.get("decision", "").upper()
        dec_mention = decision.get("mention") or ""
        dec_note = decision.get("note") or ""

        dec_full = f"DÉCISION DU CONSEIL : {dec_titre}"
        if dec_mention:
            dec_full += f"  ·  Mention : {dec_mention}"

        drawer.fill_color(0.05)
        drawer.text(M + 16, y - 14, dec_full, font="/F2", size=8.5)
        if dec_note:
            drawer.text(M + 16, y - 26, f"Motif / Note du conseil : {dec_note}", font="/F3", size=7.5)

        y = y - dec_h - 12

    # 9. Cadres des visas et signatures officiels
    sign_h = 60.0
    sign_w = (content_w - 32) / 2
    sign_y = M + 24

    # Cadre gauche : Titulaire de classe
    drawer.fill_color(1.0)
    drawer.stroke_color(0.4)
    drawer.line_width(0.5)
    drawer.rect(M + 8, sign_y, sign_w, sign_h, fill=True, stroke=True)
    drawer.fill_color(0.1)
    drawer.text(M + 16, sign_y + sign_h - 14, "Le Titulaire de Classe", font="/F2", size=8)
    drawer.text(M + 16, sign_y + sign_h - 25, "(Visa & signature)", font="/F3", size=7)

    # Cadre droit : Chef d'établissement
    drawer.fill_color(1.0)
    drawer.stroke_color(0.4)
    drawer.line_width(0.5)
    right_box_x = W - M - 8 - sign_w
    drawer.rect(right_box_x, sign_y, sign_w, sign_h, fill=True, stroke=True)
    drawer.fill_color(0.1)
    drawer.text(right_box_x + 8, sign_y + sign_h - 14, "Le Chef d'Établissement", font="/F2", size=8)
    drawer.text(right_box_x + 8, sign_y + sign_h - 25, "(Sceau de l'école & signature)", font="/F3", size=7)

    # Date de délivrance
    date_str = date.today().strftime("%d/%m/%Y")
    drawer.text(right_box_x + 8, sign_y + 8, f"Délivré le {date_str}", font="/F1", size=7)

    # 10. Pied de page légal et pagination
    drawer.fill_color(0.4)
    drawer.text(M + 8, M + 8, "Document officiel généré par Klassio — Système certifié de gestion scolaire", font="/F3", size=6.5)
    if total_pages > 1:
        drawer.text(W - M - 70, M + 8, f"Page {page_num} / {total_pages}", font="/F1", size=6.5)


def generate_student_bulletin_pdf(tenant_name, school_year, class_name, titulaire_name, bulletin_data):
    """Génère le bulletin d'un seul élève en PDF (1 page A4)."""
    doc = PDFDocument()
    stream = doc.new_page()
    drawer = PageDrawer(stream)
    _draw_single_bulletin_page(
        drawer, tenant_name, school_year, class_name, titulaire_name,
        bulletin_data, page_num=1, total_pages=1
    )
    return doc.render()


def generate_class_bulletins_pdf(tenant_name, school_year, class_name, titulaire_name, bulletins_list):
    """Génère l'ensemble des bulletins d'une classe en un seul document PDF multipages (1 page par élève)."""
    doc = PDFDocument()
    total = max(1, len(bulletins_list))
    if not bulletins_list:
        # Page de garde / classe vide
        stream = doc.new_page()
        drawer = PageDrawer(stream)
        _draw_single_bulletin_page(
            drawer, tenant_name, school_year, class_name, titulaire_name,
            {"student": {"first_name": "Aucun", "last_name": "Élève actif"}, "period": "—", "subjects": []},
            page_num=1, total_pages=1
        )
    else:
        for idx, b in enumerate(bulletins_list, start=1):
            stream = doc.new_page()
            drawer = PageDrawer(stream)
            _draw_single_bulletin_page(
                drawer, tenant_name, school_year, class_name, titulaire_name,
                b, page_num=idx, total_pages=total
            )
    return doc.render()
