import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
TOKEN_FILE = "token.json"
CREDENTIALS_FILE = "credentials.json"


def get_credentials():
    """Return valid OAuth2 credentials, opening browser sign-in if needed."""
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"\n'{CREDENTIALS_FILE}' not found.\n\n"
                    "To set up Gmail access:\n"
                    "  1. Go to console.cloud.google.com\n"
                    "  2. Create a project and enable the Gmail API\n"
                    "  3. Create OAuth 2.0 Credentials (Desktop app)\n"
                    "  4. Download the file and save it as 'credentials.json' in this folder\n"
                    "  5. Run again — a browser window will open for sign-in\n"
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return creds


def signout():
    """Delete the local token file, requiring re-authentication on next run."""
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
        print("Signed out. Local token deleted.")
        print("To fully revoke app access: https://myaccount.google.com/permissions")
    else:
        print("Not currently signed in (no token.json found).")
