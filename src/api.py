"""
api.py
FastAPI routes for chemical knowledge-graph questions.
"""

import inspect
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from .questions import QuestionService
from .knowledge_graph import WikidataStore
from .rhea_store import RheaStore


app = FastAPI(
    title="Wikidata Knowledge Graph API",
    description=(
        "API service for querying chemical entities and properties "
        "via Wikidata and Rhea"
    ),
    version="1.0.0",
)

question_service = QuestionService(WikidataStore(), RheaStore())


def create_ask_endpoint(
    question_id: str,
    method_name: str,
    params: dict[str, str],
):
    """
    Register an endpoint whose required query parameters are defined by `params`.

    `params` maps each parameter name to its description.
    """
    service_method = getattr(question_service, method_name)

    def endpoint(**kwargs: str) -> dict[str, Any]:
        try:
            result = service_method(**kwargs)
            if not isinstance(result, dict):
                raise TypeError(
                    f"{method_name} must return a dictionary, "
                    f"got {type(result).__name__}"
                )

            response = {"question_id": question_id, **kwargs}
            response.update(result)
            return response
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    # FastAPI reads this signature to create required query parameters,
    # validate requests, and document them in OpenAPI.
    signature_params = []
    for name, description in params.items():
        if not name.isidentifier():
            raise ValueError(f"Invalid query parameter name: {name!r}")

        signature_params.append(
            inspect.Parameter(
                name=name,
                kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=Query(..., description=description),
                annotation=str,
            )
        )

    name = f"ask_{question_id.replace('-', '_')}"
    signature = inspect.Signature(
        parameters=signature_params,
        return_annotation=dict[str, Any],
    )
    setattr(endpoint, "__name__", name)
    setattr(endpoint, "__signature__", signature)

    app.get(
        f"/api/v1/ask/{question_id}",
        name=f"ask_{question_id}",
    )(endpoint)

    return endpoint


create_ask_endpoint(
    question_id="reaction",
    method_name="answer_reaction",
    params={
        "substance": "First substance name, QID, or Wikidata URL",
        "other_substance": "Second substance name, QID, or Wikidata URL",
    },
)

create_ask_endpoint(
    question_id="chemical-properties",
    method_name="answer_chemical_properties",
    params={"substance": "Substance name or ID"},
)

create_ask_endpoint(
    question_id="substance-kind",
    method_name="answer_substance_kind",
    params={"substance": "Substance name or ID"},
)

create_ask_endpoint(
    question_id="physical-properties",
    method_name="answer_physical_properties",
    params={"substance": "Substance name or ID"},
)

create_ask_endpoint(
    question_id="mixture-components",
    method_name="answer_mixture_components",
    params={"mixture": "Mixture name or ID"},
)
