from logging import getLogger
from typing import Any, List

import questionary
from mokkari import api
from mokkari.series import SeriesList
from mokkari.session import Session

from barda.exceptions import ApiError
from barda.gcd.db import DB
from barda.gcd.gcd_issue import GCD_Issue
from barda.importer_base import BaseImporter
from barda.post_data import PostData
from barda.settings import BardaSettings
from barda.styles import Styles
from barda.utils import fix_story_chapters

LOGGER = getLogger(__name__)


class GcdUpdate(BaseImporter):
    def __init__(self, config: BardaSettings) -> None:
        super(GcdUpdate, self).__init__(config)
        self.metron: Session = api(config.metron_user, config.metron_password)
        self.barda = PostData(config.metron_user, config.metron_password)
        self.reprint_only: bool = False

    # GCD methods
    @staticmethod
    def _select_gcd_series(series_lst: List[Any]) -> int | None:
        choices = []
        for count, series in enumerate(series_lst, start=0):
            choice = questionary.Choice(
                title=f"{series[1]} ({series[2]}): {series[3]} issues - {series[4]}", value=count
            )
            choices.append(choice)
        choices.append(questionary.Choice(title="None", value=""))
        return questionary.select("What GCD series do you want to use?", choices=choices).ask()

    def _get_gcd_series_id(self):
        with DB() as db_obj:
            gcd_query = questionary.text("What series name do you want to use to search GCD?").ask()
            if gcd_series_list := db_obj.get_series_list(gcd_query):
                gcd_idx = self._select_gcd_series(gcd_series_list)
                gcd_series_id = None if gcd_idx is None else gcd_series_list[gcd_idx][0]
            else:
                questionary.print(f"Unable to find series '{gcd_query}' on GCD.")
                gcd_series_id = None
        return gcd_series_id

    @staticmethod
    def _select_gcd_issue(issue_lst: List[Any]) -> int | None:
        choices = []
        for count, issue in enumerate(issue_lst, start=0):
            choice = questionary.Choice(title=f"#{issue[1]}", value=count)
            choices.append(choice)
        choices.append(questionary.Choice(title="None", value=""))
        return questionary.select("What GCD issue number should be used?", choices=choices).ask()

    def _get_gcd_issue(self, gcd_series_id, issue_number: str) -> GCD_Issue | None:
        with DB() as gcd_obj:
            issue_lst = gcd_obj.get_issues(gcd_series_id, issue_number)
            if not issue_lst:
                return None
            issue_count = len(issue_lst)
            idx = self._select_gcd_issue(issue_lst) if issue_count > 1 else 0
            if idx is not None:
                gcd_issue = issue_lst[idx]
                return GCD_Issue(
                    gcd_id=gcd_issue[0],  # type: ignore
                    number=gcd_issue[1],  # type: ignore
                    price=gcd_issue[2],  # type: ignore
                    barcode=gcd_issue[3],  # type: ignore
                    pages=gcd_issue[4],  # type: ignore
                    rating=gcd_issue[5],  # type: ignore
                    publisher=gcd_issue[6],  # type: ignore
                )
            else:
                return None

    @staticmethod
    def _get_gcd_stories(gcd_issue_id: int) -> List[str]:
        with DB() as gcd_obj:
            stories_list = gcd_obj.get_stories(gcd_issue_id)
            if not stories_list:
                return []

            if len(stories_list) == 1 and not stories_list[0][0]:
                return []

            stories = []
            for i in stories_list:
                story = str(i[0]) if i[0] else "[Untitled]"
                stories.append(fix_story_chapters(story))

            return stories

    # Metron
    @staticmethod
    def _create_series_choices(results) -> List[questionary.Choice]:
        choices = []
        for s in results:
            choice = questionary.Choice(
                title=f"{s.name} ({s.start_year}) - {s.issue_count} issues", value=s
            )
            choices.append(choice)
        choices.append(questionary.Choice(title="Skip", value=""))
        return choices

    @staticmethod
    def _select_metron_series(series_lst: SeriesList, series: str):
        choices: List[questionary.Choice] = []
        for i in series_lst:
            choice = questionary.Choice(title=i.display_name, value=i.id)
            choices.append(choice)
        choices.append(questionary.Choice(title="None", value=""))
        return questionary.select(
            f"What series on Metron should be used for '{series}'?",
            choices=choices,
        ).ask()

    def _what_series(self) -> int | None:
        series = questionary.text("What Metron series do you want to update?").ask()
        if series_lst := self.metron.series_list({"name": series}):
            return self._select_metron_series(series_lst, series)

    ##########
    # Update #
    ##########
    def _update_issue(self, gcd_series_id, issue) -> bool:
        gcd = self._get_gcd_issue(gcd_series_id, issue.number)
        if gcd is None:
            questionary.print(
                f"'{issue.series.name} #{issue.number}' not found on GCD. Skipping..."
            )
            return False

        data: dict[str, Any] = {}
        updated = False
        msg = "Changed:"
        if not self.reprint_only:
            gcd_stories = self._get_gcd_stories(gcd.id) if gcd is not None else None
            if gcd_stories is not None and issue.story_titles != gcd_stories:
                data["name"] = gcd_stories
                msg += f"\n\tStories: {gcd_stories}"
                updated = True

            if gcd.barcode is not None and issue.upc != gcd.barcode:
                data["upc"] = gcd.barcode
                msg += f"\n\tBarcode: {gcd.barcode}"
                updated = True

            if gcd.price is not None and issue.price != gcd.price:
                data["price"] = gcd.price
                msg += f"\n\tPrice: {gcd.price}"
                updated = True

            if gcd.pages is not None and issue.page_count != gcd.pages:
                data["page"] = gcd.pages
                msg += f"\n\tPages: {gcd.pages}"
                updated = True

        gcd_reprints_lst = self.get_gcd_reprints(gcd.id) if gcd is not None else None
        reprints_lst = (
            self.get_metron_reprint(gcd_reprints_lst, issue)
            if gcd_reprints_lst and gcd_reprints_lst is not None
            else []
        )

        if reprints_lst:
            if issue.reprints:
                original_reprints_lst = self._create_metron_reprint_lst(issue.reprints)
                if original_reprints_lst != reprints_lst:
                    data["reprints"] = reprints_lst
                    msg += f"\n\tReprints: {reprints_lst}"
                    updated = True
            else:
                data["reprints"] = reprints_lst
                msg += f"\n\tReprints: {reprints_lst}"
                updated = True

        if not updated:
            questionary.print(
                f"Nothing to update for '{issue.series.name} #{issue.number}'", style=Styles.SUCCESS
            )
            return False

        try:
            self.barda.patch_issue(issue.id, data)
        except ApiError:
            questionary.print(
                f"Failed to update '{issue.series.name} #{issue.number}'. Data: {data}",
                style=Styles.WARNING,
            )
            return False

        questionary.print(msg, style=Styles.SUCCESS)

        return True

    def run(self) -> None:
        gcd_series_id = self._get_gcd_series_id()
        metron_series_id = self._what_series()
        if not metron_series_id or metron_series_id is None:
            questionary.print("No series found. Exiting...", style=Styles.WARNING)
            exit()

        issue_lst = self.metron.issues_list({"series_id": metron_series_id})
        self.reprint_only = questionary.confirm("Do you want to only update the reprints?").ask()
        for i in issue_lst:
            m_issue = self.metron.issue(i.id)
            if self._update_issue(gcd_series_id, m_issue):
                questionary.print(f"Updated {i.issue_name}", style=Styles.SUCCESS)
