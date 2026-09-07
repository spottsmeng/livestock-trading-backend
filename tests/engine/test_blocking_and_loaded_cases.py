"""fixtures/engine-test-vectors.json's `blocking_cases` array — non-negotiables
#6 and #9. Each case is purpose-built to isolate one behaviour, so
`expect_issues` is checked as "these codes must be present", not as an
exhaustive set — except for the loaded case, where the fixture explicitly
demands the ACTIVE-only rule codes be entirely absent via
`expect_rules_NOT_fired`, and the whole point is that nothing else fires
either (this line is genuinely complete: date, cost and margin are all
present, so no §5.7.1 rule has anything to flag).
"""

from dataclasses import replace
from decimal import Decimal

from domain.engine.workings import Lifecycle, OrderLineInput, compute_order_workings, is_publishable
from tests.engine.helpers import assert_decimal_close, config_from_reference_tables, dec, load_vectors

_DATA = load_vectors()
_REFERENCE_TABLES = _DATA["reference_tables_used"]
_CASES = {case["id"]: case for case in _DATA["blocking_cases"]}


def _issue_codes(found_issues) -> set[str]:
    return {issue.code for issue in found_issues}


def _assert_expected_issues_present(found_issues, expect_issues) -> None:
    for expected in expect_issues:
        matches = [i for i in found_issues if i.code == expected["code"] and i.severity.value == expected["severity"]]
        assert matches, f"expected issue {expected} not found in {found_issues}"


def test_active_mutton_blocks_no_factor() -> None:
    case = _CASES["active_mutton_blocks_no_factor"]
    config = config_from_reference_tables(_REFERENCE_TABLES)
    line = OrderLineInput(
        species=case["input"]["species"],
        lifecycle=Lifecycle(case["input"]["lifecycle"]),
        avg_price_aud=dec(case["input"]["avg_price_aud"]),
    )

    workings, found_issues = compute_order_workings(line, config)

    assert workings is not None
    assert workings.bing_dnbp is None
    _assert_expected_issues_present(found_issues, case["expect_issues"])
    assert is_publishable(found_issues) is case["expect_publishable"]


def test_missing_livestock_cost_still_publishes() -> None:
    case = _CASES["missing_livestock_cost_still_publishes"]
    config = config_from_reference_tables(_REFERENCE_TABLES)
    line = OrderLineInput(
        species=case["input"]["species"],
        lifecycle=Lifecycle.ACTIVE,
        avg_price_aud=dec(case["input"]["avg_price_aud"]),
        expected_livestock_cost_per_kg=None,
    )

    workings, found_issues = compute_order_workings(line, config)

    assert workings is not None
    assert_decimal_close(workings.bing_dnbp, case["expect_bing_dnbp"], label="missing_livestock_cost.bing_dnbp")
    _assert_expected_issues_present(found_issues, case["expect_issues"])
    assert is_publishable(found_issues) is case["expect_publishable"]


def test_missing_standard_weight_still_publishes() -> None:
    case = _CASES["missing_standard_weight_still_publishes"]
    base_config = config_from_reference_tables(_REFERENCE_TABLES)
    species = case["input"]["species"]
    config = replace(
        base_config,
        standard_weight_by_species={k: v for k, v in base_config.standard_weight_by_species.items() if k != species},
    )
    line = OrderLineInput(
        species=species,
        lifecycle=Lifecycle.ACTIVE,
        avg_price_aud=dec(case["input"]["avg_price_aud"]),
    )

    workings, found_issues = compute_order_workings(line, config)

    assert workings is not None
    assert_decimal_close(workings.bing_dnbp, case["expect_bing_dnbp"], label="missing_standard_weight.bing_dnbp")
    assert workings.pack_cost_per_kg is None
    assert workings.offal_return_per_kg is None
    assert workings.skin_return_per_kg is None
    _assert_expected_issues_present(found_issues, case["expect_issues"])
    assert is_publishable(found_issues) is case["expect_publishable"]


def test_loaded_mutton_must_not_block() -> None:
    """REGRESSION GUARD (§5.3, §5.7): CED18656 is the only MUTTON row in
    either supplied file and is LOADED in all three occurrences. If this
    test fails, both real workbooks would refuse to publish on ingestion."""
    case = _CASES["loaded_mutton_must_not_block"]
    config = config_from_reference_tables(_REFERENCE_TABLES)
    raw = case["input"]
    line = OrderLineInput(
        species=raw["species"],
        lifecycle=Lifecycle(raw["lifecycle"]),
        contract_no=raw["contract_no"],
        avg_price_aud=dec(raw["avg_price_aud"]),
        incoterm=raw["incoterm"],
        expected_livestock_cost_per_kg=dec(raw["expected_livestock_cost_per_kg"]),
        avg_weight_kg=dec(raw["avg_weight_kg"]),
        loadout_date=raw["loadout_date"],
    )

    workings, found_issues = compute_order_workings(line, config)

    assert (workings is not None) is case["expect_order_workings_row"]
    assert workings is None
    assert found_issues == case["expect_issues"] == []
    assert is_publishable(found_issues) is case["expect_publishable"]

    fired_codes = _issue_codes(found_issues)
    for forbidden_code in case["expect_rules_NOT_fired"]:
        assert forbidden_code not in fired_codes, f"{forbidden_code} must never fire on a LOADED line"


def test_loaded_lines_never_reach_active_rule_functions() -> None:
    """Structural guarantee behind non-negotiable #6: LOADED dispatches to a
    wholly separate function that cannot even reference the ACTIVE-only
    issue codes, not an ACTIVE path with an `if lifecycle == LOADED: skip`
    guard bolted on."""
    import ast
    import inspect

    from domain.engine import issues as issues_module
    from domain.engine import workings as workings_module
    from domain.engine.issues import ACTIVE_ONLY_CODES

    source = inspect.getsource(workings_module._compute_loaded_line_issues)
    tree = ast.parse(source)
    referenced_names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}

    active_only_attr_names = {
        name
        for name in dir(issues_module)
        if not name.startswith("_") and getattr(issues_module, name) in ACTIVE_ONLY_CODES
    }

    assert referenced_names.isdisjoint(active_only_attr_names)


def test_dnbp_below_cost_and_negative_margin_are_active_only_warns() -> None:
    """Sanity check that WARN-level pricing rules exist and are reachable
    on an ACTIVE line, complementing the BLOCK-focused cases above."""
    config = config_from_reference_tables(_REFERENCE_TABLES)
    line = OrderLineInput(
        species="SHEEP",
        lifecycle=Lifecycle.ACTIVE,
        avg_price_aud=Decimal("1.00"),  # tiny price -> AC well below livestock cost
        expected_livestock_cost_per_kg=Decimal("50"),
        pack_cost_ph=Decimal("4"),
        offal_return_ph=Decimal("8"),
        skin_return_ph=Decimal("10"),
        avg_weight_kg=Decimal("22"),
    )

    workings, found_issues = compute_order_workings(line, config)

    assert workings is not None
    codes_fired = _issue_codes(found_issues)
    assert "DNBP_BELOW_COST" in codes_fired
    assert "NEGATIVE_MARGIN" in codes_fired
