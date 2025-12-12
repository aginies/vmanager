"""
the Cmd line tool
"""
import cmd
import re
import libvirt
from config import load_config
from libvirt_utils import find_all_vm
from vm_actions import start_vm

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
            self.conn = libvirt.open(server_info['uri'])
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
                self.conn.close()
                print("Disconnected.")
                self.conn = None
                self.selected_vms = ""
                self.prompt = '(vmanager) '
            except libvirt.libvirtError as e:
                print(f"Error during disconnection: {e}")
        else:
            print("Not connected.")

    def do_list_vms(self, arg):
        """List all VMs on the connected server."""
        if not self.conn:
            print("Not connected to any server. Use 'connect <server_name>'.")
            return
        try:
            vms = find_all_vm(self.conn)
            if vms:
                print("Available VMs:")
                for vm in vms:
                    print(f"  - {vm}")
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
        """Stops one or more VMs gracefully. Use 'stop --force' for a forced shutdown.
Usage: stop [--force] [vm_name_1] [vm_name_2] ...
If no VM names are provided, it will stop the selected VMs."""
        if not self.conn:
            print("Not connected to any server. Use 'connect <server_name>'.")
            return

        arg_list = args.split()
        force = False
        if '--force' in arg_list:
            force = True
            arg_list.remove('--force')

        vms_to_stop = self._get_vms_to_operate(" ".join(arg_list))
        if not vms_to_stop:
            return

        for vm_name in vms_to_stop:
            try:
                domain = self.conn.lookupByName(vm_name)
                if not domain.isActive():
                    print(f"VM '{vm_name}' is not running.")
                    continue

                if force:
                    domain.destroy()
                    print(f"VM '{vm_name}' force stopped.")
                else:
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

    def do_quit(self, arg):
        """Exit the vmanager shell."""
        if self.conn:
            self.do_disconnect(None)
        return True

    def do_exit(self, arg):
        """Exit the vmanager shell."""
        if self.conn:
            self.do_disconnect(None)
        return True

if __name__ == '__main__':
    VManagerCMD().cmdloop()
