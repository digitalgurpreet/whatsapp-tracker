# WhatsApp Cloud API Tracker (Phase 1)

FastAPI webhook listener for Meta's WhatsApp Business Cloud API. It completes the subscription handshake, captures inbound customer messages and outbound business/rep replies, and stores them for later AI processing.

**Run this in the cloud in production.** Local Uvicorn + ngrok works for a first test, but Meta needs a stable HTTPS URL. If your laptop sleeps, ngrok stops, or the ngrok URL changes, webhooks break.

## Production (recommended)

Use any always-on host with a public HTTPS URL (Render Starter, Railway, Fly.io, a small VPS). Do **not** use a free host that sleeps after idle time — Meta will fail webhook delivery.

Do **not** use SQLite in the cloud. The disk is usually ephemeral, so chats disappear on restart. Use Postgres (Neon, Render Postgres, Railway Postgres, etc.).

### 1. Create a Postgres database

Copy the connection string. Example:

```
postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require
```

### 2. Deploy this app

A `Dockerfile` is included. Point the platform at this repo, then set these environment variables (same values as local `.env`, except `DATABASE_URL`):

| Variable | Purpose |
| --- | --- |
| `VERIFY_TOKEN` | Same string as Meta webhook Verify token |
| `DATABASE_URL` | Postgres URL from step 1 |
| `WHATSAPP_TOKEN` | Cloud API access token |
| `WHATSAPP_PHONE_NUMBER_ID` | Phone number ID from API setup |
| `WHATSAPP_DISPLAY_PHONE` | Business number digits, e.g. `917986341955` |
| `GRAPH_API_VERSION` | `v25.0` |
| `PORT` | Set automatically by most hosts |

Health check path: `/health`

On Render you can use `render.yaml`. After deploy you get a URL like `https://whatsapp-tracker.onrender.com`.

### 3. Point Meta at the cloud URL

WhatsApp → Configuration → Webhook:

```
https://YOUR-SERVICE-HOST/webhook
```

Verify token must match `VERIFY_TOKEN`. Keep `messages` subscribed.

Then **stop** local Uvicorn and ngrok so only the cloud service receives events.

### 4. Confirm

```bash
curl -i "https://YOUR-SERVICE-HOST/health"
curl -i "https://YOUR-SERVICE-HOST/webhook?hub.mode=subscribe&hub.verify_token=YOUR_TOKEN&hub.challenge=123"
```

Send a WhatsApp to the business number. The cloud logs should show `[INBOUND ]`.

Existing rows in local `whatsapp_chats.db` are **not** copied automatically. The cloud database starts empty unless you import them.

---

## Local development (optional)

Use this only to try the handshake on your laptop. You will need ngrok, and both Uvicorn and ngrok must stay running.


## 1. Create a virtual environment and install dependencies

```bash
cd "/path/to/this/project"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and set a secret verify token (any string you choose):

```
VERIFY_TOKEN=my-local-verify-token
DATABASE_URL=sqlite:///./whatsapp_chats.db
PORT=8000
```

You will paste the **same** `VERIFY_TOKEN` into the Meta Developer Portal webhook settings.

## 3. Start the FastAPI app with Uvicorn (reload mode)

```bash
source .venv/bin/activate
uvicorn main:app --reload --port 8000
```

The app creates `whatsapp_chats.db` on first startup. Leave this terminal running.

Optional: `python main.py` uses the `PORT` value from `.env`.

## 4. Expose the local server with ngrok

In a **second** terminal:

```bash
ngrok http 8000
```

ngrok prints a forwarding URL such as:

```
https://abc123.ngrok-free.app
```

## 5. Register the webhook in the Meta Developer Portal

1. Open [Meta for Developers](https://developers.facebook.com/) → your app → **WhatsApp** → **Configuration** (or **Webhooks**).
2. Set the Callback URL to:

   ```
   https://<ngrok_id>.ngrok-free.app/webhook
   ```

   Example: `https://abc123.ngrok-free.app/webhook`

3. Set **Verify token** to the same value as `VERIFY_TOKEN` in `.env`.
4. Subscribe to the `messages` field (and `smb_message_echoes` if you use WhatsApp Business App coexistence for rep replies from the phone/app).

