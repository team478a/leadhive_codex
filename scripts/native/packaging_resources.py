"""Build-time manifests: preserve existing privileges and opt into process UTF-8."""

import hashlib
import xml.dom.minidom as DOM


def utf8_manifest(original):
    namespace = "urn:schemas-microsoft-com:asm.v3"
    with DOM.parseString(original) as document:
        root = document.documentElement
        applications = root.getElementsByTagNameNS(namespace, "application")
        if applications:
            application = applications[0]
        else:
            application = document.createElementNS(namespace, "application")
            application.setAttribute("xmlns", namespace)
            root.appendChild(application)
        windows = application.getElementsByTagNameNS(namespace, "windowsSettings")
        if windows:
            settings = windows[0]
        else:
            settings = document.createElementNS(namespace, "windowsSettings")
            settings.setAttribute("xmlns", namespace)
            application.appendChild(settings)
        page_namespace = "http://schemas.microsoft.com/SMI/2019/WindowsSettings"
        pages = settings.getElementsByTagNameNS(page_namespace, "activeCodePage")
        if pages:
            page = pages[0]
            for child in list(page.childNodes):
                page.removeChild(child)
        else:
            page = document.createElementNS(page_namespace, "activeCodePage")
            page.setAttribute("xmlns", page_namespace)
            settings.appendChild(page)
        page.appendChild(document.createTextNode("UTF-8"))
        return document.toxml(encoding="utf-8")


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
