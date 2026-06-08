# PyInstaller spec for both macOS and Windows.
# Build with:
#   macOS:   pyinstaller build/lanny.spec
#   Windows: pyinstaller build\lanny.spec
import sys
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
is_mac = sys.platform == "darwin"
is_win = sys.platform.startswith("win")

a = Analysis(
    ["../tray.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("../templates", "templates"),
        ("../static", "static"),
        ("../oui.tsv", "."),
    ],
    hiddenimports=collect_submodules("pystray") + collect_submodules("PIL"),
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Lanny",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,        # GUI app — no console window on Windows
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=True, upx_exclude=[], name="Lanny",
)

if is_mac:
    app = BUNDLE(
        coll,
        name="Lanny.app",
        icon=None,
        bundle_identifier="com.lanny.app",
        info_plist={
            "LSUIElement": True,        # menubar-only app (no dock icon)
            "CFBundleShortVersionString": "0.1.0",
            "NSHighResolutionCapable": True,
        },
    )
