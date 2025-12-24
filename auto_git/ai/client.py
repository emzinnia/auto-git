"""OpenAI client setup and connection utilities."""

import json
import os
import re

import openai


def get_openai_client():
    """
    Get an OpenAI client, reading API key from environment or .env file.

    Raises RuntimeError if no API key is found.
    """
    api_key = os.environ.get("OPEN_AI_API_KEY")

    if not api_key:
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as env_file:
                for line in env_file:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    if key.strip() == "OPEN_AI_API_KEY":
                        api_key = value.strip().strip('"').strip("'")
                        break

    if not api_key:
        raise RuntimeError("OPEN_AI_API_KEY is not set in the environment or .env file")

    return openai.OpenAI(api_key=api_key)


def parse_json_from_openai_response(text):
    """
    Parse JSON from an OpenAI response, handling markdown code blocks.

    Args:
        text: Raw response text from OpenAI

    Returns:
        Parsed JSON object
    """
    stripped = (text or "").strip()

    # If the response contains a fenced code block, prefer its contents.
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped, flags=re.IGNORECASE)
    if m:
        stripped = m.group(1).strip()

    # Trim any leading prose before the first JSON token.
    starts = [i for i in (stripped.find("["), stripped.find("{")) if i != -1]
    if starts:
        stripped = stripped[min(starts) :]

    # Parse the first JSON value and ignore any trailing noise.
    obj, _end = json.JSONDecoder().raw_decode(stripped)
    return obj
