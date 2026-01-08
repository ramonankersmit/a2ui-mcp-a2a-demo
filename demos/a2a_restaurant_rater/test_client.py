import json
import os
import uuid
from typing import Any, Dict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _post_json(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers={"Content-Type": "application/json"})
    with urlopen(request) as response:
        body = response.read().decode("utf-8")
        if response.status != 200:
            raise SystemExit(f"HTTP error {response.status}: {body}")
        return json.loads(body)


def main() -> None:
    port = int(os.getenv("A2A_RATER_PORT", "8002"))
    base_url = f"http://localhost:{port}"
    endpoint = f"{base_url}/"

    payload = {
        "restaurants": [
            {
                "id": "r1",
                "name": "Canal Bistro",
                "cuisine": "French",
                "rating": 4.7,
                "price_level": 3,
                "distance_km": 1.2,
            },
            {
                "id": "r2",
                "name": "Noord Pizza Lab",
                "cuisine": "Italian",
                "rating": 4.5,
                "price_level": 2,
                "distance_km": 2.4,
            },
            {
                "id": "r3",
                "name": "Budget Bites",
                "cuisine": "Italian",
                "rating": 4.1,
                "price_level": 1,
                "distance_km": 4.0,
            },
        ],
        "prefs": {"cuisine": "Italian", "max_price_level": 2},
    }

    message = {
        "kind": "message",
        "messageId": str(uuid.uuid4()),
        "role": "user",
        "parts": [
            {
                "kind": "data",
                "data": payload,
                "metadata": {"mimeType": "application/json"},
            }
        ],
    }

    request_body = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "sendMessage",
        "params": {"message": message},
    }

    try:
        response = _post_json(endpoint, request_body)
    except HTTPError as error:
        error_body = error.read().decode("utf-8") if error.fp else ""
        raise SystemExit(f"HTTP error {error.code}: {error_body}")
    except URLError as error:
        raise SystemExit(f"Request failed: {error.reason}")

    print(json.dumps(response, indent=2))


if __name__ == "__main__":
    main()
