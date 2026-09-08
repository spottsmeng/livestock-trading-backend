"""§17.3's three named properties against `domain.engine.dnbp.compute_bing_dnbp`
(non-negotiable #14): "DNBP is monotonic in avg_price_aud; DNBP never
exceeds X (the CIF-adjusted price); no input produces a division-by-zero or
NaN/Inf." Hypothesis-driven, lives under tests/engine/ so it inherits that
directory's DB-free conftest (§17.1 — domain/engine/ has zero I/O, and its
tests must not need Postgres/Redis either).

This file does not touch domain/engine/ itself — it is a new test file only
(non-negotiable #1, #14).
"""

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from domain.engine.dnbp import compute_bing_dnbp
from tests.engine.helpers import config_from_reference_tables, load_vectors

_REFERENCE_TABLES = load_vectors()["reference_tables_used"]
_CONFIG = config_from_reference_tables(_REFERENCE_TABLES)

# Every seeded species/factor pair, so the properties aren't just proven for
# one arbitrarily-chosen species.
_SPECIES_WITH_FACTORS = sorted(_CONFIG.dnbp_factor_by_species)

_prices = st.decimals(min_value="0.01", max_value="1000000", places=4, allow_nan=False, allow_infinity=False)
_species = st.sampled_from(_SPECIES_WITH_FACTORS)


@given(species=_species, price1=_prices, price2=_prices)
def test_dnbp_is_monotonic_in_avg_price_aud(species: str, price1: Decimal, price2: Decimal) -> None:
    """Every seeded factor is positive (0.50-0.83 — see
    fixtures/reference-data-seed.json), so AC = (G - buffer) * factor is a
    strictly increasing linear function of G. A higher sell price can never
    produce a lower Do Not Buy Price."""
    dnbp1 = compute_bing_dnbp(price1, species, _CONFIG)
    dnbp2 = compute_bing_dnbp(price2, species, _CONFIG)
    if price1 <= price2:
        assert dnbp1 <= dnbp2
    else:
        assert dnbp1 >= dnbp2


_prices_above_buffer = st.decimals(
    min_value="0.30", max_value="1000000", places=4, allow_nan=False, allow_infinity=False
)


@given(species=_species, price=_prices_above_buffer)
def test_dnbp_never_exceeds_x(species: str, price: Decimal) -> None:
    """Bounded to avg_price_aud >= cif_buffer (0.30) so X = G - buffer is
    never negative — a real sell price is always well above the $0.30
    buffer, and "never exceeds X" only holds when X >= 0 combined with every
    seeded factor being <= 1 (all seeded factors are 0.50-0.83). Documented
    domain restriction, not a silent narrowing of the property."""
    x = price - _CONFIG.cif_buffer_per_kg
    dnbp = compute_bing_dnbp(price, species, _CONFIG)
    assert dnbp <= x


@given(
    species=_species,
    price=st.decimals(min_value="-1000000", max_value="1000000", places=6, allow_nan=False, allow_infinity=False),
)
def test_dnbp_never_produces_nan_or_inf_for_any_input(species: str, price: Decimal) -> None:
    """compute_bing_dnbp performs no division at all — (avg_price_aud -
    cif_buffer) * factor, confirmed by reading domain/engine/dnbp.py — so
    there is no denominator that could be zero. This property is therefore
    about Decimal robustness across an arbitrarily wide input range (including
    negative and extreme prices no real submission would ever carry) rather
    than a guarded division: it asserts the result always stays a finite,
    valid Decimal, with no InvalidOperation/Overflow raised."""
    result = compute_bing_dnbp(price, species, _CONFIG)
    assert isinstance(result, Decimal)
    assert result.is_finite()


def test_every_seeded_species_has_a_positive_factor_le_one():
    """The two properties above both lean on this invariant — assert it
    directly so a future reference-data change that violates it fails loudly
    here rather than producing a confusing Hypothesis counterexample."""
    for species in _SPECIES_WITH_FACTORS:
        factor = _CONFIG.dnbp_factor_by_species[species]
        assert Decimal("0") < factor <= Decimal("1"), f"{species} factor {factor} breaks the property tests' assumption"
