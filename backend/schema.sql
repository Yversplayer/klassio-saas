-- KLASSIO — schéma de base de données (SQLite)
-- Reflète docs/FINANCE.md §22, docs/MULTI_TENANT.md §10, docs/SECURITE.md §6-8, docs/EVENEMENTS.md §22
--
-- Principe non négociable : tenant_id sur chaque table métier, jamais fourni par le
-- client — voir backend/security.py pour l'application réelle de cette règle.

PRAGMA foreign_keys = ON;

-- Identité globale (docs/MULTI_TENANT.md §10.3 : User est global, ses memberships sont tenant-scoped)
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tenants (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL
);

-- docs/MULTI_TENANT.md §7.1 : un utilisateur peut avoir plusieurs memberships (multi-écoles)
CREATE TABLE IF NOT EXISTS memberships (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  role TEXT NOT NULL, -- directeur | professeur | parent | eleve
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  UNIQUE(user_id, tenant_id)
);

CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  tenant_id TEXT NOT NULL REFERENCES tenants(id), -- tenant actif de la session (docs/MULTI_TENANT.md §7)
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS academic_years (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  label TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1,
  -- ACTIVE | PREPARATION | ARCHIVED. `is_active` disait « c'est celle-ci » ;
  -- il ne distinguait pas une année qu'on PRÉPARE d'une année CLOSE.
  -- ARCHIVED ne veut jamais dire supprimée : l'historique reste consultable.
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS classes (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  academic_year_id TEXT NOT NULL REFERENCES academic_years(id),
  name TEXT NOT NULL,
  level TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS students (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  academic_year_id TEXT NOT NULL REFERENCES academic_years(id),
  class_id TEXT REFERENCES classes(id),
  first_name TEXT NOT NULL,
  last_name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active', -- active | archived | transferred
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS guardians (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  first_name TEXT NOT NULL,
  last_name TEXT NOT NULL,
  phone TEXT,
  email TEXT,
  user_id TEXT REFERENCES users(id), -- lien vers un compte parent si connecté (peut être NULL)
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS student_guardians (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  student_id TEXT NOT NULL REFERENCES students(id),
  guardian_id TEXT NOT NULL REFERENCES guardians(id),
  relationship TEXT,
  UNIQUE(student_id, guardian_id)
);

-- Catalogue financier (docs/FINANCE.md §15)
CREATE TABLE IF NOT EXISTS catalog_items (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  amount REAL NOT NULL,
  currency TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- Obligation financière (docs/FINANCE.md §6) — jamais un chiffre brut : le solde se
-- calcule toujours à partir des paiements liés, jamais stocké ici.
CREATE TABLE IF NOT EXISTS obligations (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  student_id TEXT NOT NULL REFERENCES students(id),
  academic_year_id TEXT NOT NULL REFERENCES academic_years(id),
  catalog_item_id TEXT NOT NULL REFERENCES catalog_items(id),
  amount REAL NOT NULL,
  currency TEXT NOT NULL,
  due_date TEXT,
  status TEXT NOT NULL DEFAULT 'ISSUED', -- calculé aussi via l'API, ce champ est un cache dérivé
  created_at TEXT NOT NULL
);

-- Paiement (docs/FINANCE.md §7) — états explicites, idempotency_key obligatoire.
CREATE TABLE IF NOT EXISTS payments (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  obligation_id TEXT NOT NULL REFERENCES obligations(id),
  amount REAL NOT NULL,
  currency TEXT NOT NULL,
  method TEXT NOT NULL, -- cash | mobile_money | bank | card
  status TEXT NOT NULL DEFAULT 'CREATED', -- CREATED|PENDING|PROCESSING|CONFIRMED|FAILED|CANCELLED|EXPIRED|UNKNOWN|REFUNDED|REVERSED
  idempotency_key TEXT NOT NULL,
  provider_reference TEXT,
  created_by TEXT REFERENCES users(id),
  created_at TEXT NOT NULL,
  confirmed_at TEXT,
  -- Trouvé par pentest : une contrainte UNIQUE globale sur idempotency_key permettait
  -- à une école de faire planter (500) une opération d'une autre école en réutilisant
  -- la même clé — violation de l'isolation multi-tenant (docs/MULTI_TENANT.md §10.4).
  -- L'unicité doit être scopée par tenant, jamais globale.
  UNIQUE(tenant_id, idempotency_key)
);

-- Journal financier (docs/FINANCE.md §5) — chaque mouvement, jamais modifié après coup.
CREATE TABLE IF NOT EXISTS ledger_entries (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  entry_type TEXT NOT NULL, -- payment_confirmed | refund | adjustment
  reference_type TEXT NOT NULL, -- payment | obligation
  reference_id TEXT NOT NULL,
  amount REAL NOT NULL,
  currency TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- Événements (docs/EVENEMENTS.md §6.1) — journal append-only des faits.
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  event_type TEXT NOT NULL,
  entity_type TEXT,
  entity_id TEXT,
  actor_id TEXT,
  correlation_id TEXT,
  payload TEXT NOT NULL, -- JSON
  created_at TEXT NOT NULL
);

-- Notifications (docs/EVENEMENTS.md §17.7)
CREATE TABLE IF NOT EXISTS notifications (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  recipient_user_id TEXT NOT NULL REFERENCES users(id),
  event_id TEXT REFERENCES events(id),
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  priority TEXT NOT NULL DEFAULT 'NORMAL',
  status TEXT NOT NULL DEFAULT 'unread', -- unread | read
  -- Trouvé par simulation grandeur nature (docs/RAPPORT_SIMULATION.md) : sans ces
  -- colonnes, chaque paiement confirmé crée une notification séparée pour le
  -- directeur (2530 notifications mesurées pour une seule vague de paiements).
  -- Elles permettent de regrouper plusieurs événements en une notification qui
  -- s'incrémente, cohérent avec docs/EVENEMENTS.md §17.5.
  count INTEGER NOT NULL DEFAULT 1,
  amount_total REAL,
  updated_at TEXT,
  created_at TEXT NOT NULL
);

-- Invitations (refonte onboarding/rôles) — un parent ou un professeur ne crée jamais
-- librement son compte : seul le directeur invite, le rôle vient de l'invitation,
-- jamais d'un choix client. Le token brut n'est JAMAIS stocké, seul son hash l'est
-- (même principe que les mots de passe) — un accès en lecture à la base ne suffit
-- pas à usurper une invitation.
CREATE TABLE IF NOT EXISTS invitations (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  role TEXT NOT NULL, -- professeur | parent
  token_hash TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'pending', -- pending | accepted | revoked | expired
  label TEXT, -- ex. nom du destinataire prévu, informatif seulement, jamais une preuve d'identité
  created_by TEXT NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  accepted_at TEXT,
  accepted_user_id TEXT REFERENCES users(id)
);

-- Élèves couverts par une invitation "parent" — décidé par le directeur à la création
-- de l'invitation, jamais choisi par la personne qui l'accepte (docs point 15/16).
CREATE TABLE IF NOT EXISTS invitation_students (
  invitation_id TEXT NOT NULL REFERENCES invitations(id),
  student_id TEXT NOT NULL REFERENCES students(id),
  PRIMARY KEY (invitation_id, student_id)
);

-- Assistant IA (lecture seule) — historique de conversation, strictement isolé
-- par utilisateur ET par établissement (docs point 20). L'IA elle-même n'a
-- accès à aucune table d'écriture : voir backend/ai_assistant.py, dont le seul
-- catalogue d'outils exposé est un ensemble de fonctions get_*/search_* qui
-- relisent les mêmes tables que le reste du produit, jamais un accès direct.
CREATE TABLE IF NOT EXISTS ai_conversations (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  user_id TEXT NOT NULL REFERENCES users(id),
  title TEXT NOT NULL DEFAULT 'Nouvelle conversation',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES ai_conversations(id),
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  role TEXT NOT NULL, -- user | assistant
  content TEXT NOT NULL,
  rich_json TEXT,
  intent TEXT,
  created_at TEXT NOT NULL
);

-- Audit (docs/SECURITE.md §11) — immuable, jamais supprimable par un utilisateur normal.
CREATE TABLE IF NOT EXISTS audit_logs (
  id TEXT PRIMARY KEY,
  tenant_id TEXT,
  actor_id TEXT,
  action TEXT NOT NULL,
  resource_type TEXT,
  resource_id TEXT,
  status TEXT NOT NULL, -- success | denied
  before_json TEXT,
  after_json TEXT,
  created_at TEXT NOT NULL
);

-- ===========================================================================
-- L'ÉLÈVE AU CENTRE — dossier central et domaines rattachés.
-- Chaque table ci-dessous se rattache à students(id) et porte tenant_id ;
-- les espaces Direction / DD / Professeur / Parent lisent TOUTES les mêmes
-- lignes, filtrées par les règles de backend/school.py — jamais dupliquées.
-- ===========================================================================

-- Rattachement professeur ↔ classe. Un professeur n'est JAMAIS titulaire
-- implicitement : is_titulaire est une décision explicite de la Direction.
CREATE TABLE IF NOT EXISTS class_teachers (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  class_id TEXT NOT NULL REFERENCES classes(id),
  user_id TEXT NOT NULL REFERENCES users(id),
  subject TEXT,
  is_titulaire INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  UNIQUE(class_id, user_id)
);

-- Classes pré-affectées à une invitation "professeur" — décidées par la
-- Direction à la création du lien, jamais par la personne qui l'accepte.
CREATE TABLE IF NOT EXISTS invitation_classes (
  invitation_id TEXT NOT NULL REFERENCES invitations(id),
  class_id TEXT NOT NULL REFERENCES classes(id),
  is_titulaire INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (invitation_id, class_id)
);

-- Présence : UNE donnée centrale par élève et par jour (jamais un système
-- par espace). Statut : present | late | absent | excused.
CREATE TABLE IF NOT EXISTS attendance (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  student_id TEXT NOT NULL REFERENCES students(id),
  class_id TEXT REFERENCES classes(id),
  date TEXT NOT NULL, -- AAAA-MM-JJ
  status TEXT NOT NULL,
  note TEXT,
  recorded_by TEXT REFERENCES users(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(tenant_id, student_id, date)
);

-- Règles disciplinaires configurées par la Direction (points positifs ou
-- négatifs). L'IA ne crée jamais de règle ni d'incident (voir ai_assistant.py).
CREATE TABLE IF NOT EXISTS discipline_rules (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  label TEXT NOT NULL,
  category TEXT NOT NULL, -- retard | absence | comportement | bonus | autre
  points INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

-- Incident disciplinaire — enregistré par un humain (DD ou Direction).
-- `internal_note` est réservée DD/Direction ; `action_taken` est la
-- conséquence communicable (titulaire, parent si notify_parent=1).
CREATE TABLE IF NOT EXISTS incidents (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  student_id TEXT NOT NULL REFERENCES students(id),
  class_id TEXT REFERENCES classes(id),
  rule_id TEXT REFERENCES discipline_rules(id),
  category TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  severity TEXT NOT NULL DEFAULT 'medium', -- low | medium | high
  points INTEGER NOT NULL DEFAULT 0,
  action_taken TEXT,
  internal_note TEXT,
  notify_parent INTEGER NOT NULL DEFAULT 0,
  occurred_at TEXT NOT NULL,
  recorded_by TEXT REFERENCES users(id),
  created_at TEXT NOT NULL
);

-- Résultats scolaires (une ligne = une note). Le bulletin est CALCULÉ à
-- partir de ces lignes, jamais stocké comme document figé.
CREATE TABLE IF NOT EXISTS grades (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  student_id TEXT NOT NULL REFERENCES students(id),
  class_id TEXT REFERENCES classes(id),
  subject TEXT NOT NULL,
  period TEXT NOT NULL, -- ex. "Période 1", "Trimestre 2"
  score REAL NOT NULL,
  max_score REAL NOT NULL DEFAULT 20,
  comment TEXT,
  recorded_by TEXT REFERENCES users(id),
  created_at TEXT NOT NULL
);

-- Emploi du temps : rattaché à la CLASSE (Élève → Classe → Horaire).
CREATE TABLE IF NOT EXISTS schedule_slots (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  class_id TEXT NOT NULL REFERENCES classes(id),
  weekday INTEGER NOT NULL, -- 1 = lundi … 7 = dimanche
  start_time TEXT NOT NULL,
  end_time TEXT NOT NULL,
  subject TEXT NOT NULL,
  teacher_user_id TEXT REFERENCES users(id),
  room TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exams (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  class_id TEXT NOT NULL REFERENCES classes(id),
  subject TEXT NOT NULL,
  date TEXT NOT NULL,
  start_time TEXT,
  room TEXT,
  exam_type TEXT NOT NULL DEFAULT 'Évaluation',
  notes TEXT,
  created_at TEXT NOT NULL
);

-- Boutique scolaire : catalogue de produits vendus par l'établissement.
CREATE TABLE IF NOT EXISTS store_products (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  name TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'fournitures',
  price REAL NOT NULL,
  currency TEXT NOT NULL,
  stock INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

-- Commande = rattachée à l'élève ET au Financial Core (obligation_id) :
-- pas de second système financier pour la boutique.
CREATE TABLE IF NOT EXISTS orders (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  number TEXT NOT NULL,
  student_id TEXT NOT NULL REFERENCES students(id),
  parent_user_id TEXT NOT NULL REFERENCES users(id),
  status TEXT NOT NULL DEFAULT 'pending', -- pending | paid | delivered | cancelled
  total REAL NOT NULL,
  currency TEXT NOT NULL,
  obligation_id TEXT REFERENCES obligations(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(tenant_id, number)
);

CREATE TABLE IF NOT EXISTS order_items (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  order_id TEXT NOT NULL REFERENCES orders(id),
  product_id TEXT NOT NULL REFERENCES store_products(id),
  name TEXT NOT NULL,
  quantity INTEGER NOT NULL,
  unit_price REAL NOT NULL
);

-- Reçu numérique : généré UNIQUEMENT à la confirmation réelle d'un paiement
-- (financial.confirm_payment), numéroté par établissement et par année.
-- Demandes envoyées depuis le formulaire public de contact. Aucune donnée
-- d'établissement : ce sont des messages de gens qui n'ont pas encore de
-- compte, ou qui ne peuvent plus y accéder. Lues par l'administration Klassio.
CREATE TABLE IF NOT EXISTS contact_requests (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT NOT NULL,
  subject TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'question', -- question | probleme | suggestion | commercial
  school TEXT,
  message TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'new',    -- new | handled
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS receipts (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  number TEXT NOT NULL,
  payment_id TEXT NOT NULL REFERENCES payments(id),
  student_id TEXT NOT NULL REFERENCES students(id),
  amount REAL NOT NULL,
  currency TEXT NOT NULL,
  method TEXT NOT NULL,
  label TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(tenant_id, number),
  UNIQUE(payment_id)
);

-- Réglages d'établissement — la visibilité financière des professeurs est
-- une PERMISSION contrôlée ici par la Direction, vérifiée côté serveur.
CREATE TABLE IF NOT EXISTS tenant_settings (
  tenant_id TEXT PRIMARY KEY REFERENCES tenants(id),
  currency TEXT NOT NULL DEFAULT 'USD',
  teacher_sees_finance INTEGER NOT NULL DEFAULT 0,
  parent_notify_attendance INTEGER NOT NULL DEFAULT 1,
  parent_notify_incidents INTEGER NOT NULL DEFAULT 0,
  parent_notify_grades INTEGER NOT NULL DEFAULT 1,
  discipline_alert_threshold INTEGER NOT NULL DEFAULT -10,
  school_phone TEXT,
  school_address TEXT,
  school_email TEXT,
  updated_at TEXT
);

-- Lien de réinitialisation de mot de passe — généré UNIQUEMENT par la
-- Direction de l'établissement pour un membre de son équipe ou un parent
-- (aucun canal email/SMS n'est branché : le lien part sur WhatsApp comme
-- l'invitation). Hash seul stocké, usage unique, 24 h, révoque les sessions.
CREATE TABLE IF NOT EXISTS password_resets (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  user_id TEXT NOT NULL REFERENCES users(id),
  token_hash TEXT NOT NULL UNIQUE,
  created_by TEXT NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT
);

-- Livraisons (la couche qui manquait entre la notification et l'appareil).
--
-- `events` dit CE QUI S'EST PASSÉ, `notifications` dit QUI DOIT LE SAVOIR.
-- Aucune table ne disait jusqu'ici SI LE MESSAGE EST PARTI. L'audit du 21/09
-- l'a confirmé : notifications.py se terminait sur un INSERT, et rien ne
-- quittait le serveur.
--
-- Une ligne = UNE tentative d'acheminement par UN canal. Une notification peut
-- donc avoir zéro livraison (in-app seulement), une, ou plusieurs (e-mail qui
-- échoue puis réussit). `notification_id` est NULLABLE : une invitation et une
-- réinitialisation de mot de passe s'envoient à quelqu'un qui n'a pas encore
-- de compte, donc pas de notification interne.
--
-- ACCEPTED N'EST PAS DELIVERED. « Le fournisseur a accepté la demande » ne veut
-- pas dire « le parent l'a reçue ». On ne passe à DELIVERED que si le
-- fournisseur le confirme réellement — jamais par optimisme.
CREATE TABLE IF NOT EXISTS deliveries (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  notification_id TEXT REFERENCES notifications(id),
  channel TEXT NOT NULL,              -- EMAIL | WHATSAPP_LINK | SMS | PUSH
  template TEXT NOT NULL,             -- invitation_parent, password_reset, ...
  recipient_user_id TEXT REFERENCES users(id),
  recipient_address TEXT NOT NULL,    -- adresse réellement visée, telle qu'utilisée
  subject TEXT,
  status TEXT NOT NULL DEFAULT 'CREATED',
  -- CREATED QUEUED SENDING ACCEPTED DELIVERED FAILED BOUNCED CANCELLED
  provider TEXT,
  provider_message_id TEXT,
  error_code TEXT,
  error_message TEXT,                 -- message technique, jamais de secret
  attempts INTEGER NOT NULL DEFAULT 0,
  -- Même mécanique que les paiements : une clé identifie UNE livraison. Un
  -- double clic, un rafraîchissement ou un rejeu retombent sur la même ligne
  -- au lieu d'envoyer deux fois le même message.
  idempotency_key TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT,
  sent_at TEXT,
  failed_at TEXT,
  UNIQUE(tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_deliveries_tenant ON deliveries(tenant_id, created_at);

-- Exports. L'établissement doit pouvoir REPRENDRE ses données.
--
-- Klassio savait importer depuis Excel depuis longtemps ; rien ne sortait.
-- Pour un logiciel payant c'est d'abord une question de confiance : « et si
-- j'arrête de payer, je perds tout ? » est la première question d'un directeur
-- prudent, et la réponse doit être bonne.
--
-- Une ligne = UNE demande d'export, avec son état RÉEL. L'écran n'affiche
-- jamais « prêt » parce qu'un bouton a été cliqué : il l'affiche parce que le
-- serveur a écrit READY. `counts` garde le nombre de lignes par feuille, ce
-- qui permet de vérifier qu'une archive est complète sans l'ouvrir.
--
-- ARCHIVER N'EST PAS SUPPRIMER. Rien ici n'efface quoi que ce soit : un export
-- est une COPIE. La suppression des données d'une année close, si elle arrive
-- un jour, sera une décision distincte et explicite.
CREATE TABLE IF NOT EXISTS exports (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  academic_year_id TEXT REFERENCES academic_years(id),
  kind TEXT NOT NULL,                 -- students | classes | ... | annual
  scope TEXT,                         -- JSON des filtres appliqués
  status TEXT NOT NULL DEFAULT 'CREATED',
  -- CREATED | PROCESSING | READY | FAILED | EXPIRED
  file_name TEXT,
  file_size INTEGER,
  counts TEXT,                        -- JSON {feuille: nombre de lignes}
  error_message TEXT,
  requested_by TEXT NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL,
  completed_at TEXT,
  expires_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_exports_tenant ON exports(tenant_id, created_at);


CREATE INDEX IF NOT EXISTS idx_deliveries_status ON deliveries(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_deliveries_notification ON deliveries(notification_id);

CREATE INDEX IF NOT EXISTS idx_students_tenant ON students(tenant_id);
CREATE INDEX IF NOT EXISTS idx_class_teachers_user ON class_teachers(tenant_id, user_id);
CREATE INDEX IF NOT EXISTS idx_attendance_student ON attendance(tenant_id, student_id, date);
CREATE INDEX IF NOT EXISTS idx_attendance_class_date ON attendance(tenant_id, class_id, date);
CREATE INDEX IF NOT EXISTS idx_incidents_student ON incidents(tenant_id, student_id);
CREATE INDEX IF NOT EXISTS idx_grades_student ON grades(tenant_id, student_id);
CREATE INDEX IF NOT EXISTS idx_schedule_class ON schedule_slots(tenant_id, class_id);
CREATE INDEX IF NOT EXISTS idx_orders_parent ON orders(tenant_id, parent_user_id);
CREATE INDEX IF NOT EXISTS idx_receipts_student ON receipts(tenant_id, student_id);
CREATE INDEX IF NOT EXISTS idx_obligations_tenant_student ON obligations(tenant_id, student_id);
CREATE INDEX IF NOT EXISTS idx_payments_tenant_obligation ON payments(tenant_id, obligation_id);
CREATE INDEX IF NOT EXISTS idx_events_tenant ON events(tenant_id);
CREATE INDEX IF NOT EXISTS idx_ai_conv_user ON ai_conversations(tenant_id, user_id);
CREATE INDEX IF NOT EXISTS idx_ai_msg_conv ON ai_messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_notifications_recipient ON notifications(recipient_user_id, status);
CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_logs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_invitations_tenant ON invitations(tenant_id);

-- ===========================================================================
-- LOTS 2–5 : calendrier & communiqués, ressources (livres/devoirs), documents,
-- cahier de communication, justifications, discipline (signalements,
-- convocations, seuils), résultats (périodes, appréciations, conduite,
-- décisions), boutique (retrait), préférences, abonnement & plateforme.
-- Même principe partout : tenant_id sur chaque ligne, périmètre décidé par
-- backend/school.py, jamais par le client.
-- ===========================================================================

-- Événement ou communiqué de l'établissement, ciblé (toute l'école, un cycle,
-- une classe), publié par la Direction ou le DD. Alimente le calendrier des
-- parents et du personnel + notification.
CREATE TABLE IF NOT EXISTS calendar_events (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  kind TEXT NOT NULL DEFAULT 'evenement', -- evenement | communique | reunion | fete | deuil | conge | examens | echeance
  title TEXT NOT NULL,
  body TEXT,
  starts_on TEXT,            -- AAAA-MM-JJ (NULL pour un communiqué sans date)
  ends_on TEXT,
  starts_time TEXT,
  target_scope TEXT NOT NULL DEFAULT 'all', -- all | cycle | class
  target_value TEXT,         -- nom du cycle ou id de classe
  audience TEXT NOT NULL DEFAULT 'all',     -- all | parents | staff
  created_by TEXT REFERENCES users(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Ressource pédagogique rattachée à une classe : livre, leçon, fiche, devoir
-- (avec échéance). Publiée par le titulaire/enseignant ou la Direction ;
-- visible des parents de la classe. Fichier stocké en data URL (MVP).
CREATE TABLE IF NOT EXISTS resources (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  class_id TEXT NOT NULL REFERENCES classes(id),
  kind TEXT NOT NULL DEFAULT 'lecon', -- livre | lecon | fiche | devoir | autre
  title TEXT NOT NULL,
  subject TEXT,
  description TEXT,
  file_name TEXT,
  file_data TEXT,
  file_size INTEGER,
  due_date TEXT,
  published_by TEXT REFERENCES users(id),
  created_at TEXT NOT NULL
);

-- Documents officiels de l'établissement (règlement intérieur…), consultables
-- par les rôles autorisés.
CREATE TABLE IF NOT EXISTS school_documents (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  kind TEXT NOT NULL DEFAULT 'autre', -- reglement | calendrier | autre
  title TEXT NOT NULL,
  file_name TEXT,
  file_data TEXT,
  file_size INTEGER,
  visible_to TEXT NOT NULL DEFAULT 'all', -- all | staff
  uploaded_by TEXT REFERENCES users(id),
  created_at TEXT NOT NULL
);

-- Cahier de communication : un fil par élève entre ses parents et le
-- personnel autorisé (titulaire, DD, Direction). Lecture tracée par personne.
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  student_id TEXT NOT NULL REFERENCES students(id),
  sender_id TEXT NOT NULL REFERENCES users(id),
  sender_role TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS message_reads (
  message_id TEXT NOT NULL REFERENCES messages(id),
  user_id TEXT NOT NULL REFERENCES users(id),
  read_at TEXT NOT NULL,
  PRIMARY KEY (message_id, user_id)
);

-- Justification d'absence demandée par le parent, décidée par un humain
-- (DD, titulaire, Direction). Acceptée → présence passe en 'excused'.
CREATE TABLE IF NOT EXISTS attendance_justifications (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  student_id TEXT NOT NULL REFERENCES students(id),
  date TEXT NOT NULL,
  reason TEXT NOT NULL,
  attachment_name TEXT,
  attachment_data TEXT,
  status TEXT NOT NULL DEFAULT 'pending', -- pending | accepted | refused
  requested_by TEXT REFERENCES users(id),
  decided_by TEXT REFERENCES users(id),
  decided_at TEXT,
  decision_note TEXT,
  created_at TEXT NOT NULL
);

-- Droit de réponse du parent sur un incident communiqué.
CREATE TABLE IF NOT EXISTS incident_replies (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  incident_id TEXT NOT NULL REFERENCES incidents(id),
  user_id TEXT NOT NULL REFERENCES users(id),
  body TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- Signalement d'un professeur au DD : un fait, pas une décision. Le DD le
-- qualifie (→ incident) ou le classe sans suite.
CREATE TABLE IF NOT EXISTS incident_reports (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  student_id TEXT NOT NULL REFERENCES students(id),
  class_id TEXT REFERENCES classes(id),
  reported_by TEXT NOT NULL REFERENCES users(id),
  description TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', -- pending | qualified | dismissed
  incident_id TEXT REFERENCES incidents(id),
  handled_by TEXT REFERENCES users(id),
  handled_at TEXT,
  handling_note TEXT,
  created_at TEXT NOT NULL
);

-- Convocation d'un parent (liée ou non à un incident).
CREATE TABLE IF NOT EXISTS convocations (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  student_id TEXT NOT NULL REFERENCES students(id),
  incident_id TEXT REFERENCES incidents(id),
  scheduled_on TEXT NOT NULL,
  scheduled_time TEXT,
  motif TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'planned', -- planned | held | missed | cancelled
  parent_attended INTEGER,
  notes TEXT,
  created_by TEXT REFERENCES users(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Seuils du capital de points, définis par l'établissement : quand le solde
-- restant passe sous `remaining_points`, une alerte humaine est déclenchée.
CREATE TABLE IF NOT EXISTS discipline_thresholds (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  remaining_points INTEGER NOT NULL,
  label TEXT NOT NULL,
  action TEXT,
  sort INTEGER NOT NULL DEFAULT 0
);

-- Périodes officielles de l'année (P1…P4, examens). Les notes d'une période ne
-- sont visibles des parents qu'après « proclamation » (published_at).
CREATE TABLE IF NOT EXISTS academic_periods (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  academic_year_id TEXT NOT NULL REFERENCES academic_years(id),
  label TEXT NOT NULL,
  sort INTEGER NOT NULL DEFAULT 0,
  weight REAL NOT NULL DEFAULT 1,
  starts_on TEXT,
  ends_on TEXT,
  is_exam INTEGER NOT NULL DEFAULT 0,
  published_at TEXT,
  published_by TEXT REFERENCES users(id),
  created_at TEXT NOT NULL
  -- L'unicité d'un libellé porte sur (tenant, année, DIVISION, libellé) et non
  -- sur le seul libellé : une école nomme « Période 1 » aussi bien au primaire
  -- qu'au secondaire, avec des dates différentes. Elle est posée en INDEX par
  -- db._migrate() plutôt qu'en contrainte de table, parce qu'un index se
  -- remplace sans reconstruire la table.
);

-- Maternelle : appréciations par domaine (pas de moyenne chiffrée).
CREATE TABLE IF NOT EXISTS appreciations (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  student_id TEXT NOT NULL REFERENCES students(id),
  class_id TEXT REFERENCES classes(id),
  period TEXT NOT NULL,
  domain TEXT NOT NULL,
  level INTEGER NOT NULL, -- 1 = en construction … 4 = acquis
  comment TEXT,
  recorded_by TEXT REFERENCES users(id),
  created_at TEXT NOT NULL
);

-- Cote de conduite fixée à la main par le conseil de classe (prime sur le calcul).
CREATE TABLE IF NOT EXISTS conduct_overrides (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  student_id TEXT NOT NULL REFERENCES students(id),
  period TEXT NOT NULL,
  label TEXT NOT NULL,
  note TEXT,
  set_by TEXT REFERENCES users(id),
  created_at TEXT NOT NULL,
  UNIQUE(tenant_id, student_id, period)
);

-- Décision de fin d'année (proclamation) — toujours une décision humaine.
-- Délibérations — le MOMENT où le conseil examine une classe.
--
-- Beaucoup de la délibération existait déjà sans porter ce nom : l'onglet
-- « Conseil de classe » montre rang, moyenne, conduite et décision ;
-- `bulletin_decisions` garde la décision de fin d'année ; `academic_periods`
-- rend les périodes configurables. Ce qui manquait, c'est la SESSION : un
-- objet qui a un début, un état, et une clôture — sans quoi personne ne peut
-- dire si la classe a été délibérée ou non.
--
-- La session porte (année, période, classe). `period_id` est NULL pour une
-- délibération ANNUELLE : c'est l'année entière qui est examinée, pas une
-- période. L'unicité empêche d'ouvrir deux fois la même séance.
CREATE TABLE IF NOT EXISTS deliberations (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  academic_year_id TEXT NOT NULL REFERENCES academic_years(id),
  period_id TEXT REFERENCES academic_periods(id),
  class_id TEXT NOT NULL REFERENCES classes(id),
  kind TEXT NOT NULL DEFAULT 'PERIOD',   -- PERIOD | ANNUAL
  status TEXT NOT NULL DEFAULT 'DRAFT',  -- DRAFT | IN_PROGRESS | CLOSED
  opened_by TEXT REFERENCES users(id),
  opened_at TEXT,
  closed_by TEXT REFERENCES users(id),
  closed_at TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(tenant_id, academic_year_id, period_id, class_id, kind)
);
CREATE INDEX IF NOT EXISTS idx_deliberations_tenant ON deliberations(tenant_id, academic_year_id);
CREATE INDEX IF NOT EXISTS idx_deliberations_class ON deliberations(tenant_id, class_id);

-- Ce que chacun DÉPOSE au cours de la délibération.
--
-- Trois natures, une seule table, parce qu'elles partagent tout : un auteur,
-- un rôle, une date, un élève, une délibération.
--
--   OBSERVATION  le conseil note quelque chose. Personne ne décide.
--   AVIS         un titulaire, un professeur ou le DD se prononce. Ce n'est
--                PAS la décision : c'est une contribution au débat.
--   DECISION     la Direction tranche. Seul ce type fait foi.
--
-- APPEND-ONLY. Rien n'est jamais écrasé : corriger crée une nouvelle ligne et
-- date l'ancienne dans `superseded_at`. C'est exactement le motif déjà employé
-- pour les notes (`grades.is_current` / `superseded_at`), et pour la même
-- raison : une délibération est un acte institutionnel, on doit pouvoir dire
-- plus tard qui a proposé quoi et quand la position a changé.
CREATE TABLE IF NOT EXISTS deliberation_entries (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  deliberation_id TEXT NOT NULL REFERENCES deliberations(id),
  student_id TEXT NOT NULL REFERENCES students(id),
  kind TEXT NOT NULL,                    -- OBSERVATION | AVIS | DECISION
  value TEXT,                            -- PASSAGE | REDOUBLEMENT | DEPART | AUTRE | A_EXAMINER
  comment TEXT,
  author_id TEXT NOT NULL REFERENCES users(id),
  author_role TEXT NOT NULL,
  created_at TEXT NOT NULL,
  superseded_at TEXT,                    -- non NULL = remplacée par une plus récente
  superseded_by TEXT REFERENCES deliberation_entries(id)
);
CREATE INDEX IF NOT EXISTS idx_delib_entries ON deliberation_entries(tenant_id, deliberation_id, student_id);
CREATE INDEX IF NOT EXISTS idx_delib_entries_student ON deliberation_entries(tenant_id, student_id);

CREATE TABLE IF NOT EXISTS bulletin_decisions (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  student_id TEXT NOT NULL REFERENCES students(id),
  academic_year_id TEXT NOT NULL REFERENCES academic_years(id),
  decision TEXT NOT NULL, -- admis | ajourne | doublant
  mention TEXT,
  note TEXT,
  set_by TEXT REFERENCES users(id),
  created_at TEXT NOT NULL,
  UNIQUE(tenant_id, student_id, academic_year_id)
);

-- Préférences personnelles (notification quotidienne de présence, partage du téléphone…)
CREATE TABLE IF NOT EXISTS user_preferences (
  user_id TEXT PRIMARY KEY REFERENCES users(id),
  notify_present_daily INTEGER NOT NULL DEFAULT 1,
  share_phone INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT
);

-- ---------------------------------------------------------------------------
-- ABONNEMENT (l'école paie Klassio) — circuit strictement séparé des frais
-- scolaires : ni obligation, ni paiement, ni reçu des tables métier.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS plans (
  code TEXT PRIMARY KEY,          -- essentiel | ecole | complexe | reseau
  name TEXT NOT NULL,
  min_students INTEGER NOT NULL DEFAULT 0,
  max_students INTEGER,           -- NULL = illimité (sur devis)
  base_price REAL NOT NULL DEFAULT 0,
  per_student REAL NOT NULL DEFAULT 0,
  currency TEXT NOT NULL DEFAULT 'USD',
  description TEXT,
  sort INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS subscriptions (
  tenant_id TEXT PRIMARY KEY REFERENCES tenants(id),
  plan_code TEXT NOT NULL REFERENCES plans(code),
  status TEXT NOT NULL DEFAULT 'trial', -- trial | active | past_due | suspended | cancelled
  trial_ends_at TEXT,
  current_period_start TEXT,
  current_period_end TEXT,
  grace_days INTEGER NOT NULL DEFAULT 15,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invoices (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  number TEXT NOT NULL UNIQUE,
  plan_code TEXT NOT NULL,
  period_start TEXT NOT NULL,
  period_end TEXT NOT NULL,
  students INTEGER NOT NULL,
  amount REAL NOT NULL,
  currency TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open', -- open | pending | paid | void
  due_at TEXT NOT NULL,
  paid_at TEXT,
  method TEXT,
  reference TEXT,
  created_at TEXT NOT NULL
);

-- Administrateurs de la plateforme Klassio (rôle global, hors tenant).
-- Session d'import (docs/IMPORT.md) — le lien entre ce qui a été ANALYSÉ et
-- montré à la personne, et ce qui sera réellement ÉCRIT.
--
-- Sans cette table, /api/onboarding/confirm-import acceptait la liste
-- d'enregistrements envoyée par le client : rien ne garantissait qu'elle
-- corresponde à l'aperçu validé. Un aperçu de 100 élèves pouvait être confirmé
-- par 500 lignes différentes. Les enregistrements sont désormais conservés côté
-- serveur au moment de l'analyse, et la confirmation rejoue exactement ceux-là.
CREATE TABLE IF NOT EXISTS import_sessions (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  created_by TEXT NOT NULL REFERENCES users(id),
  file_name TEXT,
  students_count INTEGER NOT NULL,
  records TEXT NOT NULL,                    -- JSON des enregistrements normalisés
  status TEXT NOT NULL DEFAULT 'analyzed',  -- analyzed | confirmed
  created_at TEXT NOT NULL,
  confirmed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_import_sessions_tenant ON import_sessions(tenant_id, created_at);

-- Limitation anti-force-brute (docs/SECURITE.md §4.4).
-- Les compteurs vivaient dans un dictionnaire en mémoire de processus, ce qui
-- imposait de ne jamais lancer plus d'un worker : avec N workers, un attaquant
-- obtenait N fois la limite. En base, la limite est la même quel que soit le
-- nombre de workers, et elle survit à un redémarrage du serveur.
CREATE TABLE IF NOT EXISTS rate_limit_attempts (
  id TEXT PRIMARY KEY,
  bucket TEXT NOT NULL,          -- login | register | invite_accept | …
  subject TEXT NOT NULL,         -- adresse e-mail ou adresse IP, selon la route
  attempted_at REAL NOT NULL     -- horodatage epoch de la tentative
);
CREATE INDEX IF NOT EXISTS idx_rate_limit_lookup ON rate_limit_attempts(bucket, subject, attempted_at);
CREATE INDEX IF NOT EXISTS idx_rate_limit_purge ON rate_limit_attempts(attempted_at);

CREATE TABLE IF NOT EXISTS platform_admins (
  user_id TEXT PRIMARY KEY REFERENCES users(id),
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_calendar_tenant ON calendar_events(tenant_id, starts_on);
CREATE INDEX IF NOT EXISTS idx_resources_class ON resources(tenant_id, class_id);
CREATE INDEX IF NOT EXISTS idx_messages_student ON messages(tenant_id, student_id, created_at);
CREATE INDEX IF NOT EXISTS idx_justif_status ON attendance_justifications(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_reports_status ON incident_reports(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_convocations_student ON convocations(tenant_id, student_id);
CREATE INDEX IF NOT EXISTS idx_appreciations_student ON appreciations(tenant_id, student_id);
CREATE INDEX IF NOT EXISTS idx_invoices_tenant ON invoices(tenant_id, status);

-- ===========================================================================
-- SYSTÈME ACADÉMIQUE — résultats officiels
--
-- Klassio V1 ne remplace pas le cahier de notes de l'enseignant : il gère les
-- résultats OFFICIELS, ceux que l'établissement a lui-même calculés et qu'il
-- importe pour les valider, les proclamer et les publier. Aucune saisie
-- quotidienne n'est imposée.
-- ===========================================================================

-- Session d'import de RÉSULTATS. Distincte de import_sessions (qui importe des
-- ÉLÈVES) : les colonnes attendues, la correspondance et les anomalies n'ont
-- rien à voir. Même principe de sécurité en revanche — les lignes analysées
-- sont conservées côté serveur, et c'est exactement elles qui seront écrites.
CREATE TABLE IF NOT EXISTS result_imports (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  academic_year_id TEXT NOT NULL REFERENCES academic_years(id),
  period_id TEXT NOT NULL REFERENCES academic_periods(id),
  created_by TEXT NOT NULL REFERENCES users(id),
  file_name TEXT,
  rows_total INTEGER NOT NULL DEFAULT 0,
  rows_matched INTEGER NOT NULL DEFAULT 0,
  rows_ambiguous INTEGER NOT NULL DEFAULT 0,
  rows_unmatched INTEGER NOT NULL DEFAULT 0,
  records TEXT NOT NULL,                      -- JSON des lignes analysées + correspondance
  status TEXT NOT NULL DEFAULT 'analyzed',    -- analyzed | confirmed | cancelled
  created_at TEXT NOT NULL,
  confirmed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_result_imports_tenant ON result_imports(tenant_id, created_at);

-- Réouverture exceptionnelle d'une période verrouillée. Jamais silencieuse :
-- une raison, un responsable, une date, et la trace de la refermeture.
CREATE TABLE IF NOT EXISTS period_reopenings (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  period_id TEXT NOT NULL REFERENCES academic_periods(id),
  reason TEXT NOT NULL,
  reopened_by TEXT NOT NULL REFERENCES users(id),
  reopened_at TEXT NOT NULL,
  relocked_at TEXT,
  relocked_by TEXT REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_period_reopenings ON period_reopenings(tenant_id, period_id);

-- Proclamation d'une période : QUI a été inclus, décidé et recalculé par le
-- SERVEUR au moment de publier. L'audience n'est jamais la liste envoyée par
-- le navigateur — celle-ci ne sert qu'à afficher l'aperçu.
CREATE TABLE IF NOT EXISTS period_publications (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  period_id TEXT NOT NULL REFERENCES academic_periods(id),
  audience_filter TEXT,                       -- JSON du filtre demandé (classes, niveaux, élèves)
  included_count INTEGER NOT NULL DEFAULT 0,
  excluded_count INTEGER NOT NULL DEFAULT 0,
  published_by TEXT NOT NULL REFERENCES users(id),
  published_at TEXT NOT NULL,
  unpublished_at TEXT,
  unpublished_by TEXT REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_period_publications ON period_publications(tenant_id, period_id);

-- Élèves réellement couverts par une proclamation. C'est CETTE table que lit
-- le portail parent : un élève absent d'ici ne voit pas ses résultats, quelle
-- que soit la période.
CREATE TABLE IF NOT EXISTS publication_students (
  publication_id TEXT NOT NULL REFERENCES period_publications(id),
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  student_id TEXT NOT NULL REFERENCES students(id),
  PRIMARY KEY (publication_id, student_id)
);
CREATE INDEX IF NOT EXISTS idx_publication_students ON publication_students(tenant_id, student_id);
