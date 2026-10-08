import os
import io
import socket
import sqlite3
import hashlib
import hmac
from datetime import datetime, date

import streamlit as st
import pandas as pd
import qrcode

# ============================================================
# CAMPUSKART
# Smart Stationery. Smarter Resources.
# DESKTOP = CUSTOMER QR + PROTECTED ADMIN | QR ROUTE = CUSTOMER ONLY
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "campuskart.db")
PORT = int(os.environ.get("STREAMLIT_SERVER_PORT", "8501"))
ADMIN_ID = "ADMIN24"
ADMIN_PASSWORD = "@admin1234"

# Product images. If an internet image is unavailable, the product card
# still works because the application does not depend on the image.
IMAGES = {
    "Blue Ball Pen": "https://images.unsplash.com/photo-1585336261022-680e295ce3fe?w=700",
    "Black Ball Pen": "https://images.unsplash.com/photo-1583485088034-697b5bc54ccd?w=700",
    "HB Pencil": "https://images.unsplash.com/photo-1516962215378-7fa8e6e0b4f1?w=700",
    "Eraser": "https://images.unsplash.com/photo-1597075095425-ef2c1a1f0f47?w=700",
    "Permanent Marker": "https://images.unsplash.com/photo-1592647420148-bfcc7a7a3f9c?w=700",
    "Sketch Pens": "https://images.unsplash.com/photo-1513364776144-60967b0f800f?w=700",
    "Colour Crayons": "https://images.unsplash.com/photo-1607453998774-d533f65dac99?w=700",
    "A4 Paper Pack": "https://images.unsplash.com/photo-1586075010923-2dd4570fb338?w=700",
    "Notebook": "https://images.unsplash.com/photo-1531346680769-a1d79b57de5b?w=700",
    "File Folder": "https://images.unsplash.com/photo-1586282391129-76a6df230234?w=700",
    "Scale": "https://images.unsplash.com/photo-1594736797933-d0c6e2a7f9f3?w=700",
    "Stapler": "https://images.unsplash.com/photo-1586953208448-b95a79798f07?w=700",
    "A4 Sheet": "https://images.unsplash.com/photo-1455390582262-044cdead277a?w=700",
    "A4 Notebook 200 Pages": "https://images.unsplash.com/photo-1531346680769-a1d79b57de5b?w=700",
    "Chemistry Lab Record": "https://images.unsplash.com/photo-1532094349884-543bc11b234d?w=700",
    "Physics Lab Record": "https://images.unsplash.com/photo-1636466497217-26a8cbeaf0aa?w=700",
    "Stapler Pin [Boxes]": "https://images.unsplash.com/photo-1586953208448-b95a79798f07?w=700",
    "Sharpener": "https://images.unsplash.com/photo-1516962215378-7fa8e6e0b4f1?w=700",
    "Brushes": "https://images.unsplash.com/photo-1513364776144-60967b0f800f?w=700",
    "Glue Sticks": "https://images.unsplash.com/photo-1586075010923-2dd4570fb338?w=700",
    "Glue": "https://images.unsplash.com/photo-1586075010923-2dd4570fb338?w=700",
    "Scissors": "https://images.unsplash.com/photo-1582979512210-99b6a53386f9?w=700",
}

# ============================================================
# DATABASE
# ============================================================

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password, stored_hash):
    if not stored_hash:
        return False
    return hmac.compare_digest(hash_password(password), stored_hash)


def ensure_column(conn, table, column, definition):
    columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_database():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            college_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'Student',
            department TEXT NOT NULL,
            password_hash TEXT,
            created_at TEXT NOT NULL
        )
    """)
    ensure_column(conn, "users", "password_hash", "TEXT")
    ensure_column(conn, "users", "created_at", "TEXT")
    ensure_column(conn, "users", "login_count", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "users", "last_login", "TEXT")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            category TEXT NOT NULL,
            price REAL NOT NULL,
            stock INTEGER NOT NULL DEFAULT 0,
            reorder_level INTEGER NOT NULL DEFAULT 10,
            max_quantity INTEGER NOT NULL DEFAULT 10,
            monthly_usage INTEGER NOT NULL DEFAULT 0,
            image_url TEXT,
            description TEXT
        )
    """)
    for column, definition in [
        ("reorder_level", "INTEGER NOT NULL DEFAULT 10"),
        ("max_quantity", "INTEGER NOT NULL DEFAULT 10"),
        ("monthly_usage", "INTEGER NOT NULL DEFAULT 0"),
        ("image_url", "TEXT"),
        ("description", "TEXT"),
    ]:
        ensure_column(conn, "products", column, definition)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            total REAL NOT NULL,
            payment_method TEXT NOT NULL,
            status TEXT NOT NULL,
            department TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL,
            FOREIGN KEY(order_id) REFERENCES orders(id),
            FOREIGN KEY(product_id) REFERENCES products(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS stock_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            change_quantity INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(product_id) REFERENCES products(id)
        )
    """)

    # --------------------------------------------------------
    # ADMINISTRATORS
    # --------------------------------------------------------
    # The administrator account is stored in SQLite. The password is
    # never stored as plain text; only its SHA-256 hash is saved.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("SELECT id FROM admins WHERE admin_id = ?", (ADMIN_ID,))
    admin_row = cur.fetchone()
    if admin_row is None:
        cur.execute("""
            INSERT INTO admins (admin_id, password_hash, created_at)
            VALUES (?, ?, ?)
        """, (ADMIN_ID, hash_password(ADMIN_PASSWORD), datetime.now().isoformat(timespec="seconds")))
    else:
        # Keep the required demo administrator credentials synchronized with SQLite.
        cur.execute("UPDATE admins SET password_hash = ? WHERE admin_id = ?", (hash_password(ADMIN_PASSWORD), ADMIN_ID))

    # No student is required to be pre-registered. This seed is only for
    # backward compatibility with an older database. New users register
    # themselves through the customer portal.
    products = [
        ("Blue Ball Pen", "Pens", 10, 100, 20, 10, 80, IMAGES["Blue Ball Pen"], "Smooth blue ink ball pen for everyday campus use."),
        ("Black Ball Pen", "Pens", 10, 85, 20, 10, 70, IMAGES["Black Ball Pen"], "Reliable black ink pen for notes and examinations."),
        ("HB Pencil", "Pencils", 5, 150, 30, 20, 120, IMAGES["HB Pencil"], "Standard HB pencil for writing and drawing."),
        ("Eraser", "Pencils", 5, 120, 25, 20, 90, IMAGES["Eraser"], "Soft eraser suitable for students."),
        ("Permanent Marker", "Markers", 25, 35, 10, 5, 30, IMAGES["Permanent Marker"], "Permanent marker for lab, office and classroom use."),
        ("Sketch Pens", "Sketch Pens", 80, 40, 10, 5, 25, IMAGES["Sketch Pens"], "Colourful sketch pens for creative work."),
        ("Colour Crayons", "Crayons", 60, 30, 8, 5, 20, IMAGES["Colour Crayons"], "Colour crayon set for creative and academic activities."),
        ("A4 Paper Pack", "Paper", 250, 18, 5, 3, 15, IMAGES["A4 Paper Pack"], "A4 printing paper pack for institutional use."),
        ("Notebook", "Notebooks", 50, 75, 15, 10, 60, IMAGES["Notebook"], "Ruled notebook for classroom and personal notes."),
        ("File Folder", "Files", 20, 60, 15, 10, 45, IMAGES["File Folder"], "Document file folder for academic records."),
        ("Scale", "Accessories", 15, 55, 10, 10, 35, IMAGES["Scale"], "30 cm transparent scale."),
        ("Stapler", "Accessories", 90, 12, 5, 2, 8, IMAGES["Stapler"], "Compact stapler for office and classroom work."),
        ("A4 Sheet", "Paper", 5, 250, 50, 50, 200, IMAGES["A4 Sheet"], "Single A4 sheet for printing, assignments and academic work."),
        ("A4 Notebook 200 Pages", "Notebooks", 120, 60, 15, 5, 40, IMAGES["A4 Notebook 200 Pages"], "A4-size 200-page notebook for notes and academic work."),
        ("Chemistry Lab Record", "Lab Records", 80, 50, 10, 5, 30, IMAGES["Chemistry Lab Record"], "Record notebook for chemistry laboratory experiments."),
        ("Physics Lab Record", "Lab Records", 80, 50, 10, 5, 30, IMAGES["Physics Lab Record"], "Record notebook for physics laboratory experiments."),
        ("Stapler Pin [Boxes]", "Accessories", 25, 40, 10, 5, 25, IMAGES["Stapler Pin [Boxes]"], "Stapler pin boxes for office and classroom use."),
        ("Sharpener", "Pencils", 5, 100, 20, 10, 70, IMAGES["Sharpener"], "Compact sharpener for pencils."),
        ("Brushes", "Art Supplies", 40, 50, 10, 5, 30, IMAGES["Brushes"], "Brushes for drawing, painting and creative activities."),
        ("Glue Sticks", "Adhesives", 20, 60, 15, 5, 40, IMAGES["Glue Sticks"], "Glue sticks for paper and craft work."),
        ("Glue", "Adhesives", 25, 50, 12, 5, 35, IMAGES["Glue"], "Liquid glue for paper, craft and academic projects."),
        ("Scissors", "Accessories", 35, 45, 10, 5, 30, IMAGES["Scissors"], "Scissors for paper, craft and classroom activities."),
    ]

    for product in products:
        cur.execute("""
            INSERT OR IGNORE INTO products
            (name, category, price, stock, reorder_level, max_quantity,
             monthly_usage, image_url, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, product)

    # Refresh missing image/description fields without changing live stock.
    for product in products:
        name, _, _, _, _, _, _, image_url, description = product
        cur.execute("""
            UPDATE products
            SET image_url = COALESCE(NULLIF(image_url, ''), ?),
                description = COALESCE(NULLIF(description, ''), ?)
            WHERE name = ?
        """, (image_url, description, name))

    conn.commit()
    conn.close()


