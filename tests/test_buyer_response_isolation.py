"""§2.2, §14, §19 acceptance criterion: "A buyer response containing a
customer name, sell price, or margin field fails CI." Introspects every
Pydantic response model reachable from every route in api/v1/buyer.py
(recursing into nested models and generic containers) and fails if any
field name matches the forbidden set — a structural guarantee, not a
review checklist.
"""

import re
import typing

from fastapi.routing import APIRoute
from pydantic import BaseModel

from api.v1 import buyer

FORBIDDEN_FIELD_PATTERN = re.compile(
    r"^(customer_name|avg_price_aud|nrv_per_kg|amount_aud|mom_ph|dnbp_benchmark|profit_on_.*|diff_vs_.*"
    # Phase 4, §13.1/§2.2 — the Buy Instruction's cost/margin-adjacent
    # figures, same forbidden category as mom_ph/profit_on_*: a buyer may
    # see the DNBP ceiling and the target heads/weight it applies to, never
    # what Bing expects to pay for it or what she thinks it should cost.
    r"|peters_expectation|expected_livestock_cost)$"
)


def _flatten_models(annotation: object, seen: set[type[BaseModel]]) -> None:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation in seen:
            return
        seen.add(annotation)
        for field in annotation.model_fields.values():
            _flatten_models(field.annotation, seen)
        return

    for arg in typing.get_args(annotation):
        _flatten_models(arg, seen)


def _all_buyer_response_models() -> set[type[BaseModel]]:
    models: set[type[BaseModel]] = set()
    for route in buyer.router.routes:
        if isinstance(route, APIRoute) and route.response_model is not None:
            _flatten_models(route.response_model, models)
    return models


def test_buyer_router_has_response_models_to_check():
    # Sanity check — if this ever drops to zero, the introspection below is
    # vacuously passing and would silently stop meaning anything.
    assert len(_all_buyer_response_models()) >= 3


def test_no_buyer_response_model_carries_a_forbidden_field():
    offending = []
    for model in _all_buyer_response_models():
        for name in model.model_fields:
            if FORBIDDEN_FIELD_PATTERN.match(name):
                offending.append(f"{model.__name__}.{name}")
    assert offending == [], f"Forbidden fields reachable from a buyer response: {offending}"
