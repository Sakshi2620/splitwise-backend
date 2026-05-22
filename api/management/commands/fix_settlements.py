from django.core.management.base import BaseCommand
from django.db.models import Sum
from api.models import Settlement, ExpenseShare

class Command(BaseCommand):
    help = 'Recalculate total_paise for settlements from expense shares and update status.'

    def handle(self, *args, **options):
        fixed = 0
        for s in Settlement.objects.all():
            outstanding = ExpenseShare.objects.filter(
                member=s.from_member,
                expense__group=s.group,
                expense__paid_by_member=s.to_member,
            ).aggregate(total=Sum('amount_paise'))['total'] or 0
            old_total = s.total_paise
            s.total_paise = (s.paid_paise or 0) + (outstanding or 0)
            if s.remaining_paise == 0:
                s.status = 'completed'
            elif s.paid_paise > 0:
                s.status = 'partial'
            else:
                s.status = 'pending'
            s.save()
            if s.total_paise != old_total:
                fixed += 1
                self.stdout.write(f'Updated Settlement {s.id}: old_total={old_total}, new_total={s.total_paise}, paid={s.paid_paise}, remaining={s.remaining_paise}, status={s.status}')
        self.stdout.write(self.style.SUCCESS(f'Fixed {fixed} settlements'))
