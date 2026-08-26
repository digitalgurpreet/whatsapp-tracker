"""FastAPI entrypoint for the WhatsApp Cloud API webhook listener.

Exposes Meta's verification handshake (GET /webhook) and persists inbound
customer messages plus outbound business/rep replies (POST /webhook).
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Optional, Tuple

from fastapi import FastAPI, Query, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.exc import IntegrityError

from config import get_settings
from database import AsyncSessionLocal, init_db
from models import Message
from schemas import SendTextRequest, WebhookMessage, WebhookPayload, WebhookStatus, WebhookValue
from whatsapp_client import WhatsAppSendError, normalize_phone, send_text_message

logger = logging.getLogger("whatsapp_webhook")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

settings = get_settings()

ANSI_GREEN = "\033[92m"
ANSI_BLUE = "\033[94m"
ANSI_DIM = "\033[2m"
ANSI_YELLOW = "\033[93m"
ANSI_RESET = "\033[0m"

MEDIA_TYPES = ("image", "video", "audio", "document")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Create database tables on startup, then yield control to the ASGI server."""

    await init_db()
    logger.info("Database schema ready (%s)", settings.DATABASE_URL)
    yield


app = FastAPI(
    title="WhatsApp Cloud API Tracker",
    description="Webhook listener that logs WhatsApp Cloud API messages for later AI processing.",
    version="0.1.0",
    lifespan=lifespan,
)


def _parse_epoch(raw_timestamp: str) -> int:
    """Convert Meta's string epoch timestamp to an int, defaulting to 0 on bad input."""

    try:
        return int(raw_timestamp)
    except (TypeError, ValueError):
        return 0


def extract_content(message: WebhookMessage) -> str:
    """Pull human-readable text (or a type placeholder) from a Cloud API message object."""

    msg_type = (message.type or "unknown").lower()

    if msg_type == "text" and message.text:
        return str(message.text.get("body") or "")

    if msg_type in MEDIA_TYPES:
        media = getattr(message, msg_type, None) or {}
        caption = media.get("caption") if isinstance(media, dict) else None
        return str(caption) if caption else "[{}]".format(msg_type)

    if msg_type == "interactive" and message.interactive:
        interactive = message.interactive
        for key in ("button_reply", "list_reply"):
            reply = interactive.get(key) or {}
            title = reply.get("title") or reply.get("id")
            if title:
                return str(title)
        nfm = interactive.get("nfm_reply") or {}
        if nfm.get("response_json"):
            return str(nfm.get("response_json"))
        return "[interactive]"

    if msg_type == "button" and message.button:
        return str(message.button.get("text") or message.button.get("payload") or "[button]")

    if msg_type == "reaction" and message.reaction:
        emoji = message.reaction.get("emoji") or ""
        return emoji or "[reaction]"

    if msg_type == "location" and message.location:
        lat = message.location.get("latitude")
        lng = message.location.get("longitude")
        name = message.location.get("name") or ""
        coords = "{}, {}".format(lat, lng)
        return "{} ({})".format(name, coords).strip() if name else coords

    if msg_type == "contacts":
        return "[contacts]"

    if msg_type == "sticker":
        return "[sticker]"

    if msg_type == "order":
        return "[order]"

    if msg_type == "system" and message.system:
        return str(message.system.get("body") or "[system]")

    if msg_type == "unsupported":
        return "[unsupported]"

    return "[{}]".format(msg_type)


def _is_business_sender(from_phone: str, value: WebhookValue) -> bool:
    """Return True when `from` matches the business display number or phone_number_id."""

    metadata = value.metadata
    candidates = {
        (metadata.display_phone_number or "").lstrip("+"),
        (metadata.phone_number_id or "").lstrip("+"),
    }
    normalized = (from_phone or "").lstrip("+")
    return bool(normalized) and normalized in candidates


