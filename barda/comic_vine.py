import datetime
import uuid
from enum import Enum, unique
from pathlib import Path
from typing import List

import questionary
import requests
from mokkari import api as m_api
from mokkari.arc import ArcsList
from mokkari.character import CharactersList
from mokkari.publisher import PublishersList
from mokkari.series import SeriesTypeList
from mokkari.session import Session
from mokkari.team import TeamsList
from PIL import Image
from simyan.comicvine import Comicvine as CV
from simyan.comicvine import Issue, VolumeEntry
from simyan.schemas.generic_entries import GenericEntry
from simyan.sqlite_cache import SQLiteCache
from titlecase import titlecase

from barda.exceptions import ApiError
from barda.post_data import PostData
from barda.resource_keys import ConversionKeys
from barda.settings import BardaSettings
from barda.styles import Styles
from barda.utils import cleanup_html


@unique
class Resources(Enum):
    Character = 0
    Team = 1
    Arc = 2
    Creator = 3


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
        self.conversions = ConversionKeys(str(config.conversions))

    @staticmethod
    def fix_cover_date(orig_date: datetime.date) -> datetime.date:
        if orig_date.day != 1:
            return datetime.date(orig_date.year, orig_date.month, 1)
        else:
            return orig_date

    @staticmethod
    def _resize_img(img: Path) -> None:
        width = 600
        height = 923
        i = Image.open(img)
        i = i.resize((width, height), Image.Resampling.LANCZOS)
        i.save(img)

    def _get_image(self, url: str):
        receive = requests.get(url)
        cv = Path(url)
        extension = cv.suffix
        new_fn = f"{uuid.uuid4().hex}{extension}"
        img_file = Path("/tmp") / new_fn
        img_file.write_bytes(receive.content)
        self._resize_img(img_file)
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

    # Handle Arcs
    def _create_arc(self, cv_id: int) -> int:
        cv_data = self.simyan.story_arc(cv_id)
        questionary.print(
            f"Story Arc '{cv_data.name}' needs to be created on Metron.", style=Styles.TITLE
        )
        name = (
            cv_data.name
            if questionary.confirm(f"Is '{cv_data.name}' the correct name?").ask()
            else questionary.text("What should be the story arc name be?").ask()
        )
        desc = questionary.text("What should be the description for this story arc?").ask()
        img = self._get_image(cv_data.image.original)
        data = {"name": name, "desc": desc, "image": str(img)}
        resp = self.barda.post_arc(data)
        self.conversions.store(Resources.Arc.value, cv_data.story_arc_id, resp["id"])
        questionary.print(
            f"Add '{name}' to {Resources.Arc.name} conversions", style=Styles.SUCCESS
        )
        return resp["id"]

    def _choose_arc(self, arc: GenericEntry) -> int | None:
        if arc.name:
            arc_lst: ArcsList = self.mokkari.arcs_list(params={"name": arc.name})
            if len(arc_lst) < 1:
                return None
            choices = []
            for i in arc_lst:
                choice = questionary.Choice(title=i.name, value=i.id)
                choices.append(choice)
            choices.append(questionary.Choice(title="None", value=""))
            if metron_id := questionary.select(
                f"What story arc should be added for '{arc.name}'?", choices=choices
            ).ask():
                self.conversions.store(Resources.Arc.value, arc.id_, metron_id)
                questionary.print(
                    f"Added '{arc.name}' to {Resources.Arc.name}  conversions",
                    style=Styles.SUCCESS,
                )
                return metron_id
            else:
                return None

    def _search_for_arc(self, arc: GenericEntry) -> int:
        metron_id = self._choose_arc(arc) if arc.name else None
        if metron_id is not None:
            return metron_id
        else:
            metron_id = self._create_arc(arc.id_)

        return metron_id

    def _create_arc_list(self, arcs: List[GenericEntry]) -> List[int]:
        arc_lst = []
        for i in arcs:
            metron_id = self.conversions.get(Resources.Arc.value, i.id_)
            if metron_id is None:
                metron_id = self._search_for_arc(i)
            arc_lst.append(metron_id)
        return arc_lst

    # Handle Teams
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
        data = {"name": name, "desc": desc, "image": str(img), "creators": []}
        resp = self.barda.post_team(data)
        self.conversions.store(Resources.Team.value, cv_data.team_id, resp["id"])
        questionary.print(
            f"Added '{name}' to {Resources.Team.name}  conversions", style=Styles.SUCCESS
        )
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
                self.conversions.store(Resources.Team.value, team.id_, metron_id)
                questionary.print(
                    f"Added '{team.name}' to {Resources.Team.name}  conversions",
                    style=Styles.SUCCESS,
                )
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
            metron_id = self.conversions.get(Resources.Team.value, t.id_)
            if metron_id is None:
                metron_id = self._search_for_team(t)
            team_lst.append(metron_id)
        return team_lst

    # Handle Characters
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
        self.conversions.store(Resources.Character.value, cv_data.character_id, resp["id"])
        questionary.print(
            f"Added '{name}' to {Resources.Character.name} conversions.", style=Styles.SUCCESS
        )
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
                self.conversions.store(Resources.Character.value, character.id_, metron_id)
                questionary.print(
                    f"Added '{character.name}' to {Resources.Character.name} conversions.",
                    style=Styles.SUCCESS,
                )
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
            metron_id = self.conversions.get(Resources.Character.value, c.id_)
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
        img = self._get_image(cv_issue.image.original)
        data = {
            "series": series_id,
            "number": cv_issue.number,
            "name": stories,
            "cover_date": cover_date,
            "store_date": cv_issue.store_date,
            "desc": cleaned_desc,
            "image": str(img),
            "characters": character_lst,
            "teams": team_lst,
            "arcs": arc_lst,
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
                    questionary.print(f"Added issue #{new_issue['number']}", Styles.SUCCESS)
        else:
            print("Nothing found")
