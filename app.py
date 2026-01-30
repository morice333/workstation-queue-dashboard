
import os
import base64
import requests
import ssl
from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_migrate import Migrate
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from sqlalchemy.engine.url import make_url  # robust DB URI 

# Gmail API imports
from google.oauth2.credentials import Credentials

from googleapiclient.discovery import build
from google.auth.transport.requests import Request as GoogleRequest

# Gmail API scope
SCOPES = ['https://www.googleapis.com/auth/gmail.send']

# Flask app setup
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'


# NEW: make sure the instance folder exists (Flask stores local files here)
os.makedirs(app.instance_path, exist_ok=True)

db_url = os.environ.get("DATABASE_URL", "sqlite:///db.sqlite")

# Render sometimes provides postgres:// which SQLAlchemy wants as postgresql://
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
print("DB URI in use:", app.config["SQLALCHEMY_DATABASE_URI"])

db = SQLAlchemy(app)
migrate = Migrate(app, db)


# -----------------------------
# (new) Helper to resolve sqlite path reliably
# -----------------------------
# --- keep BASEDIR as you already have it ---
BASEDIR = os.path.abspath(os.path.dirname(__file__))

def _resolve_sqlite_path(uri: str) -> str | None:
    """
    Return absolute path to the SQLite file if the URI is SQLite (not :memory:).
    For relative DB URIs, check (in order):
      1) Flask instance_path
      2) folder where app.py lives (BASEDIR)
      3) current working directory (CWD)
    If none exists yet, prefer instance_path as canonical location.
    """
    from sqlalchemy.engine.url import make_url
    try:
        url = make_url(uri)
    except Exception:
        return None

    if not url.drivername.startswith("sqlite"):
        return None

    db_part = url.database  # may be None, ':memory:', relative or absolute
    if not db_part or db_part == ":memory:":
        return None

    # Absolute path? Use it directly.
    if os.path.isabs(db_part):
        return db_part


    # Relative path -> build candidates
    candidate_instance = os.path.abspath(os.path.join(app.instance_path, db_part))
    candidate_basedir  = os.path.abspath(os.path.join(BASEDIR, db_part))
    candidate_cwd      = os.path.abspath(os.path.join(os.getcwd(), db_part))

    # Return the first existing path
    for p in (candidate_instance, candidate_basedir, candidate_cwd):
        if os.path.exists(p):
            return p

    # None exist yet -> prefer instance folder
    return candidate_instance


login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Role durations
role_durations = {
    "Researcher": timedelta(days=120),
    "PhD": timedelta(days=90),
    "Master": timedelta(days=150),
    "Short term": timedelta(days=14)
}

# Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True)
    password = db.Column(db.String(150))
    role = db.Column(db.String(50), default='user')
    
