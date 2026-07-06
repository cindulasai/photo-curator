# packaging/photo-curator.spec
# Build: pyinstaller packaging/photo-curator.spec
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [
    ("../curator/data", "curator/data"),
    ("../curator/prompts", "curator/prompts"),
    ("../curator/schemas", "curator/schemas"),
    ("../curator/providers/registry.yaml", "curator/providers"),
]
datas += collect_data_files("litellm")          # model_prices json
datas += collect_data_files("textual")

hiddenimports = (collect_submodules("keyring.backends")
                 + ["PIL._tkinter_finder"])

a = Analysis(["../curator/__main__.py"], pathex=[".."], datas=datas,
             hiddenimports=hiddenimports, excludes=["tkinter", "matplotlib"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="photo-curator",
          console=True, onefile=True, strip=False, upx=False)
