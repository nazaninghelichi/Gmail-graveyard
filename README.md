# Gmail Graveyard

Clean your Gmail inbox without touching your password. Sign in with Google OAuth2 — no credentials stored in code or config files.

---

## What It Does

| Feature | Description |
|---|---|
| Priority protection | Emails matching job offers, invoices, urgent keywords are starred and never deleted |
| Bulk delete old emails | Moves emails older than 90 days (configurable) to Trash |
| Newsletter detection | Detects marketing emails and lists their unsubscribe links |
| Category labeling | Auto-labels emails as Shopping, Finance, Dev Tools, etc. |
| Duplicate removal | Finds and trashes duplicate emails, keeps one copy |
| Dry-run mode | Preview everything before making any changes |
| Scheduled auto-cleanup | Runs daily or weekly in the background |

---

## Setup

### 1. Install dependencies

```bash
cd Gmail-graveyard
pip install -r requirements.txt
```

### 2. Get Google credentials

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a project and enable the **Gmail API**
3. Go to **APIs & Services > Credentials**
4. Click **Create Credentials > OAuth 2.0 Client ID** — choose **Desktop app**
5. Download the JSON file and save it as `credentials.json` in this folder

### 3. Configure your rules

Edit `config.yaml` to set your preferences — delete threshold, priority senders, safety cap:

```yaml
rules:
  delete_older_than_days: 90
  priority_keywords:
    - job offer
    - interview
    - invoice
  priority_senders:
    - boss@company.com
```

### 4. Run

```bash
python main.py --dry-run
```

A browser window opens for Google sign-in. After that, a token is saved locally and you won't be asked again.

---

## Commands

```bash
# Preview everything — no changes made
python main.py --dry-run

# Full cleanup (shows preview, asks confirmation)
python main.py

# Run a specific action only
python main.py --action delete-old
python main.py --action unsubscribe
python main.py --action organize
python main.py --action duplicates

# Override the delete threshold
python main.py --action delete-old --days 30

# Start scheduled auto-cleanup (daily at 09:00)
python main.py --auto

# Show the full usage guide
python main.py guide

# Sign out (deletes local token)
python main.py signout
```

---

## Security

- Your Gmail password is **never stored anywhere**
- Sign-in uses Google OAuth2 — a browser window opens and you approve access
- The permission token (`token.json`) is saved locally and gitignored
- To fully revoke access at any time: [myaccount.google.com/permissions](https://myaccount.google.com/permissions)

---

## Project Structure

```
Gmail-graveyard/
├── main.py              # CLI entry point
├── config.yaml          # Your rules (no passwords)
├── requirements.txt
├── .gitignore           # token.json and credentials.json are excluded
└── gmail/
    ├── auth.py          # OAuth2 sign-in flow
    ├── client.py        # Gmail API wrapper
    ├── analyzer.py      # Priority scoring and categorization
    ├── actions.py       # All cleanup actions
    ├── unsubscribe.py   # Newsletter unsubscribe link detection
    ├── duplicates.py    # Duplicate email detection
    └── scheduler.py     # Scheduled auto-runs
```
