import datetime
import logging
import uuid
from enum import Enum, auto, unique
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, List

import questionary
import requests
from mokkari import api as m_api
from mokkari.issue import RoleList
from mokkari.publisher import PublishersList
from mokkari.series import SeriesTypeList
from mokkari.session import Session
from mokkari.sqlite_cache import SqliteCache as sql_cache
from mokkari.team import TeamsList
from simyan.comicvine import Comicvine as CV
from simyan.comicvine import Issue, VolumeEntry
from simyan.exceptions import ServiceError
from simyan.schemas.generic_entries import CreatorEntry, GenericEntry
from simyan.sqlite_cache import SQLiteCache
from titlecase import titlecase

from barda.exceptions import ApiError
from barda.gcd.db import DB
from barda.gcd.gcd_issue import GCD_Issue, Rating
from barda.image import CVImage
from barda.post_data import PostData
from barda.resource_keys import ResourceKeys, Resources
from barda.settings import BardaSettings
from barda.styles import Styles
from barda.utils import cleanup_html
from barda.validators import NumberValidator, YearValidator

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.DEBUG)
handler = logging.FileHandler("barda.log")
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
handler.setFormatter(formatter)
LOGGER.addHandler(handler)


@unique
class ImageType(Enum):
    Cover = auto()
    Creator = auto()
    Resource = auto()


@unique
class CV_Creator(Enum):
    Alan_Fine = 56587
    Dan_Buckley = 41596
    Joe_Quesada = 1537
    CB_Cebulski = 43193
    Axel_Alonso = 23115
    Jim_Shooter = 40450


@unique
class Ignore_Characters(Enum):
    Abraham_Lincoln = 14131
    Adolf_Hitler = 9671
    Arjuna = 26052
    Barack_Obama = 56661
    Bill_Clinton = 11570
    Del_Close = 96033
    Donald_Trump = 17028
    Frank_Belknap_Long = 142839
    Genghis_Khan = 37303
    George_H_W_Bush = 9957
    George_W_Bush = 4660
    H_P_Lovecraft = 10641
    John_Ostrander = 96034
    Krishna = 44322
    L_Ron_Hubbard = 96035
    Lash_LaRue = 75444
    Lyndon_Johnson = 38601
    Nelson_Mandela = 19799
    P_W_Botha = 173183
    Santa_Claus = 22143
    Sonia_Haft_Greene = 142844
    Stan_Lee = 3115
    Tom_DeFalco = 11901


@unique
class Ignore_Creators(Enum):
    Typeset = 67476


@unique
class Ignore_Teams(Enum):
    Cavemen = 57593
    Communists = 56975
    Dinosaurs = 56551
    Father_and_Daughter = 57450
    Justice_Forever = 57862
    Special_Air_Service = 57233
    United_States_Air_Force = 44417
    United_States_Navy = 44418
    United_States_Special_Forces = 55045


