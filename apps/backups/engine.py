"""
SSH engine: log in to ONE device and read its configuration. It knows nothing about files or the
database - saving the result is the job of services.py.
"""
import logging
import os
import re
import hashlib
from contextlib import contextmanager
import socket
import tempfile
from datetime import datetime
from pathlib import Path
import threading
import time
from dataclasses import dataclass
from importlib.metadata import version as pkg_version
from typing import Optional

from django.conf import settings
from netmiko import ConnectHandler
from paramiko.hostkeys import HostKeyEntry
from netmiko.cisco.cisco_ios import CiscoIosSSH
from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException, ReadTimeout

from apps.core.netguard import resolve_allowed_host
from apps.devices.vendors import ALIASES, get_vendor

logger = logging.getLogger("dbms")

PARAMIKO_VER = pkg_version("paramiko")
PARAMIKO_HINT = (f'Installed paramiko {PARAMIKO_VER} has no SHA-1 SSH algorithms. Run: '
                 'python -m pip install "paramiko==4.0.0" and restart VAULT')
if int(PARAMIKO_VER.split(".")[0]) >= 5:
    logger.warning("paramiko %s cannot connect to old devices (e.g. Cisco IOS 'Cisco-1.25'). "
                   'Fix: python -m pip install "paramiko==4.0.0"', PARAMIKO_VER)

# First lines of CLI error replies (Cisco, Huawei, Junos, MikroTik, Fortinet ...)
BAD_OUTPUT = re.compile(
    r"(?im)^\s*(?:%\s*(?:invalid|incomplete|ambiguous|unrecognized|authorization failed|access denied|bad)\b"
    r"|syntax error|error:|unknown command|unrecognized command|invalid (?:input|command)"
    r"|command (?:authorization )?fail|bad command name|expected end of command)")
MORE = re.compile(r"<?-{2,}\s*more\b[^\r\n]*?-{2,}>?", re.I)          # --More--, ---- More ( Press 'Q' ) ----
MORE_CLEAN = re.compile(r"[ \t]*" + MORE.pattern + r"[\x08 \r]*", re.I)
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


@dataclass
class FetchedConfig:
    text: str
    hostname: Optional[str]      # name read from the config itself
    prompt: str                  # CLI prompt name, used when the config has no hostname


def cli_error(text):
    """First error line if the device replied with an error (or nothing) instead of a config."""
    if not text.strip():
        return "empty reply"
    m = BAD_OUTPUT.search(text[:400])
    return m.group(0).strip() if m else ""


# ---- patience: wait while the device works, give up only when it goes silent ----------------------
class DeviceSilent(ReadTimeout):
    """The device stopped sending data for longer than the idle limit while a command was running."""


class DeviceTooSlow(ReadTimeout):
    """The device kept sending, but one device took longer than the safety ceiling (COMMAND_TIMEOUT)."""


class LoginPacer:
    """Spaces new SSH logins at least `spacing` seconds apart across all worker threads, so a job does not
    start dozens of logins in the same second (busy devices, full VTY lines and the AAA / RADIUS server behind
    the devices then answer late or reject). When the parallel-session limit is the bottleneck it costs nothing."""

    def __init__(self):
        self._lock = threading.Lock()
        self._next = 0.0
        self.override = None                   # the job's second pass uses a wider spacing

    def wait(self, spacing=None):
        spacing = self.override if self.override is not None else (
            settings.LOGIN_SPACING if spacing is None else spacing)
        if spacing <= 0:
            return
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next)
            self._next = slot + spacing
        if slot > now:
            time.sleep(slot - now)

    @contextmanager
    def spacing(self, seconds):
        self.override = seconds
        try:
            yield
        finally:
            self.override = None


LOGIN_PACER = LoginPacer()


