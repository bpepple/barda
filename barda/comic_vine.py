import datetime
import uuid
from enum import Enum, auto, unique
from pathlib import Path
from typing import List

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
from simyan.schemas.generic_entries import CreatorEntry, GenericEntry
from simyan.sqlite_cache import SQLiteCache
from titlecase import titlecase

from barda.exceptions import ApiError
from barda.image import CVImage
from barda.post_data import PostData
from barda.resource_keys import ConversionKeys
from barda.settings import BardaSettings
from barda.styles import Styles
from barda.utils import cleanup_html


@unique
class ImageType(Enum):
    Cover = auto()
    Creator = auto()
    Resource = auto()


@unique
class Resources(Enum):
    Character = 0
    Team = 1
    Arc = 2
    Creator = 3


@unique
class CV_Creator(Enum):
    Alan_Fine = 56587
    Dan_Buckley = 41596
    Joe_Quesada = 1537
    CB_Cebulski = 43193
    Axel_Alonso = 23115


class ComicVine:
    def __init__(self, config: BardaSettings) -> None:
        self.config = config
        cv_cache = SQLiteCache(config.cv_cache, 1) if config.cv_cache else None
        metron_cache = sql_cache(str(config.metron_cache), 1) if config.metron_cache else None

        self.simyan = CV(api_key=config.cv_api_key, cache=cv_cache)  # type: ignore
        self.mokkari: Session = m_api(config.metron_user, config.metron_password, metron_cache)  # type: ignore
        self.barda = PostData(config.metron_user, config.metron_password)
        self.conversions = ConversionKeys(str(config.conversions))

    @staticmethod
    def fix_cover_date(orig_date: datetime.date) -> datetime.date:
        if orig_date.day != 1:
            return datetime.date(orig_date.year, orig_date.month, 1)
        else:
            return orig_date

    def _get_image(self, url: str, img_type: ImageType) -> str | None:
        receive = requests.get(url)
        cv = Path(url)
        if cv.name in ["6373148-blank.png"]:
            return None
        new_fn = f"{uuid.uuid4().hex}{cv.suffix}"
        img_file = Path("/tmp") / new_fn
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
                return None
        return str(img_file)

    @staticmethod
    def _fix_title_data(title: str | None) -> List[str]:
        if title is None:
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

    ##################
    # Handle Credits #
    ##################
    @staticmethod
    def _bad_creator(cv_id: int) -> bool:
        bad_creator_id = [67476]
        return cv_id in bad_creator_id

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

    def _add_credits(
        self, issue_id: int, cover_date: datetime.date, credits: List[CreatorEntry]
    ) -> None:
        for i in credits:
            if self._bad_creator(i.id_):
                continue
            person = GenericEntry(id=i.id_, name=i.name, api_detail_url="")
            creator_id = self.conversions.get(Resources.Creator.value, i.id_)
            if creator_id is None:
                creator_id = self._search_for_creator(person)
            if creator_id is None:
                continue
            role_lst = self._create_role_list(i, cover_date)
            data = {"issue": issue_id, "creator": creator_id, "role": role_lst}
            try:
                self.barda.post_credit(data)
            except ApiError:
                questionary.print(f"Failed to add credit for '{i.name}'", style=Styles.ERROR)
                return
            questionary.print(f"Added credit for {i.name}.", style=Styles.SUCCESS)

    ###################
    # Handle Creators #
    ###################
    def _create_creator(self, cv_id: int) -> int | None:
        cv_data = self.simyan.creator(cv_id)
        questionary.print(f"Let's create creator '{cv_data.name}' on Metron", style=Styles.TITLE)
        name = (
            cv_data.name
            if questionary.confirm(f"Is '{cv_data.name}' the correct name?").ask()
            else questionary.text("What should be the creator's name be?").ask()
        )
        desc = questionary.text("What should be the description for this creator?").ask()
        img = self._get_image(cv_data.image.original, ImageType.Creator)
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

        self.conversions.store(Resources.Creator.value, cv_data.creator_id, resp["id"])
        questionary.print(
            f"Added '{name}' to {Resources.Creator.name} conversions. CV: {cv_data.creator_id}, Metron: {resp['id']}",
            style=Styles.SUCCESS,
        )
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
        cv_data = self.simyan.story_arc(cv_id)
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
        cv_data = self.simyan.team(cv_id)
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
        cv_data = self.simyan.character(cv_id)
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
    def _choose_series_type(self):  # sourcery skip: class-extract-method
        st_lst: SeriesTypeList = self.mokkari.series_type_list()
        choices = []
        for s in st_lst:
            choice = questionary.Choice(title=s.name, value=s.id)
            choices.append(choice)
        return questionary.select("What type of series is this?", choices=choices).ask()

    #############
    # Publisher #
    #############
    def _choose_publisher(self):
        pub_lst: PublishersList = self.mokkari.publishers_list()
        choices = []
        for p in pub_lst:
            choice = questionary.Choice(title=p.name, value=p.id)
            choices.append(choice)
        # TODO: Provide option to add a Publisher
        return questionary.select("Which publisher is this series from?", choices=choices).ask()

    ##########
    # Series #
    ##########
    def _what_series(self) -> VolumeEntry | None:
        series = questionary.text("What series do you want to import?").ask()
        if not (
            results := self.simyan.volume_list(
                params={
                    "filter": f"name:{series}",
                }
            )
        ):
            return None
        choices = []
        for s in results:
            choice = questionary.Choice(
                title=f"{s.name} ({s.start_year}) - {s.issue_count} issues", value=s
            )
            choices.append(choice)
        choices.append(questionary.Choice(title="Skip", value=""))

        return questionary.select("Which series to import", choices=choices).ask()

    def _check_series_exist(self, series: VolumeEntry) -> bool:
        params = {"name": series.name, "year_began": series.start_year}
        return bool(self.mokkari.series_list(params=params))

    def _create_series(self, cv_series: VolumeEntry) -> int:
        display_name = f"{cv_series.name} ({cv_series.start_year})"
        questionary.print(
            f"Series '{display_name}' needs to be created on Metron",
            style=Styles.TITLE,
        )
        series_name = (
            cv_series.name
            if questionary.confirm(f"Is '{cv_series.name}' the correct name?").ask()
            else questionary.text("What should the series name be?").ask()
        )
        sort_name = (
            series_name
            if questionary.confirm(f"Should '{series_name}' also be the Sort Name?").ask()
            else questionary.text("What should the sort name be?").ask()
        )
        # TODO: Need to validate this.
        volume = int(questionary.text(f"What is the volume number for '{display_name}'?").ask())
        publisher_id = self._choose_publisher()
        series_type_id = self._choose_series_type()
        year_began = (
            cv_series.start_year
            if questionary.confirm(
                f"Is '{cv_series.start_year}' the correct year that this series began?"
            ).ask()
            else int(questionary.text("What begin year should be used for this series?").ask())
        )
        if series_type_id == 11:
            year_end = int(questionary.text("What year did this series end in?").ask())
        else:
            year_end = None
        desc = questionary.text(f"Do you want to add a series summary for '{display_name}'?").ask()

        data = {
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

        try:
            new_series = self.barda.post_series(data)
        except ApiError:
            questionary.print(
                f"Failed to create series for '{series_name}'. Exiting...", style=Styles.ERROR
            )
            exit(0)

        return new_series["id"]

    #########
    # Issue #
    #########
    def _create_issue(self, series_id: int, cv_issue: Issue):
        if cv_issue.cover_date:
            cover_date = self.fix_cover_date(cv_issue.cover_date)
        else:
            # If we don't have a date, let's bail.
            questionary.print(f"{cv_issue.name} doesn't have a cover date. Exiting...")
            exit(0)
        stories = self._fix_title_data(cv_issue.name)
        cleaned_desc = cleanup_html(cv_issue.description, True)
        character_lst = self._create_character_list(cv_issue.characters)
        team_lst = self._create_team_list(cv_issue.teams)
        arc_lst = self._create_arc_list(cv_issue.story_arcs)
        img = self._get_image(cv_issue.image.original, ImageType.Cover)
        data = {
            "series": series_id,
            "number": cv_issue.number,
            "name": stories,
            "cover_date": cover_date,
            "store_date": cv_issue.store_date,
            "desc": cleaned_desc,
            "image": img,
            "characters": character_lst,
            "teams": team_lst,
            "arcs": arc_lst,
        }
        try:
            resp = self.barda.post_issue(data)
        except ApiError:
            return None

        self._add_credits(resp["id"], cover_date, cv_issue.creators)

        return resp

    def run(self) -> None:
        if series := self._what_series():
            new_series_id = self._create_series(series)

            if i_list := self.simyan.issue_list(
                params={"filter": f"volume:{series.volume_id}", "sort": "cover_date:asc"}
            ):
                for i in i_list:
                    cv_issue = self.simyan.issue(i.issue_id)
                    new_issue = self._create_issue(new_series_id, cv_issue)
                    if new_issue is not None:
                        questionary.print(f"Added issue #{new_issue['number']}", Styles.SUCCESS)
                    else:
                        questionary.print(
                            f"Failed to create issue #{cv_issue.number}", style=Styles.ERROR
                        )
        else:
            print("Nothing found")
