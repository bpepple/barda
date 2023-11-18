from logging import getLogger
from typing import Any, List

import questionary
from mokkari import api
from mokkari.issue import IssueSchema, IssuesList
from mokkari.reprint import ReprintSchema
from mokkari.series import SeriesList
from mokkari.session import Session

from barda.exceptions import ApiError
from barda.gcd.db import DB, GcdReprintIssue
from barda.gcd.gcd_issue import GCD_Issue
from barda.post_data import PostData
from barda.resource_keys import ResourceKeys, Resources
from barda.settings import BardaSettings
from barda.styles import Styles
from barda.utils import fix_story_chapters

LOGGER = getLogger(__name__)


class GcdUpdate:
    def __init__(self, config: BardaSettings) -> None:
        self.metron: Session = api(config.metron_user, config.metron_password)
        self.barda = PostData(config.metron_user, config.metron_password)
        self.conversions = ResourceKeys(str(config.conversions))
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

    ############
    # Reprints #
    ############
    @staticmethod
    def get_gcd_reprints(gcd_issue_id: int) -> list[GcdReprintIssue]:
        result_lst = []
        with DB() as gcd_obj:
            story_ids = gcd_obj.get_story_ids(gcd_issue_id)
            LOGGER.debug(f"Story IDS: {story_ids}")
            for story_id in story_ids:
                reprints_lst = gcd_obj.get_reprints_ids(story_id[0])
                LOGGER.debug(f"Story ID: {story_id} | Reprint IDS: {reprints_lst}")
                if not reprints_lst:
                    continue
                for item in reprints_lst:
                    gcd_reprint = gcd_obj.get_reprint_issue(item[0])
                    LOGGER.debug(f"Issue: {gcd_reprint}")
                    if gcd_reprint.series is None and gcd_reprint.number is None:
                        continue
                    if gcd_reprint not in result_lst:
                        result_lst.append(gcd_reprint)
        return result_lst

    @staticmethod
    def _create_issue_choices(item: IssuesList) -> List[questionary.Choice] | None:
        if not item:
            return None
        choices: List[questionary.Choice] = []
        for i in item:
            choice = questionary.Choice(title=i.issue_name, value=i.id)
            choices.append(choice)
        choices.append(questionary.Choice(title="None", value=""))
        return choices

    @staticmethod
    def _create_metron_reprint_lst(reprint_lst: list[ReprintSchema]) -> list[int]:
        new_lst = []
        for i in reprint_lst:
            new_lst.append(i.id)
        return new_lst

    def get_metron_reprint(
        self, gcd_reprints_lst: list[GcdReprintIssue], issue: IssueSchema
    ) -> list[int]:
        metron_reprints_lst = (
            self._create_metron_reprint_lst(issue.reprints) if issue.reprints else []
        )

        for item in gcd_reprints_lst:
            questionary.print(
                f"Searching for reprint issue: '{item}'{' (Collection)' if item.collection else ''}",
            )
            # Let's see if the reprint id is in the cache.
            metron_issue_id = self.conversions.get_gcd(Resources.Issue.value, item.id_)
            if metron_issue_id is not None:
                questionary.print(f"Found {item} in cache.", style=Styles.WARNING)
                if metron_issue_id not in metron_reprints_lst:
                    questionary.print(f"Adding '{item}' to reprints list", style=Styles.SUCCESS)
                    metron_reprints_lst.append(metron_issue_id)
                else:
                    questionary.print(
                        f"'{item}' is already listed as a reprint", style=Styles.WARNING
                    )
                continue

            if issues_lst := self.metron.issues_list(
                {"series_name": item.series, "number": item.number}
            ):
                # If only one result, let's check if it's match.
                single_issue = issues_lst[0]
                if len(issues_lst) == 1 and str(item).lower() == single_issue.issue_name.lower():
                    # Let's check that they are both collections.
                    if item.collection and "tpb" not in single_issue.issue_name.lower():
                        questionary.print(
                            f"'{item}' is a collection and '{single_issue.issue_name}' is not. Skipping..."
                        )
                        continue
                    # Let's add it to the conversion cache
                    self.conversions.store_gcd(Resources.Issue.value, item.id_, single_issue.id)
                    questionary.print(
                        f"Added '{item}' to {Resources.Issue.name} to cache. "
                        f"GCD: {item.id_} | Metron: {single_issue.id}",
                        style=Styles.SUCCESS,
                    )
                    # Add the issue if it's not already in the reprints list.
                    if single_issue.id not in metron_reprints_lst:
                        metron_reprints_lst.append(single_issue.id)
                        questionary.print(f"Found match for '{item}'", style=Styles.SUCCESS)
                    else:
                        questionary.print(
                            f"'{item}' is already listed as a reprint.", style=Styles.WARNING
                        )
                    continue

                # Let's see if we can find an exact match.
                issue_match = next(
                    (i for i in issues_lst if i.issue_name.lower() == str(item).lower()),
                    None,
                )

                if issue_match is not None:
                    # Let's add it to the conversion cache.
                    self.conversions.store_gcd(Resources.Issue.value, item.id_, issue_match.id)
                    questionary.print(
                        f"Added '{item}' to {Resources.Issue.name} to cache. "
                        f"GCD: {item.id_} | Metron: {issue_match.id}",
                        style=Styles.SUCCESS,
                    )
                    if issue_match.id not in metron_reprints_lst:
                        metron_reprints_lst.append(issue_match.id)
                        questionary.print(f"Found match for '{item}'", style=Styles.SUCCESS)
                    else:
                        questionary.print(
                            f"'{item}' is already listed as a reprint.", style=Styles.WARNING
                        )
                    continue

                # Ok, no exact match, let's ask the user.
                choices = self._create_issue_choices(issues_lst)
                if choices is None:
                    questionary.print(f"Nothing issues found for '{item}'", style=Styles.WARNING)
                    continue
                if result := questionary.select(
                    "Which issue should be added as a reprint?", choices=choices
                ).ask():
                    if result not in metron_reprints_lst:
                        metron_reprints_lst.append(result)
                        questionary.print(
                            f"Added '{item}' to {Resources.Issue.name} to cache. "
                            f"GCD: {item.id_} | Metron: {single_issue.id}",
                            style=Styles.SUCCESS,
                        )
        return metron_reprints_lst

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
