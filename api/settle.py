import heapq
from collections import defaultdict
from decimal import Decimal

def compute_balances(group):
    balances = defaultdict(int)

    # Build user_id → member lookup as fallback for old expenses
    user_to_member = {
        m.user_id: m.id
        for m in group.members.all()
        if m.user_id is not None
    }

    for expense in group.expenses.prefetch_related(
        'shares__member', 'shares__user'
    ).select_related('paid_by_member', 'paid_by').all():

        # Resolve payer member_id — new way first, fallback to user lookup
        payer_mid = expense.paid_by_member_id
        if not payer_mid and expense.paid_by_id:
            payer_mid = user_to_member.get(expense.paid_by_id)

        if payer_mid:
            balances[payer_mid] += expense.amount_paise

        for share in expense.shares.all():
            mid = share.member_id
            if not mid and share.user_id:
                mid = user_to_member.get(share.user_id)
            if mid:
                balances[mid] -= share.amount_paise

    return dict(balances)

def compute_settlements(group):
    """Returns list of {from_member_id, to_member_id, amount_paise}."""
    balances = compute_balances(group)
    creditors, debtors = [], []

    for mid, bal in balances.items():
        if bal > 0:
            heapq.heappush(creditors, (-bal, mid))
        elif bal < 0:
            heapq.heappush(debtors, (bal, mid))

    transactions = []
    while creditors and debtors:
        credit_neg, creditor = heapq.heappop(creditors)
        debt_neg,   debtor   = heapq.heappop(debtors)
        credit  = -credit_neg
        debt    = -debt_neg
        settled = min(credit, debt)
        transactions.append({
            'from_member_id': debtor,
            'to_member_id':   creditor,
            'amount_paise':   settled,
        })
        if credit > settled:
            heapq.heappush(creditors, (-(credit - settled), creditor))
        if debt > settled:
            heapq.heappush(debtors,   (-(debt - settled),   debtor))

    return transactions


def get_balance_summary(group):
    from .models import GroupMember

    balances     = compute_balances(group)
    transactions = compute_settlements(group)

    # Load all members (real + pending) keyed by member.id
    all_member_ids = (
        set(balances.keys())
        | {t['from_member_id'] for t in transactions}
        | {t['to_member_id']   for t in transactions}
    )
    members = {
        m.id: m
        for m in GroupMember.objects.filter(id__in=all_member_ids).select_related('user')
    }

    def member_dict(mid):
        m = members.get(mid)
        if not m:
            return {'id': None, 'name': '?', 'avatar_color': '#94a3b8'}
        if m.user:
            return {
                'id':           m.user.id,
                'name':         m.user.name,
                'avatar_color': m.user.avatar_color,
            }
        # Pending member
        colors = ['#6366f1','#ec4899','#10b981','#f59e0b','#3b82f6','#8b5cf6','#ef4444','#14b8a6']
        idx    = sum(ord(c) for c in (m.invited_email or '')) % len(colors)
        return {
            'id':           None,
            'name':         m.invited_name or m.invited_email or '?',
            'avatar_color': colors[idx],
        }

    return {
        'balances': [
            {
                'user':       member_dict(mid),
                'net_paise':  bal,
                'net_rupees': str(Decimal(bal) / 100),
                'status':     'owed' if bal > 0 else ('owes' if bal < 0 else 'settled'),
            }
            for mid, bal in balances.items()
        ],
        'settlements': [
            {
                'from_user':    member_dict(t['from_member_id']),
                'to_user':      member_dict(t['to_member_id']),
                'amount_paise': t['amount_paise'],
                'amount_rupees': str(Decimal(t['amount_paise']) / 100),
            }
            for t in transactions
        ],
        'total_transactions': len(transactions),
    }