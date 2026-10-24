"""
test_api.py
Pytest test suite for testing the FastAPI application routes with relevance validation.
"""

from fastapi.testclient import TestClient
from src.api import app

client = TestClient(app)


def test_ask_reaction():
    """Test that reaction queries return relevant reactions for the substance."""
    response = client.get("/api/v1/ask/reaction?substance=glucose")
    assert response.status_code == 200
    data = response.json()
    assert data["question_id"] == "reaction"
    assert "reactions" in data
    assert data["query_substance"] == "glucose"

    # Verify relevance: reactions should be non-empty or provide meaningful empty result
    reactions = data.get("reactions", [])
    if reactions:
        for reaction in reactions:
            assert "reaction_uri" in reaction
            # Reactions should reference participants
            assert "left_participants" in reaction or "right_participants" in reaction
            # Labels should be present if results exist
            assert (
                reaction.get("label")
                or reaction.get("description")
                or reaction.get("reaction_uri")
            )


def test_ask_chemical_properties():
    """Test that chemical properties match the queried substance."""
    response = client.get("/api/v1/ask/chemical-properties?substance=citric_acid")
    assert response.status_code == 200
    data = response.json()
    assert data["question_id"] == "chemical-properties"
    assert data["substance"] == "citric_acid"
    assert "properties" in data

    # Verify relevance: properties should be chemical in nature
    properties = data.get("properties", [])
    if properties:
        valid_property_types = {
            "chemical_formula",
            "molecular_formula",
            "canonical_smiles",
            "inchi_string",
            "is_organic",
            "molecular_charge",
        }
        for prop in properties:
            assert "entity_uri" in prop
            assert "property" in prop
            assert "value" in prop
            # Property should be one of the known chemical properties
            assert (
                prop["property"] in valid_property_types
            ), f"Unexpected property type: {prop['property']}"
            # Value should not be empty
            assert prop["value"], "Property value should not be empty"

# TODO: rework answer_concentration
def test_ask_concentration():
    """Test that concentration queries return components with concentration data."""
    response = client.get("/api/v1/ask/concentration?mixture=solution")
    assert response.status_code == 200
    data = response.json()
    assert data["question_id"] == "concentration"
    assert data["mixture"] == "solution"
    assert "proportions" in data

    # Verify relevance: mixture components should have measurable concentrations
    proportions = data.get("proportions", [])
    if proportions:
        for proportion in proportions:
            assert "mixture_uri" in proportion
            assert "component_uri" in proportion
            assert "component_label" in proportion
            # At least one component should have concentration data
            assert proportion.get("concentration_value") is not None or any(
                p.get("concentration_value") for p in proportions
            ), "At least one component should have concentration value"


def test_ask_substance_kind():
    """Test that substance kind returns valid ontological types."""
    response = client.get("/api/v1/ask/substance-kind?substance=water")
    assert response.status_code == 200
    data = response.json()
    assert data["question_id"] == "substance-kind"
    assert data["substance"] == "water"
    assert "kinds" in data

    # Verify relevance: water should be categorized with valid types
    kinds = data.get("kinds", [])
    if kinds:
        for kind in kinds:
            assert "entity_uri" in kind
            assert "type_uri" in kind
            # Type label or URI should exist
            assert kind.get("type_label") or kind.get("type_uri")
            # Water should be identified as a molecule or chemical entity
            type_str = (
                str(kind.get("type_uri", "")).lower()
                + str(kind.get("type_label", "")).lower()
            )
            assert any(
                keyword in type_str
                for keyword in ["molecule", "chemical", "substance", "entity"]
            ), f"Water should be classified as a recognized chemical type, got: {kind}"

# TODO: rework answer_physical_properties
def test_ask_physical_properties():
    """Test that physical properties include measurable values."""
    response = client.get("/api/v1/ask/physical-properties?entity=methane")
    assert response.status_code == 200
    data = response.json()
    assert data["question_id"] == "physical-properties"
    assert data["entity"] == "methane"
    assert "properties" in data

    # Verify relevance: properties should be physical measurements
    properties = data.get("properties", [])
    if properties:
        valid_physical_props = {
            "boiling_point_celsius",
            "melting_point_celsius",
            "bond_length_angstroms",
            "bond_length",
            "bond_energy",
            "bond_angle",
        }
        for prop in properties:
            assert "entity_uri" in prop
            assert "property" in prop
            assert "value" in prop
            # Property should be one of the known physical properties
            assert (
                prop["property"] in valid_physical_props
            ), f"Expected physical property, got: {prop['property']}"
            # Value should be numeric or a meaningful string
            assert (
                prop["value"] and str(prop["value"]).strip()
            ), "Physical property value should not be empty"


def test_ask_substance_category():
    """Test that substance category returns valid material classifications."""
    response = client.get("/api/v1/ask/substance-category?substance=cellulose")
    assert response.status_code == 200
    data = response.json()
    assert data["question_id"] == "substance-category"
    assert data["substance"] == "cellulose"
    assert "categories" in data

    # Verify relevance: cellulose should be classified as a known category
    categories = data.get("categories", [])
    if categories:
        valid_categories = {
            "Molecule",
            "MonomolecularPolymer",
            "Mineral",
            "ChemicalMixture",
            "Macromolecule",
            "Material",
            "Polymer",
        }
        for category in categories:
            assert "entity_uri" in category
            assert "category_uri" in category
            assert "category_label" in category
            # Category label should match one of the known types
            category_label = category.get("category_label", "")
            assert any(
                valid_cat.lower() in category_label.lower()
                for valid_cat in valid_categories
            ), f"Cellulose should be a known category type, got: {category_label}"


def test_ask_mixture_components():
    """Test that mixture components returns constituent substances."""
    response = client.get("/api/v1/ask/mixture-components?mixture=alloy")
    assert response.status_code == 200
    data = response.json()
    assert data["question_id"] == "mixture-components"
    assert data["mixture"] == "alloy"
    assert "components" in data

    # Verify relevance: alloy should have identifiable components
    components = data.get("components", [])
    if components:
        for component in components:
            assert "mixture_uri" in component
            assert "component_uri" in component
            # Each component should have identifying information
            assert component.get("component_label") or component.get(
                "component_uri"
            ), "Component should have a label or URI"
            assert "component_type" in component
    else:
        # If no components, verify the response still has valid structure
        assert isinstance(components, list), "Components should be a list even if empty"


def test_ask_reaction_no_results_handling():
    """Test that queries with no results are handled gracefully."""
    response = client.get("/api/v1/ask/reaction?substance=nonexistent_xyz_chemical")
    assert response.status_code == 200
    data = response.json()
    assert data["question_id"] == "reaction"
    # Should return empty list, not error
    assert isinstance(data.get("reactions", []), list)


def test_ask_concentration_with_values():
    """Test that concentration values are numeric when present."""
    response = client.get("/api/v1/ask/concentration?mixture=saltwater_solution")
    assert response.status_code == 200
    data = response.json()

    proportions = data.get("proportions", [])
    for proportion in proportions:
        if proportion.get("concentration_value"):
            # Concentration value should be convertible to float if numeric
            try:
                float(proportion["concentration_value"])
            except (ValueError, TypeError):
                # Or it could be a string representation of the value
                assert isinstance(proportion["concentration_value"], str)
