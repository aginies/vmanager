"""
Module for managing libvirt storage pools and volumes.
"""
from typing import List, Dict, Any
import logging
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
import libvirt
import threading
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

def find_vms_using_volume(conn: libvirt.virConnect, vol_path: str, vol_name: str) -> List[libvirt.virDomain]:
    """Finds VMs that are using a specific storage volume path by checking different disk types."""
    vms_using_volume = []
    if not conn:
        return vms_using_volume

    try:
        domains = conn.listAllDomains(0)
        for domain in domains:
            # Quick check to avoid parsing XML for every VM if volume name isn't there
            xml_desc = domain.XMLDesc(0)
            if vol_name not in xml_desc:
                continue

            root = ET.fromstring(xml_desc)
            for disk in root.findall('.//disk'):
                source_element = disk.find('source')
                if source_element is None:
                    continue

                # Case 1: Disk path is specified directly
                disk_path = source_element.get('file') or source_element.get('dev')
                if disk_path and disk_path == vol_path:
                    vms_using_volume.append(domain)
                    break  # Found it, move to the next domain

                # Case 2: Disk is specified by pool and volume name
                if disk.get('type') == 'volume':
                    pool_name = source_element.get('pool')
                    volume_name_from_xml = source_element.get('volume')
                    if pool_name and volume_name_from_xml:
                        try:
                            p = conn.storagePoolLookupByName(pool_name)
                            v = p.storageVolLookupByName(volume_name_from_xml)
                            if v.path() == vol_path:
                                vms_using_volume.append(domain)
                                break  # Found it, move to the next domain
                        except libvirt.libvirtError:
                            # This can happen if the pool/volume is not found, which is not necessarily an error to halt on.
                            logging.warning(f"Could not resolve volume '{volume_name_from_xml}' in pool '{pool_name}' for VM '{domain.name()}'.")
                            continue
    except (libvirt.libvirtError, ET.ParseError) as e:
        logging.error(f"Error finding VMs using volume {vol_path}: {e}")

    return vms_using_volume

def check_domain_volumes_in_use(domain: libvirt.virDomain) -> None:
    """
    Check if any volumes used by the domain are in use by other running VMs.
    Raises a ValueError if a volume is in use.
    """
    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)
    conn = domain.connect()

    for disk in root.findall(".//devices/disk"):
        if disk.get("device") != "disk":
            continue
        
        source_elem = disk.find("source")
        if source_elem is None or "pool" not in source_elem.attrib or "volume" not in source_elem.attrib:
            continue

        pool_name = source_elem.get("pool")
        vol_name = source_elem.get("volume")
        try:
            # Check against all other running domains
            for other_domain in conn.listAllDomains(libvirt.VIR_DOMAIN_RUNNING):
                if other_domain.UUIDString() == domain.UUIDString():
                    continue
                
                other_xml = other_domain.XMLDesc(0)
                other_root = ET.fromstring(other_xml)
                for other_disk in other_root.findall(".//devices/disk"):
                    other_source = other_disk.find("source")
                    if (other_source is not None and 
                        other_source.get("pool") == pool_name and 
                        other_source.get("volume") == vol_name):
                        raise ValueError(f"Volume '{vol_name}' is in use by running VM '{other_domain.name()}'")
        except libvirt.libvirtError:
            # Ignore errors during check (e.g., pool not found on other host)
            continue

