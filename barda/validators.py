from prompt_toolkit.document import Document
from questionary import ValidationError, Validator


class YearValidator(Validator):
    def validate(self, document: Document) -> None:
        if not document.text.isnumeric():
            raise ValidationError(
                message="Value must be numeric", cursor_position=len(document.text)
            )
        if len(document.text) != 4:
            raise ValidationError(
                message="Year value must have a length of 4.", cursor_position=len(document.text)
            )
        return super().validate(document)


class NumberValidator(Validator):
    def validate(self, document: Document) -> None:
        if not document.text.isnumeric():
            raise ValidationError(
                message="Value must be numeric", cursor_position=len(document.text)
            )
        return super().validate(document)
