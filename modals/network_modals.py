"""
Network Hypervisor and guest side
"""
import ipaddress
from textual.app import ComposeResult
from textual.widgets import Button, Input, Label, RadioSet, RadioButton, Checkbox, Select, TextArea
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual import on

from modals.base_modals import BaseModal, BaseDialog
from network_manager import (
    create_network, get_host_network_interfaces, get_existing_subnets
)

class AddEditNetworkInterfaceModal(BaseDialog[dict | None]):
    """A dialog to add or edit a VM's network interface."""

    def __init__(self, is_edit: bool, networks: list[str], interface_info: dict | None = None) -> None:
        super().__init__()
        self.is_edit = is_edit
        self.interface_info = interface_info
        self.networks = networks
        self.models = ["virtio", "e1000", "e1000e", "rtl8139", "ne2k_pci", "pcnet"]

    def compose(self):
        network_options = [(str(net), str(net)) for net in self.networks]
        model_options = [(model, model) for model in self.models]

        network_value = None
        model_value = "virtio"
        mac_value = ""

        if self.is_edit and self.interface_info:
            network_value = self.interface_info.get("network")
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

            if self.is_edit:
                yield Input(value=mac_value, id="mac-input", disabled=True)

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
    """Modal screen for creating a new network."""

    def __init__(self, conn) -> None:
        super().__init__()
        self.conn = conn

    def compose(self) -> ComposeResult:
        with Vertical(id="create-network-dialog"):
            yield Label("Create New Network", id="create-network-title")

            with ScrollableContainer():
                with Vertical(id="create-network-form"):
                    yield Input(placeholder="Network Name (e.g., nat_net)", id="net-name-input")
                    with RadioSet(id="type-network", classes="type-network-radioset"):
                        yield RadioButton("Nat network", id="type-network-nat", value=True)
                        yield RadioButton("Routed network", id="type-network-routed")
                    yield Select([("Loading...", "")], prompt="Select Forward Interface", id="net-forward-input", classes="net-forward-input", disabled=True)
                    yield Input(placeholder="IPv4 Network (e.g., 192.168.100.0/24)", id="net-ip-input", value="192.168.11.0/24")
                    yield Checkbox("Enable DHCPv4", id="dhcp-checkbox", value=True)
                    with Vertical(id="dhcp-inputs-horizontal"):
                        with Horizontal(id="dhcp-options"):
                            yield Input(placeholder="DHCP Start (e.g., 192.168.100.100)", id="dhcp-start-input", classes="dhcp-input", value="192.168.11.10")
                            yield Input(placeholder="DHCP End (e.g., 192.168.100.254)", id="dhcp-end-input", classes="dhcp-input", value="192.168.11.30")
                    with RadioSet(id="dns-domain-radioset", classes="dns-domain-radioset"):
                        yield RadioButton("Use Network Name for DNS Domain", id="dns-use-net-name", value=True)
                        yield RadioButton("Use Custom DNS Domain", id="dns-use-custom")
                    yield Input(placeholder="Custom DNS Domain", id="dns-custom-domain-input", classes="hidden")
                    with Vertical(id="network-create-close-horizontal"):
                        with Horizontal(id="dhcp-options"):
                            yield Button("Create Network", variant="primary", id="create-net-btn", classes="create-net-btn")
            yield Button("Close", variant="default", id="close-btn", classes="close-button")

    def on_mount(self) -> None:
        """Called when the modal is mounted to populate network interfaces."""
        self.run_worker(self.populate_interfaces, thread=True)

    def populate_interfaces(self) -> None:
        """Worker to fetch host network interfaces."""
        try:
            host_interfaces = get_host_network_interfaces()
            options = [ (f"{name} ({ip})" if ip else name, name) for name, ip in host_interfaces]
            if not options:
                options = [("No interfaces found", "")]

            select = self.query_one("#net-forward-input", Select)

            def update_select():
                select.set_options(options)
                select.disabled = False
                select.prompt = "Select Forward Interface"

            self.app.call_from_thread(update_select)
        except Exception as e:
            self.app.call_from_thread(
                self.app.show_error_message, 
                f"Error getting host interfaces: {e}"
            )

    @on(Checkbox.Changed, "#dhcp-checkbox")
    def on_dhcp_checkbox_changed(self, event: Checkbox.Changed) -> None:
        dhcp = self.query_one("#dhcp-checkbox", Checkbox).value
        dhcp_options = self.query_one("#dhcp-options")
        if dhcp:
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
            if typenet_id == "type-network-nat":
                typenet = "nat"
            elif typenet_id == "type-network-routed":
                typenet = "route"
            else:
                self.app.show_error_message(f"Unknown network type: {typenet_id}")
                return
            forward_select = self.query_one("#net-forward-input", Select)
            forward = forward_select.value
            ip = self.query_one("#net-ip-input", Input).value
            dhcp = self.query_one("#dhcp-checkbox", Checkbox).value
            dhcp_start = self.query_one("#dhcp-start-input", Input).value
            dhcp_end = self.query_one("#dhcp-end-input", Input).value

            domain_radio = self.query_one("#dns-domain-radioset", RadioSet).pressed_button.id
            domain_name = name
            if domain_radio == "dns-use-custom":
                domain_name = self.query_one("#dns-custom-domain-input", Input).value

            try:
                ip_network = ipaddress.ip_network(ip, strict=False)
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

            def do_create_network():
                try:
                    existing_subnets = get_existing_subnets(self.conn)
                    for existing_subnet in existing_subnets:
                        if ip_network.overlaps(existing_subnet):
                            self.app.call_from_thread(
                                self.app.show_error_message,
                                f"Subnet {ip_network} overlaps with existing network's subnet {existing_subnet}."
                            )
                            return

                    create_network(self.conn, name, typenet, forward, ip, dhcp, dhcp_start, dhcp_end, domain_name)

                    self.app.call_from_thread(
                        self.app.show_success_message,
                        f"Network {name} created successfully."
                    )
                    self.app.call_from_thread(self.dismiss, True)
                except Exception as e:
                    self.app.call_from_thread(self.app.show_error_message, f"Error creating network: {e}")

            self.app.run_worker(do_create_network, thread=True)

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
                text_area = TextArea(self.network_xml, language="xml", read_only=True)
                text_area.styles.height = "auto"
                yield text_area
            with Horizontal():
                yield Button("Close", variant="default", id="close-btn", classes="close-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-btn":
            self.dismiss(None)
