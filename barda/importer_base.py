from enum import Enum, unique
from tempfile import TemporaryDirectory
from typing import List

import questionary
from mokkari import api
from mokkari.publisher import PublishersList
from mokkari.series import SeriesTypeList
from mokkari.session import Session

from barda import __version__
from barda.post_data import PostData
from barda.settings import BardaSettings
from barda.validators import YearValidator


@unique
class MetronGenres(Enum):
    Adult = 1
    Crime = 13
    Espionage = 2
    Fantasy = 3
    Historical = 4
    Horror = 5
    Humor = 6
    Manga = 7
    Parody = 14
    Romance = 8
    Science_Fiction = 9
    Sport = 15
    Super_Hero = 10
    War = 11
    Western = 12


class BaseImporter:
    def __init__(self, config: BardaSettings) -> None:
        self.image_dir = TemporaryDirectory()
        self.barda = PostData(config.metron_user, config.metron_password)
        self.metron: Session = api(config.metron_user, config.metron_password, user_agent=f"Barda/{__version__}")
        self.series_type: SeriesTypeList | None = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.image_dir.cleanup()

    ########
    # Misc #
    ########
    @staticmethod
    def _create_choices(item) -> List[questionary.Choice] | None:
        if not item:
            return None
        choices: List[questionary.Choice] = []
        for i in item:
            choice = questionary.Choice(title=i.name, value=i.id)
            choices.append(choice)
        choices.append(questionary.Choice(title="None", value=""))
        return choices

    ###############
    # Series Type #
    ###############
    def _choose_series_type(self) -> int:
        if self.series_type is None:
            self.series_type = self.metron.series_type_list()
        choices = []
        for s in self.series_type:
            choice = questionary.Choice(title=s.name, value=s.id)
            choices.append(choice)
        return int(questionary.select("What type of series is this?", choices=choices).ask())

    #########
    # Genre #
    #########
    @staticmethod
    def _choose_genre() -> list[int]:
        choices = []
        for i in MetronGenres:
            choice = questionary.Choice(title=i.name, value=i.value)
            choices.append(choice)
        return questionary.checkbox("What genre should this series be?", choices=choices).ask()

    #############
    # Publisher #
    #############
    def _choose_publisher(self) -> int:
        pub_lst: PublishersList = self.metron.publishers_list()
        choices = []
        for p in pub_lst:
            choice = questionary.Choice(title=p.name, value=p.id)
            choices.append(choice)
        # TODO: Provide option to add a Publisher
        return int(
            questionary.select("Which publisher is this series from?", choices=choices).ask()
        )

    ##########
    # Series #
    ##########
    @staticmethod
    def _determine_series_name(series_name: str) -> str:
        return (
            series_name
            if questionary.confirm(f"Is '{series_name}' the correct name?").ask()
            else questionary.text("What should the series name be?").ask()
        )

    @staticmethod
    def _determine_series_sort_name(series_name: str) -> str:
        return (
            series_name
            if questionary.confirm(f"Should '{series_name}' also be the Sort Name?").ask()
            else questionary.text("What should the sort name be?").ask()
        )

    @staticmethod
    def _determine_series_year_began(start_year: int | None = None) -> int:
        if start_year is None:
            return int(
                questionary.text(
                    "No begin year found. What begin year should be used for this series?",
                    validate=YearValidator,
                ).ask()
            )
        return (
            start_year
            if questionary.confirm(
                f"Is '{start_year}' the correct year that this series began?"
            ).ask()
            else int(
                questionary.text(
                    "What begin year should be used for this series?",
                    validate=YearValidator,
                ).ask()
            )
        )

    @staticmethod
    def _determine_series_year_end(series_type_id: int) -> int | None:
        return (
            int(questionary.text("What year did this series end in?", validate=YearValidator).ask())
            if series_type_id in {11, 2}
            else None
        )
