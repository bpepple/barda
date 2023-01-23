from enum import Enum, auto, unique

import questionary

from barda.settings import BardaSettings


@unique
class SourceType(Enum):
    ComicVine = auto()
    LoCG = auto()


class Runner:
    """Main runner"""

    def __init__(self, config: BardaSettings) -> None:
        self.config = config

    @staticmethod
    def _what_task():
        choices = []
        for source in SourceType:
            choice = questionary.Choice(title=f"{source.name}", value=source.value)
            choices.append(choice)
        choices.append(questionary.Choice(title="Quit", value="q"))
        result = questionary.select("Choose what task you want to do", choices=choices).ask()

        if result != "q":
            return result

        print("Quiting...")
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

    def run(self) -> None:
        if not self._has_metron_credentials() and not self._get_metron_credentials():
            questionary.print("No Metron credentials provided. Exiting...")
            exit(0)
        if not self._has_cv_credentials() and not self._get_cv_credentials():
            questionary.print("No Comic Vine credentials were provided. Exiting...")
            exit(0)

        task = self._what_task()
        match task:
            case SourceType.ComicVine.value:
                print("Going to import from Comic Vine...")
            case SourceType.LoCG.value:
                print("Going to import from League of Comic Geeks...")
            case _:
                print("Invalid choice.")
