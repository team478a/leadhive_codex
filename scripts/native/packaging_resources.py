"""Build-time manifests: preserve existing privileges and opt into process UTF-8."""

import hashlib
import xml.etree.ElementTree as ET


def utf8_manifest(original):
    tree = ET.fromstring(original)
    namespace = "urn:schemas-microsoft-com:asm.v3"
    application = tree.find(f"{{{namespace}}}application")
    if application is None:
        application = ET.SubElement(tree, f"{{{namespace}}}application")
    settings = application.find(f"{{{namespace}}}windowsSettings")
    if settings is None:
        settings = ET.SubElement(application, f"{{{namespace}}}windowsSettings")
    tag = "{http://schemas.microsoft.com/SMI/2019/WindowsSettings}activeCodePage"
    page = settings.find(tag)
    if page is None:
        page = ET.SubElement(settings, tag)
    page.text = "UTF-8"
    return ET.tostring(tree, encoding="utf-8", xml_declaration=True)


def configure_postgres(directory):
    from PyInstaller.utils.win32.winmanifest import (
        read_manifest_from_executable,
        write_manifest_to_executable,
    )

    adjustments = []
    for exe in directory.glob("*.exe"):
        original = read_manifest_from_executable(str(exe))
        if isinstance(original, tuple):
            original = original[1]
        before = hashlib.sha256(exe.read_bytes()).hexdigest()
        write_manifest_to_executable(str(exe), utf8_manifest(original))
        adjustments.append(
            {
                "file": exe.name,
                "original_sha256": before,
                "adjustment": "Windows activeCodePage UTF-8; existing privileges preserved",
            }
        )
    return adjustments
