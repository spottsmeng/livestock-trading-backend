"""The single source of truth (PRD §5.3, §17.1).

    bing_dnbp = (avg_price_aud - cif_buffer) * dnbp_factor[species]

Three inputs. Nothing else in A-V or X-AF can change the published number.
This function must stay exactly this small: no avg_weight_kg, pack_cost_ph,
offal_return_ph, skin_return_ph, expected_livestock_cost_per_kg, incoterm,
standard_weight, or dnbp_benchmark in its signature — not merely unused,
physically absent, so a future change elsewhere cannot smuggle a new
dependency in. Changes here require two reviewers (§17.1).
"""

from decimal import Decimal

from domain.engine.config import EverhealthConfig


class NoDnbpFactorError(Exception):
    """Raised when `species` has no configured dnbp_factor. Caught by the
    calling layer (workings.py) and turned into a NO_DNBP_FACTOR BLOCK issue
    — never guessed, never defaulted (§5.7, §6.9)."""

    def __init__(self, species: str) -> None:
        self.species = species
        super().__init__(f"No DNBP factor configured for {species}")


def compute_bing_dnbp(avg_price_aud: Decimal, species: str, config: EverhealthConfig) -> Decimal:
    factor = config.dnbp_factor_by_species.get(species)
    if factor is None:
        raise NoDnbpFactorError(species)
    return (avg_price_aud - config.cif_buffer_per_kg) * factor
