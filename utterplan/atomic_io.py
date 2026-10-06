"""Atomic UTF-8 text file output helpers."""

from __future__ import annotations

import errno
import os
import tempfile
from pathlib import Path

_UNSUPPORTED_FSYNC_ERRNOS = {
    errno.EINVAL,
    getattr(errno, "ENOSYS", errno.EINVAL),
    getattr(errno, "ENOTSUP", errno.EINVAL),
}


def atomic_write_text(path: str | Path, value: str, *, create_parent: bool = False) -> None:
    """Atomically replace *path* with UTF-8 text using a sibling temporary file.

    The existing target is untouched until the complete temporary file has been
    written, flushed, and closed. Parent directories are created only when the
    caller explicitly opts in.
    """
    target = Path(path)
    parent = target.parent
    if create_parent:
        parent.mkdir(parents=True, exist_ok=True)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(value)
            stream.flush()
            try:
                os.fsync(stream.fileno())
            except OSError as exc:
                if exc.errno not in _UNSUPPORTED_FSYNC_ERRNOS:
                    raise
        os.replace(temporary, target)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        finally:
            raise


__all__ = ["atomic_write_text"]
