"""Thin WhatsApp Cloud API client for sending outbound messages."""

from typing import Any, Dict, Optional, Tuple

import httpx

from config import get_settings


class WhatsAppSendError(Exception):
    """Raised when the Graph API rejects or cannot send a message."""

    def __init__(self, message: str, status_code: int = 502, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.details = details or {}


def normalize_phone(raw: str) -> str:
    """Strip spaces, dashes, and a leading plus so Graph API gets digits-only E.164."""

    cleaned = (
        (raw or "")
        .strip()
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]
    return cleaned


async def send_text_message(to: str, text: str) -> Tuple[str, Dict[str, Any]]:
    """Send a text message via Cloud API.

    Returns `(wamid, raw_graph_response)`.
    """

    get_settings.cache_clear()
    settings = get_settings()
    token = (settings.WHATSAPP_TOKEN or "").strip()
    phone_number_id = (settings.WHATSAPP_PHONE_NUMBER_ID or "").strip()
    if not token or not phone_number_id:
        raise WhatsAppSendError(
            "Set WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID in .env to send outbound messages.",
            status_code=503,
        )

    recipient = normalize_phone(to)
    if not recipient.isdigit():
        raise WhatsAppSendError("Recipient phone must be digits in international format.", status_code=400)

    url = "https://graph.facebook.com/{version}/{phone_id}/messages".format(
        version=settings.GRAPH_API_VERSION,
        phone_id=phone_number_id,
    )
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }
    headers = {
        "Authorization": "Bearer {}".format(token),
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, json=payload, headers=headers)

    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text}

    if response.status_code >= 400:
        error = body.get("error") if isinstance(body, dict) else None
        message = "WhatsApp Cloud API rejected the send request."
        if isinstance(error, dict) and error.get("message"):
            message = str(error.get("message"))
        raise WhatsAppSendError(message, status_code=502, details=body if isinstance(body, dict) else {})

    messages = body.get("messages") if isinstance(body, dict) else None
    wamid = ""
    if isinstance(messages, list) and messages:
        wamid = str(messages[0].get("id") or "")
    if not wamid:
        raise WhatsAppSendError(
            "Cloud API send succeeded but returned no message id.",
            status_code=502,
            details=body if isinstance(body, dict) else {},
        )
    return wamid, body if isinstance(body, dict) else {"response": body}
