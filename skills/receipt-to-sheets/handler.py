import os, json
from datetime import date
from typing import Optional
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from openai import OpenAI

SHEET_ID = os.environ["GOOGLE_SHEETS_ID"]
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

def extract_transaction(text: str, image_b64: Optional[str]) -> dict:
    client = OpenAI()
    messages = [{"role": "user", "content": []}]

    prompt = (
        f"Extract transaction details. Categories: {', '.join(CATEGORIES)}. "
        "Return JSON only: {\"merchant\": str, \"amount\": float, \"currency\": str, "
        "\"category\": str, \"description\": str}. "
        "Use ISO currency codes (GBP, PKR, USD). If currency unclear, use GBP."
    )

    if image_b64:
        messages[0]["content"] = [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            {"type": "text", "text": prompt},
        ]
    else:
        messages[0]["content"] = [{"type": "text", "text": f"{prompt}\n\nInput: {text}"}]

    response = client.chat.completions.create(
        model="gpt-4o-mini", messages=messages, max_tokens=200
    )
    return json.loads(response.choices[0].message.content)

def get_or_create_tab(service, tab_name: str):
    sheet = service.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    tabs = [s["properties"]["title"] for s in sheet["sheets"]]
    if tab_name not in tabs:
        service.spreadsheets().batchUpdate(
            spreadsheetId=SHEET_ID,
            body={"requests": [{"addSheet": {"properties": {"title": tab_name}}}]}
        ).execute()
        service.spreadsheets().values().update(
            spreadsheetId=SHEET_ID, range=f"{tab_name}!A1",
            valueInputOption="RAW",
            body={"values": [["Date", "Merchant", "Amount", "Currency",
                              "Category", "Description", "Source"]]}
        ).execute()

def handle(context):
    """
    context.text: str — the user's message or transcribed voice note
    context.image_b64: str | None — base64 image if user sent a photo
    context.source: str — "photo", "voice", or "text"
    Returns: str — confirmation message to send back
    """
    tx = extract_transaction(context.text, context.image_b64)
    today = date.today()
    tab_name = today.strftime("%b %Y")

    svc = get_sheets_service()
    get_or_create_tab(svc, tab_name)

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
        spreadsheetId=SHEET_ID,
        range=f"{tab_name}!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()

    return (
        f"Logged {tx['currency']} {tx['amount']:.2f} at {tx['merchant']} "
        f"→ {tx['category']}"
    )
