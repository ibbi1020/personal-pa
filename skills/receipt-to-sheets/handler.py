import os
import json
from datetime import date
from typing import Optional
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from openai import OpenAI

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CATEGORIES = ["Food & Drink", "Transport", "Shopping", "Bills",
               "Education", "Entertainment", "Income", "Other"]

def get_sheets_service():
    token_path = os.environ.get(
        "GOOGLE_CREDENTIALS_PATH",
        os.path.expanduser("~/.openclaw/google_token.json")
    )
    creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    return build("sheets", "v4", credentials=creds)

def _llm_client() -> OpenAI:
    return OpenAI(
        api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        base_url="https://openrouter.ai/api/v1",
    )

def extract_transaction(text: str, image_b64: Optional[str]) -> dict:
    model = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    client = _llm_client()

    prompt = (
        f"Extract transaction details. Categories: {', '.join(CATEGORIES)}. "
        'Return JSON only: {"merchant": str, "amount": float, "currency": str, '
        '"category": str, "description": str}. '
        "Use ISO currency codes (GBP, PKR, USD). If currency unclear, use GBP."
    )

    content: list = []
    if image_b64:
        mime = "image/jpeg"
        if image_b64.startswith("iVBORw0"):  # PNG magic bytes base64-encoded
            mime = "image/png"
        content = [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
            {"type": "text", "text": prompt},
        ]
    else:
        content = [{"type": "text", "text": f"{prompt}\n\nInput: {text}"}]

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        max_tokens=400,
    )

    raw = response.choices[0].message.content or ""
    # strip markdown fences if model wraps output
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        tx = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"LLM returned non-JSON response: {raw[:200]}") from exc

    required = {"merchant", "amount", "currency", "category", "description"}
    missing = required - tx.keys()
    if missing:
        raise ValueError(f"LLM response missing keys: {missing}")

    return tx

def get_or_create_tab(service, sheet_id: str, tab_name: str) -> None:
    sheet = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    tabs = [s["properties"]["title"] for s in sheet["sheets"]]
    if tab_name not in tabs:
        service.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": tab_name}}}]}
        ).execute()
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id, range=f"{tab_name}!A1",
            valueInputOption="RAW",
            body={"values": [["Date", "Merchant", "Amount", "Currency",
                              "Category", "Description", "Source"]]}
        ).execute()

def handle(context) -> str:
    """
    context.text: str — the user's message or transcribed voice note
    context.image_b64: str | None — base64 image if user sent a photo
    context.source: str — "photo", "voice", or "text"
    Returns: str — confirmation message to send back
    """
    sheet_id = os.environ.get("GOOGLE_SHEETS_ID", "")
    if not sheet_id:
        return "GOOGLE_SHEETS_ID is not configured."

    try:
        tx = extract_transaction(context.text, context.image_b64)
    except ValueError as exc:
        return f"Sorry, I couldn't parse that transaction. Try: 'spent £5 on coffee' ({exc})"

    today = date.today()
    tab_name = today.strftime("%b %Y")

    svc = get_sheets_service()
    get_or_create_tab(svc, sheet_id, tab_name)

    row = [
        today.isoformat(),
        tx["merchant"],
        tx["amount"],
        tx["currency"],
        tx["category"],
        tx["description"],
        context.source,
    ]
    svc.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range=f"{tab_name}!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()

    return (
        f"Logged {tx['currency']} {tx['amount']:.2f} at {tx['merchant']} "
        f"→ {tx['category']}"
    )
