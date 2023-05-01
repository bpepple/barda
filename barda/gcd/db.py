import mysql.connector
from mysql.connector.errors import DatabaseError


class DB:
    def __init__(self) -> None:
        self.db = self._get_db()
        self.cursor = self.db.cursor()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.cursor.close()

    def _get_db(self):
        try:
            return mysql.connector.connect(
                host="frodo",
                user="bpepple",
                passwd="123456",
                database="gcd",
            )
        except DatabaseError as e:
            print(f"Database Error: {e}")
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