@contextmanager
def watch_silence(conn, idle, what="the command"):
    """While active, a read that gets no data for `idle` seconds raises DeviceSilent.

    Netmiko's own read loop (send_command -> read_until_pattern -> read_channel) keeps its prompt detection and
    output cleaning; only the moment of giving up changes: from "N seconds after the command started" to
    "N seconds after the device last sent anything". A slow but working device is never cut off."""
    original = conn.read_channel
    state = {"last": time.monotonic(), "bytes": 0}

    def read_channel():
        data = original()
        now = time.monotonic()
        if data:
            state["last"] = now
            state["bytes"] += len(data)
        elif now - state["last"] > idle:
            raise DeviceSilent(f"The device sent nothing for {idle} seconds while running {what} "
                               f"({state['bytes']} characters received before that).")
        return data

    conn.read_channel = read_channel
    try:
        yield state
    finally:
        try:
            del conn.read_channel              # back to the class method
        except AttributeError:
            conn.read_channel = original


def probe_tcp(host, port, timeout=5):
    """Explain a failed SSH connect: is the TCP port open, refused, or silent (filtered/unreachable)?"""
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return (f"TCP port {port} is open but SSH did not answer in time (slow/old device, VTY lines full, or "
                "slow AAA login). Try DBMS_SSH_TIMEOUT=60 and DBMS_SLOW_DEVICES=1")
    except ConnectionRefusedError:
        return f"TCP port {port} refused: SSH is not enabled on the device, or the port is wrong"
    except (socket.timeout, TimeoutError):
        return f"No reply on TCP port {port}: firewall/ACL blocking this server, routing problem, or wrong IP"
    except OSError as e:
        return f"Cannot reach {host}:{port} ({e.strerror or e})"


def read_paged(conn, cmd, timeout=120, idle=None):
    """Run a command on a device that pages its output and return the whole text (presses space at --More--).
    Keeps waiting while the device sends data; gives up after `idle` seconds of silence (DeviceSilent) or when
    the whole command took longer than `timeout` (DeviceTooSlow)."""
    conn.clear_buffer()
    conn.write_channel(cmd + conn.RETURN)
    prompt, buf, handled = conn.base_prompt, "", 0
    start = last_data = time.monotonic()
    while True:
        now = time.monotonic()
        if now - start > timeout:
            raise DeviceTooSlow(f"The device was still sending after {timeout} seconds while running '{cmd}'")
        if idle and now - last_data > idle:
            raise DeviceSilent(f"The device sent nothing for {idle} seconds while running '{cmd}' "
                               f"({len(buf)} characters received before that).")
        time.sleep(0.15)
        new = conn.read_channel()
        if new:
            buf += new
            last_data = time.monotonic()
        hits = list(MORE.finditer(buf, handled))
        if hits and not buf[hits[-1].end():].strip(" \r\n\x08"):       # marker is the last thing on screen
            conn.write_channel(" ")
            handled = len(buf)
            continue
        last = ANSI.sub("", buf).replace("\r", "").split("\n")[-1].strip()
        if last.startswith(prompt) and last.endswith(("#", ">")):
            lines = ANSI.sub("", MORE_CLEAN.sub("", buf)).replace("\r\n", "\n").replace("\r", "").split("\n")
            return "\n".join(lines[1:-1]).strip("\n")                  # drop echoed command and final prompt


# ---- Which commands may be sent to a device ------------------------------------------------------
# A backup must only READ the configuration. The old guard was a deny-list ("block reload, block
# configure ...") which misses things like `copy running-config tftp://...`, `clear ...`, `ping`,
# `request system reboot` or MikroTik `/system reboot`. We now use an ALLOW-list: the command must
# start with a read-only verb, contain no command chaining, and may only pipe into display filters.
SAFE_START = re.compile(
    r"(?i)^\s*(?:show|display|get|export|/export|/[a-z0-9 /-]+\s+(?:print|export)|more|cat|uci\s+export|"
    r"list|dir|ls|print|tail|head|type)\b")
SAFE_PIPE_FILTERS = {"display", "include", "exclude", "begin", "section", "grep", "egrep", "except", "match",
                     "find", "count", "no-more", "nomore", "more", "last", "trim", "compare", "resolve"}
UNSAFE_COMMAND = re.compile(            # second line of defence behind SAFE_START (kept short to avoid false alarms)
    r"(?i)(?:^|[\s|])(?:configure|system-view|reload|reboot|erase|delete|shutdown|poweroff|tftp|ftp|scp|sftp|"
    r"ssh|telnet|ping|traceroute|undo|redirect|tee)\b")


