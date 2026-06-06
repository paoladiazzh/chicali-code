"""
LLM Engine – Gemini API Interface
===================================
Handles all interactions with the Google Gemini API via the OpenAI-compatible endpoint.
Extracts and returns usage_metadata (token counts) from every response.
"""

import os
import json
import time
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

# ─── Gemini Client ────────────────────────────────────────────────────────────────
_client = AsyncOpenAI(
    api_key=os.getenv("GEMINI_API_KEY"),
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Cost per 1M tokens (approximate for Gemini 2.5 Flash)
COST_PER_1M_INPUT_TOKENS = 0.15
COST_PER_1M_OUTPUT_TOKENS = 0.60


@dataclass
class LLMResponse:
    """Structured response from an LLM call including token metrics."""
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost: float = 0.0
    model: str = ""
    latency_ms: float = 0.0


@dataclass
class TokenTracker:
    """Accumulates token usage across multiple LLM calls."""
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    call_count: int = 0
    history: list = field(default_factory=list)

    def record(self, response: LLMResponse):
        self.total_prompt_tokens += response.prompt_tokens
        self.total_completion_tokens += response.completion_tokens
        self.total_tokens += response.total_tokens
        self.total_cost += response.estimated_cost
        self.call_count += 1
        self.history.append({
            "call_number": self.call_count,
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "total_tokens": response.total_tokens,
            "cost": response.estimated_cost,
            "latency_ms": response.latency_ms,
            "timestamp": time.time(),
        })

    def to_dict(self) -> dict:
        return {
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
            "total_cost": round(self.total_cost, 6),
            "call_count": self.call_count,
            "history": self.history,
        }


# Global tracker instance
tracker = TokenTracker()


async def call_llm(system_prompt: str, user_prompt: str) -> LLMResponse:
    """
    Send a prompt to Gemini and return structured response with token metrics.
    """
    start = time.perf_counter()

    response = await _client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=4000,
    )

    latency_ms = (time.perf_counter() - start) * 1000

    # Extract usage metadata
    usage = response.usage
    prompt_tokens = usage.prompt_tokens if usage else 0
    completion_tokens = usage.completion_tokens if usage else 0
    total_tokens = (usage.total_tokens if usage else 0) or (prompt_tokens + completion_tokens)

    # Calculate cost
    cost = (
        (prompt_tokens / 1_000_000) * COST_PER_1M_INPUT_TOKENS +
        (completion_tokens / 1_000_000) * COST_PER_1M_OUTPUT_TOKENS
    )

    result = LLMResponse(
        content=response.choices[0].message.content.strip(),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        estimated_cost=cost,
        model=response.model or MODEL,
        latency_ms=round(latency_ms, 1),
    )

    # Record in global tracker
    tracker.record(result)

    return result


async def infer_mapping(origin_log: list, dest_log: list, dest_fields: list) -> dict[str, Any]:
    """
    Analyze interaction logs and infer field mapping using Gemini.
    Returns both the mapping and token usage metrics.
    """
    system_prompt = """You are an expert data-mapping analyst. You observe user interactions 
between two web systems and deduce the semantic field mapping. You MUST output ONLY valid JSON, 
no markdown, no explanation."""

    user_prompt = f"""I observed a user copying data from a source web application (an e-commerce site) 
and pasting/typing it into a destination form (an internal ERP).

Here is the interaction log from the SOURCE system (what the user clicked/copied):
{json.dumps(origin_log, indent=2)}

Here is the interaction log from the DESTINATION system (where the user pasted/typed data):
{json.dumps(dest_log, indent=2)}

Here is the structure of the destination form:
{json.dumps(dest_fields, indent=2)}

Based on these observations, produce a JSON mapping object. Each key should be a semantic 
description of the data from the origin (e.g., "product_name", "price", "first_name"), 
and each value should be an object with:
- "destination_selector": the CSS selector to target the field (use #id)
- "description": a brief note on what this field represents

Output ONLY the JSON object. Example format:
{{
    "product_name": {{
        "destination_selector": "#item_title",
        "description": "The name/title of the product"
    }}
}}
"""

    response = await call_llm(system_prompt, user_prompt)

    # Parse the mapping JSON
    try:
        cleaned = response.content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            cleaned = cleaned.rsplit("```", 1)[0]
        mapping = json.loads(cleaned)
    except json.JSONDecodeError:
        mapping = {}

    return {
        "mapping": mapping,
        "usage": {
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "total_tokens": response.total_tokens,
            "estimated_cost": response.estimated_cost,
            "latency_ms": response.latency_ms,
        }
    }


async def generate_fill_payload(page_data: dict, mapping: dict) -> dict[str, Any]:
    """
    Given scraped page data and a learned mapping, produce fill instructions.
    Returns both the fill payload and token usage metrics.
    """
    system_prompt = """You are a data-transformation agent. Given raw scraped data from a source 
web page and a field mapping schema, produce exact values to fill into the destination form.
Output ONLY valid JSON, no markdown, no explanation."""

    user_prompt = f"""Here is raw data scraped from the source e-commerce page:
{json.dumps(page_data, indent=2)}

Here is the learned field mapping (semantic_key -> destination_selector):
{json.dumps(mapping, indent=2)}

Produce a JSON object where each key is the destination CSS selector (e.g., "#item_title") 
and the value is the exact string to type into that field. Extract the appropriate data from 
the scraped source to fill each destination field.

If a field cannot be filled from the available data, omit it.

Output ONLY the JSON object. Example:
{{
    "#item_title": "Sauce Labs Backpack",
    "#unit_cost": "29.99"
}}
"""

    response = await call_llm(system_prompt, user_prompt)

    try:
        cleaned = response.content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            cleaned = cleaned.rsplit("```", 1)[0]
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        payload = {}

    return {
        "payload": payload,
        "usage": {
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "total_tokens": response.total_tokens,
            "estimated_cost": response.estimated_cost,
            "latency_ms": response.latency_ms,
        }
    }
