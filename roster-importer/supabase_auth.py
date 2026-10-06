"""Talking to Supabase Auth, the service that keeps everyone's sign-in (email address and password).

DA Management asks it to send an invitation (a new sign-in), to send a password email (an existing sign-in), or to
move a sign-in to a new email address. It uses the service key (SUPABASE_SERVICE_ROLE_KEY), which only this server
knows. Emails are sent only when a manager has checked and confirmed the list first (Account Manager, Staff
accounts); an import never sends email by itself.
"""
import requests

import settings


def admin_headers():
    """The headers that prove to Supabase Auth that this server may ask (the service key)."""
    if not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise ValueError("SUPABASE_SERVICE_ROLE_KEY is not configured for the Account Manager.")
    return {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }


def auth_request(path, payload):
    """Sends one request to Supabase Auth (every email goes through here). Returns its answer, or raises ValueError
    with Supabase's own reason."""
    response = requests.post(f"{settings.SUPABASE_AUTH_INTERNAL_URL}{path}",
                             params={"redirect_to": settings.PASSWORD_REDIRECT_URL},
                             headers=admin_headers(), json=payload, timeout=20)
    try:
        body = response.json()
    except Exception:
        body = {"message": response.text}
    if not response.ok:
        raise ValueError(body.get("msg") or body.get("message") or body.get("error_description") or f"Auth HTTP {response.status_code}")
    return body


def invite(email, data):
    """Makes a new sign-in for this email and sends the invitation. Returns the new sign-in's id when Supabase says it
    (else None: look it up by the email)."""
    answer = auth_request("/auth/v1/invite", {"email": email, "data": data})
    return answer.get("id") or (answer.get("user") or {}).get("id")


def send_password_email(email):
    """Sends a "set your password" email to an existing sign-in."""
    auth_request("/auth/v1/recover", {"email": email})


def update_sign_in_email(user_id, email):
    """Moves an existing sign-in to a new email address. The address counts as confirmed: the password email that
    follows proves it."""
    response = requests.put(f"{settings.SUPABASE_AUTH_INTERNAL_URL}/auth/v1/admin/users/{user_id}", headers=admin_headers(),
                            json={"email": email, "email_confirm": True}, timeout=20)
    if not response.ok:
        try:
            body = response.json()
        except Exception:
            body = {}
        raise ValueError(body.get("msg") or body.get("message") or f"The sign-in email could not be changed (Auth HTTP {response.status_code}).")
    return response.json()
