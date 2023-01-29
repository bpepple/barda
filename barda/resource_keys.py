"""
ConversionKeys module.

This module provides the following classes:

- ConversionKeys
"""
import sqlite3
from typing import Any


class ConversionKeys:
    """
    The ConversionKeys object to save Comic Vine and Metron ID's.

    Args:
        db_name (str): Path and database name to use.
    """

    def __init__(self, db_name: str = "barda.db") -> None:
        """Initialize a new ConversionKeys database."""
        self.con = sqlite3.connect(db_name)
        self.cur = self.con.cursor()
        self.cur.execute("CREATE TABLE IF NOT EXISTS conversions (resource, cv, metron)")

    def get(self, resource: int, cv: int) -> Any | None:
        """
        Retrieve Metron Resource ID.

        Args:
            resource (int): The Resource enum value.
            cv (int): The Comic Vine ID to search for.
        """
        self.cur.execute(
            "SELECT metron from conversions WHERE resource = ? AND cv = ?", (resource, cv)
        )
        return result[0] if (result := self.cur.fetchone()) else None

    def store(self, resource: int, cv: int, metron: int) -> None:
        """
        Save the Resource Conversion ID's.

        Args:
            resource (int): The Resource enum value.
            cv (int): The Comic Vine ID.
            metron (int): The Metron ID.
        """
        self.cur.execute(
            "INSERT INTO conversions(resource, cv, metron) VALUES(?,?,?)",
            (resource, cv, metron),
        )
        self.con.commit()
