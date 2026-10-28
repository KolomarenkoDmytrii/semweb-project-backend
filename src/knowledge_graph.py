"""
Wikidata SPARQL store wrapper using the requests library.
"""

from collections.abc import Mapping

import re
import requests

WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"


class Row:
    """Row of returned SPARQL results"""

    def __init__(
        self,
        var_names: list[str],
        binding_dict: Mapping[str, Mapping[str, str]],
    ) -> None:
        self._values: dict[str, str | None] = {
            name: binding_dict[name].get("value") if name in binding_dict else None
            for name in var_names
        }

    def __getattr__(self, name: str) -> str | None:
        return self._values.get(name)

    def asdict(self) -> dict[str, str | None]:
        """Return SPARQL results row data as a dict."""
        return self._values.copy()


class WikidataStore:
    """Wrapper for executing SPARQL queries against the Wikidata endpoint using requests."""

    def __init__(self):
        self._label_cache = {}

    def query(self, query_str: str) -> list[Row]:
        """Send SPARQL query to Wikidata endpoint and return results."""
        headers = {
            "Accept": "application/sparql-results+json",
            "User-Agent": "ChemrofAPI/1.0 (Python requests client)",
        }
        params = {"query": query_str}

        response = requests.get(
            WIKIDATA_ENDPOINT, headers=headers, params=params, timeout=480
        )
        response.raise_for_status()

        data = response.json()
        variables = data.get("head", {}).get("vars", [])
        bindings = data.get("results", {}).get("bindings", [])

        rows = []
        for binding in bindings:
            rows.append(Row(variables, binding))
        return rows

    def get_label(self, entity_uri: str, language: str = "en") -> str | None:
        """Return an English label for a Wikidata entity URI."""
        match = re.fullmatch(
            r"https?://www\.wikidata\.org/entity/(Q\d+)",
            entity_uri or "",
        )
        if not match:
            return None

        entity_id = match.group(1)
        cache_key = (entity_id, language)
        if cache_key in self._label_cache:
            return self._label_cache[cache_key]

        query = f"""
        PREFIX wd: <http://www.wikidata.org/entity/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

        SELECT ?label WHERE {{
          wd:{entity_id} rdfs:label ?label .
          FILTER(LANG(?label) = "{language}")
        }}
        LIMIT 1
        """

        rows = self.query(query)
        label = rows[0].label if rows else None
        self._label_cache[cache_key] = label
        return label

    def search_entities(
        self,
        search: str,
        language: str = "en",
        limit: int = 10,
    ) -> list[dict]:
        """Search Wikidata items by name using its entity-search API."""
        params: dict[str, str | int] = {
            "action": "wbsearchentities",
            "search": search,
            "language": language,
            "uselang": language,
            "type": "item",
            "limit": limit,
            "format": "json",
        }

        response = requests.get(
            "https://www.wikidata.org/w/api.php",
            params=params,
            headers={
                "User-Agent": "semweb-prj-backend/1.0 (Python requests client)",
            },
            timeout=(5, 20),
        )
        response.raise_for_status()
        return response.json().get("search", [])
