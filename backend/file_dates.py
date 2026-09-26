"""Folder arrival dates, using macOS Date Added rather than document edits."""
import ctypes
import os
import struct
import sys
from functools import lru_cache

class _Attributes(ctypes.Structure):
    _fields_ = [('count', ctypes.c_uint16), ('reserved', ctypes.c_uint16)] + [
        (name, ctypes.c_uint32) for name in ('common', 'volume', 'directory', 'file', 'fork')]

@lru_cache(maxsize=1)
def _reader():
    if sys.platform != 'darwin':return None
    try:
        fn = ctypes.CDLL(None, use_errno=True).getattrlist
        fn.argtypes = [ctypes.c_char_p, ctypes.POINTER(_Attributes), ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong]
        fn.restype = ctypes.c_int
        return fn
    except AttributeError:return None

def added_time(path, stat):
    fn = _reader()
    if fn:
        # sys/attr.h: ATTR_CMN_ADDEDTIME; returned timespec has 4-byte packing.
        attrs = _Attributes(5, 0, 0x10000000, 0, 0, 0, 0)
        buffer = ctypes.create_string_buffer(20)
        if fn(os.fsencode(path), ctypes.byref(attrs), buffer, len(buffer), 1) == 0:
            length, seconds, nanos = struct.unpack('=Iqq', buffer.raw)
            if length == 20 and seconds > 0 and 0 <= nanos < 1000000000:
                return seconds + nanos / 1000000000, 'date_added'
    # Some file systems do not record arrival dates. Disclose the fallback.
    birth = getattr(stat, 'st_birthtime', 0)
    return (birth, 'created') if birth > 0 else (stat.st_ctime, 'metadata_changed')
