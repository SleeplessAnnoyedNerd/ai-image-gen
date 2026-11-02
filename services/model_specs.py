"""Capability tables for the DashScope models.

The advanced-mode panel builds its dropdowns from these tables, so a user can
only pick parameter values the selected model actually accepts.  The payload
builders read the same tables, so an out-of-range value is caught before the
request leaves the machine.

Values were verified against the live API -- see probe_dashscope.py.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ImageSpec:
    """Capabilities of one DashScope image model."""

    sizes: tuple[str, ...]     # allowed values for the "size" parameter
    default_size: str          # "auto" means: omit the parameter
    max_images: int            # reference images the model accepts


@dataclass(frozen=True)
class VideoSpec:
    """Capabilities of one DashScope video model."""

    media: str | None          # None | "first_frame" | "reference_image"
    min_images: int
    max_images: int
    resolutions: tuple[str, ...]
    duration_min: int
    duration_max: int
    ratios: tuple[str, ...] | None   # None = the model takes no ratio parameter
    default_resolution: str
    default_duration: int
    default_ratio: str | None


# "auto" omits the size parameter; qwen then picks a resolution itself,
# wan2.7 falls back to its 2K default.
_PIXEL_SIZES = ("1024*1024", "1920*1080", "1080*1920", "2048*2048")

IMAGE_SPECS: dict[str, ImageSpec] = {
    "qwen-image-3.0-pro": ImageSpec(
        sizes=("auto",) + _PIXEL_SIZES,
        default_size="1024*1024",
        max_images=3,
    ),
    "wan2.7-image": ImageSpec(
        sizes=("auto", "1K", "2K") + _PIXEL_SIZES,
        default_size="1K",
        max_images=10,
    ),
    "wan2.7-image-pro": ImageSpec(
        sizes=("auto", "1K", "2K") + _PIXEL_SIZES,
        default_size="1K",
        max_images=10,
    ),
}

_WAN27_RATIOS = ("16:9", "9:16", "1:1", "4:3", "3:4")
_WAN30_RATIOS = ("adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16")
_HAPPYHORSE_RATIOS = ("16:9", "9:16", "1:1", "4:3", "3:4", "4:5", "5:4", "9:21", "21:9")

VIDEO_SPECS: dict[str, VideoSpec] = {
    "wan2.7-t2v": VideoSpec(
        media=None, min_images=0, max_images=0,
        resolutions=("720P", "1080P"), duration_min=2, duration_max=15,
        ratios=_WAN27_RATIOS,
        default_resolution="720P", default_duration=5, default_ratio="16:9",
    ),
    "wan2.7-r2v": VideoSpec(
        media="reference_image", min_images=1, max_images=5,
        resolutions=("720P", "1080P"), duration_min=2, duration_max=15,
        ratios=_WAN27_RATIOS,
        default_resolution="720P", default_duration=5, default_ratio="16:9",
    ),
    "wan3.0-video": VideoSpec(
        media="reference_image", min_images=0, max_images=10,
        resolutions=("480P", "720P", "1080P"), duration_min=2, duration_max=30,
        ratios=_WAN30_RATIOS,
        default_resolution="720P", default_duration=5, default_ratio="16:9",
    ),
    "happyhorse-1.1-t2v": VideoSpec(
        media=None, min_images=0, max_images=0,
        resolutions=("480P", "720P", "1080P"), duration_min=3, duration_max=15,
        ratios=_HAPPYHORSE_RATIOS,
        default_resolution="720P", default_duration=5, default_ratio="16:9",
    ),
    "happyhorse-1.1-r2v": VideoSpec(
        media="reference_image", min_images=1, max_images=9,
        resolutions=("480P", "720P", "1080P"), duration_min=3, duration_max=15,
        ratios=_HAPPYHORSE_RATIOS,
        default_resolution="720P", default_duration=5, default_ratio="16:9",
    ),
    "happyhorse-1.1-i2v": VideoSpec(
        media="first_frame", min_images=1, max_images=1,
        resolutions=("480P", "720P", "1080P"), duration_min=3, duration_max=15,
        ratios=None,
        default_resolution="720P", default_duration=5, default_ratio=None,
    ),
}


def image_spec(model: str) -> ImageSpec | None:
    """Capability table entry for an image model, or None if unknown."""
    return IMAGE_SPECS.get(model)


def video_spec(model: str) -> VideoSpec | None:
    """Capability table entry for a video model, or None if unknown."""
    return VIDEO_SPECS.get(model)
