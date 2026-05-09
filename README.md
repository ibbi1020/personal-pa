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
   - **Authentication:** SSH key — paste your public key (`cat ~/.ssh/id_rsa.pub` on your Mac)
4. Click **Create Droplet**
5. Note the IP address shown in the dashboard

---

### Step 2 — Upload this repo and run setup

On your **Mac terminal:**
```bash
# Clone the repo
git clone https://github.com/ibbi1020/personal-pa.git
cd personal-pa

# Upload to your Droplet (replace YOUR_IP)
scp -r . root@YOUR_IP:~/pa-setup
```

On your **Droplet** (SSH in first: `ssh root@YOUR_IP`):
```bash
# Create the pa user
adduser pa
usermod -aG sudo pa
rsync --archive --chown=pa:pa ~/.ssh /home/pa

# Switch to pa user and run setup
su - pa
cp -r ~/pa-setup ~/pa
cd ~/pa
bash setup.sh
```

---

### Step 3 — Get an OpenAI API key

1. Go to [platform.openai.com](https://platform.openai.com) → API keys → Create new secret key
2. Copy it — you'll need it in the next step
3. Add a small amount of credit ($5 covers months of personal use)

---

### Step 4 — Configure your environment

On the **Droplet**, as the `pa` user:
```bash
cd ~/pa
cp .env.example .env
nano .env
```

Fill in:
- `OPENAI_API_KEY` — your key from Step 3
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
cp openclaw.yaml.example openclaw.yaml
openclaw onboard
```

The onboarding wizard will ask for your LLM provider — choose **OpenAI**, paste your key, choose model **gpt-4o-mini**.

When it asks for a channel, choose **WhatsApp (wacli)**. A QR code will appear in the terminal.

**On your phone:** WhatsApp → Settings → Linked Devices → Link a Device → scan the QR code.

Once linked, send yourself "hello" on WhatsApp. You should get a reply within a few seconds.

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
ExecStart=/usr/bin/openclaw start
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
   - Click **Add or remove scopes**, add:
     - `calendar`
     - `classroom.courses.readonly`
     - `classroom.coursework.me.readonly`
     - `gmail.readonly`
     - `gmail.compose`
     - `spreadsheets`
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

Load the custom skills:
```bash
openclaw skill load ./skills/receipt-to-sheets
openclaw skill load ./skills/classroom-poller
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
