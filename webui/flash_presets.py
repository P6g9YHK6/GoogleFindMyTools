"""Canned starting points for the Firmware page's Advanced build settings
(device name, advertising interval, TX power, unwanted-tracking-protection
flag - see webui/firmware_build.py). Picking one of these just pre-fills the
Advanced section with a sensible default for that kind of build; nothing
about building actually branches on which preset, if any, it came from, and
nothing about which preset was used is ever saved (see
webui/firmware_store.py's record_build_settings(), which only ever stores
the four submitted values themselves - same spirit as
webui/registration_presets.py's own docstring for the identity presets, and
the first six keys below match those one-for-one).

tracking_protection is left enabled (True) in every preset here on purpose -
these differ only on the legitimate battery-life/range/discoverability
tradeoffs a given build's use case actually calls for, never on whether the
firmware advertises itself as trackable. Anyone who wants it off can still
flip that dropdown by hand afterward.

min_power/max_power sit at the two ends of the range firmware_build.py
itself enforces (_ADV_INTERVAL_MIN_MS/_ADV_INTERVAL_MAX_MS and the TX power
enum's lowest/highest entries) rather than at a particular item's tradeoff,
for anyone who'd rather pick an extreme directly than match it to a use case.

Adding a new one here needs no new Python function, just a new entry below -
same discipline as webui/forwarders/presets.py.
"""

PRESETS: dict[str, dict] = {
    "keys": {
        "label": "Keys",
        "hint": "Everyday-carry keys are easy to recharge often, so this favors fast discovery over battery life.",
        "device_name": "Keys Tracker",
        "adv_interval_ms": 20,
        "tx_power_dbm": 9,
        "tracking_protection": True,
    },
    "bag": {
        "label": "Bag",
        "hint": "A middle ground for a backpack or handbag carried daily but not charged as often as keys.",
        "device_name": "Bag Tracker",
        "adv_interval_ms": 320,
        "tx_power_dbm": 3,
        "tracking_protection": True,
    },
    "bike": {
        "label": "Bike",
        "hint": (
            "Parked outdoors and often further from your phone than an everyday item - keeps full TX "
            "power for range, with a longer interval to help the battery last between charges."
        ),
        "device_name": "Bike Tracker",
        "adv_interval_ms": 100,
        "tx_power_dbm": 9,
        "tracking_protection": True,
    },
    "luggage": {
        "label": "Luggage",
        "hint": "Checked bags can sit untouched for days, so this leans hard toward battery life over how quickly it's found.",
        "device_name": "Luggage Tracker",
        "adv_interval_ms": 1280,
        "tx_power_dbm": 6,
        "tracking_protection": True,
    },
    "wallet": {
        "label": "Wallet",
        "hint": "Small battery, mostly indoors and close at hand - lower TX power and a longer interval to stretch runtime.",
        "device_name": "Wallet Tracker",
        "adv_interval_ms": 2560,
        "tx_power_dbm": -3,
        "tracking_protection": True,
    },
    "pet_collar": {
        "label": "Pet collar",
        "hint": "Meant to run for weeks between charges on a collar, but still findable outdoors if it comes off.",
        "device_name": "Pet Collar",
        "adv_interval_ms": 640,
        "tx_power_dbm": 6,
        "tracking_protection": True,
    },
    "min_power": {
        "label": "Min power (max battery life)",
        "hint": (
            "The slowest advertising interval and lowest TX power this firmware allows - longest "
            "possible battery life, at the cost of discoverability and range."
        ),
        "device_name": "Min Power",
        "adv_interval_ms": 10240,
        "tx_power_dbm": -12,
        "tracking_protection": True,
    },
    "max_power": {
        "label": "Max power (max range)",
        "hint": (
            "The fastest advertising interval and highest TX power this firmware allows - best "
            "possible discoverability and range, at the cost of battery life."
        ),
        "device_name": "Max Power",
        "adv_interval_ms": 20,
        "tx_power_dbm": 9,
        "tracking_protection": True,
    },
}
