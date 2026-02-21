#!/bin/bash
set -e

echo "=== Building Ouroboros.app ==="

# Verify python-standalone exists
if [ ! -f "python-standalone/bin/python3" ]; then
    echo "ERROR: python-standalone/ not found."
    echo "Run first:  bash scripts/download_python_standalone.sh"
    exit 1
fi

# Install launcher deps (pywebview into build env)
echo "--- Installing launcher dependencies ---"
pip install -q -r requirements-launcher.txt

# Install agent deps into bundled python
echo "--- Installing agent dependencies into python-standalone ---"
python-standalone/bin/pip3 install -q -r requirements.txt

# Clean previous build
rm -rf build dist

# Build
echo "--- Running PyInstaller ---"
python -m PyInstaller Ouroboros.spec --clean --noconfirm

# Ad-hoc codesign so macOS doesn't quarantine-block on first open
codesign -s - --force --deep "dist/Ouroboros.app"

echo ""
echo "=== Build complete ==="
echo "Output: dist/Ouroboros.app"
echo ""
echo "To create DMG:"
echo "  hdiutil create -volname Ouroboros -srcfolder dist/Ouroboros.app -ov dist/Ouroboros.dmg"
echo ""
echo "To transfer as ZIP:"
echo "  cd dist && zip -r Ouroboros.zip Ouroboros.app"
echo ""
echo "On target Mac: right-click > Open to bypass Gatekeeper."
