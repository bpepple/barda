import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Optional

import questionary
import requests
from dateutil import relativedelta
from esak import api, sqlite_cache
from mokkari import api as metron
from mokkari.series import SeriesTypeList

from barda.exceptions import ApiError
from barda.gcd.gcd_issue import Rating
from barda.image import CVImage
from barda.import_series import ImageType
from barda.post_data import PostData
from barda.settings import BardaSettings
from barda.styles import Styles
from barda.validators import NumberValidator, YearValidator


class MarvelNewReleases:
    def __init__(self, config: BardaSettings) -> None:
        marvel_cache = sqlite_cache.SqliteCache(str(config.marvel_cache), 2)
        self.marvel = api(config.marvel_public_key, config.marvel_private_key, marvel_cache)
        self.metron = metron(config.metron_user, config.metron_password)
        self.barda = PostData(config.metron_user, config.metron_password)
        self.image_dir = TemporaryDirectory()

    @staticmethod
    def _determine_cover_date(release_date: date) -> date:
        new_date = release_date + relativedelta.relativedelta(months=2)
        return new_date.replace(day=1)

    @staticmethod
    def _get_title_name(title: str) -> str:
        idx = title.rfind("(")
        return title[:idx].strip()

    @staticmethod
    def _get_title_year(title: str) -> int:
        idx = title.rfind("(")
        tmp = title[idx:]
        year = "".join(c for c in tmp if c.isdigit())
        if len(year) > 4:
            year = year[:4]
        return int(year)

    @staticmethod
    def _create_series_choice(item) -> List[questionary.Choice] | None:
        if not item:
            return None
        choices: List[questionary.Choice] = []
        for i in item:
            choice = questionary.Choice(title=i.display_name, value=i.id)
            choices.append(choice)
        choices.append(questionary.Choice(title="None", value=""))
        return choices

    @staticmethod
    def _check_for_solicit_txt(text_objects) -> Optional[str]:
        return next((i.text for i in text_objects if i.type == "issue_solicit_text"), None)

    def _add_ceb_credits(self, issue_id: int) -> None:
        CB = 215  # Metron ID
        EIC = 20
        data = {"issue": issue_id, "creator": CB, "role": [EIC]}
        credits_lst = [data]
        try:
            self.barda.post_credit(credits_lst)
            questionary.print("Added credits for CB.", style=Styles.SUCCESS)
        except ApiError:
            questionary.print("Failed to add credits for CB", style=Styles.ERROR)

    def _get_cover(self, url: str, img_type: ImageType) -> str:
        receive = requests.get(url)
        cover = Path(url)
        new_fn = f"{uuid.uuid4().hex}{cover.suffix}"
        img_file = Path(self.image_dir.name) / new_fn
        img_file.write_bytes(receive.content)
        cv_img = CVImage(img_file)
        match img_type:
            case ImageType.Cover:
                cv_img.resize_cover()
            case ImageType.Resource:
                cv_img.resize_resource()
            case ImageType.Creator:
                cv_img.resize_creator()
            case _:
                return ""

        return str(img_file)

    ###############
    # Series Type #
    ###############
    def _choose_series_type(self):  # sourcery skip: class-extract-method
        st_lst: SeriesTypeList = self.metron.series_type_list()
        choices = []
        for s in st_lst:
            choice = questionary.Choice(title=s.name, value=s.id)
            choices.append(choice)
        return questionary.select("What type of series is this?", choices=choices).ask()

    ##########
    # Series #
    ##########
    def _create_series(self, name: str, year: int) -> int:
        series_name = (
            name
            if questionary.confirm(f"Is '{name}' the correct name?").ask()
            else questionary.text("What should the series name be?").ask()
        )
        sort_name = (
            series_name
            if questionary.confirm(f"Should '{series_name}' also be the Sort Name?").ask()
            else questionary.text("What should the sort name be?").ask()
        )
        volume = int(
            questionary.text(
                f"What is the volume number for '{name} ({year})'?", validate=NumberValidator
            ).ask()
        )
        series_type_id = self._choose_series_type()
        year_began = (
            year
            if questionary.confirm(f"Is '{year}' the correct year that this series began?").ask()
            else int(
                questionary.text(
                    "What begin year should be used for this series?", validate=YearValidator
                ).ask()
            )
        )
        if series_type_id in [11, 2]:
            year_end = int(
                questionary.text("What year did this series end in?", validate=YearValidator).ask()
            )
        else:
            year_end = None
        desc = questionary.text(f"Do you want to add a series summary for '{name} ({year})'?").ask()

        data = {
            "name": series_name,
            "sort_name": sort_name,
            "volume": volume,
            "desc": desc,
            "series_type": series_type_id,
            "publisher": 1,  # Marvel publisher id
            "year_began": year_began,
            "year_end": year_end,
            "genres": [],
            "associated": [],
        }

        try:
            new_series = self.barda.post_series(data)
        except ApiError:
            questionary.print(
                f"Failed to create series for '{series_name}'. Exiting...", style=Styles.ERROR
            )
            exit(0)

        return new_series["id"]

    def _create_issue(self, series_id: int, comic):
        cover_date = self._determine_cover_date(comic.dates.on_sale)
        desc = ""
        if solicit := self._check_for_solicit_txt(comic.text_objects):
            desc = solicit
        price = comic.prices.print if comic.prices.print > Decimal("0.00") else None
        if comic.images:
            cover = self._get_cover(comic.images[0], ImageType.Cover)
        else:
            cover = ""

        data = {
            "series": series_id,
            "number": comic.issue_number,
            "name": [],
            "cover_date": cover_date,
            "store_date": comic.dates.on_sale,
            "desc": desc,
            "upc": comic.upc,
            "sku": comic.diamond_code,
            "price": price,
            "page": comic.page_count,
            "rating": Rating.Unknown.value,
            "image": cover,
            "characters": [],
            "teams": [],
            "arcs": [],
        }

        try:
            resp = self.barda.post_issue(data)
        except ApiError:
            return None

        self._add_ceb_credits(resp["id"])

        return resp

    def run(self) -> None:
        release_str = questionary.text(
            "What is the first day of the week you want to search for? (Ex. 2022-12-21)"
        ).ask()
        start_date = datetime.strptime(release_str, "%Y-%m-%d").date()
        end_date = start_date + relativedelta.relativedelta(days=6)

        # Get data from Marvel
        comics_lst = self.marvel.comics_list(
            {
                "format": "comic",
                "formatType": "comic",
                "noVariants": True,
                "dateRange": f"{start_date},{end_date}",
            }
        )

        # Query Metron
        for comic in comics_lst:
            series_name = self._get_title_name(comic.series.name)
            series_year = self._get_title_year(comic.series.name)
            series_lst = self.metron.series_list({"name": series_name})
            choices = self._create_series_choice(series_lst)
            if choices is not None:
                series_id = questionary.select(
                    f"What series should be used for '{series_name} ({series_year})'?",
                    choices=choices,
                ).ask()
            else:
                series_id = ""
            if not series_id:
                if questionary.confirm(
                    f"Nothing found for '{series_name}'. Do you want to create a new series?"
                ).ask():
                    series_id = self._create_series(series_name, series_year)
                else:
                    questionary.print("Ok, continuing to next comic...", style=Styles.SUCCESS)
                    continue

            # Check if issue exists and if not add it.
            if self.metron.issues_list(
                params={"series_id": series_id, "number": comic.issue_number}
            ):
                questionary.print(
                    f"'{series_name} #{comic.issue_number}' already existing on Metron. Going to next comic...",
                    style=Styles.WARNING,
                )
            else:
                new_issue = self._create_issue(series_id, comic)
                if new_issue is not None:
                    questionary.print(
                        f"Added '{series_name} #{comic.issue_number}'", style=Styles.SUCCESS
                    )
                else:
                    questionary.print(
                        f"Failed to create '{series_name} #{comic.issue_number}'.",
                        style=Styles.ERROR,
                    )
