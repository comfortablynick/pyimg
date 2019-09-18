"""Classes, enums, and misc data containers."""

import argparse
import configparser
import logging
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple

import tinify

LOG = logging.getLogger(__name__)


class Position(Enum):
    """Predefined locations of text watermark."""

    TOP_LEFT = "top-left"
    TOP_RIGHT = "top-right"
    BOTTOM_RIGHT = "bottom-right"

    BOTTOM_LEFT = "bottom-left"

    def __str__(self):
        """Return enum value in lowercase."""
        return self.value.lower()

    def __repr__(self):
        """Return string representation of enum."""
        return str(self)

    @staticmethod
    def argparse(s):
        """Parse string values from CLI into Position."""
        vals = {x.value.lower(): x for x in list(Position)}
        try:
            return vals[s.lower()]
        except KeyError:
            return s


@dataclass
class Config:
    """Store options from config file and command line."""

    input_file: Optional[Path] = None
    output_file: Optional[Path] = None
    verbosity: int = 0
    suffix: Optional[str] = None
    tinify_api_key: Optional[str] = None
    use_tinify: bool = False
    no_op: bool = False
    pct_scale: float = 0
    width: int = 0
    height: int = 0
    keep_exif: bool = False
    watermark_text: Optional[str] = None
    watermark_image: Optional[Path] = None
    watermark_rotation: int = 0
    watermark_opacity: float = 0
    watermark_position: Optional[Position] = None
    jpg_quality: int = 0

    @staticmethod
    def from_args(args: argparse.Namespace):
        """Create Config instance from file and command line args."""
        cp = configparser.ConfigParser()
        cp.read(args.config_file)
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
        if use_tinify or args.use_tinify:
            if not api_key:
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
            tinify.key = api_key
        with open(args.config_file, "w") as f:
            cp.write(f)
        cfg = Config(tinify_api_key=api_key, use_tinify=use_tinify)
        cfg.merge_cli_args(args)
        return cfg

    def merge_cli_args(self, args: argparse.Namespace):
        """Update existing config object from command line args."""
        self.input_file = args.input
        self.output_file = args.output
        self.verbosity = args.verbosity
        self.suffix = args.suffix
        self.use_tinify = args.use_tinify
        self.no_op = args.no_op
        self.pct_scale = args.pct_scale
        self.width = args.width
        self.height = args.height
        self.keep_exif = args.keep_exif
        self.watermark_text = args.watermark_text
        self.watermark_image = args.watermark_image
        self.watermark_rotation = args.watermark_rotation
        self.watermark_opacity = args.watermark_opacity
        self.watermark_position = args.watermark_position
        self.jpg_quality = args.jpg_quality


@dataclass
class ImageSize:
    """Pixel dimensions of image."""

    width: int = 0
    height: int = 0


@dataclass
class ImageContext:
    """Store details about the image being processed."""

    orig_size: ImageSize = ImageSize()
    new_size: ImageSize = ImageSize()
    orig_file_size: int = 0
    new_file_size: int = 0
    orig_dpi: Tuple[int, int] = (0, 0)
    new_dpi: Tuple[int, int] = (0, 0)
    image_buffer: Optional[bytes] = None
    orig_exif: Optional[dict] = None

    def as_dict_copy(self) -> dict:
        """Return dict representation as copy without `image_buffer` included."""
        out = self.__dict__.copy()
        try:
            del out["image_buffer"]
            del out["orig_exif"]
        except KeyError:
            pass
        return out

