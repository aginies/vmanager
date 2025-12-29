"""
Defines custom Message classes for the application.
"""
from textual.message import Message


class VMNameClicked(Message):
    """Posted when a VM's name is clicked."""

    def __init__(self, vm_name: str, vm_uuid: str) -> None:
        super().__init__()
        self.vm_name = vm_name
        self.vm_uuid = vm_uuid


class VMSelectionChanged(Message):
    """Posted when a VM's selection state changes."""

    def __init__(self, vm_uuid: str, is_selected: bool) -> None:
        super().__init__()
        self.vm_uuid = vm_uuid
        self.is_selected = is_selected


class VmActionRequest(Message):
    """Posted when a user requests an action on a VM (start, stop, etc.)."""

    def __init__(self, vm_uuid: str, action: str, delete_storage: bool = False) -> None:
        super().__init__()
        self.vm_uuid = vm_uuid
        self.action = action
        self.delete_storage = delete_storage
