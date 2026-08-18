#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

import json
import os


def get_example_data(identifier: str) -> str:
    try:
        with open(_get_example_file()) as file:
            data = json.load(file)
    except OSError as e:
        raise ValueError("example_data.json is missing or unreadable.") from e
    except json.JSONDecodeError as e:
        raise ValueError("example_data.json is not valid JSON.") from e

    value = data.get(identifier)
    if value is None:
        raise ValueError(f"'{identifier}' was not found in example_data.json.")
    return value


def _get_example_file() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, 'example_data.json')