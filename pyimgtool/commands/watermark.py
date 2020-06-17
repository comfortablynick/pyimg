"""Watermark image with text or another image."""

import logging
from datetime import datetime
from pathlib import PurePath
from typing import Any, Dict, List, Tuple, Union

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageStat
from PIL.Image import Image as PILImage

from pyimgtool import utils
from pyimgtool.commands.resize import resize_height
from pyimgtool.data_structures import Box, Position, Size, Stat
from pyimgtool.exceptions import OverlaySizeError

LOG = logging.getLogger(__name__)


def get_region_stats(im: PILImage, region: Box) -> ImageStat:
    """Get ImageStat object for region of PIL image.

    Parameters
    ----------
    im : PIL Image
        The image to get the luminance of
    region : Box
        Coordinates for region

    Returns: ImageStat object with stats
    """
    LOG.debug("Region for stats: %s", region)
    image_l = im.convert("L")
    m = Image.new("L", image_l.size, 0)
    drawing_layer = ImageDraw.Draw(m)
    drawing_layer.rectangle(region, fill=255)
    return ImageStat.Stat(image_l, mask=m)


def get_region_stats_np(im: np.ndarray, region: Box) -> Stat:
    """Get array region stats using Numpy.

    Parameters
    ----------
    im : np.ndarray
        Input image to analyze
    region : Box
        Coordinates for region

    Returns
    -------
    Stat
        Stat object containing various statistics of region
    """
    x0, y0, x1, y1 = region
    dtype = np.float64
    im = im[y0:y1, x0:x1].copy()
    return Stat(stddev=np.std(im, dtype=dtype), mean=np.mean(im, dtype=dtype))


def find_best_location(im: Image, size: Size, padding: float) -> Position:
    """Find the best location for the watermark.

    The best location is the one with least luminance variance.

    Args:
        im: PIL Image
        size: Size of watermark image
        padding: Proportion of padding to add around watermark

    Returns: Position object
    """
    bl_padding = (
        padding * im.size[0],
        im.size[1] - size.height - padding * im.size[1],
    )
    br_padding = (
        im.size[0] - size.width - padding * im.size[0],
        im.size[1] - size.height - padding * im.size[1],
    )
    tl_padding = (padding * im.size[0], padding * im.size[0])
    tr_padding = (im.size[0] - size.width - padding * im.size[0], padding * im.size[1])
    bc_padding = (
        im.size[0] / 2 - size.width / 2,
        im.size[1] - size.height - padding * im.size[1],
    )
    paddings = [
        tuple(int(x) for x in t)
        for t in [bl_padding, br_padding, tl_padding, tr_padding, bc_padding]
    ]
    stats = [
        get_region_stats(
            im,
            Box(
                padding[0],
                padding[1],
                padding[0] + size.width,
                padding[1] + size.height,
            ),
        ).stddev[0]
        for padding in paddings
    ]
    LOG.debug("stats: %s", stats)
    index = stats.index(min(stats))
    locations = [
        Position.BOTTOM_LEFT,
        Position.BOTTOM_RIGHT,
        Position.TOP_LEFT,
        Position.TOP_RIGHT,
        Position.BOTTOM_CENTER,
    ]
    return locations[index]


def find_best_position(
    im: np.ndarray, size: Size, padding: float
) -> Tuple[Position, Box, Stat]:
    """Find the best location for the watermark.

    The best location is the one with lowest luminance stddev.

    Parameters
    ----------
    im
        Image array
    size
        Size of watermark image
    padding
        Proportion of padding to add around watermark

    Returns
    -------
    Position, Box, Stat
    """
    im_size = Size.from_np(im)
    positions = []
    for p in Position:
        if p is not Position.CENTER:
            pos = p.calculate_for_overlay(im_size, size, padding)
            st = get_region_stats_np(im, pos)
            positions.append((p, pos, st))
    LOG.debug("Positions: %s", positions)
    # utils.show_image_cv2(im)
    return min(positions, key=lambda i: i[2].stddev)


def get_copyright_string(exif: Dict[Any, Any]) -> str:
    """Extract date taken from photo to add to copyright text.

    Args:
        exif: Dictionary of exif data

    Returns: string of copyright symbol and date
    """
    if exif is not None:
        # LOG.debug("Exif data: %s", exif["Exif"])
        try:
            photo_dt = datetime.strptime(
                exif["Exif"]["DateTimeOriginal"].decode("utf-8"), "%Y:%m:%d %H:%M:%S",
            )
        except KeyError:
            photo_dt = datetime.now()
    copyright_year = photo_dt.strftime("%Y")
    # LOG.info("Using copyright text: %s", text_copyright)
    LOG.info("Photo date from exif: %s", photo_dt)
    return f"© {copyright_year}"


