"""Cli for Barda."""

from argparse import Namespace

from barda.options import make_parser
from barda.run import Runner
from barda.settings import BardaSettings


def get_args() -> Namespace:
    parser = make_parser()
    return parser.parse_args()


def get_configs(opts: Namespace) -> BardaSettings:
    return BardaSettings()


def main():
    args = get_args()
    config = get_configs(args)

    runner = Runner(config)
    runner.run()


if __name__ == "__main__":
    main()
