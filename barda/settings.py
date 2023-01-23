"""Class to handle project settings"""

import configparser
import json
import platform
from os import environ
from pathlib import Path, PurePath
from typing import List, Optional, TypedDict

from xdg.BaseDirectory import save_config_path


class ComicVine(TypedDict):
    cv: int
    metron: str


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

        # Resource key files
        self.creator: Optional[List[ComicVine]] = None
        self.characters: Optional[List[ComicVine]] = None
        self.teams: Optional[List[ComicVine]] = None

        self.config = configparser.ConfigParser()

        # setting & json file locations
        folder = Path(config_dir) if config_dir else BardaSettings.get_settings_folder()
        self.settings_file = folder / "settings.ini"
        self.creators_file = folder / "creator.json"
        self.characters_file = folder / "characters.json"
        self.teams_file = folder / "teams.json"

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

        if self.creators_file.exists():
            with open(self.creators_file) as creator_file:
                self.creator = json.load(creator_file)

        if self.characters_file.exists():
            with open(self.characters_file) as characters:
                self.characters = json.load(characters)

        if self.teams_file.exists():
            with open(self.teams_file) as teams:
                self.teams = json.load(teams)

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
