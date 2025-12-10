"""
Utility functions for libvirt XML parsing and common helpers.
"""
import libvirt
import xml.etree.ElementTree as ET
from utils import log_function_call

VMANAGER_NS = "http://github.com/aginies/vmanager"
ET.register_namespace("vmanager", VMANAGER_NS)


@log_function_call
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
