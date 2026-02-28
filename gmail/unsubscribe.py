import re

from rich.console import Console
from rich.table import Table

from gmail.analyzer import get_header

console = Console()


def get_unsubscribe_links(headers):
    """Parse the List-Unsubscribe header and return mailto/http links."""
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

    return result if result else None


def print_unsubscribe_report(items):
    """Print a formatted rich table of (sender, subject, links) tuples."""
    if not items:
        console.print("  [bold green]No newsletter unsubscribe links found.[/]")
        return

    console.print(f"\n  Found [bold yellow]{len(items)}[/] emails with unsubscribe links:\n")

    table = Table(show_header=True, header_style="bold cyan", show_lines=True)
    table.add_column("From", style="white", max_width=38)
    table.add_column("Subject", style="dim", max_width=38)
    table.add_column("Unsubscribe Link", style="bold blue", max_width=50)

    for sender, subject, links in items:
        link = links.get("http") or links.get("mailto") or "—"
        table.add_row(
            (sender or "—")[:38],
            (subject or "—")[:38],
            link,
        )

    console.print(table)
    console.print()
