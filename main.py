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

PRICE_ID = "price_1SyJzBEHLxArJ4j1jId0Hnsc"  # ✅ NUEVO PRICE LIVE
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
@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig,STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        print("Webhook error:", str(e))
        return JSONResponse(status_code=400, content={"error": str(e)})

    event_type = event["type"]
    data = event["data"]["object"]

    conn = sqlite3.connect(DB)
    c = conn.cursor()

    # =========================
    # ALTA SUSCRIPCIÓN
    # =========================
    if event_type == "checkout.session.completed":
        email = data["customer_details"]["email"]
        customer_id = data["customer"]
        subscription_id = data["subscription"]

        print("Nueva suscripción:", email)

        sub = stripe.Subscription.retrieve(subscription_id)

        c.execute("""
            INSERT INTO subscriptions 
            (email, stripe_customer_id, stripe_subscription_id, status, current_period_end)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                stripe_customer_id = excluded.stripe_customer_id,
                stripe_subscription_id = excluded.stripe_subscription_id,
                status = excluded.status,
                current_period_end = excluded.current_period_end
        """, (
            email,
            customer_id,
            subscription_id,
            sub["status"],
            sub["current_period_end"]
        ))

    # =========================
    # RENOVACIÓN CORRECTA
    # =========================
    elif event_type == "invoice.paid":
        customer_id = data["customer"]

        c.execute("""
            UPDATE subscriptions
            SET status='active'
            WHERE stripe_customer_id=?
        """, (customer_id,))

    # =========================
    # IMPAGO
    # =========================
    elif event_type == "invoice.payment_failed":
        customer_id = data["customer"]

        c.execute("""
            UPDATE subscriptions
            SET status='past_due'
            WHERE stripe_customer_id=?
        """, (customer_id,))

    # =========================
    # CANCELACIÓN
    # =========================
    elif event_type == "customer.subscription.deleted":
        subscription_id = data["id"]

        c.execute("""
            UPDATE subscriptions
            SET status='canceled'
            WHERE stripe_subscription_id=?
        """, (subscription_id,))

    conn.commit()
    conn.close()

    return {"status": "ok"}
@app.get("/premium-check/{email}")
def premium_check(email: str):
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
        SELECT status FROM subscriptions WHERE email=?
    """, (email,))

    row = c.fetchone()
    conn.close()

    if not row:
        return {"active": False}

    return {"active": row[0] == "active"}