init_database()

# ============================================================
# SESSION STATE
# ============================================================

DEFAULTS = {
    "page": "qr",                # Desktop starts with the customer QR; admin is protected behind login.
    "admin": False,
    "user_id": None,
    "cart": [],
    "customer_hero": True,
    "order_success": None,
    "selected_product": None,
    "search": "",
    "category": "All",
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value

# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def money(value):
    return f"₹{float(value):,.2f}"


def get_local_ip():
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("10.255.255.255", 1))
        ip = sock.getsockname()[0]
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    finally:
        if sock:
            sock.close()
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    return "127.0.0.1"


def get_base_url():
    override = os.environ.get("CAMPUSKART_URL", "").strip()
    if override:
        return override.rstrip("/")
    return f"http://{get_local_ip()}:{PORT}"


def get_customer_url():
    return f"{get_base_url()}/?mode=customer"


def make_qr_bytes():
    qr = qrcode.QRCode(version=1, box_size=9, border=4)
    qr.add_data(get_customer_url())
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def verify_admin_credentials(admin_id, password):
    """Verify administrator credentials against the SQLite admins table."""
    conn = get_db()
    admin = conn.execute(
        "SELECT * FROM admins WHERE admin_id = ?",
        (admin_id.strip(),)
    ).fetchone()
    conn.close()
    if not admin:
        return False
    return verify_password(password, admin["password_hash"])


def get_current_user():
    if not st.session_state.user_id:
        return None
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (st.session_state.user_id,)).fetchone()
    conn.close()
    return user


def get_product(product_id):
    conn = get_db()
    product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    conn.close()
    return product


