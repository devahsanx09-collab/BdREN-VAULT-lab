"""Secret key files. Pure Python on purpose: settings.py imports this before Django is configured."""
import os


def load_or_create_key(path, make):
    """Read a secret from disk, creating it (owner-only permissions) on first start."""
    if not path.exists():
        # Created owner-only from the first byte (not written first and restricted afterwards, which left a
        # moment when other accounts on the server could read the new key).
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:            # another process created it in the meantime
            return path.read_bytes()
        with os.fdopen(fd, "wb") as stream:
            stream.write(make())
        try:
            os.chmod(path, 0o600)
        except OSError:        # not supported on every filesystem (e.g. Windows)
            pass
    return path.read_bytes()
