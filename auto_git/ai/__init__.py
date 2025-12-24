"""AI integration package."""

from .client import get_openai_client, parse_json_from_openai_response
from .commits import ask_openai_for_commits, ask_openai_for_amendments, ask_openai_for_fix

__all__ = [
    "get_openai_client",
    "parse_json_from_openai_response",
    "ask_openai_for_commits",
    "ask_openai_for_amendments",
    "ask_openai_for_fix",
]
