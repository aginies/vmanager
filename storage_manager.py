"""
Module for managing libvirt storage pools and volumes.
"""
from typing import List, Dict, Any
import logging
import os
import xml.etree.ElementTree as ET
import libvirt
from vm_queries import get_vm_disks_info

def is_default_image_pool(pool: libvirt.virStoragePool) -> bool:
    """Checks if the given pool is the default 'dir' type pool with path /var/lib/libvirt/images."""
    if pool.name() == "default":
        try:
            xml_desc = pool.XMLDesc(0)
            root = ET.fromstring(xml_desc)
            pool_type = root.get("type")
            path_element = root.find("target/path")

            if pool_type == "dir" and path_element is not None and path_element.text == "/var/lib/libvirt/images":
                return True
        except (libvirt.libvirtError, ET.ParseError):
            # If XML parsing fails, or pool is invalid, treat as not the default image pool
            pass
    return False

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
                    # Bypass the default image pool
                    if is_default_image_pool(pool):
                        continue

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
                        # Bypass the default image pool
                        if is_default_image_pool(pool):
                            continue

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
        msg = f"Error trying to {state} pool '{pool.name()}': {e}"
        logging.error(msg)
        raise Exception(msg) from e

def set_pool_autostart(pool: libvirt.virStoragePool, autostart: bool):
    """
    Sets a storage pool's autostart flag.
    """
    try:
        pool.setAutostart(1 if autostart else 0)
    except libvirt.libvirtError as e:
        msg = f"Error setting autostart for pool '{pool.name()}': {e}"
        logging.error(msg)
        raise Exception(msg) from e

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
        msg = f"Pool '{pool.name()}' is not active."
        logging.error(msg)
        raise Exception(msg)

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
        msg = f"Error creating volume '{name}': {e}"
        logging.error(msg)
        raise Exception(msg) from e

def delete_volume(vol: libvirt.virStorageVol):
    """
    Deletes a storage volume.
    """
    try:
        # The flag VIR_STORAGE_VOL_DELETE_NORMAL = 0 is for normal deletion.
        vol.delete(0)
    except libvirt.libvirtError as e:
        # Re-raise with a more informative message
        msg = f"Error deleting volume '{vol.name()}': {e}"
        logging.error(msg)
        raise Exception(msg) from e

def find_vms_using_volume(conn: libvirt.virConnect, vol_path: str) -> List[libvirt.virDomain]:
    """Finds VMs that are using a specific storage volume path."""
    vms_using_volume = []
    if not conn:
        return vms_using_volume

    try:
        domains = conn.listAllDomains(0)
        for domain in domains:
            # Quick check to avoid parsing XML for every VM
            xml_desc = domain.XMLDesc(0)
            if vol_path not in xml_desc:
                continue

            root = ET.fromstring(xml_desc)
            for disk in root.findall('.//disk'):
                source_element = disk.find('source')
                if source_element is not None:
                    if source_element.get('file') == vol_path or source_element.get('dev') == vol_path:
                        vms_using_volume.append(domain)
                        break  # Found it in this VM, move to the next
    except (libvirt.libvirtError, ET.ParseError) as e:
        logging.error(f"Error finding VMs using volume {vol_path}: {e}")

    return vms_using_volume


