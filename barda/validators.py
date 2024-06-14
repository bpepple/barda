from datetime import date

from prompt_toolkit.document import Document
from questionary import ValidationError, Validator


class YearValidator(Validator):
    def validate(self, document: Document) -> None:
        year_length = 4
        if not document.text.isnumeric() or len(document.text) != year_length:
            raise ValidationError(
                message=f"Value must be numeric and have a length of {year_length}",
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


class DateValidator(Validator):
    def validate(self, document: Document) -> None:
        try:
            date.fromisoformat(document.text)
        except ValueError as e:
            raise ValidationError(
                message=f"Invalid date: {e}", cursor_position=len(document.text)
            ) from e
