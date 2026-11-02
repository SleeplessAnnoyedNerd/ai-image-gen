"""Tests for the DashScope model capability tables."""
from services.model_specs import (
    IMAGE_SPECS,
    VIDEO_SPECS,
    image_spec,
    video_spec,
)


def _video(name):
    """Capability table entry, asserting that the model is known."""
    spec = video_spec(name)
    assert spec is not None, name
    return spec


def test_unknown_models_have_no_spec():
    """A model that is not in the table is simply unknown."""
    assert image_spec("no-such-model") is None
    assert video_spec("no-such-model") is None


def test_every_video_spec_is_self_consistent():
    """The defaults a spec declares must be values the model accepts."""
    for name, spec in VIDEO_SPECS.items():
        assert spec.default_resolution in spec.resolutions, name
        assert spec.duration_min <= spec.default_duration <= spec.duration_max, name
        assert spec.min_images <= spec.max_images, name
        if spec.ratios is None:
            assert spec.default_ratio is None, name
        else:
            assert spec.default_ratio in spec.ratios, name


def test_every_image_spec_default_is_allowed():
    """The default size must be one of the offered sizes."""
    for name, spec in IMAGE_SPECS.items():
        assert spec.default_size in spec.sizes, name


def test_text_to_video_models_take_no_images():
    """A model without media support accepts no images at all."""
    for name in ("wan2.7-t2v", "happyhorse-1.1-t2v"):
        spec = _video(name)
        assert spec.media is None
        assert spec.min_images == 0
        assert spec.max_images == 0


def test_i2v_model_takes_exactly_one_first_frame():
    """happyhorse-1.1-i2v is a single first frame and takes no ratio."""
    spec = _video("happyhorse-1.1-i2v")
    assert spec.media == "first_frame"
    assert spec.min_images == 1
    assert spec.max_images == 1
    assert spec.ratios is None


def test_r2v_models_take_reference_images():
    """The reference-to-video models take a list of reference images."""
    assert _video("happyhorse-1.1-r2v").media == "reference_image"
    assert _video("wan3.0-video").media == "reference_image"


def test_wan3_video_allows_more_images_and_time():
    """wan3.0-video is the most permissive of the video models."""
    spec = _video("wan3.0-video")
    assert spec.max_images == 10
    assert spec.duration_max == 30
    assert spec.ratios is not None
    assert "adaptive" in spec.ratios
