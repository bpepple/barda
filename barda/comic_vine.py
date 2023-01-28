import json
from enum import Enum, unique
from pathlib import Path
from typing import List

import questionary
import requests
from mokkari import api as m_api
from mokkari.character import CharactersList
from mokkari.publisher import PublishersList
from mokkari.series import SeriesTypeList
from mokkari.session import Session
from mokkari.team import TeamsList
from simyan.comicvine import Comicvine as CV
from simyan.comicvine import Issue, VolumeEntry
from simyan.schemas.generic_entries import GenericEntry
from simyan.sqlite_cache import SQLiteCache
from titlecase import titlecase

from barda.exceptions import ApiError
from barda.post_data import PostData
from barda.settings import BardaSettings, ResourceKeys
from barda.styles import Styles
from barda.utils import cleanup_html


@unique
class CV_Creator_ID(Enum):
    Alan_Fine = 56587
    Dan_Buckley = 41596
    Joe_Quesada = 1537
    CB_Cebulski = 43193
    Axel_Alonso = 23115


class ComicVine:
    def __init__(self, config: BardaSettings) -> None:
        self.config = config
        cache = SQLiteCache(config.cv_cache, 1) if config.cv_cache else None
        # Christ! What a horrible design...
        self.simyan = CV(api_key=config.cv_api_key, cache=cache)  # type: ignore
        self.mokkari: Session = m_api(config.metron_user, config.metron_password)
        self.barda = PostData(config.metron_user, config.metron_password)

    @staticmethod
    def _get_image(url: str):
        receive = requests.get(url)
        cv = Path(url)
        img_file = Path("/tmp") / cv.name
        img_file.write_bytes(receive.content)
        return img_file

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

    # Handle Teams
    def _user_correct_team(self, team: GenericEntry) -> int | None:
        if self.config.teams:
            for t in self.config.teams:
                if not isinstance(t["cv"], int):
                    t["cv"] = int(t["cv"])
                if team.id_ == t["cv"]:
                    if not isinstance(t["metron"], int):
                        t["metron"] = int(t["metron"])
                    return t["metron"]
        return None

    def _add_team_to_keyfile(self, cv_id: int, metron_id: int, name: str) -> None:
        new_value: ResourceKeys = {"cv": cv_id, "metron": metron_id}
        if self.config.teams:
            self.config.teams.append(new_value)
            self.config.teams = sorted(self.config.teams, key=lambda k: k["cv"])
            self.config.teams_file.write_text(json.dumps(self.config.teams, indent=4))
            questionary.print(f"Added '{name}' to team  keyfile", style=Styles.SUCCESS)

    def _create_team(self, cv_id: int) -> int:
        cv_data = self.simyan.team(cv_id)
        questionary.print(
            f"Team '{cv_data.name}' needs to be created on Metron",
            style=Styles.TITLE,
        )
        name = (
            cv_data.name
            if questionary.confirm(f"Is '{cv_data.name}' the correct name?").ask()
            else questionary.text("What should the team name be?").ask()
        )
        desc = questionary.text("What should be the description for this team?").ask()
        img = self._get_image(cv_data.image.original)
        data = {"name": name, "desc": desc, "image": img, "creators": []}
        resp = self.barda.post_team(data)
        self._add_team_to_keyfile(cv_data.team_id, resp["id"], resp["name"])
        return resp["id"]

    def _choose_team(self, team: GenericEntry) -> int | None:
        if team.name:
            t_lst: TeamsList = self.mokkari.teams_list(params={"name": team.name})
            if len(t_lst) < 1:
                return None
            choices = []
            for i in t_lst:
                choice = questionary.Choice(title=i.name, value=i.id)
                choices.append(choice)
            choices.append(questionary.Choice(title="None", value=""))
            if metron_id := questionary.select(
                f"What team should be added for '{team.name}'?", choices=choices
            ).ask():
                self._add_team_to_keyfile(team.id_, metron_id, team.name)
                return metron_id
            else:
                return None

    def _search_for_team(self, team: GenericEntry) -> int:
        metron_id = self._choose_team(team) if team.name else None
        if metron_id is not None:
            return metron_id
        else:
            metron_id = self._create_team(team.id_)

        return metron_id

    def _create_team_list(self, teams: List[GenericEntry]) -> List[int]:
        team_lst = []
        for t in teams:
            metron_id = self._user_correct_team(t)
            if metron_id is None:
                metron_id = self._search_for_team(t)
            team_lst.append(metron_id)
        return team_lst

    # Handle Characters
    def _use_correct_character(self, character: GenericEntry) -> int | None:
        if self.config.characters:
            for c in self.config.characters:
                if not isinstance(c["cv"], int):
                    c["cv"] = int(c["cv"])
                if character.id_ == c["cv"]:
                    if not isinstance(c["metron"], int):
                        c["metron"] = int(c["metron"])
                    return c["metron"]

        return None

    def _add_character_to_keyfile(self, cv_id: int, metron_id: int, name: str) -> None:
        new_value: ResourceKeys = {"cv": cv_id, "metron": metron_id}
        if self.config.characters:
            self.config.characters.append(new_value)
            self.config.characters = sorted(self.config.characters, key=lambda k: k["cv"])
            self.config.characters_file.write_text(
                json.dumps(self.config.characters, indent=4)
            )
            questionary.print(f"Added '{name}' to character keyfile", style=Styles.SUCCESS)

    def _create_character(self, cv_id: int) -> int:
        cv_data = self.simyan.character(cv_id)
        questionary.print(
            f"Character '{cv_data.name}' needs to be created on Metron",
            style=Styles.TITLE,
        )
        name = (
            cv_data.name
            if questionary.confirm(f"Is '{cv_data.name}' the correct name?").ask()
            else questionary.text("What should the characters name be?").ask()
        )
        desc = questionary.text(
            "What description do you want to have for this character?"
        ).ask()
        image = self._get_image(cv_data.image.original)
        teams_lst = self._create_team_list(cv_data.teams)
        data = {
            "name": name,
            "alias": [],
            "desc": desc,
            "image": str(image),
            "teams": teams_lst,
            "creators": [],
        }
        resp = self.barda.post_character(data)
        self._add_character_to_keyfile(cv_data.character_id, resp["id"], resp["name"])
        return resp["id"]

    def _choose_character(self, character: GenericEntry) -> int | None:
        if character.name:
            c_lst: CharactersList = self.mokkari.characters_list(
                params={"name": character.name}
            )
            if len(c_lst) < 1:
                return None
            choices = []
            for i in c_lst:
                choice = questionary.Choice(title=i.name, value=i.id)
                choices.append(choice)
            choices.append(questionary.Choice(title="None", value=""))
            if metron_id := questionary.select(
                f"What character should be added for '{character.name}'?", choices=choices
            ).ask():
                self._add_character_to_keyfile(character.id_, metron_id, character.name)
                return metron_id
            else:
                return None

    def _search_for_character(self, character: GenericEntry) -> int:
        metron_id = self._choose_character(character) if character.name else None
        if metron_id is not None:
            return metron_id
        else:
            metron_id = self._create_character(character.id_)

        return metron_id

    def _create_character_list(self, characters: List[GenericEntry]) -> List[int]:
        character_lst = []
        for c in characters:
            metron_id = self._use_correct_character(c)
            if metron_id is None:
                metron_id = self._search_for_character(c)
            character_lst.append(metron_id)
        return character_lst

    # Series Type
    def _choose_series_type(self):  # sourcery skip: class-extract-method
        st_lst: SeriesTypeList = self.mokkari.series_type_list()
        choices = []
        for s in st_lst:
            choice = questionary.Choice(title=s.name, value=s.id)
            choices.append(choice)
        return questionary.select("What type of series is this?", choices=choices).ask()

    # Publisher
    def _choose_publisher(self):
        pub_lst: PublishersList = self.mokkari.publishers_list()
        choices = []
        for p in pub_lst:
            choice = questionary.Choice(title=p.name, value=p.id)
            choices.append(choice)
        # TODO: Provide option to add a Publisher
        return questionary.select(
            "Which publisher is this series from?", choices=choices
        ).ask()

    # Series
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
            choice = questionary.Choice(title=f"{s.name} ({s.start_year})", value=s)
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
        volume = int(
            questionary.text(f"What is the volume number for '{display_name}'?").ask()
        )
        publisher_id = self._choose_publisher()
        series_type_id = self._choose_series_type()
        year_began = (
            cv_series.start_year
            if questionary.confirm(
                f"Is '{cv_series.start_year}' the correct year that this series began?"
            ).ask()
            else int(questionary.text("What begin year should be used for this series?").ask())
        )
        if series_type_id == 2:
            year_end = int(questionary.text("What year did this series end in?").ask())
        else:
            year_end = None
        desc = questionary.text(
            f"Do you want to add a series summary for '{display_name}'?"
        ).ask()

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
        except ApiError as e:
            questionary.print(f"API Error: {e}", style=Styles.ERROR)
            exit(0)

        return new_series["id"]

    # Issue
    def _create_issue(self, series_id: int, cv_issue: Issue):
        stories = self._fix_title_data(cv_issue.name)
        cleaned_desc = cleanup_html(cv_issue.description, True)
        character_lst = self._create_character_list(cv_issue.characters)
        team_lst = self._create_team_list(cv_issue.teams)
        img = self._get_image(cv_issue.image.original)
        data = {
            "series": series_id,
            "number": cv_issue.number,
            "name": stories,
            "cover_date": cv_issue.cover_date,
            "store_date": cv_issue.store_date,
            "desc": cleaned_desc,
            "image": str(img),
            "characters": character_lst,
            "teams": team_lst,
        }
        return self.barda.post_issue(data)

    def run(self) -> None:
        if series := self._what_series():
            new_series_id = self._create_series(series)

            if i_list := self.simyan.issue_list(
                params={"filter": f"volume:{series.volume_id}"}
            ):
                for i in i_list:
                    cv_issue = self.simyan.issue(i.issue_id)
                    new_issue = self._create_issue(new_series_id, cv_issue)
                    questionary.print(f"Added issue #{new_issue['number']}", Styles.SUCCESS)  # type: ignore

        else:
            print("Nothing found")
