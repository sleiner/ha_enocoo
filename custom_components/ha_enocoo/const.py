"""Constants for enocoo."""

import datetime as dt
from logging import Logger, getLogger
from typing import Final

LOGGER: Logger = getLogger(__package__)

DOMAIN = "ha_enocoo"

ATTR_READOUT_TIME: Final = "readout_time"
ATTR_ENOCOO_AREA: Final = "enocoo_area"
ATTR_MEASUREMENT_START: Final = "measurement_start"
ATTR_MEASUREMENT_END: Final = "measurement_end"
ATTR_MEASUREMENT_DURATION: Final = "measurement_duration"

CONF_NUM_SHARES: Final = "num_shares"
CONF_NUM_SHARES_TOTAL: Final = "num_shares_total"

SUBENTRY_TYPE_OWNERSHIP_SHARES: Final = "ownership_shares"

# The interval in which the enocoo dashboard updates
UPDATE_INTERVAL: Final[dt.timedelta] = dt.timedelta(minutes=15)
