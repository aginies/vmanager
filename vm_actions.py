"""
Module for performing actions and modifications on virtual machines.
"""
import os
import secrets
import string
import uuid
import logging
import xml.etree.ElementTree as ET
import libvirt
from libvirt_utils import _find_vol_by_path, _get_disabled_disks_elem
from utils import log_function_call
from vm_queries import get_vm_disks_info

@log_function_call
def clone_vm(original_vm, new_vm_name):
    """
    Clones a VM, including its storage using libvirt's storage pool API.
    """
    conn = original_vm.connect()
    original_xml = original_vm.XMLDesc(0)
    root = ET.fromstring(original_xml)

    name_elem = root.find('name')
    if name_elem is not None:
        name_elem.text = new_vm_name

    uuid_elem = root.find('uuid')
    if uuid_elem is not None:
        uuid_elem.text = str(uuid.uuid4())

    for interface in root.findall('.//devices/interface'):
        mac_elem = interface.find('mac')
        if mac_elem is not None:
            interface.remove(mac_elem)

    for disk in root.findall('.//devices/disk'):
        if disk.get('device') != 'disk':
            continue

        source_elem = disk.find('source')
        if source_elem is None:
            continue

        original_disk_path = source_elem.get('file')
        if not original_disk_path:
            continue

        original_vol, original_pool = _find_vol_by_path(conn, original_disk_path)
        # If the disk is not a managed libvirt storage volume, skip it as per user's instruction.
        if not original_vol:
            logging.info(f"Skipping cloning of non-libvirt managed disk: {original_disk_path}")
            continue

        original_vol_xml = original_vol.XMLDesc(0)
        vol_root = ET.fromstring(original_vol_xml)

        _, vol_name_ext = os.path.splitext(original_vol.name())
        new_vol_name = f"{new_vm_name}_{secrets.token_hex(4)}{vol_name_ext}"
        vol_root.find('name').text = new_vol_name

        # Libvirt will handle capacity, allocation, and backing store when cloning.
        # Clear old path/key info just in case.
        if vol_root.find('key') is not None:
             vol_root.remove(vol_root.find('key'))
        target_elem = vol_root.find('target')
        if target_elem is not None:
            if target_elem.find('path') is not None:
                target_elem.remove(target_elem.find('path'))

        new_vol_xml = ET.tostring(vol_root, encoding='unicode')

        # Clone the volume. Use REFLINK for efficiency (thin clone).
        try:
            new_vol = original_pool.createXMLFrom(new_vol_xml, original_vol, libvirt.VIR_STORAGE_VOL_CREATE_REFLINK)
        except libvirt.libvirtError as e:
            # If reflinking is not supported by the storage backend, fall back to a full clone.
            if 'unsupported flags' in str(e).lower():
                new_vol = original_pool.createXMLFrom(new_vol_xml, original_vol, 0)
            else:
                raise

        disk.set('type', 'volume')
        if 'file' in source_elem.attrib:
            del source_elem.attrib['file']
        source_elem.set('pool', original_pool.name())
        source_elem.set('volume', new_vol.name())

    new_xml = ET.tostring(root, encoding='unicode')
    new_vm = conn.defineXML(new_xml)

    return new_vm

def rename_vm(domain, new_name, delete_snapshots=False):
    """
    Renames a VM.
    The VM must be stopped.
    If delete_snapshots is True, it will delete all snapshots before renaming.
    """
    if not domain:
        raise ValueError("Invalid domain object.")

    if domain.isActive():
        raise libvirt.libvirtError("VM must be stopped to be renamed.")

    conn = domain.connect()

    if domain.name() == new_name:
        return  # It's already named this, do nothing.

    # Check for snapshots
    num_snapshots = domain.snapshotNum(0)
    if num_snapshots > 0:
        if delete_snapshots:
            for snapshot in domain.listAllSnapshots(0):
                snapshot.delete(0)
        else:
            raise libvirt.libvirtError(f"Cannot rename VM with {num_snapshots} snapshot(s).")

    # Check if a VM with the new name already exists
    try:
        conn.lookupByName(new_name)
        # If lookup succeeds, a VM with the new name already exists.
        raise libvirt.libvirtError(f"A VM with the name '{new_name}' already exists.")
    except libvirt.libvirtError as e:
        # "domain not found" is the expected error if the name is available.
        # We check the error code to be sure, as the error message string
        if e.get_error_code() != libvirt.VIR_ERR_NO_DOMAIN:
            raise # Re-raise other libvirt errors.

    xml_desc = domain.XMLDesc(0)

    domain.undefine()

    try:
        # Modify XML with new name
        root = ET.fromstring(xml_desc)
        name_elem = root.find('name')
        if name_elem is None:
            raise Exception("Could not find name element in VM XML.")
        name_elem.text = new_name
        new_xml = ET.tostring(root, encoding='unicode')

        # Define the new domain from the modified XML
        conn.defineXML(new_xml)
    except Exception as e:
        conn.defineXML(xml_desc)
        raise Exception(f"Failed to rename VM, but restored original state. Error: {e}")

