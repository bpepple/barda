"""
ResourceKeys module.

This module provides the following classes:

- ResourceKeys
"""

import sqlite3
from enum import Enum, unique
from typing import Any


@unique
class Resources(Enum):
    Character = 0
    Team = 1
    Arc = 2
    Creator = 3
    Issue = 4


class ResourceKeys:
    """
    The ResourceKeys object to save Comic Vine and Metron ID's.

    Args:
        db_name (str): Path and database name to use.
    """

    def __init__(self, db_name: str = "barda.db") -> None:
        """Initialize a new ResourceKeys database."""
        self.con = sqlite3.connect(db_name)
        self.cur = self.con.cursor()
        self.cur.execute("CREATE TABLE IF NOT EXISTS conversions (resource, cv, metron)")
        self.cur.execute("CREATE TABLE IF NOT EXISTS gcddb (resource, gcd, metron)")

    def get_gcd(self, resource: int, gcd: int) -> Any | None:
        """
        Retrieve Metron Resource ID from a GCD ID.

        Args:
            resource (int): The Resource enum value.
            gcd (int): The GCD ID to search for.
        """
        self.cur.execute("SELECT metron from gcddb WHERE resource = ? AND gcd = ?", (resource, gcd))
        return result[0] if (result := self.cur.fetchone()) else None

    def store_gcd(self, resource: int, gcd: int, metron: int) -> None:
        """
        Save the Resource Conversion ID's for GCD.

        Args:
            resource (int): The Resource enum value.
            gcd (int): The GCD ID.
            metron (int): The Metron ID.
        """
        self.cur.execute(
            "INSERT INTO gcddb(resource, gcd, metron) VALUES(?,?,?)",
            (resource, gcd, metron),
        )
        self.con.commit()

    def get_cv(self, resource: int, cv: int) -> Any | None:
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

    def store_cv(self, resource: int, cv: int, metron: int) -> None:
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

    def edit_cv(self, resource: int, cv: int, metron: int) -> None:
        """
        Update the Resource Conversion ID's.

        Args:
            resource (int): The Resource enum value.
            cv (int): The Comic Vine ID.
            metron (int): The Metron ID.
        """
        self.cur.execute(
            "UPDATE conversions SET metron = ? WHERE resource = ? AND cv = ?",
            (metron, resource, cv),
        )
        self.con.commit()

    def delete_cv(self, resource: int, cv: int) -> bool:
        """
        Delete a Comic Vine Resource key.

        Args:
            resource (int): The Resource enum value.
            cv (int): The Comic Vine ID.
        """
        self.cur.execute("DELETE FROM conversions WHERE resource = ? and cv = ?", (resource, cv))
        self.con.commit()
        return self.get_cv(resource, cv) is None
