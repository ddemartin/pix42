#!/bin/bash

# Build script for FITSPacker on macOS Silicon (Apple M1/M2/M3)
# This script builds both the Rust backend and Python GUI, then creates a DMG installer

set -e  # Exit on any error

echo "Building FITSPacker for macOS Silicon..."

# Update version in build files from version.py
echo "Updating version in build configuration files..."
python3 "$(dirname "$0")/../update_version_in_build.py"

# Check if we're on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "ERROR: This script is designed for macOS only"
    exit 1
fi

# Check if we're on Apple Silicon
if [[ $(uname -m) != "arm64" ]]; then
    echo "WARNING: This script is optimized for Apple Silicon (M1/M2/M3)"
    echo "Detected architecture: $(uname -m)"
fi

# Set build directory
BUILD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$BUILD_DIR")"
DIST_DIR="$BUILD_DIR/dist_macos"
APP_NAME="FITSPacker"
DMG_NAME="FITSPacker-macOS-Silicon"

echo "Project directory: $PROJECT_DIR"
echo "Build directory: $BUILD_DIR"
echo "Distribution directory: $DIST_DIR"

# Clean previous build
echo "Cleaning previous build..."
rm -rf "$DIST_DIR"
rm -f "$BUILD_DIR/$DMG_NAME.dmg"

# Create distribution directory
mkdir -p "$DIST_DIR"

# Create app bundle structure (Python-only version)
echo "Creating app bundle structure..."
APP_BUNDLE="$DIST_DIR/$APP_NAME.app"
mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources"
mkdir -p "$APP_BUNDLE/Contents/Frameworks"

cd "$PROJECT_DIR"

# Copy bins directory (FITS tools)
if [ -d "bins" ]; then
    cp -r "bins" "$APP_BUNDLE/Contents/Resources/"
    echo "Copied FITS tools to app bundle"
fi

# Copy assets
if [ -d "assets" ]; then
    cp -r "assets" "$APP_BUNDLE/Contents/Resources/"
    echo "Copied assets to app bundle"
fi

# Create Info.plist
cat > "$APP_BUNDLE/Contents/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>FITSPacker</string>
    <key>CFBundleIdentifier</key>
    <string>com.fitspacker.app</string>
    <key>CFBundleName</key>
    <string>FITSPacker</string>
    <key>CFBundleVersion</key>
    <string>1.1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.1.0</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleSignature</key>
    <string>????</string>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>LSRequiresNativeExecution</key>
    <true/>
    <key>LSArchitecturePriority</key>
    <array>
        <string>arm64</string>
    </array>
</dict>
</plist>
EOF

# Build Python GUI if it exists
if [ -d "$PROJECT_DIR/python" ]; then
    echo "Building Python GUI..."
    cd "$PROJECT_DIR/python"
    
    # Check if Python 3 is available
    if ! command -v python3 &> /dev/null; then
        echo "WARNING: Python 3 not found. Skipping GUI build."
    else
        # Install PyInstaller and dependencies
        echo "Installing PyInstaller and dependencies..."
        python3 -m pip install --user pyinstaller pyqt5
        
        # Build standalone executable
        echo "Creating standalone GUI executable..."
        python3 -m PyInstaller FITSPacker.spec --target-dir "$DIST_DIR/gui_build"
        
        # Copy GUI executable to app bundle
        if [ -f "$DIST_DIR/gui_build/dist/FITSPacker" ]; then
            cp "$DIST_DIR/gui_build/dist/FITSPacker" "$APP_BUNDLE/Contents/MacOS/FITSPacker"
            echo "GUI executable added to app bundle"
        else
            echo "WARNING: GUI build failed, continuing without GUI"
        fi
    fi
fi

# Make executables executable
chmod +x "$APP_BUNDLE/Contents/MacOS/"*

# Create DMG
echo "Creating DMG installer..."
cd "$BUILD_DIR"

# Create temporary DMG directory
DMG_TEMP_DIR="$DIST_DIR/dmg_temp"
mkdir -p "$DMG_TEMP_DIR"

# Copy app to DMG directory
cp -r "$APP_BUNDLE" "$DMG_TEMP_DIR/"

# Create Applications symlink
ln -s /Applications "$DMG_TEMP_DIR/Applications"

# Create DMG background (optional)
if [ -f "$PROJECT_DIR/assets/logo.png" ]; then
    cp "$PROJECT_DIR/assets/logo.png" "$DMG_TEMP_DIR/.background.png"
fi

# Calculate DMG size (add some padding)
DMG_SIZE=$(du -sm "$DMG_TEMP_DIR" | cut -f1)
DMG_SIZE=$((DMG_SIZE + 50))

# Create DMG
echo "Creating DMG with size ${DMG_SIZE}MB..."
hdiutil create -volname "$APP_NAME" \
               -srcfolder "$DMG_TEMP_DIR" \
               -ov \
               -format UDZO \
               -imagekey zlib-level=9 \
               "$DMG_NAME.dmg"

# Clean up temporary directory
rm -rf "$DMG_TEMP_DIR"
rm -rf "$DIST_DIR/gui_build"

echo ""
echo "✅ Build completed successfully!"
echo "📦 DMG file: $BUILD_DIR/$DMG_NAME.dmg"
echo "📁 App bundle: $APP_BUNDLE"
echo ""
echo "To install:"
echo "1. Double-click the DMG file"
echo "2. Drag $APP_NAME.app to Applications folder"
echo ""

# Display file sizes
echo "File sizes:"
if [ -f "$DMG_NAME.dmg" ]; then
    ls -lh "$DMG_NAME.dmg"
fi
if [ -d "$APP_BUNDLE" ]; then
    du -sh "$APP_BUNDLE"
fi