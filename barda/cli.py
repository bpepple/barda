"""Cli for Barda."""
import logging
from argparse import Namespace

from barda.options import make_parser
from barda.run import Runner
from barda.settings import BardaSettings

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)
handler = logging.FileHandler("barda.log")
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
handler.setFormatter(formatter)
LOGGER.addHandler(handler)


def get_args() -> Namespace:
    parser = make_parser()
    return parser.parse_args()


def get_configs(opts: Namespace) -> BardaSettings:
    return BardaSettings()


def main():
    LOGGER.info("Program starting.")
    args = get_args()
    config = get_configs(args)

    runner = Runner(config)
    runner.run()
    LOGGER.info("Program ending.")


if __name__ == "__main__":
    main()
