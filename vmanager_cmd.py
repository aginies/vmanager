"""
the Cmd line tool
"""
import cmd
import re
import libvirt
from config import load_config
from libvirt_utils import find_all_vm
from vm_actions import start_vm, delete_vm, stop_vm, pause_vm, force_off_vm
from connection_manager import ConnectionManager
from storage_manager import list_unused_volumes, list_storage_pools

class VManagerCMD(cmd.Cmd):
    """VManager command-line interface."""
    prompt = '(vmanager) '
    intro = "Welcome to the vmanager command shell. Type help or ? to list commands.\n"

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.servers = self.config.get('servers', [])
        self.server_names = [s['name'] for s in self.servers]
        self.connection_manager = ConnectionManager()
        self.active_connections = {}
        self.selected_vms = {}

    def _update_prompt(self):
        if self.active_connections:
            server_names = ",".join(self.active_connections.keys())

            # Flatten the list of selected VMs from all servers
            all_selected_vms = []
            for vms in self.selected_vms.values():
                all_selected_vms.extend(vms)

            if all_selected_vms:
                self.prompt = f"({server_names}) [{','.join(all_selected_vms)}] "
            else:
                self.prompt = f"({server_names}) "
        else:
            self.prompt = '(vmanager)> '

    def _get_vms_to_operate(self, args):
        vms_to_operate = {}
        args_list = args.split()

        if args_list:
            # If args are provided, find which servers the VMs belong to
            vm_map = {}
            for server_name, conn in self.active_connections.items():
                try:
                    vms_on_server = find_all_vm(conn)
                    for vm_name in vms_on_server:
                        if vm_name not in vm_map:
                            vm_map[vm_name] = []
                        vm_map[vm_name].append(server_name)
                except libvirt.libvirtError:
                    continue

            for vm_name in args_list:
                if vm_name in vm_map:
                    for server_name in vm_map[vm_name]:
                        if server_name not in vms_to_operate:
                            vms_to_operate[server_name] = []
                        vms_to_operate[server_name].append(vm_name)
                else:
                    print(f"Warning: VM '{vm_name}' not found on any connected server.")

        else:
            # If no args, use the pre-selected VMs
            vms_to_operate = self.selected_vms

        if not vms_to_operate:
            print("No VMs specified. Either pass VM names as arguments or select them with 'select_vm'.")
            return None

        return vms_to_operate

    def do_connect(self, args):
        """Connect to one or more servers.
Usage: connect <server_name_1> [<server_name_2> ...] | all"""
        server_names_to_connect = args.split()

        if not server_names_to_connect:
            print("Please specify one or more server names.")
            print(f"Available servers: {', '.join(self.server_names)}")
            return

        if 'all' in server_names_to_connect:
            server_names_to_connect = self.server_names

        for server_name in server_names_to_connect:
            if server_name in self.active_connections:
                print(f"Already connected to '{server_name}'.")
                continue

            server_info = next((s for s in self.servers if s['name'] == server_name), None)

            if not server_info:
                print(f"Server '{server_name}' not found in configuration.")
                continue

            try:
                print(f"Connecting to {server_name} at {server_info['uri']}...")
                conn = self.connection_manager.connect(server_info['uri'])
                if conn:
                    self.active_connections[server_name] = conn
                    print(f"Successfully connected to '{server_name}'.")
                else:
                    print(f"Failed to connect to '{server_name}'.")
            except libvirt.libvirtError as e:
                print(f"Error connecting to {server_name}: {e}")

        self._update_prompt()

    def complete_connect(self, text, line, begidx, endidx):
        """Auto-completion for server names."""
        if not text:
            completions = self.server_names[:]
        else:
            completions = [s for s in self.server_names if s.startswith(text)]
        return completions

    def do_disconnect(self, args):
        """Disconnects from one or more libvirt servers.
Usage: disconnect [<server_name_1> <server_name_2> ...] | all"""
        if not self.active_connections:
            print("Not connected to any servers.")
            return

        servers_to_disconnect = args.split()
        if not servers_to_disconnect or 'all' in servers_to_disconnect:
            servers_to_disconnect = list(self.active_connections.keys())

        for server_name in servers_to_disconnect:
            if server_name in self.active_connections:
                try:
                    conn = self.active_connections[server_name]
                    uri = conn.getURI()
                    self.connection_manager.disconnect(uri)
                    del self.active_connections[server_name]
                    if server_name in self.selected_vms:
                        del self.selected_vms[server_name]
                    print(f"Disconnected from '{server_name}'.")
                except libvirt.libvirtError as e:
                    print(f"Error during disconnection from '{server_name}': {e}")
            else:
                print(f"Not connected to '{server_name}'.")

        self._update_prompt()

    def do_list_vms(self, arg):
        """List all VMs on the connected servers with their status."""
        if not self.active_connections:
            print("Not connected to any server. Use 'connect <server_name>'.")
            return

        for server_name, conn in self.active_connections.items():
            try:
                print(f"\n--- VMs on {server_name} ---")
                domains = conn.listAllDomains(0)
                if domains:
                    print(f"{'VM Name':<30} {'Status':<15}")
                    print(f"{'-'*30} {'-'*15}")

                    status_map = {
                        libvirt.VIR_DOMAIN_NOSTATE: 'No State',
                        libvirt.VIR_DOMAIN_RUNNING: 'Running',
                        libvirt.VIR_DOMAIN_BLOCKED: 'Blocked',
                        libvirt.VIR_DOMAIN_PAUSED: 'Paused',
                        libvirt.VIR_DOMAIN_SHUTDOWN: 'Shutting Down',
                        libvirt.VIR_DOMAIN_SHUTOFF: 'Stopped',
                        libvirt.VIR_DOMAIN_CRASHED: 'Crashed',
                        libvirt.VIR_DOMAIN_PMSUSPENDED: 'Suspended',
                    }

                    sorted_domains = sorted(domains, key=lambda d: d.name())
                    for domain in sorted_domains:
                        status_code = domain.info()[0]
                        status_str = status_map.get(status_code, 'Unknown')
                        print(f"{domain.name():<30} {status_str:<15}")
                else:
                    print("No VMs found on this server.")
            except libvirt.libvirtError as e:
                print(f"Error listing VMs on {server_name}: {e}")

    def do_select_vm(self, args):
        """Select one or more VMs from any connected server. Can use patterns with 're:' prefix.
Usage: select_vm <vm_name_1> <vm_name_2> ...
       select_vm re:<pattern>"""
        if not self.active_connections:
            print("Not connected to any server. Use 'connect <server_name>'.")
            return

        arg_list = args.split()
        if not arg_list:
            print("Usage: select_vm <vm_name_1> <vm_name_2> ... or select_vm re:<pattern>")
            return

        # Master list of all VMs from all connected servers
        # vm_map: {vm_name: [server1, server2, ...]}
        vm_map = {}
        for server_name, conn in self.active_connections.items():
            try:
                vms_on_server = find_all_vm(conn)
                for vm_name in vms_on_server:
                    if vm_name not in vm_map:
                        vm_map[vm_name] = []
                    vm_map[vm_name].append(server_name)
            except libvirt.libvirtError as e:
                print(f"Could not fetch VMs from {server_name}: {e}")
                continue

        # This will hold the names of the VMs to be selected
        vms_to_select_names = set()
        invalid_inputs = []

        for arg in arg_list:
            if arg.startswith("re:"):
                pattern_str = arg[3:]
                try:
                    pattern = re.compile(pattern_str)
                    matched_vms = {vm_name for vm_name in vm_map if pattern.match(vm_name)}
                    if matched_vms:
                        vms_to_select_names.update(matched_vms)
                    else:
                        print(f"Warning: No VMs found matching pattern '{pattern_str}'.")
                except re.error as e:
                    print(f"Error: Invalid regular expression '{pattern_str}': {e}")
                    invalid_inputs.append(arg)
            else:
                if arg in vm_map:
                    vms_to_select_names.add(arg)
                else:
                    invalid_inputs.append(arg)
        
        # Reset selection and populate it based on the names and the vm_map
        self.selected_vms = {}
        for vm_name in sorted(list(vms_to_select_names)):
            for server_name in vm_map[vm_name]:
                if server_name not in self.selected_vms:
                    self.selected_vms[server_name] = []
                self.selected_vms[server_name].append(vm_name)

        if invalid_inputs:
            print(f"Error: The following VMs or patterns were not found or invalid: {', '.join(invalid_inputs)}")

        if self.selected_vms:
            print("Selected VMs:")
            for server, vms in self.selected_vms.items():
                print(f"  on {server}: {', '.join(vms)}")
        else:
            print("No VMs selected.")

        self._update_prompt()

    def complete_select_vm(self, text, line, begidx, endidx):
        """Auto-completion of VM list for select_vm and pattern-based selection."""
        if not self.active_connections:
            return []

        all_vms = set()
        for conn in self.active_connections.values():
            try:
                vms_on_server = find_all_vm(conn)
                all_vms.update(vms_on_server)
            except libvirt.libvirtError:
                continue

        if not text:
            completions = list(all_vms)
        else:
            completions = [f for f in all_vms if f.startswith(text)]
        return completions

    def do_unselect_vm(self, args):
        """Unselect one or more VMs. Can use patterns with 're:' prefix or use 'all' to unselect all.
Usage: unselect_vm <vm_name_1> <vm_name_2> ...
       unselect_vm re:<pattern>
       unselect_vm all"""
        if not self.selected_vms:
            print("No VMs are currently selected.")
            return

        arg_list = args.split()
        if not arg_list:
            print("Usage: unselect_vm <vm_name_1> <vm_name_2> ... or unselect_vm re:<pattern> or unselect_vm all")
            return

        if 'all' in arg_list:
            self.selected_vms = {}
            print("All VMs have been unselected.")
            self._update_prompt()
            return

        # Get a flat list of currently selected VM names
        currently_selected_vms = {vm_name for server_vms in self.selected_vms.values() for vm_name in server_vms}

        vms_to_unselect = set()
        not_found = []

        for arg in arg_list:
            if arg.startswith("re:"):
                pattern_str = arg[3:]
                try:
                    pattern = re.compile(pattern_str)
                    # Find matches within the currently selected VMs
                    matched_vms = {vm_name for vm_name in currently_selected_vms if pattern.match(vm_name)}
                    if matched_vms:
                        vms_to_unselect.update(matched_vms)
                    else:
                        not_found.append(arg)
                except re.error as e:
                    print(f"Error: Invalid regular expression '{pattern_str}': {e}")
            else:
                if arg in currently_selected_vms:
                    vms_to_unselect.add(arg)
                else:
                    not_found.append(arg)

        if not vms_to_unselect:
            print("No matching VMs to unselect found in the current selection.")
            if not_found:
                 print(f"The following VMs/patterns were not found: {', '.join(not_found)}")
            return

        # New dictionary for selected VMs
        new_selected_vms = {}
        for server_name, vm_list in self.selected_vms.items():
            vms_to_keep = [vm for vm in vm_list if vm not in vms_to_unselect]
            if vms_to_keep:
                new_selected_vms[server_name] = vms_to_keep

        self.selected_vms = new_selected_vms

        print(f"Unselected VM(s): {', '.join(sorted(list(vms_to_unselect)))}")
        if not_found:
            print(f"Warning: The following were not found in the selection: {', '.join(not_found)}")

        if self.selected_vms:
            print("Remaining selected VMs:")
            for server, vms in self.selected_vms.items():
                print(f"  on {server}: {', '.join(vms)}")
        else:
            print("No VMs are selected anymore.")

        self._update_prompt()

    def complete_unselect_vm(self, text, line, begidx, endidx):
        """Auto-completion for unselect_vm from the list of selected VMs."""
        if not self.selected_vms:
            return []

        selected_vms_flat = {vm_name for vms_list in self.selected_vms.values() for vm_name in vms_list}

        if not text:
            completions = list(selected_vms_flat)
        else:
            completions = sorted([f for f in selected_vms_flat if f.startswith(text)])
        return completions

    def do_status(self, args):
        """Shows the status of one or more VMs across any connected server.
Usage: status [vm_name_1] [vm_name_2] ...
If no VM names are provided, it will show the status of selected VMs."""
        if not self.active_connections:
            print("Not connected to any server. Use 'connect <server_name>'.")
            return

        vms_to_check = self._get_vms_to_operate(args)
        if not vms_to_check:
            return

        status_map = {
            libvirt.VIR_DOMAIN_NOSTATE: 'No State',
            libvirt.VIR_DOMAIN_RUNNING: 'Running',
            libvirt.VIR_DOMAIN_BLOCKED: 'Blocked',
            libvirt.VIR_DOMAIN_PAUSED: 'Paused',
            libvirt.VIR_DOMAIN_SHUTDOWN: 'Shutting Down',
            libvirt.VIR_DOMAIN_SHUTOFF: 'Stopped',
            libvirt.VIR_DOMAIN_CRASHED: 'Crashed',
            libvirt.VIR_DOMAIN_PMSUSPENDED: 'Suspended',
        }

        for server_name, vm_list in vms_to_check.items():
            print(f"\n--- Status on {server_name} ---")
            conn = self.active_connections[server_name]
            print(f"{'VM Name':<30} {'Status':<15} {'vCPUs':<7} {'Memory (MiB)':<15}")
            print(f"{'-'*30} {'-'*15} {'-'*7} {'-'*15}")

            for vm_name in vm_list:
                try:
                    domain = conn.lookupByName(vm_name)
                    info = domain.info()
                    state_code = info[0]
                    state_str = status_map.get(state_code, 'Unknown')
                    vcpus = info[3]
                    mem_kib = info[2]  # Current memory
                    mem_mib = mem_kib // 1024
                    print(f"{domain.name():<30} {state_str:<15} {vcpus:<7} {mem_mib:<15}")
                except libvirt.libvirtError as e:
                    print(f"Could not retrieve status for '{vm_name}': {e}")

    def complete_status(self, text, line, begidx, endidx):
        return self.complete_select_vm(text, line, begidx, endidx)

    def do_start(self, args):
        """Starts one or more VMs.
Usage: start [vm_name_1] [vm_name_2] ...
If no VM names are provided, it will start the selected VMs."""
        if not self.active_connections:
            print("Not connected to any server. Use 'connect <server_name>'.")
            return

        vms_to_start = self._get_vms_to_operate(args)
        if not vms_to_start:
            return

        for server_name, vm_list in vms_to_start.items():
            print(f"\n--- Starting VMs on {server_name} ---")
            conn = self.active_connections[server_name]
            for vm_name in vm_list:
                try:
                    domain = conn.lookupByName(vm_name)
                    if domain.isActive():
                        print(f"VM '{vm_name}' is already running.")
                        continue
                    start_vm(domain)
                    print(f"VM '{vm_name}' started successfully.")
                except libvirt.libvirtError as e:
                    print(f"Error starting VM '{vm_name}': {e}")
                except Exception as e:
                    print(f"An unexpected error occurred with VM '{vm_name}': {e}")

    def complete_start(self, text, line, begidx, endidx):
        return self.complete_select_vm(text, line, begidx, endidx)

    def do_stop(self, args):
        """Stops one or more VMs gracefully (sends shutdown signal).
For a forced shutdown, use the 'force_off' command.
Usage: stop [vm_name_1] [vm_name_2] ...
If no VM names are provided, it will stop the selected VMs."""
        if not self.active_connections:
            print("Not connected to any server. Use 'connect <server_name>'.")
            return

        vms_to_stop = self._get_vms_to_operate(args)
        if not vms_to_stop:
            return

        for server_name, vm_list in vms_to_stop.items():
            print(f"\n--- Stopping VMs on {server_name} ---")
            conn = self.active_connections[server_name]
            for vm_name in vm_list:
                try:
                    domain = conn.lookupByName(vm_name)
                    if not domain.isActive():
                        print(f"VM '{vm_name}' is not running.")
                        continue

                    stop_vm(domain)
                    print(f"Sent shutdown signal to VM '{vm_name}'.")
                except libvirt.libvirtError as e:
                    print(f"Error stopping VM '{vm_name}': {e}")

    def complete_stop(self, text, line, begidx, endidx):
        return self.complete_select_vm(text, line, begidx, endidx)

    def do_force_off(self, args):
        """Forcefully powers off one or more VMs (like pulling the power plug).
Usage: force_off [vm_name_1] [vm_name_2] ...
If no VM names are provided, it will force off the selected VMs."""
        if not self.active_connections:
            print("Not connected to any server. Use 'connect <server_name>'.")
            return

        vms_to_force_off = self._get_vms_to_operate(args)
        if not vms_to_force_off:
            return

        for server_name, vm_list in vms_to_force_off.items():
            print(f"\n--- Force-off VMs on {server_name} ---")
            conn = self.active_connections[server_name]
            for vm_name in vm_list:
                try:
                    domain = conn.lookupByName(vm_name)
                    if not domain.isActive():
                        print(f"VM '{vm_name}' is not running.")
                        continue
                    force_off_vm(domain)
                    print(f"VM '{vm_name}' forcefully powered off.")
                except libvirt.libvirtError as e:
                    print(f"Error forcefully powering off VM '{vm_name}': {e}")
                except Exception as e:
                    print(f"An unexpected error occurred with VM '{vm_name}': {e}")

    def complete_force_off(self, text, line, begidx, endidx):
        return self.complete_select_vm(text, line, begidx, endidx)

    def do_pause(self, args):
        """Pauses one or more running VMs.
Usage: pause [vm_name_1] [vm_name_2] ...
If no VM names are provided, it will pause the selected VMs."""
        if not self.active_connections:
            print("Not connected to any server. Use 'connect <server_name>'.")
            return

        vms_to_pause = self._get_vms_to_operate(args)
        if not vms_to_pause:
            return

        for server_name, vm_list in vms_to_pause.items():
            print(f"\n--- Pausing VMs on {server_name} ---")
            conn = self.active_connections[server_name]
            for vm_name in vm_list:
                try:
                    domain = conn.lookupByName(vm_name)
                    if not domain.isActive():
                        print(f"VM '{vm_name}' is not running.")
                        continue
                    if domain.info()[0] == libvirt.VIR_DOMAIN_PAUSED:
                        print(f"VM '{vm_name}' is already paused.")
                        continue
                    pause_vm(domain)
                    print(f"VM '{vm_name}' paused.")
                except libvirt.libvirtError as e:
                    print(f"Error pausing VM '{vm_name}': {e}")

    def complete_pause(self, text, line, begidx, endidx):
        return self.complete_select_vm(text, line, begidx, endidx)


    def do_resume(self, args):
        """Resumes one or more paused VMs.
Usage: resume [vm_name_1] [vm_name_2] ...
If no VM names are provided, it will resume the selected VMs."""
        if not self.active_connections:
            print("Not connected to any server. Use 'connect <server_name>'.")
            return

        vms_to_resume = self._get_vms_to_operate(args)
        if not vms_to_resume:
            return

        for server_name, vm_list in vms_to_resume.items():
            print(f"\n--- Resuming VMs on {server_name} ---")
            conn = self.active_connections[server_name]
            for vm_name in vm_list:
                try:
                    domain = conn.lookupByName(vm_name)
                    if domain.info()[0] != libvirt.VIR_DOMAIN_PAUSED:
                        print(f"VM '{vm_name}' is not paused.")
                        continue
                    domain.resume()
                    print(f"VM '{vm_name}' resumed.")
                except libvirt.libvirtError as e:
                    print(f"Error resuming VM '{vm_name}': {e}")

    def complete_resume(self, text, line, begidx, endidx):
        return self.complete_select_vm(text, line, begidx, endidx)

    def do_delete(self, args):
        """Deletes one or more VMs, optionally removing associated storage.
Usage: delete [--force-storage-delete] [vm_name_1] [vm_name_2] ...
Use --force-storage-delete to automatically confirm deletion of associated storage.
If no VM names are provided, it will delete the selected VMs."""
        if not self.active_connections:
            print("Not connected to any server. Use 'connect <server_name>'.")
            return

        args_list = args.split()
        force_storage_delete = "--force-storage-delete" in args_list
        if force_storage_delete:
            args_list.remove("--force-storage-delete")
        
        vms_to_delete = self._get_vms_to_operate(" ".join(args_list))
        if not vms_to_delete:
            return

        # Consolidate all VM names for a single confirmation
        all_vm_names = [vm for vms in vms_to_delete.values() for vm in vms]
        if not all_vm_names:
            return

        vm_list_str = ', '.join(all_vm_names)
        confirm_vm_delete = input(f"Are you sure you want to delete the following VMs: {vm_list_str}? (yes/no): ").lower()
        
        if confirm_vm_delete != 'yes':
            print("VM deletion cancelled.")
            return

        delete_storage_confirmed = False
        if force_storage_delete:
            delete_storage_confirmed = True
        else:
            confirm_storage = input(f"Do you want to delete associated storage for all selected VMs? (yes/no): ").lower()
            if confirm_storage == 'yes':
                delete_storage_confirmed = True

        for server_name, vm_list in vms_to_delete.items():
            print(f"\n--- Deleting VMs on {server_name} ---")
            conn = self.active_connections[server_name]
            for vm_name in vm_list:
                try:
                    domain = conn.lookupByName(vm_name)
                    delete_vm(domain, delete_storage_confirmed)
                    print(f"VM '{vm_name}' deleted successfully.")
                    if delete_storage_confirmed:
                        print(f"Associated storage for '{vm_name}' also deleted.")

                except libvirt.libvirtError as e:
                    print(f"Error deleting VM '{vm_name}': {e}")
                except Exception as e:
                    print(f"An unexpected error occurred with VM '{vm_name}': {e}")

    def complete_delete(self, text, line, begidx, endidx):
        return self.complete_select_vm(text, line, begidx, endidx)

    def do_list_unused_volumes(self, args):
        """Lists all storage volumes that are not attached to any VM.
If pool_name is provided, only checks volumes in that specific pool.
Usage: list_unused_volumes [pool_name]"""
        if not self.active_connections:
            print("Not connected to any server. Use 'connect <server_name>'.")
            return

        pool_name = args.strip() if args else None

        for server_name, conn in self.active_connections.items():
            print(f"\n--- Unused Volumes on {server_name} ---")
            try:
                unused_volumes = list_unused_volumes(conn, pool_name)
                if unused_volumes:
                    print(f"{'Pool':<20} {'Volume Name':<30} {'Path':<50} {'Capacity (MiB)':<15}")
                    print(f"{'-'*20} {'-'*30} {'-'*50} {'-'*15}")
                    for vol in unused_volumes:
                        pool_name_vol = vol.storagePoolLookupByVolume().name()
                        info = vol.info()
                        capacity_mib = info[1] // (1024 * 1024)
                        print(f"{pool_name_vol:<20} {vol.name():<30} {vol.path():<50} {capacity_mib:<15}")
                else:
                    print("No unused volumes found on this server.")
            except libvirt.libvirtError as e:
                print(f"Error listing unused volumes on {server_name}: {e}")
            except Exception as e:
                print(f"An unexpected error occurred on {server_name}: {e}")

    def do_list_pool(self, args):
        """Lists all storage pools on the connected servers.
Usage: list_pool"""
        if not self.active_connections:
            print("Not connected to any server. Use 'connect <server_name>'.")
            return

        for server_name, conn in self.active_connections.items():
            print(f"\n--- Storage Pools on {server_name} ---")
            try:
                pools_info = list_storage_pools(conn)
                if pools_info:
                    print(f"{'Pool Name':<30} {'Status':<15} {'Capacity (GiB)':<15} {'Allocation (GiB)':<15}")
                    print(f"{'-'*30} {'-'*15} {'-'*15} {'-'*15}")
                    for pool_info in pools_info:
                        capacity_gib = pool_info['capacity'] // (1024*1024*1024)
                        allocation_gib = pool_info['allocation'] // (1024*1024*1024)
                        print(f"{pool_info['name']:<30} {pool_info['status']:<15} {capacity_gib:<15} {allocation_gib:<15}")
                else:
                    print("No storage pools found on this server.")
            except libvirt.libvirtError as e:
                print(f"Error listing storage pools on {server_name}: {e}")
            except Exception as e:
                print(f"An unexpected error occurred on {server_name}: {e}")

    def complete_list_unused_volumes(self, text, _, _b, _e):
        """Auto-completion for pool names in list_unused_volumes command."""
        if not self.active_connections:
            return []

        all_pool_names = set()
        for conn in self.active_connections.values():
            try:
                pools_info = list_storage_pools(conn)
                pool_names = {pool_info["name"] for pool_info in pools_info}
                all_pool_names.update(pool_names)
            except libvirt.libvirtError:
                continue

        if not text:
            return list(all_pool_names)
        else:
            return [pool for pool in all_pool_names if pool.startswith(text)]

    def do_quit(self, arg):
        """Exit the vmanager shell."""
        # Disconnect all connections when quitting
        self.connection_manager.disconnect_all()
        print("\nExiting vmanager.")
        return True

if __name__ == '__main__':
    VManagerCMD().cmdloop()
