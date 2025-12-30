"""
Shared constants for the application.
"""

class AppInfo:
    """Define app data"""
    name = "virtui-manager"
    version = "0.5.0"

class VmAction:
    """Defines constants for VM action types."""
    START = "start"
    STOP = "stop"
    FORCE_OFF = "force_off"
    PAUSE = "pause"
    RESUME = "resume"
    DELETE = "delete"

class VmStatus:
    """Defines constants for VM status filters."""
    DEFAULT = "default"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    SELECTED = "selected"

class ButtonLabels:
    """Constants for button labels"""
    START = "Start"
    SHUTDOWN = "Shutdown"
    FORCE_OFF = "Force Off"
    PAUSE = "Pause"
    RESUME = "Resume"
    CONFIGURE = "Configure"
    WEB_CONSOLE = "Web Console"
    CONNECT = "Connect"
    SNAPSHOT = "Snapshot"
    RESTORE_SNAPSHOT = "Restore Snapshot"
    DELETE_SNAPSHOT = "Del Snapshot"
    DELETE = "Delete"
    CLONE = "Clone"
    MIGRATION = "! Migration !"
    VIEW_XML = "View XML"
    RENAME = "Rename"

class ButtonIds:
    """Constants for button IDs"""
    START = "start"
    SHUTDOWN = "shutdown"
    STOP = "stop"
    PAUSE = "pause"
    RESUME = "resume"
    CONFIGURE_BUTTON = "configure-button"
    WEB_CONSOLE = "web_console"
    CONNECT = "connect"
    SNAPSHOT_TAKE = "snapshot_take"
    SNAPSHOT_RESTORE = "snapshot_restore"
    SNAPSHOT_DELETE = "snapshot_delete"
    DELETE = "delete"
    CLONE = "clone"
    MIGRATION = "migration"
    XML = "xml"
    RENAME_BUTTON = "rename-button"

class TabTitles:
    """Constants for tab titles"""
    MANAGE = "Manage"
    SPECIAL = "Special"
    SNAPSHOT = "Snapshot"
    SNAPSHOTS = "Snapshots"

class StatusText:
    """Constants for status text"""
    STOPPED = "Stopped"
    RUNNING = "Running"
    PAUSED = "Paused"

class SparklineLabels:
    """Constants for sparkline labels"""
    DISK_RW = "Disk R/W {read:.2f}/{write:.2f} MB/s"
    NET_RX_TX = "Net Rx/Tx {rx:.2f}/{tx:.2f} MB/s"
    VCPU = "{cpu} VCPU"
    MEMORY_GB = "{mem} Gb"

class ErrorMessages:
    """Constants for error messages"""
    VIRT_VIEWER_NOT_FOUND = "virt-viewer command not found. Please ensure it is installed."
    CANNOT_OPEN_DISPLAY = "Could not open display. Ensure you are in a graphical session."
    HARD_STOP_WARNING = "This is a hard stop, like unplugging the power cord."
    MIGRATION_LOCALHOST_NOT_SUPPORTED = "Migration from localhost (qemu:///system) is not supported.\nA full remote URI (e.g., qemu+ssh://user@host/system) is required."
    NO_DESTINATION_SERVERS = "No destination servers available."
    DIFFERENT_SOURCE_HOSTS = "Cannot migrate VMs from different source hosts at the same time."
    MIXED_VM_STATES = "Cannot migrate running/paused and stopped VMs at the same time."

class DialogMessages:
    """Constants for dialog messages"""
    DELETE_VM_CONFIRMATION = "Are you sure you want to delete '{name}'?"
    DELETE_SNAPSHOT_CONFIRMATION = "Are you sure you want to delete snapshot '{name}'?"
    DELETE_SNAPSHOTS_AND_RENAME = "VM has {count} snapshot(s). To rename, they must be deleted.\nDelete snapshots and continue?"
    MIGRATION_EXPERIMENTAL = "Experimental Features! not yet fully tested!"