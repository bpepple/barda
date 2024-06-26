import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, List

import dateutil.relativedelta
import questionary
import requests
from comicgeeks import Comic_Geeks
from comicgeeks.Comic_Geeks import Character, Issue
from mokkari.schemas.series import BaseSeries

from barda.exceptions import ApiError
from barda.gcd.gcd_issue import Rating
from barda.image import CVImage
from barda.importer_base import BaseImporter
from barda.settings import BardaSettings
from barda.styles import Styles
from barda.utils import clean_search_series_title
from barda.validators import NumberValidator


class GeeksImporter(BaseImporter):
    def __init__(self, config: BardaSettings) -> None:
        super(GeeksImporter, self).__init__(config)
        self.locg: Comic_Geeks | None = None

    def _get_cover(self, url: str, variant: bool = False) -> str:
        receive = requests.get(url)
        img = Path(url)
        ext = img.suffix.split("?")
        new_fn = f"{uuid.uuid4().hex}{ext[0]}"
        img_file = Path(self.image_dir.name) / new_fn
        img_file.write_bytes(receive.content)
        cover = CVImage(img_file)
        if not variant:
            cover.resize_cover()
        else:
            cover.resize_resource()
        return str(img_file)

    def _setup_client(self) -> None:
        self.locg = Comic_Geeks()
        self.locg.login("bpepple", "kT4qy23sA54CzAWT9^y3")

    ############
    # Variants #
    ############

    @staticmethod
    def _variant_name(name: str) -> str:
        split = name.split(" ")
        begin = next(
            (idx + 1 for idx, item in enumerate(split) if item.lower().startswith("#")),
            None,
        )
        if begin is not None:
            new_name = " ".join(split[begin:])
            bad_name = " Card Stock"
            if bad_name in new_name:
                new_name = new_name.replace(bad_name, "")
            return new_name

        return name

    def _get_variants(self, issue_id: int, issue: Issue) -> None:
        for item in issue.variant_covers:
            name = self._variant_name(item["name"])
            if questionary.confirm(
                f"Do you want to a variant for '{name}' to '{issue.cover['name']}'"
            ).ask():
                img = self._get_cover(item["image"], variant=True)
                data = {
                    "issue": issue_id,
                    "image": img,
                    "name": name,
                    "sku": "",
                    "upc": "",
                }
                try:
                    resp = self.barda.post_variant(data)
                except ApiError:
                    questionary.print(
                        f"Failed to upload variant cover. Data: {data}", style=Styles.ERROR
                    )
                    continue

                if resp is not None:
                    questionary.print(
                        f"Added variant cover: {issue.cover['name']}", style=Styles.SUCCESS
                    )

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
            if metron_id is None or metron_id == "":
                continue
            else:
                characters_lst.append(metron_id)
        return characters_lst

    ##########
    # Series #
    ##########
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
        genres = self._choose_genre()
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

    @staticmethod
    def _select_metron_series(series_lst: list[BaseSeries], series):
        choices: List[questionary.Choice] = []
        for i in series_lst:
            choice = questionary.Choice(title=i.display_name, value=i.id)
            choices.append(choice)
        choices.append(questionary.Choice(title="None", value=""))
        return questionary.select(
            f"What series on Metron should be used for '{series}'?",
            choices=choices,
        ).ask()

    def _check_metron_for_series(self, series: str) -> str | None:
        if series_lst := self.metron.series_list({"name": clean_search_series_title(series)}):
            return self._select_metron_series(series_lst, series)

        if not questionary.confirm(
            f"Nothin found for {series} on Metron. Do you want to do another search?"
        ).ask():
            return None
        series_query = questionary.text("What series name should we use?").ask()
        return (
            self._select_metron_series(series_lst, series)
            if (series_lst := self.metron.series_list({"name": series_query}))
            else None
        )

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
        if pub_id not in {2, 26, 1, 24, 12, 8, 7, 13, 14}:
            return date(store.year, store.month, 1)
        new_date = store + dateutil.relativedelta.relativedelta(months=2)
        return new_date.replace(day=1)

    @staticmethod
    def _get_pages(issue: Issue) -> int | str:
        try:
            pages = issue.details["page_count"]
        except KeyError:
            return ""

        tmp_page = pages.split(" ")
        return int(tmp_page[0]) if tmp_page[0].isdecimal() else ""

    @staticmethod
    def _get_upc(issue: Issue) -> str:
        try:
            upc = issue.details["upc"]
        except KeyError:
            upc = ""
        return upc

    @staticmethod
    def _get_sku(issue: Issue) -> str:
        try:
            sku = issue.details["distributor_sku"].upper()
        except KeyError:
            sku = ""
        return sku

    @staticmethod
    def _get_price(issue: Issue) -> Decimal:
        try:
            price = Decimal(repr(issue.price))
        except InvalidOperation:
            price = Decimal("0")
        return price

    def _create_issue(self, issue: Issue) -> None:
        try:
            series_name = self._get_series_name(issue.cover["name"])
        except IndexError:
            questionary.print("Missing information on LOCG. Skipping...", style=Styles.WARNING)
            return
        series_id = self._get_series_id(series_name)
        if series_id is None:
            questionary.print(f"Failed to find: {series_name}.", style=Styles.WARNING)
            return
        issue_number = issue.number or "1"
        store_date = self._get_store_date(issue.store_date)
        cover_date = self._get_cover_date(series_id, store_date)
        upc = self._get_upc(issue)
        sku = self._get_sku(issue)
        cover = self._get_cover(issue.cover["image"])
        # if questionary.confirm("Do you want to add characters to this issue?").ask():
        #     character_lst = self._create_characters_list(issue.characters)
        # else:
        #     character_lst = []
        character_lst = []
        pages = self._get_pages(issue)
        price = self._get_price(issue)

        data = {
            "series": series_id,
            "number": issue_number,
            "name": [],
            "cover_date": cover_date,
            "store_date": store_date,
            "desc": issue.description.strip(),
            "upc": upc,
            "sku": sku,
            "price": price,
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
            resp = None

        if resp is not None:
            questionary.print(
                f"Added '{series_name} #{issue_number}' to Metron", style=Styles.SUCCESS
            )
            # if issue.variant_covers:
            #     if questionary.confirm("Do you want to add variant covers for this issue?").ask():
            #         self._get_variants(resp["id"], issue)
        else:
            questionary.print(
                f"'{series_name} #{issue_number}' already exists on Metron", style=Styles.WARNING
            )
            # if questionary.confirm("Do you want to add any variants to the existing issue?").ask():
            #     issue_lst = self.metron.issues_list(
            #         {"series_id": series_id, "number": issue_number}
            #     )
            #     if not issue_lst:
            #         return
            #
            #     if len(issue_lst) < 2:
            #         self._get_variants(issue_lst[0].id, issue)
            #     else:
            #         issue_choices = self._create_issue_choices(issue_lst)
            #         metron_issue = questionary.select(
            #             "What issue should be used?", choices=issue_choices
            #         ).ask()
            #         if metron_issue:
            #             self._get_variants(metron_issue.id, issue)

    def run(self) -> None:
        self._setup_client()
        while questionary.confirm("Do you want to import an issue from LOCG?").ask():
            issue = self._retrieve_issue()
            if issue is not None:
                self._create_issue(issue)
