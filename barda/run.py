from darkseid.utils import get_recursive_filelist

from barda.settings import BardaSettings


class Runner:
    """Main runner"""

    def __init__(self, config: BardaSettings) -> None:
        self.config = config

    def run(self) -> None:
        if not self.config.path or not (
            file_list := get_recursive_filelist(self.config.path)  # type:ignore
        ):
            print("No files to process. Exiting.")
            exit(0)

        for i in file_list:
            print(i)
