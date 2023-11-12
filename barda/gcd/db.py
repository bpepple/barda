import mysql.connector
import questionary
from mysql.connector.errors import DatabaseError

from barda.styles import Styles


class DB:
    def __init__(self) -> None:
        self.db = self._get_db()
        self.cursor = self.db.cursor()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.cursor.close()

    @staticmethod
    def _get_db():
        try:
            return mysql.connector.connect(
                host="frodo",
                user="bpepple",
                passwd="123456",
                database="gcd",
            )
        except DatabaseError as e:
            questionary.print(f"Database Error: {e}", style=Styles.ERROR)
            exit(0)

    def get_series_list(self, name: str):  # sourcery skip: class-extract-method
        q = (
            "SELECT id, name, year_began, issue_count, publishing_format "
            "from gcd_series WHERE country_id=225 AND name=%s "
            "AND NOT publishing_format='collected edition' "
            "AND NOT publishing_format='Collected Series'"
            "AND NOT publishing_format='collected editions' "
            "AND NOT publishing_format='coloring book' "
            "ORDER BY year_began ASC;"
        )
        self.cursor.execute(q, [name])
        return self.cursor.fetchall()

    def get_issues(self, series_id: int, issue_number: str):
        q = (
            "SELECT id, number, price, barcode, page_count, rating, indicia_publisher_id FROM "
            "gcd_issue WHERE series_id=%s AND number=%s"
            "AND NOT number LIKE '%Pre-Order%' "
            "AND variant_of_id IS NULL;"
        )
        self.cursor.execute(q, [series_id, issue_number])
        return self.cursor.fetchall()

    def get_stories(self, issue_id: int):
        q = "SELECT title from gcd_story WHERE type_id=19 AND issue_id=%s ORDER BY sequence_number;"
        self.cursor.execute(q, [issue_id])
        return self.cursor.fetchall()

    def get_story_ids(self, issue_id: int) -> list[any]:
        """Return a list of story id's for the issue."""
        q = "SELECT id from gcd_story WHERE type_id=19 AND issue_id=%s ORDER BY id;"
        self.cursor.execute(q, [issue_id])
        return self.cursor.fetchall()

    def get_reprints_ids(self, story_id: int) -> list[any]:
        """Returns a list of reprint issue id's for the story."""
        q = "SELECT DISTINCT target_issue_id FROM gcd_reprint WHERE origin_id=%s;"
        self.cursor.execute(q, [story_id])
        return self.cursor.fetchall()

    def get_reprint_issue(self, issue_id: int) -> tuple[str | None, int | None, int | None]:
        q = "SELECT series_id, number FROM gcd_issue WHERE id=%s;"
        self.cursor.execute(q, [issue_id])
        series_id, number = self.cursor.fetchone()
        # Check that number is all digits.
        if str(number).isdigit():
            number = int(number)
        else:
            return None, None, None
        q = "SELECT name, country_id, year_began FROM gcd_series WHERE id=%s AND country_id=225;"
        self.cursor.execute(q, [series_id])
        res = self.cursor.fetchone()
        if res is None:
            return None, None, None
        if res[0] is None:
            return None, None, None
        if res[1] != 225:
            return None, None, None
        # Verify year_began is all digits and if not return 0
        year_began = int(res[2]) if str(res[2]).isdigit() else 0

        return str(res[0]), number, year_began
