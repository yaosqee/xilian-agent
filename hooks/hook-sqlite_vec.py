"""
PyInstaller hook for sqlite-vec.

The vec0 shared library (vec0.so / vec0.pyd / vec0.dll) is loaded at runtime
via sqlite3.Connection.load_extension(), not a Python import.
Also, default PY_DYLIB_PATTERNS only match lib*.so — vec0.so doesn't match.
"""
import os
import sqlite_vec

from PyInstaller.utils.hooks import collect_data_files

pkg_dir = os.path.dirname(sqlite_vec.__file__)

# Determine the correct shared library filename per platform
# Linux: vec0.so  macOS: vec0.dylib  Windows: vec0.dll or vec0.pyd
for candidate in ('vec0.so', 'vec0.dylib', 'vec0.dll', 'vec0.pyd'):
    vec0_path = os.path.join(pkg_dir, candidate)
    if os.path.isfile(vec0_path):
        binaries = [(vec0_path, 'sqlite_vec')]
        break
else:
    binaries = []

datas = collect_data_files('sqlite_vec')
