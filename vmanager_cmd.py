"""
the Cmd line tool
"""
import cmd

class VManagerCMD(cmd.Cmd):
    """VManager command-line interface."""
    prompt = '(vmanager) '
    intro = "Welcome to the vmanager command shell. Type help or ? to list commands.\n"

    def do_quit(self, arg):
        """Exit the vmanager shell."""
        return True

    def do_exit(self, arg):
        """Exit the vmanager shell."""
        return True

if __name__ == '__main__':
    VManagerCMD().cmdloop()
