#!/usr/bin/env python
"""Resize and watermark images."""

import argparse
import configparser
import logging
import os
import sys
from dataclasses import dataclass
from enum import Enum
from io import BytesIO
from pathlib import Path

import tinify
from PIL import Image

logging.basicConfig(level=logging.DEBUG)
LOG = logging.getLogger(__name__)


@dataclass
class Config:
    """Store options from config file."""

    tinify_api_key: str
    use_tinify: bool

    @staticmethod
    def read_from_file(file: Path):
        """Create Config instance from file."""
        cp = configparser.ConfigParser()
        cp.read(file)
        config_sections = ["GENERAL", "TINIFY"]

        for sec in config_sections:
            try:
                cp.add_section(sec)
            except configparser.DuplicateSectionError:
                pass

        use_tinify = cp.getboolean("GENERAL", "use_tinify", fallback=False)
        api_key = cp.get("TINIFY", "api_key", fallback="")
        if not cp.has_option("GENERAL", "use_tinify"):
            cp.set("GENERAL", "use_tinify", str(use_tinify))
        if not cp.has_option("TINIFY", "api_key"):
            cp.set("TINIFY", "api_key", api_key)
        if use_tinify and not api_key:
            try:
                api_key = input("Enter Tinify API key: ")
                tinify.validate()
            except tinify.Error:
                print("Invalid Tinify API key: '%s'", sys.stderr)
                sys.exit(1)
            if api_key:
                LOG.info("User input for Tinify API key: '%s'", api_key)
                print("Tinify API key will be saved to conf.ini file.")
                cp.set("TINIFY", "api_key", api_key)
        with open(file, "w") as f:
            cp.write(f)
        return Config(api_key, use_tinify)


class Position(Enum):
    """Predefined locations of text watermark."""

    TOP_LEFT = "top-left"
    TOP_RIGHT = "top-right"
    BOTTOM_RIGHT = "bottom-right"
    BOTTOM_LEFT = "bottom-left"

    def __str__(self):
        return self.value.lower()

    def __repr__(self):
        return str(self)

    @staticmethod
    def argparse(s):
        """Helper to parse string values from CLI into Position."""
        vals = {x.value.lower(): x for x in list(Position)}
        try:
            return vals[s.lower()]
        except KeyError:
            return s


def tinify_image(filename):
    tinify.key = "1VwxdYS5L9H7D8mmK3jLsRH1995JV4y4"
    source = tinify.from_file(filename)
    source.to_file(filename)


def parse_args(args: list):
    """Parse command line arguments."""
    # flags
    desc = (
        "A command-line utility which uses the vips library to manipulate "
        "images for web vewing. Images can be resampled, resized, and "
        "compressed at custom quality levels. Watermarking can also be added."
    )
    parser = argparse.ArgumentParser(prog="pyimg", description=desc, add_help=False)

    # Positionals
    parser.add_argument("input", help="image file to process", metavar="INPUT")
    parser.add_argument("output", help="file to save processed image", metavar="OUTPUT")

    # Flags
    parser.add_argument(
        "-c",
        help="read from this config file (default: conf.ini)",
        dest="config_file",
        default="conf.ini",
    )
    parser.add_argument(
        "-v",
        help="increase logging output to console",
        action="count",
        dest="verbosity",
        default=0,
    )
    parser.add_argument("-h", action="help", help="show this help message and exit")
    parser.add_argument("--help", action="help", help=argparse.SUPPRESS)
    parser.add_argument("-V", action="version", version="%(prog)s 0.0.1")
    parser.add_argument(
        "-s",
        nargs=1,
        help="text suffix appended to INPUT path if no OUTPUT file given",
        metavar="TEXT",
        default="_edited",
    )
    parser.add_argument(
        "-t",
        help="use tinify API for resize/compression",
        action="store_true",
        dest="use_tinify",
    )
    parser.add_argument(
        "-n",
        help="display results only; don't save file",
        dest="no_op",
        action="store_true",
    )

    # Image group
    image_group = parser.add_argument_group("General image options")
    image_group.add_argument(
        "-p",
        help="scale output by percent of orig size",
        dest="pct_scale",
        metavar="SCALE",
        type=float,
    )
    image_group.add_argument(
        "-mw", help="maximum width of output", dest="width", metavar="WIDTH", type=int
    )
    image_group.add_argument(
        "-mh",
        help="maximum height of output",
        dest="height",
        metavar="HEIGHT",
        type=int,
    )
    image_group.add_argument(
        "-ke", help="keep exif data if possible", dest="keep_exif", action="store_true"
    )

    # Watermark group
    watermark_group = parser.add_argument_group("Watermark options")
    watermark_group.add_argument(
        "-wt",
        help="text to display in watermark",
        type=str,
        dest="watermark_text",
        metavar="TEXT",
    )
    watermark_group.add_argument(
        "-wf",
        help="image file to use as watermark",
        type=Path,
        dest="watermark_file",
        metavar="PATH",
    )
    watermark_group.add_argument(
        "-wr",
        help="angle of watermark rotation",
        dest="watermark_rotation",
        metavar="ANGLE",
        type=int,
        default=0,
    )
    watermark_group.add_argument(
        "-wo",
        help="watermark opacity",
        dest="watermark_opacity",
        type=float,
        metavar="OPACITY",
        default=0.3,
    )
    watermark_group.add_argument(
        "-wp",
        help="watermark position",
        dest="watermark_position",
        metavar="POS",
        default=Position.BOTTOM_RIGHT,
        type=Position.argparse,
        choices=list(Position),
    )

    # Jpg group
    jpg_group = parser.add_argument_group("Jpeg options")
    jpg_group.add_argument(
        "-q",
        help="Quality setting for jpeg files (an integer between 1 and 100; default: 75)",
        type=int,
        dest="jpg_quality",
        default=75,
        metavar="QUALITY",
    )

    if parser._positionals.title is not None:
        parser._positionals.title = "Arguments"
    if parser._optionals.title is not None:
        parser._optionals.title = "Options"
    parsed = parser.parse_intermixed_args(args)

    # do basic validation
    if not 0 <= parsed.jpg_quality <= 100:
        parser.error(f"Quality (-q) must be within 0-100; found: {parsed.jpg_quality}")

    if parsed.watermark_text is not None and parsed.watermark_file is not None:
        parser.error("Can use either -wt or -wf, not both")
    return parsed


