"""
Module for managing libvirt storage pools and volumes.
"""
from typing import List, Dict, Any
import libvirt
from vm_queries import get_vm_disks_info

def list_storage_pools(conn: libvirt.virConnect) -> List[Dict[str, Any]]:
    """
    Lists all storage pools with their status and details.
    """
    if not conn:
        return []

    pools_info = []
    try:
        # Active pools
        pool_names = conn.listStoragePools()
        for name in pool_names:
            try:
                pool = conn.storagePoolLookupByName(name)
                if pool:
                    info = pool.info() # state, capacity, allocation, available
                    pools_info.append({
                        'name': name,
                        'pool': pool,
                        'status': 'active',
                        'autostart': pool.autostart() == 1,
                        'capacity': info[1],
                        'allocation': info[2],
                    })
            except libvirt.libvirtError:
                continue

        # Inactive pools
        defined_pool_names = conn.listDefinedStoragePools()
        for name in defined_pool_names:
            if name not in pool_names:
                try:
                    pool = conn.storagePoolLookupByName(name)
                    if pool:
                        info = pool.info()
                        pools_info.append({
                            'name': name,
                            'pool': pool,
                            'status': 'inactive',
                            'autostart': pool.autostart() == 1,
                            'capacity': info[1],
                            'allocation': info[2],
                        })
                except libvirt.libvirtError:
                    continue
    except libvirt.libvirtError:
        return []

    return pools_info

def list_storage_volumes(pool: libvirt.virStoragePool) -> List[Dict[str, Any]]:
    """
    Lists all storage volumes in a given pool.
    """
    volumes_info = []
    if not pool or not pool.isActive():
        return volumes_info

    try:
        vol_names = pool.listVolumes()
        for name in vol_names:
            try:
                vol = pool.storageVolLookupByName(name)
                info = vol.info() # type, capacity, allocation
                volumes_info.append({
                    'name': name,
                    'volume': vol,
                    'type': info[0],
                    'capacity': info[1],
                    'allocation': info[2],
                })
            except libvirt.libvirtError:
                continue
    except libvirt.libvirtError:
        pass # Or log error
    return volumes_info

def set_pool_active(pool: libvirt.virStoragePool, active: bool):
    """
    Sets a storage pool's active state.
    """
    try:
        if active:
            pool.create(0)
        else:
            pool.destroy()
    except libvirt.libvirtError as e:
        state = "activate" if active else "deactivate"
        raise logging.error(f"Error trying to {state} pool '{pool.name()}': {e}") from e

def set_pool_autostart(pool: libvirt.virStoragePool, autostart: bool):
    """
    Sets a storage pool's autostart flag.
    """
    try:
        pool.setAutostart(1 if autostart else 0)
    except libvirt.libvirtError as e:
        raise logging.error(f"Error setting autostart for pool '{pool.name()}': {e}") from e

def create_storage_pool(conn, name, pool_type, target, source_host=None, source_path=None, source_format=None):
    """
    Creates and starts a new storage pool.
    """
    xml = f"<pool type='{pool_type}'>"
    xml += f"<name>{name}</name>"
    if pool_type == 'dir':
        xml += f"<target><path>{target}</path></target>"
    elif pool_type == 'netfs':
        xml += "<source>"
        if source_host:
            xml += f"<host name='{source_host}'/>"
        if source_path:
            xml += f"<dir path='{source_path}'/>"
        if source_format:
            xml += f"<format type='{source_format}'/>"
        xml += "</source>"
        xml += f"<target><path>{target}</path></target>"
    xml += "</pool>"
    pool = conn.storagePoolDefineXML(xml, 0)
    pool.create(0)
    pool.setAutostart(1)
    return pool

def create_volume(pool: libvirt.virStoragePool, name: str, size_gb: int, vol_format: str):
    """
    Creates a new storage volume in a pool.
    """
    if not pool.isActive():
        raise logging.error(f"Pool '{pool.name()}' is not active.")

    size_bytes = size_gb * 1024 * 1024 * 1024

    vol_xml = f"""
    <volume>
        <name>{name}</name>
        <capacity unit="bytes">{size_bytes}</capacity>
        <target>
            <format type='{vol_format}'/>
        </target>
    </volume>
    """
    try:
        pool.createXML(vol_xml, 0)
    except libvirt.libvirtError as e:
        raise logging.error(f"Error creating volume '{name}': {e}") from e

def delete_volume(vol: libvirt.virStorageVol):
    """
    Deletes a storage volume.
    """
    try:
        # The flag VIR_STORAGE_VOL_DELETE_NORMAL = 0 is for normal deletion.
        vol.delete(0)
    except libvirt.libvirtError as e:
        # Re-raise with a more informative message
        raise logging.error(f"Error deleting volume '{vol.name()}': {e}") from e

def delete_storage_pool(pool: libvirt.virStoragePool):
    """
    Deletes a storage pool.
    The pool must be inactive first.
    """
    try:
        # If pool is active, destroy it first (make it inactive)
        if pool.isActive():
            pool.destroy()
        # Undefine the pool (delete it)
        pool.undefine()
    except libvirt.libvirtError as e:
        raise logging.error(f"Error deleting storage pool '{pool.name()}': {e}") from e

def get_all_storage_volumes(conn: libvirt.virConnect) -> List[libvirt.virStorageVol]:
    """
    Retrieves all storage volumes across all active storage pools.
    """
    all_volumes = []
    if not conn:
        return all_volumes

    pools_info = list_storage_pools(conn)
    for pool_info in pools_info:
        pool = pool_info['pool']
        if pool.isActive():
            try:
                all_volumes.extend(pool.listAllVolumes())
            except libvirt.libvirtError:
                continue
    return all_volumes


def list_unused_volumes(conn: libvirt.virConnect, pool_name: str = None) -> List[libvirt.virStorageVol]:
    """
    Lists all storage volumes that are not attached to any VM.
    If pool_name is provided, only checks volumes in that specific pool.
    """
    if not conn:
        return []

    # If pool_name is specified, get volumes from that specific pool
    if pool_name:
        try:
            pool = conn.storagePoolLookupByName(pool_name)
            if not pool.isActive():
                return []
            all_volumes = pool.listAllVolumes()
        except libvirt.libvirtError:
            return []
    else:
        all_volumes = get_all_storage_volumes(conn)

    used_disk_paths = set()

    try:
        domains = conn.listAllDomains(0)
        for domain in domains:
            xml_content = domain.XMLDesc(0)
            disks_info = get_vm_disks_info(conn, xml_content)
            for disk in disks_info:
                if disk.get('path'):
                    used_disk_paths.add(disk['path'])
    except libvirt.libvirtError as e:
        print(f"Error retrieving VM disk information: {e}")
        return []

    unused_volumes = []
    for vol in all_volumes:
        if vol.path() not in used_disk_paths:
            unused_volumes.append(vol)

    return unused_volumes
