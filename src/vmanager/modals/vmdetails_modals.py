"""
Main interface
"""
import os
import logging
from collections import namedtuple
import xml.etree.ElementTree as ET

from textual.app import ComposeResult
from textual.widgets import (
        Select, Button, Input, Label,
        DataTable, Checkbox, RadioButton,
        RadioSet, TabbedContent, TabPane,
        ListView, ListItem
        )
from textual.containers import ScrollableContainer, Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual import on
import libvirt
from vm_queries import (
    get_vm_networks_info,
    get_vm_disks_info, get_vm_devices_info,
    get_supported_machine_types, get_vm_graphics_info,
    get_all_vm_nvram_usage, get_all_vm_disk_usage, get_vm_sound_model,
    get_vm_network_ip, get_vm_rng_info, get_vm_tpm_info,
    get_attached_usb_devices, get_serial_devices, get_vm_input_info,
    get_vm_watchdog_info, get_attached_pci_devices
    )
from vm_actions import (
        add_disk, remove_disk, set_vcpu, set_memory, set_machine_type, enable_disk,
        disable_disk, change_vm_network, set_shared_memory, remove_virtiofs,
        add_virtiofs, set_vm_video_model, set_cpu_model, set_uefi_file,
        set_vm_graphics, set_disk_properties, set_vm_sound_model,
        add_network_interface, remove_network_interface, set_boot_info, set_vm_rng, set_vm_tpm,
        check_for_other_spice_devices, remove_spice_devices, attach_usb_device,
        detach_usb_device, add_serial_console, remove_serial_console,
        add_vm_input, remove_vm_input, set_vm_watchdog, remove_vm_watchdog,
        add_usb_device, remove_usb_device, add_scsi_controller, remove_scsi_controller,
        migrate_vm_machine_type
)
from config import get_log_path
from network_manager import (
    list_networks,
)
from firmware_manager import (
    get_uefi_files, get_host_sev_capabilities
)
import storage_manager
from libvirt_utils import (
        get_cpu_models, get_domain_capabilities_xml, get_video_domain_capabilities,
        get_host_usb_devices, get_host_pci_devices
        )
from modals.utils_modals import ConfirmationDialog
from modals.cpu_mem_pc_modals import (
        EditCpuModal, EditMemoryModal, SelectMachineTypeModal
        )
from modals.virtiofs_modals import AddEditVirtIOFSModal
from modals.disk_pool_modals import (
          SelectPoolModal, AddDiskModal,
          SelectDiskModal, EditDiskModal
          )
from modals.network_modals import AddEditNetworkInterfaceModal
from modals.input_modals import AddInputDeviceModal

