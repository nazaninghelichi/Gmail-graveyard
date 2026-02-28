import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from rich.console import Console

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
TOKEN_FILE = "token.json"
CREDENTIALS_FILE = "credentials.json"

console = Console()


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
            console.print(
                "\n[bold yellow]A sign-in URL will appear below.[/]\n"
                "Copy it and open it in [bold]Chrome or Firefox[/] "
                "[dim](Safari may block the localhost callback)[/]\n"
            )
            creds = flow.run_local_server(port=0, open_browser=False)

        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return creds


def signout():
    """Delete the local token file, requiring re-authentication on next run."""
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
        console.print("[bold green]Signed out.[/] Local token deleted.")
        console.print(
            "To fully revoke app access: "
            "[bold blue]https://myaccount.google.com/permissions[/]"
        )
    else:
        console.print("[bold yellow]Not currently signed in[/] (no token.json found).")
