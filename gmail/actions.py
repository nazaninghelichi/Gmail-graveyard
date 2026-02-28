from tabulate import tabulate

from gmail.analyzer import get_header, get_age_days, is_newsletter, is_priority, categorize
from gmail.client import list_messages, get_message_metadata, trash_message, modify_labels, get_or_create_label
from gmail.duplicates import find_duplicates
from gmail.unsubscribe import get_unsubscribe_links, print_unsubscribe_report


def _fetch_with_headers(service, msg_list):
    """Fetch metadata headers for each message in msg_list, with progress output."""
    results = []
    total = len(msg_list)
    for i, msg in enumerate(msg_list, 1):
        if i % 50 == 0 or i == total:
            print(f"  Fetching email {i}/{total}...", end="\r")
        meta = get_message_metadata(service, msg["id"])
        results.append((msg["id"], meta.get("payload", {}).get("headers", [])))
    if total:
        print()
    return results


def _apply_labels(service, to_label):
    """Apply labels to a list of (msg_id, label_name) pairs, caching label IDs."""
    label_cache = {}
    for msg_id, label_name in to_label:
        if label_name not in label_cache:
            label_cache[label_name] = get_or_create_label(service, label_name)
        modify_labels(service, msg_id, add_labels=[label_cache[label_name]])


def _scan(service, config):
    """
    Scan the inbox and categorize all emails.
    Returns a dict with keys: to_trash, to_label, to_priority, newsletter_items, dup_ids.
    No changes are made.
    """
    rules = config.get("rules", {})
    delete_days = rules.get("delete_older_than_days", 90)
    priority_keywords = rules.get("priority_keywords", [])
    priority_senders = rules.get("priority_senders", [])

    all_msgs = list_messages(service, query="in:inbox", max_results=500)
    print(f"  Found {len(all_msgs)} messages in inbox. Fetching details...")
    msgs_with_headers = _fetch_with_headers(service, all_msgs)

    to_trash = []
    to_label = []
    to_priority = []
    newsletter_items = []

    for msg_id, headers in msgs_with_headers:
        if is_priority(headers, priority_keywords, priority_senders):
            to_priority.append(msg_id)
            continue

        if is_newsletter(headers):
            links = get_unsubscribe_links(headers)
            subject = get_header(headers, "Subject")
            sender = get_header(headers, "From")
            newsletter_items.append((sender, subject, links or {}))
            to_label.append((msg_id, "Newsletters"))
            continue

        age = get_age_days(headers)
        if age >= delete_days:
            to_trash.append(msg_id)
            continue

        category = categorize(headers)
        if category:
            to_label.append((msg_id, category))

    dup_groups = find_duplicates(msgs_with_headers)
    # Keep first copy, trash the rest
    dup_ids = [msg_id for group in dup_groups for msg_id in group[1:]]

    return {
        "to_trash": to_trash,
        "to_label": to_label,
        "to_priority": to_priority,
        "newsletter_items": newsletter_items,
        "dup_ids": dup_ids,
        "delete_days": delete_days,
    }


def _print_summary(result):
    newsletters = [x for x in result["to_label"] if x[1] == "Newsletters"]
    categorized = [x for x in result["to_label"] if x[1] != "Newsletters"]

    table = [
        ["Priority emails (protected)",    len(result["to_priority"]),     "starred, never deleted"],
        [f"Old emails (>{result['delete_days']} days)", len(result["to_trash"]), "move to Trash"],
        ["Newsletter emails",               len(newsletters),               "label 'Newsletters'"],
        ["Categorized emails",              len(categorized),               "labeled by category"],
        ["Duplicate emails",               len(result["dup_ids"]),          "move to Trash (keep 1)"],
    ]
    print(tabulate(table, headers=["Category", "Count", "Action"], tablefmt="simple"))
    print()


def run_cleanup(service, config, dry_run=True):
    """Full scan: show summary, optionally apply all changes."""
    max_trash = config.get("automation", {}).get("max_trash_per_run", 100)

    print(f"\nScanning Gmail {'(dry run)' if dry_run else ''}...\n")
    result = _scan(service, config)
    _print_summary(result)

    if result["newsletter_items"]:
        preview = result["newsletter_items"][:5]
        print_unsubscribe_report(preview)
        remainder = len(result["newsletter_items"]) - len(preview)
        if remainder > 0:
            print(f"  ...and {remainder} more. Run --action unsubscribe to see all.\n")

    if dry_run:
        print("Dry run complete. Run without --dry-run to apply changes.")
        return

    total_to_trash = result["to_trash"] + result["dup_ids"]
    if len(total_to_trash) > max_trash:
        print(
            f"Safety cap: {len(total_to_trash)} emails would be trashed, "
            f"but limit is {max_trash} (set in config.yaml)."
        )
        total_to_trash = total_to_trash[:max_trash]

    confirm = input("Proceed? [y/N]: ").strip().lower()
    if confirm != "y":
        print("Aborted. No changes made.")
        return

    print("Applying changes...")
    for msg_id in total_to_trash:
        trash_message(service, msg_id)

    _apply_labels(service, result["to_label"])

    for msg_id in result["to_priority"]:
        modify_labels(service, msg_id, add_labels=["STARRED"])

    print(
        f"Done. Trashed {len(total_to_trash)}, "
        f"labeled {len(result['to_label'])}, "
        f"starred {len(result['to_priority'])} emails."
    )


