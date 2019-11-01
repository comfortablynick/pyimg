"""Image operations."""

import logging
import sys
from io import BytesIO

import cv2
import numpy as np
import piexif
import plotille
from PIL import Image

from pyimgtool import resize, watermark
from pyimgtool.data_structures import Config, Context
from pyimgtool.utils import humanize_bytes

LOG = logging.getLogger(__name__)


def generate_histogram(cfg: Config) -> str:
    """Return string of histogram for image to print in terminal.

    Parameters
    ----------
    - `im` PIL Image
    - `cfg` Config object

    """
    hist_bins = 256
    mono = cv2.imread(cfg.input_file)
    #  hist_data = mono.histogram()
    hist_data = [
        x[0]
        for x in cv2.calcHist(
            images=[mono],
            channels=[0],
            mask=None,
            histSize=[hist_bins],
            ranges=[0, 256],
        )
    ]
    #  print(hist_data)

    hist = plotille.histogram(
        hist_data,
        height=10,
        width=50,
        X_label="Pixel Count",
        Y_label="Pixel Value",
        x_min=0,
    )
    return str(hist)


def calculate_new_size(cfg: Config, ctx: Context) -> None:
    """Update Config with correct width/height.

    Percent scale (`-p`) takes precedence over width (`-mw`) and
    height (`-mh`). Func does nothing if both height and width
    are supplied at the command line.

    Parameters
    ----------
    - `cfg` Config object
    - `ctx` Context objec

    """
    if cfg.pct_scale:
        LOG.info("Scaling image by %.1f%%", cfg.pct_scale)
        cfg.width = int(round(ctx.orig_size.width * (cfg.pct_scale / 100.0)))
        cfg.height = int(round(ctx.orig_size.height * (cfg.pct_scale / 100.0)))
    elif cfg.width and not cfg.height:
        LOG.info("Calculating height based on width")
        cfg.height = int(
            round((cfg.width * ctx.orig_size.height) / ctx.orig_size.width)
        )
    elif cfg.height and not cfg.width:
        LOG.info("Calculating width based on height")
        cfg.width = int(
            round((cfg.height * ctx.orig_size.width) / ctx.orig_size.height)
        )
    elif not cfg.height and not cfg.width:
        LOG.info("No new width or height supplied; using current dims")
        cfg.width = ctx.orig_size.width
        cfg.height = ctx.orig_size.height


def process_image(cfg: Config) -> Context:
    """Process image according to options in `cfg`."""
    ctx = Context()
    inbuf = BytesIO()
    outbuf = BytesIO()
    if not cfg.input_file:
        raise ValueError("input_file required")
    with open(cfg.input_file, "rb") as f:
        inbuf.write(f.read())
    ctx.orig_file_size = inbuf.tell()
    im = Image.open(inbuf)
    try:
        exif = piexif.load(cfg.input_file)
        del exif["thumbnail"]
        ctx.orig_exif = exif
    except KeyError:
        pass
    ctx.orig_size.width, ctx.orig_size.height = im.size
    ctx.orig_dpi = im.info["dpi"]
    LOG.info("Input dims: %s", ctx.orig_size)
    LOG.info("Input size: %s", humanize_bytes(ctx.orig_file_size))

    calculate_new_size(cfg, ctx)

    # Resize/resample
    if cfg.height != ctx.orig_size.height or cfg.width != ctx.orig_size.width:
        im = resize.resize_thumbnail(
            im,
            (cfg.width, cfg.height),
            #  bg_size=(cfg.width + 50, cfg.height + 50),
            resample=Image.ANTIALIAS,
        )

    if cfg.watermark_image is not None:
        im = watermark.with_image(im, cfg, ctx)
    if cfg.text is not None or cfg.text_copyright is not None:
        im = watermark.with_text(im, cfg, ctx)

    try:
        ctx.new_dpi = im.info["dpi"]
    except KeyError:
        pass
    LOG.info("Image mode: %s", im.mode)

    # Save
    use_progressive_jpg = ctx.orig_file_size > 10000
    if use_progressive_jpg:
        LOG.debug("Large file; using progressive jpg")

    # Exif
    if cfg.keep_exif:
        exif = piexif.dump(piexif.load(cfg.input_file))
    else:
        exif = b""

    im.save(
        outbuf,
        "JPEG",
        quality=cfg.jpg_quality,
        dpi=ctx.orig_dpi,
        progressive=use_progressive_jpg,
        optimize=True,
        exif=exif,
    )
    ctx.image_buffer = outbuf.getvalue()

    # convert back to image to get size
    if ctx.image_buffer:
        img_out = Image.open(BytesIO(ctx.image_buffer))
        if cfg.show_histogram:
            print(generate_histogram(cfg))
        ctx.new_size.width, ctx.new_size.height = img_out.size
        ctx.new_file_size = sys.getsizeof(ctx.image_buffer)
    LOG.info("Output size: %s", humanize_bytes(ctx.new_file_size))
    return ctx
