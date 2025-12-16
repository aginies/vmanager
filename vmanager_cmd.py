"""
the Cmd line tool
"""
import cmd
import re
import libvirt
from config import load_config
from libvirt_utils import find_all_vm
from vm_actions import start_vm, delete_vm
from connection_manager import ConnectionManager
from storage_manager import list_unused_volumes

class VManagerCMD(cmd.Cmd):
    """VManager command-line interface."""
    prompt = '(vmanager) '
    intro = "Welcome to the vmanager command shell. Type help or ? to list commands.\n"

    def __init__(self):
        super().__init__()
        self.conn = None
        self.config = load_config()
        self.servers = self.config.get('servers', [])
        self.server_names = [s['name'] for s in self.servers]
        self.selected_vms = []
        self.connection_manager = ConnectionManager()

    def _update_prompt(self):
        if self.conn:
            server_name = next((s['name'] for s in self.servers if s['uri'] == self.conn.getURI()), "vmanager")
            if self.selected_vms:
                self.prompt = f"({server_name}) [{','.join(self.selected_vms)}] "
            else:
                self.prompt = f"({server_name}) "
        else:
            self.prompt = '(vmanager)> '

    def _get_vms_to_operate(self, args):
        vms_to_operate = args.split()
        if not vms_to_operate:
            vms_to_operate = self.selected_vms

        if not vms_to_operate:
            print("No VMs specified. Either pass VM names as arguments or select them with 'select_vm'.")
            return None
        return vms_to_operate

    def do_connect(self, server_name):
        """Connect to a server.
Usage: connect <server_name>"""
        if not server_name:
            print("Please specify a server name.")
            print(f"Available servers: {', '.join(self.server_names)}")
            return

        if self.conn:
            print(f"Already connected to {self.prompt}. Please disconnect first.")
            return

        server_info = next((s for s in self.servers if s['name'] == server_name), None)

        if not server_info:
            print(f"Server '{server_name}' not found in configuration.")
            return

        try:
            print(f"Connecting to {server_name} at {server_info['uri']}...")
            # Use ConnectionManager to handle connection
            self.conn = self.connection_manager.connect(server_info['uri'])
            if self.conn is None:
                print(f"Failed to connect to {server_name}")
                return
            self.prompt = f"({server_name}) "
            print("Connection successful.")
            self._update_prompt()
        except libvirt.libvirtError as e:
            print(f"Error connecting to {server_name}: {e}")
            self.conn = None

    def complete_connect(self, text, line, begidx, endidx):
        """Auto-completion for server names."""
        if not text:
            completions = self.server_names[:]
        else:
            completions = [s for s in self.server_names if s.startswith(text)]
        return completions

    def do_disconnect(self, arg):
        """Disconnects from the libvirt server."""
        if self.conn:
            try:
                # Use ConnectionManager to handle disconnection
                uri = self.conn.getURI()
                self.connection_manager.disconnect(uri)
                print("Disconnected.")
                self.conn = None
                self.selected_vms = []
                self.prompt = '(vmanager) '
            except libvirt.libvirtError as e:
                print(f"Error during disconnection: {e}")
        else:
            print("Not connected.")

    def do_list_vms(self, arg):
        """List all VMs on the connected server with their status."""
        if not self.conn:
            print("Not connected to any server. Use 'connect <server_name>'.")
            return
        try:
            domains = self.conn.listAllDomains(0)
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
                print("No VMs found.")
        except libvirt.libvirtError as e:
            print(f"Error listing VMs: {e}")

    def do_select_vm(self, args):
        """Select one/some VM from the list. Can use patterns with 're:' prefix.
Usage: select_vm <vm_name_1> <vm_name_2> ...
       select_vm re:<pattern>"""
        if not self.conn:
            print("Not connected to any server. Use 'connect <server_name>'.")
            return

        all_vms = find_all_vm(self.conn)
        vms_to_select = []
        invalid_inputs = []

        arg_list = args.split()
        if not arg_list:
            print("Usage: select_vm <vm_name_1> <vm_name_2> ... or select_vm re:<pattern>")
            return

        for arg in arg_list:
            if arg.startswith("re:"):
                pattern_str = arg[3:]
                try:
                    pattern = re.compile(pattern_str)
                    matched_vms = [vm for vm in all_vms if pattern.match(vm)]
                    if matched_vms:
                        vms_to_select.extend(matched_vms)
                    else:
                        print(f"Warning: No VMs found matching pattern '{pattern_str}'.")
                except re.error as e:
                    print(f"Error: Invalid regular expression '{pattern_str}': {e}")
                    invalid_inputs.append(arg)
            else:
                if arg in all_vms:
                    vms_to_select.append(arg)
                else:
                    invalid_inputs.append(arg)

        # Remove duplicates and sort for consistent selection
        self.selected_vms = sorted(list(set(vms_to_select)))

        if invalid_inputs:
            print(f"Error: The following VMs or patterns were not found or invalid: {', '.join(invalid_inputs)}")

        if self.selected_vms:
            print(f"Selected VMs: {', '.join(self.selected_vms)}")
        else:
            print("No VMs selected.")
        self._update_prompt()

    def complete_select_vm(self, text, line, begidx, endidx):
        """Auto-completion of VM list for select_vm and pattern-based selection."""
        if not self.conn:
            return []

        try:
            list_allvms = find_all_vm(self.conn)
            if not text:
                completions = list_allvms[:]
            else:
                completions = [f for f in list_allvms if f.startswith(text)]
            return completions
        except libvirt.libvirtError:
            return []

    def do_status(self, args):
        """Shows the status of one or more VMs.
Usage: status [vm_name_1] [vm_name_2] ...
If no VM names are provided, it will show the status of selected VMs."""
        if not self.conn:
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

        print(f"{'VM Name':<30} {'Status':<15} {'vCPUs':<7} {'Memory (MiB)':<15}")
        print(f"{'-'*30} {'-'*15} {'-'*7} {'-'*15}")

        for vm_name in vms_to_check:
            try:
                domain = self.conn.lookupByName(vm_name)
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
        if not self.conn:
            print("Not connected to any server. Use 'connect <server_name>'.")
            return

        vms_to_start = self._get_vms_to_operate(args)
        if not vms_to_start:
            return

        for vm_name in vms_to_start:
            try:
                domain = self.conn.lookupByName(vm_name)
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
        if not self.conn:
            print("Not connected to any server. Use 'connect <server_name>'.")
            return

        vms_to_stop = self._get_vms_to_operate(args)
        if not vms_to_stop:
            return

        for vm_name in vms_to_stop:
            try:
                domain = self.conn.lookupByName(vm_name)
                if not domain.isActive():
                    print(f"VM '{vm_name}' is not running.")
                    continue

                domain.shutdown()
                print(f"Sent shutdown signal to VM '{vm_name}'.")
            except libvirt.libvirtError as e:
                print(f"Error stopping VM '{vm_name}': {e}")

    def complete_stop(self, text, line, begidx, endidx):
        return self.complete_select_vm(text, line, begidx, endidx)

    def do_force_off(self, args):
        """Forcefully powers off one or more VMs (like pulling the power plug).
Usage: force_off [vm_name_1] [vm_name_2] ...
If no VM names are provided, it will force off the selected VMs."""
        if not self.conn:
            print("Not connected to any server. Use 'connect <server_name>'.")
            return

        vms_to_force_off = self._get_vms_to_operate(args)
        if not vms_to_force_off:
            return

        for vm_name in vms_to_force_off:
            try:
                domain = self.conn.lookupByName(vm_name)
                if not domain.isActive():
                    print(f"VM '{vm_name}' is not running.")
                    continue
                domain.destroy()
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
        if not self.conn:
            print("Not connected to any server. Use 'connect <server_name>'.")
            return

        vms_to_pause = self._get_vms_to_operate(args)
        if not vms_to_pause:
            return

        for vm_name in vms_to_pause:
            try:
                domain = self.conn.lookupByName(vm_name)
                if not domain.isActive():
                    print(f"VM '{vm_name}' is not running.")
                    continue
                if domain.info()[0] == libvirt.VIR_DOMAIN_PAUSED:
                    print(f"VM '{vm_name}' is already paused.")
                    continue
                domain.suspend()
                print(f"VM '{vm_name}' paused.")
            except libvirt.libvirtError as e:
                print(f"Error pausing VM '{vm_name}': {e}")

    def complete_pause(self, text, line, begidx, endidx):
        return self.complete_select_vm(text, line, begidx, endidx)


    def do_resume(self, args):
        """Resumes one or more paused VMs.
Usage: resume [vm_name_1] [vm_name_2] ...
If no VM names are provided, it will resume the selected VMs."""
        if not self.conn:
            print("Not connected to any server. Use 'connect <server_name>'.")
            return

        vms_to_resume = self._get_vms_to_operate(args)
        if not vms_to_resume:
            return

        for vm_name in vms_to_resume:
            try:
                domain = self.conn.lookupByName(vm_name)
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
        if not self.conn:
            print("Not connected to any server. Use 'connect <server_name>'.")
            return

        # Parse arguments for --force-storage-delete
        args_list = args.split()
        force_storage_delete = False
        if "--force-storage-delete" in args_list:
            force_storage_delete = True
            args_list.remove("--force-storage-delete")
        
        vms_to_delete = self._get_vms_to_operate(" ".join(args_list))
        if not vms_to_delete:
            return

        # Single confirmation for VM deletion
        if len(vms_to_delete) > 1:
            vm_list_str = ', '.join(vms_to_delete)
            confirm_vm_delete = input(f"Are you sure you want to delete the following VMs: {vm_list_str}? (yes/no): ").lower()
        else:
            confirm_vm_delete = input(f"Are you sure you want to delete VM '{vms_to_delete[0]}'? (yes/no): ").lower()
        
        if confirm_vm_delete != 'yes':
            print("VM deletion cancelled.")
            return

        delete_storage_confirmed = False
        if force_storage_delete:
            delete_storage_confirmed = True
        else:
            if len(vms_to_delete) > 1:
                confirm_storage = input(f"Do you want to delete associated storage for all selected VMs ({len(vms_to_delete)} VMs)? (yes/no): ").lower()
            else:
                confirm_storage = input(f"Do you want to delete associated storage for '{vms_to_delete[0]}'? (yes/no): ").lower()
            
            if confirm_storage == 'yes':
                delete_storage_confirmed = True
        
        for vm_name in vms_to_delete:
            try:
                domain = self.conn.lookupByName(vm_name)
                
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
Usage: list_unused_volumes [pool_name]"
Usage: list_unused_volumes"""
        if not self.conn:
            print("Not connected to any server. Use 'connect <server_name>'.")
            return

        try:
            unused_volumes = list_unused_volumes(self.conn, None)

            if unused_volumes:
                print(f"{'Pool':<20} {'Volume Name':<30} {'Path':<50} {'Capacity':<15}")
                print(f"{'-'*20} {'-'*30} {'-'*50} {'-'*15}")
                for vol in unused_volumes:
                    pool_name = vol.storagePoolLookupByVolume().name()
                    info = vol.info()
                    capacity_mib = info[1] // (1024 * 1024)
                    print(f"{pool_name:<20} {vol.name():<30} {vol.path():<50} {capacity_mib:<15} MiB")
            else:
                print("No unused volumes found.")

        except libvirt.libvirtError as e:
            print(f"Error listing unused volumes: {e}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")

    def do_quit(self, arg):
        """Exit the vmanager shell."""
        if self.conn:
            self.do_disconnect(None)
        # Disconnect all connections when quitting
        self.connection_manager.disconnect_all()
        return True

    def do_exit(self, arg):
        """Exit the vmanager shell."""
        if self.conn:
            self.do_disconnect(None)
        # Disconnect all connections when quitting
        self.connection_manager.disconnect_all()
        return True

if __name__ == '__main__':
    VManagerCMD().cmdloop()