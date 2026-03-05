"""FITS image decoder — fitsio primary backend, astropy fallback."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
from PySide6.QtGui import QImage

log = logging.getLogger(__name__)

from .decoder_base import BaseDecoder, ImageMetadata, Region

# ------------------------------------------------------------------ #
# Backend detection                                                    #
# ------------------------------------------------------------------ #

try:
    import fitsio                        # pip install fitsio
    _FITSIO_AVAILABLE = True
except Exception:
    _FITSIO_AVAILABLE = False

try:
    from astropy.io import fits as _afits
    _ASTROPY_AVAILABLE = True
except ImportError:
    _ASTROPY_AVAILABLE = False

_ANY_BACKEND = _FITSIO_AVAILABLE or _ASTROPY_AVAILABLE

# ------------------------------------------------------------------ #
# GPU acceleration (optional — requires cupy + CUDA)                  #
# ------------------------------------------------------------------ #
#
# End-user requirements for GPU stretch to work:
#   1. NVIDIA GPU with CUDA-capable driver
#   2. CUDA Toolkit installed (https://developer.nvidia.com/cuda-downloads)
#      — provides headers needed by CuPy for runtime kernel compilation (NVRTC).
#      — `pip install nvidia-cuda-nvrtc-cu12` alone is NOT sufficient.
#   3. CuPy matching the installed CUDA version:
#      pip install cupy-cuda12x   # CUDA 12.x
#      pip install cupy-cuda11x   # CUDA 11.x
#
# Without the above, the app falls back to CPU (numpy) transparently.
#
try:
    import cupy as _cp
    # Probe: test an actual kernel that requires NVRTC, not just driver availability.
    _cp.isfinite(_cp.array([0.0], dtype=_cp.float32))
    _CUPY_AVAILABLE = True
    log.info("CuPy detected — FITS stretch will use GPU for arrays >= 4 MP")
except ImportError:
    _CUPY_AVAILABLE = False
except Exception as _e:
    _CUPY_AVAILABLE = False
    log.info("CuPy found but GPU probe failed — GPU stretch disabled: %s: %s", type(_e).__name__, _e)

# Transfer overhead exceeds compute savings below this pixel count.
_GPU_MIN_PIXELS = 4_000_000   # ~4 MP

_gpu_stretch_logged = False   # emit an INFO timing message on the first GPU call
_gpu_active = _CUPY_AVAILABLE  # set to False after a runtime failure to stop retrying


def _apply_stretch_gpu(arr_np: np.ndarray, lo_pct: float, hi_pct: float) -> np.ndarray:
    """Percentile stretch executed on the GPU. Returns numpy uint8."""
    import time
    global _gpu_stretch_logged

    t0 = time.perf_counter()
    arr = _cp.asarray(arr_np, dtype=_cp.float32)
    finite = arr[_cp.isfinite(arr)]
    if finite.size == 0:
        return np.zeros(arr_np.shape, dtype=np.uint8)

    vmin = float(_cp.percentile(finite, lo_pct))
    vmax = float(_cp.percentile(finite, hi_pct))
    if vmax <= vmin:
        vmax = vmin + 1.0

    out = _cp.clip(arr, vmin, vmax)
    out = (out - vmin) / (vmax - vmin) * 255.0
    result = _cp.asnumpy(out.astype(_cp.uint8))
    elapsed_ms = (time.perf_counter() - t0) * 1000

    if not _gpu_stretch_logged:
        _gpu_stretch_logged = True
        try:
            device_name = _cp.cuda.Device(0).name
        except Exception:
            device_name = "unknown"
        log.info(
            "GPU stretch (first call): %dx%d  %.1f ms  (device: %s)",
            arr_np.shape[-1], arr_np.shape[0], elapsed_ms, device_name,
        )
    else:
        log.debug("GPU stretch: %dx%d  %.1f ms", arr_np.shape[-1], arr_np.shape[0], elapsed_ms)

    return result


# ------------------------------------------------------------------ #
# Stretch                                                              #
# ------------------------------------------------------------------ #

def apply_auto_stretch(
    data: np.ndarray,
    lo_pct: float = 0.5,
    hi_pct: float = 99.5,
) -> np.ndarray:
    """
    Percentile-clip + linear stretch → uint8 [0, 255].

    Uses GPU (CuPy) when available and the array is large enough to
    justify the PCIe transfer overhead; falls back to numpy otherwise.
    """
    global _gpu_active
    if _gpu_active and data.size >= _GPU_MIN_PIXELS:
        try:
            return _apply_stretch_gpu(data, lo_pct, hi_pct)
        except Exception:
            _gpu_active = False
            log.warning("GPU stretch failed — disabling GPU path for this session", exc_info=True)

    arr = np.asarray(data, dtype=np.float32)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return np.zeros(arr.shape, dtype=np.uint8)

    vmin = float(np.percentile(finite, lo_pct))
    vmax = float(np.percentile(finite, hi_pct))
    if vmax <= vmin:
        vmax = vmin + 1.0

    out = np.clip(arr, vmin, vmax)
    out = (out - vmin) / (vmax - vmin) * 255.0
    return out.astype(np.uint8)


# ------------------------------------------------------------------ #
# QImage helpers                                                       #
# ------------------------------------------------------------------ #

def _gray_u8_to_qimage(arr: np.ndarray) -> QImage:
    """HxW uint8 → Grayscale8 QImage."""
    arr = np.ascontiguousarray(arr)
    h, w = arr.shape
    qimg = QImage(arr.data, w, h, w, QImage.Format.Format_Grayscale8)
    return qimg.copy()


def _rgb_u8_to_qimage(arr: np.ndarray) -> QImage:
    """HxWx3 uint8 → RGB888 QImage."""
    arr = np.ascontiguousarray(arr)
    h, w = arr.shape[:2]
    bytes_per_line = w * 3
    qimg = QImage(arr.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
    return qimg.copy()


def _array_to_qimage(arr: np.ndarray) -> QImage:
    """Dispatch to gray or RGB helper based on array shape."""
    if arr.ndim == 2:
        return _gray_u8_to_qimage(arr)
    return _rgb_u8_to_qimage(arr)


def _resize_array(arr: np.ndarray, max_size: int) -> np.ndarray:
    """Downscale HxW or HxWx3 array to fit within max_size using PIL."""
    from PIL import Image
    h, w = arr.shape[:2]
    scale = min(max_size / w, max_size / h, 1.0)
    if scale >= 1.0:
        return arr
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    mode = "L" if arr.ndim == 2 else "RGB"
    pil = Image.fromarray(arr, mode=mode)
    return np.array(pil.resize((nw, nh), Image.LANCZOS))


def _resize_raw(data: np.ndarray, max_size: int) -> np.ndarray:
    """Downscale raw (pre-stretch) 2-D FITS data to fit within max_size.

    Only handles 2-D arrays (the common case for grayscale science images).
    Multi-dimensional arrays are returned unchanged so that _normalise can
    handle their layout as usual.  PIL mode "F" accepts float32 and performs
    a proper LANCZOS downsample on raw pixel values.
    """
    from PIL import Image
    squeezed = np.squeeze(data)
    if squeezed.ndim != 2:
        return data
    h, w = squeezed.shape
    scale = min(max_size / w, max_size / h, 1.0)
    if scale >= 1.0:
        return squeezed
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    pil = Image.fromarray(squeezed.astype(np.float32), mode="F")
    return np.array(pil.resize((nw, nh), Image.LANCZOS))


# ------------------------------------------------------------------ #
# Raw data reading                                                     #
# ------------------------------------------------------------------ #

def _read_fitsio(path: Path) -> Tuple[Optional[np.ndarray], dict]:
    """Read first image HDU via fitsio. Returns (data, header)."""
    with fitsio.FITS(str(path)) as fits:
        for hdu in fits:
            info = hdu.get_info()
            if info.get("hdutype") == "IMAGE_HDU":
                dims = info.get("dims", ())
                if len(dims) >= 2:
                    data = hdu.read()
                    header = dict(hdu.read_header())
                    return data, header
    return None, {}


def _read_astropy(path: Path) -> Tuple[Optional[np.ndarray], dict]:
    """Read first image HDU via astropy (memmap). Returns (data, header)."""
    with _afits.open(str(path), memmap=True) as hdul:
        for hdu in hdul:
            if hasattr(hdu, "data") and hdu.data is not None:
                if hdu.data.ndim >= 2:
                    arr = np.array(hdu.data)          # materialise memmap
                    header = {k: str(v) for k, v in dict(hdu.header).items()}
                    return arr, header
    return None, {}


def _read_fits(path: Path) -> Tuple[Optional[np.ndarray], dict]:
    """Try fitsio first, fall back to astropy."""
    if _FITSIO_AVAILABLE:
        try:
            return _read_fitsio(path)
        except Exception:
            pass
    if _ASTROPY_AVAILABLE:
        try:
            return _read_astropy(path)
        except Exception:
            pass
    return None, {}


# ------------------------------------------------------------------ #
# Data normalisation                                                   #
# ------------------------------------------------------------------ #

def _normalise(data: np.ndarray) -> np.ndarray:
    """
    Convert raw FITS data to a displayable uint8 array.

    Handles:
    - 2-D grayscale   (H, W)          → HxW uint8
    - 3-D data cube   (N, H, W)       → first frame HxW uint8
    - 3-D RGB FITS    (3, H, W)       → HxWx3 uint8
    - 3-D RGB FITS    (H, W, 3)       → HxWx3 uint8
    """
    data = np.squeeze(data)

    if data.ndim == 2:
        return apply_auto_stretch(data)

    if data.ndim == 3:
        c0, c1, c2 = data.shape
        # (3, H, W) — channel-first RGB
        if c0 == 3:
            rgb = np.stack(
                [apply_auto_stretch(data[i]) for i in range(3)], axis=-1
            )
            return rgb
        # (H, W, 3) — channel-last RGB
        if c2 == 3:
            rgb = np.stack(
                [apply_auto_stretch(data[:, :, i]) for i in range(3)], axis=-1
            )
            return rgb
        # Data cube: take first frame
        return apply_auto_stretch(data[0])

    # Higher-dimensional: take first 2-D slice
    while data.ndim > 2:
        data = data[0]
    return apply_auto_stretch(data)


# ------------------------------------------------------------------ #
# Decoder class                                                        #
# ------------------------------------------------------------------ #

class FitsDecoder(BaseDecoder):
    """
    Decoder for FITS astronomical image files.

    Backend priority:  fitsio (fast C extension)  →  astropy (memmap)
    Stretch:           percentile clip + linear normalisation
    Colour:            grayscale, (3,H,W) or (H,W,3) RGB FITS supported
    """

    SUPPORTED_EXTENSIONS = (".fit", ".fits", ".fts")

    # --  probe  --------------------------------------------------------

    def probe(self, path: Path) -> float:
        if not _ANY_BACKEND:
            return 0.0
        if path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            return 0.0
        # Verify FITS magic bytes ("SIMPLE  =")
        try:
            with open(path, "rb") as f:
                magic = f.read(9)
            if magic.startswith(b"SIMPLE  "):
                return 0.95
        except OSError:
            pass
        return 0.5   # extension matches but couldn't verify magic

    # --  metadata  -----------------------------------------------------

    def read_metadata(self, path: Path) -> ImageMetadata:
        if not _ANY_BACKEND:
            return ImageMetadata(format_name="FITS")
        data, header = _read_fits(path)
        if data is None:
            return ImageMetadata(format_name="FITS")

        shape = np.squeeze(data).shape
        h = shape[-2] if len(shape) >= 2 else 1
        w = shape[-1] if len(shape) >= 1 else 1
        bitpix = int(header.get("BITPIX", 16))
        channels = 3 if (len(shape) == 3 and (shape[0] == 3 or shape[2] == 3)) else 1

        return ImageMetadata(
            width=w,
            height=h,
            channels=channels,
            bit_depth=abs(bitpix),
            color_space="linear",
            format_name="FITS",
            extra={"header": header},
        )

    # --  decode_preview  -----------------------------------------------

    def decode_preview(self, path: Path, max_size: int) -> QImage:
        if not _ANY_BACKEND:
            return QImage()
        data, _ = _read_fits(path)
        if data is None:
            return QImage()
        data = _resize_raw(data, max_size)
        arr = _normalise(data)
        return _array_to_qimage(arr)

    # --  decode_region  ------------------------------------------------

    def decode_region(self, path: Path, region: Region, scale: float) -> QImage:
        if not _ANY_BACKEND:
            return QImage()
        data, _ = _read_fits(path)
        if data is None:
            return QImage()

        data = np.squeeze(data)
        # Collapse to 2-D or 3-D (H,W,3) before slicing
        if data.ndim == 3 and data.shape[0] == 3:
            # (3,H,W) → (H,W,3)
            data = np.moveaxis(data, 0, -1)
        elif data.ndim > 3:
            while data.ndim > 2:
                data = data[0]

        r = region
        if data.ndim == 2:
            sliced = data[r.y: r.y + r.height, r.x: r.x + r.width]
            arr = apply_auto_stretch(sliced)
        else:   # (H,W,3)
            sliced = data[r.y: r.y + r.height, r.x: r.x + r.width, :]
            arr = np.stack(
                [apply_auto_stretch(sliced[:, :, i]) for i in range(3)], axis=-1
            )

        if scale != 1.0:
            arr = _resize_array(arr, max(1, int(max(arr.shape[:2]) * scale)))
        return _array_to_qimage(arr)

    def can_decode_region(self) -> bool:
        return True
