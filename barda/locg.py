import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum, unique
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, List

import dateutil.relativedelta
import questionary
import requests
from comicgeeks import Comic_Geeks
from comicgeeks.Comic_Geeks import Character, Issue
from mokkari import api
from mokkari.publisher import PublishersList
from mokkari.series import SeriesTypeList
from mokkari.session import Session

from barda.exceptions import ApiError
from barda.gcd.gcd_issue import Rating
from barda.image import CVImage
from barda.post_data import PostData
from barda.settings import BardaSettings
from barda.styles import Styles
from barda.validators import NumberValidator, YearValidator


@unique
class Metron_Genres(Enum):
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


class LeagueOfComicGeeks:
    def __init__(self, config: BardaSettings) -> None:
        self.image_dir = TemporaryDirectory()
        self.locg: Comic_Geeks | None = None
        self.metron: Session = api(config.metron_user, config.metron_password)
        self.barda = PostData(config.metron_user, config.metron_password)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.image_dir.cleanup()

    def _get_cover(self, url: str) -> str:
        receive = requests.get(url)
        img = Path(url)
        ext = img.suffix.split("?")
        new_fn = f"{uuid.uuid4().hex}{ext[0]}"
        img_file = Path(self.image_dir.name) / new_fn
        img_file.write_bytes(receive.content)
        cover = CVImage(img_file)
        cover.resize_cover()
        return str(img_file)

    def _setup_client(self) -> None:
        session_id = questionary.text("Enter you League of Comic Geeks session id").ask()
        self.locg = Comic_Geeks(session_id)

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

    ##############
    # Characters #
    ##############
    def _choose_character(self, character: str) -> int | None:
        if not character:
            return None

        questionary.print(
            f"Let's do a character search on Metron for '{character}'", style=Styles.TITLE
        )
        c_list = self.metron.characters_list(params={"name": character})
        choices = self._create_choices(c_list)
        if choices is None:
            questionary.print(f"Nothing found for '{character}'", style=Styles.WARNING)
            return None

        return questionary.select(
            f"What character should be added for '{character}'?", choices=choices
        ).ask()

    def _search_for_character(self, character: str) -> int | None:
        return self._choose_character(character) if character else None

    def _create_characters_list(self, characters: List[Character]) -> List[int]:
        characters_lst = []
        for c in characters:
            metron_id = self._search_for_character(c.name)
            if metron_id is None:
                continue
            characters_lst.append(metron_id)
        return characters_lst

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

    ###############
    # Series Type #
    ###############
    def _choose_series_type(self) -> int:  # sourcery skip: class-extract-method
        st_lst: SeriesTypeList = self.metron.series_type_list()
        choices = []
        for s in st_lst:
            choice = questionary.Choice(title=s.name, value=s.id)
            choices.append(choice)
        return int(questionary.select("What type of series is this?", choices=choices).ask())

    #########
    # Genre #
    #########
    def _choose_genre(self) -> int:
        choices = []
        for i in Metron_Genres:
            choice = questionary.Choice(title=i.name, value=i.value)
            choices.append(choice)
        return int(questionary.select("What genre should this series be?", choices=choices).ask())

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
        if start_year is not None:
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
        else:
            return int(
                questionary.text(
                    "No begin year found. What begin year should be used for this series?",
                    validate=YearValidator,
                ).ask()
            )

    @staticmethod
    def _determine_series_year_end(series_type_id: int) -> int | None:
        return (
            int(questionary.text("What year did this series end in?", validate=YearValidator).ask())
            if series_type_id in {11, 2}
            else None
        )

    @staticmethod
    def _get_series_name(name: str) -> str:
        series = name.split("#")
        return series[0].strip()

    def _ask_for_series_info(self, series: str) -> dict[str, Any]:
        questionary.print(
            f"Series '{series}' needs to be created on Metron",
            style=Styles.TITLE,
        )
        series_name = self._determine_series_name(series)
        sort_name = self._determine_series_sort_name(series_name)
        volume = int(
            questionary.text(
                f"What is the volume number for '{series_name}'?", validate=NumberValidator
            ).ask()
        )
        publisher_id = self._choose_publisher()
        series_type_id = self._choose_series_type()
        year_began = self._determine_series_year_began()
        year_end = self._determine_series_year_end(series_type_id)
        genres: List[int] = [self._choose_genre()]
        desc: str = questionary.text(f"Do you want to add a series summary for '{series}'?").ask()

        return {
            "name": series_name,
            "sort_name": sort_name,
            "volume": volume,
            "desc": desc,
            "series_type": series_type_id,
            "publisher": publisher_id,
            "year_began": year_began,
            "year_end": year_end,
            "genres": genres,
            "associated": [],
        }

    def _create_series(self, series: str) -> int | None:
        data = self._ask_for_series_info(series)

        try:
            new_series = self.barda.post_series(data)
        except ApiError:
            questionary.print(
                f"Failed to create series for '{data['name']}'. Exiting...", style=Styles.ERROR
            )
            exit(0)

        return None if new_series is None else new_series["id"]

    def _check_metron_for_series(self, series: str) -> str | None:
        if series_lst := self.metron.series_list({"name": series}):
            choices: List[questionary.Choice] = []
            for i in series_lst:
                choice = questionary.Choice(title=i.display_name, value=i.id)
                choices.append(choice)
            choices.append(questionary.Choice(title="None", value=""))
            return questionary.select(
                f"What series on Metron should be used for '{series}'?",
                choices=choices,
            ).ask()
        else:
            return None

    def _get_series_id(self, series: str) -> int | None:
        mseries_id = self._check_metron_for_series(series)
        return (
            self._create_series(series) if not mseries_id or mseries_id is None else int(mseries_id)
        )

    #########
    # Issue #
    #########
    def _retrieve_issue(self) -> Issue | None:
        if self.locg:
            id_ = questionary.text(
                "What is the issue id for the issue to import?", validate=NumberValidator
            ).ask()
            return self.locg.issue_info(id_)

    def _get_publisher_id(self, series_id: int) -> int:
        ser = self.metron.series(series_id)
        return ser.publisher.id  # type: ignore

    @staticmethod
    def _get_store_date(store: int) -> date:
        return datetime.fromtimestamp(store).date()

    def _get_cover_date(self, series_id: int, store: date) -> date:
        pub_id = self._get_publisher_id(series_id)
        if pub_id not in [2, 26, 1, 24, 12, 8, 7]:
            return date(store.year, store.month, 1)
        new_date = store + dateutil.relativedelta.relativedelta(months=2)
        return new_date.replace(day=1)

    @staticmethod
    def _get_pages(pages: str) -> int | None:
        tmp_page = pages.split(" ")
        return int(tmp_page[0]) if tmp_page[0].isdecimal() else None

    def _create_issue(self, issue: Issue) -> None:
        series_name = self._get_series_name(issue.cover["name"])
        series_id = self._get_series_id(series_name)
        if series_id is None:
            questionary.print(f"Failed to find: {series_name}.", style=Styles.WARNING)
            return
        store_date = self._get_store_date(issue.store_date)
        cover_date = self._get_cover_date(series_id, store_date)
        try:
            upc = issue.details["upc"]
        except KeyError:
            upc = ""
        try:
            sku = issue.details["distributor_sku"].upper()
        except KeyError:
            sku = ""
        cover = self._get_cover(issue.cover["image"])
        character_lst = self._create_characters_list(issue.characters)
        try:
            pages = self._get_pages(issue.details["page_count"])
        except KeyError:
            pages = ""

        if pages is None:
            pages = ""

        data = {
            "series": series_id,
            "number": issue.number,
            "name": [],
            "cover_date": cover_date,
            "store_date": store_date,
            "desc": issue.description.strip(),
            "upc": upc,
            "sku": sku,
            "price": Decimal(repr(issue.price)),
            "page": pages,
            "rating": Rating.Unknown.value,
            "image": cover,
            "characters": character_lst,
            "teams": [],
            "arcs": [],
        }

        try:
            resp = self.barda.post_issue(data)
        except ApiError:
            questionary.print(f"API error: {series_name} #{issue.number}", style=Styles.ERROR)
            return

        if resp is not None:
            questionary.print(
                f"Added '{series_name} #{issue.number}' to Metron", style=Styles.SUCCESS
            )
        else:
            questionary.print(
                f"Failed to add '{series_name} #{issue.number}' to Metron", style=Styles.WARNING
            )

    def run(self) -> None:
        self._setup_client()
        while questionary.confirm("Do you want to import an issue from LOCG?").ask():
            issue = self._retrieve_issue()
            if issue is not None:
                self._create_issue(issue)