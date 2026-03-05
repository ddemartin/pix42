#!/bin/bash

# Build script for FITSPacker on macOS Intel (x86_64)
# This script builds both the Rust backend and Python GUI, then creates a DMG installer

set -e  # Exit on any error

echo "Building FITSPacker for macOS Intel..."

# Update version in build files from version.py
echo "Updating version in build configuration files..."
python3 "$(dirname "$0")/../update_version_in_build.py"

# Check if we're on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "ERROR: This script is designed for macOS only"
    exit 1
fi

# Check if we're on Intel
if [[ $(uname -m) != "x86_64" ]]; then
    echo "WARNING: This script is optimized for Intel Macs (x86_64)"
    echo "Detected architecture: $(uname -m)"
fi

# Set build directory
BUILD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$BUILD_DIR")"
DIST_DIR="$BUILD_DIR/dist_macos_intel"
APP_NAME="FITSPacker"
DMG_NAME="FITSPacker-macOS-Intel"

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
    
    # Fix cfitsio library dependencies for macOS binaries
    if [ -f "/tmp/cfitsio-4.3.0/libcfitsio.10.dylib" ]; then
        echo "Fixing cfitsio library dependencies..."
        mkdir -p "$APP_BUNDLE/Contents/Frameworks"
        cp "/tmp/cfitsio-4.3.0/libcfitsio.10.dylib" "$APP_BUNDLE/Contents/Frameworks/"
        
        # Fix library references in fpack and funpack (new organized structure)
        install_name_tool -change @rpath/libcfitsio.10.dylib @executable_path/../../Frameworks/libcfitsio.10.dylib "$APP_BUNDLE/Contents/Resources/bins/macos-intel/fpack" 2>/dev/null || true
        install_name_tool -change @rpath/libcfitsio.10.dylib @executable_path/../../Frameworks/libcfitsio.10.dylib "$APP_BUNDLE/Contents/Resources/bins/macos-intel/funpack" 2>/dev/null || true
        
        echo "Fixed cfitsio library dependencies"
    fi
fi

# Copy assets
if [ -d "assets" ]; then
    cp -r "assets" "$APP_BUNDLE/Contents/Resources/"
    echo "Copied assets to app bundle"

    # Create app icon from apple-touch-icon.png if available
    if [ -f "assets/apple-touch-icon.png" ]; then
        echo "Creating app icon..."
        mkdir -p /tmp/icon.iconset
        sips -z 1024 1024 "assets/apple-touch-icon.png" --out /tmp/icon.iconset/icon_512x512@2x.png > /dev/null 2>&1
        sips -z 512 512 "assets/apple-touch-icon.png" --out /tmp/icon.iconset/icon_512x512.png > /dev/null 2>&1
        sips -z 256 256 "assets/apple-touch-icon.png" --out /tmp/icon.iconset/icon_256x256.png > /dev/null 2>&1
        sips -z 128 128 "assets/apple-touch-icon.png" --out /tmp/icon.iconset/icon_128x128.png > /dev/null 2>&1
        iconutil -c icns /tmp/icon.iconset --output "$APP_BUNDLE/Contents/Resources/FITSPacker.icns"
        rm -rf /tmp/icon.iconset
        echo "App icon created"
    fi
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
    <key>CFBundleIconFile</key>
    <string>FITSPacker.icns</string>
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
    <string>10.15</string>
    <key>LSRequiresNativeExecution</key>
    <true/>
    <key>LSArchitecturePriority</key>
    <array>
        <string>x86_64</string>
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
        python3 -m pip install --user pyinstaller pyside6
        
        # Build standalone executable
        echo "Creating standalone GUI executable..."
        python3 -m PyInstaller FITSPacker.spec --distpath "$DIST_DIR/gui_build"
        
        # Copy GUI executable to app bundle
        if [ -f "$DIST_DIR/gui_build/FITSPacker" ]; then
            cp "$DIST_DIR/gui_build/FITSPacker" "$APP_BUNDLE/Contents/MacOS/FITSPacker"
            echo "GUI executable added to app bundle"
        elif [ -f "dist/FITSPacker" ]; then
            cp "dist/FITSPacker" "$APP_BUNDLE/Contents/MacOS/FITSPacker"
            echo "GUI executable added to app bundle (from local dist)"
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