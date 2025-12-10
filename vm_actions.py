"""
Module for performing actions and modifications on virtual machines.
"""
import os
import secrets
import subprocess
import string
import uuid
import copy
import libvirt
import xml.etree.ElementTree as ET
from libvirt_utils import _find_vol_by_path, _get_disabled_disks_elem


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
        if not original_vol:
            raise Exception(f"Disk '{original_disk_path}' is not a managed libvirt storage volume. Cannot clone via API.")

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
    Adds a disk to a VM. Can optionally create a new disk image.
    device_type can be 'disk' or 'cdrom'
    """
    if not domain:
        raise ValueError("Invalid domain object.")

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

    if create:
        try:
            os.makedirs(os.path.dirname(disk_path), exist_ok=True)
            subprocess.run(['qemu-img', 'create', '-f', disk_format, disk_path, f'{size_gb}G'], check=True)
        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
            raise Exception(f"Failed to create disk image: {e}")

    if device_type == 'disk':
        disk_xml = f"""
        <disk type='file' device='disk'>
            <driver name='qemu' type='{disk_format}'/>
            <source file='{disk_path}'/>
            <target dev='{target_dev}' bus='{bus}'/>
        </disk>
        """
    else: # cdrom
        disk_xml = f"""
        <disk type='file' device='cdrom'>
            <driver name='qemu' type='raw'/>
            <source file='{disk_path}'/>
            <target dev='{target_dev}' bus='{bus}'/>
            <readonly/>
        </disk>
        """

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

    disk_to_remove_xml = None
    for disk in root.findall(".//disk[@device='disk'] | .//disk[@device='cdrom']"):
        source = disk.find("source")
        target = disk.find("target")

        match = False
        if source is not None and source.get("file") == disk_dev_path:
            match = True
        elif target is not None and target.get("dev") == disk_dev_path:
            match = True

        if match:
            disk_to_remove_xml = ET.tostring(disk, encoding="unicode")
            break

    if not disk_to_remove_xml:
        raise Exception(f"Disk with device path or name '{disk_dev_path}' not found.")

    flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
    if domain.isActive():
        flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE

    domain.detachDeviceFlags(disk_to_remove_xml, flags)

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

    driver_elem = ET.SubElement(fs_elem, "driver", type="virtiofs")
    source_elem = ET.SubElement(fs_elem, "source", dir=source_path)
    target_elem = ET.SubElement(fs_elem, "target", dir=target_path)

    if readonly:
        ET.SubElement(fs_elem, "readonly")

    # Redefine the VM with the updated XML
    new_xml = ET.tostring(root, encoding='unicode')

    conn = domain.connect()
    conn.defineXML(new_xml)


def change_vm_network(domain: libvirt.virDomain, mac_address: str, new_network: str):
    """Changes the network for a VM's network interface."""
    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)

    interface_to_update = None
    for iface in root.findall(f".//devices/interface"):
        mac_node = iface.find("mac")
        if mac_node is not None and mac_node.get("address") == mac_address:
            interface_to_update = iface
            break

    if interface_to_update is None:
        raise ValueError(f"Interface with MAC {mac_address} not found.")

    source_node = interface_to_update.find("source")
    if source_node is None:
        raise ValueError("Interface does not have a source element.")

    # Check if network is already the same
    if source_node.get("network") == new_network:
        return # Nothing to do

    source_node.set("network", new_network)
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
    """
    if not domain:
        raise ValueError("Invalid domain object.")

    flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
    if domain.isActive():
        flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE

    domain.setVcpusFlags(vcpu_count, flags)

def set_memory(domain, memory_mb: int):
    """
    Sets the memory for a VM in megabytes.
    """
    if not domain:
        raise ValueError("Invalid domain object.")

    memory_kb = memory_mb * 1024

    flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
    if domain.isActive():
        flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE

    domain.setMemoryFlags(memory_kb, flags)

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

def set_boot_info(domain: libvirt.virDomain, menu_enabled: bool, order: list[str]):
    """Sets the boot configuration for a VM."""
    if domain.isActive():
        raise libvirt.libvirtError("VM must be stopped to change boot settings.")

    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)
    os_elem = root.find('os')
    if os_elem is None:
        raise ValueError("Could not find <os> element in VM XML.")

    for boot_elem in os_elem.findall('boot'):
        os_elem.remove(boot_elem)
 
    boot_menu_elem = os_elem.find('bootmenu')
    if boot_menu_elem is not None:
        os_elem.remove(boot_menu_elem)

    for dev in order:
        ET.SubElement(os_elem, 'boot', dev=dev)

    if menu_enabled:
        ET.SubElement(os_elem, 'bootmenu', enable='yes')

    new_xml = ET.tostring(root, encoding='unicode')

def set_vm_video_model(domain: libvirt.virDomain, model: str | None):
    """Sets the video model for a VM."""
    if domain.isActive():
        raise libvirt.libvirtError("VM must be stopped to change the video model.")

    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)
    
    devices = root.find('devices')
    if devices is None:
        if model is None: return
        devices = ET.SubElement(root, 'devices')
        
    video = devices.find('video')
    if video is None:
        if model is None: return
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
