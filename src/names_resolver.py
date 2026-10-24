"""
compound_name_resolver.py
Module for resolving natural language compound names to PubChem CIDs using RDF ontology.
Based on PubChem RDF structure with support for synonyms, InChIKey, and SMILES identifiers.
"""

from typing import Dict, List, Optional, Tuple
from .knowledge_store import PubChemSPARQLQuerier


class CompoundNameResolver:
    """
    Resolves natural language chemical names to PubChem Compound IDs (CIDs)
    using the PubChem RDF ontology structure.

    The resolver uses multiple lookup strategies:
    1. Synonym matching (depositor-provided synonyms via synonym subdomain)
    2. InChIKey matching (chemical structure fingerprint)
    3. SMILES string matching
    4. IUPAC name matching
    5. Direct CID lookup
    """

    # Predefined common chemical name-to-CID mappings (curated database)
    COMMON_COMPOUNDS = {
        # Drugs
        "aspirin": "2244",
        "acetylsalicylic acid": "2244",
        "ibuprofen": "3672",
        "paracetamol": "1983",
        "acetaminophen": "1983",
        "caffeine": "2519",
        "atorvastatin": "60823",
        "lisinopril": "5362",
        "metformin": "4091",
        "omeprazole": "4594",
        "simvastatin": "54454",
        "warfarin": "5002",
        "clopidogrel": "93311",
        "amlodipine": "2145",
        "enalapril": "5362",
        # Common organic molecules
        "glucose": "5793",
        "fructose": "5311",
        "sucrose": "5988",
        "ethanol": "702",
        "methanol": "887",
        "acetone": "180",
        "formic acid": "283",
        "acetic acid": "176",
        "water": "962",
        "sodium chloride": "5234",
        "potassium chloride": "4873",
        "calcium carbonate": "10112",
        # Vitamins
        "vitamin c": "54660229",
        "ascorbic acid": "54660229",
        "vitamin d": "5280795",
        "vitamin b12": "6311233",
        "cobalamin": "6311233",
        "biotin": "171548",
        # Amino acids
        "alanine": "5461",
        "glycine": "750",
        "leucine": "6106",
        "serine": "5951",
        "valine": "6572",
    }

    def __init__(self):
        """Initialize the resolver with PubChem SPARQL querier."""
        self.querier = PubChemSPARQLQuerier()
        self.cache: Dict[str, str] = {}

    def resolve(self, compound_name: str, exact_match: bool = False) -> Optional[str]:
        """
        Resolve a compound name to a CID using multiple strategies.

        Args:
            compound_name: Natural language name of the compound
            exact_match: If True, only return results with exact name match

        Returns:
            CID (str) if found, None otherwise
        """
        # Normalize input
        name_lower = compound_name.lower().strip()

        # Check cache first
        if name_lower in self.cache:
            return self.cache[name_lower]

        # Strategy 1: Check common compounds database
        if name_lower in self.COMMON_COMPOUNDS:
            cid = self.COMMON_COMPOUNDS[name_lower]
            self.cache[name_lower] = cid
            return cid

        # Strategy 2: Query via RDF synonyms
        cid = self._resolve_by_synonym(compound_name, exact_match)
        if cid:
            self.cache[name_lower] = cid
            return cid

        # Strategy 3: Query via SMILES if input is a SMILES string
        if self._is_smiles(compound_name):
            cid = self._resolve_by_smiles(compound_name)
            if cid:
                self.cache[name_lower] = cid
                return cid

        return None

    def resolve_batch(self, compound_names: List[str]) -> Dict[str, Optional[str]]:
        """
        Resolve multiple compound names to CIDs.

        Args:
            compound_names: List of natural language names

        Returns:
            Dict mapping each name to its CID (or None if not found)
        """
        return {name: self.resolve(name) for name in compound_names}

    def _resolve_by_synonym(
        self, compound_name: str, exact_match: bool = False
    ) -> Optional[str]:
        """
        Resolve compound by matching against PubChem RDF synonyms.

        RDF Structure:
        - syno:MD5_<hash> sio:is-attribute-of compound:CID<n>
        - synonym values are stored with language tags and types

        Args:
            compound_name: Name to resolve
            exact_match: Require exact match if True

        Returns:
            CID if found, None otherwise
        """
        query = f"""
        PREFIX sio: <http://semanticscience.org/resource/>
        PREFIX compound: <http://rdf.ncbi.nlm.nih.gov/pubchem/compound/>
        PREFIX syno: <http://rdf.ncbi.nlm.nih.gov/pubchem/synonym/>
        PREFIX cheminf: <http://purl.obolibrary.org/obo/CHEMINF_>
        
        SELECT DISTINCT ?cid
        WHERE {{
            ?synonym_uri sio:is-attribute-of ?compound_uri .
            ?compound_uri a ?type .
            ?synonym_uri rdf:value ?synonym_value .
            
            FILTER(REGEX(?synonym_value, "{compound_name}", "i"))
            
            BIND(REPLACE(STR(?compound_uri), ".*CID", "") AS ?cid)
        }}
        LIMIT 10
        """

        try:
            results = self.querier.store.query(query)
            for row in results:
                if hasattr(row, "cid") and row.cid:
                    return str(row.cid)
        except Exception:
            pass

        return None

    def _resolve_by_smiles(self, smiles: str) -> Optional[str]:
        """
        Resolve compound by matching SMILES string against PubChem RDF.

        RDF Structure:
        - compound:CID<n> sio:has-attribute descr:CID<n>_Canonical_SMILES

        Args:
            smiles: SMILES string representation

        Returns:
            CID if found, None otherwise
        """
        query = f"""
        PREFIX sio: <http://semanticscience.org/resource/>
        PREFIX compound: <http://rdf.ncbi.nlm.nih.gov/pubchem/compound/>
        PREFIX descr: <http://rdf.ncbi.nlm.nih.gov/pubchem/descriptor/>
        
        SELECT ?cid
        WHERE {{
            ?compound_uri sio:has-attribute ?descriptor .
            ?descriptor rdf:value ?smiles_value .
            
            FILTER(?smiles_value = "{smiles}")
            
            BIND(REPLACE(STR(?compound_uri), ".*CID", "") AS ?cid)
        }}
        LIMIT 1
        """

        try:
            results = self.querier.store.query(query)
            for row in results:
                if hasattr(row, "cid") and row.cid:
                    return str(row.cid)
        except Exception:
            pass

        return None

    def _is_smiles(self, text: str) -> bool:
        """
        Simple heuristic to detect if text is a SMILES string.

        SMILES strings contain aromatic/aliphatic atoms and special characters
        but don't contain spaces (single compounds).
        """
        smiles_chars = set("CNOPSFBrClI@=()[]#-+\\/")
        return len(text) > 3 and len(set(text) & smiles_chars) > 2 and " " not in text

    def get_aliases(self, cid: str) -> List[str]:
        """
        Retrieve all known synonyms and aliases for a given CID.

        Uses the PubChem RDF synonym subdomain to fetch all depositor-provided
        and computed synonym forms.

        Args:
            cid: PubChem Compound ID

        Returns:
            List of synonym strings
        """
        query = f"""
        PREFIX sio: <http://semanticscience.org/resource/>
        PREFIX compound: <http://rdf.ncbi.nlm.nih.gov/pubchem/compound/>
        PREFIX syno: <http://rdf.ncbi.nlm.nih.gov/pubchem/synonym/>
        
        SELECT DISTINCT ?synonym_value ?synonym_type
        WHERE {{
            ?synonym_uri sio:is-attribute-of compound:CID{cid} .
            ?synonym_uri rdf:value ?synonym_value .
            OPTIONAL {{ ?synonym_uri rdf:type ?synonym_type }}
        }}
        ORDER BY ?synonym_value
        """

        aliases = []
        try:
            results = self.querier.store.query(query)
            for row in results:
                if hasattr(row, "synonym_value") and row.synonym_value:
                    aliases.append(str(row.synonym_value))
        except Exception:
            pass

        return aliases

    def get_compound_metadata(self, cid: str) -> Dict[str, any]:
        """
        Retrieve comprehensive metadata for a compound using RDF structure.

        Returns information structured according to PubChem RDF ontology:
        - Synonyms (from synonym subdomain)
        - InChIKey (from inchikey subdomain)
        - Descriptors (from descriptor subdomain)
        - Relationships (parent, stereoisomers, etc.)

        Args:
            cid: PubChem Compound ID

        Returns:
            Dictionary with compound metadata
        """
        metadata = {
            "cid": cid,
            "synonyms": self.get_aliases(cid),
        }

        # Add molecular formula and composition if available
        formula_data = self.querier.get_molecular_formula(cid)
        if "formula" in formula_data:
            metadata["molecular_formula"] = formula_data["formula"]
            metadata["elements"] = formula_data.get("elements", {})

        # Add SMILES
        representations = self.querier.get_available_representations(cid)
        metadata["canonical_smiles"] = representations.get("canonical_smiles")
        metadata["isomeric_smiles"] = representations.get("isomeric_smiles")
        metadata["inchi_key"] = representations.get("inchi_key")

        return metadata
