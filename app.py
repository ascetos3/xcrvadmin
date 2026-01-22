from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from functools import wraps
import os
import sys
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from database import Database
from helpers import *
import secrets

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', secrets.token_hex(32))
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 MB max upload size

# Log startup info
logger.info("=" * 60)
logger.info("Xcrover Admin Panel Starting...")
logger.info(f"Python version: {sys.version}")
logger.info(f"SECRET_KEY set: {'Yes' if os.getenv('SECRET_KEY') else 'No (using random)'}")
logger.info(f"MONGODB_URI set: {'Yes' if os.getenv('MONGODB_URI') else 'No'}")
logger.info(f"USE_MONGODB_DRIVER: {os.getenv('USE_MONGODB_DRIVER', 'Not set')}")
logger.info("=" * 60)

# Check static CSS availability and size (useful on Render)
try:
    static_css_path = os.path.join(os.path.dirname(__file__), 'static', 'css', 'style.css')
    if os.path.exists(static_css_path):
        size = os.path.getsize(static_css_path)
        if size == 0:
            logger.warning("static/css/style.css exists but is EMPTY (0 bytes). UI will look broken. Ensure this file is committed in your deployed repo.")
        else:
            logger.info(f"static/css/style.css loaded ({size} bytes)")
    else:
        logger.warning("static/css/style.css not found. UI styles won't load.")
except Exception as e:
    logger.warning(f"Unable to inspect static/css/style.css: {e}")

