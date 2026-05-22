import os
import json
import re
import requests

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _call_ai(system_prompt, user_prompt):
    if not OPENROUTER_API_KEY:
        return None, "OPENROUTER_API_KEY not configured in .env"

    try:
        response = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:3000",
                "X-Title": "SplitSmart",
            },
            json={
                "model": "anthropic/claude-3.5-sonnet-20241022",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                "temperature": 0.2,
            },
            timeout=30,
        )

        if response.status_code != 200:
            return None, f"OpenRouter API error {response.status_code}: {response.text[:300]}"

        data = response.json()

        if "choices" not in data:
            return None, f"Unexpected response: {data}"

        raw = data["choices"][0]["message"]["content"]
        return raw, None

    except requests.exceptions.Timeout:
        return None, "AI request timed out"
    except requests.exceptions.ConnectionError:
        return None, "Could not connect to OpenRouter"
    except Exception as e:
        return None, f"Unexpected error: {e}"


def _extract_json(text):
    """Strip markdown fences and extract first JSON object."""
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("No valid JSON object found in AI response")
    return json.loads(match.group())


EXPENSE_SYSTEM = """You are an expense parser for a group splitting app used in India (INR default).
Parse the user's natural language expense description into structured JSON.

Return ONLY a valid JSON object, no markdown, no explanation:
{
  "success": true,
  "confidence": "high",
  "description": "short description of the expense",
  "amount": 1234.50,
  "currency": "INR",
  "paid_by_name": "name of person who paid",
  "split_mode": "equal_all",
  "split_members": ["Name1", "Name2"],
  "custom_amounts": {},
  "notes": "",
  "parse_notes": "brief explanation of interpretation"
}

Rules:
- split_mode must be one of: equal_all, equal_subset, custom, shares
- For "reduce X's share by Y" or "X didn't have Z", compute final custom_amounts
- confidence: high if all fields clear, medium if some guessed, low if uncertain
- If parsing is impossible return: {"success": false, "error": "reason"}"""

BILL_SYSTEM = """You are a receipt/bill parser for a group expense app in India.
Parse the raw bill text into structured JSON.

Return ONLY a valid JSON object, no markdown, no explanation:
{
  "success": true,
  "restaurant_name": "name or null",
  "total_amount": 1234.50,
  "currency": "INR",
  "line_items": [
    {"name": "item name", "quantity": 1, "price": 150.00}
  ],
  "taxes": [
    {"name": "GST", "amount": 45.00}
  ],
  "notes": ""
}

If parsing fails return: {"success": false, "error": "reason"}"""


def parse_expense_text(text: str, group_members: list) -> dict:
    """
    Parse natural language expense into structured data.
    group_members: list of {id, name} dicts
    """
    member_list = ", ".join(m["name"].strip() for m in group_members)
    user_prompt = f"Group members: {member_list}\n\nExpense description: {text}"

    raw, err = _call_ai(EXPENSE_SYSTEM, user_prompt)
    if err:
        return {"success": False, "error": err, "fallback": True}

    try:
        parsed = _extract_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        return {"success": False, "error": f"AI returned invalid JSON: {e}", "fallback": True}

    if not parsed.get("success"):
        return {"success": False, "error": parsed.get("error", "Parse failed"), "fallback": True}

    # Resolve member names → member objects (case-insensitive)
    def find_member(name):
        nl = (name or "").lower().strip()
        for m in group_members:
            if m["name"].lower() == nl or nl in m["name"].lower():
                return m
        return None

    paid_by = find_member(parsed.get("paid_by_name", ""))
    split_members = [
        find_member(n) for n in (parsed.get("split_members") or [])
    ]
    split_members = [m for m in split_members if m]

    custom_amounts = {}
    for name, amt in (parsed.get("custom_amounts") or {}).items():
        m = find_member(name)
        if m:
            custom_amounts[str(m["id"])] = float(amt)

    return {
        "success": True,
        "confidence": parsed.get("confidence", "medium"),
        "description": parsed.get("description", ""),
        "amount": float(parsed.get("amount", 0)),
        "currency": parsed.get("currency", "INR"),
        "paid_by": paid_by,
        "split_mode": parsed.get("split_mode", "equal_all"),
        "split_members": split_members,
        "custom_amounts": custom_amounts,
        "notes": parsed.get("notes", ""),
        "parse_notes": parsed.get("parse_notes", ""),
    }


def parse_bill_text(text: str) -> dict:
    """Parse raw bill/receipt text into structured line items."""
    raw, err = _call_ai(BILL_SYSTEM, f"Bill text:\n{text}")
    if err:
        return {"success": False, "error": err, "fallback": True}

    try:
        parsed = _extract_json(raw)
        return parsed
    except (ValueError, json.JSONDecodeError) as e:
        return {"success": False, "error": f"AI returned invalid JSON: {e}", "fallback": True}