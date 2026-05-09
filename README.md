# Personal AI PA System

WhatsApp-accessible personal assistant running on DigitalOcean. Handles finances, assignments, calendar, reminders, email, and web lookups. Built on [OpenClaw](https://openclaw.ai).

## What it does

| Feature | How to use |
|---|---|
| Log expense | Send a receipt photo, voice note, or text like "spent £5 on coffee" |
| Log income | "earned £200 from freelance work" |
| Finance summary | "how much did I spend this week?" |
| New assignment | Automatic — notified within 15 min, added to Google Calendar |
| Calendar | "add meeting with Sarah tomorrow at 3pm" / "what's on my calendar today?" |
| Reminder | "remind me in 2 hours to submit the form" |
| Todo list | "add buy groceries to my list" / "show my todo list" |
| Quick note | "note: look into X scholarship" / "show my notes" |
| Email | "summarise my emails" / "draft a reply to my professor about the deadline" |
| Web lookup | "search for DigitalOcean student pricing" / "summarise this article [url]" |
| Daily briefing | Automatic at 8am — your day, due assignments, weekly spend |

Voice notes work in **English and Urdu**.

---

## Your Setup Checklist

Work through these steps in order. Each step tells you exactly what to do.

---

### Step 1 — Create a DigitalOcean Droplet

1. Log into [digitalocean.com](https://digitalocean.com) with your student account
2. Click **Create → Droplets**
3. Choose:
   - **Region:** closest to you (e.g. London, Frankfurt)
   - **OS:** Ubuntu 22.04 LTS
   - **Plan:** Basic → Regular → **2 GB / 1 CPU / 50 GB** ($12/month)
   - **Authentication:** SSH key — paste your public key (`cat ~/.ssh/id_ed25519.pub` on your Mac)
4. Click **Create Droplet**
5. Note the IP address shown in the dashboard

---

### Step 2 — Create the pa user and clone the repo

SSH into your Droplet as root:
```bash
ssh root@YOUR_IP
```

Create the `pa` user and copy your SSH key so you can log in as pa directly:
```bash
adduser pa
usermod -aG sudo pa
rsync --archive --chown=pa:pa ~/.ssh /home/pa
```

Switch to the pa user, clone the repo, and run setup:
```bash
su - pa
git clone https://github.com/ibbi1020/personal-pa.git ~/pa
cd ~/pa
bash setup.sh
```

From now on, SSH in as `pa` directly: `ssh pa@YOUR_IP`

---

### Step 3 — Get an OpenRouter API key

1. Go to [openrouter.ai](https://openrouter.ai) → Sign in → Keys → Create Key
2. Copy the key (starts with `sk-or-...`) — you'll need it in the next step
3. Add a small amount of credit ($5 covers months of personal use)
4. The default model is `openai/gpt-4o-mini` — cheap and supports receipt images. Browse alternatives at [openrouter.ai/models](https://openrouter.ai/models)

---

### Step 4 — Configure your environment

On the **Droplet**, as the `pa` user:
```bash
cd ~/pa
cp .env.example .env
nano .env
```

Fill in:
- `OPENROUTER_API_KEY` — your key from Step 3
- `OPENROUTER_MODEL` — leave as `openai/gpt-4o-mini` or change to any model from openrouter.ai/models
- `TIMEZONE` — your timezone (e.g. `Asia/Karachi`, `Europe/London`)

Leave `GOOGLE_SHEETS_ID` blank for now (Step 6).

```bash
chmod 600 .env
```

---

### Step 5 — Install OpenClaw and link WhatsApp

On the **Droplet:**
```bash
cd ~/pa
openclaw onboard --install-daemon
```

The onboarding wizard will ask for your LLM provider — choose **OpenAI** (OpenRouter uses the same API format). When it asks for the API key, paste your `sk-or-...` key. When it asks for the base URL (or API endpoint), enter `https://openrouter.ai/api/v1`. For model, enter `openai/gpt-4o-mini`.

When it asks for a channel, choose **WhatsApp (wacli)**. A QR code will appear in the terminal.

**On your phone:** WhatsApp → Settings → Linked Devices → Link a Device → scan the QR code.

Once linked, send yourself "hello" on WhatsApp. You should get a reply within a few seconds.

Now add the audio transcription and daily briefing config to the `openclaw.yaml` that onboarding generated (open it with `nano ~/pa/openclaw.yaml` and append):
```yaml
audio:
  transcriber: shell
  command: /home/pa/pa/scripts/transcribe.sh {file}

briefing:
  enabled: true
  schedule: "0 8 * * *"
  timezone: Asia/Karachi
  include:
    - calendar_today
    - assignments_due_7_days
    - finance_summary_7_days
```
Adjust `timezone` to match yours (e.g. `Europe/London`).

Set OpenClaw to run automatically:
```bash
sudo nano /etc/systemd/system/openclaw.service
```

Paste:
```ini
[Unit]
Description=OpenClaw PA
After=network.target

[Service]
Type=simple
User=pa
WorkingDirectory=/home/pa/pa
ExecStart=/usr/bin/openclaw gateway
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable openclaw
sudo systemctl start openclaw
```

---

### Step 6 — Create your Finance Google Sheet

1. Go to [sheets.google.com](https://sheets.google.com) → New spreadsheet
2. Name it **PA Finance**
3. Rename the first tab (bottom of screen) to **May 2026**
4. In row 1, add these headers: `Date | Merchant | Amount | Currency | Category | Description | Source`
5. Copy the Sheet ID from the URL:
   - URL looks like: `https://docs.google.com/spreadsheets/d/THIS_IS_THE_ID/edit`
6. On the Droplet: `nano ~/pa/.env` → paste the ID as `GOOGLE_SHEETS_ID=`

---

### Step 7 — Set up Google Cloud (one-time, ~15 minutes)

Do this on your **laptop**:

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. **New Project** → name it `personal-pa` → Create
3. In the search bar, enable each of these APIs (search → click → Enable):
   - Google Calendar API
   - Google Classroom API
   - Gmail API
   - Google Sheets API
4. Go to **APIs & Services → OAuth consent screen**:
   - User type: External → Create
   - App name: `Personal PA`, support email: your Gmail
   - Click **Add or remove scopes**, add (paste each URL into the filter box):
     - `https://www.googleapis.com/auth/calendar.events`
     - `https://www.googleapis.com/auth/classroom.courses.readonly`
     - `https://www.googleapis.com/auth/classroom.coursework.me.readonly`
     - `https://www.googleapis.com/auth/gmail.readonly`
     - `https://www.googleapis.com/auth/gmail.compose`
     - `https://www.googleapis.com/auth/spreadsheets`
   - Test users: add your Gmail address → Save
5. Go to **APIs & Services → Credentials → Create Credentials → OAuth client ID**:
   - Application type: Desktop app, name: `pa-client` → Create
   - Click the download button (⬇) → save as `google-credentials.json`
6. Upload to Droplet:
   ```bash
   scp google-credentials.json pa@YOUR_IP:~/pa/
   ```

On the **Droplet:**
```bash
cd ~/pa
openclaw auth google
```

Follow the link it prints, authorize with your Google account, paste the code back.

---

### Step 8 — Enable marketplace skills

On the **Droplet**, run each of these:
```bash
openclaw skill install google-calendar
openclaw skill install google-classroom
openclaw skill install gmail
openclaw skill install web-search
openclaw skill install reminders
openclaw skill install todo
openclaw skill install notes
```

Load the custom skills (the Python venv must be active so dependencies are available):
```bash
source ~/pa/venv/bin/activate
openclaw skill load ./skills/receipt-to-sheets
openclaw skill load ./skills/classroom-poller
deactivate
sudo systemctl restart openclaw
```

Test via WhatsApp:
- `what's on my calendar today` → should respond (empty or with events)
- `remind me in 1 minute to test` → ping arrives 1 minute later
- `add "test item" to my todo list` → confirmed

---

### Step 9 — Test every flow

Send these messages on WhatsApp and verify each works:

| Test | Message to send | Expected result |
|---|---|---|
| Text expense | `spent £5 on coffee` | Row appears in Google Sheets |
| Receipt photo | Send any receipt image | Row appears with source=photo |
| Urdu voice note | Record voice note in Urdu | Transcribed and actioned |
| Calendar | `add meeting tomorrow at 3pm` | Event in Google Calendar |
| Reminder | `remind me in 2 minutes to check` | Ping in 2 minutes |
| Email | `summarise my emails` | Inbox summary |
| Web | `search for OpenClaw documentation` | Search results |
| Assignment poll | `openclaw skill run classroom-poller` (in SSH) | Notification + calendar event |
| Daily briefing | `openclaw briefing send-now` (in SSH) | Briefing message on WhatsApp |

---

## Costs

| Item | Monthly |
|---|---|
| DigitalOcean Droplet | Covered by student credits |
| OpenAI (GPT-4o-mini) | ~$1.50–3.00 |
| Everything else | Free |

---

## Maintenance

```bash
# Check if OpenClaw is running
sudo systemctl status openclaw

# Live logs
journalctl -u openclaw -f

# Update OpenClaw
npm update -g openclaw

# Re-link WhatsApp (session expires ~every 20 days of inactivity)
openclaw auth whatsapp
```

---

## Architecture

```
You (WhatsApp)
     │
     │ WhatsApp Web (wacli)
     ▼
OpenClaw Agent  ←──────→  GPT-4o-mini (~$2/month)
     │
     ├── whisper.cpp (local, free) — voice notes
     ├── Google Calendar — events
     ├── Google Classroom — assignment poller
     ├── Google Sheets — finance ledger
     ├── Gmail — email triage
     └── Web Search — lookups
```