def move_volume(conn: libvirt.virConnect, source_pool_name: str, dest_pool_name: str, volume_name: str, new_volume_name: str = None, progress_callback=None, log_callback=None) -> List[str]:
    """
    Moves a storage volume by downloading it to a temporary file and then uploading it to a new volume.
    This is a compatible and safe method for moving volumes across different pools.
    """
    def log_and_callback(message):
        logging.info(message)
        if log_callback:
            log_callback(message)

    if not new_volume_name:
        new_volume_name = volume_name

    source_pool = conn.storagePoolLookupByName(source_pool_name)
    dest_pool = conn.storagePoolLookupByName(dest_pool_name)
    source_vol = source_pool.storageVolLookupByName(volume_name)

    source_info = source_vol.info()
    source_capacity = source_info[1]
    source_format = "qcow2"  # Default
    try:
        source_format = ET.fromstring(source_vol.XMLDesc(0)).findtext("target/format[@type]", "qcow2")
    except (ET.ParseError, libvirt.libvirtError):
        pass  # Use default if XML parsing fails

    new_vol_xml = f"""
    <volume>
        <name>{new_volume_name}</name>
        <capacity>{source_capacity}</capacity>
        <target>
            <format type='{source_format}'/>
        </target>
    </volume>
    """
    new_vol = dest_pool.createXML(new_vol_xml, 0)
    updated_vm_names = []

    # Use a temporary file in the destination pool's directory if possible, else /tmp
    temp_dir = "/tmp"
    try:
        pool_xml = ET.fromstring(dest_pool.XMLDesc(0))
        path_elem = pool_xml.find("target/path")
        if path_elem is not None and os.path.isdir(path_elem.text):
            temp_dir = path_elem.text
    except (ET.ParseError, libvirt.libvirtError):
        pass

    temp_path = os.path.join(temp_dir, f"{new_volume_name}.tmp")
    log_and_callback(f"Using temporary file for transfer: {temp_path}")

    try:
        # 1. Download source volume to the temporary file
        log_and_callback(f"Downloading '{volume_name}' to {temp_path}...")
        downloaded_bytes = 0
        with open(temp_path, "wb") as f:
            stream = conn.newStream(0)
            def stream_writer(stream, data, opaque_file):
                nonlocal downloaded_bytes
                opaque_file.write(data)
                written = len(data)
                downloaded_bytes += written
                if progress_callback and source_capacity > 0:
                    # Download is first 50%
                    progress = (downloaded_bytes / source_capacity) * 50
                    progress_callback(progress)
                return 0
            source_vol.download(stream, 0, source_capacity)
            stream.recvAll(stream_writer, f)
        log_and_callback("Download to temporary file complete.")
        if progress_callback:
            progress_callback(50)

        # 2. Upload from the temporary file to the new volume
        log_and_callback(f"Uploading from {temp_path} to '{new_volume_name}'...")
        uploaded_bytes = 0
        with open(temp_path, "rb") as f:
            stream = conn.newStream(0)
            def stream_reader(stream, nbytes, opaque_file):
                nonlocal uploaded_bytes
                chunk = opaque_file.read(nbytes)
                uploaded_bytes += len(chunk)
                if progress_callback and source_capacity > 0:
                    # Upload is second 50%
                    progress = 50 + (uploaded_bytes / source_capacity) * 50
                    progress_callback(progress)
                return chunk
            new_vol.upload(stream, 0, source_capacity)
            stream.sendAll(stream_reader, f)
        log_and_callback("Upload to new volume complete.")
        if progress_callback:
            progress_callback(100)

        # Update any VM configurations that use this volume
        old_path = source_vol.path()
        new_path = new_vol.path()

        vms_to_update = find_vms_using_volume(conn, old_path)
        if vms_to_update:
            log_and_callback(f"Found {len(vms_to_update)} VM(s) using the volume: {[vm.name() for vm in vms_to_update]}")
            for vm in vms_to_update:
                log_and_callback(f"Updating VM '{vm.name()}' configuration...")
                xml_desc = vm.XMLDesc(0)
                root = ET.fromstring(xml_desc)

                updated = False
                for disk in root.findall('.//disk'):
                    source_element = disk.find('source')
                    if source_element is not None:
                        if source_element.get('file') == old_path:
                            source_element.set('file', new_path)
                            updated = True
                        if source_element.get('dev') == old_path:
                            source_element.set('dev', new_path)
                            updated = True

                if updated:
                    new_xml_desc = ET.tostring(root, encoding='unicode')
                    conn.defineXML(new_xml_desc)
                    updated_vm_names.append(vm.name())
            log_and_callback(f"Updated configurations for VMs: {', '.join(updated_vm_names)}")

        # 3. Delete the original volume after successful copy
        log_and_callback(f"Deleting original volume '{volume_name}'...")
        source_vol.delete(0)
        log_and_callback("Original volume deleted.")

    except Exception as e:
        # If anything fails, try to clean up the newly created (but possibly incomplete) volume
        logging.error(f"An error occurred during volume move: {e}. Cleaning up destination volume.")
        try:
            new_vol.delete(0)
        except libvirt.libvirtError as del_e:
            logging.error(f"Failed to clean up destination volume '{new_volume_name}': {del_e}")
        # Re-raise the original exception
        raise
    finally:
        # 4. Clean up the temporary file in all cases
        if os.path.exists(temp_path):
            os.remove(temp_path)
            log_and_callback(f"Removed temporary file: {temp_path}")

    return updated_vm_names

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
        msg = f"Error deleting storage pool '{pool.name()}': {e}"
        logging.error(msg)
        raise Exception(msg) from e

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

def find_shared_storage_pools(source_conn: libvirt.virConnect, dest_conn: libvirt.virConnect) -> List[Dict[str, Any]]:
    """
    Finds storage pools that are present on both source and destination servers.

    A pool is considered shared if it has the same name, type, and target configuration.
    This is useful for identifying shared storage for live migration.
    The function returns detailed information for each shared pool, including a warning
    if a pool is not active on either server.
    """
    if not source_conn or not dest_conn:
        return []

    source_pools_list = list_storage_pools(source_conn)
    dest_pools_map = {p['name']: p for p in list_storage_pools(dest_conn)}

    def get_pool_details(pool: libvirt.virStoragePool) -> Dict[str, Any] | None:
        """Parse pool XML to get its type and target details for comparison."""
        try:
            xml_desc = pool.XMLDesc(0)
            root = ET.fromstring(xml_desc)
            pool_type = root.get("type")

            target_details = {}
            if pool_type == 'dir':
                path_elem = root.find("target/path")
                if path_elem is not None:
                    target_details['path'] = path_elem.text
            elif pool_type == 'netfs':
                host_elem = root.find("source/host")
                dir_elem = root.find("source/dir")
                if host_elem is not None:
                    target_details['host'] = host_elem.get('name')
                if dir_elem is not None:
                    target_details['path'] = dir_elem.get('path')
            # Other pool types can be added here (e.g., iscsi, rbd)

            return {"type": pool_type, "target": target_details}
        except (libvirt.libvirtError, ET.ParseError) as e:
            logging.warning(f"Could not parse XML for pool {pool.name()}: {e}")
            return None

    shared_pools_info = []
    for source_pool_info in source_pools_list:
        source_name = source_pool_info['name']

        if source_name in dest_pools_map:
            dest_pool_info = dest_pools_map[source_name]

            source_pool = source_pool_info['pool']
            dest_pool = dest_pool_info['pool']

            source_details = get_pool_details(source_pool)
            dest_details = get_pool_details(dest_pool)

            # A pool is shared if its name, type, and target are identical
            if source_details and dest_details and source_details == dest_details:
                warning = ""
                if source_pool_info['status'] != 'active':
                    warning += f"Source pool '{source_name}' is inactive. "
                if dest_pool_info['status'] != 'active':
                    warning += f"Destination pool '{source_name}' is inactive."

                shared_pools_info.append({
                    "name": source_name,
                    "type": source_details.get('type'),
                    "target": source_details.get('target'),
                    "source_status": source_pool_info['status'],
                    "dest_status": dest_pool_info['status'],
                    "warning": warning.strip()
                })

    return shared_pools_info
