from flask import Flask, jsonify, request, render_template, redirect, url_for, session, flash
from flask_cors import CORS
import oracledb
from contextlib import contextmanager
from datetime import datetime, timedelta
import logging
from functools import wraps


app = Flask(__name__)
app.config["SECRET_KEY"] = "parking-smart-dev-key" 
CORS(app)  # Permet les requêtes CORS si vous avez un frontend séparé

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========================================================
# CONFIGURATION DE LA BASE DE DONNÉES
# ========================================================
DB_CONFIG = {
    'user': 'PARKING',
    'password': 'Parking#2025',
    'dsn': 'localhost:1521/XEPDB1'
}


TABLE_OWNER = 'Parking'

# ========================================================
# GESTIONNAIRE DE CONNEXION (Context Manager)
# ========================================================
@contextmanager
def get_db_connection():
    """Context manager pour gérer automatiquement les connexions"""
    connection = None
    try:
        connection = oracledb.connect(**DB_CONFIG)
        yield connection
    except oracledb.Error as error:
        logger.error(f"Erreur de connexion à la base de données: {error}")
        raise
    finally:
        if connection:
            connection.close()

@contextmanager
def get_db_cursor(commit=False):
    """Context manager pour gérer les curseurs avec commit optionnel"""
    with get_db_connection() as connection:
        cursor = connection.cursor()
        try:
            yield cursor
            if commit:
                connection.commit()
        except Exception as e:
            if commit:
                connection.rollback()
            raise
        finally:
            cursor.close()
