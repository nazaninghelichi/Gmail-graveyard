import questionary
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TaskProgressColumn
from rich.table import Table

from gmail.analyzer import get_header, get_age_days, is_job_email, is_newsletter, is_priority, categorize
from gmail.client import list_messages, get_message_metadata, trash_message, modify_labels, get_or_create_label
from gmail.duplicates import find_duplicates
from gmail.state import load_reviewed, mark_reviewed
from gmail.unsubscribe import attempt_unsubscribe, get_unsubscribe_links, is_job_alert, print_unsubscribe_report

console = Console()


def _fetch_with_headers(service, msg_list):
    """Fetch metadata headers for each message in msg_list, with a progress bar."""
    results = []
    total = len(msg_list)
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Fetching emails", total=total)
        for msg in msg_list:
            meta = get_message_metadata(service, msg["id"])
            results.append((msg["id"], meta.get("payload", {}).get("headers", [])))
            progress.advance(task)
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
    Filters out already-reviewed message IDs.
    Returns auto-action lists and category_groups for user to decide.
    No changes are made.
    """
    rules = config.get("rules", {})
    delete_days = rules.get("delete_older_than_days", 90)
    priority_keywords = rules.get("priority_keywords", [])
    priority_senders = rules.get("priority_senders", [])

    all_msgs = list_messages(service, query="in:inbox", max_results=500)
    console.print(f"  Found [bold yellow]{len(all_msgs)}[/] messages in inbox. Fetching details...")
    msgs_with_headers = _fetch_with_headers(service, all_msgs)

    reviewed = load_reviewed()

    to_trash = []
    to_priority = []
    category_groups = {}
    newsletter_items = []   # parallel list with category_groups["Newsletters"]
    skipped_count = 0

    for msg_id, headers in msgs_with_headers:
        if is_priority(headers, priority_keywords, priority_senders):
            to_priority.append(msg_id)
            continue

        age = get_age_days(headers)
        if age >= delete_days:
            to_trash.append(msg_id)
            continue

        # Skip already-reviewed emails (labeled or skipped in a previous run)
        if msg_id in reviewed:
            skipped_count += 1
            continue

        if is_newsletter(headers):
            links = get_unsubscribe_links(headers)
            newsletter_items.append((
                get_header(headers, "From"),
                get_header(headers, "Subject"),
                links or {},
            ))
            category_groups.setdefault("Newsletters", []).append(msg_id)
            continue

        category = categorize(headers)
        if category:
            category_groups.setdefault(category, []).append(msg_id)

    dup_groups = find_duplicates(msgs_with_headers)
    dup_ids = [msg_id for group in dup_groups for msg_id in group[1:]]

    if skipped_count:
        console.print(
            f"  [dim]Skipping {skipped_count} already-reviewed emails "
            f"(run 'Clear review history' to reset).[/]"
        )

    return {
        "to_trash": to_trash,
        "to_priority": to_priority,
        "category_groups": category_groups,
        "newsletter_items": newsletter_items,
        "dup_ids": dup_ids,
        "delete_days": delete_days,
    }


def run_cleanup(service, config, dry_run=True):
    """Full scan: auto-handle old/priority/duplicates, then ask user what to do per category."""
    max_trash = config.get("automation", {}).get("max_trash_per_run", 500)

    console.print("\n[bold cyan]Scanning Gmail...[/]\n")
    result = _scan(service, config)

    # --- Auto-actions summary ---
    table = Table(title="Auto-actions", show_header=True, header_style="bold cyan")
    table.add_column("Action", style="white")
    table.add_column("Count", justify="right", style="bold yellow")
    table.add_column("Effect", style="dim")
    table.add_row("Priority emails (protected)", str(len(result["to_priority"])), "starred, never deleted")
    table.add_row(f"Old emails (>{result['delete_days']} days)", str(len(result["to_trash"])), "move to Trash")
    table.add_row("Duplicate emails", str(len(result["dup_ids"])), "move to Trash (keep 1)")
    console.print(table)
    console.print()

    if dry_run:
        if result["category_groups"]:
            console.print("[bold cyan]Categories found[/] (run without --dry-run to choose what to do):\n")
            for category, msg_ids in result["category_groups"].items():
                console.print(f"  [bold yellow]{category}[/]: {len(msg_ids)} emails")
        console.print("\n[bold green]Dry run complete.[/]")
        return

    # --- Interactive menu: user decides per category ---
    category_actions = {}
    if result["category_groups"]:
        # 1. Overview table — show all categories upfront
        overview = Table(show_header=True, header_style="bold cyan")
        overview.add_column("Category", style="white")
        overview.add_column("Emails", justify="right", style="bold yellow")
        for category, msg_ids in result["category_groups"].items():
            overview.add_row(category, str(len(msg_ids)))
        console.print(Panel(overview, title="[bold cyan]Categories found[/]", border_style="cyan"))
        console.print()

        # 2. Per-category decision — numbered so user knows where they are
        total_cats = len(result["category_groups"])
        console.print("[bold cyan]Choose an action for each category:[/]\n")
        for i, (category, msg_ids) in enumerate(result["category_groups"].items(), 1):
            choice = questionary.select(
                f"[{i}/{total_cats}] {category}  ({len(msg_ids)} emails)",
                choices=["Delete", "Label", "Skip"],
                default="Skip",
            ).ask()
            if choice is None:
                console.print("[bold red]Aborted.[/]")
                return
            category_actions[category] = choice[0].lower()  # d / l / s

        # 3. Summary of choices before confirming
        console.print()
        action_display = {
            "d": "[bold red]Delete[/]",
            "l": "[bold green]Label[/]",
            "s": "[dim]Skip[/]",
        }
        summary = Table(show_header=True, header_style="bold cyan")
        summary.add_column("Category", style="white")
        summary.add_column("Emails", justify="right", style="bold yellow")
        summary.add_column("Action")
        for category, msg_ids in result["category_groups"].items():
            action = category_actions.get(category, "s")
            summary.add_row(category, str(len(msg_ids)), action_display[action])
        console.print(Panel(summary, title="[bold cyan]Your choices[/]", border_style="cyan"))
        console.print()

    # Show unsubscribe links for newsletters
    if "Newsletters" in result["category_groups"] and result["newsletter_items"]:
        print_unsubscribe_report(result["newsletter_items"][:5])
        remainder = len(result["newsletter_items"]) - 5
        if remainder > 0:
            console.print(f"  ...and [bold yellow]{remainder}[/] more. Run --action unsubscribe to see all.\n")

    # --- Build final action lists ---
    to_trash = list(result["to_trash"]) + list(result["dup_ids"])
    to_label = []
    skipped_ids = []
    for category, msg_ids in result["category_groups"].items():
        action = category_actions.get(category, "s")
        if action == "d":
            to_trash.extend(msg_ids)
        elif action == "l":
            to_label.extend([(mid, category) for mid in msg_ids])
        else:
            skipped_ids.extend(msg_ids)  # "s" — remember these for next run

    if len(to_trash) > max_trash:
        console.print(f"[bold red]Safety cap:[/] {len(to_trash)} to trash, limit is {max_trash} (set in config.yaml).")
        to_trash = to_trash[:max_trash]

    if not to_trash and not to_label and not result["to_priority"]:
        console.print("Nothing to do.")
        mark_reviewed(skipped_ids)
        return

    console.print(
        f"\nReady: trash [bold yellow]{len(to_trash)}[/], "
        f"label [bold yellow]{len(to_label)}[/], "
        f"star [bold yellow]{len(result['to_priority'])}[/] emails."
    )
    confirmed = questionary.confirm("Proceed?", default=False).ask()
    if not confirmed:
        console.print("[bold red]Aborted. No changes made.[/]")
        return

    console.print("[bold cyan]Applying changes...[/]")
    for msg_id in to_trash:
        trash_message(service, msg_id)
    _apply_labels(service, to_label)
    for msg_id in result["to_priority"]:
        modify_labels(service, msg_id, add_labels=["STARRED"])

    # Mark labeled and skipped emails as reviewed so they don't reappear
    mark_reviewed([mid for mid, _ in to_label] + skipped_ids)

    console.print(
        f"[bold green]Done.[/] Trashed {len(to_trash)}, "
        f"labeled {len(to_label)}, starred {len(result['to_priority'])} emails."
    )


def run_unsubscribe_only(service, config, dry_run=True):
    """Scan for newsletter emails, list unsubscribe links, and optionally unsubscribe."""
    max_trash = config.get("automation", {}).get("max_trash_per_run", 500)

    console.print("\n[bold cyan]Scanning for newsletter emails...[/]\n")
    all_msgs = list_messages(service, query="in:inbox", max_results=500)
    msgs_with_headers = _fetch_with_headers(service, all_msgs)

    reviewed = load_reviewed()
    items = []        # (sender, subject, links) — new, with parseable unsubscribe links
    to_label = []     # (msg_id, label) — all new newsletter emails
    already_reviewed_count = 0
    no_link_count = 0

    for msg_id, headers in msgs_with_headers:
        if is_newsletter(headers):
            if msg_id in reviewed:
                already_reviewed_count += 1
                continue
            links = get_unsubscribe_links(headers)
            if links:
                items.append((get_header(headers, "From"), get_header(headers, "Subject"), links))
            else:
                no_link_count += 1
            to_label.append((msg_id, "Newsletters"))

    # Clear, specific feedback about why results might be empty
    if not items and not to_label:
        if already_reviewed_count:
            console.print(
                f"[bold yellow]All {already_reviewed_count} newsletter emails were already reviewed.[/]\n"
                "  Use [bold]Clear review history[/] from the main menu to re-scan them."
            )
        else:
            console.print("[bold green]No newsletter emails found in your inbox.[/]")
        return

    print_unsubscribe_report(items)

    if no_link_count:
        console.print(
            f"[dim]  {no_link_count} newsletter email(s) had no parseable unsubscribe link "
            f"and are not shown above.[/]\n"
        )
    if already_reviewed_count:
        console.print(
            f"[dim]  {already_reviewed_count} previously reviewed newsletter(s) skipped. "
            f"Use 'Clear review history' to re-scan.[/]\n"
        )

    if dry_run:
        if items:
            console.print("Dry run — run without --dry-run to unsubscribe.")
        return

    # --- Let user pick which senders to unsubscribe from ---
    if items:
        console.print("[dim]  All selected by default — Space = deselect   ↑↓ = navigate   Enter = confirm[/]\n")
        choices = [
            questionary.Choice(
                title=(
                    f"[JOB ALERT] {(sender or '—')[:45]}"
                    if is_job_alert(sender, subject)
                    else f"{(sender or '—')[:55]}"
                ),
                value=i,
                checked=True,
            )
            for i, (sender, subject, links) in enumerate(items)
        ]
        selected_indices = questionary.checkbox(
            f"Unsubscribe from ({len(items)} selected — uncheck any to skip):",
            choices=choices,
        ).ask()

        if selected_indices is None:
            console.print("[bold red]Aborted.[/]")
            return

        if selected_indices:
            import time
            console.print()
            if len(selected_indices) > 10:
                console.print(
                    f"[dim]Sending {len(selected_indices)} requests with a small delay "
                    f"to avoid Gmail rate limits...[/]\n"
                )
            result_rows = []
            for idx, i in enumerate(selected_indices):
                sender, subject, links = items[i]
                method, status = attempt_unsubscribe(service, links)
                result_rows.append((sender, method, status))
                # Pace mailto sends to avoid hitting Gmail's sending rate limit
                if method == "mailto" and idx < len(selected_indices) - 1:
                    time.sleep(1)

            result_table = Table(show_header=True, header_style="bold cyan")
            result_table.add_column("Sender", style="white", max_width=50)
            result_table.add_column("Method", style="dim")
            result_table.add_column("Result")
            status_display = {
                "ok":     "[bold green]Unsubscribed[/]",
                "manual": "[bold yellow]Sent — confirm on their site[/]",
                "failed": "[bold red]Failed[/]",
            }
            for sender, method, status in result_rows:
                result_table.add_row(
                    (sender or "—")[:50],
                    method,
                    status_display.get(status, status),
                )
            console.print(result_table)
            console.print()

    # --- Label or delete all newsletter emails (with cap) ---
    if to_label:
        bulk_choice = questionary.select(
            f"What do you want to do with all {len(to_label)} newsletter emails?",
            choices=["Label", "Delete", "Skip"],
            default="Skip",
        ).ask()
        if bulk_choice == "Label":
            _apply_labels(service, to_label)
            mark_reviewed([mid for mid, _ in to_label])
            console.print(f"[bold green]Labeled {len(to_label)} emails.[/]")
        elif bulk_choice == "Delete":
            to_delete = [mid for mid, _ in to_label]
            if len(to_delete) > max_trash:
                console.print(
                    f"[bold red]Safety cap:[/] {len(to_delete)} to trash, "
                    f"limit is {max_trash} (set in config.yaml)."
                )
                to_delete = to_delete[:max_trash]
            for msg_id in to_delete:
                trash_message(service, msg_id)
            console.print(f"[bold green]Deleted {len(to_delete)} emails.[/]")
        else:
            # Skipped — remember them so they don't reappear
            mark_reviewed([mid for mid, _ in to_label])


def run_duplicates_only(service, config, dry_run=True):
    """Find and optionally trash duplicate emails."""
    max_trash = config.get("automation", {}).get("max_trash_per_run", 500)
    console.print("\n[bold cyan]Scanning for duplicate emails...[/]\n")
    all_msgs = list_messages(service, query="in:inbox", max_results=500)
    msgs_with_headers = _fetch_with_headers(service, all_msgs)

    dup_groups = find_duplicates(msgs_with_headers)
    dup_ids = [msg_id for group in dup_groups for msg_id in group[1:]]

    if not dup_ids:
        console.print("  [bold green]No duplicates found.[/]")
        return

    console.print(
        f"  Found [bold yellow]{len(dup_groups)}[/] duplicate groups "
        f"([bold yellow]{len(dup_ids)}[/] emails to remove)."
    )

    if dry_run:
        console.print("Dry run. Run without --dry-run to trash duplicates.")
        return

    dup_ids = dup_ids[:max_trash]
    confirmed = questionary.confirm(f"Move {len(dup_ids)} duplicate emails to Trash?", default=False).ask()
    if confirmed:
        for msg_id in dup_ids:
            trash_message(service, msg_id)
        console.print(f"[bold green]Trashed {len(dup_ids)} duplicates.[/]")


def run_organize_only(service, config, dry_run=True):
    """Categorize inbox emails and apply labels."""
    console.print("\n[bold cyan]Scanning for emails to organize...[/]\n")
    all_msgs = list_messages(service, query="in:inbox", max_results=500)
    msgs_with_headers = _fetch_with_headers(service, all_msgs)

    reviewed = load_reviewed()
    to_label = [
        (msg_id, cat)
        for msg_id, headers in msgs_with_headers
        if msg_id not in reviewed
        for cat in [categorize(headers)]
        if cat
    ]

    if not to_label:
        console.print("  [bold green]Nothing to organize.[/]")
        return

    counts = {}
    for _, label in to_label:
        counts[label] = counts.get(label, 0) + 1

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Label", style="white")
    table.add_column("Emails", justify="right", style="bold yellow")
    for label, count in sorted(counts.items()):
        table.add_row(label, str(count))
    console.print(table)
    console.print()

    if dry_run:
        console.print("Dry run. Run without --dry-run to apply labels.")
        return

    confirmed = questionary.confirm(f"Apply labels to {len(to_label)} emails?", default=False).ask()
    if confirmed:
        _apply_labels(service, to_label)
        mark_reviewed([mid for mid, _ in to_label])
        console.print(f"[bold green]Labeled {len(to_label)} emails.[/]")


def run_delete_old_only(service, config, dry_run=True):
    """Find and optionally trash emails older than a user-chosen threshold."""
    rules = config.get("rules", {})
    config_days = rules.get("delete_older_than_days", 90)
    max_trash = config.get("automation", {}).get("max_trash_per_run", 500)
    priority_keywords = rules.get("priority_keywords", [])
    priority_senders = rules.get("priority_senders", [])

    # Ask the user how old emails should be
    presets = ["30 days", "60 days", "90 days", "180 days", "1 year (365 days)", "Custom..."]
    preset_map = {"30 days": 30, "60 days": 60, "90 days": 90,
                  "180 days": 180, "1 year (365 days)": 365}
    default_label = f"{config_days} days" if f"{config_days} days" in preset_map else "90 days"

    age_choice = questionary.select(
        "Delete emails older than:",
        choices=presets,
        default=default_label if default_label in presets else "90 days",
    ).ask()

    if age_choice is None:
        return

    if age_choice == "Custom...":
        raw = questionary.text(
            "Enter number of days:",
            validate=lambda v: v.isdigit() and int(v) > 0 or "Please enter a positive number",
        ).ask()
        if raw is None:
            return
        delete_days = int(raw)
    else:
        delete_days = preset_map[age_choice]

    console.print(f"\n[bold cyan]Scanning for emails older than {delete_days} days...[/]\n")
    all_msgs = list_messages(service, query=f"in:inbox older_than:{delete_days}d", max_results=500)
    msgs_with_headers = _fetch_with_headers(service, all_msgs)

    to_trash = [
        msg_id for msg_id, headers in msgs_with_headers
        if not is_priority(headers, priority_keywords, priority_senders)
    ]
    protected = len(msgs_with_headers) - len(to_trash)

    console.print(
        f"  Found [bold yellow]{len(to_trash)}[/] old emails to trash "
        f"([bold blue]{protected}[/] protected as priority)."
    )

    if dry_run:
        console.print("Dry run. Run without --dry-run to trash them.")
        return

    to_trash = to_trash[:500]
    confirmed = questionary.confirm(f"Move {len(to_trash)} emails to Trash?", default=False).ask()
    if confirmed:
        for msg_id in to_trash:
            trash_message(service, msg_id)
        console.print(f"[bold green]Trashed {len(to_trash)} emails.[/]")


def run_browse_and_delete(service, config):
    """List the last 100 inbox emails and let the user select which to delete."""
    max_trash = config.get("automation", {}).get("max_trash_per_run", 500)
    rules = config.get("rules", {})
    priority_keywords = rules.get("priority_keywords", [])
    priority_senders = rules.get("priority_senders", [])

    console.print("\n[bold cyan]Loading last 100 emails...[/]\n")
    all_msgs = list_messages(service, query="in:inbox", max_results=100)
    msgs_with_headers = _fetch_with_headers(service, all_msgs)

    if not msgs_with_headers:
        console.print("  [bold green]Inbox is empty.[/]")
        return

    # Build display items
    email_items = []
    for msg_id, headers in msgs_with_headers:
        sender = get_header(headers, "From") or "—"
        subject = get_header(headers, "Subject") or "(no subject)"
        age = get_age_days(headers)
        if age == 0:
            age_str = "today    "
        elif age == 1:
            age_str = "yesterday"
        else:
            age_str = f"{age}d ago   "[:9]
        display_sender = sender.split("<")[0].strip() or sender
        priority = is_priority(headers, priority_keywords, priority_senders)
        email_items.append((msg_id, display_sender, subject, age_str, priority))

    priority_count = sum(1 for *_, p in email_items if p)
    if priority_count:
        console.print(f"[dim]  ★ = priority email — be careful deleting these[/]")
    console.print("[dim]  All selected by default — Space = deselect   ↑↓ = navigate   Enter = confirm[/]")
    console.print()

    mode = questionary.select(
        "Selection mode:",
        choices=[
            "Select emails to DELETE",
            "Select emails to KEEP  (everything else gets deleted)",
        ],
    ).ask()
    if mode is None:
        return

    keep_mode = "KEEP" in mode

    choices = [
        questionary.Choice(
            title=(
                f"★ {age_str}  {display_sender[:28]:<28}  {subject[:48]}"
                if priority
                else f"  {age_str}  {display_sender[:28]:<28}  {subject[:48]}"
            ),
            value=i,
            checked=True,
        )
        for i, (msg_id, display_sender, subject, age_str, priority) in enumerate(email_items)
    ]

    selected_indices = questionary.checkbox(
        (
            f"Emails to KEEP ({len(email_items)} shown — uncheck any to delete):"
            if keep_mode
            else f"Emails to DELETE ({len(email_items)} shown — uncheck any to keep):"
        ),
        choices=choices,
    ).ask()

    if selected_indices is None:
        return

    if keep_mode:
        kept = set(selected_indices)
        selected_indices = [i for i in range(len(email_items)) if i not in kept]
        if not selected_indices:
            console.print("[dim]Nothing to delete — all emails kept.[/]")
            return

    if not selected_indices:
        console.print("[dim]Nothing selected.[/]")
        return

    to_delete = [email_items[i][0] for i in selected_indices if not email_items[i][4]]
    priority_selected = [email_items[i] for i in selected_indices if email_items[i][4]]
    if priority_selected:
        console.print(
            f"[bold yellow]Warning:[/] {len(priority_selected)} priority email(s) "
            f"{'kept safe' if keep_mode else 'skipped'}.\n"
        )
        if not to_delete:
            return

    if len(to_delete) > max_trash:
        console.print(
            f"[bold red]Safety cap:[/] {len(to_delete)} selected, "
            f"limit is {max_trash}. First {max_trash} will be deleted."
        )
        to_delete = to_delete[:max_trash]

    confirmed = questionary.confirm(
        f"Delete {len(to_delete)} selected emails?", default=False
    ).ask()
    if confirmed:
        for msg_id in to_delete:
            trash_message(service, msg_id)
        console.print(f"[bold green]Deleted {len(to_delete)} emails.[/]")


def run_job_emails(service, config):
    """Find all job-related emails in the inbox and let the user act on them."""
    console.print("\n[bold cyan]Scanning for job-related emails...[/]\n")
    all_msgs = list_messages(service, query="in:inbox", max_results=500)
    msgs_with_headers = _fetch_with_headers(service, all_msgs)

    job_items = []  # (msg_id, sender, subject, age_days)
    for msg_id, headers in msgs_with_headers:
        if is_job_email(headers):
            sender = get_header(headers, "From") or "—"
            subject = get_header(headers, "Subject") or "(no subject)"
            age = get_age_days(headers)
            display_sender = sender.split("<")[0].strip() or sender
            job_items.append((msg_id, display_sender, subject, age))

    if not job_items:
        console.print("  [bold green]No job-related emails found.[/]")
        return

    # Sort newest first
    job_items.sort(key=lambda x: x[3])

    # Display summary table
    table = Table(
        title=f"[bold magenta]Job-related emails ({len(job_items)} found)[/]",
        show_header=True,
        header_style="bold magenta",
        show_lines=True,
    )
    table.add_column("Age", style="dim", width=10)
    table.add_column("From", style="white", max_width=30)
    table.add_column("Subject", style="bold", max_width=55)

    for _, sender, subject, age in job_items:
        if age == 0:
            age_str = "today"
        elif age == 1:
            age_str = "yesterday"
        else:
            age_str = f"{age}d ago"
        table.add_row(age_str, sender[:30], subject[:55])

    console.print(table)
    console.print()

    # Let user choose what to do
    action = questionary.select(
        f"What do you want to do with these {len(job_items)} emails?",
        choices=[
            "Star all  (mark as important, never auto-deleted)",
            "Label all as 'Jobs'",
            "Pick individually  (choose per email)",
            "Nothing  (just wanted to see them)",
        ],
    ).ask()

    if action is None or "Nothing" in action:
        return

    if "Star all" in action:
        for msg_id, _, _, _ in job_items:
            modify_labels(service, msg_id, add_labels=["STARRED"])
        console.print(f"[bold green]Starred {len(job_items)} emails.[/]")

    elif "Label all" in action:
        _apply_labels(service, [(msg_id, "Jobs") for msg_id, _, _, _ in job_items])
        console.print(f"[bold green]Labeled {len(job_items)} emails as 'Jobs'.[/]")

    elif "Pick individually" in action:
        console.print("[dim]  All selected by default — Space = deselect   ↑↓ = navigate   Enter = confirm[/]\n")
        choices = [
            questionary.Choice(
                title=f"{'today' if age == 0 else 'yesterday' if age == 1 else f'{age}d ago':>9}  "
                      f"{sender[:28]:<28}  {subject[:45]}",
                value=i,
                checked=True,
            )
            for i, (_, sender, subject, age) in enumerate(job_items)
        ]
        selected = questionary.checkbox(
            "Select emails to act on (uncheck any to skip):",
            choices=choices,
        ).ask()
        if not selected:
            return

        act = questionary.select(
            f"Action for {len(selected)} selected emails:",
            choices=["Star", "Label as 'Jobs'", "Delete"],
        ).ask()

        if act == "Star":
            for i in selected:
                modify_labels(service, job_items[i][0], add_labels=["STARRED"])
            console.print(f"[bold green]Starred {len(selected)} emails.[/]")
        elif act == "Label as 'Jobs'":
            _apply_labels(service, [(job_items[i][0], "Jobs") for i in selected])
            console.print(f"[bold green]Labeled {len(selected)} emails.[/]")
        elif act == "Delete":
            max_trash = config.get("automation", {}).get("max_trash_per_run", 500)
            to_delete = [job_items[i][0] for i in selected][:max_trash]
            for msg_id in to_delete:
                trash_message(service, msg_id)
            console.print(f"[bold green]Deleted {len(to_delete)} emails.[/]")