def add_disk(domain, disk_path, device_type='disk', create=False, size_gb=10, disk_format='qcow2'):
    """
    Adds a disk to a VM. Can optionally create a new disk image in a libvirt storage pool.
    device_type can be 'disk' or 'cdrom'
    """
    if not domain:
        raise ValueError("Invalid domain object.")

    conn = domain.connect()

    # Determine target device
    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)

    if device_type == 'disk':
        bus = 'virtio'
        prefix = 'vd'
        dev_letters = string.ascii_lowercase
    elif device_type == 'cdrom':
        bus = 'sata'
        prefix = 'sd'
        dev_letters = string.ascii_lowercase
    else:
        raise ValueError(f"Unsupported device type: {device_type}")

    used_devs = [
        target.get("dev")
        for target in root.findall(".//disk/target")
        if target.get("dev")
    ]

    target_dev = ""
    for letter in dev_letters:
        dev = f"{prefix}{letter}"
        if dev not in used_devs:
            target_dev = dev
            break

    if not target_dev:
        raise Exception("No available device slots for new disk.")

    disk_xml = ""

    if create:
        if device_type != 'disk':
            raise Exception("Cannot create non-disk device types.")

        # Find storage pool from path
        pool = None
        pools = conn.listAllStoragePools(0)
        for p in pools:
            if p.isActive():
                try:
                    p_xml = p.XMLDesc(0)
                    p_root = ET.fromstring(p_xml)
                    target_path = p_root.findtext("target/path")
                    if target_path and os.path.dirname(disk_path) == target_path:
                        pool = p
                        break
                except libvirt.libvirtError:
                    continue  # Some pools might not have paths, etc.

        if not pool:
            raise Exception(f"Could not find an active storage pool managing the path '[red]{os.path.dirname(disk_path)}[/red]'.")

        vol_name = os.path.basename(disk_path)

        # Check if volume already exists
        try:
            pool.storageVolLookupByName(vol_name)
            raise Exception(f"A storage volume named '{vol_name}' already exists in pool '{pool.name()}'.")
        except libvirt.libvirtError as e:
            if e.get_error_code() != libvirt.VIR_ERR_NO_STORAGE_VOL:
                raise

        vol_xml_def = f"""
        <volume>
            <name>{vol_name}</name>
            <capacity unit="G">{size_gb}</capacity>
            <target>
                <format type='{disk_format}'/>
            </target>
        </volume>
        """
        try:
            new_vol = pool.createXML(vol_xml_def, 0)
        except libvirt.libvirtError as e:
            raise Exception(f"Failed to create volume in libvirt pool: {e}")

        disk_xml = f"""
        <disk type='volume' device='disk'>
            <driver name='qemu' type='{disk_format}'/>
            <source pool='{pool.name()}' volume='{new_vol.name()}'/>
            <target dev='{target_dev}' bus='{bus}'/>
        </disk>
        """
    else:  # not creating, just attaching
        if device_type == 'cdrom':
            disk_xml = f"""
            <disk type='file' device='cdrom'>
                <driver name='qemu' type='raw'/>
                <source file='{disk_path}'/>
                <target dev='{target_dev}' bus='{bus}'/>
                <readonly/>
            </disk>
            """
        else:  # device_type is 'disk'
            vol, _ = _find_vol_by_path(conn, disk_path)
            vol_format = disk_format
            if vol:
                try:
                    vol_xml_str = vol.XMLDesc(0)
                    vol_root = ET.fromstring(vol_xml_str)
                    format_elem = vol_root.find("target/format")
                    if format_elem is not None:
                        vol_format = format_elem.get('type')
                except (libvirt.libvirtError, ET.ParseError):
                    pass # use default disk_format

            disk_xml = f"""
            <disk type='file' device='disk'>
                <driver name='qemu' type='{vol_format}' discard='unmap'/>
                <source file='{disk_path}'/>
                <target dev='{target_dev}' bus='{bus}'/>
            </disk>
            """

    if not disk_xml:
        raise Exception("Could not generate disk XML for attaching.")

    flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
    if domain.isActive():
        flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE

    domain.attachDeviceFlags(disk_xml, flags)
    return target_dev

def remove_disk(domain, disk_dev_path):
    """
    Removes a disk from a VM based on its device path (e.g. /path/to/disk.img) or device name (vda)
    """
    if not domain:
        raise ValueError("Invalid domain object.")

    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)
    logging.debug(f"remove_disk: Attempting to remove disk: {disk_dev_path}")
    logging.debug(f"remove_disk: VM XML description:\n{xml_desc}")

    disk_to_remove_xml = None

    # Try two separate findall calls and combine
    disks_type_disk = root.findall(".//disk[@device='disk']")
    disks_type_cdrom = root.findall(".//disk[@device='cdrom']")
    all_matching_disks = disks_type_disk + disks_type_cdrom

    for disk in all_matching_disks:
        source = disk.find("source")
        target = disk.find("target")

        current_disk_path = ""
        current_target_dev = ""

        if source is not None:
            if "file" in source.attrib:
                current_disk_path = source.get("file")
            elif "pool" in source.attrib and "volume" in source.attrib:
                pool_name = source.get("pool")
                vol_name = source.get("volume")
                try:
                    pool = domain.connect().storagePoolLookupByName(pool_name)
                    vol = pool.storageVolLookupByName(vol_name)
                    current_disk_path = vol.path()
                except libvirt.libvirtError as e:
                    current_disk_path = f"ERROR: Could not resolve volume path for {vol_name} in {pool_name}: {e}"

        if target is not None:
            current_target_dev = target.get("dev")

        match = False
        logging.debug(f"remove_disk: Comparing disk_dev_path={repr(disk_dev_path)} with current_disk_path={repr(current_disk_path)} and current_target_dev={repr(current_target_dev)}")
        if current_disk_path == disk_dev_path:
            match = True
        elif current_target_dev == disk_dev_path: # This is for matching by "vda", "vdb" etc.
            match = True
        else:
            logging.debug("remove_disk: No exact match found for this disk element.")

        if match:
            disk_to_remove_xml = ET.tostring(disk, encoding="unicode")
            break

    if not disk_to_remove_xml:
        raise Exception(f"Disk with device path or name '[red]{disk_dev_path}[/red]' not found.")

    flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
    if domain.isActive():
        flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE

    domain.detachDeviceFlags(disk_to_remove_xml, flags)


