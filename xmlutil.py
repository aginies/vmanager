"""
parse VM xml file
"""

import xml.etree.ElementTree as ET
import os

#Element.iter(‘tag’) -Iterates over all the child elements(Sub-tree elements)
#Element.findall(‘tag’) -Finds only elements with a tag which are direct children of
# current element
#Element.find(‘tag’) -Finds the first Child with the particular tag.
#Element.get(‘tag’) -Accesses the elements attributes.
#Element.text -Gives the text of the element.
#Element.attrib-returns all the attributes present.
#Element.tag-returns the element name.
# Modify
#Element.set(‘attrname’, ‘value’) – Modifying element attributes.
#Element.SubElement(parent, new_childtag) -creates a new child tag under the parent.
#Element.write(‘filename.xml’)-creates the tree of xml into another file.
#Element.pop() -delete a particular attribute.
#Element.remove() -to delete a complete tag.

def get_vm_machine_firmware_info(xml_content: str) -> dict:
    """
    Extracts machine type and firmware (BIOS/UEFI) from a VM's XML definition.

    Args:
        xml_content (str): The VM's XML definition as a string.

    Returns:
        dict: A dictionary containing 'machine_type' and 'firmware'.
              Returns default values if information is not found.
    """
    machine_type = "N/A"
    firmware = "BIOS" # Default to BIOS

    try:
        root = ET.fromstring(xml_content)

        # Get machine type from the 'machine' attribute of the 'type' element within 'os'
        os_elem = root.find('os')
        if os_elem is not None:
            type_elem = os_elem.find('type')
            if type_elem is not None and 'machine' in type_elem.attrib:
                machine_type = type_elem.get('machine')

        # Determine firmware
        if os_elem is not None:
            loader_elem = os_elem.find('loader')
            if loader_elem is not None and loader_elem.get('type') == 'pflash':
                loader_path = loader_elem.text
                if loader_path:
                    firmware_basename = os.path.basename(loader_path)
                    firmware = f"UEFI {firmware_basename}"
            else:
                bootloader_elem = os_elem.find('bootloader')
                if bootloader_elem is not None:
                    firmware = "BIOS" # Explicitly BIOS if bootloader is present and no pflash loader

    except ET.ParseError:
        pass # Return default values if XML parsing fails

    return {"machine_type": machine_type, "firmware": firmware}
