#!/usr/bin/env python3
"""Gmail Graveyard — clean your inbox without touching your password."""

import argparse
import os
import sys

import questionary
import yaml
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

console = Console()

GUIDE_MD = """\
# Gmail Graveyard

Clean your Gmail inbox using a browser sign-in — no passwords in your code.

## What It Does

1. **Protects important emails** — job offers, invoices, urgent messages are starred and never deleted
2. **Trashes old emails** — moves emails older than 90 days to Trash
3. **Labels newsletters** — detects and labels marketing/newsletter email, and lists their unsubscribe links
4. **Organizes by category** — labels Shopping, Finance, Dev Tools, etc.
5. **Removes duplicates** — finds and trashes duplicate emails (keeps one)

## Commands

    python main.py                        Full cleanup (dry-run preview, then confirm)
    python main.py --dry-run              Preview only — no changes made
    python main.py --action delete-old    Only trash old emails
    python main.py --action unsubscribe   Only scan for unsubscribe links
    python main.py --action organize      Only apply category labels
    python main.py --action duplicates    Only find and trash duplicates
    python main.py --auto                 Start scheduled auto-cleanup (see config.yaml)
    python main.py --tui                  Launch interactive TUI dashboard
    python main.py guide                  Show this guide
    python main.py signout                Sign out (deletes local token)

## Options

`--days N`   Override the delete threshold (e.g. `--days 30` for 30-day-old emails)

## First-Time Setup

1. Go to console.cloud.google.com
2. Create a project and enable the Gmail API
3. Go to APIs & Services > Credentials
4. Create OAuth 2.0 Credentials (Desktop app)
5. Download the file and save it as `credentials.json` in this folder
6. Edit `config.yaml` to add your priority senders and adjust rules
7. Run: `python main.py --dry-run`

## Sign-In

On first run, a browser window opens for Google sign-in.
Your password is never stored — only a permission token (`token.json`).

## Sign-Out

    python main.py signout

This deletes `token.json` from your machine.
To fully revoke access: https://myaccount.google.com/permissions

## Config

Edit `config.yaml` to customize:

- `delete_older_than_days` (default: 90)
- `priority_keywords` (emails matching these are never deleted)
- `priority_senders` (email addresses that are always protected)
- `max_trash_per_run` (safety cap, default: 100)
"""


def _load_config():
    if not os.path.exists("config.yaml"):
        console.print("[bold red]config.yaml not found.[/]")
        console.print("Copy config.example.yaml to config.yaml and edit it, then run again.")
        sys.exit(1)
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(
        description="Gmail Graveyard — clean your inbox without touching your password.",
        add_help=True,
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["guide", "signout"],
        help="guide: show usage | signout: delete local sign-in token",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would happen — no changes made",
    )
    parser.add_argument(
        "--action",
        choices=["all", "delete-old", "unsubscribe", "organize", "duplicates"],
        default="all",
        help="Which action to run (default: all)",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Start scheduled auto-cleanup (runs daily at 09:00)",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Launch the interactive TUI dashboard",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Override: delete emails older than N days",
    )

    args = parser.parse_args()

    # Subcommands that don't need Gmail connection
    if args.command == "guide":
        console.print(Panel(Markdown(GUIDE_MD), title="[bold cyan]Gmail Graveyard[/]", border_style="cyan"))
        return

    if args.command == "signout":
        from gmail.auth import signout
        signout()
        return

    # Load config
    config = _load_config()
    if args.days:
        config.setdefault("rules", {})["delete_older_than_days"] = args.days

    # Connect to Gmail
    from gmail.auth import get_credentials
    from gmail.client import build_service

    console.print("[bold cyan]Connecting to Gmail...[/]")
    creds = get_credentials()
    service = build_service(creds)
    console.print("[bold green]Connected.[/]\n")

    # Launch TUI if requested
    if args.tui:
        from gmail.tui import GmailGraveyardApp
        GmailGraveyardApp(service=service, config=config).run()
        return

    if args.auto:
        from gmail.scheduler import start_scheduler
        start_scheduler(config)
        return

    from gmail.actions import (
        run_cleanup,
        run_delete_old_only,
        run_duplicates_only,
        run_organize_only,
        run_unsubscribe_only,
    )

    # If no explicit flags were passed, show a pre-scan menu
    no_explicit_flags = (
        args.action == "all"
        and not args.dry_run
        and not args.days
    )
    if no_explicit_flags:
        while True:
            console.print()
            action_choice = questionary.select(
                "What would you like to do?",
                choices=[
                    "Full cleanup  (scan + auto-actions + choose per category)",
                    "Delete old emails only",
                    "Find newsletters & unsubscribe links",
                    "Organize by category  (apply labels)",
                    "Find duplicates",
                    "Clear review history  (re-show previously skipped/labeled emails)",
                    "Exit",
                ],
            ).ask()

            if action_choice and "Clear review history" in action_choice:
                from gmail.state import clear_reviewed, count_reviewed
                n = count_reviewed()
                confirmed = questionary.confirm(
                    f"Clear history of {n} reviewed emails? They will reappear on next scan.",
                    default=False,
                ).ask()
                if confirmed:
                    clear_reviewed()
                    console.print("[bold green]Review history cleared.[/]")
                continue

            if action_choice is None or action_choice == "Exit":
                exit_choice = questionary.select(
                    "How do you want to exit?",
                    choices=[
                        "Soft exit  (stay signed in — token kept)",
                        "Sign out   (delete token — browser sign-in required next time)",
                    ],
                ).ask()
                if exit_choice is None or exit_choice.startswith("Soft"):
                    console.print("[dim]Goodbye.[/]")
                else:
                    from gmail.auth import signout
                    signout()
                return

            mode_choice = questionary.select(
                "Run mode:",
                choices=[
                    "Dry run  (preview only — no changes made)",
                    "Live run  (apply changes)",
                ],
            ).ask()

            if mode_choice is None:
                return

            dry_run = mode_choice.startswith("Dry")

            if "Full cleanup" in action_choice:
                run_cleanup(service, config, dry_run=dry_run)
            elif "Delete old" in action_choice:
                run_delete_old_only(service, config, dry_run=dry_run)
            elif "newsletters" in action_choice:
                run_unsubscribe_only(service, config, dry_run=dry_run)
            elif "Organize" in action_choice:
                run_organize_only(service, config, dry_run=dry_run)
            elif "duplicates" in action_choice:
                run_duplicates_only(service, config, dry_run=dry_run)

            # Loop back to the menu after each action completes
        return

    # Explicit flags path (--action / --dry-run passed directly)
    dry_run = args.dry_run

    if args.action == "all":
        run_cleanup(service, config, dry_run=dry_run)
    elif args.action == "unsubscribe":
        run_unsubscribe_only(service, dry_run=dry_run)
    elif args.action == "duplicates":
        run_duplicates_only(service, config, dry_run=dry_run)
    elif args.action == "organize":
        run_organize_only(service, config, dry_run=dry_run)
    elif args.action == "delete-old":
        run_delete_old_only(service, config, dry_run=dry_run)


if __name__ == "__main__":
    main()
