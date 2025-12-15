"""
Utility functions for libvirt XML parsing and common helpers.
"""
import xml.etree.ElementTree as ET
import logging
import libvirt

VMANAGER_NS = "http://github.com/aginies/vmanager"
ET.register_namespace("vmanager", VMANAGER_NS)

def _find_vol_by_path(conn, vol_path):
    """Finds a storage volume by its path and returns the volume and its pool."""
    # Slower but more compatible way to find a volume by path
    try:
        all_pool_names = conn.listStoragePools() + conn.listDefinedStoragePools()
    except libvirt.libvirtError:
        all_pool_names = []

    for pool_name in all_pool_names:
        try:
            pool = conn.storagePoolLookupByName(pool_name)
            if not pool.isActive():
                try:
                    pool.create(0)
                except libvirt.libvirtError:
                    continue  # Skip pools we can't start

            # listAllVolumes returns a list of virStorageVol objects
            for vol in pool.listAllVolumes():
                if vol and vol.path() == vol_path:
                    return vol, pool
        except libvirt.libvirtError:
            continue # Permissions issue or other problem, try next pool
    return None, None

def _get_vmanager_metadata(root):
    metadata_elem = root.find('metadata')
    if metadata_elem is None:
        metadata_elem = ET.SubElement(root, 'metadata')

    vmanager_meta_elem = metadata_elem.find(f'{{{VMANAGER_NS}}}vmanager')
    if vmanager_meta_elem is None:
        vmanager_meta_elem = ET.SubElement(metadata_elem, f'{{{VMANAGER_NS}}}vmanager')

    return vmanager_meta_elem

def _get_disabled_disks_elem(root):
    vmanager_meta_elem = _get_vmanager_metadata(root)
    disabled_disks_elem = vmanager_meta_elem.find(f'{{{VMANAGER_NS}}}disabled-disks')
    if disabled_disks_elem is None:
        disabled_disks_elem = ET.SubElement(vmanager_meta_elem, f'{{{VMANAGER_NS}}}disabled-disks')
    return disabled_disks_elem

def get_cpu_models(conn, arch):
    """
    Get a list of CPU models for a given architecture.
    """
    if not conn:
        return []
    try:
        # Returns a list of supported CPU model names
        models = conn.getCPUModelNames(arch)
        return models
    except libvirt.libvirtError as e:
        print(f"Error getting CPU models for arch {arch}: {e}")
        return []

def find_all_vm(conn):
    """
    Find all VM from the current Hypervisor
    """
    allvm_list = []
    # Store all VM from the hypervisor
    domains = conn.listAllDomains(0)
    for domain in domains:
        if domain.name():
            vmdomain = domain.name()
            allvm_list.append(vmdomain)
    return allvm_list

def get_domain_capabilities_xml(
    conn: libvirt.virConnect,
    emulatorbin: str,
    arch: str,
    machine: str,
    flags: int = 0
) -> str | None:
    """
    Retrieves the domain capabilities XML for a specific guest configuration.
    """
    try:
        caps_xml = conn.getDomainCapabilities(
            emulatorbin=emulatorbin,
            arch=arch,
            machine=machine,
            flags=flags
        )
        return caps_xml
    except libvirt.libvirtError as e:
        logging.error(f"Error getting domain capabilities: {e}")
        return None

def get_video_domain_capabilities(xml_content: str) -> dict:
    """
    Parses the domain capabilities XML to extract supported video
    """
    supported_models = {
        'video_models': [],
    }

    if not xml_content:
        return supported_models

    try:
        root = ET.fromstring(xml_content)

        # Extract supported video models
        for video_elem in root.findall(".//video[@supported='yes']/enum[@name='modelType']"):
            for value_elem in video_elem.findall('value'):
                if value_elem.text:
                    supported_models['video_models'].append(value_elem.text)

    except ET.ParseError as e:
        logging.error(f"Error parsing domain capabilities XML: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred during XML parsing: {e}")

    return supported_models

def get_sound_domain_capabilities(xml_content: str) -> dict:
    """
    Parses the domain capabilities XML to extract supported sound models.
    """
    supported_models = {
        'sound_models': [],
    }

    if not xml_content:
        return supported_models

    try:
        root = ET.fromstring(xml_content)

        # Extract supported sound models
        for sound_elem in root.findall(".//sound[@supported='yes']/enum[@name='model']"):
            for value_elem in sound_elem.findall('value'):
                if value_elem.text:
                    supported_models['sound_models'].append(value_elem.text)

    except ET.ParseError as e:
        logging.error(f"Error parsing domain capabilities XML: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred during XML parsing: {e}")

    return supported_models