@log_function_call
def remove_virtiofs(domain: libvirt.virDomain, target_dir: str):
    """
    Removes a virtiofs filesystem from a VM.
    The VM must be stopped to remove a virtiofs device.
    """
    if not domain:
        raise ValueError("Invalid domain object.")

    if domain.isActive():
        raise libvirt.libvirtError("VM must be stopped to remove a virtiofs device.")

    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)

    devices = root.find('devices')
    if devices is None:
        raise ValueError("Could not find <devices> in VM XML.")

    virtiofs_to_remove = None
    for fs_elem in devices.findall("./filesystem[@type='mount']"):
        driver = fs_elem.find('driver')
        target = fs_elem.find('target')
        if driver is not None and driver.get('type') == 'virtiofs' and target is not None:
            if target.get('dir') == target_dir:
                virtiofs_to_remove = fs_elem
                break

    if virtiofs_to_remove is None:
        raise ValueError(f"VirtIO-FS mount with target directory '{target_dir}' not found.")

    devices.remove(virtiofs_to_remove)

    new_xml = ET.tostring(root, encoding='unicode')

    conn = domain.connect()
    conn.defineXML(new_xml)

@log_function_call
def add_virtiofs(domain: libvirt.virDomain, source_path: str, target_path: str, readonly: bool):
    """
    Adds a virtiofs filesystem to a VM.
    The VM must be stopped to add a virtiofs device.
    """
    if not domain:
        raise ValueError("Invalid domain object.")

    if domain.isActive():
        raise libvirt.libvirtError("VM must be stopped to add a virtiofs device.")

    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)

    devices = root.find('devices')
    if devices is None:
        devices = ET.SubElement(root, 'devices')

    # Create the new virtiofs XML element
    fs_elem = ET.SubElement(devices, "filesystem", type="mount", accessmode="passthrough")

    #driver_elem = ET.SubElement(fs_elem, "driver", type="virtiofs")
    #source_elem = ET.SubElement(fs_elem, "source", dir=source_path)
    #target_elem = ET.SubElement(fs_elem, "target", dir=target_path)

    if readonly:
        ET.SubElement(fs_elem, "readonly")

    # Redefine the VM with the updated XML
    new_xml = ET.tostring(root, encoding='unicode')

    conn = domain.connect()
    conn.defineXML(new_xml)


def add_network_interface(domain: libvirt.virDomain, network: str, model: str):
    """Adds a network interface to a VM."""
    if not domain:
        raise ValueError("Invalid domain object.")

    interface_xml = f"""
    <interface type='network'>
        <source network='{network}'/>
        <model type='{model}'/>
    </interface>
    """

    flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
    if domain.isActive():
        flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE

    domain.attachDeviceFlags(interface_xml, flags)

def remove_network_interface(domain: libvirt.virDomain, mac_address: str):
    """Removes a network interface from a VM."""
    if not domain:
        raise ValueError("Invalid domain object.")

    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)

    interface_to_remove = None
    for iface in root.findall(".//devices/interface"):
        mac_node = iface.find("mac")
        if mac_node is not None and mac_node.get("address") == mac_address:
            interface_to_remove = iface
            break

    if interface_to_remove is None:
        raise ValueError(f"Interface with MAC {mac_address} not found.")

    interface_xml = ET.tostring(interface_to_remove, 'unicode')

    flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
    if domain.isActive():
        flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE

    domain.detachDeviceFlags(interface_xml, flags)


