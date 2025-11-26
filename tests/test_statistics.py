"""Tests for the _statistics module."""

import pytest
from oocone.model import ConsumptionType

from custom_components.ha_enocoo._statistics import StatisticsInserter


class TestStatisticsInserter:
    """Tests for the StatisticsInserter class."""

    @staticmethod
    def test_consumption_type_to_unit_class_implemented_for_all_types(
        subtests: pytest.Subtests,
    ) -> None:
        """Check that _consumption_type_to_unit_class works for all ConsumptionTypes."""
        for type_ in ConsumptionType:
            with subtests.test(type=type_):
                unit_class = StatisticsInserter._consumption_type_to_unit_class(type_)  # noqa: SLF001
                assert unit_class
