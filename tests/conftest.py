from argparse import ArgumentParser

import pytest

from barda.options import make_parser


@pytest.fixture(scope="session")
def parser() -> ArgumentParser:
    return make_parser()