def get_db():
    if not hasattr(get_db, 'instance'):
        try:
            logger.info("Initializing Database connection...")
            get_db.instance = Database()
            logger.info("Database connection successful!")
        except Exception as e:
            logger.error(f"Database connection failed: {str(e)}")
            raise
    return get_db.instance

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    return redirect(url_for('dashboard') if session.get('admin_logged_in') else url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if username == 'admin' and password == 'admin123':
            session['admin_logged_in'] = True
            session['admin_username'] = username
            session.permanent = True
            flash('Giris basarili!', 'success')
            return redirect(url_for('dashboard'))
        flash('Hatali kullanici adi veya sifre!', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Cikis yapildi.', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    stats = {
        'total_licenses': db.count('licenses'),
        'active_licenses': db.count('licenses', {'isActive': True}),
        'expired_licenses': 0,  # TODO: Calculate expired
        'total_games': db.count('premium_games') + db.count('denuvo_games'),
        'premium_games': db.count('premium_games'),
        'denuvo_games': db.count('denuvo_games'),
        'open_tickets': db.count('support_tickets', {'status': 'open'}),
        'closed_tickets': db.count('support_tickets', {'status': 'closed'}),
        'total_resellers': db.count('resellers')
    }
    recent_licenses = db.find('licenses', {}, {'sort': {'createdAt': -1}, 'limit': 5})
    recent_tickets = db.find('support_tickets', {}, {'sort': {'createdAt': -1}, 'limit': 5})
    return render_template('dashboard.html', 
                         admin_username=session.get('admin_username'),
                         stats=stats,
                         recent_licenses=recent_licenses,
                         recent_tickets=recent_tickets)

# ==================== LICENSES ====================
@app.route('/licenses')
@login_required
def licenses():
    db = get_db()
    licenses_list = db.find('licenses', {}, {'sort': {'createdAt': -1}})
    return render_template('licenses.html', 
                         admin_username=session.get('admin_username'),
                         licenses=licenses_list)

@app.route('/licenses/add', methods=['POST'])
@login_required
def add_license():
    db = get_db()
    try:
        key = request.form.get('licenseKey', '').strip().upper()
        if not key:
            key = generate_license_key()  # 24 karakter
        
        # Check if exists
        existing = db.find_one('licenses', {'$or': [{'licenseKey': key}, {'key': key}]})
        if existing:
            return jsonify({'success': False, 'message': 'Bu lisans zaten mevcut'}), 400
        
        username = request.form.get('username', '').strip()
        license_type = request.form.get('type', 'basic').strip()
        expires_days = request.form.get('expiresDays', '')
        
        expires_at = None
        if expires_days and expires_days.isdigit() and int(expires_days) > 0:
            expires_at = datetime.utcnow() + timedelta(days=int(expires_days))
        
        license_data = {
            'licenseKey': key,
            'key': key,
            'username': username or None,
            'type': license_type,
            'isActive': True,
            'usageCount': 0,
            'maxUsage': -1,
            'createdAt': datetime.utcnow(),
            'createdBy': session.get('admin_username', 'admin'),
            'lastModifiedAt': datetime.utcnow(),
            'lastModifiedBy': session.get('admin_username', 'admin'),
            'expiresAt': expires_at,
            'notes': request.form.get('notes', '').strip() or None,
            'hwid': None,
            'lastUsed': None,
            'hasDenuvoAccess': license_type == 'premium'
        }
        
        db.insert('licenses', license_data)
        return jsonify({'success': True, 'message': 'Lisans basariyla eklendi', 'licenseKey': key})
    except Exception as e:
        print(f"License add error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/licenses/edit/<license_key>', methods=['POST'])
@login_required
def edit_license(license_key):
    db = get_db()
    try:
        max_usage = request.form.get('maxUsage', '-1')
        expires_days = request.form.get('expiresDays', '')
        
        expires_at = None
        if expires_days and expires_days.isdigit():
            expires_at = datetime.utcnow() + timedelta(days=int(expires_days))
        
        update_data = {
            'maxUsage': int(max_usage) if max_usage.lstrip('-').isdigit() else -1,
            'resellerId': request.form.get('resellerId', '').strip() or None,
            'expiresAt': expires_at,
            'notes': request.form.get('notes', '').strip(),
            'lastModifiedAt': datetime.utcnow(),
            'lastModifiedBy': session.get('admin_username')
        }
        
        updated = db.update('licenses', {'licenseKey': license_key}, update_data)
        if not updated:
            updated = db.update('licenses', {'key': license_key}, update_data)
        
        if updated:
            return jsonify({'success': True, 'message': 'Lisans guncellendi'})
        return jsonify({'success': False, 'message': 'Lisans bulunamadi'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/support/debug_status/<ticket_id>')
@login_required
def support_debug_status(ticket_id):
    """Return raw vs normalized status for a ticket to diagnose legacy values."""
    db = get_db()
    try:
        from bson import ObjectId
        ticket = db.find_one('support_tickets', {'_id': ObjectId(ticket_id)})
        if not ticket:
            return jsonify({'success': False, 'message': 'Destek talebi bulunamadi'}), 404
        raw_status = ticket.get('status')
        ser = serialize_doc(ticket)
        norm_status = ser.get('status')
        return jsonify({'success': True, 'raw_status': raw_status, 'normalized_status': norm_status})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500
@app.route('/licenses/toggle/<license_key>', methods=['POST'])
@login_required
def toggle_license(license_key):
    db = get_db()
    try:
        license_doc = db.find_one('licenses', {'licenseKey': license_key})
        if not license_doc:
            license_doc = db.find_one('licenses', {'key': license_key})
        
        if not license_doc:
            return jsonify({'success': False, 'message': 'Lisans bulunamadi'}), 404
        
        current = boolval_safe(doc_get(license_doc, 'isActive', True))
        new_status = not current
        
        update_data = {
            'isActive': new_status,
            'lastModifiedAt': datetime.utcnow(),
            'lastModifiedBy': session.get('admin_username')
        }
        
        db.update('licenses', {'licenseKey': license_key}, update_data)
        return jsonify({'success': True, 'newStatus': new_status})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/licenses/delete/<license_key>', methods=['POST'])
@login_required
def delete_license(license_key):
    db = get_db()
    try:
        deleted = db.delete('licenses', {'licenseKey': license_key})
        if not deleted:
            deleted = db.delete('licenses', {'key': license_key})
        
        if deleted:
            return jsonify({'success': True, 'message': 'Lisans silindi'})
        return jsonify({'success': False, 'message': 'Lisans bulunamadi'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/licenses/detail/<license_key>')
@login_required
def license_detail(license_key):
    db = get_db()
    try:
        license_doc = db.find_one('licenses', {'licenseKey': license_key})
        if not license_doc:
            license_doc = db.find_one('licenses', {'key': license_key})
        
        if not license_doc:
            return jsonify({'success': False, 'message': 'Lisans bulunamadi'}), 404
        
        # Serialize MongoDB document to JSON
        from helpers import serialize_doc
        serialized = serialize_doc(license_doc)
        
        return jsonify({'success': True, 'license': serialized})
    except Exception as e:
        print(f"Detail error: {e}")
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/licenses/add-time/<license_key>', methods=['POST'])
@login_required
def add_time_license(license_key):
    db = get_db()
    try:
        data = request.get_json()
        days = int(data.get('days', 0))
        
        if days <= 0:
            return jsonify({'success': False, 'message': 'Gecersiz gun sayisi'}), 400
        
        license_doc = db.find_one('licenses', {'licenseKey': license_key})
        if not license_doc:
            license_doc = db.find_one('licenses', {'key': license_key})
        
        if not license_doc:
            return jsonify({'success': False, 'message': 'Lisans bulunamadi'}), 404
        
        current_expires = doc_get(license_doc, 'expiresAt')
        if current_expires:
            new_expires = to_ts(current_expires) + timedelta(days=days)
        else:
            new_expires = datetime.utcnow() + timedelta(days=days)
        
        db.update('licenses', {'licenseKey': license_key}, {'expiresAt': new_expires})
        return jsonify({'success': True, 'message': f'{days} gun eklendi', 'newExpires': new_expires.isoformat()})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/licenses/reset-hwid/<license_key>', methods=['POST'])
@login_required
def reset_hwid_license(license_key):
    db = get_db()
    try:
        license_doc = db.find_one('licenses', {'licenseKey': license_key})
        if not license_doc:
            license_doc = db.find_one('licenses', {'key': license_key})
        
        if not license_doc:
            return jsonify({'success': False, 'message': 'Lisans bulunamadi'}), 404
        
        db.update('licenses', {'licenseKey': license_key}, {
            'hwid': None,
            'hwidRegisteredAt': None,
            'hwidChangeCount': 0
        })
        return jsonify({'success': True, 'message': 'HWID sifirlandi'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/licenses/toggle-denuvo/<license_key>', methods=['POST'])
@login_required
def toggle_denuvo_license(license_key):
    db = get_db()
    try:
        data = request.get_json()
        enabled = bool(data.get('enabled', False))
        
        license_doc = db.find_one('licenses', {'licenseKey': license_key})
        if not license_doc:
            license_doc = db.find_one('licenses', {'key': license_key})
        
        if not license_doc:
            return jsonify({'success': False, 'message': 'Lisans bulunamadi'}), 404
        
        db.update('licenses', {'licenseKey': license_key}, {'denuvoEnabled': enabled})
        return jsonify({'success': True, 'message': f'Denuvo {"aktif" if enabled else "pasif"}'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/licenses/destroy/<license_key>', methods=['POST'])
@login_required
def destroy_license(license_key):
    db = get_db()
    try:
        license_doc = db.find_one('licenses', {'licenseKey': license_key})
        if not license_doc:
            license_doc = db.find_one('licenses', {'key': license_key})
        
        if not license_doc:
            return jsonify({'success': False, 'message': 'Lisans bulunamadi'}), 404
        
        if doc_get(license_doc, 'isDestroyed', False):
            return jsonify({'success': False, 'message': 'Lisans zaten imha edilmis'}), 400
        
        db.update('licenses', {'licenseKey': license_key}, {
            'isDestroyed': True,
            'destroyedAt': datetime.utcnow(),
            'destroyedBy': session.get('admin_username'),
            'isActive': False
        })
        return jsonify({'success': True, 'message': 'Lisans imha edildi'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/licenses/view/<license_key>')
@login_required
def view_license(license_key):
    db = get_db()
    license_doc = db.find_one('licenses', {'licenseKey': license_key})
    if not license_doc:
        license_doc = db.find_one('licenses', {'key': license_key})
    
    if not license_doc:
        flash('Lisans bulunamadi', 'error')
        return redirect(url_for('licenses'))
    
    return render_template('license_detail.html',
                         admin_username=session.get('admin_username'),
                         license=license_doc)

# ==================== GAMES ====================
@app.route('/games')
@login_required
def games():
    db = get_db()
    premium = list(db.find('premium_games', {}, {'sort': {'name': 1}}))
    denuvo = list(db.find('denuvo_games', {}, {'sort': {'name': 1}}))
    return render_template('games.html',
                         admin_username=session.get('admin_username'),
                         premium_games=premium,
                         denuvo_games=denuvo)

@app.route('/games/add', methods=['POST'])
@login_required
def add_game():
    db = get_db()
    try:
        name = request.form.get('name', '').strip()
        app_id = request.form.get('appId', '').strip()
        
        if not name or not app_id:
            return jsonify({'success': False, 'message': 'Oyun adi ve App ID gerekli'}), 400
        
        game_type = request.form.get('gameType', 'premium')
        collection = 'premium_games' if game_type == 'premium' else 'denuvo_games'
        
        # Check if exists
        existing = db.find_one(collection, {'appId': app_id})
        if existing:
            return jsonify({'success': False, 'message': 'Bu oyun zaten mevcut'}), 400
        
        game_data = {
            'name': name,
            'appId': app_id,
            'imageUrl': request.form.get('imageUrl', '').strip(),
            'description': request.form.get('description', '').strip(),
            'addedAt': datetime.utcnow(),
            'addedBy': session.get('admin_username')
        }
        
        db.insert(collection, game_data)
        return jsonify({'success': True, 'message': 'Oyun basariyla eklendi'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/games/edit/<game_type>/<app_id>', methods=['POST'])
@login_required
def edit_game(game_type, app_id):
    db = get_db()
    try:
        collection = 'premium_games' if game_type == 'premium' else 'denuvo_games'
        
        update_data = {
            'name': request.form.get('name', '').strip(),
            'imageUrl': request.form.get('imageUrl', '').strip(),
            'description': request.form.get('description', '').strip()
        }
        
        updated = db.update(collection, {'appId': app_id}, update_data)
        
        if updated:
            return jsonify({'success': True, 'message': 'Oyun guncellendi'})
        return jsonify({'success': False, 'message': 'Oyun bulunamadi'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/games/delete/<game_type>/<app_id>', methods=['POST'])
@login_required
def delete_game(game_type, app_id):
    db = get_db()
    try:
        collection = 'premium_games' if game_type == 'premium' else 'denuvo_games'
        deleted = db.delete(collection, {'appId': app_id})
        
        if deleted:
            return jsonify({'success': True, 'message': 'Oyun silindi'})
        return jsonify({'success': False, 'message': 'Oyun bulunamadi'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

# ==================== SUPPORT (NEW) ====================

## Removed duplicate support reply/close routes (unified at the bottom)

# ==================== RESELLERS ====================
@app.route('/resellers')
@login_required
def resellers():
    db = get_db()
    resellers_list = list(db.find('resellers', {}, {'sort': {'createdAt': -1}}))
    
    # Calculate license count for each reseller
    for reseller in resellers_list:
        reseller_id = doc_get(reseller, 'resellerId', '')
        if reseller_id:
            reseller['licenseCount'] = db.count('licenses', {'resellerId': reseller_id})
            reseller['activeLicenseCount'] = db.count('licenses', {'resellerId': reseller_id, 'isActive': True})
    
    return render_template('resellers.html',
                         admin_username=session.get('admin_username'),
                         resellers=resellers_list)

@app.route('/resellers/add', methods=['POST'])
@login_required
def add_reseller():
    db = get_db()
    try:
        reseller_id = request.form.get('resellerId', '').strip()
        name = request.form.get('name', '').strip()
        
        if not reseller_id or not name:
            return jsonify({'success': False, 'message': 'Bayi ID ve isim gerekli'}), 400
        
        existing = db.find_one('resellers', {'resellerId': reseller_id})
        if existing:
            return jsonify({'success': False, 'message': 'Bu bayi ID zaten mevcut'}), 400
        
        reseller_data = {
            'resellerId': reseller_id,
            'name': name,
            'email': request.form.get('email', '').strip(),
            'phone': request.form.get('phone', '').strip(),
            'isActive': True,
            'createdAt': datetime.utcnow(),
            'createdBy': session.get('admin_username')
        }
        
        db.insert('resellers', reseller_data)
        return jsonify({'success': True, 'message': 'Bayi basariyla eklendi'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/premium-games')
@login_required
def premium_games():
    db = get_db()
    games = list(db.find('premium_games', {}))
    return render_template('premium_games.html', 
                         admin_username=session.get('admin_username'),
                         games=games)

@app.route('/premium-games/add', methods=['POST'])
@login_required
def add_premium_game():
    db = get_db()
    try:
        game_id = request.form.get('gameId', '').strip()
        game_name = request.form.get('gameName', '').strip()
        
        if not game_id or not game_name:
            return jsonify({'success': False, 'message': 'Oyun ID ve isim gerekli'}), 400
        
        existing = db.find_one('premium_games', {'gameId': game_id})
        if existing:
            return jsonify({'success': False, 'message': 'Bu oyun zaten mevcut'}), 400
        
        game_data = {
            'gameId': game_id,
            'gameName': game_name,
            'addedAt': datetime.utcnow(),
            'addedBy': session.get('admin_username')
        }
        
        db.insert('premium_games', game_data)
        return jsonify({'success': True, 'message': 'Oyun eklendi'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/premium-games/delete/<game_id>', methods=['POST'])
@login_required
def delete_premium_game(game_id):
    db = get_db()
    try:
        result = db.delete('premium_games', {'gameId': game_id})
        if result.deleted_count > 0:
            return jsonify({'success': True, 'message': 'Oyun silindi'})
        return jsonify({'success': False, 'message': 'Oyun bulunamadi'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/denuvo-games')
@login_required
def denuvo_games():
    db = get_db()
    games = list(db.find('denuvo_games', {}))
    return render_template('denuvo_games.html', 
                         admin_username=session.get('admin_username'),
                         games=games)

@app.route('/denuvo-games/add', methods=['POST'])
@login_required
def add_denuvo_game():
    db = get_db()
    try:
        game_id = request.form.get('gameId', '').strip()
        game_name = request.form.get('gameName', '').strip()
        
        if not game_id or not game_name:
            return jsonify({'success': False, 'message': 'Oyun ID ve isim gerekli'}), 400
        
        existing = db.find_one('denuvo_games', {'gameId': game_id})
        if existing:
            return jsonify({'success': False, 'message': 'Bu oyun zaten mevcut'}), 400
        
        game_data = {
            'gameId': game_id,
            'gameName': game_name,
            'addedAt': datetime.utcnow(),
            'addedBy': session.get('admin_username')
        }
        
        db.insert('denuvo_games', game_data)
        return jsonify({'success': True, 'message': 'Denuvo oyunu eklendi'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/denuvo-games/delete/<game_id>', methods=['POST'])
@login_required
def delete_denuvo_game(game_id):
    db = get_db()
    try:
        result = db.delete('denuvo_games', {'gameId': game_id})
        if result.deleted_count > 0:
            return jsonify({'success': True, 'message': 'Denuvo oyunu silindi'})
        return jsonify({'success': False, 'message': 'Oyun bulunamadi'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/manual-games')
@login_required
def manual_games():
    db = get_db()
    games = list(db.find('manual_games', {}))
    return render_template('manual_games.html', 
                         admin_username=session.get('admin_username'),
                         games=games)

@app.route('/manual-games/add', methods=['POST'])
@login_required
def add_manual_game():
    db = get_db()
    try:
        app_id = request.form.get('appId', '').strip()
        game_name = request.form.get('gameName', '').strip()
        
        if not app_id or not game_name:
            return jsonify({'success': False, 'message': 'Oyun ID ve isim gerekli'}), 400
        
        # Check if file exists
        if 'gameFile' not in request.files:
            return jsonify({'success': False, 'message': 'ZIP dosyasi gerekli'}), 400
        
        file = request.files['gameFile']
        if file.filename == '':
            return jsonify({'success': False, 'message': 'Dosya secilmedi'}), 400
        
        if not file.filename.endswith('.zip'):
            return jsonify({'success': False, 'message': 'Sadece ZIP dosyalari yuklenebilir'}), 400
        
        # Check if game already exists
        existing = db.find_one('manual_games', {'appId': app_id})
        if existing:
            return jsonify({'success': False, 'message': 'Bu oyun ID zaten mevcut'}), 400
        
        # Check if MongoDB driver mode is active
        if not db.db:
            return jsonify({'success': False, 'message': 'MongoDB baglantisi yok. GridFS kullanilamaz.'}), 500
        
        # Save file to GridFS with bucket name 'manualGames'
        from gridfs import GridFSBucket
        bucket = GridFSBucket(db.db, bucket_name='manualGames')
        
        file_content = file.read()
        file_size = len(file_content)
        
        print(f"[ManualGame] Uploading: appId={app_id}, name={game_name}, size={file_size} bytes")
        
        file_id = bucket.upload_from_stream(
            file.filename,
            file_content,
            metadata={
                'content_type': 'application/zip',
                'appId': app_id,
                'gameName': game_name
            }
        )
        
        game_data = {
            'appId': app_id,
            'gameName': game_name,
            'fileId': file_id,
            'fileName': file.filename,
            'fileSize': file_size,
            'addedAt': datetime.utcnow(),
            'addedBy': session.get('admin_username')
        }
        
        db.insert('manual_games', game_data)
        return jsonify({'success': True, 'message': 'Manuel oyun yuklendi'})
    except Exception as e:
        print(f"Manual game add error: {e}")
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/manual-games/delete/<app_id>', methods=['POST'])
@login_required
def delete_manual_game(app_id):
    db = get_db()
    try:
        # Find game first to get fileId
        game = db.find_one('manual_games', {'appId': app_id})
        if not game:
            return jsonify({'success': False, 'message': 'Oyun bulunamadi'}), 404
        
        # Delete file from GridFS if exists
        if 'fileId' in game and db.db:
            try:
                from gridfs import GridFSBucket
                bucket = GridFSBucket(db.db, bucket_name='manualGames')
                bucket.delete(game['fileId'])
            except Exception as e:
                print(f"GridFS delete error: {e}")
        
        # Delete game record
        result = db.delete('manual_games', {'appId': app_id})
        if result.deleted_count > 0:
            return jsonify({'success': True, 'message': 'Manuel oyun silindi'})
        return jsonify({'success': False, 'message': 'Oyun silinemedi'}), 500
    except Exception as e:
        print(f"Delete manual game error: {e}")
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/manual-games/download/<app_id>')
@login_required
def download_manual_game(app_id):
    db = get_db()
    try:
        game = db.find_one('manual_games', {'appId': app_id})
        if not game or 'fileId' not in game:
            return jsonify({'success': False, 'message': 'Oyun bulunamadi'}), 404
        
        if not db.db:
            return jsonify({'success': False, 'message': 'MongoDB baglantisi yok'}), 500
        
        from gridfs import GridFSBucket
        from flask import send_file
        import io
        
        bucket = GridFSBucket(db.db, bucket_name='manualGames')
        stream = io.BytesIO()
        bucket.download_to_stream(game['fileId'], stream)
        stream.seek(0)
        
        return send_file(
            stream,
            mimetype='application/zip',
            as_attachment=True,
            download_name=game['fileName']
        )
    except Exception as e:
        print(f"Download manual game error: {e}")
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/bypass-games')
@login_required
def bypass_games():
    db = get_db()
    packages = list(db.find('bypass_packages', {}))
    return render_template('bypass_games.html', 
                         admin_username=session.get('admin_username'),
                         packages=packages)

@app.route('/bypass-games/add', methods=['POST'])
@login_required
def add_bypass_package():
    db = get_db()
    try:
        package_name = request.form.get('packageName', '').strip()
        target_path = request.form.get('targetPath', '').strip()
        
        if not package_name or not target_path:
            return jsonify({'success': False, 'message': 'Paket adı ve hedef yol gerekli'}), 400
        
        # Check if file exists
        if 'bypassFile' not in request.files:
            return jsonify({'success': False, 'message': 'Dosya gerekli'}), 400
        
        file = request.files['bypassFile']
        if file.filename == '':
            return jsonify({'success': False, 'message': 'Dosya seçilmedi'}), 400
        
        if not file.filename.endswith(('.zip', '.rar')):
            return jsonify({'success': False, 'message': 'Sadece ZIP veya RAR dosyaları yüklenebilir'}), 400
        
        # Check if MongoDB driver mode is active
        if not db.db:
            return jsonify({'success': False, 'message': 'MongoDB baglantisi yok. GridFS kullanilamaz.'}), 500
        
        # Save file to GridFS with bucket name 'bypassFiles'
        from gridfs import GridFSBucket
        from bson import ObjectId
        
        bucket = GridFSBucket(db.db, bucket_name='bypassFiles')
        
        file_content = file.read()
        file_size = len(file_content)
        
        print(f"[BypassPackage] Uploading: name={package_name}, size={file_size} bytes")
        
        file_id = bucket.upload_from_stream(
            file.filename,
            file_content,
            metadata={
                'name': package_name,
                'targetPath': target_path,
                'fileSize': file_size
            }
        )
        
        package_data = {
            'name': package_name,
            'targetPath': target_path,
            'gridFsId': file_id,
            'fileId': file_id,  # Ana uygulama fileId kullanıyor
            'fileName': file.filename,
            'fileSize': file_size,
            'createdAt': datetime.utcnow(),
            'uploadedBy': session.get('admin_username')
        }
        
        db.insert('bypass_packages', package_data)
        return jsonify({'success': True, 'message': 'Bypass paketi eklendi'})
    except Exception as e:
        print(f"Bypass package add error: {e}")
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/bypass-games/delete/<package_id>', methods=['POST'])
@login_required
def delete_bypass_package(package_id):
    db = get_db()
    try:
        from bson import ObjectId
        from gridfs import GridFSBucket
        
        # Find package first to get gridFsId
        package = db.find_one('bypass_packages', {'_id': ObjectId(package_id)})
        if not package:
            return jsonify({'success': False, 'message': 'Paket bulunamadi'}), 404
        
        # Delete file from GridFS if exists
        grid_fs_id = package.get('gridFsId') or package.get('fileId')
        if grid_fs_id and db.db:
            try:
                bucket = GridFSBucket(db.db, bucket_name='bypassFiles')
                bucket.delete(grid_fs_id)
            except Exception as e:
                print(f"GridFS delete error: {e}")
        
        result = db.delete('bypass_packages', {'_id': ObjectId(package_id)})
        if result.deleted_count > 0:
            return jsonify({'success': True, 'message': 'Bypass paketi silindi'})
        return jsonify({'success': False, 'message': 'Paket silinemedi'}), 500
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/announcements')
@login_required
def announcements():
    db = get_db()
    announcements_list = list(db.find('announcements', {}))
    return render_template('announcements.html', 
                         admin_username=session.get('admin_username'),
                         announcements=announcements_list)

@app.route('/announcements/add', methods=['POST'])
@login_required
def add_announcement():
    db = get_db()
    try:
        data = request.get_json()
        title = data.get('title', '').strip()
        body = data.get('body', '').strip()
        
        if not title or not body:
            return jsonify({'success': False, 'message': 'Baslik ve icerik gerekli'}), 400
        
        announcement_data = {
            'title': title,
            'body': body,
            'imageUrl': data.get('imageUrl', '').strip() or None,
            'isActive': data.get('isActive', True),
            'createdAt': datetime.utcnow(),
            'createdBy': session.get('admin_username')
        }
        
        db.insert('announcements', announcement_data)
        return jsonify({'success': True, 'message': 'Duyuru olusturuldu'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/announcements/toggle/<announcement_id>', methods=['POST'])
@login_required
def toggle_announcement(announcement_id):
    db = get_db()
    try:
        from bson import ObjectId
        print(f"[Toggle Announcement] ID received: {announcement_id}")
        
        announcement = db.find_one('announcements', {'_id': ObjectId(announcement_id)})
        if not announcement:
            print(f"[Toggle Announcement] Not found: {announcement_id}")
            return jsonify({'success': False, 'message': 'Duyuru bulunamadi'}), 404
        
        current_status = announcement.get('isActive', False)
        new_status = not current_status
        print(f"[Toggle Announcement] Current: {current_status}, New: {new_status}")
        
        update_result = db.update('announcements', {'_id': ObjectId(announcement_id)}, {'$set': {'isActive': new_status}})
        print(f"[Toggle Announcement] Update result: {update_result.modified_count} modified")
        
        return jsonify({'success': True, 'message': 'Durum guncellendi', 'newStatus': new_status})
    except Exception as e:
        print(f"[Toggle Announcement] Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/announcements/delete/<announcement_id>', methods=['POST'])
@login_required
def delete_announcement(announcement_id):
    db = get_db()
    try:
        from bson import ObjectId
        result = db.delete('announcements', {'_id': ObjectId(announcement_id)})
        if result.deleted_count > 0:
            return jsonify({'success': True, 'message': 'Duyuru silindi'})
        return jsonify({'success': False, 'message': 'Duyuru bulunamadi'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/updates')
@login_required
def updates():
    db = get_db()
    updates_list = list(db.find('updates', {}))
    return render_template('updates.html', 
                         admin_username=session.get('admin_username'),
                         updates=updates_list)

@app.route('/updates/add', methods=['POST'])
@login_required
def add_update():
    db = get_db()
    try:
        data = request.get_json()
        version = data.get('version', '').strip()
        download_url = data.get('downloadUrl', '').strip()
        
        if not version or not download_url:
            return jsonify({'success': False, 'message': 'Versiyon ve indirme linki gerekli'}), 400
        
        update_data = {
            'version': version,
            'downloadUrl': download_url,
            'changelog': data.get('changelog', '').strip(),
            'isMandatory': data.get('isMandatory', False),
            'createdAt': datetime.utcnow(),
            'createdBy': session.get('admin_username')
        }
        
        db.insert('updates', update_data)
        return jsonify({'success': True, 'message': 'Guncelleme eklendi'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/updates/delete/<update_id>', methods=['POST'])
@login_required
def delete_update(update_id):
    db = get_db()
    try:
        from bson import ObjectId
        result = db.delete('updates', {'_id': ObjectId(update_id)})
        if result.deleted_count > 0:
            return jsonify({'success': True, 'message': 'Guncelleme silindi'})
        return jsonify({'success': False, 'message': 'Guncelleme bulunamadi'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/support')
@login_required
def support_tickets():
    # New SPA-like page; data loads via /api endpoints
    return render_template('support.html', admin_username=session.get('admin_username'))

def _normalize_status(status: str) -> str:
    if status in ('replied', 'open'):
        return 'accepted'
    return status or 'pending'

def _serialize_ticket(ticket: dict) -> dict:
    # use existing serialize_doc for ObjectId/datetime, then fix status
    s = serialize_doc(ticket)
    if s:
        s['status'] = _normalize_status(s.get('status'))
    return s

@app.route('/api/support/tickets')
@login_required
def api_support_list():
    db = get_db()
    status = request.args.get('status')
    q = request.args.get('q', '').strip()
    filter_q = {}
    if status:
        # normalize filter targets
        if status in ('replied', 'open'):
            status = 'accepted'
        filter_q['status'] = {'$in': [status, 'replied', 'open']} if status == 'accepted' else status
    if q:
        filter_q['$or'] = [
            {'subject': {'$regex': q, '$options': 'i'}},
            {'username': {'$regex': q, '$options': 'i'}}
        ]
    tickets = list(db.find('support_tickets', filter_q, {'sort': {'createdAt': -1}}))
    return jsonify({'success': True, 'tickets': [_serialize_ticket(t) for t in tickets]})

@app.route('/api/support/tickets/<ticket_id>')
@login_required
def api_support_detail(ticket_id):
    db = get_db()
    try:
        from bson import ObjectId
        t = db.find_one('support_tickets', {'_id': ObjectId(ticket_id)})
        if not t:
            return jsonify({'success': False, 'message': 'Destek talebi bulunamadi'}), 404
        # persist normalization
        norm = _normalize_status(t.get('status'))
        if norm != t.get('status'):
            db.update('support_tickets', {'_id': ObjectId(ticket_id)}, {'$set': {'status': norm, 'updatedAt': datetime.utcnow()}})
            t['status'] = norm
        return jsonify({'success': True, 'ticket': _serialize_ticket(t)})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/api/support/tickets/<ticket_id>/accept', methods=['POST'])
@login_required
def api_support_accept(ticket_id):
    db = get_db()
    try:
        from bson import ObjectId
        t = db.find_one('support_tickets', {'_id': ObjectId(ticket_id)})
        if not t:
            return jsonify({'success': False, 'message': 'Destek talebi bulunamadi'}), 404
        if _normalize_status(t.get('status')) == 'accepted':
            return jsonify({'success': True, 'message': 'Zaten kabul edildi'})
        db.update('support_tickets', {'_id': ObjectId(ticket_id)}, {'$set': {'status': 'accepted', 'acceptedAt': datetime.utcnow(), 'updatedAt': datetime.utcnow()}})
        return jsonify({'success': True, 'message': 'Talep kabul edildi'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/api/support/tickets/<ticket_id>/reply', methods=['POST'])
@login_required
def api_support_reply(ticket_id):
    db = get_db()
    try:
        from bson import ObjectId
        t = db.find_one('support_tickets', {'_id': ObjectId(ticket_id)})
        if not t:
            return jsonify({'success': False, 'message': 'Destek talebi bulunamadi'}), 404
        
        current_status = _normalize_status(t.get('status'))
        if current_status == 'pending':
            return jsonify({'success': False, 'message': 'Once talebi kabul etmelisiniz'}), 400
        if current_status == 'closed':
            return jsonify({'success': False, 'message': 'Kapalı talebe yanıt verilemez'}), 400
            
        data = request.get_json(silent=True) or {}
        msg = (data.get('message') or '').strip()
        if not msg:
            return jsonify({'success': False, 'message': 'Mesaj gerekli'}), 400
        
        new_msg = {'sender': 'admin', 'message': msg, 'timestamp': datetime.utcnow()}
        # Yanıt gönderince status 'accepted' olarak kalır, otomatik kapatma YOK
        db.update('support_tickets', {'_id': ObjectId(ticket_id)}, {
            '$push': {'messages': new_msg}, 
            '$set': {'updatedAt': datetime.utcnow(), 'lastReplyAt': datetime.utcnow(), 'lastReplyBy': 'admin'}
        })
        return jsonify({'success': True, 'message': 'Yanıt gönderildi'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/api/support/tickets/<ticket_id>/close', methods=['POST'])
@login_required
def api_support_close(ticket_id):
    db = get_db()
    try:
        from bson import ObjectId
        t = db.find_one('support_tickets', {'_id': ObjectId(ticket_id)})
        if not t:
            return jsonify({'success': False, 'message': 'Destek talebi bulunamadi'}), 404
        db.update('support_tickets', {'_id': ObjectId(ticket_id)}, {'$set': {'status': 'closed', 'closedAt': datetime.utcnow(), 'updatedAt': datetime.utcnow()}})
        return jsonify({'success': True, 'message': 'Talep kapatildi'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.template_filter('format_datetime')
def format_datetime_filter(value, fmt='%d.%m.%Y %H:%M'):
    return format_date(value, fmt)

@app.template_filter('status_badge')
def status_badge_filter(status):
    return get_status_badge(status)

# ===================== VERSION MANAGEMENT =====================

@app.route('/admin/version', methods=['GET', 'POST'])
@login_required
def admin_version():
    db = get_db()
    if request.method == 'POST':
        new_version = request.form.get('version', '').strip()
        if not new_version:
            flash('Sürüm numarası gerekli!', 'error')
        else:
            db.update('app_config', {'key': 'active_version'}, 
                     {'$set': {'key': 'active_version', 'value': new_version, 'updatedAt': datetime.utcnow()}},
                     upsert=True)
            flash(f'Aktif sürüm {new_version} olarak güncellendi!', 'success')
        return redirect(url_for('admin_version'))
    
    # GET: load current version
    config = db.find_one('app_config', {'key': 'active_version'}) or {}
    current_version = config.get('value', '0.0.0')
    return render_template('version.html', 
                         admin_username=session.get('admin_username'),
                         current_version=current_version)

@app.route('/api/version')
def api_version():
    """Public endpoint for client apps to check required version"""
    db = get_db()
    config = db.find_one('app_config', {'key': 'active_version'}) or {}
    version = config.get('value', '0.0.0')
    return jsonify({'success': True, 'version': version})

# ===================== LOGS MANAGEMENT =====================

@app.route('/logs')
@login_required
def logs():
    """Logs page - displays system activity logs"""
    return render_template('logs.html', 
                         admin_username=session.get('admin_username'))

@app.route('/api/logs', methods=['GET'])
@login_required
def api_logs():
    """API endpoint to fetch logs with filtering and pagination"""
    db = get_db()
    try:
        # Get query parameters
        log_type = request.args.get('type', '').strip()
        username = request.args.get('user', '').strip()
        date_from = request.args.get('dateFrom', '').strip()
        date_to = request.args.get('dateTo', '').strip()
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 50))
        
        # Build filter query
        filter_query = {}
        
        if log_type:
            filter_query['logType'] = log_type
        
        if username:
            filter_query['username'] = {'$regex': username, '$options': 'i'}
        
        if date_from or date_to:
            filter_query['timestamp'] = {}
            if date_from:
                filter_query['timestamp']['$gte'] = datetime.strptime(date_from, '%Y-%m-%d')
            if date_to:
                # Add one day to include the entire end date
                end_date = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
                filter_query['timestamp']['$lt'] = end_date
        
        # Get total count
        total_logs = db.count('activity_logs', filter_query)
        total_pages = (total_logs + limit - 1) // limit  # Ceiling division
        
        # Get paginated logs
        skip = (page - 1) * limit
        logs = list(db.find('activity_logs', filter_query, {
            'sort': {'timestamp': -1},
            'limit': limit,
            'skip': skip
        }))
        
        # Calculate stats
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        stats = {
            'total': total_logs,
            'today': db.count('activity_logs', {'timestamp': {'$gte': today_start}}),
            'errors': db.count('activity_logs', {'logType': 'error'}),
            'gameAdds': db.count('activity_logs', {'logType': 'game_add'})
        }
        
        return jsonify({
            'success': True,
            'logs': [serialize_doc(log) for log in logs],
            'stats': stats,
            'totalPages': total_pages,
            'currentPage': page
        })
    except Exception as e:
        logger.error(f"Error fetching logs: {e}")
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/api/logs/add', methods=['POST'])
def api_add_log():
    """API endpoint for client apps to add activity logs"""
    db = get_db()
    try:
        data = request.get_json()
        
        log_entry = {
            'username': data.get('username', 'Sistem'),
            'licenseKey': data.get('licenseKey'),
            'logType': data.get('logType', 'info'),
            'details': data.get('details', ''),
            'metadata': data.get('metadata', {}),
            'timestamp': datetime.utcnow()
        }
        
        db.insert('activity_logs', log_entry)
        return jsonify({'success': True, 'message': 'Log kaydedildi'})
    except Exception as e:
        logger.error(f"Error adding log: {e}")
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/api/logs/delete', methods=['POST'])
@login_required
def api_delete_logs():
    """API endpoint to delete selected logs"""
    db = get_db()
    try:
        from bson import ObjectId
        data = request.get_json()
        log_ids = data.get('logIds', [])
        
        if not log_ids:
            return jsonify({'success': False, 'message': 'Silinecek log seçilmedi'}), 400
        
        # Convert string IDs to ObjectIds
        object_ids = [ObjectId(log_id) for log_id in log_ids]
        
        result = db.db.activity_logs.delete_many({'_id': {'$in': object_ids}})
        
        logger.info(f"Deleted {result.deleted_count} logs")
        
        return jsonify({
            'success': True,
            'deletedCount': result.deleted_count,
            'message': f'{result.deleted_count} log kaydı silindi'
        })
    except Exception as e:
        logger.error(f"Error deleting logs: {e}")
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

@app.route('/api/logs/clear', methods=['POST'])
@login_required
def api_clear_all_logs():
    """API endpoint to clear all logs"""
    db = get_db()
    try:
        result = db.db.activity_logs.delete_many({})
        
        logger.info(f"Cleared all logs: {result.deleted_count} deleted")
        
        return jsonify({
            'success': True,
            'deletedCount': result.deleted_count,
            'message': f'Tüm loglar temizlendi ({result.deleted_count} kayıt)'
        })
    except Exception as e:
        logger.error(f"Error clearing logs: {e}")
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500

if __name__ == '__main__':
    print("=" * 60)
    print("  Xcrover Admin Panel")
    print("=" * 60)
    port = int(os.environ.get('PORT', 5000))
    print(f"  URL: http://127.0.0.1:{port}")
    print("  Kullanici: admin")
    print("  Sifre: admin123")
    print("=" * 60)
    app.run(debug=False, host='0.0.0.0', port=port, threaded=True)
