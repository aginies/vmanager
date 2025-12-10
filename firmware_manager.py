"""
Module for managing firmware-related information and operations.
"""
import os
import json
import libvirt
import xml.etree.ElementTree as ET

FIRMWARE_META_BASE_DIR = "/usr/share/qemu/firmware/"


class Firmware:
    """
    firmware class
    """
    def __init__(self):
        """
        Set default values
        """
        self.executable = None
        self.nvram_template = None
        self.architectures = []
        self.features = []
        self.interfaces = []

    def load_from_json(self, jsondata):
        """
        Initialize object from a json firmware description
        """
        if "interface-types" in jsondata:
            self.interfaces = jsondata['interface-types']
        else:
            return False

        if 'mapping' in jsondata:
            if 'executable' in jsondata['mapping'] and 'filename' in jsondata['mapping']['executable']:
                self.executable = jsondata['mapping']['executable']['filename']
            elif 'filename' in jsondata['mapping']:
                self.executable = jsondata['mapping']['filename']
            if 'nvram-template' in jsondata['mapping'] and 'filename' in jsondata['mapping']['nvram-template']:
                self.nvram_template = jsondata['mapping']['nvram-template']['filename']

        if self.executable is None:
            return False

        if 'features' in jsondata:
            for feat in jsondata['features']:
                self.features.append(feat)

        if 'targets' in jsondata:
            for target in jsondata['targets']:
                self.architectures.append(target['architecture'])

        if not self.architectures:
            return False

        return True


def get_uefi_files():
    """
    Scans for UEFI firmware json description files and returns a list of firmware capabilities.
    """
    uefi_files = []
    if not os.path.isdir(FIRMWARE_META_BASE_DIR):
        return uefi_files

    for file in os.listdir(FIRMWARE_META_BASE_DIR):
        if file.endswith(".json"):
            full_path = os.path.join(FIRMWARE_META_BASE_DIR, file)
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    jsondata = json.load(f)

                firmware = Firmware()
                if firmware.load_from_json(jsondata):
                    uefi_files.append(firmware)
            except (json.JSONDecodeError, IOError):
                # ignore malformed or unreadable files
                continue

    return uefi_files

def get_host_sev_capabilities(conn):
    """
    Checks if the host supports AMD SEV and SEV-ES.
    """
    sev_caps = {'sev': False, 'sev-es': False}
    if conn is None:
        return sev_caps
    try:
        caps_xml = conn.getCapabilities()
        root = ET.fromstring(caps_xml)
        sev_elem = root.find('.//host/cpu/sev')
        if sev_elem is not None:
            sev_caps['sev'] = True

        guest_arch = root.find(".//guest/arch[@name='x86_64']")
        if guest_arch is not None:
            features = guest_arch.find('features')
            if features is not None:
                if features.find('sev-es') is not None:
                    sev_caps['sev-es'] = True
    except (libvirt.libvirtError, ET.ParseError):
        pass
    return sev_caps
