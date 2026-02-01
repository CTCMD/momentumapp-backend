import os
import secrets
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import sqlite3
from dotenv import load_dotenv
import stripe

# =========================
# CONFIG
# =========================
load_dotenv()

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

print("STRIPE_SECRET_KEY:", STRIPE_SECRET_KEY)
print("STRIPE_WEBHOOK_SECRET:", STRIPE_WEBHOOK_SECRET)

stripe.api_key = STRIPE_SECRET_KEY

PRICE_ID = "price_1Sw8XCELLxArJ4j1VOl7T92N"  # ✅ NUEVO PRICE LIVE
DB = "users.db"

# =========================
# APP
# =========================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",          # frontend local
        "https://momentumapp.site",       # frontend producción
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# DATABASE INIT
# =========================
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            is_active INTEGER DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS login_tokens (
            token TEXT PRIMARY KEY,
            email TEXT,
            expires_at TEXT
        )
    """)

    conn.commit()
    conn.close()

init_db()

# =========================
# LOGIN MAGIC LINK
# =========================
@app.post("/request-login")
def request_login(email: str):
    token = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(minutes=15)

    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute(
        "INSERT INTO login_tokens (token, email, expires_at) VALUES (?, ?, ?)",
        (token, email, expires.isoformat())
    )
    conn.commit()
    conn.close()

    login_link = f"https://momentumapp.site/magic-login/{token}"
    print("LOGIN LINK:", login_link)

    return {"message": "Login link enviado"}

@app.get("/magic-login/{token}")
def magic_login(token: str):
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("SELECT email, expires_at FROM login_tokens WHERE token=?", (token,))
    row = c.fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="Token inválido")

    email, expires_at = row

    if datetime.utcnow() > datetime.fromisoformat(expires_at):
        raise HTTPException(status_code=401, detail="Token expirado")

    c.execute("DELETE FROM login_tokens WHERE token=?", (token,))
    c.execute("SELECT is_active FROM users WHERE email=?", (email,))
    user = c.fetchone()

    conn.commit()
    conn.close()

    if not user or user[0] == 0:
        return {"login": "denied", "reason": "no subscription"}

    return {"login": "ok", "email": email}

# =========================
# STATUS
# =========================
@app.get("/status/{email}")
def status(email: str):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT is_active FROM users WHERE email=?", (email,))
    row = c.fetchone()
    conn.close()
    return {"active": bool(row and row[0] == 1)}

# =========================
# STRIPE CHECKOUT
# =========================
@app.post("/create-checkout-session")
def create_checkout_session():
    try:
        print("➡️ Creando sesión Stripe con price:", PRICE_ID)

        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": PRICE_ID, "quantity": 1}],
            success_url="https://momentumapp.site/success",
            cancel_url="https://momentumapp.site/cancel",
        )

        print("✅ Stripe session creada:", session.url)
        return {"url": session.url}

    except Exception as e:
        print("❌ ERROR STRIPE:", str(e))
        raise HTTPException(status_code=500, detail=str(e))

# =========================
# STRIPE WEBHOOK
# =========================
@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig, STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        print("❌ WEBHOOK ERROR:", str(e))
        return JSONResponse(status_code=400, content={"detail": "Webhook error"})

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = session["customer_details"]["email"]
        print("💰 Pago completado:", email)

        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute("""
            INSERT INTO users (email, is_active)
            VALUES (?, 1)
            ON CONFLICT(email) DO UPDATE SET is_active=1
        """, (email,))
        conn.commit()
        conn.close()

    return {"status": "ok"}