def change_vm_network(domain: libvirt.virDomain, mac_address: str, new_network: str, new_model: str = None):
    """Changes the network for a VM's network interface."""
    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)

    interface_to_update = None
    for iface in root.findall(".//devices/interface"):
        mac_node = iface.find("mac")
        if mac_node is not None and mac_node.get("address") == mac_address:
            interface_to_update = iface
            break

    if interface_to_update is None:
        raise ValueError(f"Interface with MAC {mac_address} not found.")

    source_node = interface_to_update.find("source")
    if source_node is None:
        raise ValueError("Interface does not have a source element.")

    model_node = interface_to_update.find("model")
    if model_node is None:
        model_node = ET.SubElement(interface_to_update, "model")

    # Check if network is already the same
    if source_node.get("network") == new_network and (new_model is None or model_node.get("type") == new_model):
        return # Nothing to do

    source_node.set("network", new_network)
    if new_model:
        model_node.set("type", new_model)

    interface_xml = ET.tostring(interface_to_update, 'unicode')

    state = domain.info()[0]
    flags = libvirt.VIR_DOMAIN_DEVICE_MODIFY_CONFIG
    if state in [libvirt.VIR_DOMAIN_RUNNING, libvirt.VIR_DOMAIN_PAUSED]:
        flags |= libvirt.VIR_DOMAIN_DEVICE_MODIFY_LIVE

    domain.updateDeviceFlags(interface_xml, flags)


def disable_disk(domain, disk_path):
    """Disables a disk by moving it to a metadata section in the XML."""
    if domain.isActive():
        raise libvirt.libvirtError("VM must be stopped to disable a disk.")

    conn = domain.connect()
    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)

    devices = root.find('devices')
    if devices is None:
        raise ValueError("Could not find <devices> in VM XML.")

    disk_to_disable = None
    for disk in devices.findall('disk'):
        source = disk.find('source')
        path = None
        if source is not None and 'file' in source.attrib:
            path = source.attrib['file']
        elif source is not None and 'dev' in source.attrib:
            path = source.attrib['dev']

        if path == disk_path:
            disk_to_disable = disk
            break

    if disk_to_disable is None:
        raise ValueError(f"Enabled disk '{disk_path}' not found.")

    devices.remove(disk_to_disable)

    disabled_disks_elem = _get_disabled_disks_elem(root)
    disabled_disks_elem.append(disk_to_disable)

    new_xml = ET.tostring(root, encoding='unicode')
    conn.defineXML(new_xml)

def enable_disk(domain, disk_path):
    """Enables a disk by moving it from metadata back to devices."""
    if domain.isActive():
        raise libvirt.libvirtError("VM must be stopped to enable a disk.")

    conn = domain.connect()
    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)

    disabled_disks_elem = _get_disabled_disks_elem(root)

    disk_to_enable = None
    for disk in disabled_disks_elem.findall('disk'):
        source = disk.find('source')
        path = None
        if source is not None and 'file' in source.attrib:
            path = source.attrib['file']
        elif source is not None and 'dev' in source.attrib:
            path = source.attrib['dev']

        if path == disk_path:
            disk_to_enable = disk
            break

    if disk_to_enable is None:
        raise ValueError(f"Disabled disk '{disk_path}' not found.")

    disabled_disks_elem.remove(disk_to_enable)

    devices = root.find('devices')
    if devices is None:
        devices = ET.SubElement(root, 'devices')
    devices.append(disk_to_enable)

    new_xml = ET.tostring(root, encoding='unicode')
    conn.defineXML(new_xml)

def set_vcpu(domain, vcpu_count: int):
    """
    Sets the number of virtual CPUs for a VM.
    Handles both simple and complex (with attributes) vCPU definitions.
    """
    if not domain:
        raise ValueError("Invalid domain object.")

    conn = domain.connect()

    xml_flags = libvirt.VIR_DOMAIN_XML_INACTIVE if domain.isPersistent() else 0
    xml_desc = domain.XMLDesc(xml_flags)
    root = ET.fromstring(xml_desc)

    vcpu_elem = root.find('vcpu')
    if vcpu_elem is None:
        vcpu_elem = ET.SubElement(root, 'vcpu')

    vcpu_elem.text = str(vcpu_count)
    new_xml = ET.tostring(root, encoding='unicode')

    conn.defineXML(new_xml)

    # For a running VM, the only way to change vCPU count is setVcpusFlags.
    if domain.isActive():
        try:
            # Attempt a live update.
            domain.setVcpusFlags(vcpu_count, libvirt.VIR_DOMAIN_AFFECT_LIVE)
        except libvirt.libvirtError as e:
            # If live update fails, we inform the user. The persistent config is still updated.
            raise libvirt.libvirtError(
                f"Live vCPU update failed: {e}. "
                "The configuration has been saved and will apply on the next reboot."
            )

def set_memory(domain, memory_mb: int):
    """
    Sets the memory for a VM in megabytes.
    Handles both simple and complex (with attributes) memory definitions.
    """
    if not domain:
        raise ValueError("Invalid domain object.")

    memory_kb = memory_mb * 1024
    conn = domain.connect()

    xml_flags = libvirt.VIR_DOMAIN_XML_INACTIVE if domain.isPersistent() else 0
    xml_desc = domain.XMLDesc(xml_flags)
    root = ET.fromstring(xml_desc)

    # Update max memory
    memory_elem = root.find('memory')
    if memory_elem is None:
        memory_elem = ET.SubElement(root, 'memory')
    memory_elem.text = str(memory_kb)
    memory_elem.set('unit', 'KiB')

    # Update current memory
    current_memory_elem = root.find('currentMemory')
    if current_memory_elem is None:
        current_memory_elem = ET.SubElement(root, 'currentMemory')
    current_memory_elem.text = str(memory_kb)
    current_memory_elem.set('unit', 'KiB')

    new_xml = ET.tostring(root, encoding='unicode')

    # Update the persistent definition of the VM.
    conn.defineXML(new_xml)

    # For a running VM, we use setMemoryFlags for a live update.
    if domain.isActive():
        try:
            # Attempt a live update.
            domain.setMemoryFlags(memory_kb, libvirt.VIR_DOMAIN_AFFECT_LIVE)
        except libvirt.libvirtError as e:
            # If live update fails, inform the user. The persistent config is still updated.
            raise libvirt.libvirtError(
                f"Live memory update failed: {e}. "
                "The configuration has been saved and will apply on the next reboot."
            )

