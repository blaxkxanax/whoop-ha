from flask import Flask, request, redirect, session, url_for, jsonify
import os
import requests
from datetime import datetime, timezone, timedelta
import json
from dotenv import load_dotenv
import pathlib
import logging
from logging.handlers import RotatingFileHandler
import threading
import time
import sqlite3
from functools import wraps
import secrets
import base64

# Load environment variables
load_dotenv(os.path.join(os.getenv('CONFIG_DIR', './config'), '.env'))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
log_file = os.getenv('LOG_FILE', '/app/data/whoop.log')
os.makedirs(os.path.dirname(log_file), exist_ok=True)
handler = RotatingFileHandler(log_file, maxBytes=10000000, backupCount=5)
handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
logger.addHandler(handler)

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY')
API_TOKEN = os.getenv('API_TOKEN')

# Whoop API Configuration
WHOOP_CLIENT_ID = os.getenv('WHOOP_CLIENT_ID')
WHOOP_CLIENT_SECRET = os.getenv('WHOOP_CLIENT_SECRET')
WHOOP_REDIRECT_URI = os.getenv('WHOOP_REDIRECT_URI')
WHOOP_AUTH_URL = 'https://api.prod.whoop.com/oauth/oauth2/auth'
WHOOP_TOKEN_URL = 'https://api.prod.whoop.com/oauth/oauth2/token'
WHOOP_API_BASE = 'https://api.prod.whoop.com/developer/v1'

# Database configuration
DB_PATH = os.getenv('SQLITE_DB', '/app/data/whoop.db')
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            whoop_id INTEGER PRIMARY KEY,
            email TEXT,
            first_name TEXT,
            last_name TEXT,
            gender TEXT,
            height_meter REAL,
            weight_kg REAL,
            max_heart_rate INTEGER,
            rest_heart_rate INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        conn.execute("""
        CREATE TABLE IF NOT EXISTS tokens (
            whoop_id INTEGER PRIMARY KEY,
            access_token TEXT,
            refresh_token TEXT,
            expires_at TIMESTAMP,
            FOREIGN KEY (whoop_id) REFERENCES users(whoop_id)
        )
        """)
        
        conn.execute("""
        CREATE TABLE IF NOT EXISTS whoop_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            whoop_id INTEGER,
            timestamp TIMESTAMP,
            cycle_id INTEGER,
            cycle_data TEXT,
            recovery_data TEXT,
            sleep_data TEXT,
            workout_data TEXT,
            recovery_score INTEGER,
            sleep_score INTEGER,
            strain_score REAL,
            calories_burned INTEGER,
            average_heart_rate INTEGER,
            max_heart_rate INTEGER,
            respiratory_rate REAL,
            spo2_percentage REAL,
            skin_temp_celsius REAL,
            FOREIGN KEY (whoop_id) REFERENCES users(whoop_id)
        )
        """)
        conn.commit()

# Initialize database
init_db()

def require_api_token(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get('X-API-Token')
        if not token or token != API_TOKEN:
            return jsonify({"error": "Invalid or missing API token"}), 401
        return f(*args, **kwargs)
    return decorated_function

def save_user_data(user_info, token_info):
    with sqlite3.connect(DB_PATH) as conn:
        # Save user info
        conn.execute("""
        INSERT OR REPLACE INTO users (whoop_id, email, first_name, last_name)
        VALUES (?, ?, ?, ?)
        """, (user_info['id'], user_info.get('email'), 
              user_info.get('first_name'), user_info.get('last_name')))
        
        # Save token info
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_info['expires_in'])
        conn.execute("""
        INSERT OR REPLACE INTO tokens (whoop_id, access_token, refresh_token, expires_at)
        VALUES (?, ?, ?, ?)
        """, (user_info['id'], token_info['access_token'], 
              token_info['refresh_token'], expires_at))
        
        conn.commit()