class ImportSeries:
    def __init__(self, config: BardaSettings) -> None:
        self.config = config
        cv_cache = SQLiteCache(config.cv_cache, 1) if config.cv_cache else None
        metron_cache = sql_cache(str(config.metron_cache), 1) if config.metron_cache else None

        self.simyan = CV(api_key=config.cv_api_key, cache=cv_cache)  # type: ignore
        self.mokkari: Session = m_api(config.metron_user, config.metron_password, metron_cache)  # type: ignore
        self.barda = PostData(config.metron_user, config.metron_password)
        self.conversions = ResourceKeys(str(config.conversions))
        self.image_dir = TemporaryDirectory()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.image_dir.cleanup()

    @staticmethod
    def fix_cover_date(orig_date: datetime.date) -> datetime.date:
        if orig_date.day != 1:
            return datetime.date(orig_date.year, orig_date.month, 1)
        else:
            return orig_date

    @staticmethod
    def _ignore_resource(resource, cv_id: int) -> bool:
        return any(cv_id == i.value for i in resource)

    def _get_image(self, url: str, img_type: ImageType) -> str:
        LOGGER.debug("Entering get_image()...")
        receive = requests.get(url)
        cv = Path(url)
        LOGGER.debug(f"Comic Vine image: {cv.name}")
        if cv.name in ["6373148-blank.png", "img_broken.png"]:
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
            result[index] = titlecase(result[index])

        LOGGER.debug(f"title: {result}")
        LOGGER.debug("Exiting fix_title_data()...")
        return result

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

    def _confirm_resource_choice(
        self, resource: Resources, cv_entry: GenericEntry, choices: List[questionary.Choice]
    ) -> int | None:
        if metron_id := questionary.select(
            f"What {resource.name} should be added for '{cv_entry.name}'?", choices=choices
        ).ask():
            self.conversions.store(resource.value, cv_entry.id_, metron_id)
            questionary.print(
                f"Added '{cv_entry.name}' to {resource.name} conversions. CV: {cv_entry.id_}, Metron: {metron_id}",
                style=Styles.SUCCESS,
            )
        return metron_id

    def _check_metron_for_series(self, series: VolumeEntry) -> str | None:
        if series_lst := self.mokkari.series_list({"name": series.name}):
            choices: List[questionary.Choice] = []
            for i in series_lst:
                choice = questionary.Choice(title=i.display_name, value=i.id)
                choices.append(choice)
            choices.append(questionary.Choice(title="None", value=""))
            return questionary.select(
                f"What series on Metron should be used for '{series.name} ({series.start_year})'?",
                choices=choices,
            ).ask()
        else:
            return None

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

    def _get_gcd_stories(self, gcd_issue_id):
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
                stories.append(titlecase(story))

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
        if cover_date >= datetime.date(2011, 4, 1) and cover_date < datetime.date(2018, 3, 1):
            return ["editor in chief"]
        return []

    @staticmethod
    def _get_cb_cebulski_role(cover_date: datetime.date) -> List[str]:
        return ["editor in chief"] if cover_date >= datetime.date(2018, 3, 1) else []

    @staticmethod
    def _get_jim_shooter_role(cover_date: datetime.date) -> List[str]:
        if cover_date >= datetime.date(1978, 3, 1) and cover_date < datetime.date(1987, 10, 1):
            return ["editor in chief"]
        return []

    def _handle_specal_creators(self, creator: int, cover_date: datetime.date) -> List[str]:
        match creator:
            case CV_Creator.Alan_Fine.value:
                return ["executive producer"]
            case CV_Creator.Dan_Buckley.value:
                return self._get_dan_buckley_role(cover_date)
            case CV_Creator.Joe_Quesada.value:
                return self._get_joe_quesada_role(cover_date)
            case CV_Creator.CB_Cebulski.value:
                return self._get_cb_cebulski_role(cover_date)
            case CV_Creator.Axel_Alonso.value:
                return self._get_axel_alonso_role(cover_date)
            case CV_Creator.Jim_Shooter.value:
                return self._get_jim_shooter_role(cover_date)
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
    def _ask_for_role(creator: CreatorEntry, metron_roles: RoleList):
        choices = []
        for i in metron_roles:
            choice = questionary.Choice(title=i.name, value=i.id)  # type: ignore
            choices.append(choice)
        return questionary.select(
            f"No role found for {creator.name}. What should it be?", choices=choices
        ).ask()

    def _create_role_list(self, creator: CreatorEntry, cover_date: datetime.date) -> List[str]:
        role_lst = self._handle_specal_creators(creator.id_, cover_date)
        if len(role_lst) == 0:
            role_lst = creator.roles.split(", ")
            role_lst = self._fix_role_list(role_lst)

        metron_role_lst = self.mokkari.role_list()
        roles = []
        for i in role_lst:
            roles.extend(
                m_role.id for m_role in metron_role_lst if i.lower() == m_role.name.lower()
            )

        if not roles:
            roles.append(self._ask_for_role(creator, metron_role_lst))

        return roles

    def _create_credits_list(
        self, issue_id: int, cover_date: datetime.date, credits: List[CreatorEntry]
    ) -> List:
        LOGGER.debug("Entering create_credits_list()...")
        credits_lst = []
        for i in credits:
            if self._ignore_resource(Ignore_Creators, i.id_):
                continue
            person = GenericEntry(id=i.id_, name=i.name, api_detail_url="")
            creator_id = self.conversions.get(Resources.Creator.value, i.id_)
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
            cv_data = self.simyan.creator(cv_id)
        except ServiceError:
            questionary.print(
                f"Failed to retrieve information from Comic Vine for Creator ID: {cv_id}.",
                style=Styles.ERROR,
            )
            return None

        questionary.print(f"Let's create creator '{cv_data.name}' on Metron", style=Styles.TITLE)
        name = (
            cv_data.name
            if questionary.confirm(f"Is '{cv_data.name}' the correct name?").ask()
            else questionary.text("What should be the creator's name be?").ask()
        )
        desc = questionary.text("What should be the description for this creator?").ask()
        LOGGER.debug(f"Retrieving image for '{name}'.")
        img = self._get_image(cv_data.image.original, ImageType.Creator)
        LOGGER.debug(f"{name} image: {img}")
        data = {
            "name": name,
            "desc": desc,
            "image": img,
            "alias": [],
            "birth": cv_data.date_of_birth,
            "death": cv_data.date_of_death,
        }

        try:
            resp = self.barda.post_creator(data)
        except ApiError:
            questionary.print(f"Failed to create creator: '{name}'.", style=Styles.ERROR)
            return None

        if resp is None:
            return None

        self.conversions.store(Resources.Creator.value, cv_data.creator_id, resp["id"])
        questionary.print(
            f"Added '{name}' to {Resources.Creator.name} conversions. CV: {cv_data.creator_id}, Metron: {resp['id']}",
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
        c_list = self.mokkari.creators_list(params={"name": creator.name})
        choices = self._create_choices(c_list)
        if choices is None:
            questionary.print(f"Nothing found for '{creator.name}'", style=Styles.WARNING)
        elif metron_id := self._confirm_resource_choice(Resources.Creator, creator, choices):
            return metron_id

        if questionary.confirm(
            f"Do want to use another name to search for '{creator.name}'?"
        ).ask():
            txt = questionary.text(f"What name do you want to search for '{creator.name}'?").ask()
            lst = self.mokkari.creators_list(params={"name": txt})
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
            return self._create_creator(creator.id_)
        else:
            return None

    def _create_creator_list(self, creators: List[GenericEntry]) -> List[int]:
        creator_lst = []
        for creator in creators:
            metron_id = self.conversions.get(Resources.Creator.value, creator.id_)
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
            cv_data = self.simyan.story_arc(cv_id)
        except ServiceError:
            questionary.print(
                f"Failed to retrieve information from Comic Vine for Story Arc ID: {cv_id}.",
                style=Styles.ERROR,
            )
            return None
        questionary.print(f"Let's create story arc '{cv_data.name}' on Metron", style=Styles.TITLE)
        name = (
            cv_data.name
            if questionary.confirm(f"Is '{cv_data.name}' the correct name?").ask()
            else questionary.text("What should be the story arc name be?").ask()
        )
        desc = questionary.text("What should be the description for this story arc?").ask()
        img = self._get_image(cv_data.image.original, ImageType.Resource)
        data = {"name": name, "desc": desc, "image": img}

        try:
            resp = self.barda.post_arc(data)
        except ApiError:
            questionary.print(f"Fail to create story arc for '{name}'.", style=Styles.ERROR)
            return None

        if resp is None:
            return None

        self.conversions.store(Resources.Arc.value, cv_data.story_arc_id, resp["id"])
        questionary.print(f"Add '{name}' to {Resources.Arc.name} conversions", style=Styles.SUCCESS)
        return resp["id"]

    def _choose_arc(self, arc: GenericEntry) -> int | None:
        if not arc.name:
            return None

        questionary.print(
            f"Let's do a story arc search on Metron for '{arc.name}'", style=Styles.TITLE
        )
        arc_lst = self.mokkari.arcs_list(params={"name": arc.name})
        choices = self._create_choices(arc_lst)
        if choices is None:
            questionary.print(f"Nothing found for '{arc.name}'", style=Styles.WARNING)
        elif metron_id := self._confirm_resource_choice(Resources.Arc, arc, choices):
            return metron_id

        if questionary.confirm(f"Do want to use another name to search for '{arc.name}'?").ask():
            txt = questionary.text(f"What name do you want to search for '{arc.name}'?").ask()
            lst = self.mokkari.arcs_list(params={"name": txt})
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
            return self._create_arc(arc.id_)
        else:
            return None

    def _create_arc_list(self, arcs: List[GenericEntry]) -> List[int]:
        arc_lst = []
        for arc in arcs:
            metron_id = self.conversions.get(Resources.Arc.value, arc.id_)
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
            cv_data = self.simyan.team(cv_id)
        except ServiceError:
            questionary.print(
                f"Failed to retrieve information from Comic Vine for Team ID: {cv_id}.",
                style=Styles.ERROR,
            )
            return None

        questionary.print(f"Let's create team '{cv_data.name}' on Metron", style=Styles.TITLE)
        name = (
            cv_data.name
            if questionary.confirm(f"Is '{cv_data.name}' the correct name?").ask()
            else questionary.text("What should the team name be?").ask()
        )
        desc = questionary.text("What should be the description for this team?").ask()
        img = self._get_image(cv_data.image.original, ImageType.Resource)
        data = {"name": name, "desc": desc, "image": img, "creators": []}

        try:
            resp = self.barda.post_team(data)
        except ApiError:
            questionary.print(f"Failed to create team for '{name}'.", style=Styles.ERROR)
            return None

        if resp is None:
            return None

        self.conversions.store(Resources.Team.value, cv_data.team_id, resp["id"])
        questionary.print(
            f"Added '{name}' to {Resources.Team.name}  conversions", style=Styles.SUCCESS
        )
        return resp["id"]

    def _choose_team(self, team: GenericEntry) -> int | None:
        if not team.name:
            return None

        questionary.print(f"Let's do a team search on Metron for '{team.name}'", style=Styles.TITLE)
        team_lst: TeamsList = self.mokkari.teams_list(params={"name": team.name})
        choices = self._create_choices(team_lst)
        if choices is None:
            questionary.print(f"Nothing found for '{team.name}'", style=Styles.WARNING)
        elif metron_id := self._confirm_resource_choice(Resources.Team, team, choices):
            return metron_id

        if questionary.confirm(f"Do want to use another name to search for '{team.name}'?").ask():
            txt = questionary.text(f"What name do you want to search for '{team.name}'?").ask()
            lst = self.mokkari.teams_list(params={"name": txt})
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
            return self._create_team(team.id_)
        else:
            return None

    def _create_team_list(self, teams: List[GenericEntry]) -> List[int]:
        team_lst = []
        for team in teams:
            if self._ignore_resource(Ignore_Teams, team.id_):
                continue
            metron_id = self.conversions.get(Resources.Team.value, team.id_)
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
            cv_data = self.simyan.character(cv_id)
        except ServiceError:
            questionary.print(
                f"Failed to retrieve information from Comic Vine for Character ID: {cv_id}.",
                style=Styles.ERROR,
            )
            return None

        questionary.print(f"Let's create character '{cv_data.name}' on Metron", style=Styles.TITLE)
        name = (
            cv_data.name
            if questionary.confirm(f"Is '{cv_data.name}' the correct name?").ask()
            else questionary.text("What should the characters name be?").ask()
        )
        desc = questionary.text("What description do you want to have for this character?").ask()
        img = self._get_image(cv_data.image.original, ImageType.Resource)
        teams_lst = self._create_team_list(cv_data.teams)
        creators_lst = self._create_creator_list(cv_data.creators)
        data = {
            "name": name,
            "alias": [],
            "desc": desc,
            "image": img,
            "teams": teams_lst,
            "creators": creators_lst,
        }

        try:
            resp = self.barda.post_character(data)
        except ApiError:
            questionary.print(f"Failed to create character for '{name}'.", style=Styles.ERROR)
            return None

        if resp is None:
            return None

        self.conversions.store(Resources.Character.value, cv_data.character_id, resp["id"])
        questionary.print(
            f"Added '{name}' to {Resources.Character.name} conversions.", style=Styles.SUCCESS
        )
        return resp["id"]

    def _choose_character(self, character: GenericEntry) -> int | None:
        if not character.name:
            return None

        questionary.print(
            f"Let's do a character search on Metron for '{character.name}'", style=Styles.TITLE
        )
        c_list = self.mokkari.characters_list(params={"name": character.name})
        choices = self._create_choices(c_list)
        if choices is None:
            questionary.print(f"Nothing found for '{character.name}'", style=Styles.WARNING)
        elif metron_id := self._confirm_resource_choice(Resources.Character, character, choices):
            return metron_id

        if questionary.confirm(
            f"Do want to use another name to search for '{character.name}'?"
        ).ask():
            txt = questionary.text(f"What name do you want to search for '{character.name}'?").ask()
            lst = self.mokkari.characters_list(params={"name": txt})
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
            return self._create_character(character.id_)
        else:
            return None

    def _create_character_list(self, characters: List[GenericEntry]) -> List[int]:
        character_lst = []
        for character in characters:
            if self._ignore_resource(Ignore_Characters, character.id_):
                continue
            metron_id = self.conversions.get(Resources.Character.value, character.id_)
            if metron_id is None:
                metron_id = self._search_for_character(character)
            if metron_id is None:
                continue
            character_lst.append(metron_id)
        return character_lst

    ###############
    # Series Type #
    ###############
    def _choose_series_type(self) -> int:  # sourcery skip: class-extract-method
        st_lst: SeriesTypeList = self.mokkari.series_type_list()
        choices = []
        for s in st_lst:
            choice = questionary.Choice(title=s.name, value=s.id)
            choices.append(choice)
        return int(questionary.select("What type of series is this?", choices=choices).ask())

    #############
    # Publisher #
    #############
    def _choose_publisher(self) -> int:
        pub_lst: PublishersList = self.mokkari.publishers_list()
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
    def _create_series_choices(results) -> List[questionary.Choice]:
        choices = []
        for s in results:
            choice = questionary.Choice(
                title=f"{s.name} ({s.start_year}) - {s.issue_count} issues", value=s
            )
            choices.append(choice)
        choices.append(questionary.Choice(title="Skip", value=""))
        return choices

    def _what_series(self) -> VolumeEntry | None:
        series = questionary.text("What series do you want to import?").ask()
        try:
            results = self.simyan.volume_list(
                params={
                    "filter": f"name:{series}",
                }
            )
        except ServiceError:
            questionary.print(
                f"Failed to retrieve information from Comic Vine for Series: {series}.",
                style=Styles.ERROR,
            )
            return None

        if not results:
            return None

        choices = self._create_series_choices(results)

        return questionary.select("Which series to import", choices=choices).ask()

    @staticmethod
    def _determine_series_year_began(start_year: int | None) -> int:
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
        year_began = self._determine_series_year_began(cv_series.start_year)
        year_end = self._determine_series_year_end(series_type_id)
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
            "genres": [],
            "associated": [],
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
    def _create_issue(self, series_id: int, cv_issue: Issue, gcd_series_id):
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
            # If we don't have a date, let's bail.
            questionary.print(f"{cv_issue.name} doesn't have a cover date. Exiting...")
            exit(0)
        if gcd_stories is not None and len(gcd_stories) > 0:
            stories = gcd_stories
        else:
            stories = self._fix_title_data(cv_issue.name)

        LOGGER.debug(f"Stories is List: {isinstance(stories, List)}")

        cleaned_desc = cleanup_html(cv_issue.description, True)
        character_lst = self._create_character_list(cv_issue.characters)
        team_lst = self._create_team_list(cv_issue.teams)
        arc_lst = self._create_arc_list(cv_issue.story_arcs)
        img = self._get_image(cv_issue.image.original, ImageType.Cover)
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
        }
        try:
            resp = self.barda.post_issue(data)
        except ApiError:
            return None

        if resp is None:
            return None

        credits_lst = self._create_credits_list(resp["id"], cover_date, cv_issue.creators)
        try:
            self.barda.post_credit(credits_lst)
            questionary.print(f"Added credits for #{resp['number']}.", style=Styles.SUCCESS)
        except ApiError:
            questionary.print(f"Failed to add credits for #{resp['number']}", style=Styles.ERROR)

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
                gcd_series_id = None if gcd_idx is None else gcd_series_list[gcd_idx][0]
            else:
                questionary.print(f"Unable to find series '{gcd_query}' on GCD.")
                gcd_series_id = None
        return gcd_series_id

    def run(self) -> None:
        if series := self._what_series():
            try:
                i_list = self.simyan.issue_list(
                    params={"filter": f"volume:{series.volume_id}", "sort": "cover_date:asc"}
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

            for i in i_list:
                try:
                    cv_issue = self.simyan.issue(i.issue_id)
                except ServiceError:
                    questionary.print(
                        f"Failed to retrieve information from Comic Vine for Issue: {i.volume.name} #{i.number}. Skipping...",
                        style=Styles.ERROR,
                    )
                    continue

                if cv_issue and cv_issue.number is not None:
                    if not self.mokkari.issues_list(
                        params={"series_id": series_id, "number": cv_issue.number}
                    ):
                        new_issue = self._create_issue(series_id, cv_issue, gcd_series_id)
                        if new_issue is not None:
                            questionary.print(f"Added issue #{new_issue['number']}", Styles.SUCCESS)
                        else:
                            questionary.print(
                                f"Failed to create issue #{cv_issue.number}", style=Styles.ERROR
                            )
                    else:
                        questionary.print(
                            f"{cv_issue.volume.name} #{cv_issue.number} already exists. Skipping..."
                        )
        else:
            print("Nothing found")
