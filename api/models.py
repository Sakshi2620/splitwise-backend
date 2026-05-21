from django.db import models
from decimal import Decimal


class User(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    avatar_color = models.CharField(max_length=7, default='#6366f1')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'users'

    def __str__(self):
        return f"{self.name} <{self.email}>"


class Group(models.Model):
    CATEGORY_CHOICES = [
        ('trip', 'Trip'), ('flat', 'Flat'),
        ('dinner', 'Dinner'), ('other', 'Other'),
    ]
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_groups')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    currency = models.CharField(max_length=3, default='INR')

    class Meta:
        db_table = 'groups'

    def __str__(self):
        return self.name


class GroupMember(models.Model):
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='group_memberships')
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'group_members'
        unique_together = ('group', 'user')


class Expense(models.Model):
    SPLIT_MODES = [
        ('equal_all', 'Equal among all'),
        ('equal_subset', 'Equal among subset'),
        ('custom', 'Custom amounts'),
        ('shares', 'By share weights'),
    ]
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='expenses')
    paid_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='paid_expenses')
    description = models.CharField(max_length=200)
    # MONEY: stored as integer paise (1 INR = 100 paise). Never float.
    amount_paise = models.BigIntegerField()
    currency = models.CharField(max_length=3, default='INR')
    split_mode = models.CharField(max_length=20, choices=SPLIT_MODES, default='equal_all')
    date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True)
    ai_parsed = models.BooleanField(default=False)

    class Meta:
        db_table = 'expenses'
        ordering = ['-date', '-created_at']

    @property
    def amount_display(self):
        return str(Decimal(self.amount_paise) / 100)

    @property
    def amount_rupees(self):
        return Decimal(self.amount_paise) / 100


class ExpenseShare(models.Model):
    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name='shares')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='expense_shares')
    # Amount owed by this user for this expense, in integer paise
    amount_paise = models.BigIntegerField()
    share_weight = models.IntegerField(default=1)

    class Meta:
        db_table = 'expense_shares'
        unique_together = ('expense', 'user')