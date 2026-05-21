"""
Settle-up algorithm — minimum transactions to clear all debts.

Algorithm (greedy on debt graph):
1. Compute net balance per person:
   net = total_paid - total_owed
   positive  → person is owed money
   negative  → person owes money
2. Use two max-heaps: creditors (positive), debtors (negative).
3. Each step: pair largest creditor with largest debtor.
   Settle min(credit, debt). Push remainder back.
4. Result: O(n) transactions where n = number of non-zero balances.
   This is optimal for the greedy approach (proven for this class of problem).

Money: all arithmetic in integer paise. Zero floats.
"""

import heapq
from collections import defaultdict
from decimal import Decimal


def compute_balances(group):
    """Net balance per user_id in paise. Positive = owed to them."""
    balances = defaultdict(int)
    for expense in group.expenses.prefetch_related('shares').all():
        balances[expense.paid_by_id] += expense.amount_paise
        for share in expense.shares.all():
            balances[share.user_id] -= share.amount_paise
    return dict(balances)


def compute_settlements(group):
    """Returns list of {from_user_id, to_user_id, amount_paise}."""
    balances = compute_balances(group)
    creditors, debtors = [], []

    for uid, bal in balances.items():
        if bal > 0:
            heapq.heappush(creditors, (-bal, uid))   # max-heap via negation
        elif bal < 0:
            heapq.heappush(debtors, (bal, uid))       # min-heap (most negative first)

    transactions = []
    while creditors and debtors:
        credit_neg, creditor = heapq.heappop(creditors)
        debt_neg, debtor = heapq.heappop(debtors)
        credit = -credit_neg
        debt = -debt_neg
        settled = min(credit, debt)
        transactions.append({'from_user_id': debtor, 'to_user_id': creditor, 'amount_paise': settled})
        if credit > settled:
            heapq.heappush(creditors, (-(credit - settled), creditor))
        if debt > settled:
            heapq.heappush(debtors, (-(debt - settled), debtor))

    return transactions


def get_balance_summary(group):
    from .models import User
    balances = compute_balances(group)
    transactions = compute_settlements(group)

    all_ids = set(balances.keys()) | {t['from_user_id'] for t in transactions} | {t['to_user_id'] for t in transactions}
    users = {u.id: u for u in User.objects.filter(id__in=all_ids)}

    def user_dict(uid):
        u = users.get(uid)
        return {'id': uid, 'name': u.name, 'avatar_color': u.avatar_color} if u else {}

    return {
        'balances': [
            {
                'user': user_dict(uid),
                'net_paise': bal,
                'net_rupees': str(Decimal(bal) / 100),
                'status': 'owed' if bal > 0 else ('owes' if bal < 0 else 'settled'),
            }
            for uid, bal in balances.items() if uid in users
        ],
        'settlements': [
            {
                'from_user': user_dict(t['from_user_id']),
                'to_user': user_dict(t['to_user_id']),
                'amount_paise': t['amount_paise'],
                'amount_rupees': str(Decimal(t['amount_paise']) / 100),
            }
            for t in transactions
        ],
        'total_transactions': len(transactions),
    }