@log_function_call
def set_disk_properties(domain: libvirt.virDomain, disk_path: str, properties: dict):
    """Sets multiple driver properties for a specific disk."""
    if domain.isActive():
        raise libvirt.libvirtError("VM must be stopped to change disk settings.")

    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)

    disk_found = False
    for disk in root.findall(".//disk[@device='disk']"):
        source = disk.find("source")
        if source is not None and source.get("file") == disk_path:
            driver = disk.find("driver")
            if driver is None:
                driver = ET.SubElement(disk, "driver", name="qemu", type="qcow2")

            for key, value in properties.items():
                if key == "cache" and value == "default":
                    if key in driver.attrib:
                        del driver.attrib[key]
                else:
                    driver.set(key, value)

            disk_found = True
            break

    if not disk_found:
        raise ValueError(f"Disk with path '{disk_path}' not found.")

    new_xml = ET.tostring(root, encoding='unicode')
    conn = domain.connect()
    conn.defineXML(new_xml)

def set_machine_type(domain, new_machine_type):
    """
    Sets the machine type for a VM.
    The VM must be stopped.
    """
    if not domain:
        raise ValueError("Invalid domain object.")

    if domain.isActive():
        raise libvirt.libvirtError("VM must be stopped to change machine type.")

    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)

    type_elem = root.find(".//os/type")
    if type_elem is None:
        raise Exception("Could not find OS type element in VM XML.")

    type_elem.set('machine', new_machine_type)

    new_xml_desc = ET.tostring(root, encoding='unicode')

    conn = domain.connect()
    conn.defineXML(new_xml_desc)


def set_shared_memory(domain: libvirt.virDomain, enable: bool):
    """Enable or disable shared memory for a VM."""
    if domain.isActive():
        raise ValueError("Cannot change shared memory setting on a running VM.")

    xml_content = domain.XMLDesc(0)
    root = ET.fromstring(xml_content)

    memory_backing = root.find('memoryBacking')

    if enable:
        if memory_backing is None:
            memory_backing = ET.SubElement(root, 'memoryBacking')

        # Ensure no conflicting access mode is set
        access_elem = memory_backing.find('access')
        if access_elem is not None and access_elem.get('mode') != 'shared':
            memory_backing.remove(access_elem)
            access_elem = None # It's gone

        # Add it if it doesn't exist
        if access_elem is None:
            ET.SubElement(memory_backing, 'access', mode='shared')

    else:  # disable
        if memory_backing is not None:
            # Remove both possible shared memory indicators
            shared_elem = memory_backing.find('shared')
            if shared_elem is not None:
                memory_backing.remove(shared_elem)

            access_elem = memory_backing.find('access')
            if access_elem is not None and access_elem.get('mode') == 'shared':
                memory_backing.remove(access_elem)

            # If memoryBacking is now empty, and has no attributes, remove it.
            if not list(memory_backing) and not memory_backing.attrib:
                root.remove(memory_backing)

    new_xml = ET.tostring(root, encoding='unicode')

    conn = domain.connect()
    conn.defineXML(new_xml)

@log_function_call
def set_boot_info(domain: libvirt.virDomain, menu_enabled: bool, order: list[str]):
    """Sets the boot configuration for a VM."""
    if domain.isActive():
        raise libvirt.libvirtError("VM must be stopped to change boot settings.")

    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)
    conn = domain.connect()
    os_elem = root.find('.//os')
    if os_elem is None:
        os_elem = ET.SubElement(root, 'os')

    # Remove old <boot> elements under <os>
    for boot_elem in os_elem.findall('boot'):
        os_elem.remove(boot_elem)

    # Remove old <boot> elements under devices
    for dev_node in root.findall('.//devices/*[boot]'):
        boot_elem = dev_node.find('boot')
        if boot_elem is not None:
            dev_node.remove(boot_elem)

    # Set boot menu
    boot_menu_elem = os_elem.find('bootmenu')
    if boot_menu_elem is not None:
        os_elem.remove(boot_menu_elem)
    if menu_enabled:
        ET.SubElement(os_elem, 'bootmenu', enable='yes')

    # Set new boot order
    for i, device_id in enumerate(order, 1):
        # Find the device and add a <boot order='...'> element
        # Check disks first
        disk_found = False
        for disk_elem in root.findall('.//devices/disk'):
            source_elem = disk_elem.find('source')
            if source_elem is not None:
                path = None
                if "file" in source_elem.attrib:
                    path = source_elem.attrib["file"]
                elif "dev" in source_elem.attrib:
                    path = source_elem.attrib["dev"]
                elif "pool" in source_elem.attrib and "volume" in source_elem.attrib:
                    pool_name = source_elem.attrib["pool"]
                    vol_name = source_elem.attrib["volume"]
                    try:
                        pool = conn.storagePoolLookupByName(pool_name)
                        vol = pool.storageVolLookupByName(vol_name)
                        path = vol.path()
                    except libvirt.libvirtError:
                        pass # Could not resolve path, so it cannot match device_id

                if path == device_id:
                    ET.SubElement(disk_elem, 'boot', order=str(i))
                    disk_found = True
                    break
        if disk_found:
            continue

        # Check interfaces
        for iface_elem in root.findall('.//devices/interface'):
            mac_elem = iface_elem.find('mac')
            if mac_elem is not None and mac_elem.get('address') == device_id:
                ET.SubElement(iface_elem, 'boot', order=str(i))
                break

    # Update the domain
    new_xml = ET.tostring(root, encoding='unicode')
    conn.defineXML(new_xml)

