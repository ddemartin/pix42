"""Utilities to estimate memory requirements before decoding."""
from __future__ import annotations


class MemoryEstimator:
    """Static helpers for estimating image memory footprint."""

    @staticmethod
    def estimate_bytes(width: int, height: int, bpp: int = 4) -> int:
        """
        Estimate uncompressed pixel buffer size in bytes.

        :param width:  Image width in pixels.
        :param height: Image height in pixels.
        :param bpp:    Bytes per pixel (default 4 = RGBA).
        :return:       Estimated byte count.
        """
        return width * height * bpp

    @staticmethod
    def estimate_mb(width: int, height: int, bpp: int = 4) -> float:
        """Return estimated size in mebibytes."""
        return MemoryEstimator.estimate_bytes(width, height, bpp) / (1024 ** 2)

    @staticmethod
    def available_ram_bytes() -> int:
        """
        Return available physical RAM in bytes.

        Falls back to a conservative 512 MiB if psutil is unavailable.
        """
        try:
            import psutil
            return psutil.virtual_memory().available
        except ImportError:
            return 512 * 1024 * 1024

    @staticmethod
    def fits_in_ram(width: int, height: int, bpp: int = 4,
                    safety_factor: float = 0.5) -> bool:
        """
        Return True if the decoded image is expected to fit comfortably in RAM.

        :param safety_factor: Fraction of available RAM allowed to use.
        """
        needed = MemoryEstimator.estimate_bytes(width, height, bpp)
        available = MemoryEstimator.available_ram_bytes()
        return needed <= available * safety_factor
