"""
AI expense parsing via Anthropic Claude (claude-sonnet-4-20250514).
Structured JSON output with schema validation. Always fails gracefully.
"""
import os, json, re
import anthropic

EXPENSE_SYSTEM = """You are an expense parser for a group expense splitting app (India, INR default).
Parse the user's natural language into structured JSON. 

Return ONLY valid JSON (no markdown fences):
{
  "success": true,
  "confidence": "high"|"medium"|"low",
  "description": "short description",
  "amount": 1234.50,
  "currency": "INR",
  "paid_by_name": "exact name from group",
  "split_mode": "equal_all"|"equal_subset"|"custom"|"shares",
  "split_members": ["name1","name2"],
  "custom_amounts": {"name1": 500.00, "name2": 300.00},
  "notes": "",
  "parse_notes": "how you interpreted it"
}
For adjustments like "reduce X's share by Y", compute the final custom_amounts.
If parsing is impossible: {"success": false, "error": "reason"}"""

BILL_SYSTEM = """You are a receipt parser for a group expense app.
Return ONLY valid JSON (no markdown):
{
  "success": true,
  "restaurant_name": "name or null",
  "total_amount": 1234.50,
  "currency": "INR",
  "line_items": [{"name": "item", "quantity": 1, "price": 150.00}],
  "taxes": [{"name": "GST", "amount": 45.00}],
  "notes": ""
}
If parsing fails: {"success": false, "error": "reason"}"""


def _call_claude(system, user_msg):
    api_key = os.getenv('ANTHROPIC_API_KEY', '')
    if not api_key:
        return None, 'ANTHROPIC_API_KEY not configured'
    try:
        client = anthropic.Anthropic(api_key=api_key)
        r = client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=800,
            system=system,
            messages=[{'role': 'user', 'content': user_msg}],
        )
        raw = r.content[0].text.strip()
        raw = re.sub(r'^```(?:json)?\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw)
        return json.loads(raw), None
    except json.JSONDecodeError as e:
        return None, f'Invalid JSON from AI: {e}'
    except anthropic.APIError as e:
        return None, f'AI API error: {e}'
    except Exception as e:
        return None, f'Unexpected error: {e}'


def parse_expense_text(text: str, group_members: list) -> dict:
    member_list = ', '.join(m['name'] for m in group_members)
    prompt = f"Group members: {member_list}\n\nExpense: {text}"
    data, err = _call_claude(EXPENSE_SYSTEM, prompt)

    if err:
        return {'success': False, 'error': err, 'fallback': True}
    if not data.get('success'):
        return {'success': False, 'error': data.get('error', 'Parse failed'), 'fallback': True}

    # Resolve names → member objects
    def find_member(name):
        nl = name.lower()
        for m in group_members:
            if m['name'].lower() == nl or nl in m['name'].lower():
                return m
        return None

    paid_by = find_member(data.get('paid_by_name', ''))
    split_members = [find_member(n) for n in data.get('split_members', [])]
    split_members = [m for m in split_members if m]

    custom_amounts = {}
    for name, amt in (data.get('custom_amounts') or {}).items():
        m = find_member(name)
        if m:
            custom_amounts[str(m['id'])] = float(amt)

    return {
        'success': True,
        'confidence': data.get('confidence', 'medium'),
        'description': data.get('description', ''),
        'amount': float(data.get('amount', 0)),
        'currency': data.get('currency', 'INR'),
        'paid_by': paid_by,
        'split_mode': data.get('split_mode', 'equal_all'),
        'split_members': split_members,
        'custom_amounts': custom_amounts,
        'notes': data.get('notes', ''),
        'parse_notes': data.get('parse_notes', ''),
    }


def parse_bill_text(text: str) -> dict:
    data, err = _call_claude(BILL_SYSTEM, f'Bill:\n{text}')
    if err:
        return {'success': False, 'error': err, 'fallback': True}
    return data