
import os
import json
from dotenv import load_dotenv
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY", "").strip()

if not api_key:
    print("ERROR: GEMINI_API_KEY is missing")
    raise SystemExit(1)

url = "https://generativelanguage.googleapis.com/v1beta/models"
request = Request(url, headers={"x-goog-api-key": api_key})

try:
    with urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))

    models = [
        model["name"]
        for model in data.get("models", [])
        if "generateContent" in model.get("supportedGenerationMethods", [])
    ]

    print("Available models:")
    for model in models:
        print(model)

except HTTPError as exc:
    print(f"HTTP Error: {exc.code}")
    print(exc.read().decode("utf-8")[:1000])
except URLError as exc:
    print(f"Connection error: {exc.reason}")
