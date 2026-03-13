# video-mask.spec
# PyInstaller spec for the video-mask GUI launcher.
# Build with: pyinstaller video-mask.spec

from PyInstaller.utils.hooks import collect_all

cv2_datas, cv2_binaries, cv2_hiddenimports = collect_all("cv2")

a = Analysis(
    ["gui.py"],
    pathex=[],
    binaries=cv2_binaries,
    datas=cv2_datas,
    hiddenimports=cv2_hiddenimports + ["annotate", "process", "gui_helpers"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="video-mask",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