def move_volume(conn: libvirt.virConnect, source_pool_name: str, dest_pool_name: str, volume_name: str, new_volume_name: str = None, progress_callback=None, log_callback=None) -> List[str]:
    """
    Moves a storage volume using an in-memory pipe for direct streaming.
    This method avoids intermediate disk I/O by streaming data from the source
    to the destination volume concurrently.
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

    # Check for available space before starting the move
    source_info = source_vol.info()
    source_capacity = source_info[1]  # in bytes

    # 1. Check for space in the temporary directory for the pipe
    tmp_dir = tempfile.gettempdir()
    try:
        tmp_free_space = shutil.disk_usage(tmp_dir).free
        if tmp_free_space < source_capacity:
            msg = (f"Not enough space in temporary directory '{tmp_dir}'. "
                   f"Required: {source_capacity // 1024**2} MB, "
                   f"Available: {tmp_free_space // 1024**2} MB.")
            log_and_callback(f"ERROR: {msg}")
            raise Exception(msg)
    except FileNotFoundError:
        log_and_callback(f"WARNING: Could not check disk space for temporary directory '{tmp_dir}'.")

    # Check if the volume is in use by any running VMs before starting the move
    vms_using_volume = find_vms_using_volume(conn, source_vol.path(), source_vol.name())
    running_vms = [vm.name() for vm in vms_using_volume if vm.state()[0] == libvirt.VIR_DOMAIN_RUNNING]

    if running_vms:
        msg = f"Cannot move volume '{volume_name}' because it is in use by running VM(s): {', '.join(running_vms)}."
        log_and_callback(f"ERROR: {msg}")
        raise Exception(msg)

    if vms_using_volume:
        log_and_callback(f"Volume is used by offline VM(s): {[vm.name() for vm in vms_using_volume]}. Their configuration will be updated after the move.")

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

    # Create a pipe for in-memory streaming
    r_fd, w_fd = os.pipe()
    log_and_callback("Starting in-memory stream for volume move...")

    download_thread = None
    upload_thread = None
    download_error = None
    upload_error = None
    download_stream = conn.newStream(0)
    upload_stream = conn.newStream(0)

    try:
        # --- Download Thread ---
        def download_volume_task(stream, write_fd, capacity, callback):
            nonlocal download_error
            try:
                log_and_callback(f"Downloading '{volume_name}'...")
                downloaded_bytes = 0

                def stream_writer_pipe(st, data, opaque_fd):
                    nonlocal downloaded_bytes, download_error
                    try:
                        os.write(opaque_fd, data)
                        downloaded_bytes += len(data)
                        if callback and capacity > 0:
                            progress = (downloaded_bytes / capacity) * 50
                            callback(progress)
                        return 0
                    except Exception as e:
                        logging.error(f"Error in stream writer pipe: {e}")
                        download_error = e
                        return -1  # Abort stream

                source_vol.download(stream, 0, capacity)
                stream.recvAll(stream_writer_pipe, write_fd)

                if download_error:
                    stream.abort()
                else:
                    stream.finish()
                log_and_callback("Download stream finished.")
            except Exception as e:
                logging.error(f"Error in download thread: {e}")

                download_error = e
                stream.abort()
            finally:
                os.close(write_fd)

        # --- Upload Thread ---
        def upload_volume_task(stream, read_fd, capacity, callback):
            nonlocal upload_error
            try:
                log_and_callback(f"Uploading to '{new_volume_name}'...")
                uploaded_bytes = 0

                def stream_reader_pipe(st, nbytes, opaque_fd):
                    nonlocal uploaded_bytes
                    try:
                        chunk = os.read(opaque_fd, nbytes)
                        uploaded_bytes += len(chunk)
                        if callback and capacity > 0:
                            progress = 50 + (uploaded_bytes / capacity) * 50
                            callback(progress)
                        return chunk
                    except Exception as e:
                        logging.error(f"Error in stream reader pipe: {e}")
                        raise e # Propagate error to sendAll

                new_vol.upload(stream, 0, capacity)
                stream.sendAll(stream_reader_pipe, read_fd)
                stream.finish()
                log_and_callback("Upload stream finished.")
            except Exception as e:
                logging.error(f"Error in upload thread: {e}")
                nonlocal upload_error
                upload_error = e
                stream.abort()
            finally:
                os.close(read_fd)

        # Create and start threads
        download_thread = threading.Thread(target=download_volume_task, args=(download_stream, w_fd, source_capacity, progress_callback))
        upload_thread = threading.Thread(target=upload_volume_task, args=(upload_stream, r_fd, source_capacity, progress_callback))

        download_thread.start()
        upload_thread.start()

        download_thread.join()
        upload_thread.join()

        # Check for errors during streaming
        if download_error:
            raise Exception(f"Failed to download volume: {download_error}") from download_error
        if upload_error:
            raise Exception(f"Failed to upload volume: {upload_error}") from upload_error

        log_and_callback("In-memory stream transfer complete.")
        if progress_callback:
            progress_callback(100)

        # Refresh destination pool to make the new volume visible
        log_and_callback(f"Refreshing destination pool '{dest_pool.name()}'...")
        dest_pool.refresh(0)

        # Update any VM configurations that use this volume
        old_path = source_vol.path()
        new_path = new_vol.path()
        old_pool_name = source_pool.name()
        new_pool_name = dest_pool.name()
        
        if vms_using_volume:
            log_and_callback(f"Updating configurations for {len(vms_using_volume)} VM(s)...")
            for vm in vms_using_volume:
                xml_desc = vm.XMLDesc(0)
                root = ET.fromstring(xml_desc)
                updated = False
                for disk in root.findall('.//disk'):
                    source_element = disk.find('source')
                    if source_element is None:
                        continue

                    # Case 1: file or dev
                    if source_element.get('file') == old_path:
                        source_element.set('file', new_path)
                        updated = True
                    if source_element.get('dev') == old_path:
                        source_element.set('dev', new_path)
                        updated = True

                    # Case 2: volume
                    if disk.get('type') == 'volume':
                        if source_element.get('pool') == old_pool_name and source_element.get('volume') == volume_name:
                            source_element.set('pool', new_pool_name)
                            source_element.set('volume', new_volume_name)
                            updated = True
                
                if updated:
                    log_and_callback(f"Updating VM '{vm.name()}' configuration...")
                    conn.defineXML(ET.tostring(root, encoding='unicode'))
                    updated_vm_names.append(vm.name())
            log_and_callback(f"Updated configurations for VMs: {', '.join(updated_vm_names)}")

        # Delete the original volume after successful copy
        log_and_callback(f"Deleting original volume '{volume_name}'...")
        source_vol.delete(0)
        log_and_callback("Original volume deleted.")

        # Refresh source pool to remove the old volume from listings
        log_and_callback(f"Refreshing source pool '{source_pool.name()}'...")
        source_pool.refresh(0)
        log_and_callback("\nMove Finished, you can close this window")

    except Exception as e:
        # If anything fails, try to clean up the newly created (but possibly incomplete) volume
        logging.error(f"An error occurred during volume move: {e}. Cleaning up destination volume.")
        if new_vol:
            try:
                new_vol.delete(0)
            except libvirt.libvirtError as del_e:
                logging.error(f"Failed to clean up destination volume '{new_volume_name}': {del_e}")
        # Re-raise the original exception
        raise
    finally:
        # Abort streams if they are still active
        try:
            if download_stream:
                download_stream.abort()
        except libvirt.libvirtError:
            pass
        try:
            if upload_stream:
                upload_stream.abort()
        except libvirt.libvirtError:
            pass

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

        def _is_default_image_pool(pool: libvirt.virStoragePool) -> bool:
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
                    pass
            return False

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
            source_pool = source_pool_info['pool']

            if _is_default_image_pool(source_pool):
                continue

            if source_name in dest_pools_map:
                dest_pool_info = dest_pools_map[source_name]
                dest_pool = dest_pool_info['pool']

                if _is_default_image_pool(dest_pool):
                    continue

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
