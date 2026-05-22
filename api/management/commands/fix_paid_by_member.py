from django.core.management.base import BaseCommand
from django.db import transaction
from api.models import Expense, GroupMember

class Command(BaseCommand):
    help = 'Populate missing paid_by_member on expenses using safe heuristics'

    def handle(self, *args, **options):
        fixed = []
        ambiguous = []
        with transaction.atomic():
            for e in Expense.objects.select_related('group', 'paid_by').prefetch_related('shares__user').filter(paid_by_member__isnull=True):
                # Heuristic 1: map from paid_by user to group member
                if e.paid_by:
                    gm = GroupMember.objects.filter(group=e.group, user=e.paid_by).first()
                    if gm:
                        e.paid_by_member = gm
                        e.save(update_fields=['paid_by_member'])
                        fixed.append((e.id, 'mapped_from_paid_by'))
                        continue
                # Heuristic 2: use first share.user that matches a group member
                share_users = [s.user for s in e.shares.all() if s.user]
                if share_users:
                    gm = GroupMember.objects.filter(group=e.group, user=share_users[0]).first()
                    if gm:
                        e.paid_by_member = gm
                        e.paid_by = gm.user
                        e.save(update_fields=['paid_by_member', 'paid_by'])
                        fixed.append((e.id, 'mapped_from_share_user'))
                        continue
                # Heuristic 3: if group has exactly one non-pending member, use them
                non_pending = e.group.members.filter(is_pending=False)
                if non_pending.count() == 1:
                    gm = non_pending.first()
                    if gm.user:
                        e.paid_by_member = gm
                        e.paid_by = gm.user
                        e.save(update_fields=['paid_by_member', 'paid_by'])
                        fixed.append((e.id, 'mapped_from_single_member'))
                        continue
                # Ambiguous
                ambiguous.append(e.id)
        self.stdout.write(self.style.SUCCESS(f'Fixed {len(fixed)} expenses'))
        if fixed:
            for fid, why in fixed:
                self.stdout.write(f'  - expense {fid}: {why}')
        if ambiguous:
            self.stdout.write(self.style.WARNING(f'{len(ambiguous)} ambiguous expenses left: {ambiguous}'))
