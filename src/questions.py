"""
questions.py

Wikidata-backed answers for chemical-substance questions.

Assumptions:
- get_knowledge_graph_store().query(query) accepts SPARQL and returns
  RDFLib-style rows.
- Labels are matched exactly in English. A label may identify multiple
  Wikidata items, so results include entity URIs.
"""

import re
import json
from urllib.parse import urlsplit

from requests import HTTPError

from .knowledge_graph import WikidataStore
from .rhea_store import RheaStore


class QuestionService:
    """Coordinate Wikidata entity resolution and Rhea reaction searches."""

    LIMIT = 30
    CHEMICAL_CLASS_QIDS = ("Q11173", "Q79529", "Q11344", "Q169336")

    def __init__(
        self,
        wikidata_store: WikidataStore,
        rhea_store: RheaStore,
    ):
        self.wikidata = wikidata_store
        self.rhea = rhea_store

    def _chebi_ids_for_qid(self, qid: str) -> list[str]:
        if not re.fullmatch(r"Q\d+", qid):
            raise ValueError(f"Invalid Wikidata QID: {qid!r}")

        query = f"""
        PREFIX wd: <http://www.wikidata.org/entity/>
        PREFIX wdt: <http://www.wikidata.org/prop/direct/>

        SELECT DISTINCT ?chebi WHERE {{
          wd:{qid} wdt:P683 ?chebi .
        }}
        """
        rows = self.wikidata.query(query)

        ids = set()
        for row in rows:
            value = row.chebi
            if value:
                match = re.fullmatch(r"(?:CHEBI:)?(\d+)", str(value).strip())
                if match:
                    ids.add(f"CHEBI:{match.group(1)}")

        return sorted(ids)

    def _run_question(self, query: str) -> list[dict]:
        try:
            rows = self._query(query)
            return [{key: self._value(row, key) for key in row} for row in rows]
        except HTTPError as exc:
            return [{"error": f"Query failed: {exc}"}]

    def _query(self, query_str: str) -> list[dict]:
        """Execute SPARQL and convert store rows to dictionaries."""
        return [row.asdict() for row in self.wikidata.query(query_str)]

    @staticmethod
    def _label_value(value: str) -> str:
        return f"{json.dumps(value)}@en"

    @staticmethod
    def _value(row: dict, key: str):
        """Convert an RDF value to a string, or return None."""
        value = row.get(key)
        return str(value) if value is not None else None

    @staticmethod
    def _row_value(row, key: str):
        if hasattr(row, key):
            return getattr(row, key)
        if hasattr(row, "asdict"):
            return row.asdict().get(key)
        if isinstance(row, dict):
            return row.get(key)
        return None

    def _chemical_candidate_info(self, qids: list[str]) -> dict[str, dict]:
        """Return chemical-class, mixture-class, and identifier information."""
        qids = list(
            dict.fromkeys(
                qid.upper()
                for qid in qids
                if isinstance(qid, str) and re.fullmatch(r"Q\d+", qid, re.IGNORECASE)
            )
        )
        if not qids:
            return {}

        entity_values = " ".join(f"wd:{qid}" for qid in qids)
        class_values = " ".join(f"wd:{qid}" for qid in self.CHEMICAL_CLASS_QIDS)

        # OPTIONAL {{
        #                 ?entity wdt:P31/wdt:P279* ?chemical_class .
        #                 VALUES ?chemical_class {{ {class_values} }}
        #             }}
        query = f"""
        PREFIX wd: <http://www.wikidata.org/entity/>
        PREFIX wdt: <http://www.wikidata.org/prop/direct/>

        SELECT DISTINCT ?entity ?chemical_class
                    ?has_chebi ?has_pubchem ?has_cas ?has_formula
        WHERE {{
            VALUES ?entity {{ {entity_values} }}

            OPTIONAL {{
                ?entity (wdt:P31|wdt:P279)/wdt:P279* ?chemical_class .
                VALUES ?chemical_class {{ {class_values} }}
            }}

            BIND(EXISTS {{ ?entity wdt:P683 ?chebi }}
                AS ?has_chebi)
            BIND(EXISTS {{ ?entity wdt:P662 ?pubchem }}
                AS ?has_pubchem)
            BIND(EXISTS {{ ?entity wdt:P231 ?cas }}
                AS ?has_cas)
            BIND(EXISTS {{ ?entity wdt:P274 ?formula }}
                AS ?has_formula)
        }}
        """

        results: dict[str, dict] = {}

        for row in self.wikidata.query(query):
            entity_uri = self._row_value(row, "entity")
            match = re.search(r"/(Q\d+)$", str(entity_uri or ""))
            if not match:
                continue

            qid = match.group(1)
            info = results.setdefault(
                qid,
                {
                    "chemical_classes": set(),
                    "is_mixture": False,
                    "has_chebi": False,
                    "has_other_chemical_identifier": False,
                },
            )

            chemical_class = self._row_value(row, "chemical_class")
            class_match = re.search(r"/(Q\d+)$", str(chemical_class or ""))
            if class_match:
                info["chemical_classes"].add(class_match.group(1))

            info["has_chebi"] |= (
                str(self._row_value(row, "has_chebi")).lower() == "true"
            )
            info["has_other_chemical_identifier"] |= any(
                str(self._row_value(row, key)).lower() == "true"
                for key in ("has_pubchem", "has_cas", "has_formula")
            )

        # Keep only recognized chemical classes or mixtures.
        return {
            qid: info
            for qid, info in results.items()
            if info["chemical_classes"] or info["is_mixture"]
        }
        # return results

    def _resolve_entity(self, value: str) -> str:
        """Resolve a QID, Wikidata URL, or label to a chemical QID."""
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Entity must be a non-empty QID, Wikidata URL, or label")

        value = value.strip()

        # Explicit identifiers are authoritative: do not replace them with a search hit.
        if re.fullmatch(r"Q\d+", value, flags=re.IGNORECASE):
            return value.upper()

        if value.lower().startswith(("http://", "https://")):
            parsed = urlsplit(value)
            if (parsed.hostname or "").lower() not in {
                "www.wikidata.org",
                "wikidata.org",
            }:
                raise ValueError("URL must be a Wikidata URL")

            match = re.fullmatch(
                r"/(?:entity|wiki)/(Q\d+)/?",
                parsed.path,
                flags=re.IGNORECASE,
            )
            if not match:
                raise ValueError(f"Could not find a QID in Wikidata URL: {value!r}")

            return match.group(1).upper()

        search_results = self.wikidata.search_entities(
            value,
            language="en",
            limit=50,
        )

        # Keep Wikidata's search order for the fallback.
        candidates = []
        seen_qids = set()

        for item in search_results:
            qid = item.get("id")
            if not qid or not re.fullmatch(r"Q\d+", qid):
                continue
            if qid in seen_qids:
                continue

            seen_qids.add(qid)
            candidates.append(
                {
                    "qid": qid,
                    "label": item.get("label", ""),
                }
            )

        if not candidates:
            raise ValueError(f"No Wikidata item found for {value!r}")

        info_by_qid = self._chemical_candidate_info(
            [candidate["qid"] for candidate in candidates]
        )

        chemical_candidates = [
            candidate for candidate in candidates if candidate["qid"] in info_by_qid
        ]

        if not chemical_candidates:
            raise ValueError(
                f"No chemical Wikidata entity found for {value!r}. "
                "Pass a chemical QID or Wikidata URL if you know the intended item."
            )

        exact_label_candidates = [
            candidate
            for candidate in chemical_candidates
            if candidate["label"].strip().casefold() == value.casefold()
        ]

        if exact_label_candidates:
            # Prefer exact-label chemical items, especially those with a ChEBI ID
            # that can be used for Rhea lookups.
            selected = max(
                exact_label_candidates,
                key=lambda candidate: (
                    info_by_qid[candidate["qid"]]["has_chebi"],
                    info_by_qid[candidate["qid"]]["has_other_chemical_identifier"],
                    -candidates.index(candidate),
                ),
            )
        else:
            # If no exact-label chemical hit exists, use the first chemical result
            # in Wikidata search order.
            selected = chemical_candidates[0]

        return selected["qid"]

    # DONE
    def answer_reaction(self, substance: str, other_substance: str) -> dict:
        """Get information about reaction between two substances."""
        qid_a = self._resolve_entity(substance)
        qid_b = self._resolve_entity(other_substance)

        chebi_a = self._chebi_ids_for_qid(qid_a)
        chebi_b = self._chebi_ids_for_qid(qid_b)

        reactions_a = {}
        for chebi_id in chebi_a:
            for reaction in self.rhea.search_reactions(chebi_id):
                reactions_a[reaction["rhea_id"]] = reaction

        reactions_b = {}
        for chebi_id in chebi_b:
            for reaction in self.rhea.search_reactions(chebi_id):
                reactions_b[reaction["rhea_id"]] = reaction

        shared_ids = reactions_a.keys() & reactions_b.keys()
        shared_reactions = [reactions_a[rhea_id] for rhea_id in sorted(shared_ids)]

        if shared_reactions:
            status = "shared_reactions_found"
        elif not reactions_a or not reactions_b:
            status = "no_rhea_reactions_for_one_or_both"
        else:
            status = "no_shared_reactions"

        return {
            "question_id": "reaction",
            "query_substances": [substance, other_substance],
            "resolved_qids": [qid_a, qid_b],
            "status": status,
            "reactions": shared_reactions,
            "individual_reactions": [
                {
                    "input": substance,
                    "qid": qid_a,
                    "reactions": list(reactions_a.values()),
                },
                {
                    "input": other_substance,
                    "qid": qid_b,
                    "reactions": list(reactions_b.values()),
                },
            ],
            "message": (
                "Shared records mean both substances are listed as participants "
                "in the same Rhea reaction; they do not establish that simply "
                "mixing the substances causes a reaction."
            ),
        }

    # DONE
    def answer_chemical_properties(self, substance: str) -> dict:
        """
        Return available identifiers, structural data, and selected quantities.
        Accepts a label, QID, or Wikidata /wiki/Q... or /entity/Q... URL.
        """
        value = substance.strip()

        match = re.fullmatch(
            r"(?:https?://www\.wikidata\.org/(?:wiki|entity)/)?(Q\d+)",
            value,
        )
        if match:
            entity_selector = f"VALUES ?entity {{ wd:{match.group(1)} }}"
        else:
            entity_selector = f"?entity rdfs:label {self._label_value(value)} ."

        query = f"""
        PREFIX wd: <http://www.wikidata.org/entity/>
        PREFIX wdt: <http://www.wikidata.org/prop/direct/>
        PREFIX p: <http://www.wikidata.org/prop/>
        PREFIX ps: <http://www.wikidata.org/prop/statement/>
        PREFIX psv: <http://www.wikidata.org/prop/statement/value/>
        PREFIX wikibase: <http://wikiba.se/ontology#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

        SELECT DISTINCT ?entity ?property ?value ?unit WHERE {{
        {entity_selector}

        {{
            VALUES (?predicate ?property) {{
            (wdt:P274 "chemical_formula")
            (wdt:P233 "canonical_smiles")
            (wdt:P234 "inchi")
            (wdt:P235 "inchi_key")
            (wdt:P231 "cas_registry_number")
            (wdt:P232 "ec_number")
            (wdt:P662 "pubchem_cid")
            (wdt:P683 "chebi_id")
            }}
            ?entity ?predicate ?value .
        }}
        UNION
        {{
            VALUES (?statementPredicate ?valuePredicate ?quantityPredicate ?property) {{
            (p:P2067 ps:P2067 psv:P2067 "mass")
            (p:P2054 ps:P2054 psv:P2054 "density")
            (p:P2101 ps:P2101 psv:P2101 "melting_point")
            (p:P2102 ps:P2102 psv:P2102 "boiling_point")
            }}

            ?entity ?statementPredicate ?statement .
            ?statement ?valuePredicate ?rawValue ;
                    ?quantityPredicate ?quantityNode .
            ?quantityNode wikibase:quantityAmount ?value ;
                        wikibase:quantityUnit ?unit .
        }}
        }}
        LIMIT {self.LIMIT}
        """

        properties = self._run_question(query)

        # Resolve unit URIs separately; get_label() can cache repeated lookups.
        for item in properties:
            unit_uri = item.get("unit")
            if unit_uri:
                item["unit_name"] = self.wikidata.get_label(unit_uri)

        return {
            "question_id": "chemical-properties",
            "substance": substance,
            "properties": properties,
        }

    # DONE
    def answer_substance_kind(self, substance: str) -> dict:
        """Return direct instance-of and subclass-of classifications."""
        value = substance.strip()

        # Accept QIDs, /wiki/Q... URLs, and /entity/Q... URLs.
        match = re.fullmatch(
            r"(?:https?://www\.wikidata\.org/(?:wiki|entity)/)?(Q\d+)",
            value,
        )

        if match:
            entity_selector = f"VALUES ?entity {{ wd:{match.group(1)} }}"
        else:
            label = self._label_value(value)
            entity_selector = f"?entity rdfs:label {label} ."

        query = f"""
        PREFIX wd: <http://www.wikidata.org/entity/>
        PREFIX wdt: <http://www.wikidata.org/prop/direct/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX wikibase: <http://wikiba.se/ontology#>
        PREFIX bd: <http://www.bigdata.com/rdf#>

        SELECT DISTINCT ?entity ?relation ?type ?typeLabel WHERE {{
        {entity_selector}

        {{
            ?entity wdt:P31 ?type .
            BIND("instance of" AS ?relation)
        }}
        UNION
        {{
            ?entity wdt:P279 ?type .
            BIND("subclass of" AS ?relation)
        }}

        SERVICE wikibase:label {{
            bd:serviceParam wikibase:language "en" .
        }}
        }}
        LIMIT {self.LIMIT}
        """

        return {
            "question_id": "substance-kind",
            "substance": substance,
            "kinds": self._run_question(query),
        }

    # DONE
    def answer_physical_properties(self, substance: str) -> dict:
        """
        Retrieve selected physical-property quantities:
        P2102 boiling point, P2101 melting point, P2054 density.

        Return the stored quantity and unit rather than assuming Celsius
        or grams per millilitre.
        """
        label = self._label_value(substance)
        query = f"""
        PREFIX p: <http://www.wikidata.org/prop/>
        PREFIX psv: <http://www.wikidata.org/prop/statement/value/>
        PREFIX ps: <http://www.wikidata.org/prop/statement/>
        PREFIX wikibase: <http://wikiba.se/ontology#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

        SELECT ?entity ?property ?amount ?unit WHERE {{
          ?entity rdfs:label {label} .
          {{
            ?entity p:P2102 ?statement .
            ?statement ps:P2102 ?rawValue ;
                       psv:P2102 ?valueNode .
            ?valueNode wikibase:quantityAmount ?amount ;
                       wikibase:quantityUnit ?unit .
            BIND("boiling_point" AS ?property)
          }} UNION {{
            ?entity p:P2101 ?statement .
            ?statement ps:P2101 ?rawValue ;
                       psv:P2101 ?valueNode .
            ?valueNode wikibase:quantityAmount ?amount ;
                       wikibase:quantityUnit ?unit .
            BIND("melting_point" AS ?property)
          }} UNION {{
            ?entity p:P2054 ?statement .
            ?statement ps:P2054 ?rawValue ;
                       psv:P2054 ?valueNode .
            ?valueNode wikibase:quantityAmount ?amount ;
                       wikibase:quantityUnit ?unit .
            BIND("density" AS ?property)
          }}
        }}
        LIMIT {self.LIMIT}
        """
        properties = self._run_question(query)

        for row in properties:
            if "error" not in row and row.get("unit"):
                row["unit_name"] = self.wikidata.get_label(row["unit"])

        return {
            "question_id": "physical-properties",
            "substance": substance,
            "properties": properties,
        }

    # done
    def answer_mixture_components(self, mixture: str) -> dict:
        """
        Return all directly recorded P527 components for a Wikidata entity.

        Accepts a chemical label, Wikidata QID, or Wikidata URL.
        Component labels are resolved in English by Wikidata's label service.

        Note:
        P527 records direct parts; it does not guarantee that every
        constituent of a chemical mixture is represented in Wikidata.
        """
        if not isinstance(mixture, str) or not mixture.strip():
            raise ValueError("Mixture must be a non-empty QID, Wikidata URL, or label")

        value = mixture.strip()

        try:
            qid = self._resolve_entity(value)
        except ValueError as exc:
            return {
                "question_id": "mixture-components",
                "mixture": mixture,
                "status": "not_found",
                "error": str(exc),
                "components": [],
            }

        query = f"""
        PREFIX wd: <http://www.wikidata.org/entity/>
        PREFIX wdt: <http://www.wikidata.org/prop/direct/>
        PREFIX wikibase: <http://wikiba.se/ontology#>
        PREFIX bd: <http://www.bigdata.com/rdf#>

        SELECT DISTINCT ?component ?componentLabel
        WHERE {{
            wd:{qid} wdt:P527 ?component .

            SERVICE wikibase:label {{
                bd:serviceParam wikibase:language "en" .
            }}
        }}
        ORDER BY ?componentLabel
        """

        rows = self._run_question(query)

        error = next(
            (row["error"] for row in rows if isinstance(row, dict) and "error" in row),
            None,
        )

        if error:
            return {
                "question_id": "mixture-components",
                "mixture": mixture,
                "resolved_qid": qid,
                "status": "query_error",
                "error": error,
                "components": [],
            }

        # Each component is identified by its Wikidata entity URI.
        components_by_uri = {}

        for row in rows:
            component_uri = row.get("component")

            if not component_uri:
                continue

            components_by_uri[component_uri] = {
                "entity": component_uri,
                "label": row.get("componentLabel"),
            }

        components = list(components_by_uri.values())

        return {
            "question_id": "mixture-components",
            "mixture": mixture,
            "resolved_qid": qid,
            "status": ("components_found" if components else "no_components_recorded"),
            "components": components,
        }