Meta will immediately send a `GET /webhook` handshake. The app echoes `hub.challenge` with HTTP 200 when the token matches.

> The free ngrok URL changes every time you restart ngrok unless you use a reserved domain. Update the Callback URL after each restart.

## 6. Test the GET verification handshake locally

With Uvicorn running, in a third terminal:

```bash
curl -i "http://127.0.0.1:8000/webhook?hub.mode=subscribe&hub.verify_token=my-local-verify-token&hub.challenge=1234567890"
```

Expected: HTTP 200 and a body of `1234567890`.

A wrong token should fail:

```bash
curl -i "http://127.0.0.1:8000/webhook?hub.mode=subscribe&hub.verify_token=wrong-token&hub.challenge=1234567890"
```

Expected: HTTP 403.

## 7. Test POST message capture locally

Simulate an inbound customer text message:

```bash
curl -i -X POST "http://127.0.0.1:8000/webhook" \
  -H "Content-Type: application/json" \
  -d '{
    "object": "whatsapp_business_account",
    "entry": [{
      "id": "WABA_ID",
      "changes": [{
        "field": "messages",
        "value": {
          "messaging_product": "whatsapp",
          "metadata": {
            "display_phone_number": "15551234567",
            "phone_number_id": "123456789"
          },
          "contacts": [{ "profile": { "name": "Jane" }, "wa_id": "15557654321" }],
          "messages": [{
            "from": "15557654321",
            "id": "wamid.HBgNMTU1NTc2NTQzMjEVAgASGBQzOEI",
            "timestamp": "1700000000",
            "type": "text",
            "text": { "body": "Hello, I need help with my order" }
          }]
        }
      }]
    }]
  }'
```

Expected:

- HTTP 200 with `{"status":"accepted"}`
- A green terminal line: `[INBOUND ] 15557654321  Hello, I need help with my order`
- A new row in `whatsapp_chats.db`

Repeating the same `curl` does not insert a duplicate (unique `wamid`).

Simulate an outbound rep echo (WhatsApp Business App coexistence):

```bash
curl -i -X POST "http://127.0.0.1:8000/webhook" \
  -H "Content-Type: application/json" \
  -d '{
    "object": "whatsapp_business_account",
    "entry": [{
      "id": "WABA_ID",
      "changes": [{
        "field": "smb_message_echoes",
        "value": {
          "messaging_product": "whatsapp",
          "metadata": {
            "display_phone_number": "15551234567",
            "phone_number_id": "123456789"
          },
          "smb_message_echoes": [{
            "from": "15551234567",
            "to": "15557654321",
            "id": "wamid.OUTBOUNDTEST001",
            "timestamp": "1700000001",
            "type": "text",
            "text": { "body": "Thanks Jane — we are looking into it" }
          }]
        }
      }]
    }]
  }'
```

## What gets stored vs acknowledged only

| Webhook content | Stored in SQLite? | Terminal log |
| --- | --- | --- |
| `value.messages` (customer → business) | Yes, `direction=inbound` | `[INBOUND ]` |
| `value.message_echoes` / `smb_message_echoes` (rep → customer) | Yes, `direction=outbound` | `[OUTBOUND]` |
| `value.statuses` (`sent` / `delivered` / `read` / `failed`) | No — these are receipts, not message bodies | `[STATUS  ]` (dim) |

`POST /webhook` **always** returns HTTP 200 so Meta does not retry.

## Project layout

| File | Role |
| --- | --- |
| `main.py` | FastAPI app, GET handshake, POST parser, colorized logs |
| `config.py` | `VERIFY_TOKEN`, `DATABASE_URL`, `PORT` via pydantic-settings |
| `database.py` | Async SQLAlchemy + SQLite (`aiosqlite`) |
| `models.py` | `messages` table |
| `schemas.py` | Pydantic models for Meta webhook JSON |
| `.env.example` | Environment variable template |

## Inspect stored messages

```bash
sqlite3 whatsapp_chats.db "SELECT id, direction, from_phone, content, wamid FROM messages;"
```


https://dash-sauna-sphere.ngrok-free.dev