def set_vm_video_model(domain: libvirt.virDomain, model: str | None):
    """Sets the video model for a VM."""
    if domain.isActive():
        raise libvirt.libvirtError("VM must be stopped to change the video model.")

    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)

    devices = root.find('devices')
    if devices is None:
        if model is None:
            return
        devices = ET.SubElement(root, 'devices')

    video = devices.find('video')
    if video is None:
        if model is None:
            return
        video = ET.SubElement(devices, 'video')

    model_elem = video.find('model')

    if model is None:
        if model_elem is not None:
            video.remove(model_elem)
    else:
        if model_elem is None:
            model_elem = ET.SubElement(video, 'model')

        old_attribs = model_elem.attrib.copy()
        model_elem.clear()
        model_elem.set('type', model)

        if model == 'virtio':
            model_elem.set('heads', '1')
            model_elem.set('primary', 'yes')
        elif model == 'qxl':
            model_elem.set('vram', old_attribs.get('vram', '65536'))
            model_elem.set('ram', old_attribs.get('ram', '65536'))
        else: # vga, cirrus etc.
             model_elem.set('vram', old_attribs.get('vram', '16384'))

    new_xml = ET.tostring(root, encoding='unicode')
    domain.connect().defineXML(new_xml)


def set_cpu_model(domain: libvirt.virDomain, cpu_model: str):
    """Sets the CPU model for a VM."""
    if domain.isActive():
        raise libvirt.libvirtError("VM must be stopped to change the CPU model.")

    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)

    cpu = root.find('.//cpu')
    if cpu is None:
        cpu = ET.SubElement(root, 'cpu')

    new_xml = ET.tostring(root, encoding='unicode')
    domain.connect().defineXML(new_xml)

@log_function_call
def set_uefi_file(domain: libvirt.virDomain, uefi_path: str, secure_boot: bool):
    """
    Sets the UEFI file for a VM and optionally enables/disables secure boot.
    The VM must be stopped.
    """
    if domain.isActive():
        raise libvirt.libvirtError("VM must be stopped to change UEFI firmware.")

    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)

    os_elem = root.find('os')
    if os_elem is None:
        raise ValueError("Could not find <os> element in VM XML.")

    loader_elem = os_elem.find('loader')
    if loader_elem is None:
        loader_elem = ET.SubElement(os_elem, 'loader', type='pflash')

    if not uefi_path:
        if loader_elem is not None:
            os_elem.remove(loader_elem)
        nvram_elem = os_elem.find('nvram')
        if nvram_elem is not None:
            os_elem.remove(nvram_elem)
    else:
        loader_elem.text = uefi_path
        if secure_boot:
            loader_elem.set('secure', 'yes')
        elif 'secure' in loader_elem.attrib:
            del loader_elem.attrib['secure']

        nvram_elem = os_elem.find('nvram')
        if nvram_elem is None:
            nvram_elem = ET.SubElement(os_elem, 'nvram', template=f"{uefi_path.replace('.bin', '_VARS.fd')}",)

    new_xml = ET.tostring(root, encoding='unicode')
    domain.connect().defineXML(new_xml)

def set_vm_sound_model(domain: libvirt.virDomain, model: str):
    """
    Sets the sound model for a VM.
    The VM must be stopped.
    """
    if domain.isActive():
        raise libvirt.libvirtError("VM must be stopped to change the sound model.")

    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)

    devices = root.find("devices")
    if devices is None:
        devices = ET.SubElement(root, "devices")

    sound = devices.find("sound")
    if sound is None:
        sound = ET.SubElement(devices, "sound")

    model_elem = sound.find("model")

    if model is None:
        if model_elem is not None:
            sound.remove(model_elem)
    else:
        if model_elem is None:
            model_elem = ET.SubElement(sound, "model")

        model_elem.set("type", model)

    new_xml = ET.tostring(root, encoding="unicode")
    domain.connect().defineXML(new_xml)


