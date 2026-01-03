"""
Network Hypervisor and guest side
"""
import ipaddress
from textual.app import ComposeResult
from textual.widgets import Button, Input, Label, RadioSet, RadioButton, Checkbox, Select, TextArea
from textual.widgets.text_area import LanguageDoesNotExist
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual import on

from modals.base_modals import BaseModal, BaseDialog
from network_manager import (
    create_network, get_host_network_interfaces, get_existing_subnets
)

class AddEditNetworkInterfaceModal(BaseDialog[dict | None]):
    """A dialog to add or edit a VM's network interface."""

    def __init__(self, is_edit: bool, networks: list[str], network_models: list[str], interface_info: dict | None = None) -> None:
        super().__init__()
        self.is_edit = is_edit
        self.interface_info = interface_info
        self.networks = networks
        self.models = network_models if network_models else ["virtio", "e1000", "e1000e", "rtl8139", "ne2k_pci", "pcnet"]

    def compose(self):
        network_options = [(str(net), str(net)) for net in self.networks]
        model_options = [(model, model) for model in self.models]

        network_value = None
        model_value = "virtio"
        mac_value = "52:54:00:" if not self.is_edit else ""

        if self.is_edit and self.interface_info:
            network_value = self.interface_info.get("network")
            if network_value not in self.networks:
                self.app.show_error_message(f"Network '{network_value}' not found. Please select an available network.")
                network_value = self.networks[0] if self.networks else None # Set to first available network if any, otherwise None
            model_value = self.interface_info.get("model", "virtio")
            mac_value = self.interface_info.get("mac", "")
        elif not self.is_edit and self.networks:
            network_value = self.networks[0]

        with Vertical(id="add-edit-network-dialog"):
            yield Label("Select network and model")

            if self.networks:
                yield Select(network_options, id="network-select", prompt="Select a network", value=network_value)
            else:
                yield Select([], id="network-select", disabled=True, prompt="No networks available")

            yield Select(model_options, id="model-select", value=model_value)
            # Add Input for MAC address, enabled for both add and edit
            yield Input(
                placeholder="MAC Address (e.g., 52:54:00:xx:xx:xx)",
                id="mac-input",
                value=mac_value,
                disabled=False # Always enabled so user can edit or set
            )

            with Horizontal(id="dialog-buttons"):
                yield Button("Save" if self.is_edit else "Add", variant="success", id="save")
                yield Button("Cancel", variant="error", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            network_select = self.query_one("#network-select", Select)
            model_select = self.query_one("#model-select", Select)

            new_network = network_select.value
            new_model = model_select.value

            if new_network is Select.BLANK:
                self.app.show_error_message("Please select a network.")
                return

            result = {"network": new_network, "model": new_model}
            if self.is_edit:
                result["mac"] = self.query_one("#mac-input", Input).value

            self.dismiss(result)
        else:
            self.dismiss(None)

class AddEditNetworkModal(BaseModal[None]):
    """Modal screen for creating or editing a network."""

    def __init__(self, conn, network_info: dict | None = None) -> None:
        super().__init__()
        self.conn = conn
        self.network_info = network_info
        self.is_edit = network_info is not None

    def compose(self) -> ComposeResult:
        title = "Edit Network" if self.is_edit else "Create New Network"
        button_label = "Save Changes" if self.is_edit else "Create Network"

        name_val = ""
        forward_mode = "nat"
        forward_dev = None
        ip_val = ""
        dhcp_val = False
        dhcp_start_val = ""
        dhcp_end_val = ""
        domain_name = ""
        use_custom_domain = False

        if self.is_edit and self.network_info:
            name_val = self.network_info.get("name", "")
            forward_mode = self.network_info.get("forward_mode", "nat")
            forward_dev = self.network_info.get("forward_dev")

            ip_address = self.network_info.get("ip_address")
            if ip_address:
                prefix = self.network_info.get("prefix")
                netmask = self.network_info.get("netmask")
                if prefix:
                    ip_val = f"{ip_address}/{prefix}"
                elif netmask:
                    try:
                        prefix_len = ipaddress.ip_network(f"0.0.0.0/{netmask}").prefixlen
                        ip_val = f"{ip_address}/{prefix_len}"
                    except ValueError:
                        pass # Keep ip_val empty if netmask is invalid

            dhcp_val = self.network_info.get("dhcp", False)
            dhcp_start_val = self.network_info.get("dhcp_start", "")
            dhcp_end_val = self.network_info.get("dhcp_end", "")
            domain_name = self.network_info.get("domain_name", "")
            if domain_name and domain_name != name_val:
                use_custom_domain = True
        else: # For create mode
            ip_val = "192.168.11.0/24"
            dhcp_val = True
            dhcp_start_val = "192.168.11.10"
            dhcp_end_val = "192.168.11.30"



        with Vertical(id="create-network-dialog"):
            yield Label(title, id="create-network-title")

            with ScrollableContainer():
                with Vertical(id="create-network-form"):
                    yield Input(
                        placeholder="Network Name (e.g., nat_net)",
                        id="net-name-input",
                        value=name_val,
                        disabled=self.is_edit
                    )
                    with RadioSet(id="type-network", classes="type-network-radioset"):
                        yield RadioButton("Nat network", id="type-network-nat", value=(forward_mode == "nat"))
                        yield RadioButton("Routed network", id="type-network-routed", value=(forward_mode == "route"))
                    yield Select(
                        [("Loading...", "")],
                        prompt="Select Forward Interface",
                        id="net-forward-input",
                        classes="net-forward-input",
                        disabled=True
                    )
                    yield Input(
                        placeholder="IPv4 Network (e.g., 192.168.100.0/24)", id="net-ip-input", value=ip_val
                    )
                    yield Checkbox("Enable DHCPv4", id="dhcp-checkbox", value=dhcp_val)
                    with Vertical(id="dhcp-inputs-horizontal"):
                        dhcp_options_classes = "" if dhcp_val else "hidden"
                        with Horizontal(id="dhcp-options", classes=dhcp_options_classes):
                            yield Input(
                                placeholder="DHCP Start (e.192.168.100.100)",
                                id="dhcp-start-input",
                                classes="dhcp-input",
                                value=dhcp_start_val
                            )
                            yield Input(
                                placeholder="DHCP End (e.g., 192.168.100.254)",
                                id="dhcp-end-input",
                                classes="dhcp-input",
                                value=dhcp_end_val
                            )
                    with RadioSet(id="dns-domain-radioset", classes="dns-domain-radioset"):
                        yield RadioButton(
                            "Use Network Name for DNS Domain", id="dns-use-net-name", value=not use_custom_domain
                        )
                        yield RadioButton("Use Custom DNS Domain", id="dns-use-custom", value=use_custom_domain)

                    custom_domain_classes = "hidden" if not use_custom_domain else ""
                    yield Input(
                        placeholder="Custom DNS Domain",
                        id="dns-custom-domain-input",
                        value=domain_name,
                        classes=custom_domain_classes
                    )
                    with Vertical(id="network-create-close-horizontal"):
                        with Horizontal(classes="action-buttons"):
                            yield Button(
                                button_label, variant="primary", id="create-net-btn", classes="create-net-btn"
                            )
            yield Button("Close", variant="default", id="close-btn", classes="close-button")

    def on_mount(self) -> None:
        """Called when the modal is mounted to populate network interfaces."""
        self.run_worker(self.populate_interfaces, thread=True)

    def populate_interfaces(self) -> None:
        """Worker to fetch host network interfaces."""
        try:
            host_interfaces = get_host_network_interfaces()
            options = [(f"{name} ({ip})" if ip else name, name) for name, ip in host_interfaces]
            if not options:
                options = [("No interfaces found", "")]

            select = self.query_one("#net-forward-input", Select)

            def update_select():
                select.set_options(options)
                select.disabled = False
                select.prompt = "Select Forward Interface"
                if self.is_edit and self.network_info:
                    forward_dev = self.network_info.get("forward_dev")
                    if forward_dev is not None:
                        all_values = [value for _, value in options]
                        if forward_dev in all_values:
                            select.value = forward_dev
                        else:
                            select.clear()
                            self.app.show_error_message(
                                f"Warning: Forward device '{forward_dev}' not found on host."
                            )
                    else:
                        select.clear()

            self.app.call_from_thread(update_select)
        except Exception as e:
            self.app.call_from_thread(
                self.app.show_error_message,
                f"Error getting host interfaces: {e}"
            )

    @on(Checkbox.Changed, "#dhcp-checkbox")
    def on_dhcp_checkbox_changed(self, event: Checkbox.Changed) -> None:
        dhcp_options = self.query_one("#dhcp-options")
        if event.value:
            dhcp_options.remove_class("hidden")
        else:
            dhcp_options.add_class("hidden")

    @on(RadioSet.Changed, "#dns-domain-radioset")
    def on_dns_domain_radioset_changed(self, event: RadioSet.Changed) -> None:
        custom_domain_input = self.query_one("#dns-custom-domain-input")
        if event.pressed.id == "dns-use-custom":
            custom_domain_input.remove_class("hidden")
        else:
            custom_domain_input.add_class("hidden")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-btn":
            self.dismiss(None)
        elif event.button.id == "create-net-btn":
            name = self.query_one("#net-name-input", Input).value
            typenet_id = self.query_one("#type-network", RadioSet).pressed_button.id
            typenet = "nat" if typenet_id == "type-network-nat" else "route"
            forward_select = self.query_one("#net-forward-input", Select)
            forward = forward_select.value
            if forward is Select.BLANK:
                forward = None
            ip = self.query_one("#net-ip-input", Input).value
            dhcp = self.query_one("#dhcp-checkbox", Checkbox).value
            dhcp_start = self.query_one("#dhcp-start-input", Input).value
            dhcp_end = self.query_one("#dhcp-end-input", Input).value

            domain_radio = self.query_one("#dns-domain-radioset", RadioSet).pressed_button.id
            domain_name = self.query_one("#dns-custom-domain-input", Input).value if domain_radio == "dns-use-custom" else name

            if ip:
                try:
                    ip_network = ipaddress.ip_network(ip, strict=False)
                    ip = str(ip_network) # Use the canonical network address string
                    if dhcp:
                        dhcp_start_ip = ipaddress.ip_address(dhcp_start)
                        dhcp_end_ip = ipaddress.ip_address(dhcp_end)
                        if dhcp_start_ip not in ip_network or dhcp_end_ip not in ip_network:
                            self.app.show_error_message(f"DHCP IPs are not in the network {ip_network}")
                            return
                        if dhcp_start_ip >= dhcp_end_ip:
                            self.app.show_error_message("DHCP start IP must be before the end IP.")
                            return
                except ValueError as e:
                    self.app.show_error_message(f"Invalid IP address or network: {e}")
                    return
            elif dhcp:
                self.app.show_error_message("DHCP cannot be enabled without an IP network.")
                return

            def do_create_or_update_network():
                try:
                    original_network = None
                    if self.is_edit and self.network_info:
                        ip_address = self.network_info.get("ip_address")
                        if ip_address:
                            prefix = self.network_info.get("prefix")
                            netmask = self.network_info.get("netmask")
                            original_ip_val = None
                            if prefix:
                                original_ip_val = f"{ip_address}/{prefix}"
                            elif netmask:
                                try:
                                    prefix_len = ipaddress.ip_network(f"0.0.0.0/{netmask}").prefixlen
                                    original_ip_val = f"{ip_address}/{prefix_len}"
                                except ValueError:
                                    pass
                            if original_ip_val:
                                original_network = ipaddress.ip_network(original_ip_val, strict=False)

                    if ip:
                        ip_network = ipaddress.ip_network(ip, strict=False)
                        existing_subnets = get_existing_subnets(self.conn)
                        for existing_subnet in existing_subnets:
                            if self.is_edit and existing_subnet == original_network:
                                continue

                            if ip_network.overlaps(existing_subnet):
                                self.app.call_from_thread(
                                    self.app.show_error_message,
                                    f"Subnet {ip_network} overlaps with an existing network."
                                )
                                return

                    uuid = self.network_info.get('uuid') if self.is_edit and self.network_info else None
                    create_network(self.conn, name, typenet, forward, ip, dhcp, dhcp_start, dhcp_end, domain_name, uuid=uuid)

                    message = f"Network {name} {'updated' if self.is_edit else 'created'} successfully."
                    self.app.call_from_thread(self.app.show_success_message, message)
                    self.app.call_from_thread(self.dismiss, True)
                except Exception as e:
                    self.app.call_from_thread(
                        self.app.show_error_message,
                        f"Error {'updating' if self.is_edit else 'creating'} network: {e}"
                    )

            self.app.worker_manager.run(
                do_create_or_update_network, name=f"update_network_{name}"
            )

class NetworkXMLModal(BaseModal[None]):
    """Modal screen to show detailed network information."""

    def __init__(self, network_name: str, network_xml: str) -> None:
        super().__init__()
        self.network_name = network_name
        self.network_xml = network_xml

    def compose(self) -> ComposeResult:
        with Vertical(id="network-detail-dialog"):
            yield Label(f"Network Details: {self.network_name}", id="title")
            with ScrollableContainer():
                text_area = TextArea(self.network_xml, read_only=True)
                try:
                    text_area.language = "xml"
                except LanguageDoesNotExist:
                    text_area.language = None
                text_area.styles.height = "auto"
                yield text_area
            with Horizontal():
                yield Button("Close", variant="default", id="close-btn", classes="close-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-btn":
            self.dismiss(None)