def stock_status(product):
    stock = int(product["stock"])
    reorder = int(product["reorder_level"])
    if stock == 0:
        return "OUT OF STOCK"
    if stock <= max(1, reorder // 2):
        return "CRITICAL"
    if stock <= reorder:
        return "LOW STOCK"
    return "AVAILABLE"


def stock_badge(product):
    status = stock_status(product)
    return {
        "OUT OF STOCK": "🔴 OUT OF STOCK",
        "CRITICAL": "🔴 CRITICAL",
        "LOW STOCK": "🟠 LOW STOCK",
        "AVAILABLE": "🟢 AVAILABLE",
    }[status]


def cart_count():
    return sum(int(item["quantity"]) for item in st.session_state.cart)


def cart_total():
    return sum(float(item["price"]) * int(item["quantity"]) for item in st.session_state.cart)


def navigate(page):
    st.session_state.page = page
    st.session_state.selected_product = None
    st.rerun()


def customer_logout():
    st.session_state.user_id = None
    st.session_state.cart = []
    st.session_state.order_success = None
    st.session_state.customer_hero = True
    st.rerun()


def admin_logout():
    st.session_state.admin = False
    st.session_state.page = "admin_login"
    st.rerun()


def recommended_order_quantity(product):
    monthly_usage = max(int(product["monthly_usage"]), 1)
    target_stock = max(int(product["reorder_level"]), int(monthly_usage * 1.5))
    return max(0, target_stock - int(product["stock"]))


def reorder_recommendation(product):
    stock = int(product["stock"])
    usage = max(int(product["monthly_usage"]), 1)
    reorder = int(product["reorder_level"])
    qty = recommended_order_quantity(product)

    if stock == 0:
        return f"🔴 Stock-out risk. Recommended procurement: **{qty} units**."
    if stock <= reorder:
        return f"🟠 Stock is below the reorder level. Suggested procurement: **{qty} units**."
    if stock > usage * 2:
        return "📦 Excess inventory detected. Avoid unnecessary procurement until demand increases."
    return "🟢 Stock is healthy. Continue monitoring consumption."


def calculate_efficiency():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
    low = conn.execute("SELECT COUNT(*) AS c FROM products WHERE stock <= reorder_level").fetchone()["c"]
    excess = conn.execute("SELECT COUNT(*) AS c FROM products WHERE stock > monthly_usage * 2").fetchone()["c"]
    conn.close()
    if not total:
        return 0
    score = 100 - (low / total) * 35 - (excess / total) * 20
    return max(0, min(100, round(score)))


def add_to_cart(product_id, quantity):
    product = get_product(product_id)
    quantity = int(quantity)

    if not product or quantity <= 0:
        return False, "Enter a valid quantity."
    if int(product["stock"]) <= 0:
        return False, "This item is out of stock."
    if quantity > int(product["stock"]):
        return False, f"Only {product['stock']} units are available."
    if quantity > int(product["max_quantity"]):
        return False, f"Maximum allowed per transaction is {product['max_quantity']}."

    for item in st.session_state.cart:
        if item["product_id"] == product_id:
            new_qty = int(item["quantity"]) + quantity
            if new_qty > int(product["max_quantity"]):
                return False, f"Maximum allowed per transaction is {product['max_quantity']}."
            if new_qty > int(product["stock"]):
                return False, "Quantity exceeds available stock."
            item["quantity"] = new_qty
            return True, f"{product['name']} quantity updated in cart."

    st.session_state.cart.append({
        "product_id": int(product_id),
        "name": product["name"],
        "price": float(product["price"]),
        "quantity": quantity,
        "image_url": product["image_url"],
    })
    return True, f"{product['name']} added to cart."


def process_order(payment_method):
    user = get_current_user()
    if not user:
        return False, "Please log in first."
    if not st.session_state.cart:
        return False, "Your cart is empty."

    conn = get_db()
    try:
        conn.execute("BEGIN")
        validated_items = []
        total = 0.0

        for item in st.session_state.cart:
            product = conn.execute("SELECT * FROM products WHERE id = ?", (item["product_id"],)).fetchone()
            if not product:
                raise ValueError(f"Product not found: {item['name']}")
            qty = int(item["quantity"])
            if qty <= 0 or qty > int(product["stock"]):
                raise ValueError(f"Not enough stock for {product['name']}")
            if qty > int(product["max_quantity"]):
                raise ValueError(f"Maximum quantity exceeded for {product['name']}")
            subtotal = float(product["price"]) * qty
            total += subtotal
            validated_items.append((product, qty, subtotal))

        now = datetime.now().isoformat(timespec="seconds")
        cur = conn.execute("""
            INSERT INTO orders
            (user_id, total, payment_method, status, department, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user["id"], total, payment_method, "Confirmed", user["department"], now))
        order_id = cur.lastrowid

        for product, qty, subtotal in validated_items:
            conn.execute("""
                INSERT INTO order_items(order_id, product_id, quantity, price)
                VALUES (?, ?, ?, ?)
            """, (order_id, product["id"], qty, product["price"]))
            conn.execute(
                "UPDATE products SET stock = stock - ? WHERE id = ?",
                (qty, product["id"]),
            )
            conn.execute("""
                INSERT INTO stock_logs(product_id, change_quantity, reason, created_at)
                VALUES (?, ?, ?, ?)
            """, (product["id"], -qty, f"Customer purchase - Order #{order_id}", now))

        conn.commit()
        st.session_state.cart = []
        st.session_state.order_success = (order_id, total)
        return True, "Order placed successfully."
    except Exception as exc:
        conn.rollback()
        return False, str(exc)
    finally:
        conn.close()

# ============================================================
# PAGE CONFIG + CSS
# ============================================================

st.set_page_config(
    page_title="CampusKart | Smart Stationery",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.block-container {max-width: 1250px; padding-top: 2rem;}
.hero {text-align:center; padding:55px 20px 30px;}
.hero h1 {font-size:52px; margin-bottom:8px; font-weight:800;}
.hero .tagline {font-size:24px; font-weight:700; margin-bottom:20px;}
.hero .copy {max-width:780px; margin:auto; font-size:18px; line-height:1.75;}
.words {text-align:center; font-size:19px; font-weight:800; margin:24px 0 34px;}
.section-title {text-align:center; font-size:28px; font-weight:800; margin-top:20px;}
.product-card {padding:14px; border:1px solid #e8e8e8; border-radius:16px; min-height:120px;}
.info-card {padding:20px; border:1px solid #e8e8e8; border-radius:16px; text-align:center; min-height:145px;}
.admin-banner {padding:18px 22px; border-radius:15px; border:1px solid #e5e5e5; margin-bottom:20px;}
.small {color:#707070; font-size:13px;}
</style>
""", unsafe_allow_html=True)

# ============================================================
# CUSTOMER PAGES
# ============================================================

def page_customer_hero():
    """Customer-only first page opened from QR."""
    st.markdown("""
    <div class="hero">
        <h1>🎓 Welcome SVC Digitalized Stationary</h1>
        <div class="tagline">Smart Stationery. Smarter Resources.</div>
        <div class="copy">
            <b>Learn.</b> <b>Educate.</b> <b>Elevate.</b><br>
            A smarter campus where stationery is easy to access,
            resources are used responsibly, and every purchase helps
            institutions make better decisions.
        </div>
    </div>
    <div class="words">📚 LEARN &nbsp; • &nbsp; 🎓 EDUCATE &nbsp; • &nbsp; 🚀 ELEVATE</div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="section-title">Everything You Need, In One Campus Store</div>', unsafe_allow_html=True)
    st.write("")

    c1, c2, c3, c4 = st.columns(4)
    cards = [
        (c1, "🛍️", "Digital Marketplace", "Find everyday stationery quickly."),
        (c2, "📦", "Live Inventory", "Know what is available before ordering."),
        (c3, "📊", "Smart Analytics", "Every purchase contributes to better decisions."),
        (c4, "🎯", "Smart Procurement", "Institutions replenish based on real demand."),
    ]
    for col, icon, title, text in cards:
        with col:
            st.markdown(f'<div class="info-card"><div style="font-size:32px">{icon}</div><b>{title}</b><br><span class="small">{text}</span></div>', unsafe_allow_html=True)

    st.write("")
    st.markdown('<div class="section-title">Ready to Shop?</div>', unsafe_allow_html=True)
    st.caption("Create your campus account once, then use the same College ID and password for future purchases.")

    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        if st.button("🛍️ START SHOPPING", type="primary", use_container_width=True):
            st.session_state.page = "customer_auth"
            st.session_state.customer_hero = False
            st.rerun()

    st.markdown("---")
    st.markdown("<div style='text-align:center'><b>QR → Welcome → Login/Register → Shopping → Cart → Checkout → Inventory Update → Analytics → Smart Reorder</b></div>", unsafe_allow_html=True)


def page_customer_auth():
    st.title("🛍️ CampusKart Shopping")
    st.caption("Sign in with your College ID or register as a new campus user.")

    if st.button("← Back to Welcome"):
        st.session_state.customer_hero = True
        st.rerun()

    login_tab, register_tab = st.tabs(["🔑 Existing User Login", "📝 New User Registration"])

    with login_tab:
        with st.form("customer_login"):
            college_id = st.text_input("College ID / Register Number", placeholder="Example: RBSD2419").strip().upper()
            password = st.text_input("Password", type="password")
            submit = st.form_submit_button("Login & Continue Shopping", type="primary", use_container_width=True)

        if submit:
            if not college_id or not password:
                st.error("Enter your College ID and password.")
            else:
                conn = get_db()
                user = conn.execute("SELECT * FROM users WHERE college_id = ?", (college_id,)).fetchone()
                conn.close()
                if not user:
                    st.error("College ID is not registered. Please use the New User Registration tab.")
                elif not user["password_hash"]:
                    st.warning("This older account has no password. Please register a new College ID or complete its account setup.")
                elif not verify_password(password, user["password_hash"]):
                    st.error("Incorrect password.")
                else:
                    conn = get_db()
                    conn.execute("UPDATE users SET login_count = COALESCE(login_count, 0) + 1, last_login = ? WHERE id = ?", (datetime.now().isoformat(timespec="seconds"), user["id"]))
                    conn.commit()
                    conn.close()
                    st.session_state.user_id = user["id"]
                    st.session_state.page = "products"
                    st.rerun()

    with register_tab:
        with st.form("customer_register"):
            reg_id = st.text_input("College ID / Register Number", placeholder="Example: RBSD2419").strip().upper()
            name = st.text_input("Full Name", placeholder="Example: Vidyashree M")
            role = st.selectbox("Role", ["Student", "Faculty"])
            department = st.text_input("Department", placeholder="Example: Data Science")
            password = st.text_input("Create Password", type="password")
            confirm = st.text_input("Confirm Password", type="password")
            submit = st.form_submit_button("Create Account & Start Shopping", type="primary", use_container_width=True)

        if submit:
            reg_id = reg_id.strip().upper()
            name = name.strip()
            department = department.strip()
            if not all([reg_id, name, department, password, confirm]):
                st.error("Please fill all registration fields.")
            elif len(password) < 6:
                st.error("Password must contain at least 6 characters.")
            elif password != confirm:
                st.error("Passwords do not match.")
            else:
                conn = get_db()
                existing = conn.execute("SELECT id FROM users WHERE college_id = ?", (reg_id,)).fetchone()
                if existing:
                    conn.close()
                    st.error("This College ID is already registered. Please use the login tab.")
                else:
                    cur = conn.execute("""
                        INSERT INTO users(college_id, name, role, department, password_hash, created_at, login_count, last_login)
                        VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                    """, (reg_id, name, role, department, hash_password(password), datetime.now().isoformat(timespec="seconds"), datetime.now().isoformat(timespec="seconds")))
                    conn.commit()
                    user_id = cur.lastrowid
                    conn.close()
                    st.session_state.user_id = user_id
                    st.session_state.page = "products"
                    st.success("Account created successfully.")
                    st.rerun()


def page_products():
    user = get_current_user()
    if not user:
        st.session_state.page = "customer_auth"
        st.rerun()
        return

    st.title("🛍️ Stationery Marketplace")
    st.caption(f"Welcome, {user['name']} • {user['department']}")

    if st.session_state.order_success:
        order_id, total = st.session_state.order_success
        st.success(f"Order #{order_id} confirmed • {money(total)} • Inventory updated successfully.")
        if st.button("Close order message"):
            st.session_state.order_success = None
            st.rerun()

    top1, top2 = st.columns([4, 1])
    with top1:
        search = st.text_input("🔎 Search stationery", placeholder="Search notebook, pen, paper...", value=st.session_state.search)
        st.session_state.search = search
    with top2:
        if st.button(f"🛒 Cart ({cart_count()})", use_container_width=True):
            st.session_state.page = "cart"
            st.rerun()

    conn = get_db()
    categories = [r["category"] for r in conn.execute("SELECT DISTINCT category FROM products ORDER BY category").fetchall()]
    rows = conn.execute("SELECT * FROM products ORDER BY category, name").fetchall()
    conn.close()

    selected_category = st.selectbox("Category", ["All"] + categories)
    products = [dict(row) for row in rows]

    f1, f2 = st.columns(2)
    with f1:
        sort_by = st.selectbox("Sort by", ["Recommended", "Price: Low to High", "Price: High to Low", "Name A-Z", "Stock Available"], key="product_sort")
    with f2:
        stock_filter = st.selectbox("Stock", ["All", "In Stock Only", "Low Stock", "Out of Stock"], key="stock_filter")

    if selected_category != "All":
        products = [p for p in products if p["category"] == selected_category]
    if search.strip():
        # Search across all useful product text so queries such as
        # "pen", "writing", "paper", or a description keyword work.
        q = " ".join(search.strip().lower().split())
        terms = q.split()
        def matches(product):
            searchable = " ".join([
                str(product.get("name") or ""),
                str(product.get("category") or ""),
                str(product.get("description") or "")
            ]).lower()
            return all(term in searchable for term in terms)
        products = [p for p in products if matches(p)]

    st.markdown("### Available Stationery")
    if not products:
        st.info("No products matched your search.")
        return

    columns = st.columns(3)
    for index, product in enumerate(products):
        with columns[index % 3]:
            with st.container(border=True):
                if product["image_url"]:
                    st.image(product["image_url"], use_container_width=True)
                st.markdown(f"### {product['name']}")
                st.caption(product["category"])
                st.write(product["description"])
                st.markdown(f"**{money(product['price'])}**  •  {stock_badge(product)}")
                st.caption(f"Available: {product['stock']} | Max/order: {product['max_quantity']}")

                if product["stock"] > 0:
                    qty = st.number_input(
                        "Quantity",
                        min_value=1,
                        max_value=max(1, min(int(product["stock"]), int(product["max_quantity"]))),
                        value=1,
                        step=1,
                        key=f"qty_{product['id']}",
                    )
                    if st.button("Add to Cart", key=f"add_{product['id']}", type="primary", use_container_width=True):
                        ok, message = add_to_cart(product["id"], qty)
                        if ok:
                            st.success(message)
                        else:
                            st.error(message)
                else:
                    st.button("Out of Stock", key=f"out_{product['id']}", disabled=True, use_container_width=True)

    st.markdown("---")
    st.info("💡 Smart recommendation: your purchases are not only orders — they become consumption data used by CampusKart's inventory and procurement intelligence.")


def page_cart():
    user = get_current_user()
    if not user:
        st.session_state.page = "customer_auth"
        st.rerun()
        return

    st.title("🛒 Your Cart")
    if st.button("← Continue Shopping"):
        st.session_state.page = "products"
        st.rerun()

    if not st.session_state.cart:
        st.info("Your cart is empty.")
        if st.button("Browse Products", type="primary"):
            st.session_state.page = "products"
            st.rerun()
        return

    for index, item in enumerate(st.session_state.cart):
        product = get_product(item["product_id"])
        if not product:
            continue
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([2.5, 1, 1, 1])
            with c1:
                st.write(f"**{item['name']}**")
                st.caption(f"{money(item['price'])} each")
            with c2:
                new_qty = st.number_input(
                    "Qty",
                    min_value=1,
                    max_value=max(1, min(int(product["stock"]), int(product["max_quantity"]))),
                    value=int(item["quantity"]),
                    key=f"cart_qty_{item['product_id']}",
                )
            with c3:
                st.write(f"**{money(item['price'] * new_qty)}**")
            with c4:
                if st.button("Remove", key=f"remove_{item['product_id']}"):
                    st.session_state.cart.pop(index)
                    st.rerun()
            if new_qty != item["quantity"]:
                item["quantity"] = int(new_qty)

    st.markdown("---")
    c1, c2 = st.columns([3, 1])
    with c1:
        st.markdown(f"### Total: {money(cart_total())}")
    with c2:
        if st.button("Proceed to Checkout →", type="primary", use_container_width=True):
            st.session_state.page = "checkout"
            st.rerun()


def make_invoice_text(order_id):
    conn = get_db()
    order = conn.execute("""SELECT o.*, u.name, u.college_id
        FROM orders o JOIN users u ON o.user_id=u.id WHERE o.id=?""", (order_id,)).fetchone()
    items = conn.execute("""SELECT p.name, oi.quantity, oi.price
        FROM order_items oi JOIN products p ON p.id=oi.product_id WHERE oi.order_id=?""", (order_id,)).fetchall()
    conn.close()
    if not order:
        return "Invoice not found."
    lines = ["========================================", "      SVC DIGITALIZED STATIONARY", "             CAMPUSKART",
             "========================================", f"Order ID : CK{order['id']:05d}", f"Customer : {order['name']}",
             f"College ID: {order['college_id']}", f"Department: {order['department']}", f"Date     : {order['created_at']}",
             "----------------------------------------"]
    for item in items:
        lines.append(f"{item['name']} x {item['quantity']}  ₹{item['price'] * item['quantity']:.2f}")
    lines += ["----------------------------------------", f"TOTAL    : ₹{order['total']:.2f}",
              f"Payment  : {order['payment_method']}", f"Status   : {order['status']}", "========================================",
              "Thank you for using CampusKart!", "Smart Stationery. Smarter Resources."]
    return "\n".join(lines)


def page_checkout():
    user = get_current_user()
    if not user:
        st.session_state.page = "customer_auth"
        st.rerun()
        return
    if not st.session_state.cart:
        st.session_state.page = "products"
        st.rerun()
        return

    st.title("💳 Checkout")
    st.write(f"**Customer:** {user['name']}  |  **College ID:** {user['college_id']}  |  **Department:** {user['department']}")

    st.markdown("### Order Summary")
    for item in st.session_state.cart:
        st.write(f"{item['name']} × {item['quantity']} = **{money(item['price'] * item['quantity'])}**")
    st.markdown(f"## Total: {money(cart_total())}")

    payment = st.radio("Payment Method (Demo)", ["UPI Demo", "Card Demo", "Campus Wallet Demo"])
    st.caption("This is a hackathon demonstration. No real payment is processed.")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("← Back to Cart", use_container_width=True):
            st.session_state.page = "cart"
            st.rerun()
    with c2:
        if st.button("✅ Confirm Demo Payment & Place Order", type="primary", use_container_width=True):
            ok, message = process_order(payment)
            if ok:
                st.success(message)
                order_info = st.session_state.get("order_success")
                if order_info:
                    order_id, total = order_info
                    st.download_button("🧾 Download Digital Invoice", data=make_invoice_text(order_id),
                                       file_name=f"CampusKart_Invoice_{order_id}.txt", mime="text/plain",
                                       use_container_width=True)
                if st.button("🛍️ Continue Shopping", type="primary"):
                    st.session_state.page = "products"
                    st.rerun()
            else:
                st.error(message)


def page_profile():
    user = get_current_user()
    if not user:
        st.session_state.page = "customer_auth"
        st.rerun()
        return

    st.title("👤 My CampusKart")
    conn = get_db()
    stats = conn.execute("""
        SELECT COUNT(*) AS orders, COALESCE(SUM(total), 0) AS spent
        FROM orders WHERE user_id = ?
    """, (user["id"],)).fetchone()
    items = conn.execute("""
        SELECT COALESCE(SUM(oi.quantity), 0) AS items
        FROM order_items oi JOIN orders o ON oi.order_id = o.id
        WHERE o.user_id = ?
    """, (user["id"],)).fetchone()
    recent = conn.execute("""
        SELECT id, total, payment_method, status, department, created_at
        FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT 10
    """, (user["id"],)).fetchall()
    conn.close()

    a, b, c = st.columns(3)
    a.metric("Orders", stats["orders"])
    b.metric("Items Purchased", items["items"])
    c.metric("Total Spent", money(stats["spent"]))

    st.subheader("Profile")
    st.write(f"**College ID:** {user['college_id']}")
    st.write(f"**Role:** {user['role']}")
    st.write(f"**Department:** {user['department']}")

    st.subheader("Recent Orders")
    if recent:
        df = pd.DataFrame([dict(r) for r in recent])
        df["total"] = df["total"].map(money)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No orders yet.")

# ============================================================
# DESKTOP ADMIN PAGES
# ============================================================

def page_admin_login():
    st.markdown('<div class="admin-banner"><h1>🔐 CampusKart Administrator Portal</h1><p>Protected desktop management for inventory, orders, analytics and smart procurement.</p></div>', unsafe_allow_html=True)

    left, center, right = st.columns([1, 2, 1])
    with center:
        st.subheader("Administrator Login")
        with st.form("admin_login_form"):
            admin_id = st.text_input("Admin ID", placeholder="ADMIN24")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login to Admin Portal", type="primary", use_container_width=True)

        if submitted:
            if verify_admin_credentials(admin_id, password):
                st.session_state.admin = True
                st.session_state.page = "admin_dashboard"
                st.rerun()
            else:
                st.error("Invalid Admin ID or password.")

        st.caption("Authorized administrator access only.")


def page_admin_dashboard():
    if not st.session_state.admin:
        st.session_state.page = "admin_login"
        st.rerun()
        return

    st.title("📊 SVC Digitalized Stationary — Admin Dashboard")
    st.caption("Complete desktop management for customers, sales, inventory, analytics and smart procurement.")

    # QR is available to the administrator, but it is not part of the customer page.
    with st.expander("📱 Customer QR — scan this from a phone", expanded=True):
        c1, c2 = st.columns([1, 2])
        with c1:
            st.image(make_qr_bytes(), width=300)
        with c2:
            st.markdown("### Scan to open the customer experience")
            st.write("The QR is **customer-only**. It opens the Welcome SVC Digitalized Stationary page on a phone.")
            st.code(get_customer_url(), language="text")
            st.caption("Phone and laptop must be connected to the same Wi-Fi/network.")

    conn = get_db()
    today = date.today().isoformat()
    today_data = conn.execute("""
        SELECT COUNT(*) AS orders, COALESCE(SUM(total), 0) AS sales
        FROM orders WHERE DATE(created_at) = ?
    """, (today,)).fetchone()
    total_orders = conn.execute("SELECT COUNT(*) AS c FROM orders").fetchone()["c"]
    total_users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    total_products = conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
    total_stock = conn.execute("SELECT COALESCE(SUM(stock),0) AS c FROM products").fetchone()["c"]
    low_stock = conn.execute("SELECT COUNT(*) AS c FROM products WHERE stock <= reorder_level").fetchone()["c"]
    out_stock = conn.execute("SELECT COUNT(*) AS c FROM products WHERE stock = 0").fetchone()["c"]
    all_sales = conn.execute("SELECT COALESCE(SUM(total),0) AS x FROM orders").fetchone()["x"]
    recent_orders = conn.execute("""
        SELECT o.id, u.college_id, u.name, o.department, o.total,
               o.payment_method, o.status, o.created_at
        FROM orders o JOIN users u ON o.user_id=u.id
        ORDER BY o.id DESC LIMIT 10
    """).fetchall()
    conn.close()

    a, b, c, d, e = st.columns(5)
    a.metric("Today's Orders", today_data["orders"])
    b.metric("Today's Sales", money(today_data["sales"]))
    c.metric("Total Stock Units", total_stock)
    d.metric("Low / Critical", low_stock)
    e.metric("Efficiency", f"{calculate_efficiency()}%")

    a, b, c, d = st.columns(4)
    a.metric("Registered Users", total_users)
    b.metric("Products", total_products)
    c.metric("Out of Stock", out_stock)
    d.metric("All-Time Sales", money(all_sales))

    # --------------------------------------------------------
    # TODAY'S ANALYSIS + SALES REPORT
    # --------------------------------------------------------
    st.markdown("## 📊 Today’s Total Analysis")
    conn = get_db()
    today = date.today().isoformat()
    today_stats = conn.execute("""
        SELECT COUNT(*) AS orders, COALESCE(SUM(total),0) AS sales,
               COALESCE(SUM((SELECT SUM(quantity) FROM order_items WHERE order_id=orders.id)),0) AS units
        FROM orders WHERE DATE(created_at) = ?
    """, (today,)).fetchone()
    today_logins = conn.execute("SELECT COALESCE(SUM(login_count),0) AS c FROM users").fetchone()["c"]
    active_users_today = conn.execute("SELECT COUNT(*) AS c FROM users WHERE DATE(last_login) = ?", (today,)).fetchone()["c"]
    low_items_today = conn.execute("SELECT COUNT(*) AS c FROM products WHERE stock <= reorder_level").fetchone()["c"]
    daily_sales = conn.execute("""
        SELECT DATE(created_at) AS sale_date, COUNT(*) AS orders, COALESCE(SUM(total),0) AS sales
        FROM orders
        WHERE DATE(created_at) >= DATE('now','-6 day')
        GROUP BY DATE(created_at)
        ORDER BY sale_date
    """).fetchall()
    payment_sales = conn.execute("""
        SELECT payment_method, COUNT(*) AS orders, COALESCE(SUM(total),0) AS sales
        FROM orders GROUP BY payment_method ORDER BY sales DESC
    """).fetchall()
    top_sales = conn.execute("""
        SELECT p.name, COALESCE(SUM(oi.quantity),0) AS units
        FROM order_items oi JOIN products p ON p.id=oi.product_id
        GROUP BY p.id ORDER BY units DESC LIMIT 8
    """).fetchall()
    conn.close()

    t1, t2, t3, t4, t5 = st.columns(5)
    t1.metric("Today’s Orders", int(today_stats["orders"]))
    t2.metric("Today’s Sales", money(today_stats["sales"]))
    t3.metric("Units Sold", int(today_stats["units"]))
    t4.metric("Users Active Today", int(active_users_today))
    t5.metric("Low Stock Items", int(low_items_today))

    # Show the sales report when the system has recorded more than one login.
    if today_logins > 1 or int(today_stats["orders"]) > 1:
        st.markdown("### 📈 Sales Report")
        r1, r2 = st.columns(2)
        with r1:
            sdf = pd.DataFrame([dict(row) for row in daily_sales])
            if not sdf.empty:
                sdf["sale_date"] = pd.to_datetime(sdf["sale_date"])
                st.caption("Sales for the last 7 days")
                st.line_chart(sdf.set_index("sale_date")["sales"])
            else:
                st.info("Sales graph will appear after transactions are recorded.")
        with r2:
            pdf = pd.DataFrame([dict(row) for row in payment_sales])
            if not pdf.empty:
                st.caption("Sales by payment method")
                st.bar_chart(pdf.set_index("payment_method")["sales"])
            else:
                st.info("Payment report will appear after the first sale.")

        topdf = pd.DataFrame([dict(row) for row in top_sales])
        if not topdf.empty:
            st.caption("Top-selling stationery")
            st.bar_chart(topdf.set_index("name")["units"])
    else:
        st.info("Sales report graphs will appear after the system records more than one user login or more than one order.")

    conn = get_db()
    total_products_eff = conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
    low_eff = conn.execute("SELECT COUNT(*) AS c FROM products WHERE stock <= reorder_level").fetchone()["c"]
    excess_eff = conn.execute("SELECT COUNT(*) AS c FROM products WHERE stock > monthly_usage * 2").fetchone()["c"]
    conn.close()
    efficiency = 100 if not total_products_eff else max(0, min(100, int(100 - (low_eff / total_products_eff) * 35 - (excess_eff / total_products_eff) * 20)))
    st.markdown("### ♻️ Resource Efficiency Score")
    e1,e2=st.columns([1,3]); e1.metric("Efficiency",f"{efficiency}/100"); e2.progress(efficiency/100,text="Healthy resource utilisation" if efficiency>=75 else "Needs procurement optimisation")

    st.markdown("### 🧠 Smart Resource Insight")
    st.info("Every customer purchase reduces live stock and creates a stock log. That same transaction becomes consumption data for analytics and need-based procurement.")

    st.markdown("### 🎯 Smart Procurement Recommendations")
    conn = get_db()
    products = [dict(row) for row in conn.execute("SELECT * FROM products ORDER BY stock ASC").fetchall()]
    conn.close()
    recommendations = 0
    for product in products:
        status = stock_status(product)
        if status != "AVAILABLE" or product["stock"] > max(product["monthly_usage"], 1) * 2:
            recommendations += 1
            with st.expander(f"{stock_badge(product)} — {product['name']}"):
                st.write(reorder_recommendation(product))
                st.write(f"Current stock: **{product['stock']}** | Reorder level: **{product['reorder_level']}** | Monthly usage: **{product['monthly_usage']}**")
    if recommendations == 0:
        st.success("All products are currently within healthy stock conditions.")

    st.markdown("### 🧾 Recent Customer Orders")
    if recent_orders:
        df = pd.DataFrame([dict(row) for row in recent_orders])
        df["total"] = df["total"].map(money)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No customer orders yet. Scan the QR from a phone to create a live transaction.")


def page_inventory():
    if not st.session_state.admin:
        st.session_state.page = "admin_login"
        st.rerun()
        return

    st.title("📦 Inventory Management")
    st.caption("Live stock is changed automatically when customers place orders.")

    conn = get_db()
    products = [dict(row) for row in conn.execute("SELECT * FROM products ORDER BY category, name").fetchall()]
    conn.close()

    for product in products:
        with st.container(border=True):
            c1, c2, c3, c4, c5 = st.columns([2.2, 1, 1, 1.2, 1.2])
            with c1:
                st.write(f"**{product['name']}**")
                st.caption(product["category"])
            with c2:
                st.write(f"Stock: **{product['stock']}**")
                st.caption(stock_badge(product))
            with c3:
                st.write(f"Reorder: **{product['reorder_level']}**")
                st.caption(f"Usage: {product['monthly_usage']}/month")
            with c4:
                add_qty = st.number_input("Receive", min_value=0, max_value=5000, value=0, step=1, key=f"receive_{product['id']}")
            with c5:
                if st.button("Add Stock", key=f"stock_btn_{product['id']}", type="primary"):
                    if add_qty <= 0:
                        st.warning("Enter a quantity greater than 0.")
                    else:
                        conn = get_db()
                        now = datetime.now().isoformat(timespec="seconds")
                        conn.execute("UPDATE products SET stock = stock + ? WHERE id = ?", (int(add_qty), product["id"]))
                        conn.execute("""
                            INSERT INTO stock_logs(product_id, change_quantity, reason, created_at)
                            VALUES (?, ?, ?, ?)
                        """, (product["id"], int(add_qty), "Admin Procurement / Stock Received", now))
                        conn.commit()
                        conn.close()
                        st.success(f"Added {add_qty} units to {product['name']}.")
                        st.rerun()

    st.markdown("### Recent Stock Movement")
    conn = get_db()
    logs = conn.execute("""
        SELECT p.name, sl.change_quantity, sl.reason, sl.created_at
        FROM stock_logs sl JOIN products p ON sl.product_id=p.id
        ORDER BY sl.id DESC LIMIT 30
    """).fetchall()
    conn.close()
    if logs:
        st.dataframe(pd.DataFrame([dict(row) for row in logs]), use_container_width=True, hide_index=True)
    else:
        st.info("No stock movements recorded yet.")


def page_admin_orders():
    if not st.session_state.admin:
        st.session_state.page = "admin_login"
        st.rerun()
        return
    st.title("📋 Order Management")
    st.caption("Monitor customer orders and update their status from the protected desktop portal.")
    conn = get_db()
    orders = conn.execute("""SELECT o.id, u.name AS customer, u.college_id, o.department, o.total,
        o.payment_method, o.status, o.created_at,
        COALESCE((SELECT SUM(quantity) FROM order_items WHERE order_id=o.id),0) AS units
        FROM orders o JOIN users u ON o.user_id=u.id ORDER BY o.id DESC LIMIT 100""").fetchall()
    conn.close()
    if not orders:
        st.info("No customer orders yet.")
        return
    statuses = ["Confirmed", "Processing", "Ready", "Completed", "Cancelled"]
    for order in orders:
        with st.container(border=True):
            c1,c2,c3,c4=st.columns([1.3,2.4,1.4,1.7])
            with c1:
                st.write(f"**CK{order['id']:05d}**")
                st.caption(order["created_at"])
            with c2:
                st.write(f"**{order['customer']}**")
                st.caption(f"{order['college_id']} • {order['department']} • {order['units']} units")
            with c3:
                st.write(f"**{money(order['total'])}**")
                st.caption(order["payment_method"])
            with c4:
                current=order["status"] if order["status"] in statuses else "Confirmed"
                new_status=st.selectbox("Status",statuses,index=statuses.index(current),key=f"order_status_{order['id']}")
                if new_status != order["status"] and st.button("Update",key=f"order_update_{order['id']}"):
                    conn=get_db(); conn.execute("UPDATE orders SET status=? WHERE id=?",(new_status,order["id"])); conn.commit(); conn.close(); st.rerun()


def page_analytics():
    if not st.session_state.admin:
        st.session_state.page = "admin_login"
        st.rerun()
        return

    st.title("📈 Consumption & Resource Analytics")
    conn = get_db()

    consumption = conn.execute("""
        SELECT p.name, p.category, p.stock, p.reorder_level, p.monthly_usage,
               COALESCE(SUM(oi.quantity), 0) AS purchased_units
        FROM products p
        LEFT JOIN order_items oi ON p.id = oi.product_id
        GROUP BY p.id
        ORDER BY purchased_units DESC
    """).fetchall()

    departments = conn.execute("""
        SELECT department, COUNT(*) AS orders,
               COALESCE(SUM(total),0) AS spending,
               COALESCE(SUM((SELECT SUM(quantity) FROM order_items WHERE order_id=orders.id)),0) AS units
        FROM orders
        GROUP BY department
        ORDER BY spending DESC
    """).fetchall()

    top_products = conn.execute("""
        SELECT p.name, COALESCE(SUM(oi.quantity),0) AS units
        FROM products p
        LEFT JOIN order_items oi ON p.id=oi.product_id
        GROUP BY p.id
        ORDER BY units DESC LIMIT 10
    """).fetchall()

    logs = conn.execute("""
        SELECT p.name, sl.change_quantity, sl.reason, sl.created_at
        FROM stock_logs sl JOIN products p ON sl.product_id=p.id
        ORDER BY sl.id DESC LIMIT 30
    """).fetchall()
    conn.close()

    df = pd.DataFrame([dict(row) for row in consumption])
    if not df.empty:
        st.subheader("Product Consumption")
        st.bar_chart(df.set_index("name")[["monthly_usage", "purchased_units"]])
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.subheader("Consumption Alerts")
        alerts = []
        for _, row in df.iterrows():
            monthly = max(int(row["monthly_usage"]), 1)
            purchased = int(row["purchased_units"])
            if purchased > monthly * 1.5:
                alerts.append({"Product": row["name"], "Alert": "⚠️ High / irregular usage", "Observed": purchased, "Baseline": monthly})
        if alerts:
            st.dataframe(pd.DataFrame(alerts), use_container_width=True, hide_index=True)
        else:
            st.success("No major high-consumption pattern detected from current transaction data.")

    st.subheader("Department-wise Consumption")
    ddf = pd.DataFrame([dict(row) for row in departments])
    if not ddf.empty:
        st.bar_chart(ddf.set_index("department")[["orders", "units"]])
        st.dataframe(ddf, use_container_width=True, hide_index=True)
    else:
        st.info("No department transactions yet.")

    st.subheader("Top Stationery")
    tdf = pd.DataFrame([dict(row) for row in top_products])
    if not tdf.empty:
        st.bar_chart(tdf.set_index("name"))

    st.subheader("Sales Trend")
    conn=get_db()
    sales_trend=conn.execute("""SELECT DATE(created_at) AS sale_date, COALESCE(SUM(total),0) AS sales
        FROM orders WHERE DATE(created_at)>=DATE('now','-29 day') GROUP BY DATE(created_at) ORDER BY sale_date""").fetchall()
    conn.close()
    sales_df=pd.DataFrame([dict(r) for r in sales_trend])
    if not sales_df.empty:
        sales_df["sale_date"]=pd.to_datetime(sales_df["sale_date"])
        st.line_chart(sales_df.set_index("sale_date")["sales"])
        w1,w2=st.columns(2); w1.metric("Last 7 Days Sales",money(float(sales_df.tail(7)["sales"].sum()))); w2.metric("Last 30 Days Sales",money(float(sales_df["sales"].sum())))
    else:
        st.info("Sales trend will appear after customer purchases.")

    st.subheader("Recent Stock Logs")
    ldf = pd.DataFrame([dict(row) for row in logs])
    if not ldf.empty:
        st.dataframe(ldf, use_container_width=True, hide_index=True)

# ============================================================
# DESKTOP SIDEBAR
# ============================================================

def render_admin_sidebar():
    with st.sidebar:
        st.markdown("# 🎓 CampusKart")
        st.caption("Smart Stationery. Smarter Resources.")
        st.divider()

        if st.session_state.admin:
            st.success("ADMIN PORTAL ACTIVE")
            if st.button("📊 Dashboard", use_container_width=True):
                st.session_state.page = "admin_dashboard"
                st.rerun()
            if st.button("📱 Customer QR", use_container_width=True):
                st.session_state.page = "qr"
                st.rerun()
            if st.button("📦 Inventory", use_container_width=True):
                st.session_state.page = "inventory"
                st.rerun()
            if st.button("📋 Orders", use_container_width=True):
                st.session_state.page = "admin_orders"
                st.rerun()
            if st.button("📈 Analytics", use_container_width=True):
                st.session_state.page = "analytics"
                st.rerun()
            st.divider()
            if st.button("🚪 Admin Logout", use_container_width=True):
                admin_logout()
        else:
            st.success("📱 CUSTOMER QR READY")
            st.caption("Scan the QR with a phone to open the customer shopping experience.")
            if st.button("📱 Show Customer QR", type="primary", use_container_width=True):
                st.session_state.page = "qr"
                st.rerun()
            st.divider()
            st.caption("Administrator access is protected.")
            if st.button("🔐 Administrator Login", use_container_width=True):
                st.session_state.page = "admin_login"
                st.rerun()

# ============================================================
# DESKTOP QR PAGE
# ============================================================

def page_qr():
    # IMPORTANT: This desktop QR page is intentionally visible without
    # administrator login. The QR destination itself is customer-only.
    # The admin portal remains protected behind the Administrator Login button.
    st.title("🎓 CampusKart")
    st.markdown("## 📱 CUSTOMER QR READY")
    st.write("Scan this QR with a phone to open the customer shopping experience.")
    st.info("💡 The QR is ONLY for customers (students/faculty). It does not open the administrator portal.")

    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.image(make_qr_bytes(), width=430)
        st.markdown("### 📲 Scan with your phone camera")
        st.caption("Laptop and phone must be connected to the same Wi-Fi/network.")
        st.code(get_customer_url(), language="text")

    st.success("Customer phone flow: Welcome SVC Digitalized Stationary → Start Shopping → Login/Register → Products → Cart → Billing/Checkout → Payment → Order Confirmation.")

    st.markdown("---")
    st.markdown("### 🔐 CampusKart Administrator Portal")
    st.write("Protected desktop management for inventory, orders, analytics and smart procurement.")
    if st.session_state.admin:
        st.success("Administrator is logged in. Use the sidebar to manage CampusKart.")
    else:
        st.caption("Administrator access is protected. Use **Administrator Login** in the sidebar.")

# ============================================================
# MAIN ROUTER
# ============================================================

query_mode = st.query_params.get("mode")

# Never render the desktop/admin sidebar on the QR customer route.
if query_mode != "customer":
    render_admin_sidebar()

# CRITICAL SEPARATION:
# ?mode=customer is the ONLY route that can enter the customer experience.
# The QR never exposes the admin portal.
if query_mode == "customer":
    if st.session_state.user_id:
        page = st.session_state.page
        if page == "customer_auth":
            page_customer_auth()
        elif page == "products":
            page_products()
        elif page == "cart":
            page_cart()
        elif page == "checkout":
            page_checkout()
        elif page == "profile":
            page_profile()
        else:
            page_products()
    else:
        if st.session_state.customer_hero:
            page_customer_hero()
        else:
            page_customer_auth()
else:
    # Desktop shows the CUSTOMER QR by default.
    # Customer shopping is available only through ?mode=customer.
    if st.session_state.page in {"products", "cart", "checkout", "profile", "customer_auth"}:
        st.session_state.page = "admin_dashboard" if st.session_state.admin else "admin_login"

    if st.session_state.page == "admin_login":
        page_admin_login()
    elif st.session_state.page == "admin_dashboard":
        page_admin_dashboard()
    elif st.session_state.page == "qr":
        page_qr()
    elif st.session_state.page == "inventory":
        page_inventory()
    elif st.session_state.page == "admin_orders":
        page_admin_orders()
    elif st.session_state.page == "analytics":
        page_analytics()
    else:
        st.session_state.page = "qr"
        st.rerun()
