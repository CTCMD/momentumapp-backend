import os
import secrets
from datetime import datetime, timedelta

import sqlite3
import stripe
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# =========================
# CONFIG
# =========================
load_dotenv()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

PRICE_ID = "price_1Sr0AeEHLxArJ4j1b4fT0Lzb"
DB = "users.db"

if not stripe.api_key or not WEBHOOK_SECRET:
    raise RuntimeError("❌ Faltan variables de entorno STRIPE_SECRET_KEY o STRIPE_WEBHOOK_SECRET")

# =========================
# APP
# =========================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
# LOGIN POR EMAIL
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

    login_link = f"http://localhost:5500/magic-login/{token}"
    print("🔑 LINK DE LOGIN:", login_link)

    return {"message": "Login link generado"}

@app.get("/magic-login/{token}")
def magic_login(token: str):
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("SELECT email, expires_at FROM login_tokens WHERE token = ?", (token,))
    row = c.fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="Token inválido")

    email, expires_at = row
    if datetime.utcnow() > datetime.fromisoformat(expires_at):
        raise HTTPException(status_code=401, detail="Token expirado")

    c.execute("DELETE FROM login_tokens WHERE token = ?", (token,))
    c.execute("SELECT is_active FROM users WHERE email = ?", (email,))
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
    c.execute("SELECT is_active FROM users WHERE email = ?", (email,))
    row = c.fetchone()
    conn.close()

    return {"active": bool(row and row[0] == 1)}

# =========================
# STRIPE CHECKOUT
# =========================
@app.post("/create-checkout-session")
def create_checkout_session():
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": PRICE_ID, "quantity": 1}],
        success_url="http://localhost:5500/success.html",
        cancel_url="http://localhost:5500/cancel.html"
    )
    return {"url": session.url}

# =========================
# STRIPE WEBHOOK
# =========================
@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=WEBHOOK_SECRET
        )
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid payload"})
    except stripe.error.SignatureVerificationError:
        return JSONResponse(status_code=400, content={"detail": "Invalid signature"})

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]

        email = (
            session.get("customer_details", {}).get("email")
            or session.get("customer_email")
        )

        if not email:
            print("⚠️ Checkout completado sin email")
            return JSONResponse(status_code=200, content={"status": "no email"})

        print("✅ Pago confirmado para:", email)

        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute("""
            INSERT INTO users (email, is_active)
            VALUES (?, 1)
            ON CONFLICT(email) DO UPDATE SET is_active = 1
        """, (email,))
        conn.commit()
        conn.close()

    return JSONResponse(status_code=200, content={"status": "ok"})