def classify_direction(
    message: WebhookMessage,
    value: WebhookValue,
    default: str,
) -> Tuple[str, str, str]:
    """Return `(direction, from_phone, to_phone)` for a webhook message.

    Inbound: customer -> business display number.
    Outbound: business/rep -> customer (echoes, or `from` matching the WABA number).
    """

    from_phone = message.from_ or ""
    to_phone = message.to or ""
    business_phone = value.metadata.display_phone_number or value.metadata.phone_number_id

    if default == "outbound":
        return "outbound", from_phone or business_phone, to_phone

    if _is_business_sender(from_phone, value):
        return "outbound", from_phone, to_phone

    return "inbound", from_phone, to_phone or business_phone


def print_message_log(direction: str, phone: str, content: str) -> None:
    """Print a single colorized line to the terminal for an inserted message."""

    preview = (content or "").replace("\n", " ").strip()
    if len(preview) > 160:
        preview = preview[:157] + "..."

    if direction == "inbound":
        color = ANSI_GREEN
        tag = "INBOUND "
    else:
        color = ANSI_BLUE
        tag = "OUTBOUND"

    print(
        "{color}[{tag}]{reset} {phone}  {preview}".format(
            color=color,
            tag=tag,
            reset=ANSI_RESET,
            phone=phone or "(unknown)",
            preview=preview or "(empty)",
        )
    )


def print_status_log(status_obj: WebhookStatus) -> None:
    """Print a dim log line for delivery receipts that are not stored as messages."""

    print(
        "{dim}[STATUS  ] {status} → {phone}  {wamid}{reset}".format(
            dim=ANSI_DIM,
            status=status_obj.status or "unknown",
            phone=status_obj.recipient_id or "(unknown)",
            wamid=status_obj.id or "",
            reset=ANSI_RESET,
        )
    )


async def persist_extracted_message(
    *,
    wamid: str,
    from_phone: str,
    to_phone: str,
    direction: str,
    message_type: str,
    content: str,
    timestamp: int,
    raw_payload: Dict[str, Any],
) -> bool:
    """Insert one message row. Returns True when a new row was written.

    Duplicate `wamid` values (Meta retries) are ignored via the unique constraint.
    """

    record = Message(
        wamid=wamid,
        from_phone=from_phone,
        to_phone=to_phone,
        direction=direction,
        message_type=message_type,
        content=content,
        timestamp=timestamp,
        raw_payload=raw_payload,
    )
    async with AsyncSessionLocal() as session:
        session.add(record)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            logger.debug("Skipped duplicate wamid=%s", wamid)
            return False
    return True


async def store_message(
    message: WebhookMessage,
    value: WebhookValue,
    raw_payload: Dict[str, Any],
    default_direction: str,
) -> None:
    """Normalize, persist, and log a single Cloud API message object."""

    wamid = (message.id or "").strip()
    if not wamid:
        logger.warning("Skipping message without a WhatsApp message id")
        return

    direction, from_phone, to_phone = classify_direction(message, value, default_direction)
    content = extract_content(message)
    inserted = await persist_extracted_message(
        wamid=wamid,
        from_phone=from_phone,
        to_phone=to_phone,
        direction=direction,
        message_type=message.type or "unknown",
        content=content,
        timestamp=_parse_epoch(message.timestamp),
        raw_payload=raw_payload,
    )
    if inserted:
        display_phone = from_phone if direction == "inbound" else (to_phone or from_phone)
        print_message_log(direction, display_phone, content)


async def process_webhook_payload(raw_payload: Dict[str, Any]) -> None:
    """Walk every entry/change and persist real messages; skip status-only receipts."""

    try:
        payload = WebhookPayload.model_validate(raw_payload)
    except Exception:
        logger.exception("Webhook JSON did not match the expected Meta envelope")
        return

    for entry in payload.entry:
        for change in entry.changes:
            value = change.value

            for inbound in value.messages:
                await store_message(inbound, value, raw_payload, default_direction="inbound")

            # WhatsApp Business App coexistence echoes carry outbound reply content.
            for echo in list(value.message_echoes) + list(value.smb_message_echoes):
                await store_message(echo, value, raw_payload, default_direction="outbound")

            for status_obj in value.statuses:
                # sent/delivered/read/failed are receipts, not message bodies.
                print_status_log(status_obj)

            if value.errors:
                print(
                    "{color}[ERROR   ] Meta reported {count} error(s) in this webhook{reset}".format(
                        color=ANSI_YELLOW,
                        count=len(value.errors),
                        reset=ANSI_RESET,
                    )
                )


