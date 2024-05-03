from enum import Enum, unique
from logging import getLogger
from tempfile import TemporaryDirectory
from typing import List

import questionary
from mokkari import api
from mokkari.schemas.base import BaseResource
from mokkari.schemas.generic import GenericItem
from mokkari.schemas.issue import BaseIssue, Issue
from mokkari.schemas.reprint import Reprint
from mokkari.session import Session

from barda import __version__
from barda.gcd.db import DB, GcdReprintIssue
from barda.post_data import PostData
from barda.resource_keys import ResourceKeys, Resources
from barda.settings import BardaSettings
from barda.styles import Styles
from barda.validators import YearValidator

LOGGER = getLogger(__name__)


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
        self.metron: Session = api(
            config.metron_user, config.metron_password, user_agent=f"Barda/{__version__}"
        )
        self.series_type: GenericItem | None = None
        self.universes: list[BaseResource] = []
        self.conversions = ResourceKeys(str(config.conversions))
        # List of GCD issues not on Metron.
        self.missing_issue: set[int] = set()

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

    #############
    # Universes #
    #############
    def _choose_universes(self) -> list[int]:
        if not self.universes:
            self.universes = self.metron.universes_list()
        choices = []
        for u in self.universes:
            choice = questionary.Choice(title=u.name, value=u.id)
            choices.append(choice)
        return questionary.checkbox("What universes should be added?", choices=choices).ask()

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
        pub_lst = self.metron.publishers_list()
        choices = []
        for p in pub_lst:
            choice = questionary.Choice(title=p.name, value=p.id)
            choices.append(choice)
        # TODO: Provide option to add a Publisher
        return int(
            questionary.select("Which publisher is this series from?", choices=choices).ask()
        )

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
    def _create_issue_choices(item: list[BaseIssue]) -> List[questionary.Choice] | None:
        if not item:
            return None
        choices: List[questionary.Choice] = []
        for i in item:
            choice = questionary.Choice(title=i.issue_name, value=i.id)
            choices.append(choice)
        choices.append(questionary.Choice(title="None", value=""))
        return choices

    @staticmethod
    def _create_metron_reprint_lst(reprint_lst: list[Reprint]) -> list[int]:
        new_lst = []
        for i in reprint_lst:
            new_lst.append(i.id)
        return new_lst

    @staticmethod
    def _check_reprints_list(
        item: GcdReprintIssue, issue_id: int, metron_reprints_lst: list[int]
    ) -> list[int]:
        if issue_id in metron_reprints_lst:
            questionary.print(f"'{item}' is already listed as a reprint.", style=Styles.WARNING)
        else:
            metron_reprints_lst.append(issue_id)
            questionary.print(f"Found match for '{item}'", style=Styles.SUCCESS)
        return metron_reprints_lst

    def get_metron_reprint(
        self, gcd_reprints_lst: list[GcdReprintIssue], issue: Issue | None = None
    ) -> list[int]:
        metron_reprints_lst = []
        if issue is not None:
            metron_reprints_lst = (
                self._create_metron_reprint_lst(issue.reprints) if issue.reprints else []
            )

        for item in gcd_reprints_lst:
            questionary.print(
                f"Searching for reprint issue: '{item}'{' (Collection)' if item.collection else ''}",
            )
            # Let's check to see if we've already searched for it.
            if self.missing_issue and item.id_ in self.missing_issue:
                questionary.print(
                    f"Already searched for '{item}'. Skipping...", style=Styles.WARNING
                )
                continue
            # Let's see if the reprint id is in the cache.
            metron_issue_id = self.conversions.get_gcd(Resources.Issue.value, item.id_)
            if metron_issue_id is not None:
                questionary.print(f"Found {item} in cache.", style=Styles.WARNING)
                metron_reprints_lst = self._check_reprints_list(
                    item, metron_issue_id, metron_reprints_lst
                )
                continue

            if issues_lst := self.metron.issues_list(
                {"series_name": item.series, "number": item.number}
            ):
                # If only one result, let's check if it's match.
                single_issue = issues_lst[0]
                if len(issues_lst) == 1 and str(item).lower() == single_issue.issue_name.lower():
                    # Let's check that they are both collections.
                    if item.collection is True and "tpb" not in single_issue.issue_name.lower():
                        questionary.print(
                            f"'{item}' is a collection and '{single_issue.issue_name}' is not. Skipping...",
                            style=Styles.WARNING,
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
                    metron_reprints_lst = self._check_reprints_list(
                        item, single_issue.id, metron_reprints_lst
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
                    metron_reprints_lst = self._check_reprints_list(
                        item, issue_match.id, metron_reprints_lst
                    )
                    continue

                # Ok, no exact match, let's ask the user.
                choices = self._create_issue_choices(issues_lst)
                if choices is None:
                    self.missing_issue.add(item.id_)
                    questionary.print(f"No issues found for '{item}'", style=Styles.WARNING)
                    continue

                if result := questionary.select(
                    f"Which issue should be added as a reprint for '{item}'?", choices=choices
                ).ask():
                    self.conversions.store_gcd(Resources.Issue.value, item.id_, result)
                    questionary.print(
                        f"Added '{item}' to {Resources.Issue.name} to cache. "
                        f"GCD: {item.id_} | Metron: {result}",
                        style=Styles.SUCCESS,
                    )
                    if result in metron_reprints_lst:
                        # Result is already in reprints list, let's go on to the next item
                        questionary.print(
                            f"'{item}' is already listed as a reprint.", style=Styles.WARNING
                        )
                        continue
                    metron_reprints_lst.append(result)
                else:
                    # If user selected None, let's not search for it again.
                    self.missing_issue.add(item.id_)
                    continue
            else:
                # Nothing found let's not search for the item again.
                self.missing_issue.add(item.id_)

        return metron_reprints_lst

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
            if series_type_id in {11, 2, 12}  # Limited, Cancelled, and Digital Chapters
            else None
        )

    @staticmethod
    def _determine_series_collection_title() -> bool:
        return questionary.confirm(
            "Should this series allow the user of the collection title field?", default=False
        ).ask()
