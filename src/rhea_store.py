"""
Rhea DB store wrapper using the requests library.
"""

import csv
import io
import re

import requests


RHEA_ENDPOINT = "https://www.rhea-db.org/rhea/"


class RheaStore:
    """Wrapper for searching Rhea and retrieving reaction records."""

    def __init__(self, timeout: int = 20, limit: int = 1000):
        self.timeout = timeout
        self.limit = limit
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "semweb-prj-backend/1.0 (Python requests client)",
            }
        )

    @staticmethod
    def _parse_tsv(text: str) -> list[dict]:
        if not text.strip():
            return []
        return list(csv.DictReader(io.StringIO(text), delimiter="\t"))

    def _get_tsv(self, query: str, columns: str) -> list[dict]:
        params: dict[str, str | int] = {
            "query": query,
            "columns": columns,
            "format": "tsv",
            "limit": min(self.limit, 10),
        }
        response = self._session.get(
            RHEA_ENDPOINT,
            params=params,
            timeout=self.timeout,
        )

        if response.status_code >= 400:
            response.raise_for_status()

        return self._parse_tsv(response.text)

    @staticmethod
    def _column(row: dict, *possible_names: str) -> str:
        """Handle either column IDs or display-name headers."""
        for name in possible_names:
            value = row.get(name)
            if value:
                return value.strip()
        return ""

    @staticmethod
    def _participant_ids(value: str) -> set[str]:
        return {
            f"CHEBI:{number}" for number in re.findall(r"(?:CHEBI:)?(\d+)", value or "")
        }

    def search_reactions(self, chebi_id: str) -> list[dict]:
        """Return Rhea reactions containing the exact ChEBI participant."""
        match = re.fullmatch(r"(?:CHEBI:)?(\d+)", chebi_id.strip(), re.IGNORECASE)
        if not match:
            raise ValueError(f"Invalid ChEBI ID: {chebi_id!r}")

        rows = self._get_tsv(
            query=f"chebi:{match.group(1)}",
            columns="rhea-id,equation,chebi,chebi-id",
        )

        results = []
        for row in rows:
            participant_ids = self._participant_ids(
                self._column(row, "chebi-id", "ChEBI identifier")
            )

            reaction_id = self._column(row, "rhea-id", "Reaction identifier")
            if not reaction_id:
                continue

            results.append(
                {
                    "rhea_id": reaction_id,
                    "equation": self._column(row, "equation", "Equation"),
                    "participants": self._column(row, "chebi", "ChEBI name"),
                    "participant_chebi_ids": sorted(participant_ids),
                    "url": self._reaction_url(reaction_id),
                }
            )

        return results

    def get_reaction(self, rhea_id: str) -> dict | None:
        """Retrieve a Rhea record by its ID."""
        match = re.fullmatch(r"(?:RHEA:)?(\d+)", rhea_id.strip(), re.IGNORECASE)
        if not match:
            raise ValueError(f"Invalid Rhea ID: {rhea_id!r}")

        normalized_id = f"RHEA:{match.group(1)}"
        rows = self._get_tsv(
            query=f"rhea-id:{normalized_id}",
            columns="rhea-id,equation,chebi,chebi-id",
        )

        for row in rows:
            row_id = self._column(row, "rhea-id", "Reaction identifier")
            if row_id == normalized_id:
                participant_ids = self._participant_ids(
                    self._column(row, "chebi-id", "ChEBI identifier")
                )
                return {
                    "rhea_id": row_id,
                    "equation": self._column(row, "equation", "Equation"),
                    "participants": self._column(row, "chebi", "ChEBI name"),
                    "participant_chebi_ids": sorted(participant_ids),
                    "url": self._reaction_url(row_id),
                }

        return None

    @staticmethod
    def _reaction_url(rhea_id: str) -> str:
        number = rhea_id.removeprefix("RHEA:")
        return f"https://www.rhea-db.org/rhea/{number}"