def command_problem(cmd):
    """Why `cmd` may not be sent to a device, or '' when it is a safe read-only command."""
    if not cmd.strip():
        return "No backup command set for this device type"
    if re.search(r"[\n\r;&`$<>]", cmd):
        return "must be ONE command: no ; & ` $ < > or line breaks"
    if not SAFE_START.search(cmd):
        return "must start with a read-only verb such as show, display, get or export"
    parts = [p.strip() for p in cmd.split("|")]
    for extra in parts[1:]:
        if not extra or extra.split()[0].lower() not in SAFE_PIPE_FILTERS:
            return "may only be piped into display filters (include, exclude, begin, section, display ...)"
    if UNSAFE_COMMAND.search(parts[0]):
        return "contains a command word that can change or disrupt the device"
    return ""


class CiscoIOSNoWidthSSH(CiscoIosSSH):
    """Cisco IOS SSH session setup without the optional terminal-width command.

    Some IOS-like devices do not echo/respond to `terminal width 511`, which makes
    Netmiko's stock preparation time out. We retain channel synchronization and
    prompt discovery, but skip only that optional terminal-width step.
    """
    def session_preparation(self):
        self._test_channel_read()
        self.set_base_prompt()


def connect_with_retry(params, attempts=3):
    """Open the SSH session; retry a dropped handshake, and give a slow login a second, more patient try.

    A timeout (slow device, busy AAA / RADIUS login) is retried ONCE, with DOUBLE the connect / login time.
    A dropped handshake (EOF, reset) is retried up to `attempts` times. Avoids unsupported Netmiko kwargs.
    """
    last_error = None
    slow = (socket.timeout, TimeoutError, NetmikoTimeoutException, ReadTimeout)
    retryable = (EOFError, ConnectionResetError) + slow
    params = dict(params)
    for attempt in range(attempts):
        try:
            LOGIN_PACER.wait()                 # space new logins out across all workers
            if params.get("device_type") == "cisco_ios":
                # Netmiko does not accept `session_preparation=False` as a connection
                # argument. Instantiate a small Cisco IOS subclass instead.
                cisco_params = dict(params)
                cisco_params.pop("device_type", None)
                return CiscoIOSNoWidthSSH(**cisco_params)
            return ConnectHandler(**params)
        except retryable as exc:
            last_error = exc
            if attempt + 1 >= attempts or (isinstance(exc, slow) and attempt >= 1):
                raise
            if isinstance(exc, slow):
                for key in ("conn_timeout", "auth_timeout", "banner_timeout", "blocking_timeout"):
                    if params.get(key):
                        params[key] = params[key] * 2
                logger.warning("Slow SSH login to %s; trying once more with %ss", params.get("host", "device"),
                               params.get("auth_timeout"))
            else:
                logger.warning("Transient SSH handshake disconnect to %s (attempt %s/%s); retrying",
                               params.get("host", "device"), attempt + 1, attempts)
            time.sleep(1.0 * (attempt + 1))
    raise last_error

_KNOWN_HOSTS_LOCK = threading.RLock()
_DEVICE_HOSTKEY_LOCKS = {}
_DEVICE_HOSTKEY_LOCKS_GUARD = threading.Lock()


