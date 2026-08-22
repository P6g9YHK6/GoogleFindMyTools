"""Canned starting points for the Register form's identity fields (display
name/device type/manufacturer/model/image URL - see webui/identity_validation.py
and SpotApi/CreateBleDevice/create_ble_device.py's register_esp32()).

Picking one of these in the Firmware page's "Customize identity" section just
pre-fills the form with a sensible default for that kind of build - nothing
about registering actually branches on which preset, if any, it came from,
and nothing about which preset was used is ever saved (see
webui/firmware_store.py's record_identity(), which only ever stores the five
submitted field values themselves). A preset is a one-time template for
starting a *new* registration, not an ongoing property of one - same spirit
as webui/forwarders/presets.py's own docstring for the forwarding presets.

image_url is a real photo of that kind of item for the six object presets
(sourced from Wikimedia Commons, stable/CC-licensed rather than an
unreviewed third-party hotlink), and the same board photo
webui/firmware_store.py's DEFAULT_IDENTITY already ships with for the two
bare-hardware presets. manufacturer_name is left as "GoogleFindMyTools"
throughout - only display_name, device_type, model_name and image_url
actually vary per preset, since those are what changes the icon/label/photo
shown in Google's Find My Device app for a given kind of build.

Adding a new one here needs no new Python function, just a new entry below -
same discipline as webui/forwarders/presets.py.
"""

from webui.firmware_store import DEFAULT_IDENTITY

_MANUFACTURER = DEFAULT_IDENTITY["manufacturer_name"]

PRESETS: dict[str, dict] = {
    "esp32_devkit": {
        "label": "ESP32 DevKit",
        "hint": "Labeled as the bare board itself rather than any particular item - same photo this form already defaults to.",
        "display_name": "GFMT ESP32 DevKit",
        "device_type": "DEVICE_TYPE_BEACON",
        "manufacturer_name": _MANUFACTURER,
        "model_name": "ESP32 Dev Module",
        "image_url": DEFAULT_IDENTITY["image_url"],
    },
    "esp32c3_devkit": {
        "label": "ESP32-C3 DevKit",
        "hint": "Labeled as the bare board itself - same idea as the ESP32 DevKit preset, but with an ESP32-C3-DevKitM-1's own photo.",
        "display_name": "GFMT ESP32-C3 DevKit",
        "device_type": "DEVICE_TYPE_BEACON",
        "manufacturer_name": _MANUFACTURER,
        "model_name": "ESP32-C3 Dev Module",
        "image_url": "https://docs.espressif.com/projects/esp-idf/en/v4.3/esp32c3/_images/esp32-c3-devkitm-1-v1-isometric.png",
    },
    "keys": {
        "label": "Keys",
        "hint": "A keyring build - shows the key icon in Google's Find My Device app.",
        "display_name": "GFMT Keys Tracker",
        "device_type": "DEVICE_TYPE_KEYS",
        "manufacturer_name": _MANUFACTURER,
        "model_name": "Keys",
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/a/a0/Keychain.jpg",
    },
    "bag": {
        "label": "Bag",
        "hint": "For a backpack or handbag - shows the bag icon in Google's Find My Device app.",
        "display_name": "GFMT Bag Tracker",
        "device_type": "DEVICE_TYPE_BAG",
        "manufacturer_name": _MANUFACTURER,
        "model_name": "Bag",
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/2/2c/School_bag_backpack.jpg",
    },
    "bike": {
        "label": "Bike",
        "hint": "For a bicycle - shows the bike icon in Google's Find My Device app.",
        "display_name": "GFMT Bike Tracker",
        "device_type": "DEVICE_TYPE_BIKE",
        "manufacturer_name": _MANUFACTURER,
        "model_name": "Bike",
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/e/eb/Single-speed_mountain_bike.jpg",
    },
    "pet_collar": {
        "label": "Pet collar",
        "hint": (
            "For a cat or dog collar - defaults to the dog icon; pick DEVICE_TYPE_CAT "
            "in the dropdown below instead if you'd rather have the cat one."
        ),
        "display_name": "GFMT Pet Collar",
        "device_type": "DEVICE_TYPE_DOG",
        "manufacturer_name": _MANUFACTURER,
        "model_name": "Pet Collar",
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/b/bc/083006_Romeo_collar_web.jpg",
    },
    "bootleg_airtag": {
        "label": "Bootleg Airtag",
        "hint": "Yours if you want it.",
        "display_name": "Bootleg Airtag",
        "device_type": "DEVICE_TYPE_BEACON",
        "manufacturer_name": "Bickbutt inc.",
        "model_name": "ROFL",
        "image_url": "https://raw.githubusercontent.com/gist/nothub/699a85b808276a406c2c3122a4761b8a/raw/354c91350739b78adb10ebba8a4bb7405dfc924f/dickbutt.svg",
    },
}
