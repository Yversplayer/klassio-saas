// KLASSIO — jeu de données FICTIF pour la démonstration publique (/demo.html).
// Aucune de ces valeurs ne provient d'un établissement réel et rien ici
// n'est jamais écrit dans une base de données : c'est un objet JS statique,
// affiché tel quel, identique sur tous les écrans de la démo pour rester
// cohérent (docs point 23 du brief démo).
window.KlassioDemoData = {
  establishment: {
    name: "Collège Horizon",
    academicYear: "2026–2027",
    studentCount: 2340,
    classCount: 42,
    teacherCount: 86,
    guardianCount: 1870,
    feeCategoryCount: 6,
    paymentCount: 1925,
    qualityScore: 92,
  },

  // Fichier Excel fictif présenté à l'étape "Import"
  importPreviewRows: [
    { student: "Kabeya Jean", class: "4e A", guardian: "Paul Kabeya", fee: 450, paid: 300 },
    { student: "Mbuyi Sarah", class: "4e B", guardian: "Marie Mbuyi", fee: 450, paid: 450 },
    { student: "Ilunga David", class: "3e A", guardian: "Chantal Ilunga", fee: 400, paid: 200 },
    { student: "Tshisekedi Grace", class: "5e A", guardian: "Robert Tshisekedi", fee: 400, paid: 0 },
    { student: "Kanku Michel", class: "6e A", guardian: "Sophie Kanku", fee: 350, paid: 350 },
  ],
  importAnomalies: [
    "18 élèves sans classe assignée",
    "7 doublons potentiels détectés",
    "12 numéros de téléphone invalides",
  ],
  importQualityReasons: {
    good: ["Structure du fichier reconnue", "Colonnes principales identifiées", "Relations élèves/classes/parents cohérentes"],
    warn: ["Quelques données nécessitent une vérification manuelle"],
  },
  columnMapping: [
    { source: "Nom élève", target: "Élève" },
    { source: "Classe", target: "Classe" },
    { source: "Responsable", target: "Parent / Responsable" },
    { source: "Montant dû", target: "Obligation" },
    { source: "Montant versé", target: "Paiement" },
  ],

  finance: {
    totalExpected: 1053000,
    totalCollected: 874500,
    outstanding: 178500,
  },

  samplePayment: {
    student: "Jean Kabeya",
    className: "4e Scientifique A",
    amount: 300,
    method: "Mobile Money",
    status: "Confirmé",
  },

  director: { name: "Jean" },

  // Élèves affichés dans l'écran "Élèves & Classes" — jeu réduit mais cohérent
  // avec les totaux ci-dessus (mêmes noms, mêmes montants que partout ailleurs).
  // Chaque élève porte de quoi remplir TOUS les onglets de son dossier, comme
  // dans le vrai produit : identité, présence, discipline, résultats,
  // obligations, reçus. Rien ici n'est écrit nulle part — c'est un objet JS.
  students: [
    { name: "Kabeya Jean", className: "4e Scientifique A", guardian: "Paul Kabeya", fee: 450, paid: 300,
      code: "STU-2027-0148", sex: "Garçon", birth: "14 mars 2011", conduct: 92,
      present: 61, absent: 3, late: 2,
      incidents: [{ date: "08 janv. 2027", label: "Retard répété", impact: -8 }],
      grades: [{ period: "Période 1", subject: "Mathématiques", value: "14,5 / 20", published: true },
               { period: "Période 1", subject: "Français", value: "13,0 / 20", published: true },
               { period: "Période 2", subject: "Mathématiques", value: "15,0 / 20", published: false }],
      obligations: [{ label: "Frais de scolarité — Trimestre 1", due: 450, paid: 300, deadline: "31 oct. 2026" }],
      receipts: [{ number: "REC-2027-00412", label: "Frais de scolarité — Trimestre 1", method: "Espèces", date: "12 oct. 2026", amount: 300 }] },

    { name: "Mbuyi Sarah", className: "4e Scientifique B", guardian: "Marie Mbuyi", fee: 450, paid: 450,
      code: "STU-2027-0149", sex: "Fille", birth: "02 sept. 2011", conduct: 100,
      present: 64, absent: 1, late: 0, incidents: [],
      grades: [{ period: "Période 1", subject: "Mathématiques", value: "16,0 / 20", published: true },
               { period: "Période 1", subject: "Français", value: "15,5 / 20", published: true }],
      obligations: [{ label: "Frais de scolarité — Trimestre 1", due: 450, paid: 450, deadline: "31 oct. 2026" }],
      receipts: [{ number: "REC-2027-00287", label: "Frais de scolarité — Trimestre 1", method: "Banque", date: "03 oct. 2026", amount: 450 }] },

    { name: "Ilunga David", className: "3e A", guardian: "Chantal Ilunga", fee: 400, paid: 200,
      code: "STU-2027-0150", sex: "Garçon", birth: "27 juin 2012", conduct: 85,
      present: 58, absent: 6, late: 4,
      incidents: [{ date: "15 déc. 2026", label: "Absence non justifiée", impact: -10 },
                  { date: "09 janv. 2027", label: "Retard", impact: -5 }],
      grades: [{ period: "Période 1", subject: "Mathématiques", value: "11,0 / 20", published: true }],
      obligations: [{ label: "Frais de scolarité — Trimestre 1", due: 400, paid: 200, deadline: "31 oct. 2026" }],
      receipts: [{ number: "REC-2027-00301", label: "Frais de scolarité — Trimestre 1", method: "Espèces", date: "07 oct. 2026", amount: 200 }] },

    { name: "Tshisekedi Grace", className: "5e A", guardian: "Robert Tshisekedi", fee: 400, paid: 0,
      code: "STU-2027-0151", sex: "Fille", birth: "11 févr. 2013", conduct: 100,
      present: 63, absent: 2, late: 1, incidents: [],
      grades: [{ period: "Période 1", subject: "Français", value: "14,0 / 20", published: true }],
      obligations: [{ label: "Frais de scolarité — Trimestre 1", due: 400, paid: 0, deadline: "31 oct. 2026" }],
      receipts: [] },

    { name: "Kanku Michel", className: "6e A", guardian: "Sophie Kanku", fee: 350, paid: 350,
      code: "STU-2027-0152", sex: "Garçon", birth: "30 août 2013", conduct: 96,
      present: 65, absent: 0, late: 1, incidents: [],
      grades: [{ period: "Période 1", subject: "Éveil", value: "17,0 / 20", published: true }],
      obligations: [{ label: "Frais de scolarité — Trimestre 1", due: 350, paid: 350, deadline: "31 oct. 2026" }],
      receipts: [{ number: "REC-2027-00198", label: "Frais de scolarité — Trimestre 1", method: "Espèces", date: "29 sept. 2026", amount: 350 }] },

    { name: "Mukendi Aline", className: "4e Scientifique A", guardian: "Joseph Mukendi", fee: 450, paid: 450,
      code: "STU-2027-0153", sex: "Fille", birth: "19 avr. 2011", conduct: 100,
      present: 66, absent: 0, late: 0, incidents: [],
      grades: [{ period: "Période 1", subject: "Mathématiques", value: "18,0 / 20", published: true },
               { period: "Période 1", subject: "Français", value: "16,5 / 20", published: true }],
      obligations: [{ label: "Frais de scolarité — Trimestre 1", due: 450, paid: 450, deadline: "31 oct. 2026" }],
      receipts: [{ number: "REC-2027-00155", label: "Frais de scolarité — Trimestre 1", method: "Banque", date: "24 sept. 2026", amount: 450 }] },

    { name: "Bakena Patrick", className: "2e Primaire B", guardian: "Elise Bakena", fee: 300, paid: 150,
      code: "STU-2027-0154", sex: "Garçon", birth: "05 nov. 2017", conduct: 90,
      present: 60, absent: 4, late: 2,
      incidents: [{ date: "20 nov. 2026", label: "Matériel oublié — 3e fois", impact: -10 }],
      grades: [{ period: "Période 1", subject: "Lecture", value: "13,5 / 20", published: true }],
      obligations: [{ label: "Frais de scolarité — Trimestre 1", due: 300, paid: 150, deadline: "31 oct. 2026" }],
      receipts: [{ number: "REC-2027-00366", label: "Frais de scolarité — Trimestre 1", method: "Espèces", date: "10 oct. 2026", amount: 150 }] },

    { name: "Longandjo Esther", className: "1re Secondaire A", guardian: "Pierre Longandjo", fee: 420, paid: 420,
      code: "STU-2027-0155", sex: "Fille", birth: "23 janv. 2014", conduct: 100,
      present: 66, absent: 0, late: 0, incidents: [],
      grades: [{ period: "Période 1", subject: "Mathématiques", value: "15,0 / 20", published: true }],
      obligations: [{ label: "Frais de scolarité — Trimestre 1", due: 420, paid: 420, deadline: "31 oct. 2026" }],
      receipts: [{ number: "REC-2027-00104", label: "Frais de scolarité — Trimestre 1", method: "Banque", date: "18 sept. 2026", amount: 420 }] },
  ],

  // Notifications telles que le produit les fabrique : une audience par
  // événement, et un regroupement côté direction pour ne pas la noyer.
  notifications: [
    { icon: "🧾", title: "Paiement enregistré", body: "Kabeya Jean — 300 $ en espèces. Reçu REC-2027-00412.", when: "il y a 12 min", audience: "Direction + parent" },
    { icon: "📣", title: "Période 1 proclamée", body: "4e Scientifique A — 58 élèves. Les responsables peuvent consulter les résultats.", when: "il y a 2 h", audience: "Parents concernés" },
    { icon: "🛡️", title: "Seuil de conduite atteint", body: "Ilunga David — 85/100 après un 2e incident. Convocation proposée.", when: "hier", audience: "Direction + discipline" },
    { icon: "✓", title: "Appel incomplet", body: "4 classes sur 42 n'ont pas fait l'appel avant 10 h.", when: "hier", audience: "Discipline" },
  ],
  classes: [
    { name: "4e Scientifique A", level: "4e", studentCount: 58 },
    { name: "4e Scientifique B", level: "4e", studentCount: 56 },
    { name: "3e A", level: "3e", studentCount: 60 },
    { name: "5e A", level: "5e", studentCount: 54 },
    { name: "6e A", level: "6e", studentCount: 57 },
    { name: "2e Primaire B", level: "2e Primaire", studentCount: 49 },
    { name: "1re Secondaire A", level: "1re Secondaire", studentCount: 52 },
  ],

  // Trois responsables démo pour l'étape "Les 3 espaces" (vue Parent)
  parentDemo: {
    name: "Paul",
    children: [
      { name: "Jean Kabeya", className: "4e Scientifique A", fee: 450, paid: 300 },
      { name: "Nadège Kabeya", className: "2e Primaire A", fee: 300, paid: 300 },
    ],
  },
  teacherDemo: {
    name: "Grâce",
    className: "4e Scientifique A",
    studentCount: 58,
    present: 55,
    absent: 2,
    late: 1,
  },
};