def humanize_bytes(num, suffix="B", si_prefix=False, round_digits=2) -> str:
    """Return a human friendly byte representation.

    Modified from: https://stackoverflow.com/questions/1094841/1094933#1094933
    """
    div = 1000.0 if si_prefix else 1024.0
    unit_suffix = "i" if si_prefix else ""
    for unit in ["", "k", "M", "G", "T", "P", "E", "Z"]:
        if abs(num) < div:
            return f"{num:3.{round_digits}f} {unit}{unit_suffix}{suffix}"
        num /= div
    return f"{num:3.{round_digits}f} Y{unit_suffix}{suffix}"


def main():
    """Start point."""
    args = parse_args(sys.argv[1:])
    cfg = Config.read_from_file(args.config_file)
    inbuf = BytesIO()
    outbuf = BytesIO()
    with open(args.input, "rb") as f:
        inbuf.write(f.read())
    orig_size = inbuf.tell()
    im = Image.open(inbuf)
    in_width, in_height = im.size
    LOG.info("Input dims: %s", (in_width, in_height))
    LOG.info("Input size: %s", humanize_bytes(orig_size))

    # get new dims from args
    if args.pct_scale:
        LOG.info("Scaling image by %.1f%%", args.pct_scale)
        args.width = int(round(in_width * args.pct_scale))
        args.height = int(round(in_height * args.pct_scale))
    if args.width and not args.height:
        LOG.info("Calculating height based on width")
        args.height = int(round((args.width * in_height) / in_width))
    elif args.height and not args.width:
        LOG.info("Calculating width based on height")
        args.width = int(round((args.height * in_width) / in_height))

    if args.watermark_file:
        watermark_image = Image.open(os.path.expanduser(args.watermark_file)).convert(
            "RGBA"
        )

        mask = watermark_image.split()[3].point(lambda i: i * args.watermark_opacity)
        pos = (
            (in_width - watermark_image.width - 25),
            (in_height - watermark_image.height - 25),
        )
        im.paste(watermark_image, pos, mask)

    if cfg.use_tinify or args.use_tinify:
        tinify.tinify.key = cfg.tinify_api_key
        im.save(outbuf, "JPEG")
        try:
            outbuf = (
                tinify.tinify.from_buffer(outbuf.getvalue())
                .resize(method="scale", width=args.width)
                .to_buffer()
            )
            LOG.info("Tinify monthly count: %d", tinify.tinify.compression_count)
        except tinify.errors.AccountError:
            print(
                "Tinify API key invalid; check API key and try again.", file=sys.stderr
            )
            LOG.critical(
                "Aborting due to invalid Tinify API key: '%s'", cfg.tinify_api_key
            )
            sys.exit(1)
    else:
        im.thumbnail((args.width, args.height), Image.ANTIALIAS)
        out_width, out_height = im.size
        LOG.info("Output dims: %s", (out_width, out_height))
        im.save(outbuf, "JPEG")
        outbuf = outbuf.getvalue()
    new_size = sys.getsizeof(outbuf)
    LOG.info("Output size: %s", humanize_bytes(new_size))

    if not args.no_op:
        LOG.info("Saving buffer to %s", args.output)
        with open(args.output, "wb") as f:
            f.write(outbuf)


if __name__ == "__main__":
    main()
