import libvirt
import xml.etree.ElementTree as ET
import os

def get_vm_info(connection_uri):
    """
    Récupère les informations sur les VMs à partir d'une URI de connexion.

    Args:
        connection_uri (str): URI de connexion à libvirt.

    Returns:
        list: Liste de dictionnaires contenant les informations des VMs.
    """
    conn = libvirt.open(connection_uri)
    if conn is None:
        print(f"Failed to open connection to {connection_uri}")
        return []

    vm_info_list = []
    domains = conn.listAllDomains(0)
    if domains is not None:
        for domain in domains:
            info = domain.info()
            xml_content = domain.XMLDesc(0)
            vm_info = {
                'name': domain.name(),
                'uuid': domain.UUIDString(),
                'status': get_status(domain),
                'description': get_vm_description(domain),
                'cpu': info[3],
                'memory': info[2] // 1024,  # Convert KiB to MiB
                'machine_type': get_vm_machine_info(xml_content),
                'firmware': get_vm_firmware_info(xml_content),
                'networks': get_vm_networks_info(xml_content),
                'disks': get_vm_disks_info(xml_content),
            }
            vm_info_list.append(vm_info)

    conn.close()
    return vm_info_list


def get_status(domain):
    """
    Détermine l'état d'une VM.

    Args:
        domain: Objet domaine libvirt.

    Returns:
        str: État de la VM.
    """
    state = domain.info()[0]
    if state == libvirt.VIR_DOMAIN_RUNNING:
        return 'Running'
    elif state == libvirt.VIR_DOMAIN_PAUSED:
        return 'Paused'
    else:
        return 'Stopped'


def get_vm_description(domain):
    """
    Récupère la description d'une VM.

    Args:
        domain: Objet domaine libvirt.

    Returns:
        str: Description de la VM.
    """
    try:
        return domain.metadata(libvirt.VIR_DOMAIN_METADATA_DESCRIPTION, None)
    except libvirt.libvirtError:
        return "No description available"

def get_vm_firmware_info(xml_content: str) -> str:
    """
    Extracts firmware (BIOS/UEFI) from a VM's XML definition.

    Args:
        xml_content (str): The VM's XML definition as a string.

    """
    firmware = "BIOS" # Default to BIOS

    try:
        root = ET.fromstring(xml_content)
        os_elem = root.find('os')

        # Determine firmware
        if os_elem is not None:
            loader_elem = os_elem.find('loader')
            if loader_elem is not None and loader_elem.get('type') == 'pflash':
                loader_path = loader_elem.text
                if loader_path:
                    firmware_basename = os.path.basename(loader_path)
                    firmware = f"UEFI {firmware_basename}"
            else:
                bootloader_elem = os_elem.find('bootloader')
                if bootloader_elem is not None:
                    firmware = "BIOS" # Explicitly BIOS if bootloader is present and no pflash loader

    except ET.ParseError:
        pass # Return default values if XML parsing fails

    return firmware

def get_vm_machine_info(xml_content: str) -> str:
    """
    Extracts machine type from a VM's XML definition.

    Args:
        xml_content (str): The VM's XML definition as a string.

    """
    machine_type = "N/A"

    try:
        root = ET.fromstring(xml_content)
        os_elem = root.find('os')

        # Get machine type from the 'machine' attribute of the 'type' element within 'os'
        if os_elem is not None:
            type_elem = os_elem.find('type')
            if type_elem is not None and 'machine' in type_elem.attrib:
                machine_type = type_elem.get('machine')

    except ET.ParseError:
        pass # Return default values if XML parsing fails

    return machine_type

def get_vm_networks_info(xml_content: str) -> str:
    networks = []
    try:
        from xml.etree import ElementTree as ET
        root = ET.fromstring(xml_content)
        devices = root.find("devices")
        if devices is not None:
            interface_elements = devices.findall("interface")
            for interface in interface_elements:
                # Get interface type
                interface_type = interface.get("type", "unknown")
                # Get source (bridge, network, etc.)
                source = interface.find("source")
                if source is not None:
                    if interface_type == "bridge":
                        bridge_name = source.get("bridge", "unknown")
                        networks.append(f"bridge: {bridge_name}")
                    elif interface_type == "network":
                        network_name = source.get("network", "unknown")
                        networks.append(f"network: {network_name}")
                    elif interface_type == "user":
                        networks.append("user: network")
                else:
                    networks.append(f"{interface_type}: unknown")
    except:
        pass  # Failed to get networks, continue without them

    return networks


def get_vm_disks_info(xml_content: str) ->str:
    """
    Récupère les informations sur les disques d'une VM.

    Args:
        domain: Objet domaine libvirt.

    Returns:
        list: Liste des disques de la VM.
    """
    disks = []
    try:
        from xml.etree import ElementTree as ET
        root = ET.fromstring(xml_content)
        devices = root.find("devices")
        if devices is not None:
            disk_elements = devices.findall("disk")
            for disk in disk_elements:
                disk_source = disk.find("source")
                if disk_source is not None and "file" in disk_source.attrib:
                    disks.append(disk_source.attrib["file"])
                elif disk_source is not None and "dev" in disk_source.attrib:
                    disks.append(disk_source.attrib["dev"])
    except:
        pass  # Failed to get disks, continue without them

    return disks
