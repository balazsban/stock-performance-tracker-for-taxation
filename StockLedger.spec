# Build with: python -m PyInstaller --noconfirm StockLedger.spec

a = Analysis(['desktop.py'], pathex=[], binaries=[],
             datas=[('static', 'static'), ('LICENSE', '.'), ('THIRD_PARTY_NOTICES.txt', '.')],
             hiddenimports=[], hookspath=[], runtime_hooks=[], excludes=['tkinter'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Stock Ledger',
          debug=False, strip=False, upx=False, console=False, target_arch='arm64')
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Stock Ledger')
app = BUNDLE(coll, name='Stock Ledger.app', bundle_identifier='dk.stockledger.desktop',
             info_plist={'CFBundleShortVersionString':'1.0.3', 'CFBundleVersion':'4',
                         'LSUIElement':True, 'NSHighResolutionCapable':True})
