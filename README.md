# Conference Room Manager

A full-stack web app for booking and tracking conference rooms, built with Streamlit. Installable as a PWA on mobile.

## Features

- **Live room status** — see which rooms are free or occupied right now
- **Book a room** — pick a room, date, and time slot; instant confirmation
- **Today's schedule** — view all bookings across all rooms for the day
- **Booking history** — personal booking log with cancel support
- **Multi-method auth** — email + password, email OTP, phone OTP (Twilio), Google OAuth2, Zoho OAuth2
- **Admin panel** — manage users and bookings; admins defined via `ADMIN_EMPLOYEE_IDS`
- **PWA / mobile** — installable on iOS and Android, bottom tab bar navigation
- **Dark / Light / System theme** — persisted across sessions

## Rooms

| Floor | Room | Size | Capacity | Amenities |
|-------|------|------|----------|-----------|
| 5th | Large Conference Room | Large | 20 | TV, Whiteboard |
| 4th | Large Conference Room | Large | 20 | TV, Whiteboard |
| 3rd | Small Conference Room | Small | 5 | Whiteboard |
| 2nd | Small Conference Room | Small | 5 | Whiteboard |

## Project Structure

```
Conference Room Manager/
├── app.py                  # Main Streamlit app
├── start.py                # Launches both Streamlit + FastAPI together
├── requirements.txt        # Python dependencies (Streamlit app)
├── .env                    # Secrets — never commit this
├── utils/
│   └── auth.py             # Auth logic (OTP, OAuth, sessions, DB)
├── static/
│   └── manifest.json       # PWA web app manifest
├── backend/
│   ├── main.py             # FastAPI backend (optional, for mobile app)
│   └── requirements.txt    # FastAPI dependencies
├── mobile/                 # React Native / Expo mobile app
│   └── ...
└── db_example/             # Example DB setup scripts
```

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

Copy the example below to `.env` and fill in your values:

```env
# Admin employee IDs (comma-separated)
ADMIN_EMPLOYEE_IDS=EMP001,EMP002

# Email OTP via SMTP (leave blank for demo mode — OTP prints to console)
SMTP_HOST=smtp.zoho.in
SMTP_PORT=587
SMTP_USER=you@example.com
SMTP_PASS=yourpassword

# Phone OTP via Twilio (leave blank for demo mode)
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_FROM_NUMBER=+1234567890

# Google OAuth2 (leave blank to disable)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=

# Zoho OAuth2 (leave blank to disable)
ZOHO_CLIENT_ID=
ZOHO_CLIENT_SECRET=
ZOHO_ACCOUNTS_URL=https://accounts.zoho.in
ZOHO_MAIL_API=https://mail.zoho.in

# Session settings
SESSION_TTL_HOURS=24

# Base URL for OAuth redirect URIs (no trailing slash)
STREAMLIT_BASE_URL=http://localhost:8501
```

### 3. Run

**Streamlit only:**
```bash
streamlit run app.py
```

**Streamlit + FastAPI backend together:**
```bash
python start.py
```

| Service | URL |
|---------|-----|
| Streamlit web app | http://localhost:8501 |
| FastAPI backend | http://localhost:8000 |

## PWA Installation

1. Open the app in Chrome or Safari on your phone
2. Tap **Share → Add to Home Screen** (iOS) or **Install App** (Android)
3. Launch from the home screen for the full app experience with bottom navigation

## OAuth Setup

### Google OAuth2
1. Go to [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials
2. Create an OAuth 2.0 Client ID (Web application)
3. Add `{STREAMLIT_BASE_URL}` as an authorised redirect URI
4. Copy the Client ID and Secret into `.env`

### Zoho OAuth2
1. Go to [Zoho API Console](https://api-console.zoho.in/)
2. Create a Server-based Application
3. Set redirect URI to `{STREAMLIT_BASE_URL}`
4. Required scope: `ZohoMail.accounts.READ`
5. Copy the Client ID and Secret into `.env`

## Demo Mode

Leave SMTP and Twilio credentials blank to run without email/SMS. OTP codes will print to the terminal instead.

## Tech Stack

- [Streamlit](https://streamlit.io/) — web UI
- [FastAPI](https://fastapi.tiangolo.com/) — REST API backend (for mobile)
- [SQLite](https://sqlite.org/) — local database (WAL mode)
- [python-dotenv](https://github.com/theskumar/python-dotenv) — environment config
- [Twilio](https://www.twilio.com/) — SMS OTP
- [React Native / Expo](https://expo.dev/) — mobile app (`mobile/`)
