from enum import Enum, auto, unique

import questionary

from barda.import_series import ImportSeries
from barda.locg import LeagueOfComicGeeks
from barda.marvel import MarvelNewReleases
from barda.resource_keys import ResourceKeys, Resources
from barda.settings import BardaSettings
from barda.styles import Styles
from barda.validators import NumberValidator


@unique
class TaskType(Enum):
    Import_Series = auto()
    Import_LOCG = auto()
    Update_Resource = auto()
    Delete_Resource = auto()
    Marvel_Releases = auto()


class Runner:
    """Main runner"""

    def __init__(self, config: BardaSettings) -> None:
        self.config = config

    @staticmethod
    def _select_resource() -> int:
        choices = []
        for i in Resources:
            choice = questionary.Choice(title=i.name, value=i.value)
            choices.append(choice)
        return int(questionary.select("What Resource do you want to edit?", choices=choices).ask())

    def _update_resource_key(self) -> None:
        resource = self._select_resource()
        cv_id = int(
            questionary.text(
                "What is the Comic Vine ID for the resource?", validate=NumberValidator
            ).ask()
        )
        metron_id = int(
            questionary.text(
                "What should the new value be for the Metron ID?", validate=NumberValidator
            ).ask()
        )
        conv = ResourceKeys(str(self.config.conversions))
        conv.edit(resource, cv_id, metron_id)
        questionary.print(f"Updated CV ID: {cv_id}", style=Styles.SUCCESS)

    def _delete_resource_key(self) -> None:
        resource = self._select_resource()
        cv_id = int(
            questionary.text(
                "What is the Comic Vine ID for the resource to be deleted?",
                validate=NumberValidator,
            ).ask()
        )
        conv = ResourceKeys(str(self.config.conversions))
        if conv.delete(resource, cv_id):
            questionary.print(f"Deleted CV ID: {cv_id}", style=Styles.SUCCESS)
        else:
            questionary.print(f"Failed to delete CV ID: {cv_id}", style=Styles.WARNING)

    @staticmethod
    def _what_task():
        choices = []
        for task in TaskType:
            choice = questionary.Choice(title=f"{task.name}", value=task.value)
            choices.append(choice)
        choices.append(questionary.Choice(title="Quit", value="q"))
        result = questionary.select("Choose what task you want to do", choices=choices).ask()

        if result != "q":
            return result

        questionary.print("Quiting...", style=Styles.SUCCESS)
        exit(0)

    def _has_cv_credentials(self) -> bool:
        return bool(self.config.cv_api_key)

    def _get_cv_credentials(self) -> bool:
        answers = questionary.form(
            cv_key=questionary.text("What is your Comic Vine API key?"),
            save=questionary.confirm("Would you like to save your credentials?"),
        ).ask()
        if answers["cv_key"]:
            self.config.cv_api_key = answers["cv_key"]
            if answers["save"]:
                self.config.save()
            return True
        return False

    def _has_metron_credentials(self) -> bool:
        return bool(self.config.metron_user and self.config.metron_password)

    def _get_metron_credentials(self) -> bool:
        answers = questionary.form(
            user=questionary.text("What is your Metron username?"),
            passwd=questionary.text("What is your Metron password?"),
            save=questionary.confirm("Would you like to save your credentials?"),
        ).ask()
        if answers["user"] and answers["passwd"]:
            self.config.metron_user = answers["user"]
            self.config.metron_password = answers["passwd"]
            if answers["save"]:
                self.config.save()
            return True
        return False

    def _has_marvel_credentials(self) -> bool:
        return bool(self.config.marvel_public_key and self.config.marvel_private_key)

    def _get_marvel_credentials(self) -> bool:
        answers = questionary.form(
            public=questionary.text("What is your public key for the Marvel API?"),
            private=questionary.text("What is your private key for the Marvel API?"),
            save=questionary.confirm("Would you like to save your Marvel credenttials?"),
        ).ask()
        if answers["public"] and answers["private"]:
            self.config.marvel_public_key = answers["public"]
            self.config.marvel_private_key = answers["private"]
            if answers["save"]:
                self.config.save()
            return True
        return False

    def run(self) -> None:
        if not self._has_metron_credentials() and not self._get_metron_credentials():
            questionary.print("No Metron credentials provided. Exiting...")
            exit(0)
        if not self._has_cv_credentials() and not self._get_cv_credentials():
            questionary.print("No Comic Vine credentials were provided. Exiting...")
            exit(0)
        if not self._has_marvel_credentials() and not self._get_marvel_credentials():
            questionary.print("No Marvel credentials provided. Exiting...")
            exit(0)

        task = self._what_task()
        match task:
            case TaskType.Import_Series.value:
                if self.config.cv_api_key:
                    with ImportSeries(self.config) as importer_obj:
                        importer_obj.run()
            case TaskType.Update_Resource.value:
                self._update_resource_key()
            case TaskType.Delete_Resource.value:
                self._delete_resource_key()
            case TaskType.Marvel_Releases.value:
                with MarvelNewReleases(self.config) as marvel_obj:
                    marvel_obj.run()
            case TaskType.Import_LOCG.value:
                with LeagueOfComicGeeks(self.config) as locg:
                    locg.run()
            case _:
                questionary.print("Invalid choice.", style=Styles.ERROR)