@contextmanager
def _cross_process_file_lock(lock_path, timeout=60):
    """Lock one device's host-key file across threads and processes (Windows/Linux)."""
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _DEVICE_HOSTKEY_LOCKS_GUARD:
        thread_lock = _DEVICE_HOSTKEY_LOCKS.setdefault(str(lock_path.resolve()), threading.RLock())
    acquired = thread_lock.acquire(timeout=timeout)
    if not acquired:
        raise TimeoutError(f"Timed out waiting for SSH host-key lock: {lock_path.name}")
    stream = None
    try:
        stream = open(lock_path, "a+b")
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            deadline = time.monotonic() + timeout
            while True:
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Timed out waiting for SSH host-key lock: {lock_path.name}")
                    time.sleep(0.1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    finally:
        if stream is not None:
            stream.close()
        thread_lock.release()


def _atomic_write_text(target, text):
    """Write text to `target` through a temp file + rename, so readers never see a half-written file."""
    target = Path(target)
    fd, temp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def device_known_hosts_path(device, connect_host):
    """Return a unique, stable host-key file for this device and endpoint."""
    port = int(device.port or 22)
    identity = f"device={device.pk}|host={str(connect_host).strip().lower()}|port={port}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    root = Path(settings.DATA_DIR) / "hostkeys"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"device-{digest}.known_hosts"


def _prepare_device_known_hosts(device, connect_host, target):
    """Seed a per-device pin file from matching valid legacy entries, never from bad lines."""
    target = Path(target)
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    port = int(device.port or 22)
    expected_names = {str(connect_host), f"[{connect_host}]:{port}"}
    legacy = Path(settings.SSH_KNOWN_HOSTS)
    lines = []
    if legacy.exists():
        try:
            for number, raw in enumerate(legacy.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                stripped = raw.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                try:
                    entry = HostKeyEntry.from_line(stripped, number)
                    if entry and expected_names.intersection(entry.hostnames or []):
                        # Normalize the hostname to the endpoint Paramiko will look up.
                        for name in sorted(expected_names):
                            if name in (entry.hostnames or []):
                                lines.append(HostKeyEntry([name], entry.key).to_line())
                except Exception:
                    # A malformed legacy row is quarantined by the legacy repair command;
                    # it is deliberately not allowed to poison this device's isolated file.
                    continue
        except OSError as exc:
            logger.warning("Could not read legacy SSH known_hosts file: %s", exc)
    if lines:
        _atomic_write_text(target, "\n".join(dict.fromkeys(lines)) + "\n")
    else:
        target.touch(exist_ok=True)
    return target


def repair_known_hosts_file(path=None):
    """Quarantine malformed known_hosts lines while preserving every valid host key.

    This is a format repair only: it does NOT trust, replace, or silently accept a new
    key for a host that already has a valid saved key. Malformed lines are copied to a
    timestamped .corrupt file for inspection before the clean file is atomically replaced.
    """
    target = Path(path or settings.SSH_KNOWN_HOSTS)
    with _KNOWN_HOSTS_LOCK:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.touch()
            return {"valid": 0, "quarantined": 0, "quarantine_file": None}

        try:
            original = target.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            raise RuntimeError(f"Cannot read SSH known_hosts file {target}: {exc}") from exc

        valid_lines, bad_lines = [], []
        for line_number, line in enumerate(original, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                valid_lines.append(line)
                continue
            try:
                entry = HostKeyEntry.from_line(stripped, line_number)
                if entry is None:
                    raise ValueError("Unrecognized known_hosts entry")
                valid_lines.append(line)
            except Exception as exc:
                bad_lines.append(f"# Original line {line_number}; quarantined: {type(exc).__name__}: {exc}")
                bad_lines.append(line)

        quarantine_path = None
        if bad_lines:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            quarantine = target.with_name(target.name + f".corrupt-{stamp}")
            # Exclusive create prevents overwriting a previous quarantine file.
            suffix = 1
            while quarantine.exists():
                quarantine = target.with_name(target.name + f".corrupt-{stamp}-{suffix}")
                suffix += 1
            quarantine.write_text("\n".join(bad_lines) + "\n", encoding="utf-8")
            quarantine_path = str(quarantine)

            _atomic_write_text(target, "\n".join(valid_lines) + "\n" if valid_lines else "")
            logger.warning("Quarantined %s malformed SSH known_hosts line(s) from %s to %s; "
                           "valid host keys were preserved", len(bad_lines) // 2, target, quarantine)

        return {"valid": len(valid_lines), "quarantined": len(bad_lines) // 2,
                "quarantine_file": quarantine_path}


def _remember_host_key(conn, host_key_file):
    """Persist a first-seen key to this device's isolated file only."""
    try:
        conn.remote_conn_pre.save_host_keys(str(host_key_file))
    except Exception:
        # Do not turn a successful read-only SSH session into a backup failure merely
        # because persistence failed; log loudly so the operator can fix permissions.
        logger.warning("Could not save SSH host key to %s", host_key_file, exc_info=True)


def fetch_config(device, approved_ip=None):
    """Log in over SSH, run the read-only backup command and return the config."""
    vendor = get_vendor(device.device_type)
    cmd = (device.command or vendor.cmd or "").strip()
    if not cmd:
        raise ValueError("No backup command set for this device type")
    if problem := command_problem(cmd):
        raise ValueError(f"Backup command blocked by safety guard: {problem}")
    connect_ip = approved_ip or resolve_allowed_host(device.ip)
    if not connect_ip:
        raise ValueError("Device IP/hostname could not be resolved or is a non-routable special-use address")
    timeout = settings.SSH_TIMEOUT
    # Canonicalize legacy database values before Netmiko dispatch. Vendor lookup accepts
    # aliases too, but passing an alias such as "cisco_xe" directly to Netmiko may fail.
    canonical_type = ALIASES.get(device.device_type, device.device_type)
    driver = vendor.driver or canonical_type
    # Connect to the exact address resolved and validated by netguard. Do not
    # resolve the hostname a second time inside Paramiko (DNS-rebinding protection).
    params = dict(device_type=driver, host=connect_ip, username=device.username,
                  password=device.get_password(), port=device.port or 22, conn_timeout=timeout,
                  auth_timeout=timeout, banner_timeout=timeout + 5, blocking_timeout=timeout)
    # Cisco IOS sessions use CiscoIOSNoWidthSSH in connect_with_retry(), which skips
    # only Netmiko's optional terminal-width command. Never pass session_preparation as
    # a constructor keyword; Netmiko BaseConnection does not support that argument.
    if settings.SLOW_DEVICES:
        params.update(fast_cli=False, global_delay_factor=2)
    hostkey_file = None
    hostkey_lock_file = None
    if settings.SSH_HOSTKEY_CHECK:
        # Isolate each device/endpoint. A truncated key for one device can no longer
        # break Paramiko while it loads another device's host keys.
        hostkey_file = device_known_hosts_path(device, connect_ip)
        hostkey_lock_file = hostkey_file.with_suffix(hostkey_file.suffix + ".lock")
        params.update(alt_host_keys=True, alt_key_file=str(hostkey_file))
    secret = device.get_secret()
    if secret:
        params["secret"] = secret

    if hostkey_file is not None:
        # Lock before file preparation and keep the lock through Paramiko's handshake;
        # AutoAddPolicy may write the first-seen key while connect() is in progress.
        with _cross_process_file_lock(hostkey_lock_file):
            _prepare_device_known_hosts(device, connect_ip, hostkey_file)
            repair_known_hosts_file(hostkey_file)
            conn = connect_with_retry(params)
            _remember_host_key(conn, hostkey_file)
    else:
        conn = connect_with_retry(params)

    with conn:
        if driver == "cisco_ios":
            conn.set_base_prompt()
        if secret:
            conn.enable()
        elif vendor.enable and not conn.check_enable_mode():
            try:
                conn.enable()
            except Exception:
                raise ValueError("Logged in without privilege 15 (prompt ends with '>'). Enter the Enable "
                                 "secret for this device, or give the SSH user privilege level 15")
        # Patient read: the ceiling is long (default 1 hour); what really ends a stuck session is silence.
        command_timeout = int(settings.COMMAND_TIMEOUT)
        idle = int(settings.COMMAND_IDLE_SECONDS)
        if driver == "cisco_ios":
            try:
                conn.send_command("terminal length 0", read_timeout=min(timeout, 15))
            except Exception as exc:
                # Paging-aware profiles can still read --More--; do not fail a backup
                # solely because a platform variant rejects the optional terminal command.
                logger.debug("Could not disable paging on %s: %s", device.ip, exc)
        if vendor.paged:
            config = read_paged(conn, cmd, timeout=command_timeout, idle=idle)
        else:
            with watch_silence(conn, idle, f"'{cmd}'"):
                try:
                    config = conn.send_command(cmd, read_timeout=command_timeout)
                except DeviceSilent:
                    raise
                except ReadTimeout as exc:     # Netmiko's own ceiling: data kept coming for the whole time
                    raise DeviceTooSlow(f"The device was still sending after {command_timeout} seconds "
                                        f"while running '{cmd}'") from exc
        if bad := cli_error(config):
            raise ValueError(f"Device rejected the backup command '{cmd}': {bad}")
        hostname = None
        if vendor.name and (m := re.search(vendor.name, config)):
            hostname = m.group(1)
        elif vendor.name_cmd:
            # MikroTik identity print can wrap a multi-character value when the
            # terminal width is narrow (for example A\n h\n s\n a\n n).
            # RouterOS :put [/system identity get name] returns the value directly.
            identity_output = conn.send_command(vendor.name_cmd, read_timeout=15)
            identity_lines = [line.strip() for line in ANSI.sub("", identity_output).replace("\r", "").splitlines()
                              if line.strip()]
            if identity_lines:
                # Ignore an echoed command if a device/driver includes it in the reply.
                identity_lines = [line for line in identity_lines if line.strip() != vendor.name_cmd]
                if identity_lines:
                    hostname = identity_lines[-1].strip().strip('"\'')
        prompt = conn.base_prompt if re.fullmatch(r"[\w.\-]{1,64}", conn.base_prompt or "") else ""
    return FetchedConfig(config, hostname, prompt)


def failure_kind(exc):
    """How a failed backup is handled afterwards (docs/BACKUP_RELIABILITY.md):
    "auth"      login rejected: tried once more (an overloaded AAA / RADIUS server can reject), never in a loop
    "permanent" needs a person (host key changed, command rejected, no privilege, old SSH algorithms ...)
    "transient" anything else (timeouts, silence, dropped sessions, busy device): retried automatically"""
    if isinstance(exc, NetmikoAuthenticationException):
        return "auth"
    text = str(exc)
    if "BadHostKeyException" in type(exc).__name__ or "does not match" in text:
        return "permanent"
    if re.search(r"(?i)no acceptable (kex|host key|cipher|mac)|incompatible ssh peer", text):
        return "permanent"
    if isinstance(exc, ValueError):            # raised by VAULT itself: command rejected / blocked, no privilege
        return "permanent"
    return "transient"


def explain_failure(exc, device):
    """Turn any exception from fetch_config into one short, helpful sentence."""
    if isinstance(exc, NetmikoAuthenticationException):
        return ("Login failed: the device rejected the username or password. Nothing was saved. If the saved login "
                "is right, the device's AAA / RADIUS server may have been busy: VAULT tries once more automatically.")
    text = str(exc).strip()
    first_line = text.splitlines()[0] if text else ""
    if isinstance(exc, DeviceSilent):
        return (f"{first_line} VAULT stopped waiting; the partial output was discarded and nothing was saved. "
                "It is tried again automatically. (Wait longer with DBMS_COMMAND_IDLE_SECONDS.)")
    if isinstance(exc, DeviceTooSlow):
        return (f"{first_line}, the limit for one device. Nothing was saved; it is tried again automatically. "
                "Raise DBMS_COMMAND_TIMEOUT if this device really needs longer.")
    if isinstance(exc, ReadTimeout):
        return ("The device did not answer a command in time (read timed out). Nothing was saved; it is tried "
                "again automatically.")
    if isinstance(exc, NetmikoTimeoutException):
        # Netmiko reports a failed SSH negotiation (e.g. no common key-exchange) as "No existing session"
        if "No existing session" in text:
            return f"SSH negotiation failed; the device may only offer old SSH algorithms. {PARAMIKO_HINT}"
        return f"SSH connection failed: {probe_tcp(device.ip, device.port or 22)} [{first_line[:120] or 'no detail'}]"
    if isinstance(exc, (EOFError, ConnectionResetError)) or re.search(r"(?i)socket is closed|connection (reset|closed)", text):
        return ("The SSH session was closed by the device before the backup finished. The partial output was "
                "discarded and nothing was saved; it is tried again automatically. If it keeps happening, check "
                "the VTY limits and idle timeouts on the device.")
    if "BadHostKeyException" in type(exc).__name__ or "does not match" in text:
        return ("SSH host key CHANGED since first contact (possible man-in-the-middle, or the device was replaced/"
                "re-keyed). Nothing was saved. If expected, delete this device's file in data/hostkeys/ "
                "(or its line in data/known_hosts)")
    logger.exception("Backup of %s failed", device.ip)
    if re.search(r"(?i)no acceptable (kex|host key|cipher|mac)|incompatible ssh peer", text):
        return f"SSH algorithm mismatch: the device only offers old algorithms. {PARAMIKO_HINT}"
    return first_line[:300] or type(exc).__name__