def save_whoop_data_to_db(whoop_id, data):
    with sqlite3.connect(DB_PATH) as conn:
        # Extract metrics from the data
        recovery_data = data.get('recovery', {})
        sleep_data = data.get('sleep', {})
        workout_data = data.get('workout', {})
        cycle_data = data.get('cycle', {})

        # Get scores and metrics
        recovery_score = recovery_data.get('score', {}).get('recovery_score') if recovery_data else None
        sleep_score = sleep_data.get('score', {}).get('sleep_score') if sleep_data else None
        strain_score = cycle_data.get('score', {}).get('strain') if cycle_data else None
        
        # Get vital signs
        vitals = {}
        if recovery_data and recovery_data.get('score'):
            vitals.update({
                'respiratory_rate': recovery_data['score'].get('respiratory_rate'),
                'spo2_percentage': recovery_data['score'].get('spo2_percentage'),
                'skin_temp_celsius': recovery_data['score'].get('skin_temp_celsius'),
                'rest_heart_rate': recovery_data['score'].get('resting_heart_rate')
            })
        
        if workout_data and workout_data.get('score'):
            vitals.update({
                'calories_burned': workout_data['score'].get('kilojoule'),
                'average_heart_rate': workout_data['score'].get('average_heart_rate'),
                'max_heart_rate': workout_data['score'].get('max_heart_rate')
            })

        conn.execute("""
        INSERT INTO whoop_data 
        (whoop_id, timestamp, cycle_id, cycle_data, recovery_data, sleep_data, workout_data,
         recovery_score, sleep_score, strain_score, calories_burned, average_heart_rate,
         max_heart_rate, respiratory_rate, spo2_percentage, skin_temp_celsius)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            whoop_id,
            data['timestamp'],
            data['cycle']['id'],
            json.dumps(cycle_data),
            json.dumps(recovery_data) if recovery_data else None,
            json.dumps(sleep_data) if sleep_data else None,
            json.dumps(workout_data) if workout_data else None,
            recovery_score,
            sleep_score,
            strain_score,
            vitals.get('calories_burned'),
            vitals.get('average_heart_rate'),
            vitals.get('max_heart_rate'),
            vitals.get('respiratory_rate'),
            vitals.get('spo2_percentage'),
            vitals.get('skin_temp_celsius')
        ))
        
        # Update user's rest heart rate if available
        if vitals.get('rest_heart_rate'):
            conn.execute("""
            UPDATE users 
            SET rest_heart_rate = ?, updated_at = CURRENT_TIMESTAMP 
            WHERE whoop_id = ?
            """, (vitals['rest_heart_rate'], whoop_id))
        
        conn.commit()

def get_user_token(whoop_id):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("""
        SELECT access_token, refresh_token, expires_at
        FROM tokens WHERE whoop_id = ?
        """, (whoop_id,))
        return cursor.fetchone()

def get_user_info(whoop_id=None):
    with sqlite3.connect(DB_PATH) as conn:
        if whoop_id:
            cursor = conn.execute("SELECT * FROM users WHERE whoop_id = ?", (whoop_id,))
            return cursor.fetchone()
        else:
            cursor = conn.execute("SELECT * FROM users")
            return cursor.fetchall()

@app.route('/data')
@require_api_token
def get_data():
    whoop_id = request.args.get('user_id')
    if not whoop_id:
        return jsonify({"error": "user_id parameter is required"}), 400

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute("""
            SELECT * FROM whoop_data 
            WHERE whoop_id = ? 
            ORDER BY timestamp DESC 
            LIMIT 1
            """, (whoop_id,))
            data = cursor.fetchone()
            
            if not data:
                return jsonify({"error": "No data found for user"}), 404
                
            return jsonify({
                "user_id": data[1],
                "timestamp": data[2],
                "cycle_id": data[3],
                "cycle": json.loads(data[4]) if data[4] else None,
                "recovery": json.loads(data[5]) if data[5] else None,
                "sleep": json.loads(data[6]) if data[6] else None,
                "workout": json.loads(data[7]) if data[7] else None
            })
    except Exception as e:
        logger.error(f"Error reading data: {e}")
        return jsonify({"error": "Error reading data"}), 500

@app.route('/refresh')
@require_api_token
def manual_refresh():
    whoop_id = request.args.get('user_id')
    if not whoop_id:
        return jsonify({"error": "user_id parameter is required"}), 400

    data = get_whoop_data(whoop_id)
    if data:
        return jsonify({"status": "success", "data": data})
    return jsonify({"status": "error", "message": "Failed to refresh data"}), 500

def get_whoop_data(whoop_id):
    token_info = get_user_token(whoop_id)
    if not token_info:
        return None

    access_token = token_info[0]  # access_token
    headers = {
        'Authorization': f"Bearer {access_token}"
    }

    try:
        # Get current cycle first
        current_cycle = get_current_cycle(headers)
        if not current_cycle:
            # Try refreshing token if we got None (which might be due to 401)
            new_token = refresh_token(whoop_id)
            if new_token:
                headers = {'Authorization': f"Bearer {new_token}"}
                current_cycle = get_current_cycle(headers)
                if not current_cycle:
                    logger.error("No current cycle found even after token refresh")
                    return None
            else:
                logger.error("Failed to refresh token")
                return None

        cycle_id = current_cycle['id']
        
        # Get data for the current cycle
        recovery_data = get_recovery_for_cycle(cycle_id, headers)
        sleep_data = get_sleep_for_cycle(cycle_id, headers)
        workout_data = get_workout_for_cycle(cycle_id, headers)

        data = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'cycle': current_cycle,
            'recovery': recovery_data,
            'sleep': sleep_data,
            'workout': workout_data
        }

        save_whoop_data_to_db(whoop_id, data)
        logger.info(f"Data fetched and saved successfully for user {whoop_id}")
        return data

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            logger.warning("Token expired, attempting refresh")
            new_token = refresh_token(whoop_id)
            if new_token:
                return get_whoop_data(whoop_id)  # Retry with new token
        logger.error(f"HTTP error fetching data: {e}")
        return None
    except Exception as e:
        logger.error(f"Error fetching data: {e}")
        return None

def background_data_refresh():
    while True:
        try:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.execute("SELECT whoop_id FROM users")
                users = cursor.fetchall()
                
            for user in users:
                try:
                    get_whoop_data(user[0])
                except Exception as e:
                    logger.error(f"Error refreshing data for user {user[0]}: {e}")
                    
            time.sleep(300)  # Wait 5 minutes before next refresh
        except Exception as e:
            logger.error(f"Error in background refresh: {e}")
            time.sleep(60)  # Wait 1 minute on error before retrying

# Start background refresh thread
refresh_thread = threading.Thread(target=background_data_refresh, daemon=True)
refresh_thread.start()

@app.route('/')
def home():
    return 'Whoop Integration Service'

@app.route('/auth')
def auth():
    state = generate_state()
    session['oauth_state'] = state
    auth_url = f"{WHOOP_AUTH_URL}?client_id={WHOOP_CLIENT_ID}&response_type=code&redirect_uri={WHOOP_REDIRECT_URI}&scope=offline read:recovery read:cycles read:sleep read:workout read:profile read:body_measurement&state={state}"
    return redirect(auth_url)

def get_user_profile(access_token):
    """Get user profile from Whoop API"""
    try:
        headers = {'Authorization': f"Bearer {access_token}"}
        
        # Get user profile
        response = requests.get(
            f"{WHOOP_API_BASE}/user/profile/basic",
            headers=headers
        )
        response.raise_for_status()
        user_data = response.json()
        
        return {
            'id': user_data.get('user_id'),
            'email': user_data.get('email'),
            'first_name': user_data.get('first_name'),
            'last_name': user_data.get('last_name')
        }
    except Exception as e:
        logger.error(f"Error getting user profile: {e}")
        return None

@app.route('/login')
def login():
    code = request.args.get('code')
    state = request.args.get('state')
    
    if not code:
        return 'No code provided', 400
        
    # Verify state parameter
    if state != session.get('oauth_state'):
        return 'Invalid state parameter', 400

    # Exchange code for token
    token_data = {
        'client_id': WHOOP_CLIENT_ID,
        'client_secret': WHOOP_CLIENT_SECRET,
        'code': code,
        'grant_type': 'authorization_code',
        'redirect_uri': WHOOP_REDIRECT_URI
    }

    try:
        # Get token
        response = requests.post(WHOOP_TOKEN_URL, data=token_data)
        response.raise_for_status()
        token_info = response.json()
        
        # Get user profile
        user_profile = get_user_profile(token_info['access_token'])
        if not user_profile:
            return 'Failed to get user profile', 500
            
        # Save user and token information
        save_user_data(user_profile, token_info)
        
        # Trigger initial data fetch
        get_whoop_data(user_profile['id'])
        
        return 'Authentication successful! You can close this window.'

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to get token: {e}")
        return f'Failed to get token: {str(e)}', 400
    except Exception as e:
        logger.error(f"Error during login: {e}")
        return 'An error occurred during login', 500

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    # TODO: Process webhook data
    return 'OK', 200

def generate_state():
    """Generate a secure random state parameter for OAuth."""
    return secrets.token_hex(4)  # 8 characters as required by Whoop

def get_current_cycle(headers):
    """Get the user's current cycle"""
    try:
        params = {
            'limit': 1,  # Get only the latest cycle
            'end': datetime.now(timezone.utc).isoformat()  # Up to current time
        }
        response = requests.get(
            f"{WHOOP_API_BASE}/cycle",
            headers=headers,
            params=params
        )
        response.raise_for_status()
        cycles = response.json().get('records', [])
        return cycles[0] if cycles else None
    except Exception as e:
        logger.error(f"Error getting current cycle: {e}")
        return None

def get_recovery_for_cycle(cycle_id, headers):
    """Get recovery data for a specific cycle"""
    try:
        response = requests.get(
            f"{WHOOP_API_BASE}/cycle/{cycle_id}/recovery",
            headers=headers
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error getting recovery for cycle {cycle_id}: {e}")
        return None

def get_sleep_for_cycle(cycle_id, headers):
    """Get sleep data for a specific cycle"""
    try:
        # First get sleep collection to find the latest sleep
        params = {
            'limit': 1,
            'end': datetime.now(timezone.utc).isoformat()
        }
        response = requests.get(
            f"{WHOOP_API_BASE}/activity/sleep",
            headers=headers,
            params=params
        )
        response.raise_for_status()
        sleeps = response.json().get('records', [])
        if not sleeps:
            return None
            
        # Get detailed sleep data
        sleep_id = sleeps[0]['id']
        sleep_response = requests.get(
            f"{WHOOP_API_BASE}/activity/sleep/{sleep_id}",
            headers=headers
        )
        sleep_response.raise_for_status()
        return sleep_response.json()
    except Exception as e:
        logger.error(f"Error getting sleep data: {e}")
        return None

def get_workout_for_cycle(cycle_id, headers):
    """Get workout data for a specific cycle"""
    try:
        # First get workout collection to find the latest workout
        params = {
            'limit': 1,
            'end': datetime.now(timezone.utc).isoformat()
        }
        response = requests.get(
            f"{WHOOP_API_BASE}/activity/workout",
            headers=headers,
            params=params
        )
        response.raise_for_status()
        workouts = response.json().get('records', [])
        if not workouts:
            return None
            
        # Get detailed workout data
        workout_id = workouts[0]['id']
        workout_response = requests.get(
            f"{WHOOP_API_BASE}/activity/workout/{workout_id}",
            headers=headers
        )
        workout_response.raise_for_status()
        return workout_response.json()
    except Exception as e:
        logger.error(f"Error getting workout data: {e}")
        return None

def refresh_token(whoop_id):
    """Refresh the access token using the refresh token."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                "SELECT refresh_token FROM tokens WHERE whoop_id = ?", (whoop_id,)
            )
            refresh_token = cursor.fetchone()
            if not refresh_token:
                return None

            token_data = {
                'client_id': WHOOP_CLIENT_ID,
                'client_secret': WHOOP_CLIENT_SECRET,
                'refresh_token': refresh_token[0],
                'grant_type': 'refresh_token'
            }

            response = requests.post(WHOOP_TOKEN_URL, data=token_data)
            response.raise_for_status()
            token_info = response.json()

            # Update tokens in database
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_info['expires_in'])
            conn.execute(
                """
                UPDATE tokens 
                SET access_token = ?, refresh_token = ?, expires_at = ?
                WHERE whoop_id = ?
                """,
                (token_info['access_token'], token_info['refresh_token'], expires_at, whoop_id)
            )
            conn.commit()
            return token_info['access_token']
    except Exception as e:
        logger.error(f"Error refreshing token: {e}")
        return None

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=2008) 