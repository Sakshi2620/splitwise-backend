from django.core.management.base import BaseCommand
from django.db import transaction
from api.models import Group, Settlement

class Command(BaseCommand):
    help = 'Recompute and sync settlements for all groups'

    def handle(self, *args, **options):
        from api.settle import compute_settlements

        total_created = 0
        total_updated = 0

        groups = Group.objects.all()
        for g in groups:
            transactions = compute_settlements(g)
            existing = {
                (s.from_member_id, s.to_member_id): s
                for s in Settlement.objects.filter(group=g)
            }

            seen = set()
            with transaction.atomic():
                for t in transactions:
                    key = (t['from_member_id'], t['to_member_id'])
                    seen.add(key)
                    if key in existing:
                        s = existing[key]
                        s.total_paise = t['amount_paise'] + s.paid_paise
                        if s.remaining_paise == 0:
                            s.status = 'completed'
                        elif s.paid_paise > 0:
                            s.status = 'partial'
                        else:
                            s.status = 'pending'
                        s.save()
                        total_updated += 1
                    else:
                        Settlement.objects.get_or_create(
                            group=g,
                            from_member_id=t['from_member_id'],
                            to_member_id=t['to_member_id'],
                            defaults={
                                'total_paise': t['amount_paise'],
                                'status': 'pending',
                            }
                        )
                        total_created += 1

        self.stdout.write(self.style.SUCCESS(f'Created {total_created} settlements, updated {total_updated} settlements'))