def run_unsubscribe_only(service, dry_run=True):
    """Scan for newsletter emails and list their unsubscribe links."""
    print("\nScanning for newsletter emails...\n")
    all_msgs = list_messages(service, query="in:inbox", max_results=500)
    msgs_with_headers = _fetch_with_headers(service, all_msgs)

    items = []
    to_label = []
    for msg_id, headers in msgs_with_headers:
        if is_newsletter(headers):
            links = get_unsubscribe_links(headers)
            items.append((get_header(headers, "From"), get_header(headers, "Subject"), links or {}))
            to_label.append((msg_id, "Newsletters"))

    print_unsubscribe_report(items)

    if dry_run or not to_label:
        return

    confirm = input(f"Label {len(to_label)} emails as 'Newsletters'? [y/N]: ").strip().lower()
    if confirm == "y":
        _apply_labels(service, to_label)
        print(f"Labeled {len(to_label)} emails.")


def run_duplicates_only(service, config, dry_run=True):
    """Find and optionally trash duplicate emails."""
    max_trash = config.get("automation", {}).get("max_trash_per_run", 100)
    print("\nScanning for duplicate emails...\n")
    all_msgs = list_messages(service, query="in:inbox", max_results=500)
    msgs_with_headers = _fetch_with_headers(service, all_msgs)

    dup_groups = find_duplicates(msgs_with_headers)
    dup_ids = [msg_id for group in dup_groups for msg_id in group[1:]]

    if not dup_ids:
        print("  No duplicates found.")
        return

    print(f"  Found {len(dup_groups)} duplicate groups ({len(dup_ids)} emails to remove).")

    if dry_run:
        print("Dry run. Run without --dry-run to trash duplicates.")
        return

    dup_ids = dup_ids[:max_trash]
    confirm = input(f"Move {len(dup_ids)} duplicate emails to Trash? [y/N]: ").strip().lower()
    if confirm == "y":
        for msg_id in dup_ids:
            trash_message(service, msg_id)
        print(f"Trashed {len(dup_ids)} duplicates.")


def run_organize_only(service, config, dry_run=True):
    """Categorize inbox emails and apply labels."""
    print("\nScanning for emails to organize...\n")
    all_msgs = list_messages(service, query="in:inbox", max_results=500)
    msgs_with_headers = _fetch_with_headers(service, all_msgs)

    to_label = []
    for msg_id, headers in msgs_with_headers:
        category = categorize(headers)
        if category:
            to_label.append((msg_id, category))

    if not to_label:
        print("  Nothing to organize.")
        return

    counts = {}
    for _, label in to_label:
        counts[label] = counts.get(label, 0) + 1

    print("  Labels to apply:")
    for label, count in sorted(counts.items()):
        print(f"    {label}: {count} emails")
    print()

    if dry_run:
        print("Dry run. Run without --dry-run to apply labels.")
        return

    confirm = input(f"Apply labels to {len(to_label)} emails? [y/N]: ").strip().lower()
    if confirm == "y":
        _apply_labels(service, to_label)
        print(f"Labeled {len(to_label)} emails.")


def run_delete_old_only(service, config, dry_run=True):
    """Find and optionally trash emails older than the configured threshold."""
    rules = config.get("rules", {})
    delete_days = rules.get("delete_older_than_days", 90)
    max_trash = config.get("automation", {}).get("max_trash_per_run", 100)
    priority_keywords = rules.get("priority_keywords", [])
    priority_senders = rules.get("priority_senders", [])

    print(f"\nScanning for emails older than {delete_days} days...\n")
    all_msgs = list_messages(service, query=f"in:inbox older_than:{delete_days}d", max_results=500)
    msgs_with_headers = _fetch_with_headers(service, all_msgs)

    to_trash = [
        msg_id for msg_id, headers in msgs_with_headers
        if not is_priority(headers, priority_keywords, priority_senders)
    ]
    protected = len(msgs_with_headers) - len(to_trash)

    print(f"  Found {len(to_trash)} old emails to trash ({protected} protected as priority).")

    if dry_run:
        print("Dry run. Run without --dry-run to trash them.")
        return

    to_trash = to_trash[:max_trash]
    confirm = input(f"Move {len(to_trash)} emails to Trash? [y/N]: ").strip().lower()
    if confirm == "y":
        for msg_id in to_trash:
            trash_message(service, msg_id)
        print(f"Trashed {len(to_trash)} emails.")
