"""Gmail Graveyard — interactive Textual TUI (launched with --tui)."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Label,
    ProgressBar,
    RadioButton,
    RadioSet,
    Rule,
    Static,
)
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual import work


# ---------------------------------------------------------------------------
# ScanningScreen
# ---------------------------------------------------------------------------

class ScanningScreen(Screen):
    """Shown while the inbox scan is running."""

    CSS = """
    ScanningScreen {
        align: center middle;
    }
    #scanning-box {
        width: 60;
        height: 10;
        border: solid $accent;
        padding: 2 4;
        align: center middle;
    }
    #scanning-label {
        text-align: center;
        margin-bottom: 2;
    }
    ProgressBar {
        width: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="scanning-box"):
            yield Label("[bold cyan]Scanning your Gmail inbox…[/]", id="scanning-label")
            yield ProgressBar(id="scan-progress", show_eta=False)
        yield Footer()

    def on_mount(self) -> None:
        # Indeterminate spinner until scan finishes
        self.query_one(ProgressBar).update(total=None)


# ---------------------------------------------------------------------------
# ResultsScreen
# ---------------------------------------------------------------------------

class ResultsScreen(Screen):
    """Shown after a cleanup (or dry run) completes."""

    BINDINGS = [
        ("escape", "pop_screen", "Back"),
        ("q", "app.quit", "Quit"),
    ]

    CSS = """
    ResultsScreen {
        align: center middle;
    }
    #results-box {
        width: 50;
        height: auto;
        border: solid $success;
        padding: 2 4;
        align: center middle;
    }
    #results-title {
        text-align: center;
        margin-bottom: 1;
    }
    #results-table {
        margin-bottom: 1;
    }
    #dry-run-note {
        text-align: center;
        color: $warning;
        margin-bottom: 1;
    }
    #results-buttons {
        align: center middle;
        height: auto;
        margin-top: 1;
    }
    """

    def __init__(self, results: dict) -> None:
        super().__init__()
        self._results = results

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="results-box"):
            yield Label("[bold green]Cleanup Complete![/]", id="results-title")
            if self._results.get("dry_run"):
                yield Label("[italic](Dry run — no changes made)[/]", id="dry-run-note")
            table = DataTable(id="results-table", show_cursor=False)
            yield table
            with Horizontal(id="results-buttons"):
                yield Button("Back", id="btn-back", variant="default")
                yield Button("Quit", id="btn-quit", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Action", "Count")
        table.add_row("Trashed", str(self._results.get("trashed", 0)))
        table.add_row("Labeled", str(self._results.get("labeled", 0)))
        table.add_row("Starred", str(self._results.get("starred", 0)))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.app.pop_screen()
        elif event.button.id == "btn-quit":
            self.app.exit()


# ---------------------------------------------------------------------------
# MainScreen
# ---------------------------------------------------------------------------

class MainScreen(Screen):
    """Main dashboard: auto-actions panel + category checkboxes."""

    BINDINGS = [
        ("s", "scan", "Scan"),
        ("r", "run_cleanup", "Run"),
        ("ctrl+d", "dry_run", "Dry Run"),
        ("q", "app.quit", "Quit"),
    ]

    CSS = """
    #main-body {
        height: 1fr;
        padding: 1;
    }
    #auto-panel {
        width: 1fr;
        border: solid $accent;
        padding: 1 2;
        margin-right: 1;
    }
    #cat-panel {
        width: 1fr;
        border: solid $accent;
        padding: 1 2;
    }
    .panel-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        padding-bottom: 1;
    }
    #cat-list {
        height: 1fr;
        padding: 0 1;
    }
    #action-label {
        margin-top: 1;
        color: $text-muted;
    }
    #footer-buttons {
        height: 5;
        padding: 1 2;
        border-top: solid $accent;
        align: center middle;
    }
    Button {
        margin: 0 1;
    }
    """

    def __init__(self, service, config: dict) -> None:
        super().__init__()
        self._service = service
        self._config = config
        self._scan_data: dict | None = None
        self._default_action = "l"  # d=delete, l=label, s=skip

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main-body"):
            # Left panel — auto-actions
            with Vertical(id="auto-panel"):
                yield Static("[bold cyan]AUTO-ACTIONS[/]", classes="panel-title")
                yield DataTable(id="auto-table", show_cursor=False)
            # Right panel — categories
            with Vertical(id="cat-panel"):
                yield Static("[bold cyan]CATEGORIES[/]", classes="panel-title")
                yield ScrollableContainer(id="cat-list")
                yield Rule()
                yield Static("For checked categories:", id="action-label")
                with RadioSet(id="default-action"):
                    yield RadioButton("Delete", id="rb-delete")
                    yield RadioButton("Label", id="rb-label", value=True)
                    yield RadioButton("Skip", id="rb-skip")
        with Horizontal(id="footer-buttons"):
            yield Button("Scan", id="btn-scan", variant="primary")
            yield Button("Dry Run", id="btn-dry-run", variant="default")
            yield Button("Run Cleanup", id="btn-run", variant="success")
            yield Button("Sign Out", id="btn-signout", variant="warning")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#auto-table", DataTable)
        table.add_columns("Category", "Count", "Effect")
        table.add_row("—", "—", "Scan to populate")
        self._set_run_buttons_enabled(False)

    def _set_run_buttons_enabled(self, enabled: bool) -> None:
        self.query_one("#btn-run", Button).disabled = not enabled
        self.query_one("#btn-dry-run", Button).disabled = not enabled

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.pressed:
            label = str(event.pressed.label)
            self._default_action = label[0].lower()  # "d", "l", or "s"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        handlers = {
            "btn-scan": self.action_scan,
            "btn-dry-run": self.action_dry_run,
            "btn-run": self.action_run_cleanup,
            "btn-signout": self._handle_signout,
        }
        handler = handlers.get(event.button.id)
        if handler:
            handler()

    def _handle_signout(self) -> None:
        from gmail.auth import signout
        signout()
        self.notify("Signed out. Local token deleted.", severity="warning")

    def action_scan(self) -> None:
        self.app.push_screen(ScanningScreen())
        self._do_scan()

    def action_dry_run(self) -> None:
        if not self._scan_data:
            self.notify("Please scan first.", severity="warning")
            return
        checked, action = self._collect_ui_state()
        self._do_run(dry_run=True, checked_cats=checked, default_action=action)

    def action_run_cleanup(self) -> None:
        if not self._scan_data:
            self.notify("Please scan first.", severity="warning")
            return
        checked, action = self._collect_ui_state()
        self._do_run(dry_run=False, checked_cats=checked, default_action=action)

    def _collect_ui_state(self) -> tuple[set[str], str]:
        """Collect checkbox state and radio selection from the UI (main thread only)."""
        checked = {cb.name for cb in self.query(Checkbox) if cb.value and cb.name}
        return checked, self._default_action

    # ------------------------------------------------------------------
    # Background workers
    # ------------------------------------------------------------------

    @work(thread=True)
    def _do_scan(self) -> None:
        from gmail.actions import _scan
        try:
            result = _scan(self._service, self._config)
            self.app.call_from_thread(self._on_scan_done, result)
        except Exception as exc:
            self.app.call_from_thread(self._on_scan_error, str(exc))

    def _on_scan_done(self, result: dict) -> None:
        self._scan_data = result

        # Update auto-actions table
        table = self.query_one("#auto-table", DataTable)
        table.clear()
        table.add_row(
            "Priority (protected)",
            str(len(result["to_priority"])),
            "starred",
        )
        table.add_row(
            f"Old (>{result['delete_days']}d)",
            str(len(result["to_trash"])),
            "move to Trash",
        )
        table.add_row(
            "Duplicates",
            str(len(result["dup_ids"])),
            "Trash (keep 1)",
        )

        # Rebuild category checkboxes
        cat_list = self.query_one("#cat-list", ScrollableContainer)
        cat_list.remove_children()
        for category, msg_ids in result["category_groups"].items():
            cat_list.mount(
                Checkbox(f"{category}  ({len(msg_ids)} emails)", value=True, name=category)
            )

        self._set_run_buttons_enabled(True)

        # Pop the scanning screen
        if isinstance(self.app.screen, ScanningScreen):
            self.app.pop_screen()

        self.notify("Scan complete!", severity="information")

    def _on_scan_error(self, error: str) -> None:
        if isinstance(self.app.screen, ScanningScreen):
            self.app.pop_screen()
        self.notify(f"Scan failed: {error}", severity="error")

    @work(thread=True)
    def _do_run(self, dry_run: bool, checked_cats: set[str], default_action: str) -> None:
        from gmail.actions import _apply_labels
        from gmail.client import trash_message, modify_labels

        result = self._scan_data
        max_trash = self._config.get("automation", {}).get("max_trash_per_run", 100)

        to_trash = list(result["to_trash"]) + list(result["dup_ids"])
        to_label = []

        for category, msg_ids in result["category_groups"].items():
            if category not in checked_cats:
                continue
            if default_action == "d":
                to_trash.extend(msg_ids)
            elif default_action == "l":
                to_label.extend([(mid, category) for mid in msg_ids])

        if len(to_trash) > max_trash:
            to_trash = to_trash[:max_trash]

        trashed = labeled = starred = 0

        if not dry_run:
            for msg_id in to_trash:
                trash_message(self._service, msg_id)
                trashed += 1
            _apply_labels(self._service, to_label)
            labeled = len(to_label)
            for msg_id in result["to_priority"]:
                modify_labels(self._service, msg_id, add_labels=["STARRED"])
                starred += 1
        else:
            trashed = len(to_trash)
            labeled = len(to_label)
            starred = len(result["to_priority"])

        run_result = {
            "trashed": trashed,
            "labeled": labeled,
            "starred": starred,
            "dry_run": dry_run,
        }
        self.app.call_from_thread(self._on_run_done, run_result)

    def _on_run_done(self, results: dict) -> None:
        self.app.push_screen(ResultsScreen(results))


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class GmailGraveyardApp(App):
    """Gmail Graveyard TUI Application."""

    TITLE = "Gmail Graveyard"
    SUB_TITLE = "Clean your inbox without touching your password"

    def __init__(self, service, config: dict) -> None:
        super().__init__()
        self._service = service
        self._config = config

    def on_mount(self) -> None:
        self.push_screen(MainScreen(self._service, self._config))
