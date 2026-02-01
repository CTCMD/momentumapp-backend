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

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
PRICE_ID = os.getenv("STRIPE_PRICE_ID")

DB = "users.db"

# =========================
# APP
# =========================
app = FastAPI()

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://momentumapp-backend.onrender.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# DATABASE
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
        print("➡️ Intentando crear sesión de Stripe")

        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": PRICE_ID, "quantity": 1}],
            success_url="https://momentumapp.site/success",
            cancel_url="https://momentumapp.site/cancel"
        )

        print("✅ Stripe OK:", session.url)
        return {"url": session.url}

    except Exception as e:
        print("❌ ERROR STRIPE:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


    print("✅ URL Stripe:", session.url)
    return {"url": session.url}


    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": PRICE_ID, "quantity": 1}],
        success_url="https://momentumapp.site/success",
        cancel_url="https://momentumapp.site/cancel"
    )
    return {"url": session.url}

# =========================
# STRIPE WEBHOOK
# =========================
@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig, WEBHOOK_SECRET)
    except Exception:
        return JSONResponse(status_code=400, content={"detail": "Invalid webhook"})

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = session["customer_details"]["email"]

        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute("""
            INSERT INTO users (email, is_active)
            VALUES (?, 1)
            ON CONFLICT(email) DO UPDATE SET is_active=1
        """, (email,))
        conn.commit()
        conn.close()

        print("✅ Pago completado:", email)

    return {"status": "ok"}
