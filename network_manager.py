"""
Module for managing network-related operations for virtual machines.
"""
import os
import subprocess
import secrets
import libvirt
import xml.etree.ElementTree as ET
import ipaddress
from utils import log_function_call


@log_function_call
def list_networks(conn):
    """
    Lists all networks.
    """
    if not conn:
        return []

    networks = []
    for net in conn.listAllNetworks():
        xml_desc = net.XMLDesc(0)
        root = ET.fromstring(xml_desc)

        forward_elem = root.find('forward')
        mode = forward_elem.get('mode') if forward_elem is not None else 'isolated'

        networks.append({
            'name': net.name(),
            'mode': mode,
            'active': net.isActive(),
            'autostart': net.autostart(),
        })
    return networks

@log_function_call
def create_network(conn, name, typenet, forward_dev, ip_network, dhcp_enabled, dhcp_start, dhcp_end, domain_name):
    """
    Creates a new NAT/Routed network.
    """
    if not conn:
        raise ValueError("Invalid libvirt connection.")

    net = ipaddress.ip_network(ip_network)
    generated_mac = generate_mac_address()

    nat_xml = ""
    if typenet == "nat":
        nat_xml = """
    <nat>
      <port start='1024' end='65535'/>
    </nat>"""
    xml_forward_dev = ""
    if forward_dev:
        xml_forward_dev = f"dev='{forward_dev}'"

    xml = f"""
<network>
  <name>{name}</name>
  <forward mode='{typenet}' {xml_forward_dev}>{nat_xml}
  </forward>
  <bridge name='{name}' stp='on' delay='0'/>
  <mac address='{generated_mac}'/>
  <domain name='{domain_name}'/>
  <ip address='{net.network_address + 1}' netmask='{net.netmask}'>
"""
    if dhcp_enabled:
        xml += f"""
    <dhcp>
      <range start='{dhcp_start}' end='{dhcp_end}'/>
    </dhcp>
"""
    xml += """
  </ip>
</network>
"""

    net = conn.networkDefineXML(xml)
    net.create()
    net.setAutostart(True)

@log_function_call
def delete_network(conn, network_name):
    """
    Deletes a network.
    """
    if not conn:
        raise ValueError("Invalid libvirt connection.")

    try:
        net = conn.networkLookupByName(network_name)
        if net.isActive():
            net.destroy()
        net.undefine()
    except libvirt.libvirtError as e:
        raise Exception(f"Error deleting network '{network_name}': {e}")


@log_function_call
def get_vms_using_network(conn, network_name):
    """
    Get a list of VMs using a specific network.
    """
    if not conn:
        return []

    vm_names = []
    domains = conn.listAllDomains(0)
    if domains:
        for domain in domains:
            xml_desc = domain.XMLDesc(0)
            root = ET.fromstring(xml_desc)
            for iface in root.findall(".//devices/interface[@type='network']"):
                source = iface.find("source")
                if source is not None and source.get("network") == network_name:
                    vm_names.append(domain.name())
                    break
    return vm_names

@log_function_call
def set_network_active(conn, network_name, active):
    """
    Sets a network to active or inactive.
    """
    if not conn:
        raise ValueError("Invalid libvirt connection.")
    try:
        net = conn.networkLookupByName(network_name)
        if active:
            net.create()
        else:
            net.destroy()
    except libvirt.libvirtError as e:
        raise Exception(f"Error setting network active status: {e}")

@log_function_call
def set_network_autostart(conn, network_name, autostart):
    """
    Sets a network to autostart or not.
    """
    if not conn:
        raise ValueError("Invalid libvirt connection.")
    try:
        net = conn.networkLookupByName(network_name)
        net.setAutostart(autostart)
    except libvirt.libvirtError as e:
        raise Exception(f"Error setting network autostart status: {e}")


@log_function_call
def get_host_network_interfaces():
    """
    Retrieves a list of network interface names and their primary IPv4 addresses available on the host.
    Returns a list of tuples: (interface_name, ip_address)
    """
    try:
        result = subprocess.run(
            ['ip', '-o', 'link', 'show'],
            capture_output=True,
            text=True,
            check=True
        )
        interfaces = []
        for line in result.stdout.splitlines():
            parts = line.split(': ')
            if len(parts) > 1:
                interface_name = parts[1].split('@')[0]
                if interface_name != 'lo':
                    ip_address = ""
                    # Get IPv4 address for the interface
                    ip_result = subprocess.run(
                        ['ip', '-o', '-4', 'addr', 'show', interface_name],
                        capture_output=True,
                        text=True,
                        check=False # Do not raise error if interface has no IP
                    )
                    if ip_result.returncode == 0:
                        ip_parts = ip_result.stdout.split()
                        if len(ip_parts) > 3:
                            ip_address = ip_parts[3].split('/')[0] # Extract IP before the /

                    interfaces.append((interface_name, ip_address))
        return interfaces
    except subprocess.CalledProcessError as e:
        print(f"Error getting network interfaces: {e}")
        return []
    except FileNotFoundError:
        print("Error: 'ip' command not found. Please ensure iproute2 is installed.")
        return []

@log_function_call
def generate_mac_address():
    """Generates a random MAC address."""
    mac = [ 0x52, 0x54, 0x00,
            secrets.randbelow(0x7f),
            secrets.randbelow(0xff),
            secrets.randbelow(0xff) ]
    return ':'.join(map(lambda x: "%02x" % x, mac))

@log_function_call
def get_existing_subnets(conn: libvirt.virConnect) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """
    Returns a list of all IP subnets currently configured for libvirt networks.
    """
    subnets = []
    for net in conn.listAllNetworks():
        try:
            xml_desc = net.XMLDesc(0)
            root = ET.fromstring(xml_desc)
            ip_elements = root.findall(".//ip")
            for ip_elem in ip_elements:
                ip_addr = ip_elem.get("address")
                netmask = ip_elem.get("netmask")
                prefix = ip_elem.get("prefix")
                if ip_addr:
                    if netmask:
                        subnet_str = f"{ip_addr}/{netmask}"
                        try:
                            # ipaddress can handle netmask just fine
                            subnet = ipaddress.ip_network(subnet_str, strict=False)
                            subnets.append(subnet)
                        except ValueError:
                            pass # Ignore invalid configurations
                    elif prefix:
                        subnet_str = f"{ip_addr}/{prefix}"
                        try:
                            subnet = ipaddress.ip_network(subnet_str, strict=False)
                            subnets.append(subnet)
                        except ValueError:
                            pass # Ignore invalid configurations
        except libvirt.libvirtError:
            continue # Ignore networks we can't get XML for
    return subnets