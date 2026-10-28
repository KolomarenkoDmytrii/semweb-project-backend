"""
test_api.py
Pytest test suite for testing the FastAPI application routes and responses.
"""

from fastapi.testclient import TestClient
from src.api import app

client = TestClient(app)


def test_ask_reaction():
    """
    Test that reaction queries between two substances
    return shared and individual Rhea reactions.
    """
    response = client.get("/api/v1/ask/reaction?substance=glucose&other_substance=ATP")
    assert response.status_code == 200
    data = response.json()
    assert data["question_id"] == "reaction"
    assert "query_substances" in data
    assert "resolved_qids" in data
    assert "status" in data
    assert "reactions" in data
    assert "individual_reactions" in data

    reactions = data.get("reactions", [])
    if reactions:
        for reaction in reactions:
            assert "rhea_id" in reaction
            assert "equation" in reaction
            assert "url" in reaction


def test_ask_chemical_properties():
    """Test that chemical properties return identifiers and property measurements."""
    response = client.get("/api/v1/ask/chemical-properties?substance=citric_acid")
    assert response.status_code == 200
    data = response.json()
    assert data["question_id"] == "chemical-properties"
    assert data["substance"] == "citric_acid"
    assert "properties" in data

    properties = data.get("properties", [])
    if properties:
        for prop in properties:
            assert "property" in prop
            assert "value" in prop


def test_ask_substance_kind():
    """Test that substance kind returns instance-of and subclass-of ontological relations."""
    response = client.get("/api/v1/ask/substance-kind?substance=water")
    assert response.status_code == 200
    data = response.json()
    assert data["question_id"] == "substance-kind"
    assert data["substance"] == "water"
    assert "kinds" in data

    kinds = data.get("kinds", [])
    if kinds:
        for kind in kinds:
            assert "entity" in kind
            assert "relation" in kind
            assert "type" in kind


def test_ask_physical_properties():
    """Test that physical properties include measurable quantities and units."""
    response = client.get("/api/v1/ask/physical-properties?substance=methane")
    assert response.status_code == 200
    data = response.json()
    assert data["question_id"] == "physical-properties"
    assert data["substance"] == "methane"
    assert "properties" in data

    properties = data.get("properties", [])
    if properties:
        for prop in properties:
            assert "property" in prop
            assert "amount" in prop
            assert "unit" in prop


def test_ask_mixture_components():
    """Test that mixture components return constituent substances."""
    response = client.get("/api/v1/ask/mixture-components?mixture=air")
    assert response.status_code == 200
    data = response.json()
    assert data["question_id"] == "mixture-components"
    assert data["mixture"] == "air"
    assert "status" in data
    assert "components" in data

    components = data.get("components", [])
    if components:
        for component in components:
            assert "entity" in component
            assert "label" in component


def test_ask_mixture_components_not_found():
    """Test graceful error handling when an unknown mixture is queried."""
    response = client.get(
        "/api/v1/ask/mixture-components?mixture=nonexistent_xyz_mixture"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["question_id"] == "mixture-components"
    assert data["status"] == "not_found"
    assert "error" in data
    assert data["components"] == []
