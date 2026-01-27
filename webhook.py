import os
import sqlite3
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import stripe
from dotenv import load_dotenv

load_dotenv()
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
DB = "users.db"

router = APIRouter()

@router.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, WEBHOOK_SECRET
        )
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid payload"})
    except stripe.error.SignatureVerificationError:
        return JSONResponse(status_code=400, content={"detail": "Invalid signature"})

    # Evento de pago completado
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
        print("Pago registrado para:", email)

    return JSONResponse(status_code=200, content={"detail": "success"})