class Request(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    name = db.Column(db.String(100))
    role = db.Column(db.String(50))
    start_time = db.Column(db.String(50))
    end_time = db.Column(db.String(50))
    status = db.Column(db.String(50), default="Pending")
    workstation = db.Column(db.String(50)) 
    renewals = db.Column(db.Integer)  
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Gmail API helper

def get_gmail_service():
    creds_data = {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "refresh_token": os.getenv("GOOGLE_REFRESH_TOKEN"),
        "type": "authorized_user"
    }

    # Check if environment variables are present
    if not creds_data["client_id"] or not creds_data["client_secret"] or not creds_data["refresh_token"]:
        raise ValueError("❌ Missing Google OAuth environment variables")

    # ✅ Debug prints for credentials
    print("Client ID:", creds_data["client_id"])
    print("Client Secret starts with:", creds_data["client_secret"][:5])
    print("Refresh Token starts with:", creds_data["refresh_token"][:5])
    print("SSL CA cert paths:", ssl.get_default_verify_paths())
    
    # Strip whitespace just in case
    creds_data["client_secret"] = creds_data["client_secret"].strip()
    creds_data["refresh_token"] = creds_data["refresh_token"].strip()
    # ✅ Connectivity check
    try:
        r = requests.get("https://oauth2.googleapis.com/token", timeout=5)
        print("Google token endpoint reachable:", r.status_code)
    except Exception as e:
        print("❌ Connectivity issue:", e)

    # Create credentials object
    creds = Credentials.from_authorized_user_info(info=creds_data, scopes=SCOPES)
    # ✅ Debug credential status
    print("Credentials expired:", creds.expired)
    print("Has refresh token:", bool(creds.refresh_token))
    
    # Attempt refresh if expired
    print("Attempting token refresh with:")
    print("Client ID:", creds.client_id)
    print("Token URI:", creds.token_uri) 
    
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(GoogleRequest())
            print("✅ Token refreshed successfully")
        except Exception as e:
            import traceback
            print("❌ Token refresh failed:", e)
            traceback.print_exc()
            
    # Build Gmail API service
    return build('gmail', 'v1', credentials=creds)

# Email sending function using Gmail API
def send_email(name, role, start_time, end_time, status):
    service = get_gmail_service()
    sender = 'moriceg33@gmail.com'
    receiver = 'maugut@kth.se'  
    subject = "New Workstation Request Submitted"
    body = f"""A new workstation request has been submitted:
Name: {name}
Role: {role}
Start Time: {start_time}
End Time: {end_time}
Status: {status}
"""

    msg = MIMEText(body)
    msg['subject'] = subject
    msg['from'] = sender
    msg['to'] = receiver
    
    raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    try:
        service.users().messages().send(userId='me', body={'raw': raw_message}).execute()
        print(f"Email sent successfully via Gmail API")
    except Exception as e:
        print(f"Email sending error: {e}")
        return jsonify({'status': 'email_failed'})
    

# Routes remain unchanged except email sending now uses Gmail API
@app.route('/')
@login_required
def dashboard():
    # Remove completed requests
    Request.query.filter_by(status='Completed').delete()
    db.session.commit()
    pending_requests = (Request.query.filter_by(status='Pending').order_by(Request.role.asc(),Request.timestamp.asc()).all())
    running_requests = (Request.query.filter_by(status='Running').order_by(Request.role.asc(),Request.timestamp.asc()).all())
    chart_data = []
    for req in running_requests:
        chart_data.append({
            "name": req.name or "",
            "workstation": req.workstation or "",
            "start": str(req.start_time),
            "end": str(req.end_time),
            "renewals": req.renewals or "",
            "color": "blue" if req.role == "PhD" else "orange" if req.role == "Master" else "green"
        })
    return render_template('dashboard.html',
                           pending_requests=pending_requests,
                           running_requests=running_requests,
                           chart_data=chart_data)

@app.route('/admin')
@login_required
def admin_dashboard():
    print("Is user authenticated?", current_user.is_authenticated)
    print("Current user role:", current_user.role)   
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    requests = Request.query.order_by(Request.timestamp.desc()).all()
    running_requests = (Request.query.filter_by(status='Running').order_by(Request.role.asc(),Request.timestamp.asc()).all())
    pending_requests = (Request.query.filter_by(status='Pending').order_by(Request.role.asc(),Request.timestamp.asc()).all())
    chart_data = []
    for req in requests:
        if req.status == 'Running':
            chart_data.append({
                "name": req.name or "",
                "workstation": req.workstation or "",
                "start": str(req.start_time),
                "end": str(req.end_time),
                "renewals": req.renewals or "",
                "color": "blue" if req.role == "PhD" else "orange" if req.role == "Master" else "green"
            })
    return render_template('admin_dashboard.html', requests=pending_requests , running_requests=running_requests,  chart_data=chart_data)


# -----------------------------
# (new) Admin-only download route
# -----------------------------

@app.route('/admin/download-sqlite', methods=['GET'])
@login_required
def download_sqlite():
    if current_user.role != 'admin':
        abort(403)

    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    sqlite_path = _resolve_sqlite_path(uri)
    if sqlite_path is None:
        abort(400, description="This service is not using a file-based SQLite DB (or it's in-memory). Nothing to download.")

    # If the file doesn't exist yet, create it by opening a connection (materialize the file)
    if not os.path.exists(sqlite_path):
        try:
            with db.engine.begin():
                pass
            if not os.path.exists(sqlite_path):
                import sqlite3
                sqlite3.connect(sqlite_path).close()
        except Exception as e:
            print("SQLite touch error:", e)

    if not os.path.exists(sqlite_path):
        abort(404, description=f"SQLite database file not found at: {sqlite_path}")

    fname = f"db_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.sqlite"
    return send_file(
        sqlite_path,
        as_attachment=True,
        download_name=fname,
        mimetype='application/octet-stream'
    )


@app.route('/admin/diag-db', methods=['GET'])
@login_required
def diag_db():
    if current_user.role != 'admin':
        abort(403)

    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    try:
        url = make_url(uri)
        db_part = url.database
    except Exception:
        url = None
        db_part = None

    candidate_basedir = os.path.abspath(os.path.join(BASEDIR, db_part or "")) if db_part else None
    candidate_cwd     = os.path.abspath(os.path.join(os.getcwd(), db_part or "")) if db_part else None
    resolved          = _resolve_sqlite_path(uri)

    return {
        "cwd": os.getcwd(),
        "basedir": BASEDIR,
        "db_uri": uri,
        "url_parsed": str(url) if url else None,
        "db_part": db_part,
        "candidate_basedir": candidate_basedir,
        "candidate_basedir_exists": os.path.exists(candidate_basedir) if candidate_basedir else None,
        "candidate_cwd": candidate_cwd,
        "candidate_cwd_exists": os.path.exists(candidate_cwd) if candidate_cwd else None,
        "resolved_sqlite_path": resolved,
        "resolved_exists": os.path.exists(resolved) if resolved else None
    }   


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password, request.form['password']):
            login_user(user)
            if user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('dashboard'))
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))