def set_vm_graphics(domain: libvirt.virDomain, graphics_type: str | None, listen_type: str, address: str, port: int | None, autoport: bool, password_enabled: bool, password: str | None):
    """
    Sets the graphics configuration (VNC/Spice) for a VM.
    The VM must be stopped.
    """
    if domain.isActive():
        raise libvirt.libvirtError("VM must be stopped to change graphics settings.")

    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)

    devices = root.find('devices')
    if devices is None:
        devices = ET.SubElement(root, 'devices')

    # Remove existing graphics elements of other types or if no graphics type is specified
    existing_graphics_elements = devices.findall('graphics')
    for elem in existing_graphics_elements:
        if graphics_type is None or elem.get('type') != graphics_type:
            devices.remove(elem)

    graphics_elem = devices.find(f"graphics[@type='{graphics_type}']")

    if graphics_type is None:
        # If no graphics type is specified, ensure all graphics elements are removed
        for elem in existing_graphics_elements:
            devices.remove(elem)
    else:
        if graphics_elem is None:
            graphics_elem = ET.SubElement(devices, 'graphics', type=graphics_type)

        # Set port and autoport
        if autoport:
            graphics_elem.set('autoport', 'yes')
            if 'port' in graphics_elem.attrib:
                del graphics_elem.attrib['port']
        else:
            if 'autoport' in graphics_elem.attrib:
                del graphics_elem.attrib['autoport']
            if port is not None:
                graphics_elem.set('port', str(port))
            elif 'port' in graphics_elem.attrib:
                del graphics_elem.attrib['port'] # If autoport is off and no port provided, remove it


        # Set listen address
        listen_elem = graphics_elem.find('listen')
        if listen_type == 'address':
            if listen_elem is None:
                listen_elem = ET.SubElement(graphics_elem, 'listen', type='address')
            else:
                listen_elem.set('type', 'address')
            listen_elem.set('address', address)
        else:  # listen_type == 'none'
            if listen_elem is not None:
                graphics_elem.remove(listen_elem)

        # Set password
        if password_enabled and password:
            graphics_elem.set('passwd', password)
        elif 'passwd' in graphics_elem.attrib:
            del graphics_elem.attrib['passwd']


    new_xml = ET.tostring(root, encoding='unicode')
    domain.connect().defineXML(new_xml)


@log_function_call
def set_vm_tpm(domain: libvirt.virDomain, tpm_model: str, tpm_type: str = 'emulated', device_path: str = None, backend_type: str = None, backend_path: str = None):
    """
    Sets TPM configuration for a VM.
    The VM must be stopped.
    
    Args:
        domain: libvirt domain object
        tpm_model: TPM model (e.g., 'tpm-crb', 'tpm-tis')
        tpm_type: Type of TPM ('emulated' or 'passthrough')
        device_path: Path to TPM device (required for passthrough)
        backend_type: Backend type (e.g., 'emulator', 'passthrough')
        backend_path: Path to backend device (required for passthrough)
    """
    if domain.isActive():
        raise libvirt.libvirtError("VM must be stopped to change TPM settings.")

    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)

    devices = root.find('devices')
    if devices is None:
        devices = ET.SubElement(root, 'devices')

    # Remove existing TPM elements
    existing_tpm_elements = devices.findall('./tpm')
    for elem in existing_tpm_elements:
        devices.remove(elem)

    # Create new TPM element
    tpm_elem = ET.SubElement(devices, 'tpm', model=tpm_model)

    if tpm_type == 'passthrough':
        backend_elem = ET.SubElement(tpm_elem, 'backend', type='passthrough')
        if device_path:
            ET.SubElement(backend_elem, 'device', path=device_path)
    elif tpm_type == 'emulated':
        # For emulated TPM, add a backend of type 'emulator'
        ET.SubElement(tpm_elem, 'backend', type='emulator')

    new_xml = ET.tostring(root, encoding='unicode')
    domain.connect().defineXML(new_xml)


@log_function_call
def set_vm_rng(domain: libvirt.virDomain, rng_model: str = 'virtio', backend_model: str = 'random', backend_path: str = '/dev/urandom'):
    """
    Sets RNG (Random Number Generator) configuration for a VM.
    The VM must be stopped.
    
    Args:
        domain: libvirt domain object
        rng_model: RNG model (e.g., 'virtio')
        backend_model: Backend type (e.g., 'random', 'egd')
        backend_path: Path to backend device/file
    """
    if domain.isActive():
        raise libvirt.libvirtError("VM must be stopped to change RNG settings.")

    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)

    devices = root.find('devices')
    if devices is None:
        devices = ET.SubElement(root, 'devices')

    # Remove existing RNG elements
    existing_rng_elements = devices.findall('./rng')
    for elem in existing_rng_elements:
        devices.remove(elem)

    rng_elem = ET.SubElement(devices, 'rng', model=rng_model)
    backend_elem = ET.SubElement(rng_elem, 'backend', model=backend_model)
    if backend_model == 'random' and backend_path:
        backend_elem.text = backend_path
    elif backend_path:
        ET.SubElement(backend_elem, 'source', path=backend_path)

    new_xml = ET.tostring(root, encoding='unicode')
    domain.connect().defineXML(new_xml)


