from prompt_toolkit.document import Document
from questionary import ValidationError, Validator


class YearValidator(Validator):
    def validate(self, document: Document) -> None:
        YEAR_LENGTH = 4
        if not document.text.isnumeric() or len(document.text) != YEAR_LENGTH:
            raise ValidationError(
                message=f"Value must be numeric and have a length of {YEAR_LENGTH}",
                cursor_position=len(document.text),
            )
        return super().validate(document)


class NumberValidator(Validator):
    def validate(self, document: Document) -> None:
        if not document.text.isnumeric():
            raise ValidationError(
                message="Value must be numeric", cursor_position=len(document.text)
            )
        return super().validate(document)
