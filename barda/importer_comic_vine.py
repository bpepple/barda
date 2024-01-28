import datetime
import operator
import uuid
from enum import Enum, auto, unique
from logging import getLogger
from pathlib import Path
from typing import Any, List

import questionary
import requests
from mokkari.schemas.generic import GenericItem
from mokkari.schemas.issue import Issue as MetronIssue
from mokkari.schemas.series import BaseSeries
from simyan.comicvine import Comicvine as CV
from simyan.comicvine import Issue as CV_Issue
from simyan.comicvine import VolumeEntry
from simyan.exceptions import ServiceError
from simyan.schemas.generic_entries import CreatorEntry, GenericEntry
from simyan.sqlite_cache import SQLiteCache

from barda.exceptions import ApiError
from barda.gcd.db import DB
from barda.gcd.gcd_issue import GCD_Issue, Rating
from barda.ignore_resources import Ignore_Characters, Ignore_Creators, Ignore_Teams
from barda.image import CVImage
from barda.importer_base import BaseImporter
from barda.resource_keys import Resources
from barda.settings import BardaSettings
from barda.styles import Styles
from barda.utils import (
    clean_desc,
    clean_search_series_title,
    cleanup_html,
    fix_story_chapters,
    remove_overview_text,
)
from barda.validators import DateValidator, NumberValidator

LOGGER = getLogger(__name__)


@unique
class ImageType(Enum):
    Cover = auto()
    Creator = auto()
    Resource = auto()


@unique
class CVCreator(Enum):
    Alan_Fine = 56587
    Dan_Buckley = 41596
    Joe_Quesada = 1537
    CB_Cebulski = 43193
    Axel_Alonso = 23115
    Jim_Shooter = 40450
    Mike_Richardson = 45055


BAD_PUBLISHERS = [
    "Editoriale Corno",
    "Editions Héritage",
    "Editorial Muchnik",
    "Panini España",
    "Del Rey",
    "Cosplay Comics",
    "Eternity",
    "Takeshobo",
    "self published",
    "Scholastic Book Services",
    "Victory Productions",
    "Blackthorne",
    "Carlsen Verlag",
    "Hakusensha",
    "Irodori Comics",
    "Panini Nederland",
    "Panini España",
    "Panini Verlag",
    "Panini France",
    "Panini Comics",
    "Thorpe & Porter",
    "Brown Watson",
    "Titan Books",
    "Egmont Publishing (UK)",
    "IPC Magazines Ltd.",
    "Titan Comics",
    "Atlas Publishing",
    "Federal",
    "Stafford Pemberton",
    "Atlas Publications Pty. Ltd.",
    "World Distributors",
    "Urban Comics",
    "Ediciones Zinco",
    "ECC Ediciones",
    "Murray Comics",
    "Planeta DeAgostini",
]


