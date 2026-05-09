"""
Unit tests for skills/receipt-to-sheets/handler.py

All external calls (OpenAI, Google Sheets API) are mocked —
no real API keys required.
"""
import importlib
import json
import os
import sys
import types
from datetime import date
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: inject a fake GOOGLE_SHEETS_ID so the module-level assignment
# `SHEET_ID = os.environ["GOOGLE_SHEETS_ID"]` doesn't raise KeyError when
# the module is first imported.
# ---------------------------------------------------------------------------
os.environ.setdefault("GOOGLE_SHEETS_ID", "fake-sheet-id")
os.environ.setdefault("OPENAI_API_KEY", "fake-openai-key")

# Add the skill directory to sys.path so we can import handler directly
SKILL_DIR = os.path.join(
    os.path.dirname(__file__), "..", "skills", "receipt-to-sheets"
)
sys.path.insert(0, os.path.abspath(SKILL_DIR))

import handler  # noqa: E402  (imported after path manipulation)


# ---------------------------------------------------------------------------
# Helper: a simple context object matching the OpenClaw skill API contract
# ---------------------------------------------------------------------------
class FakeContext:
    def __init__(self, text="", image_b64=None, source="text"):
        self.text = text
        self.image_b64 = image_b64
        self.source = source


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
SAMPLE_TX = {
    "merchant": "Tesco",
    "amount": 12.50,
    "currency": "GBP",
    "category": "Food & Drink",
    "description": "Weekly groceries",
}


def _make_openai_response(tx: dict):
    """Build a minimal mock that mirrors openai.ChatCompletion response shape."""
    msg = MagicMock()
    msg.content = json.dumps(tx)
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


# ---------------------------------------------------------------------------
# Tests: get_sheets_service
# ---------------------------------------------------------------------------
class TestGetSheetsService:
    @patch("handler.build")
    @patch("handler.Credentials.from_authorized_user_file")
    def test_uses_env_var_when_set(self, mock_from_file, mock_build):
        """When GOOGLE_CREDENTIALS_PATH is set, use that path."""
        custom_path = "/custom/path/to/token.json"
        os.environ["GOOGLE_CREDENTIALS_PATH"] = custom_path

        try:
            mock_creds = MagicMock()
            mock_from_file.return_value = mock_creds

            handler.get_sheets_service()

            mock_from_file.assert_called_once_with(custom_path, handler.SCOPES)
            mock_build.assert_called_once_with("sheets", "v4", credentials=mock_creds)
        finally:
            del os.environ["GOOGLE_CREDENTIALS_PATH"]

    @patch("handler.build")
    @patch("handler.Credentials.from_authorized_user_file")
    def test_uses_default_when_env_var_not_set(self, mock_from_file, mock_build):
        """When GOOGLE_CREDENTIALS_PATH is not set, use default path."""
        # Ensure the env var is not set
        os.environ.pop("GOOGLE_CREDENTIALS_PATH", None)

        mock_creds = MagicMock()
        mock_from_file.return_value = mock_creds
        expected_default = os.path.expanduser("~/.openclaw/google_token.json")

        handler.get_sheets_service()

        mock_from_file.assert_called_once_with(expected_default, handler.SCOPES)
        mock_build.assert_called_once_with("sheets", "v4", credentials=mock_creds)


# ---------------------------------------------------------------------------
# Tests: extract_transaction
# ---------------------------------------------------------------------------
class TestExtractTransaction:
    @patch("handler.OpenAI")
    def test_text_input_calls_openai_and_parses_json(self, MockOpenAI):
        client = MagicMock()
        MockOpenAI.return_value = client
        client.chat.completions.create.return_value = _make_openai_response(SAMPLE_TX)

        result = handler.extract_transaction("spent £12.50 at Tesco", None)

        assert result == SAMPLE_TX
        client.chat.completions.create.assert_called_once()
        call_kwargs = client.chat.completions.create.call_args
        messages = call_kwargs[1]["messages"] if call_kwargs[1] else call_kwargs[0][1]
        # text-only: content should be a list with a single text element
        content = messages[0]["content"]
        assert any(item.get("type") == "text" for item in content)
        assert not any(item.get("type") == "image_url" for item in content)

    @patch("handler.OpenAI")
    def test_image_input_sends_image_url(self, MockOpenAI):
        client = MagicMock()
        MockOpenAI.return_value = client
        client.chat.completions.create.return_value = _make_openai_response(SAMPLE_TX)

        result = handler.extract_transaction("receipt", "base64encodeddata==")

        assert result["merchant"] == "Tesco"
        call_kwargs = client.chat.completions.create.call_args
        messages = call_kwargs[1]["messages"] if call_kwargs[1] else call_kwargs[0][1]
        content = messages[0]["content"]
        types_sent = [item["type"] for item in content]
        assert "image_url" in types_sent
        assert "text" in types_sent

    @patch("handler.OpenAI")
    def test_uses_gpt4o_mini_model(self, MockOpenAI):
        client = MagicMock()
        MockOpenAI.return_value = client
        client.chat.completions.create.return_value = _make_openai_response(SAMPLE_TX)

        handler.extract_transaction("paid £5 for coffee", None)

        _, kwargs = client.chat.completions.create.call_args
        assert kwargs.get("model") == "gpt-4o-mini"

    @patch("handler.OpenAI")
    def test_image_url_contains_base64_data(self, MockOpenAI):
        client = MagicMock()
        MockOpenAI.return_value = client
        client.chat.completions.create.return_value = _make_openai_response(SAMPLE_TX)

        b64 = "abc123=="
        handler.extract_transaction("receipt", b64)

        _, kwargs = client.chat.completions.create.call_args
        content = kwargs["messages"][0]["content"]
        image_item = next(i for i in content if i["type"] == "image_url")
        assert b64 in image_item["image_url"]["url"]
        assert image_item["image_url"]["url"].startswith("data:image/jpeg;base64,")


