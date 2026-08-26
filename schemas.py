"""Pydantic models that describe Meta WhatsApp Cloud API webhook JSON.

Meta's payloads vary by message type and product (Cloud API vs WhatsApp Business App
coexistence). Unknown extra fields are accepted so a schema change from Meta does
not reject the webhook.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class WebhookMetadata(BaseModel):
    """Phone number metadata attached to a webhook `value` object."""

    model_config = ConfigDict(extra="allow")

    display_phone_number: str = ""
    phone_number_id: str = ""


class WebhookMessage(BaseModel):
    """A single message object from `messages`, `message_echoes`, or `smb_message_echoes`."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    timestamp: str = "0"
    type: str = "unknown"
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None
    text: Optional[Dict[str, Any]] = None
    image: Optional[Dict[str, Any]] = None
    video: Optional[Dict[str, Any]] = None
    audio: Optional[Dict[str, Any]] = None
    document: Optional[Dict[str, Any]] = None
    sticker: Optional[Dict[str, Any]] = None
    location: Optional[Dict[str, Any]] = None
    contacts: Optional[List[Dict[str, Any]]] = None
    interactive: Optional[Dict[str, Any]] = None
    button: Optional[Dict[str, Any]] = None
    reaction: Optional[Dict[str, Any]] = None
    order: Optional[Dict[str, Any]] = None
    system: Optional[Dict[str, Any]] = None


class WebhookStatus(BaseModel):
    """A delivery status update (`sent`, `delivered`, `read`, `failed`)."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    status: str = ""
    timestamp: str = "0"
    recipient_id: str = ""


class WebhookValue(BaseModel):
    """The `entry[].changes[].value` object from a Cloud API webhook."""

    model_config = ConfigDict(extra="allow")

    messaging_product: Optional[str] = None
    metadata: WebhookMetadata = Field(default_factory=WebhookMetadata)
    messages: List[WebhookMessage] = Field(default_factory=list)
    statuses: List[WebhookStatus] = Field(default_factory=list)
    contacts: List[Dict[str, Any]] = Field(default_factory=list)
    message_echoes: List[WebhookMessage] = Field(default_factory=list)
    smb_message_echoes: List[WebhookMessage] = Field(default_factory=list)
    errors: List[Dict[str, Any]] = Field(default_factory=list)


class WebhookChange(BaseModel):
    """A single change notification inside a webhook entry."""

    model_config = ConfigDict(extra="allow")

    field: Optional[str] = None
    value: WebhookValue = Field(default_factory=WebhookValue)


class WebhookEntry(BaseModel):
    """A WhatsApp Business Account entry wrapping one or more changes."""

    model_config = ConfigDict(extra="allow")

    id: Optional[str] = None
    changes: List[WebhookChange] = Field(default_factory=list)


class WebhookPayload(BaseModel):
    """Top-level POST body sent by Meta to the webhook URL."""

    model_config = ConfigDict(extra="allow")

    object: Optional[str] = None
    entry: List[WebhookEntry] = Field(default_factory=list)


class SendTextRequest(BaseModel):
    """Body for POST /send — a business text reply that is sent and logged as outbound."""

    to: str = Field(..., min_length=8, description="Customer phone in international format, e.g. 917527055586")
    text: str = Field(..., min_length=1, description="Message body to send")