class ComicVineImporter(BaseImporter):
    def __init__(self, config: BardaSettings) -> None:
        super(ComicVineImporter, self).__init__(config)
        cv_cache = SQLiteCache(config.cv_cache, 1) if config.cv_cache else None
        self.cv = CV(api_key=config.cv_api_key, cache=cv_cache)  # type: ignore
        self.add_characters = False
        self.add_universes = False
        self.role_list: list[GenericItem] | None = None
        self.ignore_characters: List[int] = []
        self.ignore_teams: List[int] = []
        self.ignore_creators: List[int] = []

    @staticmethod
    def fix_cover_date(orig_date: datetime.date) -> datetime.date:
        if orig_date.day != 1:
            return datetime.date(orig_date.year, orig_date.month, 1)
        return orig_date

    @staticmethod
    def _ignore_resource(resource, cv_id: int) -> bool:
        return any(cv_id == i.value for i in resource)

    def _get_image(self, url: str, img_type: ImageType) -> str:
        LOGGER.debug("Entering get_image()...")
        try:
            receive = requests.get(url)
        except requests.exceptions.ConnectionError:
            LOGGER.warning(f"ConnectionError: {url}")
            return ""
        cv = Path(url)
        LOGGER.debug(f"Comic Vine image: {cv.name}")
        if not cv.suffix:
            LOGGER.debug(f"{cv.name} is missing an extension. Let's not add it to Metron.")
            return ""
        if cv.name in {"6373148-blank.png", "img_broken.png"}:
            return ""
        new_fn = f"{uuid.uuid4().hex}{cv.suffix}"
        img_file = Path(self.image_dir.name) / new_fn
        img_file.write_bytes(receive.content)
        LOGGER.debug(f"Image saved as '{img_file.name}'.")
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

        LOGGER.debug("Exiting get_image()...")
        return str(img_file)

    @staticmethod
    def _fix_title_data(title: str | None) -> List[str]:
        LOGGER.debug("Entering fix_title_data()...")
        if title is None or title == "":
            LOGGER.debug(f"original: {title}; Returning []")
            return []

        # Strip any trailing semicolon and change backslash to semicolon,
        # and then split the string by any non-ending semicolon.
        result = title.rstrip(";")
        result = result.replace(" / ", "; ")
        result = result.split("; ")

        for index, txt in enumerate(result):
            # Remove quotation marks from title
            result[index] = txt.strip('"')
            # Capitalize title correctly
            result[index] = fix_story_chapters(result[index])

        LOGGER.debug(f"title: {result}")
        LOGGER.debug("Exiting fix_title_data()...")
        return result

    def _confirm_resource_choice(
        self, resource: Resources, cv_entry: GenericEntry, choices: List[questionary.Choice]
    ) -> int | None:
        if metron_id := questionary.select(
            f"What {resource.name} should be added for '{cv_entry.name} ({cv_entry.id})'?",
            choices=choices,
        ).ask():
            self.conversions.store_cv(resource.value, cv_entry.id, metron_id)
            questionary.print(
                f"Added '{cv_entry.name}' to {resource.name} conversions. "
                f"CV: {cv_entry.id}, Metron: {metron_id}",
                style=Styles.SUCCESS,
            )
        return metron_id

    @staticmethod
    def _select_metron_series(series_lst: list[BaseSeries], series: VolumeEntry):
        choices: List[questionary.Choice] = []
        for i in series_lst:
            choice = questionary.Choice(
                title=f"{i.display_name} - {i.issue_count} issues", value=i.id
            )
            choices.append(choice)
        choices.append(questionary.Choice(title="None", value=""))
        return questionary.select(
            f"What series on Metron should be used for '{series.name} ({series.start_year})'?",
            choices=choices,
        ).ask()

    def _check_metron_for_series(self, series: VolumeEntry) -> str | None:
        if series_lst := self.metron.series_list(
            {"name": series.name.lower().replace("&", "").lstrip("the ")}
        ):
            if series_result := self._select_metron_series(series_lst, series):
                return series_result

        if not questionary.confirm(
            f"No series for '{series.name} ({series.start_year})' on Metron. "
            "Do you want to do another search?"
        ).ask():
            return None

        series_query = questionary.text("What name should we use to search for the series?").ask()
        return (
            self._select_metron_series(series_lst, series)
            if (series_lst := self.metron.series_list({"name": series_query}))
            else None
        )

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
            if idx is None:
                return None
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

    @staticmethod
    def _get_gcd_stories(gcd_issue_id):
        LOGGER.debug("Entering get_gcd_stories()...")
        with DB() as gcd_obj:
            stories_list = gcd_obj.get_stories(gcd_issue_id)
            LOGGER.debug(f"gcd_stories: {stories_list}")
            if not stories_list:
                LOGGER.debug("Returning 'not': []")
                return []

            if len(stories_list) == 1 and not stories_list[0][0]:
                LOGGER.debug("Returning 'len=1': []")
                return []

            stories = []
            for i in stories_list:
                story = str(i[0]) if i[0] else "[Untitled]"
                stories.append(fix_story_chapters(story))

            LOGGER.debug(f"Stories: {stories}")
            LOGGER.debug("Exiting get_gcd_stories()...")
            return stories

    ##################
    # Handle Credits #
    ##################
    @staticmethod
    def _get_joe_quesada_role(cover_date: datetime.date) -> List[str]:
        if cover_date >= datetime.date(2011, 4, 1):
            return ["chief creative officer"]
        return ["editor in chief"]

    @staticmethod
    def _get_dan_buckley_role(cover_date: datetime.date) -> List[str]:
        if cover_date >= datetime.date(2017, 5, 1):
            return ["president"]
        return ["publisher"]

    @staticmethod
    def _get_axel_alonso_role(cover_date: datetime.date) -> List[str]:
        if datetime.date(2011, 4, 1) <= cover_date < datetime.date(2018, 3, 1):
            return ["editor in chief"]
        return []

    @staticmethod
    def _get_cb_cebulski_role(cover_date: datetime.date) -> List[str]:
        return ["editor in chief"] if cover_date >= datetime.date(2018, 3, 1) else []

    @staticmethod
    def _get_jim_shooter_role(cover_date: datetime.date) -> List[str]:
        if datetime.date(1978, 3, 1) <= cover_date < datetime.date(1987, 10, 1):
            return ["editor in chief"]
        return []

    def _handle_special_creators(self, creator: int, cover_date: datetime.date) -> List[str]:
        match creator:
            case CVCreator.Alan_Fine.value:
                return ["executive producer"]
            case CVCreator.Dan_Buckley.value:
                return self._get_dan_buckley_role(cover_date)
            case CVCreator.Joe_Quesada.value:
                return self._get_joe_quesada_role(cover_date)
            case CVCreator.CB_Cebulski.value:
                return self._get_cb_cebulski_role(cover_date)
            case CVCreator.Axel_Alonso.value:
                return self._get_axel_alonso_role(cover_date)
            case CVCreator.Jim_Shooter.value:
                return self._get_jim_shooter_role(cover_date)
            case CVCreator.Mike_Richardson.value:
                return ["publisher"]
            case _:
                return []

    @staticmethod
    def _fix_role_list(roles: List[str]) -> List[str]:
        role_list = []

        # Handle assistant editors
        if "editor" in roles and "assistant" in roles:
            role_list.append("assistant editor")
            return role_list

        for role in roles:
            if role.lower() == "penciler":
                role = "penciller"
            role_list.append(role)
        return role_list

    @staticmethod
    def _ask_for_role(creator: CreatorEntry, metron_roles: list[GenericItem]) -> list[int]:
        choices = []
        for i in metron_roles:
            choice = questionary.Choice(title=i.name, value=i.id)  # type: ignore
            choices.append(choice)
        return questionary.checkbox(
            f"No role found for {creator.name}. What should it be?", choices=choices
        ).ask()

    def _create_role_list(self, creator: CreatorEntry, cover_date: datetime.date) -> list[int]:
        role_lst = self._handle_special_creators(creator.id, cover_date)
        if len(role_lst) == 0:
            role_lst = creator.roles.split(", ")
            role_lst = self._fix_role_list(role_lst)

        if self.role_list is None:
            self.role_list = self.metron.role_list()
        roles = []
        for i in role_lst:
            roles.extend(m_role.id for m_role in self.role_list if i.lower() == m_role.name.lower())

        if not roles:
            roles = self._ask_for_role(creator, self.role_list)

        return roles

    def _create_credits_list(
        self, issue_id: int, cover_date: datetime.date, credits: List[CreatorEntry]
    ) -> List:
        LOGGER.debug("Entering create_credits_list()...")
        credits_lst = []
        for i in credits:
            if self._ignore_resource(Ignore_Creators, i.id):
                continue
            if self.ignore_creators and i.id in self.ignore_creators:
                continue
            person = GenericEntry(id=i.id, name=i.name, api_detail_url="")
            creator_id = self.conversions.get_cv(Resources.Creator.value, i.id)
            if creator_id is None:
                creator_id = self._search_for_creator(person)
            if creator_id is None:
                continue
            role_lst = self._create_role_list(i, cover_date)
            data = {"issue": issue_id, "creator": creator_id, "role": role_lst}
            credits_lst.append(data)

        LOGGER.debug(f"Credit List: {credits_lst}")
        LOGGER.debug("Exiting create_credits_list()...")
        return credits_lst

    ###################
    # Handle Creators #
    ###################
    def _create_creator(self, cv_id: int) -> int | None:
        LOGGER.debug("Entering create_creator()...")
        try:
            creator = self.cv.get_creator(cv_id)
        except ServiceError:
            questionary.print(
                f"Failed to retrieve information from Comic Vine for Creator ID: {cv_id}.",
                style=Styles.ERROR,
            )
            return None

        questionary.print(f"Let's create creator '{creator.name}' on Metron", style=Styles.TITLE)
        name = (
            creator.name
            if questionary.confirm(f"Is '{creator.name}' the correct name?").ask()
            else questionary.text("What should be the creator's name be?").ask()
        )
        desc = questionary.text("What should be the description for this creator?").ask()
        LOGGER.debug(f"Retrieving image for '{name}'.")
        img = self._get_image(creator.image.original_url, ImageType.Creator)
        LOGGER.debug(f"{name} image: {img}")
        data = {
            "name": name,
            "desc": desc,
            "image": img,
            "alias": [],
            "cv_id": creator.id,
            "birth": creator.date_of_birth,
            "death": creator.date_of_death,
        }

        try:
            resp = self.barda.post_creator(data)
        except ApiError:
            questionary.print(f"Failed to create creator: '{name}'.", style=Styles.ERROR)
            return None

        if resp is None:
            return None

        self.conversions.store_cv(Resources.Creator.value, creator.id, resp["id"])
        questionary.print(
            f"Added '{name}' to {Resources.Creator.name} conversions. CV: "
            f"{creator.id}, Metron: {resp['id']}",
            style=Styles.SUCCESS,
        )
        LOGGER.debug("Exiting create_creator()...")
        return resp["id"]

    def _choose_creator(self, creator: GenericEntry) -> int | None:
        if not creator.name:
            return None

        questionary.print(
            f"Let's do a creator search on Metron for '{creator.name}'", style=Styles.TITLE
        )
        c_list = self.metron.creators_list(params={"name": creator.name})
        choices = self._create_choices(c_list)
        if choices is None:
            questionary.print(f"Nothing found for '{creator.name}'", style=Styles.WARNING)
        elif metron_id := self._confirm_resource_choice(Resources.Creator, creator, choices):
            return metron_id

        if questionary.confirm(
            f"Do want to use another name to search for '{creator.name}'?"
        ).ask():
            txt = questionary.text(f"What name do you want to search for '{creator.name}'?").ask()
            lst = self.metron.creators_list(params={"name": txt})
            new_choices = self._create_choices(lst)
            if new_choices is None:
                questionary.print(f"Nothing found for '{creator.name}'", style=Styles.WARNING)
            elif metron_id := self._confirm_resource_choice(
                Resources.Creator, creator, new_choices
            ):
                return metron_id

        return None

    def _search_for_creator(self, creator: GenericEntry) -> int | None:
        metron_id = self._choose_creator(creator) if creator.name else None
        if metron_id is not None:
            return metron_id

        if questionary.confirm(
            f"Do you want to create a creator for {creator.name} on Metron?"
        ).ask():
            return self._create_creator(creator.id)
        if questionary.confirm(
            "Do you want to ignore this creator during the rest of this session?"
        ).ask():
            self.ignore_creators.append(creator.id)
        return None

    def _create_creator_list(self, creators: List[GenericEntry]) -> List[int]:
        creator_lst = []
        for creator in creators:
            if self.ignore_creators and creator.id in self.ignore_creators:
                continue
            metron_id = self.conversions.get_cv(Resources.Creator.value, creator.id)
            if metron_id is None:
                metron_id = self._search_for_creator(creator)
            if metron_id is None:
                continue
            creator_lst.append(metron_id)
        return creator_lst

    ###############
    # Handle Arcs #
    ###############
    def _create_arc(self, cv_id: int) -> int | None:
        try:
            story = self.cv.get_story_arc(cv_id)
        except ServiceError:
            questionary.print(
                f"Failed to retrieve information from Comic Vine for Story Arc ID: {cv_id}.",
                style=Styles.ERROR,
            )
            return None
        questionary.print(f"Let's create story arc '{story.name}' on Metron", style=Styles.TITLE)
        name = (
            story.name
            if questionary.confirm(f"Is '{story.name}' the correct name?").ask()
            else questionary.text("What should be the story arc name be?").ask()
        )
        desc = questionary.text("What should be the description for this story arc?").ask()
        img = self._get_image(story.image.original_url, ImageType.Resource)
        data = {"name": name, "desc": desc, "image": img, "cv_id": story.id}

        try:
            resp = self.barda.post_arc(data)
        except ApiError:
            questionary.print(f"Fail to create story arc for '{name}'.", style=Styles.ERROR)
            return None

        if resp is None:
            return None

        self.conversions.store_cv(Resources.Arc.value, story.id, resp["id"])
        questionary.print(f"Add '{name}' to {Resources.Arc.name} conversions", style=Styles.SUCCESS)
        return resp["id"]

    def _choose_arc(self, arc: GenericEntry) -> int | None:
        if not arc.name:
            return None

        questionary.print(
            f"Let's do a story arc search on Metron for '{arc.name}'", style=Styles.TITLE
        )
        arc_lst = self.metron.arcs_list(params={"name": arc.name})
        choices = self._create_choices(arc_lst)
        if choices is None:
            questionary.print(f"Nothing found for '{arc.name}'", style=Styles.WARNING)
        elif metron_id := self._confirm_resource_choice(Resources.Arc, arc, choices):
            return metron_id

        if questionary.confirm(f"Do want to use another name to search for '{arc.name}'?").ask():
            txt = questionary.text(f"What name do you want to search for '{arc.name}'?").ask()
            lst = self.metron.arcs_list(params={"name": txt})
            new_choices = self._create_choices(lst)
            if new_choices is None:
                questionary.print(f"Nothing found for '{txt}'", style=Styles.WARNING)
            elif metron_id := self._confirm_resource_choice(Resources.Arc, arc, new_choices):
                return metron_id

        return None

    def _search_for_arc(self, arc: GenericEntry) -> int | None:
        metron_id = self._choose_arc(arc) if arc.name else None
        if metron_id is not None:
            return metron_id

        if questionary.confirm(f"Do you want to create a story for {arc.name} on Metron?").ask():
            return self._create_arc(arc.id)
        return None

    def _create_arc_list(self, arcs: List[GenericEntry]) -> List[int]:
        arc_lst = []
        for arc in arcs:
            metron_id = self.conversions.get_cv(Resources.Arc.value, arc.id)
            if metron_id is None:
                metron_id = self._search_for_arc(arc)
            if metron_id is None:
                continue
            arc_lst.append(metron_id)
        return arc_lst

    ################
    # Handle Teams #
    ################
    def _create_team(self, cv_id: int) -> int | None:
        try:
            team = self.cv.get_team(cv_id)
        except ServiceError:
            questionary.print(
                f"Failed to retrieve information from Comic Vine for Team ID: {cv_id}.",
                style=Styles.ERROR,
            )
            return None

        questionary.print(f"Let's create team '{team.name}' on Metron", style=Styles.TITLE)
        name = (
            team.name
            if questionary.confirm(f"Is '{team.name}' the correct name?").ask()
            else questionary.text("What should the team name be?").ask()
        )
        desc = questionary.text("What should be the description for this team?").ask()
        img = self._get_image(team.image.original_url, ImageType.Resource)
        universe_lst = self._choose_universes() if self.add_universes else []
        data = {
            "name": name,
            "desc": desc,
            "image": img,
            "creators": [],
            "universes": universe_lst,
            "cv_id": team.id,
        }

        try:
            resp = self.barda.post_team(data)
        except ApiError:
            questionary.print(f"Failed to create team for '{name}'.", style=Styles.ERROR)
            return None

        if resp is None:
            return None

        self.conversions.store_cv(Resources.Team.value, team.id, resp["id"])
        questionary.print(
            f"Added '{name}' to {Resources.Team.name}  conversions", style=Styles.SUCCESS
        )
        return resp["id"]

    def _choose_team(self, team: GenericEntry) -> int | None:
        if not team.name:
            return None

        questionary.print(f"Let's do a team search on Metron for '{team.name}'", style=Styles.TITLE)
        team_lst = self.metron.teams_list(params={"name": team.name})
        choices = self._create_choices(team_lst)
        if choices is None:
            questionary.print(f"Nothing found for '{team.name}'", style=Styles.WARNING)
        elif metron_id := self._confirm_resource_choice(Resources.Team, team, choices):
            return metron_id

        if questionary.confirm(f"Do want to use another name to search for '{team.name}'?").ask():
            txt = questionary.text(f"What name do you want to search for '{team.name}'?").ask()
            lst = self.metron.teams_list(params={"name": txt})
            new_choices = self._create_choices(lst)
            if new_choices is None:
                questionary.print(f"Nothing found for '{txt}'", style=Styles.WARNING)
            elif metron_id := self._confirm_resource_choice(Resources.Team, team, new_choices):
                return metron_id

        return None

    def _search_for_team(self, team: GenericEntry) -> int | None:
        metron_id = self._choose_team(team) if team.name else None
        if metron_id is not None:
            return metron_id

        if questionary.confirm(f"Do you want to create a team for '{team.name}' on Metron?").ask():
            return self._create_team(team.id)
        if questionary.confirm(
            "Do you want to ignore this team during the rest of this session?"
        ).ask():
            self.ignore_teams.append(team.id)
        return None

    def _create_team_list(self, teams: List[GenericEntry]) -> List[int]:
        team_lst = []
        for team in teams:
            if self._ignore_resource(Ignore_Teams, team.id):
                continue
            if self.ignore_teams and team.id in self.ignore_teams:
                continue
            metron_id = self.conversions.get_cv(Resources.Team.value, team.id)
            if metron_id is None:
                metron_id = self._search_for_team(team)
            if metron_id is None:
                continue
            team_lst.append(metron_id)
        return team_lst

    #####################
    # Handle Characters #
    #####################
    def _create_character(self, cv_id: int) -> int | None:
        try:
            character = self.cv.get_character(cv_id)
        except ServiceError:
            questionary.print(
                f"Failed to retrieve information from Comic Vine for Character ID: {cv_id}.",
                style=Styles.ERROR,
            )
            return None

        questionary.print(
            f"Let's create character '{character.name}' on Metron", style=Styles.TITLE
        )
        name = (
            character.name
            if questionary.confirm(f"Is '{character.name}' the correct name?").ask()
            else questionary.text("What should the characters name be?").ask()
        )

        desc = questionary.text("What description do you want to have for this character?").ask()
        img = self._get_image(character.image.original_url, ImageType.Resource)
        teams_lst = self._create_team_list(character.teams)
        creators_lst = self._create_creator_list(character.creators)
        universe_lst = self._choose_universes() if self.add_universes else []
        data = {
            "name": name,
            "alias": [],
            "desc": desc,
            "image": img,
            "teams": teams_lst,
            "creators": creators_lst,
            "universes": universe_lst,
            "cv_id": character.id,
        }

        try:
            resp = self.barda.post_character(data)
        except ApiError:
            questionary.print(f"Failed to create character for '{name}'.", style=Styles.ERROR)
            return None

        if resp is None:
            return None

        self.conversions.store_cv(Resources.Character.value, character.id, resp["id"])
        questionary.print(
            f"Added '{name}' to {Resources.Character.name} conversions.", style=Styles.SUCCESS
        )
        return resp["id"]

    def _choose_character(self, character: GenericEntry) -> int | None:
        if not character.name:
            return None

        questionary.print(
            f"Let's do a character search on Metron for '{character.name}'",
            style=Styles.TITLE,
        )
        c_list = self.metron.characters_list(params={"name": character.name})
        choices = self._create_choices(c_list)
        if choices is None:
            questionary.print(f"Nothing found for '{character.name}'", style=Styles.WARNING)
        elif metron_id := self._confirm_resource_choice(Resources.Character, character, choices):
            return metron_id

        if questionary.confirm(
            f"Do want to use another name to search for '{character.name}'?"
        ).ask():
            txt = questionary.text(f"What name do you want to search for '{character.name}'?").ask()
            lst = self.metron.characters_list(params={"name": txt})
            new_choices = self._create_choices(lst)
            if new_choices is None:
                questionary.print(f"Nothing found for '{txt}'", style=Styles.WARNING)
            elif metron_id := self._confirm_resource_choice(
                Resources.Character, character, new_choices
            ):
                return metron_id

        return None

    def _search_for_character(self, character: GenericEntry) -> int | None:
        metron_id = self._choose_character(character) if character.name else None
        if metron_id is not None:
            return metron_id

        if questionary.confirm(
            f"Do you want to create a character for '{character.name}' on Metron?"
        ).ask():
            return self._create_character(character.id)
        if questionary.confirm(
            "Do you want to ignore this character during the rest of this session?"
        ).ask():
            self.ignore_characters.append(character.id)
        return None

    def _create_character_list(self, characters: List[GenericEntry]) -> List[int]:
        character_lst = []
        for character in characters:
            if self._ignore_resource(Ignore_Characters, character.id):
                continue
            if self.ignore_characters and character.id in self.ignore_characters:
                continue
            metron_id = self.conversions.get_cv(Resources.Character.value, character.id)
            if metron_id is None:
                metron_id = self._search_for_character(character)
            if metron_id is None:
                continue
            character_lst.append(metron_id)
        return character_lst

    ##########
    # Series #
    ##########
    @staticmethod
    def _create_series_choices(results) -> List[questionary.Choice]:
        choices = []
        for s in results:
            # Skip bad CV publishers
            pub = s.publisher.name if s.publisher is not None else ""
            if pub in BAD_PUBLISHERS:
                continue
            choice = questionary.Choice(
                title=f"{s.name} ({s.start_year}) - {s.issue_count} issues ({pub})", value=s
            )
            choices.append(choice)
        choices.extend(
            (
                questionary.Choice(title="Skip", value=""),
                questionary.Choice(title="Quit", value=-1),
            )
        )
        return choices

    def _what_series(self) -> VolumeEntry | None:
        series = questionary.text("What series do you want to import?").ask()
        try:
            results = self.cv.list_volumes(
                params={
                    "filter": f"name:{series}",
                },
                max_results=1500,
            )
        except (ServiceError, requests.exceptions.JSONDecodeError):
            questionary.print(
                f"Failed to retrieve information from Comic Vine for Series: {series}.",
                style=Styles.ERROR,
            )
            return None

        if not results:
            return None

        results.sort(key=operator.attrgetter("name"))

        choices = self._create_series_choices(results)

        return questionary.select("Which series to import", choices=choices).ask()

    def _ask_for_series_info(self, cv_series: VolumeEntry) -> dict[str, Any]:
        display_name = f"{cv_series.name} ({cv_series.start_year})"
        questionary.print(
            f"Series '{display_name}' needs to be created on Metron",
            style=Styles.TITLE,
        )
        series_name = self._determine_series_name(cv_series.name)
        sort_name = self._determine_series_sort_name(series_name)
        volume = int(
            questionary.text(
                f"What is the volume number for '{display_name}'?", validate=NumberValidator
            ).ask()
        )
        publisher_id = self._choose_publisher()
        series_type_id = self._choose_series_type()
        # collection_title = self._determine_series_collection_title()
        year_began = self._determine_series_year_began(cv_series.start_year)
        year_end = self._determine_series_year_end(series_type_id)
        genres = self._choose_genre()
        desc: str = questionary.text(
            f"Do you want to add a series summary for '{display_name}'?"
        ).ask()

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
            "cv_id": cv_series.id,
        }

    def _create_series(self, cv_series: VolumeEntry) -> int | None:
        data = self._ask_for_series_info(cv_series)

        try:
            new_series = self.barda.post_series(data)
        except ApiError:
            questionary.print(
                f"Failed to create series for '{data['name']}'. Exiting...", style=Styles.ERROR
            )
            exit(0)

        return None if new_series is None else new_series["id"]

    #########
    # Issue #
    #########
    def _create_issue(self, series_id: int, cv_issue: CV_Issue, gcd_series_id):
        gcd_stories = None
        if cv_issue.number:
            gcd = self._get_gcd_issue(gcd_series_id, cv_issue.number)
            if gcd is not None:
                gcd_stories = self._get_gcd_stories(gcd.id)
        else:
            gcd = None

        if cv_issue.cover_date:
            cover_date = self.fix_cover_date(cv_issue.cover_date)
        else:
            if questionary.confirm(
                f"'{cv_issue.number}' doesn't have a cover date. Do you want to add one?"
            ).ask():
                cover_date = questionary.text(
                    "What should the cover date be?", validate=DateValidator
                ).ask()
            else:
                LOGGER.error(f"No Cover date: {cv_issue}")
                exit(0)
        if gcd_stories is not None and len(gcd_stories) > 0:
            stories = gcd_stories
        else:
            stories = self._fix_title_data(cv_issue.name)

        LOGGER.debug(f"Stories is List: {isinstance(stories, List)}")

        cleaned_desc = clean_desc(remove_overview_text(cleanup_html(cv_issue.description, True)))
        character_lst = (
            self._create_character_list(cv_issue.characters) if self.add_characters else []
        )
        team_lst = self._create_team_list(cv_issue.teams) if self.add_characters else []
        arc_lst = self._create_arc_list(cv_issue.story_arcs)
        universe_lst = self._choose_universes() if self.add_universes else []
        img = self._get_image(cv_issue.image.original_url, ImageType.Cover)
        if gcd is not None:
            upc = gcd.barcode
            price = gcd.price
            pages = gcd.pages
            rating = gcd.rating
        else:
            upc = None
            price = None
            pages = None
            rating = Rating.Unknown.value

        gcd_reprints_lst = self.get_gcd_reprints(gcd.id) if gcd is not None else None
        reprints_lst = (
            self.get_metron_reprint(gcd_reprints_lst)
            if gcd_reprints_lst and gcd_reprints_lst is not None
            else []
        )

        data = {
            "series": series_id,
            "number": cv_issue.number,
            "name": stories,
            "cover_date": cover_date,
            "store_date": cv_issue.store_date,
            "desc": cleaned_desc,
            "upc": upc,
            "price": price,
            "page": pages,
            "rating": rating,
            "image": img,
            "characters": character_lst,
            "teams": team_lst,
            "arcs": arc_lst,
            "universes": universe_lst,
            "reprints": reprints_lst,
            "cv_id": cv_issue.id,
        }
        try:
            resp = self.barda.post_issue(data)
        except ApiError:
            return None

        if resp is None:
            return None

        if cv_issue.creators:
            credits_lst = self._create_credits_list(resp["id"], cover_date, cv_issue.creators)
            try:
                self.barda.post_credit(credits_lst)
                questionary.print(f"Added credits for #{resp['number']}.", style=Styles.SUCCESS)
            except ApiError:
                questionary.print(
                    f"Failed to add credits for #{resp['number']}", style=Styles.ERROR
                )

        # If we have gcd information let's save it to the cache file.
        if gcd:
            self.conversions.store_gcd(Resources.Issue.value, gcd.id, resp["id"])
            questionary.print(
                f"Added #{resp['number']} to {Resources.Issue.name} to cache. "
                f"GCD: {gcd.id} | Metron: {resp['id']}",
                style=Styles.SUCCESS,
            )

        return resp

    def _get_series_id(self, series) -> int | None:
        mseries_id = self._check_metron_for_series(series)
        return (
            self._create_series(series) if not mseries_id or mseries_id is None else int(mseries_id)
        )

    def _get_gcd_series_id(self):
        with DB() as db_obj:
            gcd_query = questionary.text("What series name do you want to use to search GCD?").ask()
            if gcd_series_list := db_obj.get_series_list(gcd_query):
                gcd_idx = self._select_gcd_series(gcd_series_list)
                return None if gcd_idx is None or gcd_idx == "" else gcd_series_list[gcd_idx][0]
            questionary.print(f"Unable to find series '{gcd_query}' on GCD.")
            return None

    def _update_metron_issue(self, cv: CV_Issue, met: MetronIssue) -> bool:  # NOQA: C901
        data: dict[str, Any] = {}
        if self.add_characters:
            if cv.characters:
                characters_lst = self._create_character_list(cv.characters)
                if met.characters:
                    metron_lst = [item.id for item in met.characters]
                else:
                    metron_lst = []
                for char in characters_lst:
                    if char not in metron_lst:
                        metron_lst.append(char)
                if metron_lst:
                    data["characters"] = metron_lst
            if cv.teams:
                teams_lst = self._create_team_list(cv.teams)
                if met.teams:
                    metron_lst = [item.id for item in met.teams]
                else:
                    metron_lst = []
                for team in teams_lst:
                    if team not in metron_lst:
                        metron_lst.append(team)
                if metron_lst:
                    data["teams"] = teams_lst
        if cv.story_arcs:
            arcs_lst = self._create_arc_list(cv.story_arcs)
            if met.arcs:
                metron_lst = [item.id for item in met.arcs]
            else:
                metron_lst = []
            for arc in arcs_lst:
                if arc not in metron_lst:
                    metron_lst.append(arc)
            if metron_lst:
                data["arcs"] = metron_lst

        if cv.description and not met.desc:  # type: ignore
            desc = remove_overview_text(cleanup_html(cv.description, True))
            data["desc"] = desc

        if cv.creators and questionary.confirm("Do you want to add any missing credits?").ask():
            credits_lst = self._create_credits_list(met.id, met.cover_date, cv.creators)  # type: ignore
            for item in credits_lst:
                try:
                    self.barda.post_credit([item])
                    questionary.print(
                        f"Added credits for Creator #{item['creator']} in '{met.series.name} #{met.number}'.",
                        # type: ignore
                        style=Styles.SUCCESS,
                    )
                except ApiError:
                    questionary.print(
                        f"Failed to add credits for '{met.series.name} #{met.number}'",  # type: ignore
                        style=Styles.ERROR,
                    )

        if not met.cv_id:
            data["cv_id"] = cv.id

        if not data:
            return False

        try:
            self.barda.patch_issue(met.id, data)  # type: ignore
        except ApiError:
            questionary.print(
                f"Failed to update Metron. Metron ID: {met}",
                style=Styles.ERROR,
            )
            return False
        return True

    def run(self) -> None:  # sourcery skip: low-code-quality
        series = self._what_series()
        if series is None:
            questionary.print("Nothing found", style=Styles.WARNING)
            return

        try:
            i_list = self.cv.list_issues(
                params={"filter": f"volume:{series.id}", "sort": "cover_date:asc"}, max_results=1500
            )
        except ServiceError:
            questionary.print(
                f"Failed to retrieve issue list from Comic Vine for Series: {series.name}.",
                style=Styles.ERROR,
            )
            return None

        series_id = self._get_series_id(series)
        if series_id is None:
            questionary.print("Unable to get Series ID. Exiting...", style=Styles.ERROR)
            exit(0)

        gcd_series_id = self._get_gcd_series_id()

        self.add_characters: bool = questionary.confirm(
            "Do you want to add characters for this series?"
        ).ask()

        self.add_universes: bool = questionary.confirm(
            "Do you want to add universes for this series?"
        ).ask()

        update_issue: bool = questionary.confirm(
            "Do you want to update existing issues in Metron?"
        ).ask()

        questionary.print(f"Going to add {len(i_list)} issues to Metron.", style=Styles.TITLE)
        for i in i_list:
            try:
                cv_issue = self.cv.get_issue(i.id)
            except (ServiceError, requests.JSONDecodeError):
                questionary.print(
                    "Failed to retrieve information from Comic Vine for Issue: "
                    f"{i.volume.name} #{i.number}. Skipping...",
                    style=Styles.ERROR,
                )
                continue

            if i.number is not None:
                # Check to see if issue already exists on Metron
                if m := self.metron.issues_list(
                    params={"series_id": series_id, "number": i.number}
                ):
                    if not update_issue:
                        questionary.print(f"{series.name} #{i.number} already exists. Skipping...")
                        continue

                    if not questionary.confirm(
                        f"'{series.name} #{i.number}' already exists. "
                        "Do you want to update resources?",
                    ).ask():
                        questionary.print(f"{series.name} #{i.number} already exists. Skipping...")
                        continue

                    mt_issue = self.metron.issue(m[0].id)
                    if self._update_metron_issue(cv_issue, mt_issue):
                        questionary.print(
                            f"Updated {mt_issue.series.name} #{mt_issue.number}.",  # type: ignore
                            style=Styles.SUCCESS,
                        )
                    else:
                        questionary.print(
                            f"Failed to update {mt_issue.series.name} #{mt_issue.number}.",  # type: ignore # noqa: E501
                            style=Styles.WARNING,
                        )
                    continue

            if cv_issue and cv_issue.number is not None:
                new_issue = self._create_issue(series_id, cv_issue, gcd_series_id)
                if new_issue is None:
                    questionary.print(
                        f"Failed to create issue #{cv_issue.number}", style=Styles.ERROR
                    )
                    return
                questionary.print(f"Added issue #{new_issue['number']}", Styles.SUCCESS)

    def _patch_cvid(self, cv_id: int, metron_id: int) -> bool:
        data = {"cv_id": cv_id}
        try:
            self.barda.patch_issue(metron_id, data)
        except ApiError:
            questionary.print(
                f"Failed to update Metron. Metron ID: {metron_id} CV ID:{cv_id}",
                style=Styles.ERROR,
            )
            return False
        return True

    def _get_series_from_cv(self, series_name: str, m_series) -> List[VolumeEntry] | None:
        try:
            return self.cv.list_volumes(
                params={
                    "filter": f"name:{series_name}",
                },
                max_results=1500,
            )
        except (ServiceError, requests.exceptions.JSONDecodeError):
            questionary.print(
                "Failed to retrieve information from Comic Vine for Series: "
                f"{m_series.display_name}.",
                style=Styles.ERROR,
            )
            return None

    def _get_cv_series(self, metron_series, num: int) -> VolumeEntry | None:
        title = metron_series.display_name.rsplit(" ", 1)[0]  # Remove the series year
        cleaned_title = clean_search_series_title(title)
        results = self._get_series_from_cv(cleaned_title, metron_series)

        if not results:
            if not questionary.confirm(
                f"No series for '{metron_series.display_name}' on Comic Vine. "
                "Do you want to do another search?"
            ).ask():
                return None
            series_query = questionary.text(
                "What name should we use to search for the series?"
            ).ask()
            results = self._get_series_from_cv(series_query, metron_series)

        if not results:
            return None

        results.sort(key=operator.attrgetter("name"))

        choices = self._create_series_choices(results)

        return questionary.select(
            f"Which series to import for '{metron_series.display_name}: {num} issues'",
            choices=choices,
        ).ask()

    def import_cvid_by_publisher(self) -> None:
        pub_id = self._choose_publisher()
        series_type_id = self._choose_series_type()
        series_lst = self.metron.series_list(
            params={"publisher_id": pub_id, "series_type_id": series_type_id}
        )
        questionary.print(f"Going to start matching {len(series_lst)} series", style=Styles.SUCCESS)
        for s in series_lst:
            questionary.print(f"Searching for {s.display_name}", style=Styles.TITLE)
            metron_issues = self.metron.issues_list(
                params={"series_id": s.id, "missing_cv_id": True}
            )
            if metron_issues:
                num_issues = len(metron_issues)
                questionary.print(
                    f"Retrieved data for {num_issues} issues from Metron",
                    style=Styles.SUCCESS,
                )
                # Let's see if we can get the series from Comic Vine
                cv_series = self._get_cv_series(s, num_issues)
                match cv_series:
                    case -1:
                        questionary.print("Exiting...", style=Styles.SUCCESS)
                        exit(0)
                    case None | "":
                        questionary.print(
                            f"No series found for {s.display_name} on Comic Vine. Skipping...",
                            style=Styles.WARNING,
                        )
                        continue
                    case _:
                        # Retrieve Issue List from Comic Vine
                        try:
                            cv_list = self.cv.list_issues(
                                params={
                                    "filter": f"volume:{cv_series.id}",
                                    "sort": "cover_date:asc",
                                }
                            )
                        except ServiceError:
                            questionary.print(
                                "Failed to retrieve issue list from Comic Vine for Series: "
                                f"{cv_series.name}.",
                                style=Styles.ERROR,
                            )
                            continue
                        questionary.print(
                            f"Retrieved data for {len(cv_list)} issues from Comic Vine",
                            style=Styles.SUCCESS,
                        )
            else:
                questionary.print(
                    f"No issues need to be fixed for '{s.display_name}'", style=Styles.SUCCESS
                )
                continue

            # Now compare lists and send data to Metron.
            for x in cv_list:
                idx = next(
                    (i for i, item in enumerate(metron_issues) if item.number == x.number), None
                )
                if idx is None:
                    questionary.print(
                        f"No issue found on Metron for '{x.volume.name} #{x.number}'",
                        style=Styles.WARNING,
                    )
                    continue

                if self._patch_cvid(x.id, metron_issues[idx].id):
                    questionary.print(
                        f"Add CVID: {x.id} to '{metron_issues[idx].series.name} "
                        f"#{metron_issues[idx].number}'",
                        style=Styles.SUCCESS,
                    )

                else:
                    questionary.print(
                        f"Failed to update '{metron_issues[idx].series.name} "
                        f"#{metron_issues[idx].number}'",
                        style=Styles.WARNING,
                    )

    def import_cvid_by_series(self) -> None:
        while questionary.confirm("Do you want to import CVID's for a series?").ask():
            if not (series := self._what_series()):
                continue

            # Get Metron Series ID
            series_id = self._get_series_id(series)
            if series_id is None:
                questionary.print("Unable to get Series ID. Exiting...", style=Styles.ERROR)
                continue

            # Retrieve Issue List from Metron
            metron_issues = self.metron.issues_list(
                params={"series_id": series_id, "missing_cv_id": True}
            )  # type: ignore  # noqa: E501
            if not metron_issues:
                questionary.print("No issues on metron need a Comic Vine ID.", style=Styles.SUCCESS)
                continue

            questionary.print(
                f"Retrieved data for {len(metron_issues)} issues from Metron", style=Styles.SUCCESS
            )

            # Retrieve Issue List from Comic Vine
            try:
                cv_list = self.cv.list_issues(
                    params={"filter": f"volume:{series.id}", "sort": "cover_date:asc"},
                    max_results=1500,
                )
            except ServiceError:
                questionary.print(
                    f"Failed to retrieve issue list from Comic Vine for Series: {series.name}.",
                    style=Styles.ERROR,
                )
                continue

            questionary.print(
                f"Retrieved data for {len(cv_list)} issues from Comic Vine", style=Styles.SUCCESS
            )

            # Now compare lists and send data to Metron.
            for x in cv_list:
                idx = next(
                    (i for i, item in enumerate(metron_issues) if item.number == x.number), None
                )
                if idx is None:
                    questionary.print(
                        f"No issue found on Metron for '{series.name} #{x.number}'",
                        style=Styles.WARNING,
                    )
                    continue

                if self._patch_cvid(x.id, metron_issues[idx].id):
                    questionary.print(
                        f"Add CVID: {x.id} to '{metron_issues[idx].series.name} "
                        f"#{metron_issues[idx].number}'",
                        style=Styles.SUCCESS,
                    )

                else:
                    questionary.print(
                        f"Failed to update '{metron_issues[idx].series.name} "
                        f"#{metron_issues[idx].number}'",
                        style=Styles.WARNING,
                    )

    def _patch_series_cvid(self, cv_id: int, metron_id: int) -> bool:
        data = {"cv_id": cv_id}
        try:
            self.barda.patch_series(metron_id, data)
        except ApiError:
            questionary.print(
                f"Failed to update Metron. Metron ID: {metron_id} CV_ID: {cv_id}",
                style=Styles.ERROR,
            )
            return False
        return True

    def import_series_cvid_by_publisher(self) -> None:
        pub_id = self._choose_publisher()
        series_lst = self.metron.series_list(
            params={"publisher_id": pub_id, "missing_cv_id": True},
        )
        questionary.print(f"Going to start matching {len(series_lst)} series", style=Styles.SUCCESS)
        for s in series_lst:
            questionary.print(f"Searching for '{s.display_name}'", style=Styles.TITLE)
            cv_series = self._get_cv_series(s, s.issue_count)
            match cv_series:
                case -1:
                    questionary.print("Exiting...", style=Styles.SUCCESS)
                    exit(0)
                case None | "":
                    questionary.print(
                        f"No series found for {s.display_name} on Comic Vine. Skipping...",
                        style=Styles.WARNING,
                    )
                    continue
                case _:
                    if self._patch_series_cvid(cv_series.id, s.id):
                        questionary.print(
                            f"Added CVID: {cv_series.id} to '{s.display_name}'",
                            style=Styles.SUCCESS,
                        )
                    else:
                        questionary.print(
                            f"Failed to update '{s.display_name}'", style=Styles.WARNING
                        )
