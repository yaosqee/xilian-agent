# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for 昔涟 V3.3
Build: pyinstaller xilian.spec
Output: dist/昔涟 (single executable)
"""

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # prompts/ — personality prompt files
        ('prompts', 'prompts'),
        # skills/ — agent skill markdown files
        ('skills', 'skills'),
        # frontend dist — Vite build output
        ('packages/frontend/dist', 'packages/frontend/dist'),
        # character_memories.json — essential role memory seed data
        ('data/character_memories.json', 'data'),
        # photo/ — user images and background configs (~25MB)
        ('photo', 'photo'),
        # alembic/ — DB migration scripts
        ('alembic', 'alembic'),
        # alembic.ini — migration config
        ('alembic.ini', '.'),
    ],
    hiddenimports=[
        # sqlite-vec (loads vec0 via sqlite3.load_extension)
        'sqlite_vec',
        # System tray (needs pystray + Pillow + pywin32 on Windows)
        'pystray',
        'pystray._win32',
        'pystray._util',
        'pystray._base',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'win32api',
        'win32gui',
        'win32con',
        'win32process',
        'win32clipboard',
        # AI/API
        'openai',
        'httpx',
        # Web server
        'fastapi',
        'uvicorn',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        # Database
        'aiosqlite',
        'sqlalchemy',
        'greenlet',
        # Scheduler
        'apscheduler',
        'apscheduler.schedulers',
        'apscheduler.schedulers.asyncio',
        # Logging / CLI
        'loguru',
        'rich',
        # Config
        'dotenv',
        # Migrations
        'alembic',
        # YAML
        'yaml',
        # HTTP multipart
        'multipart',
        'python_multipart',
        # Pydantic (fastapi deps)
        'pydantic',
        'pydantic_core',
        # Starlette
        'starlette',
        'starlette.middleware',
        # Misc
        'markupsafe',
    ],
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'pydoc',
        'ensurepip',
        'idlelib',
        'venv',
        'lib2to3',
        'ctypes.test',
        'sqlite3.test',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='昔涟',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,   # MVP: keep console for debugging; change to False for --windowed
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='photo/app_icon.ico',
)
