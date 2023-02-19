"""Class to handle project settings"""

import configparser
import platform
from os import environ
from pathlib import Path, PurePath
from typing import Optional

from xdg.BaseDirectory import save_config_path


class BardaSettings:
    """Class to handle project settings"""

    @staticmethod
    def get_settings_folder() -> Path:
        """Method to determine where the users settings should be saved"""

        if platform.system() != "Windows":
            return Path(save_config_path("barda"))

        windows_path = PurePath(environ["APPDATA"]).joinpath("Barda")
        return Path(windows_path)

    def __init__(self, config_dir: Optional[str] = None) -> None:
        # Online service credentials
        self.metron_user: str = ""
        self.metron_password: str = ""
        self.cv_api_key: Optional[str] = None
        self.marvel_public_key: str = ""
        self.marvel_private_key: str = ""

        self.config = configparser.ConfigParser()

        # setting & json file locations
        folder = Path(config_dir) if config_dir else BardaSettings.get_settings_folder()
        self.settings_file = folder / "settings.ini"
        self.conversions = folder / "barda.db"
        self.cv_cache = folder / "cv.db"
        self.metron_cache = folder / "metron.db"
        self.marvel_cache = folder / "marvel.db"

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

        if self.config.has_option("marvel", "public_key"):
            self.marvel_public_key = self.config["marvel"]["public_key"]

        if self.config.has_option("marvel", "private_key"):
            self.marvel_private_key = self.config["marvel"]["private_key"]

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

        if not self.config.has_section("marvel"):
            self.config.add_section("marvel")

        if self.marvel_public_key:
            self.config["marvel"]["public_key"] = self.marvel_public_key
        if self.marvel_private_key:
            self.config["marvel"]["private_key"] = self.marvel_private_key

        with self.settings_file.open("w") as configfile:
            self.config.write(configfile)
