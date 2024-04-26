import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GcdReprintIssue:
    """Object for tracking a GCD Reprint"""

    id_: int
    series: str | None = None
    number: int | None = None
    year_began: int | None = None
    collection: bool = False

    def __repr__(self):
        return f"{self.series} ({self.year_began}) #{self.number}"


class DB:
    def __init__(self) -> None:
        self.db: sqlite3.Connection = self._get_db()
        self.cursor: sqlite3.Cursor = self.db.cursor()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.cursor.close()

    @staticmethod
    def _get_db() -> sqlite3.Connection:
        gcd_fn = Path("/home/bpepple/.cache/barda/gcd.db")
        if not gcd_fn.exists():
            raise FileNotFoundError

        return sqlite3.connect(gcd_fn)

    def get_series_list(self, name: str) -> list[any]:  # sourcery skip: class-extract-method
        q = (
            "SELECT id, name, year_began, issue_count, publishing_format "
            "from gcd_series WHERE country_id=225 AND name=? COLLATE NOCASE "
            # "AND NOT publishing_format='collected edition' "
            # "AND NOT publishing_format='Collected Series'"
            # "AND NOT publishing_format='collected editions' "
            # "AND NOT publishing_format='coloring book' "
            "ORDER BY year_began ASC"
        )
        self.cursor.execute(
            q,
            [
                name,
            ],
        )
        return self.cursor.fetchall()

    def get_issues(self, series_id: int, issue_number: str):
        params = [series_id]
        if issue_number:
            q = (
                "SELECT id, number, price, barcode, page_count, rating, indicia_publisher_id FROM "
                "gcd_issue WHERE series_id=? AND number=? AND variant_of_id IS NULL"
            )
            params.append(issue_number)
        else:
            q = (
                "SELECT id, number, price, barcode, page_count, rating, indicia_publisher_id FROM "
                "gcd_issue WHERE series_id=? AND variant_of_id IS NULL"
            )
        self.cursor.execute(q, params)
        return self.cursor.fetchall()

    def get_stories(self, issue_id: int) -> list[any]:
        q = "SELECT title from gcd_story WHERE type_id=19 AND issue_id=? ORDER BY sequence_number"
        self.cursor.execute(
            q,
            [
                issue_id,
            ],
        )
        return self.cursor.fetchall()

    def get_story_ids(self, issue_id: int) -> list[any]:
        """Return a list of story id's for the issue."""
        q = "SELECT id from gcd_story WHERE type_id=19 AND issue_id=? ORDER BY id"
        self.cursor.execute(
            q,
            [
                issue_id,
            ],
        )
        return self.cursor.fetchall()

    def get_reprints_ids(self, story_id: int) -> list[any]:
        """Returns a list of reprint issue id's for the story."""
        q = "SELECT DISTINCT target_issue_id FROM gcd_reprint WHERE origin_id=?"
        self.cursor.execute(
            q,
            [
                story_id,
            ],
        )
        return self.cursor.fetchall()

    def get_reprint_issue(self, issue_id: int) -> GcdReprintIssue:
        q = "SELECT series_id, number FROM gcd_issue WHERE id=?"
        self.cursor.execute(
            q,
            [
                issue_id,
            ],
        )
        series_id, number = self.cursor.fetchone()
        # Check that number is all digits.
        if str(number).isdigit():
            number = int(number)
        else:
            return GcdReprintIssue(issue_id, None, None, None)
        q = "SELECT name, country_id, year_began, publication_type_id FROM gcd_series WHERE id=? AND country_id=225"
        self.cursor.execute(
            q,
            [
                series_id,
            ],
        )
        res = self.cursor.fetchone()
        if res is None:
            return GcdReprintIssue(issue_id, None, None, None)
        if res[0] is None:
            return GcdReprintIssue(issue_id, None, None, None)
        if res[1] != 225:
            return GcdReprintIssue(issue_id, None, None, None)
        # Verify year_began is all digits and if not return 0
        year_began = int(res[2]) if str(res[2]).isdigit() else 0
        pub_type = res[3]
        collection = False if pub_type is None or int(pub_type) != 1 else True

        return GcdReprintIssue(issue_id, str(res[0]), number, year_began, collection)