# ---------------------------------------------------------------------------
# Tests: get_or_create_tab
# ---------------------------------------------------------------------------
def _make_sheets_service(existing_tabs=None):
    """Return a mock Sheets service stub."""
    svc = MagicMock()
    tabs = existing_tabs or []
    sheet_data = {
        "sheets": [{"properties": {"title": t}} for t in tabs]
    }
    svc.spreadsheets().get().execute.return_value = sheet_data
    return svc


class TestGetOrCreateTab:
    def test_existing_tab_does_not_create(self):
        svc = _make_sheets_service(existing_tabs=["May 2026"])
        handler.get_or_create_tab(svc, "May 2026")
        # batchUpdate should NOT have been called
        svc.spreadsheets().batchUpdate.assert_not_called()

    def test_missing_tab_creates_and_adds_header(self):
        svc = _make_sheets_service(existing_tabs=["Apr 2026"])
        handler.get_or_create_tab(svc, "May 2026")

        svc.spreadsheets().batchUpdate.assert_called_once()
        body = svc.spreadsheets().batchUpdate.call_args[1]["body"]
        assert body["requests"][0]["addSheet"]["properties"]["title"] == "May 2026"

        svc.spreadsheets().values().update.assert_called_once()
        update_kwargs = svc.spreadsheets().values().update.call_args[1]
        header_row = update_kwargs["body"]["values"][0]
        assert header_row[0] == "Date"
        assert "Merchant" in header_row
        assert "Amount" in header_row

    def test_header_written_to_correct_tab(self):
        svc = _make_sheets_service(existing_tabs=[])
        handler.get_or_create_tab(svc, "Jun 2026")

        update_kwargs = svc.spreadsheets().values().update.call_args[1]
        assert update_kwargs["range"].startswith("Jun 2026!")


# ---------------------------------------------------------------------------
# Tests: handle (end-to-end with both OpenAI and Sheets mocked)
# ---------------------------------------------------------------------------
class TestHandle:
    def _run_handle(self, context, tx_override=None, existing_tabs=None):
        tx = tx_override or SAMPLE_TX
        svc = _make_sheets_service(existing_tabs=existing_tabs or [])

        with patch("handler.extract_transaction", return_value=tx) as mock_extract, \
             patch("handler.get_sheets_service", return_value=svc) as mock_get_svc, \
             patch("handler.get_or_create_tab") as mock_tab:

            result = handler.handle(context)

        return result, mock_extract, svc, mock_tab

    def test_returns_confirmation_string(self):
        ctx = FakeContext(text="spent £12.50 at Tesco", source="text")
        result, *_ = self._run_handle(ctx)
        assert "Tesco" in result
        assert "12.50" in result
        assert "GBP" in result
        assert "Food & Drink" in result

    def test_appends_row_to_sheet(self):
        ctx = FakeContext(text="bought coffee", source="text")
        result, mock_extract, svc, _ = self._run_handle(ctx)

        svc.spreadsheets().values().append.assert_called_once()
        append_kwargs = svc.spreadsheets().values().append.call_args[1]
        row = append_kwargs["body"]["values"][0]
        # row: [date, merchant, amount, currency, category, description, source]
        assert len(row) == 7
        assert row[1] == SAMPLE_TX["merchant"]
        assert row[2] == SAMPLE_TX["amount"]
        assert row[3] == SAMPLE_TX["currency"]
        assert row[4] == SAMPLE_TX["category"]
        assert row[6] == "text"

    def test_row_date_is_today(self):
        ctx = FakeContext(text="paid for lunch", source="voice")
        _, _, svc, _ = self._run_handle(ctx)

        append_kwargs = svc.spreadsheets().values().append.call_args[1]
        row = append_kwargs["body"]["values"][0]
        assert row[0] == date.today().isoformat()

    def test_source_written_correctly_for_photo(self):
        ctx = FakeContext(text="", image_b64="abc==", source="photo")
        _, _, svc, _ = self._run_handle(ctx)

        append_kwargs = svc.spreadsheets().values().append.call_args[1]
        row = append_kwargs["body"]["values"][0]
        assert row[6] == "photo"

    def test_tab_name_matches_current_month(self):
        ctx = FakeContext(text="earned £500", source="text")
        tx = {**SAMPLE_TX, "category": "Income", "amount": 500.0, "currency": "GBP", "merchant": "Client"}
        _, _, svc, mock_tab = self._run_handle(ctx, tx_override=tx)

        expected_tab = date.today().strftime("%b %Y")
        mock_tab.assert_called_once_with(svc, expected_tab)

        append_kwargs = svc.spreadsheets().values().append.call_args[1]
        assert append_kwargs["range"].startswith(expected_tab)

    def test_extract_transaction_called_with_context_fields(self):
        ctx = FakeContext(text="spent £10", image_b64="img==", source="photo")
        _, mock_extract, *_ = self._run_handle(ctx)

        mock_extract.assert_called_once_with("spent £10", "img==")

    def test_confirmation_format(self):
        ctx = FakeContext(text="paid £3.99 for coffee", source="text")
        tx = {
            "merchant": "Costa Coffee",
            "amount": 3.99,
            "currency": "GBP",
            "category": "Food & Drink",
            "description": "Flat white",
        }
        result, *_ = self._run_handle(ctx, tx_override=tx)
        assert result == "Logged GBP 3.99 at Costa Coffee → Food & Drink"