def with_image(
    im: PILImage,
    watermark_image: PILImage,
    scale: float = 0.2,
    position: Position = Position.BOTTOM_RIGHT,
    opacity: float = 0.3,
    padding: int = 10,
    invert: bool = False,
) -> PILImage:
    """Watermark with image according to Config.

    Parameters
    ----------
    im
        PIL Image
    watermark_image
        PIL Image
    scale
        Scale for watermark relative to image
    position
        Position of watermark
    opacity
        Watermark layer opacity from 0 to 1
    padding
        Pixels of padding for watermark
    invert
        Invert watermark image

    Returns
    -------
    PIL Image with watermark
    """
    watermark_image = watermark_image.convert("RGBA")
    LOG.info("Watermark: %s", watermark_image.size)
    watermark_ratio = watermark_image.height / im.height
    LOG.info("Watermark size ratio: %.4f", watermark_ratio)
    if watermark_ratio > scale:
        LOG.debug(
            "Resizing watermark from %.4f to %.4f scale", watermark_ratio, scale,
        )
        watermark_image = resize_height(
            watermark_image, (int(im.width * scale), int(im.height * scale)),
        )
        LOG.debug("New watermark dims: %s", watermark_image.size)
    # offset_x = padding
    # offset_y = padding
    watermark_size = Size(watermark_image.width, watermark_image.height)
    mask = watermark_image.split()[3].point(lambda i: i * opacity)
    # pos = (
    #     (im.width - watermark_image.width - offset_x),
    #     (im.height - watermark_image.height - offset_y),
    # )
    loc = find_best_location(im, watermark_size, 0.05)
    LOG.debug("Best detected watermark loc: %s", loc)
    x, y, _, _ = position.calculate_for_overlay(Size(*im.size), watermark_size)
    im.paste(watermark_image, (x, y), mask)
    return im


@utils.Log(LOG)
def with_image_opencv(
    im: np.ndarray,
    watermark_image: np.ndarray,
    scale: float = 0.2,
    position: Position = Position.BOTTOM_RIGHT,
    opacity: float = 0.3,
    padding: int = 10,
) -> Image:
    """Watermark with image according to Config.

    Args:
        im: Numpy array
        watermark_image: Numpy array
        scale: Scale for watermark relative to image
        position: Position of watermark
        opacity: Watermark layer opacity from 0 to 1
        padding: Pixels of padding for watermark

    Returns: Watermarked image array
    """
    LOG.info("Inserting watermark at position: %s", position)
    orig_im_type = im.dtype
    new_size = Size.calculate_new(Size.from_np(watermark_image), scale)
    watermark_image = cv2.resize(
        watermark_image, tuple(new_size), interpolation=cv2.INTER_AREA
    )
    watermark_image = cv2.copyMakeBorder(
        watermark_image,
        padding,
        padding,
        padding,
        padding,
        cv2.BORDER_CONSTANT,
        value=(0, 0, 0),
    )
    wH, wW = watermark_image.shape[:2]
    h, w = im.shape[:2]
    im = np.dstack([im, np.ones((h, w), dtype=im.dtype)])
    overlay = np.zeros((h, w, 4), dtype=im.dtype)
    ww, hh, _, _ = position.calculate_for_overlay(Size(w, h), Size(wW, wH))
    LOG.debug("hh: %d, ww: %d", hh, ww)
    overlay[hh : hh + wH, ww : ww + wH] = watermark_image
    output = im.copy()
    cv2.addWeighted(overlay, opacity, output, 1.0, 0, output)
    # utils.show_image_cv2(output)
    # utils.show_image_plt(output)
    return output.astype(orig_im_type)


