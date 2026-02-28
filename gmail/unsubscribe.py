import re

from gmail.analyzer import get_header


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
    """Print a formatted list of (sender, subject, links) tuples."""
    if not items:
        print("  No newsletter unsubscribe links found.")
        return

    print(f"\n  Found {len(items)} emails with unsubscribe links:\n")
    for i, (sender, subject, links) in enumerate(items, 1):
        print(f"  {i:3}. From:    {sender[:70]}")
        print(f"       Subject: {subject[:70]}")
        if "http" in links:
            print(f"       Link:    {links['http']}")
        elif "mailto" in links:
            print(f"       Mailto:  {links['mailto']}")
        print()