@app.route('/submit', methods=['POST'])
@login_required
def submit():
    data = request.get_json()
    name = data['name']
    role = data['role']
    start_time = data['startTime']
    end_time = data['endTime']

    # Enforce maximum duration based on role
    try:
        start_dt = datetime.strptime(start_time, "%Y-%m-%d")
        end_dt = datetime.strptime(end_time, "%Y-%m-%d")
        max_duration = role_durations.get(role, timedelta(days=60))
        if end_dt - start_dt > max_duration:
            end_dt = start_dt + max_duration
            end_time = end_dt.strftime("%Y-%m-%d")
    except Exception as e:
        print(f"Date parsing error: {e}")

    new_request = Request(
        name=name,
        role=role,
        start_time=start_time,
        end_time=end_time
    )
    db.session.add(new_request)
    db.session.commit()

# Send email via Gmail SMTP
    send_email(new_request.name, new_request.role, new_request.start_time, new_request.end_time, new_request.status)
# Return JSON response
    return jsonify({'status': 'success'})

@app.route('/update_status/<int:request_id>', methods=['POST'])
@login_required
def update_status(request_id):
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    req = Request.query.get_or_404(request_id)
    new_status = request.form.get('status')
    new_workstation = request.form.get('workstation')
    new_start_time = request.form.get('start_time')
    new_end_time = request.form.get('end_time')
    new_renewals = request.form.get('renewals')

    # Enforce maximum duration based on role
    try:
        start_dt = datetime.strptime(new_start_time, "%Y-%m-%d")
        end_dt = datetime.strptime(new_end_time, "%Y-%m-%d")
        max_duration = role_durations.get(req.role, timedelta(days=60))
        if end_dt - start_dt > max_duration:
            end_dt = start_dt + max_duration
            new_end_time = end_dt.strftime("%Y-%m-%d")
    except Exception as e:
        print(f"Date parsing error: {e}")
        
    if new_status == 'Completed':
        db.session.delete(req)
    else:
        req.status = new_status
        if new_workstation:  # Only update if provided
            req.workstation = new_workstation
            req.start_time = new_start_time
            req.end_time = new_end_time
            req.renewals = new_renewals
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()

        # Create default users
        if not User.query.filter_by(username='admin').first():
            admin_pw = generate_password_hash('secret123', method='pbkdf2:sha256')
            admin_user = User(username='admin', password=admin_pw, role='admin')
            db.session.add(admin_user)

        if not User.query.filter_by(username='hpt').first():
            hpt_pw = generate_password_hash('hpt', method='pbkdf2:sha256')
            hpt_user = User(username='hpt', password=hpt_pw, role='user')
            db.session.add(hpt_user)

        db.session.commit()

        # --- NEW: force-create the SQLite file if using sqlite:/// and it's not present ---
        p = _resolve_sqlite_path(app.config["SQLALCHEMY_DATABASE_URI"])
        if p and not os.path.exists(p):
            try:
                # Open a DB connection (no-op transaction) — this materializes the SQLite file.
                with db.engine.begin():
                    pass
                # If for some reason that still didn't materialize, fall back to a direct sqlite3 touch:
                if not os.path.exists(p):
                    import sqlite3
                    sqlite3.connect(p).close()
                print(f"SQLite file created at: {p}")
            except Exception as e:
                print("SQLite touch error at startup:", e)
    
    
    # ✅ Use Render's PORT environment variable
    port = int(os.environ.get('PORT', 5000))  # Default to 5000 for local
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
