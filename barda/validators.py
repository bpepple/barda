from prompt_toolkit.document import Document
from questionary import ValidationError, Validator


class YearValidator(Validator):
    def validate(self, document: Document) -> None:
        if len(document.text) != 4:
            raise ValidationError(
                message="Year value must have a length of 4.", cursor_position=len(document.text)
            )
        return super().validate(document)
