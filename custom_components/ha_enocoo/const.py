"""Constants for enocoo."""

from logging import Logger, getLogger
from typing import Final

LOGGER: Logger = getLogger(__package__)

DOMAIN = "ha_enocoo"

ATTR_READOUT_TIME: Final = "readout_time"
ATTR_ENOCOO_AREA: Final = "enocoo_area"

CONF_NUM_SHARES: Final = "num_shares"
CONF_NUM_SHARES_TOTAL: Final = "num_shares_total"
