import re
import urllib.error
import urllib.parse
import urllib.request

from rich.console import Console
from rich.table import Table

from gmail.analyzer import get_header

console = Console()


def get_unsubscribe_links(headers):
    """Parse List-Unsubscribe (and List-Unsubscribe-Post) headers.

    Returns a dict with keys: mailto, http, one_click (bool).
    Returns None if no unsubscribe header is present.
    """
    header = get_header(headers, "List-Unsubscribe")
    if not header:
        return None

    result = {}
    mailto = re.search(r"<(mailto:[^>]+)>", header)
    http = re.search(r"<(https?://[^>]+)>", header)

    if mailto:
        result["mailto"] = mailto.group(1)
    if http:
        result["http"] = http.group(1)

    # RFC 8058 one-click POST support
    post_header = get_header(headers, "List-Unsubscribe-Post")
    result["one_click"] = "List-Unsubscribe=One-Click" in (post_header or "")

    return result if (result.get("mailto") or result.get("http")) else None


def attempt_unsubscribe(service, links):
    """Try to unsubscribe using the best available method.

    Returns (method, status) where status is one of:
      "ok"     — HTTP 2xx received or email sent
      "failed" — request errored out
      "manual" — non-2xx response, may need manual action
    """
    # Prefer one-click POST, then http GET, then mailto
    if links.get("http"):
        url = links["http"]
        try:
            if links.get("one_click"):
                data = b"List-Unsubscribe=One-Click"
                req = urllib.request.Request(
                    url, data=data, method="POST",
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
            else:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status in (200, 201, 202, 204):
                    return ("http", "ok")
                return ("http", "manual")
        except urllib.error.HTTPError as e:
            if e.code in (200, 201, 202, 204):
                return ("http", "ok")
            return ("http", "manual")
        except Exception:
            # Fall through to mailto if http fails
            pass

    if links.get("mailto"):
        try:
            from gmail.client import send_message
            uri = links["mailto"][len("mailto:"):]
            if "?" in uri:
                address, params = uri.split("?", 1)
                parsed = urllib.parse.parse_qs(params)
                subject = parsed.get("subject", ["Unsubscribe"])[0]
            else:
                address = uri
                subject = "Unsubscribe"
            send_message(service, to=address.strip(), subject=subject)
            return ("mailto", "ok")
        except Exception:
            return ("mailto", "failed")

    return ("unknown", "failed")


_JOB_ALERT_KEYWORDS = [
    "job alert", "job opportunity", "job opportunities", "jobs for you",
    "jobs matching", "job match", "job recommendation", "new jobs",
    "career alert", "career opportunity", "career opportunities",
    "talent alert", "talent community", "talent network",
    "hiring alert", "open position", "open role",
    "we found jobs", "jobs you may like",
]

_JOB_ALERT_SENDERS = [
    "linkedin", "indeed", "glassdoor", "ziprecruiter", "monster",
    "talent.com", "workopolis", "simplyhired", "careerbuilder",
    "joblist", "ladders", "dice.com", "hired.com", "wellfound",
]


def is_job_alert(sender: str, subject: str) -> bool:
    """Return True if the email looks like a job/career alert."""
    combined = ((sender or "") + " " + (subject or "")).lower()
    return (
        any(k in combined for k in _JOB_ALERT_KEYWORDS)
        or any(s in combined for s in _JOB_ALERT_SENDERS)
    )


def print_unsubscribe_report(items):
    """Print a formatted rich table of (sender, subject, links) tuples."""
    if not items:
        console.print("  [bold green]No newsletter unsubscribe links found.[/]")
        return

    console.print(f"\n  Found [bold yellow]{len(items)}[/] emails with unsubscribe links:\n")

    table = Table(show_header=True, header_style="bold cyan", show_lines=True)
    table.add_column("From", max_width=38)
    table.add_column("Subject", max_width=38)
    table.add_column("Unsubscribe Link", style="bold blue", max_width=50)

    for sender, subject, links in items:
        link = links.get("http") or links.get("mailto") or "—"
        if is_job_alert(sender, subject):
            table.add_row(
                f"[bold magenta]{(sender or '—')[:38]}[/]",
                f"[magenta]{(subject or '—')[:38]}[/]",
                link,
            )
        else:
            table.add_row(
                f"[white]{(sender or '—')[:38]}[/]",
                f"[dim]{(subject or '—')[:38]}[/]",
                link,
            )

    console.print(table)
    console.print()