# ========================================================
# DÉCORATEURS D'AUTHENTIFICATION
# ========================================================
def login_required(f):
    """Décorateur pour protéger les routes nécessitant une connexion"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Veuillez vous connecter pour accéder à cette page', 'warning')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Décorateur pour les routes réservées aux administrateurs"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Veuillez vous connecter pour accéder à cette page', 'warning')
            return redirect(url_for('home'))
        if session.get('role') != 'ADMIN':
            flash('Accès refusé. Cette page est réservée aux administrateurs.', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

def agent_required(f):
    """Décorateur pour les routes réservées aux agents"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Veuillez vous connecter pour accéder à cette page', 'warning')
            return redirect(url_for('home'))
        if session.get('role') not in ['ADMIN', 'AGENT']:
            flash('Accès refusé. Cette page est réservée au personnel.', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

# ========================================================
# FONCTIONS UTILITAIRES
# ========================================================
def row_to_dict(cursor, row):
    """Convertit une ligne de résultat en dictionnaire"""
    columns = [col[0] for col in cursor.description]
    return dict(zip(columns, row))

def rows_to_dict_list(cursor, rows):
    """Convertit plusieurs lignes en liste de dictionnaires"""
    return [row_to_dict(cursor, row) for row in rows]

def serialize_datetime(obj):
    """Sérialise les objets datetime pour JSON"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


# ========================================================
# ROUTES - PAGE D'ACCUEIL ET AUTHENTIFICATION
# ========================================================
@app.route('/')
def home():
    """Affiche la page d'accueil HTML"""
    # Si déjà connecté, rediriger vers le dashboard approprié
    if 'user_id' in session:
        if session.get('role') == 'ADMIN':
            return redirect(url_for('admin_dashboard'))
        elif session.get('role') == 'AGENT':
            return redirect(url_for('agent_dashboard'))
    return render_template('home.html')

@app.route('/login', methods=['POST'])
def login():
    """Authentification des utilisateurs"""
    try:
        data = request.json
        username = data.get('username', '').strip().upper()
        password = data.get('password', '')
        role_type = data.get('role', '').upper()  # 'ADMIN' ou 'AGENT'
        
        # Validation des champs
        if not username or not password or not role_type:
            return jsonify({
                'success': False,
                'error': 'Tous les champs sont requis'
            }), 400
        
        if role_type not in ['ADMIN', 'AGENT']:
            return jsonify({
                'success': False,
                'error': 'Rôle invalide'
            }), 400
        
        # Tentative de connexion à Oracle avec les credentials fournis
        try:
            connection = oracledb.connect(
                user=username,
                password=password,
                dsn=DB_CONFIG['dsn']
            )
            
            # Vérifier le rôle de l'utilisateur
            cursor = connection.cursor()
            
            # Requête pour vérifier les rôles attribués
            cursor.execute("""
                SELECT GRANTED_ROLE 
                FROM USER_ROLE_PRIVS 
                WHERE GRANTED_ROLE IN ('R_ADMIN', 'R_AGENT')
            """)
            
            roles = [row[0] for row in cursor.fetchall()]
            cursor.close()
            connection.close()
            
            # Vérifier que l'utilisateur a le rôle demandé
            required_role = f'R_{role_type}'
            if required_role not in roles:
                logger.warning(f"Tentative de connexion avec un rôle incorrect: {username} -> {role_type}")
                return jsonify({
                    'success': False,
                    'error': 'Accès refusé. Vous n\'avez pas les permissions pour ce rôle.'
                }), 403
            
            # Authentification réussie - Créer la session
            session.permanent = True
            session['user_id'] = username
            session['role'] = role_type
            session['login_time'] = datetime.now().isoformat()
            
            logger.info(f"Connexion réussie: {username} en tant que {role_type}")
            
            # Déterminer l'URL de redirection
            redirect_url = url_for('admin_dashboard') if role_type == 'ADMIN' else url_for('agent_dashboard')
            
            return jsonify({
                'success': True,
                'message': 'Connexion réussie',
                'role': role_type,
                'redirect': redirect_url
            }), 200
            
        except oracledb.Error as db_error:
            error_obj = db_error.args[0] if db_error.args else None
            
            # Erreur d'authentification Oracle (mauvais mot de passe ou utilisateur)
            if error_obj and error_obj.code in [1017, 28000]:  # Invalid username/password
                logger.warning(f"Échec de connexion pour {username}: identifiants incorrects")
                return jsonify({
                    'success': False,
                    'error': 'Nom d\'utilisateur ou mot de passe incorrect'
                }), 401
            else:
                logger.error(f"Erreur Oracle lors de la connexion: {db_error}")
                return jsonify({
                    'success': False,
                    'error': 'Erreur de connexion à la base de données'
                }), 500
                
    except Exception as e:
        logger.error(f"Erreur lors du login: {e}")
        return jsonify({
            'success': False,
            'error': 'Une erreur s\'est produite lors de la connexion'
        }), 500

@app.route('/logout')
def logout():
    """Déconnexion de l'utilisateur"""
    username = session.get('user_id', 'Utilisateur inconnu')
    session.clear()
    flash('Vous avez été déconnecté avec succès', 'success')
    logger.info(f"Déconnexion: {username}")
    return redirect(url_for('home'))

@app.route('/admin')
@admin_required
def admin_dashboard():
    """Dashboard administrateur"""
    return render_template('ADMINN.html', user=session.get('user_id'))

@app.route('/agent')
@agent_required
def agent_dashboard():
    """Dashboard agent"""
    return render_template('AGENTT.html', user=session.get('user_id'))

@app.route('/api')
def api_info():
    """Informations sur l'API (ancien endpoint home)"""
    return jsonify({
        'message': 'API Gestion de Parking',
        'version': '1.0',
        'endpoints': {
            'authentification': {
                'POST /login': 'Se connecter',
                'GET /logout': 'Se déconnecter',
                'GET /admin': 'Dashboard administrateur',
                'GET /agent': 'Dashboard agent'
            },
            'clients': {
                'GET /clients': 'Liste tous les clients',
                'GET /clients/<id>': 'Détails d\'un client'
            },
            'places': {
                'GET /places': 'Liste toutes les places',
                'GET /places/disponibles': 'Places disponibles uniquement'
            },
            'abonnements': {
                'GET /abonnements': 'Liste tous les abonnements',
                'POST /abonner': 'Créer un abonnement'
            },
            'reservations': {
                'GET /reservations': 'Liste toutes les réservations',
                'POST /entree': 'Enregistrer une entrée',
                'POST /sortie': 'Valider une sortie'
            },
            'paiements': {
                'GET /paiements': 'Liste tous les paiements'
            },
            'statistiques': {
                'GET /statistiques': 'Statistiques du parking'
            },
            'test': {
                'GET /test-connexion': 'Tester la connexion DB'
            }
        }
    })
@app.route('/tarifs', methods=['GET'])
@login_required
def get_tarifs():
    """Récupérer tous les tarifs"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(f"""
                SELECT id_tarif, type_client, tarif_horaire
                FROM {TABLE_OWNER}.TARIF
                ORDER BY id_tarif
            """)
            rows = cursor.fetchall()
            tarifs = rows_to_dict_list(cursor, rows)

        return jsonify({
            'success': True,
            'data': tarifs
        })

    except oracledb.Error as e:
        logger.error(f"Erreur récupération tarifs: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
@app.route('/tarif/update', methods=['PUT'])
@admin_required
def update_tarif():
    """Mettre à jour les tarifs Abonné / Non Abonné"""
    try:
        data = request.json
        logger.info(f"Update tarif reçu: {data}")

        tarif_abonne = data.get('tarif_abonne')
        tarif_non_abonne = data.get('tarif_non_abonne')

        if tarif_abonne is None or tarif_non_abonne is None:
            return jsonify({
                'success': False,
                'error': 'Les deux tarifs sont obligatoires.'
            }), 400

        if tarif_abonne <= 0 or tarif_non_abonne <= 0:
            return jsonify({
                'success': False,
                'error': 'Les tarifs doivent être positifs.'
            }), 400

        with get_db_cursor(commit=True) as cursor:
            # Appeler la procédure PL/SQL
            cursor.callproc(f"{TABLE_OWNER}.mettre_a_jour_tarifs", 
                           [tarif_abonne, tarif_non_abonne])

        logger.info("Tarifs mis à jour avec succès via procédure PL/SQL")

        return jsonify({
            'success': True,
            'message': 'Tarifs mis à jour avec succès'
        }), 200

    except oracledb.Error as e:
        logger.error(f"Erreur update tarif: {e}")
        error_msg = str(e)
        
        # Gestion d'erreurs spécifiques
        if "ORA-20030" in error_msg:
            return jsonify({
                'success': False,
                'error': 'Les tarifs doivent être positifs.'
            }), 400
            
        return jsonify({
            'success': False,
            'error': error_msg
        }), 500
# ========================================================
# ROUTES - GESTION DES CLIENTS
# ========================================================
@app.route('/clients', methods=['GET'])
def get_clients():
    """Récupérer tous les clients"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(f"SELECT * FROM {TABLE_OWNER}.CLIENT ORDER BY nom, prenom")
            rows = cursor.fetchall()
            clients = rows_to_dict_list(cursor, rows)
        
        return jsonify({
            'success': True,
            'count': len(clients),
            'data': clients
        })
    except oracledb.Error as error:
        logger.error(f"Erreur lors de la récupération des clients: {error}")
        return jsonify({
            'success': False,
            'error': str(error)
        }), 500

@app.route('/clients/<int:id_client>', methods=['GET'])
def get_client_by_id(id_client):
    """Récupérer un client spécifique"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                f"SELECT * FROM {TABLE_OWNER}.CLIENT WHERE id_client = :id",
                {'id': id_client}
            )
            row = cursor.fetchone()
            
            if not row:
                return jsonify({
                    'success': False,
                    'error': 'Client non trouvé'
                }), 404
            
            client = row_to_dict(cursor, row)
        
        return jsonify({
            'success': True,
            'data': client
        })
    except oracledb.Error as error:
        logger.error(f"Erreur lors de la récupération du client {id_client}: {error}")
        return jsonify({
            'success': False,
            'error': str(error)
        }), 500

# ========================================================
# ROUTES - GESTION DES PLACES
# ========================================================
@app.route('/places', methods=['GET'])
def get_places():
    """Récupérer toutes les places"""
    try:
        type_place = request.args.get('type')  # Filtre optionnel par type
        
        with get_db_cursor() as cursor:
            query = f"SELECT * FROM {TABLE_OWNER}.PLACE"
            if type_place:
                query += " WHERE type_place = :type"
                cursor.execute(query + " ORDER BY numero_place", {'type': type_place})
            else:
                cursor.execute(query + " ORDER BY numero_place")
            
            rows = cursor.fetchall()
            places = rows_to_dict_list(cursor, rows)
        
        return jsonify({
            'success': True,
            'count': len(places),
            'data': places
        })
    except oracledb.Error as error:
        logger.error(f"Erreur lors de la récupération des places: {error}")
        return jsonify({
            'success': False,
            'error': str(error)
        }), 500

@app.route('/places/disponibles', methods=['GET'])
def get_places_disponibles():
    """Récupérer uniquement les places disponibles"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(f"""
                SELECT * FROM {TABLE_OWNER}.PLACE 
                WHERE disponible = 'O' 
                ORDER BY type_place, numero_place
            """)
            rows = cursor.fetchall()
            places = rows_to_dict_list(cursor, rows)
        
        return jsonify({
            'success': True,
            'count': len(places),
            'data': places
        })
    except oracledb.Error as error:
        logger.error(f"Erreur lors de la récupération des places disponibles: {error}")
        return jsonify({
            'success': False,
            'error': str(error)
        }), 500

# ========================================================
# ROUTES - GESTION DES ABONNEMENTS
# ========================================================
@app.route('/abonnements', methods=['GET'])
def get_abonnements():
    """Récupérer tous les abonnements"""
    try:
        actif_only = request.args.get('actif', 'false').lower() == 'true'
        
        with get_db_cursor() as cursor:
            query = f"""
                SELECT a.*, c.nom, c.prenom, c.telephone
                FROM {TABLE_OWNER}.ABONNEMENT a
                JOIN {TABLE_OWNER}.CLIENT c ON a.id_client = c.id_client
            """
            if actif_only:
                query += " WHERE a.actif = 'O'"
            query += " ORDER BY a.date_inscription DESC"
            
            cursor.execute(query)
            rows = cursor.fetchall()
            abonnements = rows_to_dict_list(cursor, rows)
        
        return jsonify({
            'success': True,
            'count': len(abonnements),
            'data': abonnements
        })
    except oracledb.Error as error:
        logger.error(f"Erreur lors de la récupération des abonnements: {error}")
        return jsonify({
            'success': False,
            'error': str(error)
        }), 500
    
@app.route('/abonner', methods=['POST'])
def s_abonner():
    """S'abonner - utilise la procédure PL/SQL"""
    try:
        data = request.json
        
        # Validation des données
        required_fields = ['nom', 'prenom', 'telephone']
        for field in required_fields:
            if not data.get(field):
                return jsonify({
                    'success': False,
                    'error': f'Le champ {field} est requis'
                }), 400
        
        nom = data.get('nom')
        prenom = data.get('prenom')
        telephone = data.get('telephone')
        pmr = data.get('pmr', 'N')
        
        with get_db_cursor(commit=True) as cursor:
            cursor.callproc(f'{TABLE_OWNER}.s_abonner', [nom, prenom, telephone, pmr])
        
        logger.info(f"Nouvel abonnement créé pour {nom} {prenom}")
        return jsonify({
            'success': True,
            'message': f'Abonnement effectué avec succès pour {nom} {prenom}'
        }), 201
        
    except oracledb.Error as error:
        logger.error(f"Erreur lors de la création de l'abonnement: {error}")
        return jsonify({
            'success': False,
            'error': str(error)
        }), 500

# ========================================================
# ROUTES - GESTION DES RÉSERVATIONS
# ========================================================
@app.route('/reservations', methods=['GET'])
def get_reservations():
    """Récupérer toutes les réservations"""
    try:
        en_cours = request.args.get('en_cours', 'false').lower() == 'true'
        
        with get_db_cursor() as cursor:
            query = f"""
                SELECT r.*, c.nom, c.prenom, p.numero_place, p.type_place, t.tarif_horaire
                FROM {TABLE_OWNER}.RESERVATION r
                JOIN {TABLE_OWNER}.CLIENT c ON r.id_client = c.id_client
                JOIN {TABLE_OWNER}.PLACE p ON r.id_place = p.id_place
                LEFT JOIN {TABLE_OWNER}.TARIF t ON r.id_tarif = t.id_tarif
            """
            if en_cours:
                query += " WHERE r.date_sortie IS NULL"
            query += " ORDER BY r.date_entree DESC"
            
            cursor.execute(query)
            rows = cursor.fetchall()
            reservations = rows_to_dict_list(cursor, rows)
        
        return jsonify({
            'success': True,
            'count': len(reservations),
            'data': reservations
        })
    except oracledb.Error as error:
        logger.error(f"Erreur lors de la récupération des réservations: {error}")
        return jsonify({
            'success': False,
            'error': str(error)
        }), 500
@app.route('/entree', methods=['POST'])
def ajouter_entree():
    try:
        data = request.json or {}

        for field in ['nom', 'prenom', 'telephone']:
            if not data.get(field):
                return jsonify({'success': False, 'error': f'Le champ {field} est requis'}), 400

        nom = data.get('nom').strip()
        prenom = data.get('prenom').strip()
        telephone = data.get('telephone').strip()

        pmr = data.get('pmr', 'N')
        if isinstance(pmr, bool):
            pmr = 'O' if pmr else 'N'
        pmr = str(pmr).upper()
        if pmr not in ('O', 'N', '0', '1'):
            pmr = 'N'
        if pmr in ('0', '1'):
            pmr = 'O' if pmr == '1' else 'N'

        with get_db_connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.callproc(f'{TABLE_OWNER}.ajouter_entree', [nom, prenom, telephone, pmr])

                # ✅ IMPORTANT: TICKET n'a PAS statut -> on utilise r.statut
                cursor.execute(f"""
                    SELECT *
                    FROM (
                        SELECT
                            t.id_ticket,
                            r.id_reservation,
                            c.id_client,
                            r.date_entree,
                            p.numero_place,
                            NVL(r.statut, CASE WHEN r.date_sortie IS NULL THEN 'EN_COURS' ELSE 'TERMINE' END) AS statut
                        FROM {TABLE_OWNER}.TICKET t
                        JOIN {TABLE_OWNER}.RESERVATION r ON t.id_reservation = r.id_reservation
                        JOIN {TABLE_OWNER}.CLIENT c ON r.id_client = c.id_client
                        JOIN {TABLE_OWNER}.PLACE p ON r.id_place = p.id_place
                        WHERE c.telephone = :tel
                        ORDER BY r.date_entree DESC
                    )
                    WHERE ROWNUM = 1
                """, {'tel': telephone})

                row = cursor.fetchone()
                ticket_info = row_to_dict(cursor, row) if row else None

                # ✅ Si rien n'a été créé => la procédure a rollback mais n'a pas levé d'erreur
                if ticket_info is None:
                    connection.rollback()
                    return jsonify({
                        'success': False,
                        'error': "Entrée NON enregistrée côté Oracle (la procédure a rollback). "
                                 "Ca arrive si: aucune place libre, tarif introuvable, contrainte/clé étrangère, etc. "
                                 "Teste la procédure dans SQL Developer avec SERVEROUTPUT pour voir le vrai message."
                    }), 409

                connection.commit()

            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()

        return jsonify({
            'success': True,
            'message': f'Entrée validée pour {nom} {prenom}',
            'ticket': ticket_info
        }), 201

    except oracledb.Error as error:
        logger.error(f"Erreur lors de l'ajout de l'entrée: {error}")
        return jsonify({'success': False, 'error': str(error)}), 500

@app.route('/tickets', methods=['GET'])
def get_tickets():
    """
    Tickets récents (via table TICKET + jointures).
    Option: /tickets?en_cours=true
    """
    try:
        en_cours = request.args.get('en_cours', 'false').lower() == 'true'

        with get_db_cursor() as cursor:
            query = f"""
                SELECT
                    t.id_ticket,
                    t.date_emission,
                    r.id_reservation,
                    r.date_entree,
                    p.numero_place,
                    c.nom,
                    c.prenom,
                    CASE
                        WHEN r.date_sortie IS NULL THEN 'EN_COURS'
                        ELSE 'TERMINE'
                    END AS statut
                FROM {TABLE_OWNER}.TICKET t
                JOIN {TABLE_OWNER}.RESERVATION r ON t.id_reservation = r.id_reservation
                JOIN {TABLE_OWNER}.CLIENT c ON r.id_client = c.id_client
                JOIN {TABLE_OWNER}.PLACE p ON r.id_place = p.id_place
            """

            if en_cours:
                # si ton statut ticket existe : t.statut = 'EN_COURS'
                # sinon on peut se baser sur r.date_sortie IS NULL
                query += " WHERE (t.statut = 'EN_COURS' OR r.date_sortie IS NULL) "

            query += " ORDER BY t.date_creation DESC"

            cursor.execute(query)
            rows = cursor.fetchall()
            tickets = rows_to_dict_list(cursor, rows)

        return jsonify({'success': True, 'count': len(tickets), 'data': tickets})

    except oracledb.Error as error:
        logger.error(f"Erreur tickets: {error}")
        return jsonify({'success': False, 'error': str(error)}), 500

@app.route('/sortie', methods=['POST'])
def valider_sortie():
    """Valider une sortie - utilise la procédure PL/SQL"""
    try:
        data = request.json
        
        if not data.get('id_ticket'):
            return jsonify({
                'success': False,
                'error': 'Le champ id_ticket est requis'
            }), 400
        
        id_ticket = data.get('id_ticket')
        mode_paiement = data.get('mode_paiement', 'Espèces')
        
        with get_db_cursor(commit=True) as cursor:
            cursor.callproc(f'{TABLE_OWNER}.valider_sortie', [id_ticket, mode_paiement])
        
        logger.info(f"Sortie validée pour le ticket {id_ticket}")
        return jsonify({
            'success': True,
            'message': 'Sortie validée avec succès',
            'id_ticket': id_ticket
        }), 200
        
    except oracledb.Error as error:
        logger.error(f"Erreur lors de la validation de sortie: {error}")
        return jsonify({
            'success': False,
            'error': str(error)
        }), 500

# ========================================================
# ROUTES - GESTION DES PAIEMENTS
# ========================================================
@app.route('/paiements', methods=['GET'])
def get_paiements():
    """Récupérer tous les paiements"""
    try:
        date_debut = request.args.get('date_debut')
        date_fin = request.args.get('date_fin')
        
        with get_db_cursor() as cursor:
            query = f"""
                SELECT p.*, c.nom, c.prenom, r.date_entree, r.date_sortie
                FROM {TABLE_OWNER}.PAIEMENT p
                JOIN {TABLE_OWNER}.RESERVATION r ON p.id_reservation = r.id_reservation
                JOIN {TABLE_OWNER}.CLIENT c ON r.id_client = c.id_client
            """
            params = {}
            
            if date_debut and date_fin:
                query += " WHERE TRUNC(p.date_paiement) BETWEEN TO_DATE(:debut, 'YYYY-MM-DD') AND TO_DATE(:fin, 'YYYY-MM-DD')"
                params = {'debut': date_debut, 'fin': date_fin}
            
            query += " ORDER BY p.date_paiement DESC"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            paiements = rows_to_dict_list(cursor, rows)
        
        return jsonify({
            'success': True,
            'count': len(paiements),
            'data': paiements
        })
    except oracledb.Error as error:
        logger.error(f"Erreur lors de la récupération des paiements: {error}")
        return jsonify({
            'success': False,
            'error': str(error)
        }), 500
# ========================================================
# ROUTES - AJOUTER UN CLIENT (UTILISANT LA FONCTION PL/SQL)
# ========================================================

@app.route('/client/add', methods=['POST'])
@login_required
def add_client():
    """Ajouter un nouveau client avec la fonction PL/SQL Ajouter_client"""
    try:
        data = request.json
        
        # Log des données reçues
        logger.info(f"Données reçues: {data}")
        
        nom = data.get('nom', '').strip()
        prenom = data.get('prenom', '').strip()
        telephone = data.get('telephone', '').strip()
        pmr = data.get('pmr', 'N')  # 'O' ou 'N'
        
        # Log de la valeur PMR avant normalisation
        logger.info(f"PMR reçu: '{pmr}' (type: {type(pmr)})")

        # Vérification des champs
        if not nom or not prenom:
            return jsonify({
                'success': False,
                'error': 'Nom et prénom obligatoires.'
            }), 400
        
        # Normaliser la valeur PMR (gérer les différents cas)
        pmr = str(pmr).upper().strip()
        if pmr not in ['O', 'N']:
            logger.warning(f"Valeur PMR invalide '{pmr}', défaut à 'N'")
            pmr = 'N'
        
        # Log de la valeur PMR finale
        logger.info(f"PMR normalisé: '{pmr}'")
        
        with get_db_cursor(commit=True) as cursor:
            # Log avant l'appel de la fonction
            logger.info(f"Appel Ajouter_client({nom}, {prenom}, {telephone}, {pmr})")
            
            # Appeler la fonction PL/SQL Ajouter_client
            client_id = cursor.callfunc(
                f'{TABLE_OWNER}.Ajouter_client',
                int,
                [nom, prenom, telephone, pmr]
            )
            
            logger.info(f"ID client retourné: {client_id}")
            
            # Vérifier le résultat de la fonction
            if client_id == -1:
                return jsonify({
                    'success': False,
                    'error': 'Erreur lors de l\'ajout du client.'
                }), 500
            
            # Récupérer les informations du client
            cursor.execute(f"""
                SELECT id_client, nom, prenom, telephone, pmr
                FROM {TABLE_OWNER}.CLIENT 
                WHERE id_client = :id
            """, {'id': client_id})
            
            client = cursor.fetchone()
            
            if client:
                # Log des données récupérées
                logger.info(f"Client récupéré de la DB: {client}")
                
                return jsonify({
                    'success': True,
                    'message': f'Client {nom} {prenom} traité avec succès.',
                    'id_client': client[0],
                    'nom': client[1],
                    'prenom': client[2],
                    'telephone': client[3],
                    'pmr': client[4]
                }), 201
            else:
                return jsonify({
                    'success': False,
                    'error': 'Client créé mais non trouvé.'
                }), 500

    except oracledb.IntegrityError as e:
        logger.error(f"IntegrityError: {e}")
        return jsonify({
            'success': False,
            'error': 'Téléphone déjà utilisé.'
        }), 400
        
    except oracledb.Error as e:
        error_code = e.args[0].code if e.args else None
        logger.error(f"OracleError (code: {error_code}): {e}")
        
        if error_code == 1:
            return jsonify({
                'success': False,
                'error': 'Ce numéro de téléphone est déjà utilisé par un autre client.'
            }), 400
        elif error_code == 6502:
            return jsonify({
                'success': False,
                'error': 'Erreur dans la fonction PL/SQL.'
            }), 500
        else:
            return jsonify({
                'success': False,
                'error': f'Erreur Oracle: {str(e)}'
            }), 500
            
    except Exception as e:
        logger.error(f"Erreur lors de l'ajout du client: {e}")
        return jsonify({
            'success': False,
            'error': f'Erreur interne: {str(e)}'
        }), 500
# ========================================================
# ROUTES - STATISTIQUES
# ========================================================
@app.route('/statistiques', methods=['GET'])
def get_statistiques():
    """Récupérer les statistiques du parking"""
    try:
        with get_db_cursor() as cursor:
            # Appel des fonctions PL/SQL
            total_clients = cursor.callfunc(f'{TABLE_OWNER}.total_clients', int)
            total_abonnes = cursor.callfunc(f'{TABLE_OWNER}.total_abonnes', int)
            taux_occupation = cursor.callfunc(f'{TABLE_OWNER}.taux_d_occup_places', float)
            taux_libres = cursor.callfunc(f'{TABLE_OWNER}.taux_places_libres', float)
            revenu_jour = cursor.callfunc(f'{TABLE_OWNER}.revenu_d_jour', float)
            nbr_paiements = cursor.callfunc(f'{TABLE_OWNER}.nbr_paiement_valide', int)
        
        return jsonify({
            'success': True,
            'data': {
                'total_clients': total_clients,
                'total_abonnes': total_abonnes,
                'taux_occupation': round(taux_occupation, 2),
                'taux_places_libres': round(taux_libres, 2),
                'revenu_du_jour': round(revenu_jour, 2),
                'nombre_paiements_valides': nbr_paiements
            }
        })
        
    except oracledb.Error as error:
        logger.error(f"Erreur lors de la récupération des statistiques: {error}")
        return jsonify({
            'success': False,
            'error': str(error)
        }), 500

# =========================
# UPDATE PLACE (ADMIN)
# =========================
@app.route('/api/places/<int:id_place>', methods=['PUT'])
@admin_required
def update_place(id_place):
    data = request.json or {}
    numero_place = data.get("numero_place")
    type_place = data.get("type_place")
    disponible = data.get("disponible")

    # validations simples
    if disponible is not None:
        disponible = str(disponible).upper().strip()
        if disponible not in ("O", "N"):
            return jsonify({"success": False, "error": "disponible doit être 'O' ou 'N'"}), 400

    if type_place is not None:
        type_place = str(type_place).strip()
        if type_place not in ("Standard", "VIP", "Handicape"):
            return jsonify({"success": False, "error": "type_place invalide"}), 400

    with get_db_cursor(commit=True) as cursor:
        cursor.execute(f"SELECT 1 FROM {TABLE_OWNER}.PLACE WHERE id_place=:id", {"id": id_place})
        if not cursor.fetchone():
            return jsonify({"success": False, "error": "Place introuvable"}), 404

        cursor.execute(f"""
            UPDATE {TABLE_OWNER}.PLACE
            SET
              numero_place = COALESCE(:numero_place, numero_place),
              type_place   = COALESCE(:type_place, type_place),
              disponible   = COALESCE(:disponible, disponible)
            WHERE id_place = :id
        """, {"numero_place": numero_place, "type_place": type_place, "disponible": disponible, "id": id_place})

    return jsonify({"success": True, "message": "Place mise à jour"}), 200




# ========================================================
# ROUTE DE TEST
# ========================================================
@app.route('/test-connexion', methods=['GET'])
def test_connexion():
    """Tester la connexion à la base de données"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT 'Connexion réussie!' FROM DUAL")
            result = cursor.fetchone()
        
        return jsonify({
            'success': True,
            'message': result[0],
            'status': 'OK'
        })
    except oracledb.Error as error:
        logger.error(f"Erreur de connexion: {error}")
        return jsonify({
            'success': False,
            'error': str(error),
            'status': 'FAILED'
        }), 500

# ========================================================
# GESTION DES ERREURS GLOBALES
# ========================================================
@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'error': f'Endpoint non trouvé: {request.method} {request.path}'
    }), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Erreur interne: {error}")
    return jsonify({
        'success': False,
        'error': 'Erreur interne du serveur'
    }), 500
#ROUTE POUR SUPPRIMER UN CLIENT
@app.route('/client/delete/<int:id_client>', methods=['DELETE'])
@login_required
def delete_client(id_client):
    """Supprimer un client"""
    try:
        with get_db_cursor(commit=True) as cursor:
            # Vérifier d'abord si le client existe
            cursor.execute(f"""
                SELECT id_client FROM {TABLE_OWNER}.CLIENT 
                WHERE id_client = :id
            """, {'id': id_client})
            
            if not cursor.fetchone():
                return jsonify({
                    'success': False,
                    'error': f'Client avec ID {id_client} non trouvé.'
                }), 404
            
            # Vérifier si le client a des réservations en cours
            cursor.execute(f"""
                SELECT COUNT(*) FROM {TABLE_OWNER}.RESERVATION 
                WHERE id_client = :id AND date_sortie IS NULL
            """, {'id': id_client})
            
            reservations_actives = cursor.fetchone()[0]
            if reservations_actives > 0:
                return jsonify({
                    'success': False,
                    'error': 'Impossible de supprimer ce client : il a des réservations en cours.'
                }), 400
            
            # Supprimer le client (cascade gérée par Oracle)
            cursor.execute(f"""
                DELETE FROM {TABLE_OWNER}.CLIENT 
                WHERE id_client = :id
            """, {'id': id_client})
            
            rows_deleted = cursor.rowcount
            
            if rows_deleted == 0:
                return jsonify({
                    'success': False,
                    'error': 'Erreur lors de la suppression.'
                }), 500
            
            logger.info(f"Client {id_client} supprimé avec succès")
            return jsonify({
                'success': True,
                'message': f'Client supprimé avec succès.',
                'id_client': id_client
            }), 200
            
    except oracledb.Error as e:
        error_code = e.args[0].code if e.args else None
        logger.error(f"OracleError (code: {error_code}): {e}")
        
        if error_code == 2292:  # Violation de contrainte de clé étrangère
            return jsonify({
                'success': False,
                'error': 'Impossible de supprimer ce client car il est référencé dans d\'autres tables.'
            }), 400
        else:
            return jsonify({
                'success': False,
                'error': f'Erreur Oracle: {str(e)}'
            }), 500
            
    except Exception as e:
        logger.error(f"Erreur lors de la suppression du client: {e}")
        return jsonify({
            'success': False,
            'error': f'Erreur interne: {str(e)}'
        }), 500
    
#ROUTE POUR RÉCUPÉRER LES INFOS D'UN CLIENT
@app.route('/client/<int:id_client>', methods=['GET'])
@login_required
def get_client(id_client):
    """Récupérer les informations d'un client spécifique"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(f"""
                SELECT id_client, nom, prenom, telephone, pmr
                FROM {TABLE_OWNER}.CLIENT 
                WHERE id_client = :id
            """, {'id': id_client})
            
            client = cursor.fetchone()
            
            if not client:
                return jsonify({
                    'success': False,
                    'error': f'Client avec ID {id_client} non trouvé.'
                }), 404
            
            # Convertir en dictionnaire
            columns = [col[0] for col in cursor.description]
            client_dict = dict(zip(columns, client))
            
            return jsonify({
                'success': True,
                'data': client_dict
            })
            
    except oracledb.Error as error:
        logger.error(f"Erreur lors de la récupération du client: {error}")
        return jsonify({
            'success': False,
            'error': str(error)
        }), 500
#ROUTE POUR UPDATE TARIF


#ROUTE POUR METTRE À JOUR UN CLIENT
@app.route('/client/update/<int:id_client>', methods=['PUT'])
@login_required
def update_client(id_client):
    """Mettre à jour un client existant"""
    try:
        data = request.json
        
        # Log des données reçues
        logger.info(f"Mise à jour client {id_client}: {data}")
        
        nom = data.get('nom', '').strip()
        prenom = data.get('prenom', '').strip()
        telephone = data.get('telephone', '').strip()
        pmr = data.get('pmr', 'N')
        
        # Normaliser PMR
        pmr = str(pmr).upper().strip()
        if pmr not in ['O', 'N']:
            pmr = 'N'
        
        # Validation
        if not nom or not prenom:
            return jsonify({
                'success': False,
                'error': 'Nom et prénom obligatoires.'
            }), 400
        
        with get_db_cursor(commit=True) as cursor:
            # Vérifier si le client existe
            cursor.execute(f"""
                SELECT id_client FROM {TABLE_OWNER}.CLIENT 
                WHERE id_client = :id
            """, {'id': id_client})
            
            if not cursor.fetchone():
                return jsonify({
                    'success': False,
                    'error': f'Client avec ID {id_client} non trouvé.'
                }), 404
            
            # Vérifier si le téléphone est déjà utilisé par un autre client
            cursor.execute(f"""
                SELECT id_client FROM {TABLE_OWNER}.CLIENT 
                WHERE telephone = :tel AND id_client != :id
            """, {'tel': telephone, 'id': id_client})
            
            if cursor.fetchone():
                return jsonify({
                    'success': False,
                    'error': 'Ce numéro de téléphone est déjà utilisé par un autre client.'
                }), 400
            
            # Mettre à jour le client
            cursor.execute(f"""
                UPDATE {TABLE_OWNER}.CLIENT 
                SET nom = :nom, 
                    prenom = :prenom, 
                    telephone = :telephone, 
                    pmr = :pmr
                WHERE id_client = :id
            """, {
                'nom': nom,
                'prenom': prenom,
                'telephone': telephone,
                'pmr': pmr,
                'id': id_client
            })
            
            rows_updated = cursor.rowcount
            
            if rows_updated == 0:
                return jsonify({
                    'success': False,
                    'error': 'Aucune modification effectuée.'
                }), 400
            
            # Récupérer le client mis à jour
            cursor.execute(f"""
                SELECT id_client, nom, prenom, telephone, pmr
                FROM {TABLE_OWNER}.CLIENT 
                WHERE id_client = :id
            """, {'id': id_client})
            
            client = cursor.fetchone()
            columns = [col[0] for col in cursor.description]
            client_dict = dict(zip(columns, client))
            
            logger.info(f"Client {id_client} mis à jour avec succès")
            return jsonify({
                'success': True,
                'message': 'Client mis à jour avec succès.',
                'data': client_dict
            }), 200
            
    except oracledb.IntegrityError as e:
        logger.error(f"IntegrityError: {e}")
        return jsonify({
            'success': False,
            'error': 'Téléphone déjà utilisé.'
        }), 400
        
    except oracledb.Error as e:
        error_code = e.args[0].code if e.args else None
        logger.error(f"OracleError (code: {error_code}): {e}")
        return jsonify({
            'success': False,
            'error': f'Erreur Oracle: {str(e)}'
        }), 500
        
    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour du client: {e}")
        return jsonify({
            'success': False,
            'error': f'Erreur interne: {str(e)}'
        }), 500

# ========================================================
# LANCEMENT DE L'APPLICATION
# ========================================================
if __name__ == '__main__':
    print("=" * 60)
    print("API GESTION DE PARKING - DÉMARRAGE")
    print("=" * 60)
    print("📍 URL: http://localhost:5000")
    print("\n📋 Endpoints disponibles:")
    print("  Clients:")
    print("    - GET  /clients")
    print("    - GET  /clients/<id>")
    print("  Places:")
    print("    - GET  /places")
    print("    - GET  /places?type=PMR")
    print("    - GET  /places/disponibles")
    print("  Abonnements:")
    print("    - GET  /abonnements")
    print("    - GET  /abonnements?actif=true")
    print("    - POST /abonner")
    print("  Réservations:")
    print("    - GET  /reservations")
    print("    - GET  /reservations?en_cours=true")
    print("    - POST /entree")
    print("    - POST /sortie")
    print("  Paiements:")
    print("    - GET  /paiements")
    print("  Statistiques:")
    print("    - GET  /statistiques")
    print("  Test:")
    print("    - GET  /test-connexion")
    print("=" * 60)
    app.run(debug=True, port=5000, host='0.0.0.0')