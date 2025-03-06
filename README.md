# enocoo integration

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

**This integration will set up the following platforms.**

| Platform | Description                                                                           |
| -------- | ------------------------------------------------------------------------------------- |
| `sensor` | Shows the current status of the energy "traffic light" as well as the utility meters. |

## Installation

## Via [HACS][hacs] (recommended)

First, [set up HACS][hacs-use].
Afterwards, you can install the extension by clicking on the link below:

[![Open HACS repository on My Home Assistant][my-ha-open-hacs-repository]][my-ha-this-hacs-repository]

When the integration is installed and Home Assistant was rebooted, you can add an Enocoo dashboard account here:

[![Add integration to My Home Assistant][my-ha-add-integration]][my-ha-add-this-integration]

## Manually (not recommended)

If you can not use HACS (or do not want to), manual installation is still possible:

1. Using the tool of choice open the directory (folder) for your HA configuration (where you find `configuration.yaml`).
1. If you do not have a `custom_components` directory (folder) there, you need to create it.
1. In the `custom_components` directory (folder) create a new folder called `ha_enocoo`.
1. Download _all_ the files from the `custom_components/ha_enocoo/` directory (folder) in this repository.
1. Place the files you downloaded in the new directory (folder) you created.
1. Restart Home Assistant
1. In the HA UI go to "Configuration" -> "Integrations" click "+" and search for "enocoo"

## Configuration is done in the UI

<!---->

---

[commits-shield]: https://img.shields.io/github/commit-activity/y/sleiner/ha_enocoo.svg?style=for-the-badge
[commits]: https://github.com/sleiner/ha_enocoo/commits/main
[hacs]: https://hacs.xyz
[hacs-use]: https://hacs.xyz/docs/use/
[license-shield]: https://img.shields.io/github/license/sleiner/ha_enocoo.svg?style=for-the-badge
[my-ha-add-integration]: https://my.home-assistant.io/badges/config_flow_start.svg
[my-ha-add-this-integration]: https://my.home-assistant.io/redirect/config_flow_start/?domain=ha_enocoo
[my-ha-open-hacs-repository]: https://my.home-assistant.io/badges/hacs_repository.svg
[my-ha-this-hacs-repository]: https://my.home-assistant.io/redirect/hacs_repository/?repository=ha_enocoo&owner=sleiner
[releases-shield]: https://img.shields.io/github/release/sleiner/ha_enocoo.svg?style=for-the-badge
[releases]: https://github.com/sleiner/ha_enocoo/releases
