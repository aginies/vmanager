"""
Modals for handling VM migration.
"""
from typing import List, Dict
import libvirt

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal, Grid, ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import Button, Static, Select, Checkbox, Label, ProgressBar
from textual import on, work

from vm_actions import check_server_migration_compatibility, check_vm_migration_compatibility
from utils import extract_server_name_from_uri
from pprint import pprint # pprint(vars(object))

class MigrationModal(ModalScreen):
    """A modal to handle VM migration."""

    BINDINGS = [("escape", "app.pop_screen", "Cancel")]

    def __init__(self, vms: List[libvirt.virDomain], is_live: bool, connections: Dict[str, libvirt.virConnect], **kwargs):
        super().__init__(**kwargs)
        self.vms_to_migrate = vms
        self.is_live = is_live
        self.connections = connections
        self.source_conn = vms[0].connect()
        self.dest_conn = None
        self.compatibility_checked = False
        self.checks_passed = False
        self.log_content = ""
        self.can_migrate_vms = []
        self.cannot_migrate_vms = []

    def compose(self) -> ComposeResult:
        vm_names = ", ".join([vm.name() for vm in self.vms_to_migrate])
        source_uri = self.source_conn.getURI()
        
        try:
            source_hostname = self.source_conn.getHostname()
        except libvirt.libvirtError:
            source_hostname = None # Can't get hostname, will have to rely on URI

        dest_servers = []
        for uri, conn in self.connections.items():
            if uri == source_uri:
                continue

            if source_hostname:
                try:
                    dest_hostname = conn.getHostname()
                    if dest_hostname == source_hostname:
                        continue # It's the same host, skip it
                except libvirt.libvirtError:
                    # Could not get hostname for destination, can't compare.
                    # We will let it be in the list and let libvirt fail if it's the same.
                    # This preserves existing behavior for problematic connections.
                    pass

            dest_servers.append((extract_server_name_from_uri(uri), uri))

        migration_type = "Live" if self.is_live else "Offline"

        default_dest_uri = None
        if dest_servers:
            default_dest_uri = dest_servers[0][1]
            self.dest_conn = self.connections[default_dest_uri]

        with Vertical(id="migration-dialog",):
            with ScrollableContainer(id="migration-content-wrapper"):
                yield Label(f"[{migration_type}] Migrate VMs: [b]{vm_names}[/b]")
                yield Static("Select destination server:")
                yield Select(dest_servers, id="dest-server-select", prompt="Destination...", value=default_dest_uri, allow_blank=False)
                
                yield Static("Migration Options:")
                with Horizontal(classes="checkbox-container"):
                    yield Checkbox("Copy storage all", id="copy-storage-all", tooltip="Copy all disk files during migration", value=False)
                    yield Checkbox("Unsafe migration", id="unsafe", tooltip="Perform unsafe migration (may lose data)", disabled=not self.is_live)
                    yield Checkbox("Persistent migration", id="persistent", tooltip="Keep VM persistent on destination", value=True)
                with Horizontal(classes="checkbox-container"):
                    yield Checkbox("Compress data", id="compress", tooltip="Compress data during migration", disabled=not self.is_live)
                    yield Checkbox("Tunnelled migration", id="tunnelled", tooltip="Tunnel migration data through libvirt daemon", disabled=not self.is_live)
                yield Static("Compatibility Check Results / Migration Log:")
                yield ProgressBar(total=100, show_eta=False, id="migration-progress")
                yield Static(id="results-log")
                yield Grid(
                    Vertical(
                        Static("[b]VMs Ready for Migration:[/b]", classes="summary-title"),
                        Static(id="can-migrate-list"),
                    ),
                    Vertical(
                        Static("[b]VMs Not Ready for Migration:[/b]", classes="summary-title"),
                        Static(id="cannot-migrate-list"),
                    ),
                    id="migration-summary-grid"
                )
            
            with Horizontal(classes="modal-buttons"):
                yield Button("Check Compatibility", variant="primary", id="check", classes="Buttonpage")
                yield Button("Start Migration", variant="success", id="start", disabled=True, classes="Buttonpage")
                yield Button("Close", variant="default", id="close", disabled=False, classes="close-button")

    def _lock_controls(self, lock: bool):
        self.query_one("#check").disabled = lock
        self.query_one("#start").disabled = True
        self.query_one("#dest-server-select").disabled = lock
        self.query_one("#close").disabled = lock

    def on_mount(self) -> None:
        """Called when the modal is mounted."""
        log = self.query_one("#results-log", Static)
        log.wrap = True
        self.query_one("#migration-progress").styles.display = "none"


    @on(Select.Changed, "#dest-server-select")
    def on_select_changed(self, event: Select.Changed):
        dest_uri = event.value
        if dest_uri:
            self.dest_conn = self.connections[dest_uri]
        else:
            self.dest_conn = None

        self.query_one("#start", Button).disabled = True
        self.compatibility_checked = False
        self.checks_passed = False
        self._clear_log()

    def _clear_log(self):
        self.log_content = ""
        self.query_one("#results-log", Static).update("")
        self.can_migrate_vms = []
        self.cannot_migrate_vms = []
        self.query_one("#can-migrate-list").update("")
        self.query_one("#cannot-migrate-list").update("")

    def _write_log_line(self, line: str):
        self.log_content += line + "\n"
        self.query_one("#results-log", Static).update(self.log_content)

    @work(exclusive=True, thread=True)
    async def run_compatibility_checks(self):
        self.app.call_from_thread(self._lock_controls, True)

        def write_log(line):
            self.app.call_from_thread(self._write_log_line, line)

        all_checks_ok = True
        for i, vm in enumerate(self.vms_to_migrate):
            try:
                write_log(f"\n[on blue][bold]--- CHECKING {vm.name()} ---[/][/]")

                # --- Server Compatibility ---
                write_log(f"[bold]-- Server Compatibility --[/]")
                server_issues = check_server_migration_compatibility(self.source_conn, self.dest_conn, vm.name(), self.is_live)

                server_errors = [issue for issue in server_issues if issue['severity'] == 'ERROR']
                for issue in server_errors:
                    write_log(f"[on red bold]ERROR[/]: [red]{issue['message']}[/]")

                server_warnings = [issue for issue in server_issues if issue['severity'] == 'WARNING']
                for issue in server_warnings:
                    write_log(f"[on yellow bold][black]WARNING[/][/]: [yellow]{issue['message']}[/]")

                server_infos = [issue for issue in server_issues if issue['severity'] == 'INFO']
                # Filter out redundant server-wide informational messages for subsequent VMs
                if i > 0:
                    server_infos = [
                        issue for issue in server_infos
                        if "manually verify" not in issue['message'] and
                           "Firewalls" not in issue['message'] and
                           "user and" not in issue['message']
                    ]
                for issue in server_infos:
                    write_log(f"[bold]INFO[/]: [green]{issue['message']}[/]")

                # --- VM Compatibility ---
                write_log(f"[bold]-- VM Compatibility --[/]")
                vm_issues = check_vm_migration_compatibility(vm, self.dest_conn, self.is_live)

                vm_errors = [issue for issue in vm_issues if issue['severity'] == 'ERROR']
                for issue in vm_errors:
                    write_log(f"[on red bold]ERROR[/]: [red]{issue['message']}[/]")

                vm_warnings = [issue for issue in vm_issues if issue['severity'] == 'WARNING']
                for issue in vm_warnings:
                    write_log(f"[on yellow bold][black]WARNING[/][/]: [yellow]{issue['message']}[/]")

                vm_infos = [issue for issue in vm_issues if issue['severity'] == 'INFO']
                for issue in vm_infos:
                    write_log(f"[bold]INFO[/]: [green]{issue['message']}[/]")

                errors = server_errors + vm_errors
                if errors:
                    all_checks_ok = False
                    self.cannot_migrate_vms.append(vm.name())
                    write_log(f"\n[red]✗ Compatibility checks failed for {vm.name()}[/]")
                else:
                    self.can_migrate_vms.append(vm.name())
                    write_log(f"\n[green]✓ Compatibility checks passed for {vm.name()}[/] (with warnings if any shown above).")
            except Exception as e:
                write_log(f"\n[on red bold]FATAL ERROR[/]: An unexpected error occurred while checking {vm.name()}: {e}")
                all_checks_ok = False
                self.cannot_migrate_vms.append(vm.name())
                continue # Continue to the next VM

        self.checks_passed = all_checks_ok
        self.compatibility_checked = True

        def update_ui_after_check():
            self._lock_controls(False)
            self.query_one("#start").disabled = not self.checks_passed
            can_migrate_text = "\n".join(f"- {name}" for name in self.can_migrate_vms)
            cannot_migrate_text = "\n".join(f"- {name}" for name in self.cannot_migrate_vms)
            self.query_one("#can-migrate-list").update(can_migrate_text)
            self.query_one("#cannot-migrate-list").update(cannot_migrate_text)
        self.app.call_from_thread(update_ui_after_check)

    @work(exclusive=True, thread=True)
    async def run_migration(self):
        def write_log(line):
            self.app.call_from_thread(self._write_log_line, line)

        self.app.call_from_thread(self._lock_controls, True)

        progress_bar = self.query_one("#migration-progress", ProgressBar)
        self.app.call_from_thread(lambda: setattr(progress_bar, "total", len(self.vms_to_migrate)))
        self.app.call_from_thread(lambda: setattr(progress_bar, "progress", 0))
        self.app.call_from_thread(lambda: setattr(progress_bar.styles, "display", "block"))
        # Hide the migration summary grid when migration starts
        self.query_one("#migration-summary-grid").styles.display = "none"

        copy_storage_all = self.query_one("#copy-storage-all", Checkbox).value
        unsafe = self.query_one("#unsafe", Checkbox).value
        persistent = self.query_one("#persistent", Checkbox).value
        compress = self.query_one("#compress", Checkbox).value
        tunnelled = self.query_one("#tunnelled", Checkbox).value

        for vm in self.vms_to_migrate:
            write_log(f"\n[bold]--- Migrating {vm.name()} ---[/]")

            try:
                if self.is_live:
                    flags = libvirt.VIR_MIGRATE_LIVE | libvirt.VIR_MIGRATE_PEER2PEER

                    if copy_storage_all:
                        flags |= libvirt.VIR_MIGRATE_NON_SHARED_DISK
                    if unsafe:
                        flags |= libvirt.VIR_MIGRATE_UNSAFE
                    if persistent:
                        flags |= libvirt.VIR_MIGRATE_PERSIST_DEST
                    if compress:
                        flags |= libvirt.VIR_MIGRATE_COMPRESSED
                    if tunnelled:
                        flags |= libvirt.VIR_MIGRATE_TUNNELLED

                    write_log(f"[dim]Using live migration flags: {flags}[/dim]")
                    vm.migrate(self.dest_conn, flags, None, None, 0)
                else:  # Offline migration
                    flags = libvirt.VIR_MIGRATE_OFFLINE | libvirt.VIR_MIGRATE_PEER2PEER
                    if persistent:
                        flags |= libvirt.VIR_MIGRATE_PERSIST_DEST
                    # VIR_MIGRATE_TUNNELLED is not applied for offline migration as it does not make sense.

                    if copy_storage_all:
                        flags |= libvirt.VIR_MIGRATE_NON_SHARED_DISK
                        params = {libvirt.VIR_MIGRATE_PARAM_MIGRATE_DISKS: "*"}
                        write_log("[dim]Using migrateToURI3 for offline migration with storage copy.[/dim]")
                        vm.migrateToURI3(self.dest_conn, params, flags)
                    else:
                        write_log("[dim]Using migrate for offline migration without storage copy.[/dim]")
                        vm.migrate(self.dest_conn, flags, None, None, 0)


                write_log(f"[green]✓ Successfully migrated {vm.name()}.[/]")

                if persistent:
                    try:
                        vm.undefine()
                        write_log(f"[green]✓ Successfully undefined {vm.name()} from the source host.[/]")
                    except libvirt.libvirtError as e:
                        write_log(f"[yellow]WARNING: Failed to undefine {vm.name()} from the source host: {e}[/]")

            except libvirt.libvirtError as e:
                write_log(f"[red]ERROR: Failed to migrate {vm.name()}: {e}[/]")
            
            self.app.call_from_thread(progress_bar.advance, 1)

        def final_ui_state():
            """Disables all controls except the Close button after migration is finished."""
            self.query_one("#check").disabled = True
            self.query_one("#start").disabled = True
            self.query_one("#dest-server-select").disabled = True
            self.query_one("#copy-storage-all").disabled = True
            self.query_one("#unsafe").disabled = True
            self.query_one("#persistent").disabled = True
            self.query_one("#compress").disabled = True
            self.query_one("#tunnelled").disabled = True
            self.query_one("#close").disabled = False

        write_log("\n[bold]--- Migration process finished ---[/]")
        self.app.call_from_thread(lambda: setattr(progress_bar.styles, "display", "none"))
        self.app.call_from_thread(self.app.refresh_vm_list)
        self.app.call_from_thread(final_ui_state)

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "check":
            if not self.dest_conn:
                self.app.show_error_message("Please select a destination server.")
                return
            self._clear_log()
            self.run_compatibility_checks()

        elif event.button.id == "start":
            if not self.compatibility_checked:
                self.app.show_error_message("Please run compatibility check first.")
                return
            if not self.checks_passed:
                self.app.show_error_message("Cannot start migration due to compatibility errors.")
                return

            self._clear_log()
            self.run_migration()

        elif event.button.id == "close":
            self.dismiss()
