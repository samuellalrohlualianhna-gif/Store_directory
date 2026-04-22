from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
from functools import wraps
import os
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///store_directory.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB max
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

# ─── Models ──────────────────────────────────────────────────────────────────

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='owner')  # 'owner' or 'admin'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    stores = db.relationship('Store', backref='owner', lazy=True)
    is_active = db.Column(db.Boolean, default=True)

    @property
    def is_authenticated(self): return True
    @property
    def is_anonymous(self): return False
    def get_id(self): return str(self.id)
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)
    def is_admin(self): return self.role == 'admin'

class Store(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(50), nullable=False)
    tags = db.Column(db.String(300), nullable=True)  # JSON list
    address = db.Column(db.String(300), nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    phone = db.Column(db.String(30), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    website = db.Column(db.String(200), nullable=True)
    logo = db.Column(db.String(200), nullable=True)
    opening_hours = db.Column(db.String(300), nullable=True)
    is_approved = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    def get_tags(self):
        if self.tags:
            try: return json.loads(self.tags)
            except: return []
        return []

    def set_tags(self, tag_list):
        self.tags = json.dumps(tag_list)

class SiteSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    site_name = db.Column(db.String(150), default='LocalFind')
    tagline = db.Column(db.String(300), default='Discover stores in your community')
    primary_color = db.Column(db.String(20), default='#2d6a4f')
    secondary_color = db.Column(db.String(20), default='#52b788')
    accent_color = db.Column(db.String(20), default='#d4a017')
    bg_color = db.Column(db.String(20), default='#faf7f0')
    text_color = db.Column(db.String(20), default='#1a1a2e')
    logo = db.Column(db.String(200), nullable=True)
    maps_api_key = db.Column(db.String(200), default='YOUR_GOOGLE_MAPS_API_KEY')
    footer_text = db.Column(db.String(500), default='© 2025 LocalFind. All rights reserved.')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash('Admin access required.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_settings():
    s = SiteSettings.query.first()
    if not s:
        s = SiteSettings()
        db.session.add(s)
        db.session.commit()
    return s

def save_logo(file, subfolder='logos'):
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        folder = os.path.join(app.config['UPLOAD_FOLDER'], subfolder)
        os.makedirs(folder, exist_ok=True)
        ts = datetime.utcnow().strftime('%Y%m%d%H%M%S%f')
        ext = filename.rsplit('.', 1)[1].lower()
        saved = f"{ts}.{ext}"
        file.save(os.path.join(folder, saved))
        return f"uploads/{subfolder}/{saved}"
    return None

# ─── Context Processor ───────────────────────────────────────────────────────

@app.context_processor
def inject_settings():
    def store_pending_count():
        return Store.query.filter_by(is_approved=False, is_active=True).count()
    return dict(settings=get_settings(), store_pending_count=store_pending_count)

# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    settings = get_settings()
    featured = Store.query.filter_by(is_approved=True, is_active=True).order_by(Store.created_at.desc()).limit(6).all()
    categories = db.session.query(Store.category, db.func.count(Store.id)).filter_by(is_approved=True, is_active=True).group_by(Store.category).all()
    return render_template('index.html', featured=featured, categories=categories, settings=settings)

@app.route('/stores')
def stores():
    query = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()
    tag = request.args.get('tag', '').strip()
    page = request.args.get('page', 1, type=int)

    stmt = Store.query.filter_by(is_approved=True, is_active=True)
    if query:
        stmt = stmt.filter(
            db.or_(
                Store.name.ilike(f'%{query}%'),
                Store.description.ilike(f'%{query}%'),
                Store.address.ilike(f'%{query}%')
            )
        )
    if category:
        stmt = stmt.filter(Store.category == category)
    if tag:
        stmt = stmt.filter(Store.tags.ilike(f'%{tag}%'))

    stores_page = stmt.order_by(Store.name).paginate(page=page, per_page=12, error_out=False)
    all_categories = db.session.query(Store.category).filter_by(is_approved=True, is_active=True).distinct().all()
    all_categories = [c[0] for c in all_categories]

    all_tags_raw = db.session.query(Store.tags).filter_by(is_approved=True, is_active=True).all()
    all_tags = set()
    for row in all_tags_raw:
        if row[0]:
            try: all_tags.update(json.loads(row[0]))
            except: pass

    return render_template('stores.html',
        stores=stores_page,
        query=query,
        selected_category=category,
        selected_tag=tag,
        all_categories=all_categories,
        all_tags=sorted(all_tags))

@app.route('/store/<int:store_id>')
def store_detail(store_id):
    store = Store.query.get_or_404(store_id)
    if not store.is_approved and (not current_user.is_authenticated or
        (current_user.id != store.owner_id and not current_user.is_admin())):
        flash('Store not found.', 'danger')
        return redirect(url_for('stores'))
    settings = get_settings()
    return render_template('store_detail.html', store=store, settings=settings)

@app.route('/api/stores/nearby')
def api_nearby_stores():
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)
    stores = Store.query.filter_by(is_approved=True, is_active=True).all()
    data = []
    for s in stores:
        data.append({
            'id': s.id, 'name': s.name, 'address': s.address,
            'category': s.category, 'lat': s.latitude, 'lng': s.longitude,
            'logo': s.logo, 'tags': s.get_tags()
        })
    return jsonify(data)

# ─── Auth ─────────────────────────────────────────────────────────────────────

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        role = request.form.get('role', 'owner')

        if not all([username, email, password, confirm]):
            flash('All fields are required.', 'danger')
        elif password != confirm:
            flash('Passwords do not match.', 'danger')
        elif len(password) < 8:
            flash('Password must be at least 8 characters.', 'danger')
        elif User.query.filter_by(username=username).first():
            flash('Username already taken.', 'danger')
        elif User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
        else:
            if role not in ['owner']:
                role = 'owner'
            user = User(username=username, email=email, role=role)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember') == 'on'
        user = User.query.filter(
            (User.username == identifier) | (User.email == identifier)
        ).first()
        if user and user.check_password(password) and user.is_active:
            login_user(user, remember=remember)
            next_page = request.args.get('next')
            flash(f'Welcome back, {user.username}!', 'success')
            return redirect(next_page or url_for('dashboard'))
        flash('Invalid credentials or account is inactive.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

# ─── Dashboard ────────────────────────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.is_admin():
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('owner_dashboard'))

@app.route('/dashboard/owner')
@login_required
def owner_dashboard():
    stores = Store.query.filter_by(owner_id=current_user.id).order_by(Store.created_at.desc()).all()
    return render_template('dashboard_owner.html', stores=stores)

# ─── Store Management (Owner) ─────────────────────────────────────────────────

@app.route('/store/add', methods=['GET', 'POST'])
@login_required
def add_store():
    settings = get_settings()
    CATEGORIES = ['Grocery Store', 'Drug Store / Pharmacy', 'Restaurant / Food',
                  'Clothing & Fashion', 'Electronics', 'Hardware & Tools',
                  'Bakery & Confectionery', 'Beauty & Wellness', 'Sports & Outdoors',
                  'Books & Stationery', 'Jewelry & Accessories', 'Home & Furniture',
                  'Automotive', 'Pet Store', 'Toy Store', 'Other']
    TAGS = ['24/7', 'Delivery Available', 'Takeaway', 'Parking', 'Wheelchair Accessible',
            'Accepts Cards', 'Organic', 'Local Brand', 'Wholesale', 'Online Orders',
            'Budget-Friendly', 'Premium', 'Family-Owned', 'Franchise', 'New Arrival']

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        category = request.form.get('category', '').strip()
        address = request.form.get('address', '').strip()
        lat = request.form.get('latitude', type=float)
        lng = request.form.get('longitude', type=float)
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()
        website = request.form.get('website', '').strip()
        opening_hours = request.form.get('opening_hours', '').strip()
        selected_tags = request.form.getlist('tags')

        if not all([name, category, address]) or lat is None or lng is None:
            flash('Name, category, address and map location are required.', 'danger')
        else:
            logo_path = None
            if 'logo' in request.files:
                logo_path = save_logo(request.files['logo'], 'logos')

            store = Store(
                name=name, description=description, category=category,
                address=address, latitude=lat, longitude=lng,
                phone=phone, email=email, website=website,
                opening_hours=opening_hours, logo=logo_path,
                owner_id=current_user.id, is_approved=False
            )
            store.set_tags(selected_tags)
            db.session.add(store)
            db.session.commit()
            flash('Store submitted! Awaiting admin approval.', 'success')
            return redirect(url_for('owner_dashboard'))

    return render_template('add_store.html', categories=CATEGORIES, tags=TAGS, settings=settings)

@app.route('/store/<int:store_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_store(store_id):
    store = Store.query.get_or_404(store_id)
    if store.owner_id != current_user.id and not current_user.is_admin():
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    settings = get_settings()
    CATEGORIES = ['Grocery Store', 'Drug Store / Pharmacy', 'Restaurant / Food',
                  'Clothing & Fashion', 'Electronics', 'Hardware & Tools',
                  'Bakery & Confectionery', 'Beauty & Wellness', 'Sports & Outdoors',
                  'Books & Stationery', 'Jewelry & Accessories', 'Home & Furniture',
                  'Automotive', 'Pet Store', 'Toy Store', 'Other']
    TAGS = ['24/7', 'Delivery Available', 'Takeaway', 'Parking', 'Wheelchair Accessible',
            'Accepts Cards', 'Organic', 'Local Brand', 'Wholesale', 'Online Orders',
            'Budget-Friendly', 'Premium', 'Family-Owned', 'Franchise', 'New Arrival']

    if request.method == 'POST':
        store.name = request.form.get('name', '').strip()
        store.description = request.form.get('description', '').strip()
        store.category = request.form.get('category', '').strip()
        store.address = request.form.get('address', '').strip()
        lat = request.form.get('latitude', type=float)
        lng = request.form.get('longitude', type=float)
        if lat is not None: store.latitude = lat
        if lng is not None: store.longitude = lng
        store.phone = request.form.get('phone', '').strip()
        store.email = request.form.get('email', '').strip()
        store.website = request.form.get('website', '').strip()
        store.opening_hours = request.form.get('opening_hours', '').strip()
        store.set_tags(request.form.getlist('tags'))

        if 'logo' in request.files and request.files['logo'].filename:
            logo_path = save_logo(request.files['logo'], 'logos')
            if logo_path: store.logo = logo_path

        if not current_user.is_admin():
            store.is_approved = False
        db.session.commit()
        flash('Store updated successfully!', 'success')
        return redirect(url_for('owner_dashboard') if not current_user.is_admin() else url_for('admin_stores'))

    return render_template('edit_store.html', store=store, categories=CATEGORIES, tags=TAGS, settings=settings)

@app.route('/store/<int:store_id>/delete', methods=['POST'])
@login_required
def delete_store(store_id):
    store = Store.query.get_or_404(store_id)
    if store.owner_id != current_user.id and not current_user.is_admin():
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    db.session.delete(store)
    db.session.commit()
    flash('Store deleted.', 'success')
    return redirect(url_for('owner_dashboard') if not current_user.is_admin() else url_for('admin_stores'))

# ─── Admin Panel ──────────────────────────────────────────────────────────────

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    total_stores = Store.query.count()
    pending_stores = Store.query.filter_by(is_approved=False, is_active=True).count()
    total_users = User.query.count()
    approved_stores = Store.query.filter_by(is_approved=True).count()
    recent_stores = Store.query.order_by(Store.created_at.desc()).limit(5).all()
    return render_template('admin_dashboard.html',
        total_stores=total_stores, pending_stores=pending_stores,
        total_users=total_users, approved_stores=approved_stores,
        recent_stores=recent_stores)

@app.route('/admin/stores')
@login_required
@admin_required
def admin_stores():
    status = request.args.get('status', 'all')
    if status == 'pending':
        stores = Store.query.filter_by(is_approved=False, is_active=True).order_by(Store.created_at.desc()).all()
    elif status == 'approved':
        stores = Store.query.filter_by(is_approved=True).order_by(Store.created_at.desc()).all()
    else:
        stores = Store.query.order_by(Store.created_at.desc()).all()
    return render_template('admin_stores.html', stores=stores, status=status)

@app.route('/admin/store/<int:store_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_store(store_id):
    store = Store.query.get_or_404(store_id)
    store.is_approved = True
    db.session.commit()
    flash(f'"{store.name}" has been approved.', 'success')
    return redirect(url_for('admin_stores', status='pending'))

@app.route('/admin/store/<int:store_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_store(store_id):
    store = Store.query.get_or_404(store_id)
    store.is_active = not store.is_active
    db.session.commit()
    flash(f'Store {"activated" if store.is_active else "deactivated"}.', 'success')
    return redirect(url_for('admin_stores'))

@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin_users.html', users=users)

@app.route('/admin/user/<int:user_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("You can't deactivate yourself.", 'danger')
        return redirect(url_for('admin_users'))
    user.is_active = not user.is_active
    db.session.commit()
    flash(f'User {"activated" if user.is_active else "deactivated"}.', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/user/<int:user_id>/make-admin', methods=['POST'])
@login_required
@admin_required
def make_admin(user_id):
    user = User.query.get_or_404(user_id)
    user.role = 'admin' if user.role == 'owner' else 'owner'
    db.session.commit()
    flash(f'User role updated to {user.role}.', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_settings():
    settings = get_settings()
    if request.method == 'POST':
        settings.site_name = request.form.get('site_name', 'LocalFind').strip()
        settings.tagline = request.form.get('tagline', '').strip()
        settings.primary_color = request.form.get('primary_color', '#2d6a4f')
        settings.secondary_color = request.form.get('secondary_color', '#52b788')
        settings.accent_color = request.form.get('accent_color', '#d4a017')
        settings.bg_color = request.form.get('bg_color', '#faf7f0')
        settings.text_color = request.form.get('text_color', '#1a1a2e')
        settings.maps_api_key = request.form.get('maps_api_key', '').strip()
        settings.footer_text = request.form.get('footer_text', '').strip()

        if 'site_logo' in request.files and request.files['site_logo'].filename:
            logo_path = save_logo(request.files['site_logo'], 'site')
            if logo_path: settings.logo = logo_path

        db.session.commit()
        flash('Settings saved successfully!', 'success')
        return redirect(url_for('admin_settings'))
    return render_template('admin_settings.html', settings=settings)

# ─── Init DB ──────────────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()
    # Create default admin if none exists
    if not User.query.filter_by(role='admin').first():
        admin = User(username='admin', email='admin@localfind.com', role='admin')
        admin.set_password('admin1234')
        db.session.add(admin)
        db.session.commit()
        print("✓ Default admin created: admin / admin1234")
    # Ensure site settings exist
    if not SiteSettings.query.first():
        db.session.add(SiteSettings())
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=True)
