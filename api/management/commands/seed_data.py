from django.core.management.base import BaseCommand
from datetime import date, timedelta
from api.models import User, Group, GroupMember, Expense, ExpenseShare

USERS = [
    {'name': 'Arjun Sharma',  'email': 'arjun@example.com',  'avatar_color': '#6366f1'},
    {'name': 'Priya Mehta',   'email': 'priya@example.com',   'avatar_color': '#ec4899'},
    {'name': 'Aman Verma',    'email': 'aman@example.com',    'avatar_color': '#10b981'},
    {'name': 'Trupti Desai',  'email': 'trupti@example.com',  'avatar_color': '#f59e0b'},
    {'name': 'Rohit Kapoor',  'email': 'rohit@example.com',   'avatar_color': '#3b82f6'},
    {'name': 'Sneha Nair',    'email': 'sneha@example.com',   'avatar_color': '#8b5cf6'},
    {'name': 'Karan Joshi',   'email': 'karan@example.com',   'avatar_color': '#ef4444'},
    {'name': 'Meera Pillai',  'email': 'meera@example.com',   'avatar_color': '#14b8a6'},
]

class Command(BaseCommand):
    help = 'Seed DB with sample data'

    def handle(self, *args, **options):
        ExpenseShare.objects.all().delete()
        Expense.objects.all().delete()
        GroupMember.objects.all().delete()
        Group.objects.all().delete()
        User.objects.all().delete()

        users = [User.objects.create(**u) for u in USERS]
        arjun, priya, aman, trupti, rohit, sneha, karan, meera = users

        goa     = Group.objects.create(name='Goa Trip',         category='trip',   created_by=arjun, description='March break — Goa')
        flat    = Group.objects.create(name='Flat 4B',          category='flat',   created_by=sneha, description='Monthly flat expenses')
        dinners = Group.objects.create(name='Saturday Dinners', category='dinner', created_by=priya, description='Weekly dinner gang')

        goa_m  = [arjun, priya, aman, trupti, rohit]
        flat_m = [arjun, sneha, karan, meera]
        din_m  = users

        for g, mlist in [(goa, goa_m), (flat, flat_m), (dinners, din_m)]:
            for u in mlist:
                GroupMember.objects.create(group=g, user=u)

        def eq(group, payer, desc, inr, members, days_ago):
            p = int(inr * 100)
            e = Expense.objects.create(group=group, paid_by=payer, description=desc,
                amount_paise=p, split_mode='equal_subset', date=date.today()-timedelta(days=days_ago))
            per, rem = p // len(members), p % len(members)
            for i, u in enumerate(members):
                ExpenseShare.objects.create(expense=e, user=u, amount_paise=per+(1 if i<rem else 0))

        def custom(group, payer, desc, inr, amounts, days_ago):
            p = int(inr * 100)
            e = Expense.objects.create(group=group, paid_by=payer, description=desc,
                amount_paise=p, split_mode='custom', date=date.today()-timedelta(days=days_ago))
            for u, amt in amounts.items():
                ExpenseShare.objects.create(expense=e, user=u, amount_paise=int(amt*100))

        # Goa Trip
        eq(goa, arjun,  'Hotel booking (3 nights)',  18000, goa_m,       30)
        eq(goa, priya,  'Taxi from airport',          2400,  goa_m,       29)
        eq(goa, aman,   'Beach shack dinner',         4800,  goa_m,       29)
        eq(goa, trupti, 'Water sports',               7500,  goa_m,       28)
        eq(goa, rohit,  "Fisherman's Wharf lunch",    3200,  goa_m,       28)
        eq(goa, arjun,  'Scooter rental',             1800,  [arjun,aman],27)
        eq(goa, priya,  'Spice plantation tour',      2500,  [priya,trupti,rohit], 27)
        eq(goa, aman,   'Departure lunch',            2100,  goa_m,       26)

        # Flat 4B
        eq(flat, sneha, 'Rent (April)', 48000, flat_m, 45)
        eq(flat, karan, 'Electricity',   3200, flat_m, 30)
        eq(flat, arjun, 'Internet',      1199, flat_m, 30)
        eq(flat, meera, 'Groceries',     2840, flat_m, 15)
        eq(flat, sneha, 'Rent (May)',   48000, flat_m,  5)
        eq(flat, karan, 'Cleaning',       650, flat_m,  3)
        eq(flat, arjun, 'Gas cylinder',   980, flat_m,  2)

        # Saturday Dinners
        eq(dinners, priya, 'Dinner at Bastian', 9600,  din_m, 7)
        eq(dinners, karan, 'Drinks at Social',  4200,  din_m, 7)
        eq(dinners, meera, 'Pizza night',       3800,  din_m, 14)
        eq(dinners, rohit, 'Sushi dinner',     11200,  din_m, 21)
        custom(dinners, arjun, 'BBQ (custom split)', 6400,
               {arjun:2000, priya:2000, aman:1200, trupti:1200}, 28)
        eq(dinners, sneha, "Aman's birthday cake", 1800,
           [arjun,priya,trupti,rohit,sneha,karan,meera], 35)

        self.stdout.write(self.style.SUCCESS(
            f'Done: {User.objects.count()} users, '
            f'{Group.objects.count()} groups, '
            f'{Expense.objects.count()} expenses'
        ))