# Luma Viewer

A fast, modern image and media viewer built with PySide6.

---

## Requirements

```
pip install PySide6>=6.6.0 Pillow>=10.0.0 numpy>=1.26.0
```

### Optional dependencies

| Package | Enables |
|---|---|
| `rawpy>=0.19.0` | RAW camera files |
| `astropy>=6.0.0` | FITS astronomical images |
| `psd-tools` | Adobe Photoshop PSD files |
| `psutil>=5.9.0` | Memory usage stats |
| `cupy-cuda12x` | GPU-accelerated FITS stretch (requires NVIDIA GPU + CUDA Toolkit) |

Qt Multimedia (video/audio) is included in PySide6 — no extra install needed.
Effective codec support depends on the system backend (Windows Media Foundation on Windows).

---

## Running

```
python main.py
python main.py path/to/file
```

---

## Supported formats

### Images (static)

| Format | Extensions |
|---|---|
| JPEG | `.jpg` `.jpeg` |
| PNG | `.png` |
| BMP | `.bmp` |
| TIFF | `.tif` `.tiff` |
| WebP | `.webp` |
| GIF (first frame) | `.gif` |
| ICO | `.ico` |
| Portable bitmap | `.ppm` `.pgm` `.pbm` |
| Adobe Photoshop | `.psd` |
| FITS | `.fit` `.fits` `.fts` |

### Animated images

| Format | Notes |
|---|---|
| GIF | Always animated via QMovie |
| WebP | Animated when `n_frames > 1` |

### RAW camera (requires `rawpy`)

`.cr2` `.cr3` `.nef` `.nrw` `.arw` `.srf` `.sr2`
`.rw2` `.raf` `.orf` `.dng` `.pef` `.x3f` `.kdc`
`.dcr` `.mrw` `.3fr` `.mef` `.erf` `.rwl` `.iiq`

### Video

`.mp4` `.avi` `.mov` `.mkv` `.wmv` `.webm` `.m4v` `.flv` `.mpeg` `.mpg`

### Audio

`.mp3` `.wav` `.flac` `.aac` `.ogg` `.m4a` `.wma` `.opus`

---

## Features

- **Two-pass progressive loading** — fast preview followed by full-resolution decode
- **Pan & zoom** — mouse drag, scroll wheel, keyboard shortcuts
- **Filmstrip** — thumbnail strip with background parallel loading and prefetch
- **Navigator minimap** — shows the visible viewport over the full image
- **Animated GIF / WebP** — frame-accurate playback with pan/zoom
- **Media player** — video and audio with play, pause, stop, seek, volume
- **PSD compositing** — Photoshop files rendered even without Maximize Compatibility
- **FITS auto-stretch** — linear/asinh stretch with optional GPU acceleration (CuPy)
- **Move to Trash** — right-click context menu or Delete key
- **Stretch small images** toggle (View menu, shortcut `S`) — persistent across sessions
- **Session restore** — remembers last folder, window geometry, splitter position

### Keyboard shortcuts

| Key | Action |
|---|---|
| `←` / `→` | Previous / next file |
| `F` | Fit to window |
| `1` | Actual size (1:1) |
| `+` / `-` | Zoom in / out |
| `S` | Toggle stretch small images |
| `F11` / `Esc` | Fullscreen / exit fullscreen |
| `Space` | Play / pause (media player) |
| `Delete` | Move current file to Trash |
| `Ctrl+O` | Open file |
| `Ctrl+Shift+O` | Open folder |
| `Ctrl+Q` | Quit |

---

## Credits

| Package | Purpose |
|---|---|
| PySide6 | Qt for Python — cross-platform GUI framework |
| Pillow | Image reading and processing (JPEG, PNG, TIFF, WebP, …) |
| psd-tools | Adobe Photoshop PSD layer compositing |
| rawpy | RAW camera file decoding via LibRaw |
| astropy | FITS astronomical image support |
| NumPy | Numerical array operations |
| psutil | System resource monitoring |

---

© 2026 De Martin Davide — [www.demahub.com](https://www.demahub.com)
