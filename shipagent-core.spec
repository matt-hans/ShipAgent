# shipagent-core.spec
# PyInstaller spec for the ShipAgent unified binary.
# Build: pyinstaller shipagent-core.spec --clean --noconfirm

import sys
from pathlib import Path

block_cipher = None
project_root = Path(SPECPATH)

a = Analysis(
    [str(project_root / 'src' / 'bundle_entry.py')],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(project_root / 'frontend' / 'dist'), 'frontend/dist'),
    ],
    hiddenimports=[
        # FastAPI + Uvicorn
        'uvicorn.logging',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.http.httptools_impl',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        # SQLAlchemy
        'sqlalchemy.dialects.sqlite',
        'aiosqlite',
        # FastMCP
        'fastmcp',
        'mcp',
        # DuckDB
        'duckdb',
        # Agent SDK
        'claude_agent_sdk',
        'anthropic',
        # NL Engine
        'sqlglot',
        'jinja2',
        # UPS MCP fork
        'ups_mcp',
        # Data formats
        'openpyxl',
        'xmltodict',
        'calamine',
        # Credential storage
        'keyring',
        'keyring.backends',
        'keyring.backends.macOS',
        'cryptography',
        # CLI
        'typer',
        'rich',
        'click',
        'httpx',
        'watchdog',
        'yaml',
        # Misc
        'pydantic',
        'jsonschema',
        'pypdf',
        'sse_starlette',
        'platformdirs',
        'pydifact',
        'dateutil',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'test',
        'tests',
        'setuptools',
        'pip',
        'wheel',
        'distutils',
        '_pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# CRITICAL: Use one-FOLDER build (EXE + COLLECT), NOT one-file (EXE only).
#
# Why: MCP servers spawn this same binary as subprocesses. With one-file mode,
# every subprocess invocation re-extracts the entire bundle to a temp _MEIPASS
# directory (1-3 second cold-start penalty PER MCP server). One-folder mode
# extracts once at build time — subprocess spawning is instant.
#
# The COLLECT step creates a directory with all dependencies alongside the
# executable, which Tauri bundles as the sidecar folder.

exe = EXE(
    pyz,
    a.scripts,
    [],  # binaries, zipfiles, datas go to COLLECT instead
    name='shipagent-core',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=False,
    console=True,
    target_arch=None,
    exclude_binaries=True,  # Defer binaries to COLLECT
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=True,
    upx=False,
    name='shipagent-core',  # Output: dist/shipagent-core/ (directory)
)
