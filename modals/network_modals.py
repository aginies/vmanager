"""
Network Hypervisor side
"""
import ipaddress
from textual.app import ComposeResult
from textual.widgets import Button, Input, Label, RadioSet, RadioButton, Checkbox, Select, TextArea
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual import on

from modals.base_modals import BaseModal
from network_manager import (
    create_network, get_host_network_interfaces, get_existing_subnets
)

class CreateNetworkModal(BaseModal[None]):
    """Modal screen for creating a new network."""

    def compose(self) -> ComposeResult:
        with Vertical(id="create-network-dialog"):
            yield Label("Create New Network", id="create-network-title")

            host_interfaces = get_host_network_interfaces()
            if not host_interfaces:
                host_interfaces = [("No interfaces found", "")]
            interface_options = []
            for name, ip in host_interfaces:
                display_text = f"{name} ({ip})" if ip else name
                interface_options.append((display_text, name))

            with ScrollableContainer():
                with Vertical(id="create-network-form"):
                    yield Input(placeholder="Network Name (e.g., nat_net)", id="net-name-input")
                    with RadioSet(id="type-network", classes="type-network-radioset"):
                        yield RadioButton("Nat network", id="type-network-nat", value=True)
                        yield RadioButton("Routed network", id="type-network-routed")
                    yield Select(interface_options, prompt="Select Forward Interface", id="net-forward-input", classes="net-forward-input")
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
                # Validate network address
                ip_network = ipaddress.ip_network(ip, strict=False)

                # Check for subnet overlap
                existing_subnets = get_existing_subnets(self.app.conn)
                for existing_subnet in existing_subnets:
                    if ip_network.overlaps(existing_subnet):
                        self.app.show_error_message(f"Subnet {ip_network} overlaps with existing network's subnet {existing_subnet}.")
                        return

                if dhcp:
                    # Validate DHCP start and end IPs
                    dhcp_start_ip = ipaddress.ip_address(dhcp_start)
                    dhcp_end_ip = ipaddress.ip_address(dhcp_end)

                    # Check if DHCP IPs are within the network
                    if dhcp_start_ip not in ip_network:
                        self.app.show_error_message(f"DHCP start IP {dhcp_start_ip} is not in the network {ip_network}")
                        return
                    if dhcp_end_ip not in ip_network:
                        self.app.show_error_message(f"DHCP end IP {dhcp_end_ip} is not in the network {ip_network}")
                        return
                    if dhcp_start_ip >= dhcp_end_ip:
                        self.app.show_error_message("DHCP start IP must be before the end IP.")
                        return

            except ValueError as e:
                self.app.show_error_message(f"Invalid IP address or network: {e}")
                return

            try:
                create_network(self.app.conn, name, typenet, forward, ip, dhcp, dhcp_start, dhcp_end, domain_name)
                self.app.show_success_message(f"Network {name} created successfully.")
                self.dismiss(True) # True to indicate success
            except Exception as e:
                self.app.show_error_message(f"Error creating network: {e}")

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