def overlay_transparent(
    background: np.ndarray,
    overlay: np.ndarray,
    scale: float = None,
    position: Position = None,
    padding: float = 0.05,
    alpha: float = 0.3,
    invert: bool = False,
) -> np.ndarray:
    """Blend an image with an overlay (e.g., watermark).

    Parameters
    ----------
    background
        Main image
    overlay
        Image to blend on top of `background`
    position
        Location of overlay
    alpha
        Blend opacity, from 0 to 1
    invert
        Invert overlay image

    Returns
    -------
    Image

    Raises
    ------
    OverlaySizeError
        If overlay image is larger than background image
    """
    bg_h, bg_w = background.shape[:2]
    if scale is not None:
        overlay = cv2.resize(overlay, None, fx=scale, fy=scale)
    LOG.debug("Overlay shape: %s", overlay.shape)
    h, w, c = overlay.shape
    LOG.debug(
        "Calculated margin for overlay: %s", Size(*[int(i * padding) for i in (w, h)])
    )
    bg_gray = cv2.cvtColor(background, cv2.COLOR_RGB2GRAY)
    bg_gray = bg_gray.astype(np.float64)
    if position is None:
        pos, coords, stat = find_best_position(bg_gray, Size(w, h), padding)
        LOG.debug("Best calculated position: %s=%s, %s", pos, coords, stat)
    else:
        coords = position.calculate_for_overlay(
            Size.from_np(background), Size.from_np(overlay), padding
        )
        stat = get_region_stats_np(bg_gray, coords)
        LOG.debug("Position from args: %s=%s, %s", position, coords, stat)
    x0, y0, x1, y1 = coords
    if (x1 - x0) > bg_w or (y1 - y0) > bg_h:
        message = f"Overlay size of {Size(w, h)} is too large for image size {Size(bg_w, bg_h)}"
        LOG.error("%s; this should be unreachable", message)
        raise OverlaySizeError(message)
    if c == 3:
        shape = h, w, 1
        LOG.debug("Adding alpha channel for overlay of shape: %s", shape)
        overlay = np.concatenate(
            [overlay, np.ones(shape, dtype=overlay.dtype) * 255], axis=2,
        )
    overlay_image = overlay[..., :3]
    mask = overlay_image / 256.0 * alpha

    # Combine images, inverting overlay if necessary
    luminance_factor = stat.mean / 256.0
    invert_overlay = luminance_factor > 0.5
    if invert_overlay:
        overlay_image = ~overlay_image
    if invert:
        # Invert whether or not we automatically inverted
        overlay_image = ~overlay_image
    LOG.debug("Luminance factor: %f; invert: %s", luminance_factor, invert_overlay)
    background[y0:y1, x0:x1] = (1.0 - mask) * background[
        y0:y1, x0:x1
    ] + mask * overlay_image
    return background


def with_text(
    im: Image,
    text: str = None,
    copyright: bool = False,
    scale: float = 0.2,
    position: Position = None,
    opacity: float = 0.3,
    padding: int = 10,
    exif: dict = None,
) -> Image:
    """Watermark with text if program option is supplied.

    If text is equal to 'copyright', the exif data will be read
    (if available) to attempt to determine copyright date based on
    date photo was taken.

    Args:
        im: PIL Image
        text: Text to add to image
        copyright: Precede text with copyright info
        scale: Scale for size of text relative to image
        position: Text position in image
        opacity: Text layer opacity from 0 to 1
        padding: Pixels of padding for text
        exif: Image metadata

    Return: Watermarked image
    """
    if copyright and exif is not None:
        # Add date photo taken to copyright text
        text = f"{get_copyright_string(exif)} {text}"
    layer = Image.new("RGBA", (im.width, im.height), (255, 255, 255, 0))

    font_size = 1  # starting size
    offset_x = padding
    offset_y = padding

    try:
        font_path = str(
            PurePath.joinpath(
                utils.get_pkg_root(), "fonts", "SourceSansPro-Regular.ttf"
            )
        )
        font = ImageFont.truetype(font=font_path, size=font_size)
    except OSError:
        LOG.error("Could not find font '%s', aborting text watermark", font_path)
        return im

    LOG.debug("Found font '%s'", font_path)
    while font.getsize(text)[0] < scale * im.width:
        # iterate until text size is >= text_scale
        font_size += 1
        font = ImageFont.truetype(font=font_path, size=font_size)

    if font.getsize(text)[0] > scale * im.width:
        font_size -= 1
        font = ImageFont.truetype(font=font_path, size=font_size)

    text_width, text_height = font.getsize(text)
    LOG.debug(
        "Final text dims: %d x %d px; Font size: %d", text_width, text_height, font_size
    )
    # TODO: calculate watermark dims accurately
    stats = get_region_stats(
        im, Box(offset_x, offset_y, text_width, im.height - text_height)
    )
    LOG.debug("Region luminance: %f", stats.mean[0])
    LOG.debug("Region luminance stddev: %f", stats.stddev[0])
    d = ImageDraw.Draw(layer)
    opacity = int(round((opacity * 255)))
    LOG.info("Text opacity: %d/255", opacity)
    text_fill = 255, 255, 255, opacity
    if stats.mean[0] / 256 >= 0.5:
        text_fill = 0, 0, 0, opacity

    d.text((offset_x, offset_y), text, font=font, fill=text_fill)

    out = Image.alpha_composite(im.convert("RGBA"), layer)

    return out.convert("RGB")
