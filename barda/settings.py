"""Class to handle project settings"""

import configparser
from pathlib import Path
from typing import Optional

from xdg.BaseDirectory import save_cache_path

from barda.utils import get_settings_folder


class BardaSettings:
    """Class to handle project settings"""

    def __init__(self, config_dir: Optional[str] = None) -> None:
        # Online service credentials
        self.metron_user: str = ""
        self.metron_password: str = ""
        self.cv_api_key: Optional[str] = None

        self.config = configparser.ConfigParser()

        # setting & json file locations
        folder = Path(config_dir) if config_dir else get_settings_folder()
        self.settings_file = folder / "settings.ini"
        cache_folder = Path(save_cache_path("barda"))
        self.conversions = cache_folder / "barda.db"
        self.cv_cache = cache_folder / "cv.db"
        self.metron_cache = cache_folder / "metron.db"

        if not self.settings_file.parent.exists():
            self.settings_file.parent.mkdir()

        # Write the config file if it doesn't exist
        if not self.settings_file.exists():
            self.save()
        else:
            self.load()

    def load(self) -> None:
        """Method to retrieve a users settings."""
        self.config.read(self.settings_file)

        if self.config.has_option("metron", "user"):
            self.metron_user = self.config["metron"]["user"]

        if self.config.has_option("metron", "password"):
            self.metron_password = self.config["metron"]["password"]

        if self.config.has_option("comic_vine", "api_key"):
            self.cv_api_key = self.config["comic_vine"]["api_key"]

    def save(self) -> None:
        """Method to save a users settings"""
        if not self.config.has_section("metron"):
            self.config.add_section("metron")

        self.config["metron"]["user"] = self.metron_user
        self.config["metron"]["password"] = self.metron_password

        if not self.config.has_section("comic_vine"):
            self.config.add_section("comic_vine")

        if self.cv_api_key:
            self.config["comic_vine"]["api_key"] = self.cv_api_key

        with self.settings_file.open("w") as configfile:
            self.config.write(configfile)
