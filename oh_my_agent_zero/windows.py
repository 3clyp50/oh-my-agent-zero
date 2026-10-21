"""Windows storage equivalents for upstream's POSIX atomic-write operations."""

import os
from pathlib import Path
import stat
import tempfile


def move_atomic(source, destination, *, replace):
    import ctypes
    from ctypes import wintypes

    move = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
    move.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    move.restype = wintypes.BOOL
    # WRITE_THROUGH plus optional REPLACE_EXISTING; both files are on the same volume.
    if not move(str(source), str(destination), 8 | int(replace)):
        raise ctypes.WinError(ctypes.get_last_error())


def write_text_atomic(path, content):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(content.encode("utf-8", "replace").decode("utf-8"))
            output.flush()
            os.fsync(output.fileno())
        move_atomic(temporary, target, replace=True)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_stream_atomic(source, target_path, *, max_bytes=None):
    from helpers.file_transfers import copy_stream

    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    previous = target.lstat() if target.exists() or target.is_symlink() else None
    if previous and not stat.S_ISREG(previous.st_mode):
        raise ValueError("Choose a regular destination file.")
    descriptor, temporary = tempfile.mkstemp(prefix=".partial-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            result = copy_stream(source, output, max_bytes)
            output.flush()
            os.fsync(output.fileno())
        if previous:
            os.chmod(temporary, stat.S_IMODE(previous.st_mode))
            current = target.lstat()
            if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
                previous.st_dev, previous.st_ino, previous.st_size, previous.st_mtime_ns
            ):
                raise ValueError("The destination changed during upload. Try again.")
        move_atomic(temporary, target, replace=previous is not None)
        return result
    finally:
        Path(temporary).unlink(missing_ok=True)
