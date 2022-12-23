"""Utility to create an argument parser"""
import argparse

from barda import __version__


def make_parser():
    parser = argparse.ArgumentParser(
        description="Read in a file or set of files, and return the result.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("path", nargs="+", help="Path of a file or a folder of files.")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show the version number and exit",
    )

    return parser
