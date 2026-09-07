"""The highest-value test in the codebase (§17.3): every vector in
fixtures/engine-test-vectors.json, matched to 10 decimal places."""

import pytest

from domain.engine.workings import Lifecycle, OrderLineInput, compute_order_workings
from tests.engine.helpers import assert_decimal_close, config_from_engine_config, dec, load_vectors

_VECTORS = load_vectors()["vectors"]
_VECTOR_IDS = [v["id"] for v in _VECTORS]

# expected_X_to_AF key -> OrderWorkings attribute name
_FIELD_MAP = {
    "adjusted_price_per_kg": "adjusted_price_per_kg",
    "pack_cost_per_kg": "pack_cost_per_kg",
    "offal_return_per_kg": "offal_return_per_kg",
    "skin_return_per_kg": "skin_return_per_kg",
    "profit_on_peter_costs": "profit_on_peter_costs",
    "bing_dnbp": "bing_dnbp",
    "profit_on_bing_dnbp": "profit_on_bing_dnbp",
    "diff_vs_benchmark": "diff_vs_benchmark",
    "diff_vs_peter": "diff_vs_peter",
}


def _line_input(vector: dict) -> OrderLineInput:
    received = {k: v["value"] for k, v in vector["received_A_to_V"].items()}
    return OrderLineInput(
        species=received["species"],
        lifecycle=Lifecycle(vector["lifecycle"]),
        contract_no=received.get("contract_no"),
        avg_price_aud=dec(received["avg_price_aud"]),
        incoterm=received.get("incoterm"),
        expected_livestock_cost_per_kg=dec(received["expected_livestock_cost_per_kg"]),
        pack_cost_ph=dec(received["pack_cost_ph"]),
        offal_return_ph=dec(received["offal_return_ph"]),
        skin_return_ph=dec(received["skin_return_ph"]),
        avg_weight_kg=dec(received["avg_weight_kg"]),
        mom_ph=dec(received["mom_ph"]),
        dnbp_benchmark=dec(received["dnbp_benchmark"]),
    )


@pytest.mark.parametrize("vector", _VECTORS, ids=_VECTOR_IDS)
def test_golden_vector_matches_to_10dp(vector: dict) -> None:
    species = vector["received_A_to_V"]["species"]["value"]
    config = config_from_engine_config(species, vector["engine_config"])
    line = _line_input(vector)

    workings, found_issues = compute_order_workings(line, config)

    assert workings is not None, f"{vector['id']}: expected an ACTIVE line to produce a workings row"
    # These vectors aren't annotated with issue expectations (that's what
    # blocking_cases[] is for) — a WARN like DNBP_BELOW_COST can legitimately
    # fire here (e.g. sheep_cif_actual_weight_28_differs_from_standard_22,
    # where AC really is below L). Only BLOCK issues would be a real bug: a
    # golden vector's AC is by definition computable.
    assert not any(i.severity.value == "BLOCK" for i in found_issues), (
        f"{vector['id']}: unexpected BLOCK issue on a vector with a known-good AC: {found_issues}"
    )

    for expected_key, attr_name in _FIELD_MAP.items():
        expected_raw = vector["expected_X_to_AF"][expected_key]["value"]
        actual = getattr(workings, attr_name)
        assert_decimal_close(actual, expected_raw, label=f"{vector['id']}.{expected_key}")


@pytest.mark.parametrize("vector", _VECTORS, ids=_VECTOR_IDS)
def test_dnbp_proof_matches_isolated_formula(vector: dict) -> None:
    """Cross-check against the fixture's own `dnbp_proof` block — an
    independent re-derivation of AC from just avg_price_aud/cif_buffer/
    dnbp_factor, proving the isolated formula alone reproduces AC."""
    proof = vector["dnbp_proof"]
    engine_config = vector["engine_config"]

    isolated = (dec(vector["received_A_to_V"]["avg_price_aud"]["value"]) - dec(engine_config["cif_buffer"])) * dec(
        engine_config["dnbp_factor_for_species"]
    )

    assert_decimal_close(isolated, proof["expected"], label=f"{vector['id']}.dnbp_proof")