@log_function_call
def set_vm_watchdog(domain: libvirt.virDomain, watchdog_model: str = 'i6300esb', action: str = 'reset'):
    """
    Sets Watchdog configuration for a VM.
    The VM must be stopped.
    
    Args:
        domain: libvirt domain object
        watchdog_model: Watchdog model (e.g., 'i6300esb', 'pcie-vpd')
        action: Action to take when watchdog is triggered (e.g., 'reset', 'shutdown', 'poweroff')
    """
    if domain.isActive():
        raise libvirt.libvirtError("VM must be stopped to change Watchdog settings.")

    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)

    devices = root.find('devices')
    if devices is None:
        devices = ET.SubElement(root, 'devices')

    # Remove existing Watchdog elements
    existing_watchdog_elements = devices.findall('./watchdog')
    for elem in existing_watchdog_elements:
        devices.remove(elem)

    # Create new Watchdog element
    watchdog_elem = ET.SubElement(devices, 'watchdog', model=watchdog_model, action=action)

    new_xml = ET.tostring(root, encoding='unicode')
    domain.connect().defineXML(new_xml)


@log_function_call
def set_vm_input(domain: libvirt.virDomain, input_type: str = 'tablet', input_bus: str = 'usb'):
    """
    Sets Input (keyboard and mouse) configuration for a VM.
    The VM must be stopped.
    
    Args:
        domain: libvirt domain object
        input_type: Input device type (e.g., 'mouse', 'keyboard', 'tablet')
        input_bus: Bus type (e.g., 'usb', 'ps2', 'virtio')
    """
    if domain.isActive():
        raise libvirt.libvirtError("VM must be stopped to change Input settings.")

    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)

    devices = root.find('devices')
    if devices is None:
        devices = ET.SubElement(root, 'devices')

    # Remove existing input elements of the same type
    existing_input_elements = devices.findall(f'./input[@type="{input_type}"]')
    for elem in existing_input_elements:
        devices.remove(elem)

    # Create new input element
    input_elem = ET.SubElement(devices, 'input', type=input_type, bus=input_bus)

    new_xml = ET.tostring(root, encoding='unicode')
    domain.connect().defineXML(new_xml)


def start_vm(domain):
    """
    Starts a VM after checking for missing disks.
    """
    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)
    conn = domain.connect()

    for disk in root.findall('.//devices/disk'):
        if disk.get('device') != 'disk':
            continue

        source_elem = disk.find('source')
        if source_elem is None:
            continue

        if 'file' in source_elem.attrib:
            disk_path = source_elem.get('file')
            if not os.path.exists(disk_path):
                raise Exception(f"Disk image file not found: [red]{disk_path}[/red]")
        elif 'pool' in source_elem.attrib and 'volume' in source_elem.attrib:
            pool_name = source_elem.get('pool')
            vol_name = source_elem.get('volume')
            try:
                pool = conn.storagePoolLookupByName(pool_name)
                if not pool.isActive():
                    raise Exception(f"Storage pool '[red]{pool_name}[/red]' is not active.")
                # This will raise an exception if the volume doesn't exist
                pool.storageVolLookupByName(vol_name)
            except libvirt.libvirtError as e:
                raise Exception(f"Error checking disk volume '[red]{vol_name}[/red]' in pool '[red] {pool_name}[/red]': {e}")

    domain.create()

def delete_vm(domain: libvirt.virDomain, delete_storage: bool):
    """
    Deletes a VM and optionally its associated storage.
    """
    if not domain:
        raise ValueError("Invalid domain object.")

    conn = domain.connect()

    disks_to_delete = []
    if delete_storage:
        xml_desc = domain.XMLDesc(0)
        disks_to_delete = get_vm_disks_info(conn, xml_desc)

    if domain.isActive():
        domain.destroy()
    domain.undefine()

    if delete_storage:
        for disk_info in disks_to_delete:
            try:
                # Infer disk_type since get_vm_disks_info might not provide it directly
                disk_type = None
                if 'pool_name' in disk_info and 'volume_name' in disk_info:
                    disk_type = 'volume'
                elif 'path' in disk_info:
                    disk_type = 'file'

                if disk_type == 'file' and disk_info['path']:
                    if os.path.exists(disk_info['path']):
                        os.remove(disk_info['path'])
                        logging.info(f"Successfully deleted storage file: {disk_info['path']}")
                    else:
                        logging.warning(f"Storage file not found, skipping: {disk_info['path']}")
                elif disk_type == 'volume' and disk_info['pool_name'] and disk_info['volume_name']:
                    try:
                        pool = conn.storagePoolLookupByName(disk_info['pool_name'])
                        vol = pool.storageVolLookupByName(disk_info['volume_name'])
                        vol.delete(0)
                        logging.info(f"Successfully deleted storage volume: {disk_info['volume_name']} from pool {disk_info['pool_name']}")
                    except libvirt.libvirtError as e:
                        if e.get_error_code() == libvirt.VIR_ERR_NO_STORAGE_VOL:
                            logging.warning(f"Storage volume '{disk_info['volume_name']}' not found in pool '{disk_info['pool_name']}', skipping deletion.")
                        else:
                            logging.error(f"Error deleting storage volume {disk_info['volume_name']} from pool {disk_info['pool_name']}: {e}")
                            raise
                else:
                    logging.warning(f"Could not determine disk type for deletion for disk_info: {disk_info}")
            except OSError as e:
                logging.error(f"Error deleting storage file {disk_info.get('path', 'N/A')}: {e}")
                raise
