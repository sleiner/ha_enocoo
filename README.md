# enocoo integration

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

**This integration will set up the following platforms.**

| Platform | Description                                                                           |
| -------- | ------------------------------------------------------------------------------------- |
| `sensor` | Shows the current status of the energy "traffic light" as well as the utility meters. |

## Installation

1. Using the tool of choice open the directory (folder) for your HA configuration (where you find `configuration.yaml`).
1. If you do not have a `custom_components` directory (folder) there, you need to create it.
1. In the `custom_components` directory (folder) create a new folder called `ha_enocoo`.
1. Download _all_ the files from the `custom_components/ha_enocoo/` directory (folder) in this repository.
1. Place the files you downloaded in the new directory (folder) you created.
1. Restart Home Assistant
1. In the HA UI go to "Configuration" -> "Integrations" click "+" and search for "Integration blueprint"

## Configuration is done in the UI

<!---->

---

[commits-shield]: https://img.shields.io/github/commit-activity/y/sleiner/ha_enocoo.svg?style=for-the-badge
[commits]: https://github.com/sleiner/ha_enocoo/commits/main
[license-shield]: https://img.shields.io/github/license/sleiner/ha_enocoo.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/sleiner/ha_enocoo.svg?style=for-the-badge
[releases]: https://github.com/sleiner/ha_enocoo/releases