# Configure logging
logging.basicConfig(
    filename=get_log_path(),
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

BootDevice = namedtuple("BootDevice", ["type", "id", "description", "boot_order_idx"])

class VMDetailModal(ModalScreen):
    """Modal screen to show detailed VM information."""

    BINDINGS = [("escape", "close_modal", "Close")]

    boot_order: reactive(list)
    all_bootable_devices: reactive(list)
    graphics_info: reactive(dict) # New reactive variable

    def __init__(self, vm_name: str, vm_info: dict, domain: libvirt.virDomain, conn: libvirt.virConnect, invalidate_cache_callback=None) -> None:
        super().__init__()
        self.vm_name = vm_name
        self.vm_info = vm_info
        self.domain = domain
        self.conn = conn
        self.invalidate_cache_callback = invalidate_cache_callback
        self.available_networks = []
        self.selected_virtiofs_target = None
        self.selected_virtiofs_info = None # Store full info for editing
        self.selected_network_interface = None
        self.serial_devices = []
        self.selected_serial_port = None
        self.input_devices = []
        self.selected_input_device = None
        self.selected_controller = None
        self.boot_order = self.vm_info.get('boot', {}).get('order', [])
        self.all_bootable_devices = [] # Initialize the new reactive list
        self.sev_caps = {'sev': False, 'sev-es': False}
        self.uefi_path_map = {}
        self.xml_desc = self.domain.XMLDesc(0)
        try:
            root = ET.fromstring(self.xml_desc)
        except ET.ParseError:
            root = None

        self.graphics_info = get_vm_graphics_info(root)
        self.vm_info['sound_model'] = get_vm_sound_model(root)
        self.rng_info = get_vm_rng_info(root)
        # Initialize TPM info
        self.tpm_info = get_vm_tpm_info(root)
        self.watchdog_info = get_vm_watchdog_info(root)

    def _invalidate_cache(self):
        """Invalidates the VM cache if a callback is provided."""
        if self.invalidate_cache_callback:
            self.invalidate_cache_callback(self.vm_info['uuid'])

    @property
    def is_vm_stopped(self) -> bool:
        """Check if the VM is currently stopped.

        Returns:
            bool: True if VM status is 'Stopped', False otherwise
        """
        return self.vm_info.get("status") == "Stopped"

    @property
    def is_vm_active(self) -> bool:
        """Check if the VM domain is currently active/running.

        Returns:
            bool: True if VM is active, False otherwise
        """
        return self.domain.isActive()


    def on_mount(self) -> None:
        try:
            all_networks_info = list_networks(self.conn)
            self.available_networks = [net['name'] for net in all_networks_info]
        except (libvirt.libvirtError, Exception) as e:
            self.app.show_error_message(f"Could not load networks: {e}")
            self.available_networks = []
        self.query_one("#detail2-vm").add_class("hidden")

        # Populate Boot tab
        boot_menu_enabled = self.vm_info.get('boot', {}).get('menu_enabled', False)
        self.query_one("#boot-menu-enable", Checkbox).value = boot_menu_enabled
        self._populate_boot_lists()
        self.query_one("#boot-up", Button).disabled = True
        self.query_one("#boot-down", Button).disabled = True
        self.query_one("#boot-add", Button).disabled = True
        self.query_one("#boot-remove", Button).disabled = True

        # SEV capabilities
        firmware_type = self.vm_info['firmware'].get('type', 'BIOS')

        if firmware_type == 'UEFI':
            try:
                self.sev_caps = get_host_sev_capabilities(self.conn)
                sev_checkbox = self.query_one("#sev-checkbox", Checkbox)
                sev_es_checkbox = self.query_one("#sev-es-checkbox", Checkbox)
                sev_checkbox.display = self.sev_caps['sev']
                sev_es_checkbox.display = self.sev_caps['sev-es']
                sev_checkbox.disabled = not self.vm_info.get("status") == "Stopped"
                sev_es_checkbox.disabled = not self.vm_info.get("status") == "Stopped"
            except Exception as e:
                self.app.show_error_message(f"Could not get SEV capabilities: {e}")
                try:
                    self.query_one("#sev-checkbox", Checkbox).display = False
                    self.query_one("#sev-es-checkbox", Checkbox).display = False
                except Exception:
                    pass

            self._update_uefi_options()

        # Initialize Graphics tab values
        self._update_graphics_ui()
        self._update_tpm_ui()
        try:
            root = ET.fromstring(self.xml_desc)
        except ET.ParseError:
            root = None
        self.vm_info['disks'] = get_vm_disks_info(self.conn, root)
        self._populate_disks_table()
        self._populate_networks_table()
        self._populate_usb_lists()
        self._populate_pci_lists()
        self._populate_serial_table()
        self._populate_input_table()
        self._populate_controller_table()

    def _populate_disks_table(self):
        disks_table = self.query_one("#disks-table", DataTable)
        disks_table.clear()
        if not disks_table.columns:
            disks_table.add_column("Path", key="path")
            disks_table.add_column("Bus Type", key="bus")
            disks_table.add_column("Cache Mode", key="cache_mode")
            disks_table.add_column("Discard Mode", key="discard_mode")
            disks_table.add_column("Status", key="status")

        disks_info = self.vm_info.get('disks', [])

        for disk in disks_info:
            path = disk.get('path', 'N/A')
            status = disk.get('status', 'unknown')
            bus = disk.get('bus', 'N/A')
            cache_mode = disk.get('cache_mode', 'none')
            discard_mode = disk.get('discard_mode', 'ignore')

            if status == 'disabled':
                disks_table.add_row(
                    path,
                    bus,
                    "",
                    "",
                    "(disabled)",
                    key=path
                )
            else:
                disks_table.add_row(
                    path,
                    bus,
                    cache_mode,
                    discard_mode,
                    "enabled",
                    key=path
                )

        has_enabled_disks = any(d['status'] == 'enabled' for d in disks_info)
        has_disabled_disks = any(d['status'] == 'disabled' for d in disks_info)

        self.query_one("#detail_remove_disk", Button).display = has_enabled_disks
        self.query_one("#detail_disable_disk", Button).display = has_enabled_disks
        self.query_one("#detail_enable_disk", Button).display = has_disabled_disks

    def _populate_networks_table(self):
        networks_table = self.query_one("#networks-table", DataTable)
        networks_table.clear()
        self.query_one("#edit-network-interface-button", Button).disabled = True
        self.query_one("#remove-network-interface-button", Button).disabled = True

        networks_list = self.vm_info.get("networks", [])
        detail_network_list = self.vm_info.get("detail_network", [])
        dns_gateway_list = self.vm_info.get("network_dns_gateway", [])

        mac_to_ip = {}
        if detail_network_list:
            for detail in detail_network_list:
                ips = detail.get('ipv4', []) + detail.get('ipv6', [])
                if ips:
                    mac_to_ip[detail['mac']] = ", ".join(ips)

        network_to_dns_gateway = {net['network_name']: net for net in dns_gateway_list}

        if networks_list:
            for net in networks_list:
                ip_address = mac_to_ip.get(net['mac'], "")

                net_name = net.get('network')
                dns_gateway_info = network_to_dns_gateway.get(net_name, {})
                gateway = dns_gateway_info.get('gateway', '')
                dns = ", ".join(dns_gateway_info.get('dns_servers', []))

                networks_table.add_row(
                    net['mac'],
                    net_name,
                    net.get('model', 'N/A'),
                    ip_address,
                    gateway,
                    dns,
                    key=net['mac']
                )
        else:
            networks_table.add_row("No network interfaces found.", "", "", "", "", "", key="none")

    def _populate_boot_lists(self):
        """Populates the boot order and available devices lists."""
        boot_order_list = self.query_one("#boot-order-list", ListView)
        available_devices_list = self.query_one("#available-devices-list", ListView)

        boot_order_list.clear()
        available_devices_list.clear()

        self.all_bootable_devices = self._get_bootable_devices()
        boot_order_ids = self.boot_order

        # Create a dictionary for quick lookups
        device_map = {dev.id: dev for dev in self.all_bootable_devices}

        # Populate boot order list, preserving the order
        for device_id in boot_order_ids:
            if device_id in device_map:
                device = device_map[device_id]
                item = ListItem(Label(device.description))
                item.tooltip = device.description
                item.data = device
                boot_order_list.append(item)

        # Populate available devices list
        for device in self.all_bootable_devices:
            if device.id not in boot_order_ids:
                item = ListItem(Label(device.description))
                item.tooltip = device.description
                item.data = device
                available_devices_list.append(item)

    @on(Button.Pressed, "#boot-add")
    def on_boot_add(self, event: Button.Pressed) -> None:
        available_list = self.query_one("#available-devices-list", ListView)
        boot_list = self.query_one("#boot-order-list", ListView)

        if available_list.highlighted_child:
            # Get the highlighted item's data
            item_to_move = available_list.highlighted_child

            # Create a new ListItem with the same data
            new_item = ListItem(Label(item_to_move.children[0].renderable))
            new_item.data = item_to_move.data

            # Remove the original item
            item_to_move.remove()

            # Add the new item to the boot list
            boot_list.append(new_item)


    @on(Button.Pressed, "#boot-remove")
    def on_boot_remove(self, event: Button.Pressed) -> None:
        available_list = self.query_one("#available-devices-list", ListView)
        boot_list = self.query_one("#boot-order-list", ListView)

        if boot_list.highlighted_child:
            item_to_move = boot_list.highlighted_child

            # Create a new ListItem with the same data
            new_item = ListItem(Label(item_to_move.children[0].renderable))
            new_item.data = item_to_move.data

            # Remove the original item
            item_to_move.remove()

            # Add the new item to the available list
            available_list.append(new_item)

    @on(Button.Pressed, "#boot-up")
    def on_boot_up(self, event: Button.Pressed) -> None:
        boot_list = self.query_one("#boot-order-list", ListView)
        if boot_list.highlighted_child:
            idx = boot_list.index
            if idx > 0:
                # Get the list of data from the items
                items_data = [item.data for item in boot_list.children]

                # Move the item
                items_data.insert(idx - 1, items_data.pop(idx))

                # Get the highlighted item's data to restore highlight
                highlighted_id = boot_list.highlighted_child.data.id

                # Clear the list
                boot_list.clear()

                # Repopulate the list
                new_idx = -1
                for i, data in enumerate(items_data):
                    new_item = ListItem(Label(data.description))
                    new_item.data = data
                    boot_list.append(new_item)
                    if data.id == highlighted_id:
                        new_idx = i

                if new_idx != -1:
                    boot_list.index = new_idx

    @on(Button.Pressed, "#boot-down")
    def on_boot_down(self, event: Button.Pressed) -> None:
        boot_list = self.query_one("#boot-order-list", ListView)
        if boot_list.highlighted_child:
            idx = boot_list.index
            if idx < len(boot_list.children) - 1:
                # Get the list of data from the items
                items_data = [item.data for item in boot_list.children]

                # Move the item
                items_data.insert(idx + 1, items_data.pop(idx))

                # Get the highlighted item's data to restore highlight
                highlighted_id = boot_list.highlighted_child.data.id

                # Clear the list
                boot_list.clear()

                # Repopulate the list
                new_idx = -1
                for i, data in enumerate(items_data):
                    new_item = ListItem(Label(data.description))
                    new_item.data = data
                    boot_list.append(new_item)
                    if data.id == highlighted_id:
                        new_idx = i

                if new_idx != -1:
                    boot_list.index = new_idx

    @on(Button.Pressed, "#save-boot-order")
    def on_save_boot_order(self, event: Button.Pressed) -> None:
        boot_list = self.query_one("#boot-order-list", ListView)
        new_boot_order = [item.data.id for item in boot_list.children]

        menu_enabled = self.query_one("#boot-menu-enable", Checkbox).value

        try:
            set_boot_info(self.domain, menu_enabled, new_boot_order)
            self._invalidate_cache()
            self.app.show_success_message("Boot order saved successfully.")
            self.boot_order = new_boot_order
        except libvirt.libvirtError as e:
            self.app.show_error_message(f"Error saving boot order: {e}")


    def _get_bootable_devices(self) -> list[BootDevice]:
        """Gathers all disks and network interfaces as bootable devices."""
        devices = []
        # Add disks
        for disk in self.vm_info.get("disks", []):
            path = disk.get('path')
            if path:
                boot_order_idx = None
                try:
                    boot_order_idx = self.boot_order.index(path) + 1
                except ValueError:
                    pass # Not in boot order

                devices.append(BootDevice(
                    type="Disk",
                    id=path,
                    description=os.path.basename(path),
                    boot_order_idx=boot_order_idx
                ))

        # Add network interfaces
        for net in self.vm_info.get("networks", []):
            mac = net.get('mac')
            if mac:
                boot_order_idx = None
                try:
                    boot_order_idx = self.boot_order.index(mac) + 1
                except ValueError:
                    pass # Not in boot order
                devices.append(BootDevice(
                    type="NIC",
                    id=mac,
                    description=f"MAC: {mac} ({net.get('network', 'N/A')})",
                    boot_order_idx=boot_order_idx
                ))
        return devices

    def _update_graphics_ui(self) -> None:
        """Updates the UI elements for the Graphics tab based on self.graphics_info."""

        try:
            graphics_type_select = self.query_one("#graphics-type-select", Select)
            graphics_type_select.value = self.graphics_info['type']
            graphics_type_select.disabled = not self.is_vm_stopped
        except Exception:
            pass

        try:
            listen_type_select = self.query_one("#graphics-listen-type-select", Select)
            listen_type_select.value = self.graphics_info['listen_type']
            listen_type_select.disabled = not self.is_vm_stopped
        except Exception:
            pass

        try:
            address_radioset = self.query_one("#graphics-address-radioset", RadioSet)
            if self.graphics_info['listen_type'] == 'none':
                 address_radioset.disabled = True
            elif self.graphics_info['address'] == '127.0.0.1':
                address_radioset.set_pressed("graphics-address-localhost")
                address_radioset.disabled = not self.is_vm_stopped
            elif self.graphics_info['address'] == '0.0.0.0':
                address_radioset.set_pressed("graphics-address-all")
                address_radioset.disabled = not self.is_vm_stopped
            else:
                address_radioset.set_pressed("graphics-address-default")
                address_radioset.disabled = not self.is_vm_stopped
            
        except Exception:
            pass

        try:
            port_input = self.query_one("#graphics-port-input", Input)
            port_input.value = str(self.graphics_info['port']) if self.graphics_info['port'] else ""
            port_input.disabled = not self.is_vm_stopped or self.graphics_info['autoport']
        except Exception:
            pass

        try:
            autoport_checkbox = self.query_one("#graphics-autoport-checkbox", Checkbox)
            autoport_checkbox.value = self.graphics_info['autoport']
            autoport_checkbox.disabled = not self.is_vm_stopped
        except Exception:
            pass

        try:
            password_enable_checkbox = self.query_one("#graphics-password-enable-checkbox", Checkbox)
            password_enable_checkbox.value = self.graphics_info['password_enabled']
            password_enable_checkbox.disabled = not self.is_vm_stopped
        except Exception:
            pass

        try:
            password_input = self.query_one("#graphics-password-input", Input)
            password_input.value = self.graphics_info['password'] if self.graphics_info['password_enabled'] else ""
            password_input.disabled = not self.is_vm_stopped or not self.graphics_info['password_enabled']
        except Exception:
            pass

        try:
            self.query_one("#graphics-apply-btn", Button).disabled = not self.is_vm_stopped
        except Exception:
            pass

    def _update_uefi_options(self) -> None:
        """Filters and updates the UEFI file selection list."""
        try:
            uefi_select = self.query_one("#uefi-file-select", Select)
        except Exception: # QueryError means the Firmware tab might not be UEFI type
            return

        all_uefi_files = get_uefi_files()
        uefi_files_to_show = all_uefi_files

        try:
            secure_boot_on = self.query_one("#secure-boot-checkbox", Checkbox).value
            if secure_boot_on:
                uefi_files_to_show = [f for f in uefi_files_to_show if 'secure-boot' in f.features]
        except Exception: # QueryError
            pass

        try:
            sev_checkbox = self.query_one("#sev-checkbox", Checkbox)
            if sev_checkbox.display and sev_checkbox.value:
                uefi_files_to_show = [f for f in uefi_files_to_show if 'amd-sev' in f.features]
        except Exception: # QueryError
            pass

        try:
            sev_es_checkbox = self.query_one("#sev-es-checkbox", Checkbox)
            if sev_es_checkbox.display and sev_es_checkbox.value:
                uefi_files_to_show = [f for f in uefi_files_to_show if 'sev-es' in f.features]
        except Exception: # QueryError
            pass

        current_path = self.vm_info['firmware'].get('path')
        current_basename = os.path.basename(current_path) if current_path else None

        self.uefi_path_map = {os.path.basename(f.executable): f.executable for f in uefi_files_to_show if f.executable}

        if current_basename and current_basename not in self.uefi_path_map:
            self.uefi_path_map[current_basename] = current_path

        uefi_options = [(basename, basename) for basename in sorted(self.uefi_path_map.keys())]
        uefi_select.set_options(uefi_options)

        if current_basename and any(opt[1] == current_basename for opt in uefi_options):
            uefi_select.value = current_basename

    @on(Select.Changed)
    def on_network_change(self, event: Select.Changed) -> None:
        if not event.control.id or not event.control.id.startswith("net-select-"):
            return

        mac_address_flat = event.control.id.replace("net-select-", "")
        mac_address = ":".join(mac_address_flat[i:i+2] for i in range(0, len(mac_address_flat), 2))
        new_network = event.value
        original_network = ""

        for i in self.vm_info["networks"]:
            if i["mac"] == mac_address:
                original_network = i["network"]
                break

        if original_network == new_network:
            return

        try:
            change_vm_network(self.domain, mac_address, new_network)
            self._invalidate_cache()
            self.app.show_success_message(f"Interface {mac_address} switched to {new_network}")
            for i in self.vm_info["networks"]:
                if i["mac"] == mac_address:
                    i["network"] = new_network
                    break
        except (libvirt.libvirtError, ValueError, Exception) as e:
            self.app.show_error_message(f"Error updating network: {e}")
            event.control.value = original_network

        self.available_networks = []

    @on(Select.Changed, "#cpu-model-select")
    def on_cpu_model_changed(self, event: Select.Changed) -> None:
        new_cpu_model = event.value
        original_cpu_model = self.vm_info.get('cpu_model', 'default')

        if new_cpu_model == original_cpu_model:
            return

        try:
            set_cpu_model(self.domain, new_cpu_model)
            self._invalidate_cache()
            self.app.show_success_message(f"CPU model set to {new_cpu_model}")
            self.vm_info['cpu_model'] = new_cpu_model
            self.query_one("#cpu-model-label").update(f"CPU Model: {new_cpu_model}")
        except (libvirt.libvirtError, ValueError, Exception) as e:
            self.app.show_error_message(f"Error setting CPU model: {e}")
            event.control.value = original_cpu_model

    @on(Select.Changed, "#uefi-file-select")
    def on_uefi_file_changed(self, event: Select.Changed) -> None:
        new_uefi_basename = event.value
        new_uefi_path = self.uefi_path_map.get(new_uefi_basename)
        original_uefi_path = self.vm_info['firmware'].get('path')
        current_secure_boot = self.query_one("#secure-boot-checkbox", Checkbox).value

        if new_uefi_path == original_uefi_path:
            return

        try:
            set_uefi_file(self.domain, new_uefi_path, current_secure_boot)
            self._invalidate_cache()
            if new_uefi_path:
                self.app.show_success_message(f"UEFI file set to {os.path.basename(new_uefi_path)}")
                self.query_one("#firmware-path-label").update(f"File: {os.path.basename(new_uefi_path)}")
            else:
                self.app.show_success_message("Firmware set to BIOS.")
                self.query_one("#firmware-path-label").update("File: ")
            self.vm_info['firmware']['path'] = new_uefi_path
        except (libvirt.libvirtError, ValueError, Exception) as e:
            self.app.show_error_message(f"Error setting UEFI file: {e}")
            original_basename = os.path.basename(original_uefi_path) if original_uefi_path else None
            if original_basename and original_basename in self.uefi_path_map:
                event.control.value = original_basename
            else:
                event.control.clear()

    @on(Select.Changed, "#video-model-select")
    def on_video_model_changed(self, event: Select.Changed) -> None:
        new_model = event.value
        current_model = self.vm_info.get('video_model') or "default"

        if new_model == current_model:
            return

        try:
            set_vm_video_model(self.domain, new_model if new_model != "default" else None)
            self._invalidate_cache()
            self.app.show_success_message(f"Video model set to {new_model}")
            self.query_one("#video-model-label").update(f"Video Model: {new_model}")
            self.vm_info['video_model'] = new_model if new_model != "default" else None
        except (libvirt.libvirtError, Exception) as e:
            self.app.show_error_message(f"Error setting video model: {e}")
            # Revert selection
            event.control.value = current_model

    @on(Select.Changed, "#sound-model-select")
    def on_sound_model_changed(self, event: Select.Changed) -> None:
        new_model = event.value
        current_model = self.vm_info.get('sound_model') or "none"

        if new_model == current_model:
            return

        try:
            set_vm_sound_model(self.domain, new_model if new_model != "none" else None)
            self._invalidate_cache()
            self.app.show_success_message(f"Sound model set to {new_model}")
            self.query_one("#sound-model-label").update(f"Sound Model: {new_model}")
            self.vm_info['sound_model'] = new_model if new_model != "none" else None
        except (libvirt.libvirtError, Exception) as e:
            self.app.show_error_message(f"Error setting sound model: {e}")
            # Revert selection
            event.control.value = current_model

    @on(Checkbox.Changed, "#secure-boot-checkbox")
    def on_secure_boot_checkbox_changed(self, event: Checkbox.Changed) -> None:
        self._update_uefi_options()

        current_uefi_path = self.vm_info['firmware'].get('path')
        if not current_uefi_path and event.value: # Trying to enable secure boot without a UEFI file
            self.app.show_error_message("Cannot enable secure boot without a UEFI file selected.")
            event.checkbox.value = not event.value # Revert checkbox
            self._update_uefi_options() # Revert options
            return

        try:
            set_uefi_file(self.domain, current_uefi_path, event.value)
            self._invalidate_cache()
            self.app.show_success_message(f"Secure Boot {'enabled' if event.value else 'disabled'}.")
            self.vm_info['firmware']['secure_boot'] = event.value
        except (libvirt.libvirtError, ValueError, Exception) as e:
            self.app.show_error_message(f"Error setting Secure Boot: {e}")
            event.checkbox.value = not event.value # Revert checkbox
            self._update_uefi_options() # Revert options

    @on(Checkbox.Changed, "#sev-checkbox, #sev-es-checkbox")
    def on_sev_checkbox_changed(self, event: Checkbox.Changed) -> None:
        self._update_uefi_options()

    @on(Checkbox.Changed, "#shared-memory-checkbox")
    def on_shared_memory_changed(self, event: Checkbox.Changed) -> None:
        try:
            set_shared_memory(self.domain, event.value)
            self._invalidate_cache()
            self.app.show_success_message(f"Shared memory {'enabled' if event.value else 'disabled'}.")
            self.vm_info['shared_memory'] = event.value
        except (libvirt.libvirtError, ValueError, Exception) as e:
            self.app.show_error_message(f"Error setting shared memory: {e}")
            # Revert checkbox state on failure
            event.checkbox.value = not event.value

    # --- Graphics Tab Event Handlers ---
    @on(Select.Changed, "#graphics-type-select")
    def on_graphics_type_changed(self, event: Select.Changed) -> None:
        self.graphics_info['type'] = event.value
        self._update_graphics_ui()

    @on(Select.Changed, "#graphics-listen-type-select")
    def on_graphics_listen_type_changed(self, event: Select.Changed) -> None:
        self.graphics_info['listen_type'] = event.value
        # If listen type changes to none, clear address
        if event.value == 'none':
            self.graphics_info['address'] = ''
        self._update_graphics_ui()

    @on(RadioSet.Changed, "#graphics-address-radioset")
    def on_graphics_address_changed(self, event: RadioSet.Changed) -> None:
        if event.pressed.id == "graphics-address-localhost":
            self.graphics_info['address'] = '127.0.0.1'
        elif event.pressed.id == "graphics-address-all":
            self.graphics_info['address'] = '0.0.0.0'
        else:
            # For "Hypervisor default", we'll send "0.0.0.0" as a generic default
            # but libvirt might interpret this differently depending on its config.
            # In the UI, it means "don't specify a particular address string".
            self.graphics_info['address'] = '0.0.0.0'
        self._update_graphics_ui()

    @on(Checkbox.Changed, "#graphics-autoport-checkbox")
    def on_graphics_autoport_changed(self, event: Checkbox.Changed) -> None:
        self.graphics_info['autoport'] = event.value
        self._update_graphics_ui()

    @on(Checkbox.Changed, "#graphics-password-enable-checkbox")
    def on_graphics_password_enable_changed(self, event: Checkbox.Changed) -> None:
        self.graphics_info['password_enabled'] = event.value
        self._update_graphics_ui()

    @on(Input.Changed, "#graphics-port-input")
    def on_graphics_port_input_changed(self, event: Input.Changed) -> None:
        try:
            self.graphics_info['port'] = int(event.value) if event.value else None
        except ValueError:
            self.graphics_info['port'] = None # Invalid input, treat as None
        # No UI update needed here, as it's just updating internal state

    @on(Input.Changed, "#graphics-password-input")
    def on_graphics_password_input_changed(self, event: Input.Changed) -> None:
        self.graphics_info['password'] = event.value
        # No UI update needed here, as it's just updating internal state

    @on(Button.Pressed, "#graphics-apply-btn")
    def on_graphics_apply_button_pressed(self, event: Button.Pressed) -> None:
        if not self.is_vm_stopped:
            self.app.show_error_message("VM must be stopped to apply graphics settings.")
            return

        original_graphics_type = self.graphics_info.get('type')
        new_graphics_type = self.query_one("#graphics-type-select", Select).value
        listen_type = self.query_one("#graphics-listen-type-select", Select).value
        
        logging.info(f"Attempting to change graphics from '{original_graphics_type}' to '{new_graphics_type}'.")

        address = None
        if listen_type == 'address':
            address_radioset = self.query_one("#graphics-address-radioset", RadioSet)
            if address_radioset.pressed_button.id == "graphics-address-localhost":
                address = "127.0.0.1"
            else:
                address = "0.0.0.0"

        autoport = self.query_one("#graphics-autoport-checkbox", Checkbox).value
        port_input = self.query_one("#graphics-port-input", Input)
        port = int(port_input.value) if port_input.value and not autoport else None

        password_enabled = self.query_one("#graphics-password-enable-checkbox", Checkbox).value
        password_input = self.query_one("#graphics-password-input", Input)
        password = password_input.value if password_enabled else None

        def do_apply_graphics_settings():
            try:
                set_vm_graphics(
                    self.domain,
                    new_graphics_type if new_graphics_type != "" else None,
                    listen_type,
                    address,
                    port,
                    autoport,
                    password_enabled,
                    password
                )
                self._invalidate_cache()
                self.app.show_success_message("Graphics settings applied successfully.")
                try:
                    root = ET.fromstring(self.domain.XMLDesc(0))
                except ET.ParseError:
                    root = None
                self.graphics_info = get_vm_graphics_info(root)
                self._update_graphics_ui()
            except (libvirt.libvirtError, Exception) as e:
                self.app.show_error_message(f"Error applying graphics settings: {e}")

        # Check if switching from SPICE to VNC and other SPICE devices exist
        has_other_spice_devices = check_for_other_spice_devices(self.domain)
        logging.info(f"Checking for other SPICE devices... Found: {has_other_spice_devices}")

        if new_graphics_type == 'vnc' and has_other_spice_devices:
            logging.info("Condition met for SPICE removal, showing confirmation dialog.")

            def on_confirm_spice_removal(confirmed: bool):
                if confirmed:
                    try:
                        remove_spice_devices(self.domain)
                        self._invalidate_cache()
                        self.app.show_success_message("Removed associated SPICE devices.")
                    except Exception as e:
                        self.app.show_error_message(f"Error removing SPICE devices: {e}")
                        return # Abort on failure

                do_apply_graphics_settings()

            self.app.push_screen(
                ConfirmationDialog("This VM has other SPICE-related devices (e.g., channels, QXL video).\nDo you want to remove them for a clean switch to VNC?"),
                on_confirm_spice_removal
            )
        else:
            logging.info("Condition NOT met for SPICE removal, applying settings directly.")
            do_apply_graphics_settings()

    @on(Button.Pressed, "#apply-rng-btn")
    def on_rng_apply_button_pressed(self, event: Button.Pressed) -> None:
        if not self.is_vm_stopped:
            self.app.show_error_message("VM must be stopped to apply RNG settings.")
            return

        rng_device = self.query_one("#rng-host-device", Input).value
        if not rng_device:
            self.app.show_error_message("RNG device path cannot be empty.")
            return

        try:
            set_vm_rng(self.domain, "virtio", "random", rng_device)
            self._invalidate_cache()
            self.app.show_success_message(f"RNG settings applied successfully. Device: {rng_device}")
        except Exception as e:
            self.app.show_error_message(f"Error applying RNG settings: {e}")

    @on(Select.Changed, "#tpm-type-select")
    def on_tpm_type_changed(self, event: Select.Changed) -> None:
        if self.tpm_info:
            self.tpm_info[0]['type'] = event.value
        else:
            self.tpm_info = [{'type': event.value, 'model': 'tpm-crb'}] # Default model if none exists
        self._update_tpm_ui()

    @on(Select.Changed, "#tpm-model-select")
    def on_tpm_model_changed(self, event: Select.Changed) -> None:
        if self.tpm_info:
            self.tpm_info[0]['model'] = event.value
        else:
            self.tpm_info = [{'model': event.value, 'type': 'emulated'}] # Default type if none exists
        self._update_tpm_ui()

    @on(Button.Pressed, "#apply-tpm-btn")
    def on_tpm_apply_button_pressed(self, event: Button.Pressed) -> None:
        if not self.is_vm_stopped:
            self.app.show_error_message("VM must be stopped to apply TPM settings.")
            return

        tpm_model = self.query_one("#tpm-model-select", Select).value
        tpm_type = self.query_one("#tpm-type-select", Select).value
        device_path = self.query_one("#tpm-device-path-input", Input).value
        backend_type = self.query_one("#tpm-backend-type-input", Input).value
        backend_path = self.query_one("#tpm-backend-path-input", Input).value

        # Basic validation for passthrough
        if tpm_type == 'passthrough' and not device_path:
            self.app.show_error_message("Device path is required for passthrough TPM.")
            return

        try:
            set_vm_tpm(
                self.domain,
                tpm_model if tpm_model != "none" else None,
                tpm_type=tpm_type,
                device_path=device_path if tpm_type == 'passthrough' else None,
                backend_type=backend_type if tpm_type == 'passthrough' else None,
                backend_path=backend_path if tpm_type == 'passthrough' else None
            )
            self._invalidate_cache()
            self.app.show_success_message("TPM settings applied successfully.")
            try:
                root = ET.fromstring(self.domain.XMLDesc(0))
            except ET.ParseError:
                root = None
            self.tpm_info = get_vm_tpm_info(root) # Refresh info
            self._update_tpm_ui()
        except Exception as e:
            self.app.show_error_message(f"Error applying TPM settings: {e}")

    @on(ListView.Highlighted, "#available-devices-list")
    def on_available_devices_list_highlighted(self, event: ListView.Highlighted) -> None:
        if not self.is_vm_stopped:
            return

        if event.item:
            self.query_one("#boot-add", Button).disabled = False
        else:
            self.query_one("#boot-add", Button).disabled = True

    @on(ListView.Highlighted, "#boot-order-list")
    def on_boot_order_list_highlighted(self, event: ListView.Highlighted) -> None:
        if not self.is_vm_stopped: # Buttons should remain disabled if VM is not stopped
            return

        boot_list = self.query_one("#boot-order-list", ListView)

        if event.item:
            self.query_one("#boot-remove", Button).disabled = False
        else:
            self.query_one("#boot-remove", Button).disabled = True

        # Enable/disable Up button
        if event.item and boot_list.index is not None and boot_list.index > 0:
            self.query_one("#boot-up", Button).disabled = False
        else:
            self.query_one("#boot-up", Button).disabled = True

        # Enable/disable Down button
        if event.item and boot_list.index is not None and boot_list.index < len(boot_list.children) - 1:
            self.query_one("#boot-down", Button).disabled = False
        else:
            self.query_one("#boot-down", Button).disabled = True

    def _populate_usb_lists(self):
        """Populates the USB device lists."""
        available_list = self.query_one("#available-usb-list", ListView)
        attached_list = self.query_one("#attached-usb-list", ListView)
        available_list.clear()
        attached_list.clear()

        host_devices = get_host_usb_devices(self.conn)
        try:
            root = ET.fromstring(self.xml_desc)
        except ET.ParseError:
            root = None
        attached_device_ids = get_attached_usb_devices(root)

        attached_ids_list = [(d['vendor_id'], d['product_id']) for d in attached_device_ids]

        for dev in host_devices:
            dev_id = (dev['vendor_id'], dev['product_id'])
            item = ListItem(Label(dev['description']))
            item.tooltip = dev['description']
            item.data = dev
            if dev_id in attached_ids_list:
                attached_list.append(item)
                attached_ids_list.remove(dev_id)
            else:
                available_list.append(item)

        for vendor_id, product_id in attached_ids_list:
            description = f"Disconnected Device ({vendor_id}:{product_id})"
            item = ListItem(Label(description))
            item.tooltip = description
            item.data = {"vendor_id": vendor_id, "product_id": product_id, "description": description, "disconnected": True}
            attached_list.append(item)

    @on(ListView.Highlighted, "#available-usb-list")
    def on_available_usb_list_highlighted(self, event: ListView.Highlighted) -> None:
        self.query_one("#attach-usb-btn", Button).disabled = event.item is None

    @on(ListView.Highlighted, "#attached-usb-list")
    def on_attached_usb_list_highlighted(self, event: ListView.Highlighted) -> None:
        self.query_one("#detach-usb-btn", Button).disabled = event.item is None

    @on(Button.Pressed, "#attach-usb-btn")
    def on_attach_usb_button_pressed(self, event: Button.Pressed) -> None:
        available_list = self.query_one("#available-usb-list", ListView)
        if available_list.highlighted_child:
            device_to_attach = available_list.highlighted_child.data
            vendor_id = device_to_attach['vendor_id']
            product_id = device_to_attach['product_id']
            try:
                attach_usb_device(self.domain, vendor_id, product_id)
                self._invalidate_cache()
                self.app.show_success_message(f"Attached USB device: {device_to_attach['description']}")
                self.xml_desc = self.domain.XMLDesc(0)
                self._populate_usb_lists()
            except libvirt.libvirtError as e:
                self.app.show_error_message(f"Error attaching USB device: {e}")

    @on(Button.Pressed, "#detach-usb-btn")
    def on_detach_usb_button_pressed(self, event: Button.Pressed) -> None:
        attached_list = self.query_one("#attached-usb-list", ListView)
        if attached_list.highlighted_child:
            device_to_detach = attached_list.highlighted_child.data
            vendor_id = device_to_detach['vendor_id']
            product_id = device_to_detach['product_id']
            try:
                detach_usb_device(self.domain, vendor_id, product_id)
                self._invalidate_cache()
                self.app.show_success_message(f"Detached USB device: {device_to_detach['description']}")
                self.xml_desc = self.domain.XMLDesc(0)
                self._populate_usb_lists()
            except libvirt.libvirtError as e:
                self.app.show_error_message(f"Error detaching USB device: {e}")

    def _populate_pci_lists(self):
        """Populates the PCI device lists."""
        available_list = self.query_one("#available-pci-list", ListView)
        attached_list = self.query_one("#attached-pci-list", ListView)
        available_list.clear()
        attached_list.clear()

        host_devices = get_host_pci_devices(self.conn)
        try:
            root = ET.fromstring(self.xml_desc)
        except ET.ParseError:
            root = None
        attached_device_info = get_attached_pci_devices(root)

        attached_pci_addresses = [d['pci_address'] for d in attached_device_info]

        for dev in host_devices:
            if dev['pci_address'] in attached_pci_addresses:
                item = ListItem(Label(dev['description']))
                item.tooltip = dev['description']
                item.data = dev
                attached_list.append(item)
                attached_pci_addresses.remove(dev['pci_address']) # Remove so it's not added twice
            else:
                item = ListItem(Label(dev['description']))
                item.tooltip = dev['description']
                item.data = dev
                available_list.append(item)

        # Add any attached devices that are no longer present on the host
        for pci_address in attached_pci_addresses:
            description = f"Disconnected Device ({pci_address})"
            item = ListItem(Label(description))
            item.tooltip = description
            item.data = {"pci_address": pci_address, "description": description, "disconnected": True}
            attached_list.append(item)

    @on(ListView.Highlighted, "#available-pci-list")
    def on_available_pci_list_highlighted(self, event: ListView.Highlighted) -> None:
        self.query_one("#attach-pci-btn", Button).disabled = event.item is None

    @on(ListView.Highlighted, "#attached-pci-list")
    def on_attached_pci_list_highlighted(self, event: ListView.Highlighted) -> None:
        self.query_one("#detach-pci-btn", Button).disabled = event.item is None

    @on(Button.Pressed, "#attach-pci-btn")
    def on_attach_pci_button_pressed(self, event: Button.Pressed) -> None:
        self.app.show_error_message("PCI passthrough not implemented yet.")

    @on(Button.Pressed, "#detach-pci-btn")
    def on_detach_pci_button_pressed(self, event: Button.Pressed) -> None:
        self.app.show_error_message("PCI passthrough not implemented yet.")

    def _populate_serial_table(self):
        """Populates the serial devices table."""
        serial_table = self.query_one("#serial-table", DataTable)
        serial_table.clear()
        if not serial_table.columns:
            serial_table.add_column("Device", key="device")
            serial_table.add_column("Details", key="details")

        try:
            root = ET.fromstring(self.xml_desc)
        except ET.ParseError:
            root = None
        self.serial_devices = get_serial_devices(root)
        for i, device in enumerate(self.serial_devices):
            row_key = f"{device['device']}-{device['port']}-{i}"
            serial_table.add_row(device['device'], device['details'], key=row_key)

    @on(DataTable.RowSelected, "#serial-table")
    def on_serial_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_index = event.cursor_row
        if 0 <= row_index < len(self.serial_devices):
            self.selected_serial_port = self.serial_devices[row_index]['port']
            self.query_one("#remove-serial-btn").disabled = self.selected_serial_port == 'N/A'
        else:
            self.selected_serial_port = None
            self.query_one("#remove-serial-btn").disabled = True

    def _populate_input_table(self):
        """Populates the input devices table."""
        input_table = self.query_one("#input-table", DataTable)
        input_table.clear()
        if not input_table.columns:
            input_table.add_column("Type", key="type")
            input_table.add_column("Bus", key="bus")

        try:
            root = ET.fromstring(self.xml_desc)
        except ET.ParseError:
            root = None
        self.input_devices = get_vm_input_info(root)
        for i, device in enumerate(self.input_devices):
            row_key = f"{device['type']}-{device['bus']}-{i}"
            input_table.add_row(device['type'], device['bus'], key=row_key)

    def _update_input_table(self):
        """Refreshes the input table."""
        try:
            # Refresh domain object to ensure we get the latest config
            self.domain = self.conn.lookupByUUIDString(self.vm_info['uuid'])
        except libvirt.libvirtError as e:
            logging.error(f"Error refreshing domain object: {e}")

        self.xml_desc = self.domain.XMLDesc(0)
        logging.info(f"Updated XML for VM {self.vm_name}")

        try:
            root = ET.fromstring(self.xml_desc)
        except ET.ParseError:
            root = None
        inputs = get_vm_input_info(root)
        logging.info(f"Found {len(inputs)} input devices after update: {inputs}")

        if 'devices' in self.vm_info and isinstance(self.vm_info['devices'], dict):
            self.vm_info['devices']['input'] = inputs
        self._populate_input_table()

    @on(DataTable.RowSelected, "#input-table")
    def on_input_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_index = event.cursor_row
        if 0 <= row_index < len(self.input_devices):
            self.selected_input_device = self.input_devices[row_index]
            self.query_one("#remove-input-btn").disabled = not self.is_vm_stopped
        else:
            self.selected_input_device = None
            self.query_one("#remove-input-btn").disabled = True

    def _populate_controller_table(self):
        """Populates the controller devices table."""
        controller_table = self.query_one("#controller-table", DataTable)
        controller_table.clear()
        if not controller_table.columns:
            controller_table.add_column("Type", key="type")
            controller_table.add_column("Model", key="model")
            controller_table.add_column("Index", key="index")

        devices = self.vm_info.get("devices", {})
        usb_controllers = devices.get("usb", [])
        scsi_controllers = devices.get("scsi", [])

        all_controllers = []
        for controller in usb_controllers:
            if controller.get('type') == 'controller':
                all_controllers.append({'type': 'USB', 'model': controller['model'], 'index': controller['index']})
        for controller in scsi_controllers:
             if controller.get('type') == 'controller':
                all_controllers.append({'type': 'SCSI', 'model': controller['model'], 'index': controller['index']})

        for i, device in enumerate(all_controllers):
            row_key = f"{device['type']}-{device['model']}-{device['index']}"
            controller_table.add_row(device['type'], device['model'], device['index'], key=row_key)

    def _update_controller_table(self):
        """Refreshes the controller table."""
        new_xml = self.domain.XMLDesc(0)
        try:
            root = ET.fromstring(new_xml)
        except ET.ParseError:
            root = None
        self.vm_info['devices'] = get_vm_devices_info(root)
        self._populate_controller_table()

    @on(DataTable.RowSelected, "#controller-table")
    def on_controller_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_key = event.row_key.value
        if row_key:
            parts = row_key.split('-')
            controller_type = parts[0]
            controller_index = parts[-1]
            controller_model = '-'.join(parts[1:-1])
            self.selected_controller = {
                'type': controller_type,
                'model': controller_model,
                'index': controller_index
            }
            self.query_one("#remove-controller-btn").disabled = not self.is_vm_stopped
        else:
            self.selected_controller = None
            self.query_one("#remove-controller-btn").disabled = True

    def compose(self) -> ComposeResult:
        xml_root = ET.fromstring(self.xml_desc)
        status = self.vm_info.get("status", "N/A")
        uuid_vm = self.vm_info.get('uuid', 'N/A')
        with Vertical(id="vm-detail-container"):
            with Horizontal(id="vm-details-title"):
                yield Label(f"VM Details: {self.vm_name} ", id="title_vm")
                yield Label(f"({status})", id=f"status-{status.lower().replace(' ', '-')}")
            yield Label(f"UUID: {self.vm_info.get('uuid', 'N/A')}", id="vm-details-uuid")
            yield Button("Other Tabs", id="toggle-detail-button", classes="toggle-detail-button")
            with TabbedContent(id="detail-vm"):
                with TabPane("CPU", id="detail-cpu-tab"):
                    with Vertical(classes="info-details"):
                        yield Label(f"CPU: {self.vm_info.get('cpu', 'N/A')}", id="cpu-label", classes="tabd")
                        yield Button("Edit", id="edit-cpu", classes="edit-detail-btn")

                        # CPU Model Selection
                        current_cpu_model = self.vm_info.get('cpu_model', 'default')
                        yield Label(f"CPU Model: {current_cpu_model}", id="cpu-model-label", classes="tabd")

                        arch_elem = xml_root.find(".//os/type")
                        arch = arch_elem.get('arch') if arch_elem is not None else 'x86_64'

                        cpu_models = get_cpu_models(self.conn, arch)
                        # Ensure 'host-passthrough' and 'default' are in the list
                        if 'host-passthrough' not in cpu_models:
                            cpu_models.append('host-passthrough')
                        if 'default' not in cpu_models:
                            cpu_models.append('default')

                        cpu_model_options = [(model, model) for model in sorted(cpu_models)]

                        yield Select(
                            cpu_model_options,
                            value=current_cpu_model,
                            id="cpu-model-select",
                            disabled=not self.is_vm_stopped,
                            classes="cpu-model-select"
                        )
                with TabPane("Mem", id="detail-mem-tab", ):
                    with Vertical(classes="info-details"):
                        yield Label(f"Memory: {self.vm_info.get('memory', 'N/A')} MB", id="memory-label", classes="tabd")
                        yield Button("Edit", id="edit-memory", classes="edit-detail-btn")
                        yield Checkbox("Shared Memory", value=self.vm_info.get('shared_memory', False), id="shared-memory-checkbox", classes="shared-memory", disabled=not self.is_vm_stopped)
                with TabPane("Firmware", id="detail-firmware-tab"):
                    with Vertical(classes="info-details"):
                        firmware_info = self.vm_info.get('firmware', {'type': 'BIOS'})
                        firmware_type = firmware_info.get('type', 'BIOS')
                        firmware_path = firmware_info.get('path')

                        yield Label(f"Firmware: {firmware_type}", id="firmware-type-label")
                        if firmware_path:
                            yield Label(f"File: {os.path.basename(firmware_path)}", id="firmware-path-label")

                        if firmware_type == 'UEFI':
                            yield Checkbox(
                                "Secure Boot",
                                value=firmware_info.get('secure_boot', False),
                                id="secure-boot-checkbox",
                                disabled=not self.is_vm_stopped,
                            )
                            yield Checkbox("AMD-SEV", id="sev-checkbox", disabled=not self.is_vm_stopped)
                            yield Checkbox("AMD-SEV-ES", id="sev-es-checkbox", disabled=not self.is_vm_stopped)
                            yield Select(
                                [], # Will be populated in on_mount
                                id="uefi-file-select",
                                disabled=not self.is_vm_stopped,
                                allow_blank=True,
                            )
                            yield Button("Switch to BIOS", id="switch-to-bios", disabled=not self.is_vm_stopped)
                        else:
                            yield Button("Switch to UEFI", id="switch-to-uefi", disabled=not self.is_vm_stopped)


                        if "machine_type" in self.vm_info:
                            yield Label(f"Machine Type: {self.vm_info['machine_type']}", id="machine-type-label", classes="tabd")
                            yield Button("Edit", id="edit-machine-type", classes="edit-detail-btn", disabled=not self.is_vm_stopped)

                with TabPane("Boot", id="detail-boot-tab"):
                    with Vertical(classes="info-details"):
                        yield Checkbox("Enable boot menu", id="boot-menu-enable", disabled=not self.is_vm_stopped)
                        with Horizontal(classes="boot-manager"):
                            with Vertical(classes="boot-list-container"):
                                yield Label("Boot Order")
                                yield ListView(id="boot-order-list")
                            with Vertical(classes="boot-buttons"):
                                yield Button("<", id="boot-add", disabled=not self.is_vm_stopped)
                                yield Button(">", id="boot-remove", disabled=not self.is_vm_stopped)
                                yield Button("Up", id="boot-up", disabled=not self.is_vm_stopped)
                                yield Button("Down", id="boot-down", disabled=not self.is_vm_stopped)
                            with Vertical(classes="boot-list-container"):
                                yield Label("Available Devices")
                                yield ListView(id="available-devices-list")
                    yield Button("Save Boot Order", id="save-boot-order", disabled=not self.is_vm_stopped, variant="primary")

                with TabPane("Disks", id="detail-disk-tab"):
                    with ScrollableContainer(classes="info-details"):
                        yield DataTable(id="disks-table", cursor_type="row")

                    disks_info = self.vm_info.get("disks", [])
                    has_enabled_disks = any(d['status'] == 'enabled' for d in disks_info)
                    has_disabled_disks = any(d['status'] == 'disabled' for d in disks_info)
                    remove_button = Button("Remove Disk", id="detail_remove_disk", classes="detail-disks")
                    disable_button = Button("Disable Disk", id="detail_disable_disk", classes="detail-disks")
                    enable_button = Button("Enable Disk", id="detail_enable_disk", classes="detail-disks")
                    remove_button.display = has_enabled_disks
                    disable_button.display = has_enabled_disks
                    enable_button.display = has_disabled_disks

                    with Vertical(classes="button-details"):
                        with Horizontal():
                            yield Button("Add Disk", id="detail_add_disk", classes="detail-disks")
                            yield Button("Attach Existing Disk", id="detail_attach_disk", classes="detail-disks")
                            yield Button("Edit Disk", id="detail_edit_disk", classes="detail-disks", disabled=True)
                            yield remove_button

                    with Horizontal(classes="button-details"):
                        yield disable_button
                        yield enable_button

                with TabPane("Networks", id="networks"):
                    with ScrollableContainer(classes="info-details"):
                        networks_table = DataTable(id="networks-table", cursor_type="row")
                        networks_table.add_column("MAC", key="mac")
                        networks_table.add_column("Network", key="network")
                        networks_table.add_column("Model", key="model")
                        networks_table.add_column("IP Address", key="ip")
                        networks_table.add_column("Gateway", key="gateway")
                        networks_table.add_column("DNS", key="dns")
                        yield networks_table

                    with Vertical(classes="button-details"):
                        with Horizontal():
                            yield Button("Edit Interface", id="edit-network-interface-button", classes="detail-disks", variant="primary", disabled=True)
                            yield Button("Add Interface", id="add-network-interface-button", classes="detail-disks", variant="primary")
                            yield Button("Remove Interface", id="remove-network-interface-button", classes="detail-disks", variant="error", disabled=True)

                if self.vm_info.get("devices"):
                    with TabPane("VirtIO-FS", id="detail-virtiofs-tab"):
                        if not self.vm_info.get('shared_memory'):
                            yield Label("! Shared Memory is Mandatory to use VirtIO-FS.\n! Enable it in Mem tab.", classes="tabd-warning")
                        with ScrollableContainer(classes="info-details"):
                            virtiofs_table = DataTable(id="virtiofs-table")
                            virtiofs_table.cursor_type = "row"
                            virtiofs_table.add_column("Source Path", key="source")
                            virtiofs_table.add_column("Target Path", key="target")
                            virtiofs_table.add_column("Readonly", key="readonly")
                            for fs in self.vm_info["devices"]["virtiofs"]:
                                virtiofs_table.add_row(
                                    fs.get('source', 'N/A'),
                                    fs.get('target', 'N/A'),
                                    str(fs.get('readonly', False)),
                                    key=fs.get('target')
                                )
                            yield virtiofs_table
                        with Vertical(classes="button-details"):
                            with Horizontal():
                                yield Button("Add", variant="primary", id="add-virtiofs-btn", classes="detail-disks")
                                yield Button("Edit", variant="default", id="edit-virtiofs-btn", disabled=True, classes="detail-disks")
                                yield Button("Delete", variant="error", id="delete-virtiofs-btn", disabled=True, classes="detail-disks")

                with TabPane("Video", id="detail-video-tab"):
                    with Vertical(classes="info-details"):
                        current_model = self.vm_info.get('video_model') or "default"

                        video_models = []
                        try:
                            os_type_elem = xml_root.find(".//os/type")
                            arch = os_type_elem.get('arch') if os_type_elem is not None else 'x86_64'
                            machine = os_type_elem.get('machine') if os_type_elem is not None else None

                            emulator_elem = xml_root.find(".//devices/emulator")
                            emulatorbin = emulator_elem.text if emulator_elem is not None else None

                            if machine and emulatorbin:
                                caps_xml = get_domain_capabilities_xml(self.conn, emulatorbin, arch, machine)
                                if caps_xml:
                                    video_caps = get_video_domain_capabilities(caps_xml)
                                    video_models = video_caps.get('video_models', [])

                        except Exception as e:
                            logging.error(f"Could not dynamically get video models: {e}")

                        # Fallback to hardcoded list if dynamic fetch fails or returns empty
                        if not video_models:
                            video_models = ["default", "virtio", "qxl", "vga", "cirrus", "bochs", "ramfb", "none"]

                        # Ensure 'default' and 'none' are present, as they are special values
                        if 'default' not in video_models:
                            video_models.insert(0, 'default')
                        if 'none' not in video_models:
                            video_models.append('none')

                        video_model_options = [(model, model) for model in video_models]

                        yield Label(f"Video Model: {current_model}", id="video-model-label")
                        yield Select(
                            video_model_options,
                            value=current_model if current_model in video_models else "default",
                            id="video-model-select",
                            disabled=not self.is_vm_stopped,
                            allow_blank=False,
                        )

                with TabPane("Sound", id="detail-sound-tab"):
                    with Vertical(classes="info-details"):
                        current_sound_model = self.vm_info.get('sound_model') or "none"
                
                        sound_models = self.app.config.get('sound_models', [])
                        if not sound_models:
                            sound_models = ["none", "ich6", "ich9", "ac97", "sb16", "usb"]

                        sound_model_options = [(model, model) for model in sound_models]

                        yield Label(f"Sound Model: {current_sound_model}", id="sound-model-label")
                        yield Select(
                            sound_model_options,
                            value=current_sound_model if current_sound_model in sound_models else "none",
                            id="sound-model-select",
                            disabled=not self.is_vm_stopped,
                            allow_blank=False,
                        )

                with TabPane("Graphics", id="detail-graphics-tab"):
                    with ScrollableContainer(classes="info-details"):
                        yield Label("Type:")
                        yield Select(
                            [("VNC", "vnc"), ("Spice", "spice"), ("None", "")],
                            value=self.graphics_info['type'],
                            id="graphics-type-select",
                            disabled=not self.is_vm_stopped
                        )
                        yield Label("Listen Type:")
                        yield Select(
                            [("Address", "address"), ("None", "none")],
                            value=self.graphics_info['listen_type'],
                            id="graphics-listen-type-select",
                            disabled=not self.is_vm_stopped
                        )
                        yield Label("Address:")
                        with RadioSet(id="graphics-address-radioset", disabled=not self.is_vm_stopped or self.graphics_info['listen_type'] != 'address'):
                            yield RadioButton("Hypervisor default", id="graphics-address-default", value=self.graphics_info['address'] not in ['127.0.0.1', '0.0.0.0'])
                            yield RadioButton("Localhost only", id="graphics-address-localhost", value=self.graphics_info['address'] == '127.0.0.1')
                            yield RadioButton("All interfaces", id="graphics-address-all", value=self.graphics_info['address'] == '0.0.0.0')
                        yield Checkbox(
                            "Auto Port",
                            value=self.graphics_info['autoport'],
                            id="graphics-autoport-checkbox",
                            disabled=not self.is_vm_stopped
                        )
                        yield Input(
                            placeholder="Port (e.g., 5900)",
                            value=str(self.graphics_info['port']) if self.graphics_info['port'] else "",
                            id="graphics-port-input",
                            type="integer",
                            disabled=not self.is_vm_stopped or self.graphics_info['autoport']
                        )
                        yield Checkbox(
                            "Enable Password",
                            value=self.graphics_info['password_enabled'],
                            id="graphics-password-enable-checkbox",
                            disabled=not self.is_vm_stopped
                        )
                        yield Input(
                            placeholder="Password",
                            value=self.graphics_info['password'] if self.graphics_info['password_enabled'] else "",
                            id="graphics-password-input",
                            password=True, # Hide password input
                            disabled=not self.is_vm_stopped or not self.graphics_info['password_enabled']
                        )
                    yield Button("Apply Graphics Settings", id="graphics-apply-btn", variant="primary", disabled=not self.is_vm_stopped)
                with TabPane("TPM", id="detail-tpm-tab"):
                    tpm_model = self.tpm_info[0].get('model') if self.tpm_info else 'none'
                    tpm_type = self.tpm_info[0].get('type') if self.tpm_info else 'emulated'
                    tpm_device_path = self.tpm_info[0].get('device_path', '') if self.tpm_info else ''
                    tpm_backend_type = self.tpm_info[0].get('backend_type', '') if self.tpm_info else ''
                    tpm_backend_path = self.tpm_info[0].get('backend_path', '') if self.tpm_info else ''

                    with Vertical(classes="info-details"):
                        yield Label("TPM Model:")
                        yield Select(
                            [("None", "none"), ("tpm-crb", "tpm-crb"), ("tpm-tis", "tpm-tis")],
                            value=tpm_model,
                            id="tpm-model-select",
                            disabled=not self.is_vm_stopped,
                            allow_blank=False,
                        )
                        yield Label("TPM Type:")
                        yield Select(
                            [("Emulated", "emulated"), ("Passthrough", "passthrough")],
                            value=tpm_type,
                            id="tpm-type-select",
                            disabled=not self.is_vm_stopped,
                            allow_blank=False,
                        )
                        yield Label("Device Path (for passthrough):")
                        yield Input(
                            value=tpm_device_path,
                            id="tpm-device-path-input",
                            disabled=not self.is_vm_stopped or tpm_type != 'passthrough',
                            placeholder="/dev/tpm0"
                        )
                        yield Label("Backend Type (for passthrough):")
                        yield Input(
                            value=tpm_backend_type,
                            id="tpm-backend-type-input",
                            disabled=not self.is_vm_stopped or tpm_type != 'passthrough',
                            placeholder="emulator or passthrough"
                        )
                        yield Label("Backend Path (for passthrough):")
                        yield Input(
                            value=tpm_backend_path,
                            id="tpm-backend-path-input",
                            disabled=not self.is_vm_stopped or tpm_type != 'passthrough',
                            placeholder="/dev/tpmrm0"
                        )
                    yield Button("Apply TPM Settings", id="apply-tpm-btn", variant="primary", disabled=not self.is_vm_stopped)


            with TabbedContent(id="detail2-vm"):
                with TabPane("RNG", id="detail-rng-tab"):
                    with Vertical(classes="info-details"):
                        current_path = self.rng_info["backend_path"]
                        yield Label("Host device")
                        yield Input(value=current_path, id="rng-host-device")
                        yield Button("Apply RNG Settings", id="apply-rng-btn", variant="primary")
        # TOFIX !
                with TabPane("Serial", id="detail-serial-tab"):
                    with ScrollableContainer(classes="info-details"):
                        yield DataTable(id="serial-table", cursor_type="row")
                    with Vertical(classes="button-details"):
                        with Horizontal():
                            yield Button("Add PTY Console", id="add-serial-btn", variant="primary", disabled=not self.is_vm_stopped)
                            yield Button("Remove Console", id="remove-serial-btn", variant="error", disabled=True)
                with TabPane("Watchdog", id="detail-watchdog-tab"):
                    watchdog_model = self.watchdog_info.get('model') if self.watchdog_info and self.watchdog_info.get('model') else 'none'
                    watchdog_action = self.watchdog_info.get('action') if self.watchdog_info and self.watchdog_info.get('action') else 'reset'

                    with Vertical(classes="info-details"):
                        yield Label("Watchdog Model:")
                        
                        watchdog_models = [("None", "none"), ("i6300esb", "i6300esb"), ("ib700", "ib700"), ("diag288", "diag288")]
                        
                        # Add current model if not in list to prevent crash
                        known_models = [m[1] for m in watchdog_models]
                        if watchdog_model not in known_models:
                             watchdog_models.append((watchdog_model, watchdog_model))

                        yield Select(
                            watchdog_models,
                            value=watchdog_model,
                            id="watchdog-model-select",
                            disabled=not self.is_vm_stopped,
                            allow_blank=False
                        )
                        yield Label("Action:")
                        yield Select(
                            [("Reset", "reset"), ("Shutdown", "shutdown"), ("Poweroff", "poweroff"), ("Pause", "pause"), ("None", "none"), ("Dump", "dump"), ("Inject-NMI", "inject-nmi")],
                            value=watchdog_action,
                            id="watchdog-action-select",
                            disabled=not self.is_vm_stopped,
                            allow_blank=False
                        )
                    with Vertical(classes="button-details"):
                        with Horizontal():
                            yield Button("Apply Watchdog Settings", id="apply-watchdog-btn", variant="primary", disabled=not self.is_vm_stopped)
                            yield Button("Remove Watchdog", id="remove-watchdog-btn", variant="error", disabled=not self.is_vm_stopped or watchdog_model == 'none')
                with TabPane("Input", id="detail-input-tab"):
                    with VerticalScroll(classes="info-details"):
                        yield DataTable(id="input-table", cursor_type="row")
                    with Vertical(classes="button-details"):
                        with Horizontal():
                            yield Button("Add Input", id="add-input-btn", variant="primary", disabled=not self.is_vm_stopped)
                            yield Button("Remove Input", id="remove-input-btn", variant="error", disabled=True)
                with TabPane("Controller", id="detail-controler-tab"):
                    with ScrollableContainer(classes="info-details"):
                        yield DataTable(id="controller-table", cursor_type="row")
                    with Vertical(classes="button-details"):
                        with Horizontal():
                            yield Button("Add USB2", id="add-usb2-controller-btn", variant="primary", disabled=not self.is_vm_stopped)
                            yield Button("Add USB3", id="add-usb3-controller-btn", variant="primary", disabled=not self.is_vm_stopped)
                            yield Button("Add SCSI", id="add-scsi-controller-btn", variant="primary", disabled=not self.is_vm_stopped)
                            yield Button("Remove", id="remove-controller-btn", variant="error", disabled=True)
                with TabPane("USB Host", id="detail-usbhost-tab"):
                    with Horizontal(classes="boot-manager"):
                        with Vertical(classes="boot-list-container"):
                            yield Label("Available Host USB Devices")
                            yield ListView(id="available-usb-list")
                        with Vertical(classes="boot-buttons"):
                            yield Button("Attach >", id="attach-usb-btn", disabled=True)
                            yield Button("< Detach", id="detach-usb-btn", disabled=True)
                        with Vertical(classes="boot-list-container"):
                            yield Label("Attached to VM")
                            yield ListView(id="attached-usb-list")
                with TabPane("PCI Host", id="detail-PCIhost-tab"):
                    with Horizontal(classes="boot-manager"):
                        with Vertical(classes="boot-list-container"):
                            yield Label("Available Host PCI Devices")
                            yield ListView(id="available-pci-list")
                        with Vertical(classes="boot-buttons"):
                            yield Button("Attach >", id="attach-pci-btn", disabled=True)
                            yield Button("< Detach", id="detach-pci-btn", disabled=True)
                        with Vertical(classes="boot-list-container"):
                            yield Label("Attached to VM")
                            yield ListView(id="attached-pci-list")
                #with TabPane("PCIe", id="detail-pcie-tab"):
                #    yield Label("PCIe")
                #with TabPane("SATA", id="detail-sata-tab"):
                #    yield Label("SATA")
                with TabPane("Channel", id="detail-channel-tab"):
                    yield Label("TODO Channel")

            yield Button("Close", variant="default", id="close-btn", classes="close-button")

    def _update_tpm_ui(self) -> None:
        """Updates the UI elements for the TPM tab based on self.tpm_info."""

        # TPM Model
        try:
            tpm_model_select = self.query_one("#tpm-model-select", Select)
            tpm_model_select.value = self.tpm_info[0].get('model', 'none') if self.tpm_info else 'none'
            tpm_model_select.disabled = not self.is_vm_stopped
        except Exception:
            pass

        # TPM Type
        try:
            tpm_type_select = self.query_one("#tpm-type-select", Select)
            tpm_type_select.value = self.tpm_info[0].get('type', 'emulated') if self.tpm_info else 'emulated'
            tpm_type_select.disabled = not self.is_vm_stopped
        except Exception:
            pass

        # Device Path (for passthrough)
        try:
            device_path_input = self.query_one("#tpm-device-path-input", Input)
            device_path_input.value = self.tpm_info[0].get('device_path', '') if self.tpm_info else ''
            device_path_input.disabled = not self.is_vm_stopped or (self.tpm_info[0].get('type') != 'passthrough' if self.tpm_info else True)
        except Exception:
            pass

        # Backend Type
        try:
            backend_type_input = self.query_one("#tpm-backend-type-input", Input)
            backend_type_input.value = self.tpm_info[0].get('backend_type', '') if self.tpm_info else ''
            backend_type_input.disabled = not self.is_vm_stopped or (self.tpm_info[0].get('type') != 'passthrough' if self.tpm_info else True)
        except Exception:
            pass

        # Backend Path
        try:
            backend_path_input = self.query_one("#tpm-backend-path-input", Input)
            backend_path_input.value = self.tpm_info[0].get('backend_path', '') if self.tpm_info else ''
            backend_path_input.disabled = not self.is_vm_stopped or (self.tpm_info[0].get('type') != 'passthrough' if self.tpm_info else True)
        except Exception:
            pass

        # Apply button
        try:
            self.query_one("#apply-tpm-btn", Button).disabled = not self.is_vm_stopped
        except Exception:
            pass

    def _update_watchdog_ui(self) -> None:
        """Updates the UI elements for the Watchdog tab."""
        try:
            model = self.watchdog_info.get('model') if self.watchdog_info else 'none'
            action = self.watchdog_info.get('action') if self.watchdog_info else 'reset'

            self.query_one("#watchdog-model-select", Select).value = model
            self.query_one("#watchdog-action-select", Select).value = action
            
            self.query_one("#apply-watchdog-btn", Button).disabled = not self.is_vm_stopped
            self.query_one("#remove-watchdog-btn", Button).disabled = not self.is_vm_stopped or model == 'none'
        except Exception:
            pass

    @on(Button.Pressed, "#apply-watchdog-btn")
    def on_watchdog_apply_button_pressed(self, event: Button.Pressed) -> None:
        if not self.is_vm_stopped:
            self.app.show_error_message("VM must be stopped to apply Watchdog settings.")
            return

        model = self.query_one("#watchdog-model-select", Select).value
        action = self.query_one("#watchdog-action-select", Select).value

        if model == 'none':
             # If none is selected, treat it as removal
             self.on_watchdog_remove_button_pressed(event)
             return

        try:
            set_vm_watchdog(self.domain, model, action)
            self._invalidate_cache()
            self.app.show_success_message("Watchdog settings applied successfully.")
            try:
                root = ET.fromstring(self.domain.XMLDesc(0))
            except ET.ParseError:
                root = None
            self.watchdog_info = get_vm_watchdog_info(root)
            self._update_watchdog_ui()
        except Exception as e:
            self.app.show_error_message(f"Error applying Watchdog settings: {e}")

    @on(Button.Pressed, "#remove-watchdog-btn")
    def on_watchdog_remove_button_pressed(self, event: Button.Pressed) -> None:
        if not self.is_vm_stopped:
            self.app.show_error_message("VM must be stopped to remove Watchdog.")
            return

        def on_confirm(confirmed: bool):
            if confirmed:
                try:
                    remove_vm_watchdog(self.domain)
                    self._invalidate_cache()
                    self.app.show_success_message("Watchdog removed successfully.")
                    self.watchdog_info = {'model': 'none', 'action': 'reset'} # Reset to defaults
                    self._update_watchdog_ui()
                except Exception as e:
                    self.app.show_error_message(f"Error removing Watchdog: {e}")

        self.app.push_screen(ConfirmationDialog("Are you sure you want to remove the Watchdog device?"), on_confirm)


    def _update_disk_list(self):
        new_xml = self.domain.XMLDesc(0)
        try:
            root = ET.fromstring(new_xml)
        except ET.ParseError:
            root = None
        disks_info = get_vm_disks_info(self.conn, root)
        self.vm_info['disks'] = disks_info
        self._populate_disks_table()

    @on(DataTable.RowSelected, "#disks-table")
    def on_disks_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.query_one("#detail_edit_disk", Button).disabled = False

    @on(DataTable.RowSelected, "#virtiofs-table")
    def on_virtiofs_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.selected_virtiofs_target = event.row_key.value
        # Get the full virtiofs info for editing
        row_index = event.cursor_row
        virtiofs_data = self.vm_info["devices"]["virtiofs"]
        if 0 <= row_index < len(virtiofs_data):
            self.selected_virtiofs_info = virtiofs_data[row_index]
        else:
            self.selected_virtiofs_info = None

        self.query_one("#delete-virtiofs-btn", Button).disabled = False
        self.query_one("#edit-virtiofs-btn", Button).disabled = False

    @on(DataTable.RowSelected, "#networks-table")
    def on_networks_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.selected_network_interface = event.row_key.value
        self.query_one("#edit-network-interface-button", Button).disabled = False
        self.query_one("#remove-network-interface-button", Button).disabled = False


    def _update_virtiofs_table(self) -> None:
        """Refreshes the virtiofs table."""
        virtiofs_table = self.query_one("#virtiofs-table", DataTable)
        virtiofs_table.clear()

        # Re-fetch VM info to get updated virtiofs list
        new_xml = self.domain.XMLDesc(0)
        try:
            root = ET.fromstring(new_xml)
        except ET.ParseError:
            root = None
        updated_devices = get_vm_devices_info(root)
        self.vm_info['devices']['virtiofs'] = updated_devices.get('virtiofs', [])

        for fs in self.vm_info["devices"]["virtiofs"]:
            virtiofs_table.add_row(
                fs.get('source', 'N/A'),
                fs.get('target', 'N/A'),
                str(fs.get('readonly', False)),
                key=fs.get('target')
            )
        self.selected_virtiofs_target = None
        self.selected_virtiofs_info = None
        self.query_one("#delete-virtiofs-btn", Button).disabled = True

    def _update_networks_table(self):
        """Refreshes the networks table."""
        new_xml = self.domain.XMLDesc(0)
        try:
            root = ET.fromstring(new_xml)
        except ET.ParseError:
            root = None
        self.vm_info['networks'] = get_vm_networks_info(root)
        self.vm_info['detail_network'] = get_vm_network_ip(self.domain)
        self._populate_networks_table()

    def on_button_pressed(self, event: Button.Pressed) -> None:

        if event.button.id == "toggle-detail-button":
            vm = self.query_one("#detail-vm")
            vm2 = self.query_one("#detail2-vm")
            vm.toggle_class("hidden")
            vm2.toggle_class("hidden")
        elif event.button.id == "close-btn":
            self.dismiss()

        elif event.button.id == "add-input-btn":
            def add_input_callback(result):
                if result:
                    try:
                        add_vm_input(
                            self.domain,
                            result["type"],
                            result["bus"]
                        )
                        self._invalidate_cache()
                        self.app.show_success_message("Input device added successfully.")
                        self._update_input_table()
                    except (libvirt.libvirtError, ValueError) as e:
                        self.app.show_error_message(f"Error adding input device: {e}")

            available_types = ["mouse", "tablet", "keyboard"]
            available_buses = ["usb", "ps2", "virtio"]
            self.app.push_screen(AddInputDeviceModal(
                available_types=available_types,
                available_buses=available_buses
            ), add_input_callback)

        elif event.button.id == "remove-input-btn":
            if self.selected_input_device:
                message = f"Are you sure you want to remove the {self.selected_input_device['type']} on bus {self.selected_input_device['bus']}?"
                def on_confirm(confirmed: bool) -> None:
                    if confirmed:
                        try:
                            remove_vm_input(self.domain, self.selected_input_device['type'], self.selected_input_device['bus'])
                            self._invalidate_cache()
                            self.app.show_success_message("Input device removed successfully.")
                            self._update_input_table()
                        except (libvirt.libvirtError, ValueError) as e:
                            self.app.show_error_message(f"Error removing input device: {e}")
                self.app.push_screen(ConfirmationDialog(message), on_confirm)

        elif event.button.id == "add-virtiofs-btn":
            def add_virtiofs_callback(result):
                if result:
                    try:
                        # VM must be stopped to add virtiofs
                        if self.is_vm_active:
                            self.app.show_error_message("VM must be stopped to add VirtIO-FS mount.")
                            return
                        add_virtiofs(
                            self.domain,
                            result['source_path'],
                            result['target_path'],
                            result['readonly']
                        )
                        self._invalidate_cache()
                        self.app.show_success_message(f"VirtIO-FS mount '{result['target_path']}' added successfully.")
                        self._update_virtiofs_table()
                    except libvirt.libvirtError as e:
                        self.app.show_error_message(f"Error adding VirtIO-FS mount: {e}")
                    except Exception as e:
                        self.app.show_error_message(f"An unexpected error occurred: {e}")
            self.app.push_screen(AddEditVirtIOFSModal(is_edit=False), add_virtiofs_callback)

        elif event.button.id == "edit-network-interface-button":
            if self.selected_network_interface:
                interface_to_edit = next((net for net in self.vm_info['networks'] if net['mac'] == self.selected_network_interface), None)
                if interface_to_edit:
                    def edit_interface_callback(result):
                        if result:
                            new_network_name = result["network"]
                            new_model = result["model"]

                            original_network_name = interface_to_edit["network"]
                            original_model = interface_to_edit["model"]
                            original_mac = interface_to_edit["mac"]

                            if new_network_name == original_network_name and new_model == original_model:
                                self.app.show_success_message("No changes detected for network interface.")
                                return

                            message = (f"Are you sure you want to modify network interface\n'{original_mac}'\n"
                                       f"It will be removed and re-added, which may result\nin a NEW MAC ADDRESS.\n\n"
                                       f"Original: Network={original_network_name}, Model={original_model}\n"
                                       f"New: Network={new_network_name}, Model={new_model}")

                            def on_confirm_edit(confirmed: bool) -> None:
                                if confirmed:
                                    try:
                                        if self.is_vm_active:
                                            self.app.show_error_message("VM must be stopped to modify network interfaces.")
                                            return

                                        remove_network_interface(self.domain, original_mac)
                                        add_network_interface(self.domain, new_network_name, new_model)

                                        self._invalidate_cache()
                                        self.app.show_success_message(f"Network interface '{original_mac}' modified successfully. A new MAC address may have been assigned.")
                                        self._update_networks_table()
                                    except (libvirt.libvirtError, ValueError) as e:
                                        self.app.show_error_message(f"Error modifying network interface: {e}")
                                    except Exception as e:
                                        self.app.show_error_message(f"An unexpected error occurred: {e}")
                            self.app.push_screen(ConfirmationDialog(message), on_confirm_edit)

                    network_models = self.app.config.get('network_models', [])
                    self.app.push_screen(AddEditNetworkInterfaceModal(
                        is_edit=True,
                        networks=self.available_networks,
                        network_models=network_models,
                        interface_info=interface_to_edit
                    ), edit_interface_callback)
                else:
                    self.app.show_error_message("Could not retrieve information for the selected network interface.")

        elif event.button.id == "add-network-interface-button":
            def add_interface_callback(result):
                if result:
                    try:
                        add_network_interface(
                            self.domain,
                            result["network"],
                            result["model"]
                        )
                        self._invalidate_cache()
                        self.app.show_success_message("Network interface added successfully.")
                        self._update_networks_table()
                    except (libvirt.libvirtError, ValueError) as e:
                        self.app.show_error_message(f"Error adding network interface: {e}")
            network_models = self.app.config.get('network_models', [])
            self.app.push_screen(AddEditNetworkInterfaceModal(
                is_edit=False,
                networks=self.available_networks,
                network_models=network_models
            ), add_interface_callback)

        elif event.button.id == "remove-network-interface-button":
            if self.selected_network_interface:
                message = f"Are you sure you want to remove network interface:\n'{self.selected_network_interface}'?"
                def on_confirm(confirmed: bool) -> None:
                    if confirmed:
                        try:
                            remove_network_interface(self.domain, self.selected_network_interface)
                            self._invalidate_cache()
                            self.app.show_success_message(f"Network interface '{self.selected_network_interface}' removed successfully.")
                            self._update_networks_table()
                        except (libvirt.libvirtError, ValueError) as e:
                            self.app.show_error_message(f"Error removing network interface: {e}")
                self.app.push_screen(ConfirmationDialog(message), on_confirm)

        elif event.button.id == "edit-virtiofs-btn":
            if self.selected_virtiofs_info:
                current_source = self.selected_virtiofs_info.get('source', '')
                current_target = self.selected_virtiofs_info.get('target', '')
                current_readonly = self.selected_virtiofs_info.get('readonly', False)

                def edit_virtiofs_callback(result):
                    if result:
                        try:
                            # VM must be stopped to modify virtiofs
                            if self.is_vm_active:
                                self.app.show_error_message("VM must be stopped to modify VirtIO-FS mount.")
                                return

                            # Only proceed if there are actual changes
                            if (result['source_path'] != current_source or
                                result['target_path'] != current_target or
                                result['readonly'] != current_readonly):

                                # Remove the old one
                                remove_virtiofs(self.domain, current_target)
                                # Add the new one
                                add_virtiofs(
                                    self.domain,
                                    result['source_path'],
                                    result['target_path'],
                                    result['readonly']
                                )
                                self._invalidate_cache()
                                self.app.show_success_message(f"VirtIO-FS mount '{current_target}' updated to '{result['target_path']}'.")
                                self._update_virtiofs_table()
                            else:
                                self.app.show_success_message("No changes detected for VirtIO-FS mount.")

                        except libvirt.libvirtError as e:
                            self.app.show_error_message(f"Error editing VirtIO-FS mount: {e}")
                        except Exception as e:
                            self.app.show_error_message(f"An unexpected error occurred: {e}")

                self.app.push_screen(AddEditVirtIOFSModal(
                    source_path=current_source,
                    target_path=current_target,
                    readonly=current_readonly,
                    is_edit=True
                ), edit_virtiofs_callback)
            else:
                self.app.show_error_message("No VirtIO-FS mount selected for editing.")

        elif event.button.id == "delete-virtiofs-btn":
            if self.selected_virtiofs_target:
                message = f"Are you sure you want to delete VirtIO-FS mount:\n'{self.selected_virtiofs_target}'?\nVM must be stopped!"
                def on_confirm(confirmed: bool) -> None:
                    if confirmed:
                        try:
                            # VM must be stopped to delete virtiofs
                            if self.is_vm_active:
                                self.app.show_error_message("VM must be stopped to delete VirtIO-FS mount.")
                                return

                            remove_virtiofs(self.domain, self.selected_virtiofs_target)
                            self._invalidate_cache()
                            self.app.show_success_message(f"VirtIO-FS mount '{self.selected_virtiofs_target}' deleted successfully.")
                            self._update_virtiofs_table()
                        except libvirt.libvirtError as e:
                            self.app.show_error_message(f"Error deleting VirtIO-FS mount: {e}")
                        except Exception as e:
                            self.app.show_error_message(f"An unexpected error occurred: {e}")
                self.app.push_screen(ConfirmationDialog(message), on_confirm)

        elif event.button.id == "switch-to-bios":
            def on_confirm_bios_switch(confirmed: bool):
                if confirmed:
                    try:
                        set_uefi_file(self.domain, uefi_path=None, secure_boot=False)
                        self._invalidate_cache()
                        self.app.show_success_message("Switched to BIOS successfully. Please reopen the dialog to see changes.")
                        self.dismiss()
                    except (libvirt.libvirtError, ValueError) as e:
                        self.app.show_error_message(f"Error switching to BIOS: {e}")

            self.app.push_screen(
                ConfirmationDialog("Are you sure you want to switch to BIOS? This may affect bootability."),
                on_confirm_bios_switch
            )

        elif event.button.id == "switch-to-uefi":
            all_uefi_files = get_uefi_files()
            xml_root = ET.fromstring(self.xml_desc)
            arch_elem = xml_root.find(".//os/type")
            arch = arch_elem.get('arch') if arch_elem is not None else 'x86_64'
            uefi_for_arch = [f for f in all_uefi_files if arch in f.architectures]
            
            if not uefi_for_arch:
                self.app.show_error_message(f"No UEFI firmware found for architecture '{arch}'.")
                return

            uefi_paths = [f.executable for f in uefi_for_arch]

            def on_uefi_file_selected(uefi_path: str | None):
                if uefi_path:
                    try:
                        set_uefi_file(self.domain, uefi_path=uefi_path, secure_boot=False)
                        self._invalidate_cache()
                        self.app.show_success_message("Switched to UEFI successfully. Please reopen the dialog to see changes.")
                        self.dismiss()
                    except (libvirt.libvirtError, ValueError) as e:
                        self.app.show_error_message(f"Error switching to UEFI: {e}")

            self.app.push_screen(
                SelectDiskModal(uefi_paths, "Select UEFI Firmware"),
                on_uefi_file_selected
            )

        elif event.button.id == "edit-machine-type":
            if not self.is_vm_stopped:
                self.app.show_error_message("VM must be stopped to change machine type.")
                return

            current_machine_type = self.vm_info['machine_type']
            try:
                # get_supported_machine_types expects a domain object
                supported_machine_types = get_supported_machine_types(self.conn, self.domain)
            except libvirt.libvirtError as e:
                self.app.show_error_message(f"Error getting supported machine types: {e}")
                return

            def on_machine_type_selected(new_machine_type: str | None):
                original_machine_type = self.vm_info['machine_type']

                # Check for i440fx to q35 migration case
                if original_machine_type.startswith("pc-i440fx") and new_machine_type.startswith("pc-q35"):
                    message = (f"Are you sure you want to change the machine type "
                               f"from '{current_machine_type}' to '{new_machine_type}'?\n\n"
                               "This operation is complex and may result in an unbootable VM.\n"
                               "It will also remove some device configurations (e.g. PCI/USB addresses, watchdog)."
                               "\n\nTHIS CANNOT BE UNDONE EASILY!")

                    def on_confirm_migration(confirmed: bool):
                        if confirmed:
                            def migrate_worker():
                                try:
                                    def log_callback(msg):
                                        self.app.call_from_thread(self.app.show_success_message, msg)

                                    migrate_vm_machine_type(self.domain, new_machine_type, log_callback=log_callback)
                                    # Since this is in a worker, we need to call invalidate on the main thread if the callback is not thread-safe,
                                    # but the callback is just a function. self.invalidate_cache_callback is usually bound to VMService method.
                                    # VMService methods are generally thread-safe for cache operations (dict operations are atomic in Python).
                                    # But let's wrap it in call_from_thread just in case.
                                    self.app.call_from_thread(self._invalidate_cache)
                                    self.app.call_from_thread(self.app.show_success_message, f"VM '{self.vm_name}' successfully migrated to machine type '{new_machine_type}'.")
                                    # Refresh VM info and close modal
                                    self.app.call_from_thread(self.dismiss)
                                except libvirt.libvirtError as e:
                                    self.app.call_from_thread(self.app.show_error_message, f"Libvirt error during machine type migration: {e}")
                                except Exception as e:
                                    self.app.call_from_thread(self.app.show_error_message, f"Unexpected error during machine type migration: {e}")
                            self.app.run_worker(migrate_worker, name=f"migrate_machine_type_{self.domain.UUIDString()}", thread=True)
                        else:
                            self.app.show_success_message("Machine type migration cancelled.")

                    self.app.push_screen(ConfirmationDialog(message), on_confirm_migration)
                elif new_machine_type == current_machine_type:
                    self.app.show_success_message("Machine type is already set to the selected value.")
                else: # Use existing set_machine_type for other changes
                    try:
                        set_machine_type(self.domain, new_machine_type)
                        self._invalidate_cache()
                        self.app.show_success_message(f"Machine type set to {new_machine_type}")
                        self.vm_info['machine_type'] = new_machine_type
                        self.query_one("#machine-type-label").update(f"Machine Type: {new_machine_type}")
                        self.xml_desc = self.domain.XMLDesc(0) # Refresh XML
                    except (libvirt.libvirtError, ValueError, Exception) as e:
                        self.app.show_error_message(f"Error setting machine type: {e}")

            self.app.push_screen(SelectMachineTypeModal(supported_machine_types, current_machine_type), on_machine_type_selected)

        elif event.button.id == "detail_add_disk":
            def add_disk_callback(result):
                if result:
                    try:
                        target_dev = add_disk(
                            self.domain,
                            result["disk_path"],
                            device_type=result["device_type"],
                            bus=result["bus"],
                            create=result["create"],
                            size_gb=result["size_gb"],
                            disk_format=result["disk_format"],
                        )
                        self._invalidate_cache()
                        self.app.show_success_message(f"Disk added as {target_dev}")
                        self._update_disk_list()
                    except Exception as e:
                        self.app.show_error_message(f"Error adding disk: {e}")
            self.app.push_screen(AddDiskModal(), add_disk_callback)
        elif event.button.id == "detail_attach_disk":
            all_pools = storage_manager.list_storage_pools(self.conn)
            active_pools = [p for p in all_pools if p['status'] == 'active']

            if not active_pools:
                self.app.show_error_message("No active storage pools found.")
                return

            def select_pool_callback(pool_name: str | None) -> None:
                if not pool_name:
                    return

                selected_pool_obj = next((p['pool'] for p in active_pools if p['name'] == pool_name), None)
                if not selected_pool_obj:
                    self.app.show_error_message(f"Could not find pool object for {pool_name}")
                    return

                all_volumes_in_pool = storage_manager.list_storage_volumes(selected_pool_obj)
                all_volume_paths = [vol['volume'].path() for vol in all_volumes_in_pool]

                if not all_volume_paths:
                    self.app.show_error_message(f"No volumes found in pool '{pool_name}'.")
                    return

                def attach_disk_callback(disk_to_attach: str | None) -> None:
                    if disk_to_attach:
                        try:
                            target_dev = add_disk(
                                self.domain,
                                disk_to_attach,
                                device_type="disk",
                            )
                            self._invalidate_cache()
                            self.app.show_success_message(f"Disk added as {target_dev}")
                            self._update_disk_list()
                        except Exception as e:
                            self.app.show_error_message(f"Error attaching disk: {e}")

                self.app.push_screen(
                    SelectDiskModal(all_volume_paths, f"Select a disk to attach from pool '{pool_name}'"),
                    attach_disk_callback
                )

            self.app.push_screen(
                SelectPoolModal([p['name'] for p in active_pools], "Select a storage pool"),
                select_pool_callback
            )

        elif event.button.id == "add-usb2-controller-btn":
            try:
                add_usb_device(self.domain, 'usb', 'usb2')
                self._invalidate_cache()
                self.app.show_success_message("USB 2.0 controller added successfully.")
                self._update_controller_table()
            except (libvirt.libvirtError, ValueError) as e:
                self.app.show_error_message(f"Error adding USB 2.0 controller: {e}")
        
        elif event.button.id == "add-usb3-controller-btn":
            try:
                add_usb_device(self.domain, 'usb', 'usb3')
                self._invalidate_cache()
                self.app.show_success_message("USB 3.0 controller added successfully.")
                self._update_controller_table()
            except (libvirt.libvirtError, ValueError) as e:
                self.app.show_error_message(f"Error adding USB 3.0 controller: {e}")

        elif event.button.id == "add-scsi-controller-btn":
            try:
                add_scsi_controller(self.domain, 'virtio-scsi')
                self._invalidate_cache()
                self.app.show_success_message("SCSI controller added successfully.")
                self._update_controller_table()
            except (libvirt.libvirtError, ValueError) as e:
                self.app.show_error_message(f"Error adding SCSI controller: {e}")
        
        elif event.button.id == "remove-controller-btn":
            if self.selected_controller:
                message = f"Are you sure you want to remove the {self.selected_controller['type']} controller (model: {self.selected_controller['model']})?"
                def on_confirm(confirmed: bool) -> None:
                    if confirmed:
                        try:
                            if self.selected_controller['type'] == 'USB':
                                usb_model_arg = 'usb2' if 'uhci' in self.selected_controller['model'] else 'usb3'
                                remove_usb_device(
                                    self.domain,
                                    usb_model_arg,
                                    self.selected_controller['index']
                                )
                            elif self.selected_controller['type'] == 'SCSI':
                                remove_scsi_controller(
                                    self.domain,
                                    self.selected_controller['model'],
                                    self.selected_controller['index']
                                )
                            
                            self._invalidate_cache()
                            self.app.show_success_message("Controller removed successfully.")
                            self._update_controller_table()
                        except (libvirt.libvirtError, ValueError) as e:
                            self.app.show_error_message(f"Error removing controller: {e}")
                self.app.push_screen(ConfirmationDialog(message), on_confirm)

        elif event.button.id == "detail_remove_disk":
            highlighted_index = self.query_one("#disks-table").cursor_row
            if highlighted_index is None:
                self.app.show_error_message("No disk selected.")
                return

            disks_info = self.vm_info.get("disks", [])
            if highlighted_index >= len(disks_info):
                self.app.show_error_message("Invalid selection.")
                return

            disk_to_remove = disks_info[highlighted_index]
            if disk_to_remove['status'] != 'enabled':
                self.app.show_error_message("Can only remove enabled disks.")
                return

            disk_path = disk_to_remove['path']

            def on_confirm(confirmed: bool):
                if confirmed:
                    try:
                        remove_disk(self.domain, disk_path)
                        self._invalidate_cache()
                        self.app.show_success_message(f"Disk {disk_path} removed.")
                        self._update_disk_list()
                    except Exception as e:
                        self.app.show_error_message(f"Error removing disk: {e}")

            self.app.push_screen(ConfirmationDialog(f"Are you sure you want to remove disk:\n{disk_path}"), on_confirm)

        elif event.button.id == "detail_disable_disk":
            highlighted_index = self.query_one("#disks-table").cursor_row
            if highlighted_index is None:
                self.app.show_error_message("No disk selected.")
                return

            disks_info = self.vm_info.get("disks", [])
            if highlighted_index >= len(disks_info):
                self.app.show_error_message("Invalid selection.")
                return

            disk_to_disable = disks_info[highlighted_index]
            if disk_to_disable['status'] != 'enabled':
                self.app.show_error_message("Can only disable enabled disks.")
                return

            disk_path = disk_to_disable['path']

            def on_confirm(confirmed: bool):
                if confirmed:
                    try:
                        disable_disk(self.domain, disk_path)
                        self._invalidate_cache()
                        self.app.show_success_message(f"Disk {disk_path} disabled.")
                        self._update_disk_list()
                    except (libvirt.libvirtError, ValueError, Exception) as e:
                        self.app.show_error_message(f"Error disabling disk: {e}")

            self.app.push_screen(ConfirmationDialog(f"Are you sure you want to disable disk:\n{disk_path}"), on_confirm)

        elif event.button.id == "detail_enable_disk":
            highlighted_index = self.query_one("#disks-table").cursor_row
            if highlighted_index is None:
                self.app.show_error_message("No disk selected.")
                return

            disks_info = self.vm_info.get("disks", [])
            if highlighted_index >= len(disks_info):
                self.app.show_error_message("Invalid selection.")
                return

            disk_to_enable = disks_info[highlighted_index]
            if disk_to_enable['status'] != 'disabled':
                self.app.show_error_message("Can only enable disabled disks.")
                return

            disk_path = disk_to_enable['path']

            def on_confirm(confirmed: bool):
                if confirmed:
                    try:
                        enable_disk(self.domain, disk_path)
                        self._invalidate_cache()
                        self.app.show_success_message(f"Disk {disk_path} enabled.")
                        self._update_disk_list()
                    except (libvirt.libvirtError, ValueError, Exception) as e:
                        self.app.show_error_message(f"Error enabling disk: {e}")

            self.app.push_screen(ConfirmationDialog(f"Are you sure you want to enable disk:\n{disk_path}?"), on_confirm)

        elif event.button.id == "detail_edit_disk":
            highlighted_index = self.query_one("#disks-table").cursor_row
            if highlighted_index is None:
                self.app.show_error_message("No disk selected for editing.")
                return

            # Retrieve the disk details from the vm_info dictionary
            disks_info = self.vm_info.get("disks", [])
            if highlighted_index >= len(disks_info):
                self.app.show_error_message("Invalid disk selection.")
                return

            selected_disk = disks_info[highlighted_index]
    
            def edit_disk_callback(result):
                if result:
                    new_cache_mode = result.get('cache')
                    new_discard_mode = result.get('discard')
                    new_bus = result.get('bus')

                    if new_cache_mode == selected_disk.get('cache_mode') and new_discard_mode == selected_disk.get('discard_mode') and new_bus == selected_disk.get('bus'):
                        self.app.show_success_message("No changes detected for disk properties.")
                        return

                    try:
                        # VM must be stopped to edit disk properties
                        if not self.is_vm_stopped:
                            self.app.show_error_message("VM must be stopped to edit disk properties.")
                            return

                        disk_properties = {
                            'cache': new_cache_mode,
                            'discard': new_discard_mode,
                            'bus': new_bus
                        }
                        set_disk_properties(
                            self.domain,
                            selected_disk.get('path'),
                            properties=disk_properties
                        )
                        self._invalidate_cache()
                        self.app.show_success_message(f"Disk {os.path.basename(selected_disk.get('path'))} properties updated.")
                        self._update_disk_list() # Refresh the disk list in the UI
                    except libvirt.libvirtError as e:
                        self.app.show_error_message(f"Error editing disk properties: {e}")
                    except Exception as e:
                        self.app.show_error_message(f"An unexpected error occurred: {e}")

            self.app.push_screen(
                EditDiskModal(
                    disk_info=selected_disk, # Pass the entire selected_disk dictionary
                    is_stopped=self.is_vm_stopped # Pass the is_stopped boolean
                ),
                edit_disk_callback
            )

        elif event.button.id == "edit-cpu":
            def edit_cpu_callback(new_cpu_count):
                if new_cpu_count is not None and new_cpu_count.isdigit():
                    try:
                        set_vcpu(self.domain, int(new_cpu_count))
                        self._invalidate_cache()
                        self.app.show_success_message(f"CPU count set to {new_cpu_count}")
                        self.query_one("#cpu-label").update(f"CPU: {new_cpu_count}")
                        self.vm_info['cpu'] = int(new_cpu_count)
                    except (libvirt.libvirtError, Exception) as e:
                        self.app.show_error_message(f"Error setting CPU: {e}")

            self.app.push_screen(EditCpuModal(current_cpu=str(self.vm_info.get('cpu', ''))), edit_cpu_callback)

        elif event.button.id == "edit-memory":
            def edit_memory_callback(new_memory_size):
                if new_memory_size is not None and new_memory_size.isdigit():
                    try:
                        set_memory(self.domain, int(new_memory_size))
                        self._invalidate_cache()
                        self.app.show_success_message(f"Memory size set to {new_memory_size} MB")
                        self.query_one("#memory-label").update(f"Memory: {new_memory_size} MB")
                        self.vm_info['memory'] = int(new_memory_size)
                    except (libvirt.libvirtError, Exception) as e:
                        self.app.show_error_message(f"Error setting memory: {e}")

            self.app.push_screen(EditMemoryModal(current_memory=str(self.vm_info.get('memory', ''))), edit_memory_callback)

        elif event.button.id == "add-serial-btn":
            try:
                add_serial_console(self.domain)
                self._invalidate_cache()
                self.app.show_success_message("Serial console added successfully.")
                self.xml_desc = self.domain.XMLDesc(0)
                self._populate_serial_table()
            except (libvirt.libvirtError, ValueError) as e:
                self.app.show_error_message(f"Error adding serial console: {e}")

        elif event.button.id == "remove-serial-btn":
            if self.selected_serial_port:
                def on_confirm_remove(confirmed: bool):
                    if confirmed:
                        try:
                            remove_serial_console(self.domain, self.selected_serial_port)
                            self._invalidate_cache()
                            self.app.show_success_message("Serial console removed successfully.")
                            self.xml_desc = self.domain.XMLDesc(0)
                            self._populate_serial_table()
                        except (libvirt.libvirtError, ValueError) as e:
                            self.app.show_error_message(f"Error removing serial console: {e}")

                self.app.push_screen(
                    ConfirmationDialog(f"Are you sure you want to remove console on port {self.selected_serial_port}?"),
                    on_confirm_remove
                )

    def action_close_modal(self) -> None:
        """Close the modal."""
        self.dismiss()