@app.get("/webhook")
async def verify_webhook(
    hub_mode: Optional[str] = Query(default=None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(default=None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(default=None, alias="hub.challenge"),
) -> PlainTextResponse:
    """Complete Meta's webhook subscription handshake.

    Meta sends `hub.mode=subscribe` plus the verify token configured in the
    Developer Portal. On success the raw `hub.challenge` value is echoed back.
    """

    if hub_mode == "subscribe" and hub_verify_token == settings.VERIFY_TOKEN:
        logger.info("Webhook verification succeeded")
        return PlainTextResponse(content=hub_challenge or "", status_code=status.HTTP_200_OK)

    logger.warning(
        "Webhook verification failed (mode=%s token_match=%s)",
        hub_mode,
        hub_verify_token == settings.VERIFY_TOKEN,
    )
    return PlainTextResponse(content="Forbidden", status_code=status.HTTP_403_FORBIDDEN)


@app.post("/webhook")
async def receive_webhook(request: Request) -> JSONResponse:
    """Accept Meta webhook events and acknowledge immediately with HTTP 200.

    Persistence errors are logged but never raised to the client, so Meta does
    not retry the same payload indefinitely.
    """

    try:
        raw_payload = await request.json()
    except Exception:
        logger.warning("POST /webhook received a non-JSON body; acknowledging anyway")
        return JSONResponse(content={"status": "accepted"}, status_code=status.HTTP_200_OK)

    if not isinstance(raw_payload, dict):
        logger.warning("POST /webhook JSON was not an object; acknowledging anyway")
        return JSONResponse(content={"status": "accepted"}, status_code=status.HTTP_200_OK)

    try:
        await process_webhook_payload(raw_payload)
    except Exception:
        logger.exception("Failed while processing webhook payload")

    return JSONResponse(content={"status": "accepted"}, status_code=status.HTTP_200_OK)


@app.post("/send")
async def send_outbound_text(body: SendTextRequest) -> JSONResponse:
    """Send a text reply via Cloud API and persist it as `outbound` immediately.

    Meta webhooks for API-sent messages only include delivery statuses, not the
    body. Logging here is what makes both sides of the conversation available
    for later analysis. Replies typed in the WhatsApp Business app are still
    captured via `smb_message_echoes` on POST /webhook.
    """

    try:
        wamid, graph_response = await send_text_message(body.to, body.text)
    except WhatsAppSendError as exc:
        return JSONResponse(
            content={"status": "error", "detail": str(exc), "meta": exc.details},
            status_code=exc.status_code,
        )

    get_settings.cache_clear()
    runtime = get_settings()
    to_phone = normalize_phone(body.to)
    from_phone = normalize_phone(runtime.WHATSAPP_DISPLAY_PHONE) or runtime.WHATSAPP_PHONE_NUMBER_ID
    inserted = await persist_extracted_message(
        wamid=wamid,
        from_phone=from_phone,
        to_phone=to_phone,
        direction="outbound",
        message_type="text",
        content=body.text,
        timestamp=int(time.time()),
        raw_payload={"source": "cloud_api_send", "graph_response": graph_response, "text": body.text},
    )
    if inserted:
        print_message_log("outbound", to_phone, body.text)

    return JSONResponse(
        content={"status": "sent", "wamid": wamid, "logged": inserted},
        status_code=status.HTTP_200_OK,
    )


@app.get("/health")
async def health() -> Dict[str, str]:
    """Lightweight liveness probe for local checks."""

    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, reload=True)
