"""KLASSIO — le logo de l'école sur ses bulletins PDF (08/10/2026).

Le propriétaire : « pour les reçus ou autres documents qui sortiront du
logiciel, il faudra le logo de l'école ». Un logo JPEG s'incorpore dans le
PDF ; un logo absent ou d'un autre format laisse un bulletin valide, sans
logo — jamais un bulletin cassé.
"""
import base64
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pdf_bulletin  # noqa: E402

# En-tête JPEG minimal : SOI + SOF0 (8 bits, 3×2 px, 3 composantes) + EOI.
JPEG = bytes.fromhex("FFD8" "FFC0001108000200030301220002110103110100" "FFD9")
LOGO = "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()
BULLETIN = {"student": {"first_name": "Grace", "last_name": "Mbuyi"}, "period": "P1", "subjects": []}


class BulletinLogoTests(unittest.TestCase):

    def test_01_le_logo_jpeg_est_lu(self):
        raw, w, h, comps = pdf_bulletin.logo_jpeg(LOGO)
        self.assertEqual((w, h, comps), (3, 2, 3))

    def test_02_le_bulletin_porte_le_logo(self):
        pdf = pdf_bulletin.generate_student_bulletin_pdf("École", "2026-2027", "6e A", None, BULLETIN, logo=LOGO)
        self.assertIn(b"/DCTDecode", pdf)
        self.assertIn(b"/Im1 Do", pdf)
        self.assertTrue(pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF"))

    def test_03_sans_logo_ou_png_le_bulletin_reste_valide(self):
        for logo in (None, "data:image/png;base64,iVBORw0KGgo=", "data:image/jpeg;base64,!!!"):
            pdf = pdf_bulletin.generate_class_bulletins_pdf("École", "2026-2027", "6e A", None, [BULLETIN], logo=logo)
            self.assertNotIn(b"/Im1", pdf)
            self.assertTrue(pdf.rstrip().endswith(b"%%EOF"))


if __name__ == "__main__":
    unittest.main()
