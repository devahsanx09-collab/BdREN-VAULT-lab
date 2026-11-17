"""
Supported platforms. To add a new vendor, add ONE line to VENDORS below - nothing else needs to change.

Regular expressions that read the device name out of a config use group 1 as the name.
"""
import re
from dataclasses import dataclass
from typing import Optional

HOST = r'(?mi)^\s*hostname\s+"?([^\s"]+)'                  # Cisco, BDCOM, V-SOL, TP-Link, Arista ...
SYSN = r"(?mi)^\s*sysname\s+(\S+)"                          # Huawei
JUNOS = r"(?mi)^\s*(?:set\s+system\s+)?host-name\s+([^\s;]+)"
FORTI = r'(?mi)^\s*set hostname\s+"?([^\s"]+)'

HOSTRX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,252}$")   # IPv4 address or DNS hostname
# Names used by earlier versions -> current keys
ALIASES = {"cisco": "cisco_ios", "cisco_xe": "cisco_ios", "juniper": "juniper_junos", "huawei_vrp": "huawei"}


@dataclass(frozen=True)
class Vendor:
    """One supported platform.

    driver   - Netmiko platform to log in with (defaults to the key); BDCOM / V-SOL reuse the Cisco-style driver
    enable   - needs privileged (enable) mode before the backup command
    paged    - device pages long output with --More--, read it page by page
    name_cmd - extra command to read the device name when the config does not contain it (MikroTik)
    """
    label: str
    group: str
    cmd: Optional[str]
    name: Optional[str] = HOST
    driver: Optional[str] = None
    enable: bool = False
    paged: bool = False
    name_cmd: Optional[str] = None
    hint: str = ""


# key (stored in the database) -> platform. Order = order in the Device type menu.
VENDORS = {
    "cisco_ios": Vendor("Cisco IOS / IOS-XE", "Cisco", "show running-config", enable=True,
                        hint="Privilege 15 is detected automatically. Enable password is optional; enter it only if the device prompts for one."),
    "cisco_nxos": Vendor("Cisco NX-OS (Nexus)", "Cisco", "show running-config"),
    "cisco_asa": Vendor("Cisco ASA", "Cisco", "show running-config", enable=True),
    "huawei": Vendor("Huawei VRP (S / AR / CloudEngine)", "Huawei", "display current-configuration", SYSN),
    "huawei_smartax": Vendor("Huawei OLT (MA56xx / MA58xx)", "Huawei", "display current-configuration", SYSN,
                             paged=True, hint="Large OLT configs can take a minute to read."),
    "juniper_junos": Vendor("Juniper Junos", "Juniper", "show configuration | display set", JUNOS,
                            hint="The user needs permission to run 'show configuration'."),
    "bdcom": Vendor("BDCOM Switch / OLT", "BDCOM", "show running-config", driver="cisco_ios", enable=True,
                    paged=True, hint="BDCOM uses a Cisco-style CLI. Privilege mode is detected automatically; Enable password is optional and is used only if prompted."),
    "vsol": Vendor("V-SOL OLT / Switch", "V-SOL", "show running-config", driver="cisco_ios", enable=True,
                   paged=True, hint="V-SOL uses a Cisco-style CLI. Enable password is optional and is used only if prompted."),
    "omada": Vendor("TP-Link Omada / JetStream Switch", "TP-Link Omada", "show running-config",
                    driver="tplink_jetstream", enable=True, paged=True,
                    hint="SSH must be enabled on the switch. Fill in the Enable password only if one is set."),
    "mikrotik_routeros": Vendor("MikroTik RouterOS", "MikroTik", "/export", None,
                                name_cmd=":put [/system identity get name]", hint="If login fails, try the username 'admin+ct'."),
    "arista_eos": Vendor("Arista EOS", "Arista", "show running-config", enable=True),
    "hp_comware": Vendor("HPE Comware", "HPE", "display current-configuration", SYSN),
    "fortinet": Vendor("Fortinet FortiOS", "Fortinet", "show full-configuration", FORTI),
    "other": Vendor("Other (generic SSH)", "Other", None, None, driver="generic",
                    hint="Enter the backup command in Custom command."),
}


def get_vendor(device_type):
    """Vendor for a stored device type (old aliases accepted, unknown types fall back to 'other')."""
    return VENDORS.get(ALIASES.get(device_type, device_type), VENDORS["other"])


def vendor_menu():
    """[(primary key, vendor name)] - one entry per vendor group, in menu order. Sub-platforms (NX-OS, ASA,
    Huawei OLT) stay valid for devices that already use them but are not offered as separate choices."""
    seen, out = set(), []
    for key, v in VENDORS.items():
        if v.group not in seen:
            seen.add(v.group)
            out.append((key, v.label if key == "other" else v.group))
    return out


def vendor_meta():
    """Vendor names and hints for the browser (the Device type menu and the Type column)."""
    return {k: {"label": v.label, "group": v.group, "hint": v.hint} for k, v in VENDORS.items()}
