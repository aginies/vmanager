"""
Module for managing libvirt storage pools and volumes.
"""
import libvirt
from typing import List, Dict, Any

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
        raise Exception(f"Error trying to {state} pool '{pool.name()}': {e}") from e

def set_pool_autostart(pool: libvirt.virStoragePool, autostart: bool):
    """
    Sets a storage pool's autostart flag.
    """
    try:
        pool.setAutostart(1 if autostart else 0)
    except libvirt.libvirtError as e:
        raise Exception(f"Error setting autostart for pool '{pool.name()}': {e}") from e

def create_volume(pool: libvirt.virStoragePool, name: str, size_gb: int, vol_format: str):
    """
    Creates a new storage volume in a pool.
    """
    if not pool.isActive():
        raise Exception(f"Pool '{pool.name()}' is not active.")

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
        raise Exception(f"Error creating volume '{name}': {e}") from e

def delete_volume(vol: libvirt.virStorageVol):
    """
    Deletes a storage volume.
    """
    try:
        # The flag VIR_STORAGE_VOL_DELETE_NORMAL = 0 is for normal deletion.
        vol.delete(0)
    except libvirt.libvirtError as e:
        # Re-raise with a more informative message
        raise Exception(f"Error deleting volume '{vol.name()}': {e}") from e
