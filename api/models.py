from django.db import models
from django.contrib.auth.models import AbstractUser
from decimal import Decimal
import uuid


class User(AbstractUser):
    email = models.EmailField(unique=True)
    avatar_color = models.CharField(max_length=7, default='#6366f1')
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username', 'first_name']

    class Meta:
        db_table = 'users'

    @property
    def name(self):
        return self.get_full_name() or self.email.split('@')[0]

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
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='created_groups'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    currency = models.CharField(max_length=3, default='INR')
    invite_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        db_table = 'groups'

    def __str__(self):
        return self.name


class GroupMember(models.Model):
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='group_memberships',
        null=True, blank=True
    )
    # For pending members who haven't registered yet
    invited_email = models.EmailField(blank=True, default='')
    invited_name  = models.CharField(max_length=100, blank=True, default='')
    joined_at  = models.DateTimeField(auto_now_add=True)
    is_admin   = models.BooleanField(default=False)
    is_pending = models.BooleanField(default=False)  # True = not yet registered

    class Meta:
        db_table = 'group_members'

    def __str__(self):
        if self.user:
            return f"{self.user.name} in {self.group.name}"
        return f"{self.invited_email} (pending) in {self.group.name}"

    @property
    def display_name(self):
        if self.user:
            return self.user.name
        return self.invited_name or self.invited_email

    @property
    def display_email(self):
        if self.user:
            return self.user.email
        return self.invited_email


class Notification(models.Model):
    TYPE_CHOICES = [
        ('group_invite', 'Group Invite'),
        ('group_joined', 'Member Joined'),
        ('expense_added', 'Expense Added'),
    ]
    user      = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    type      = models.CharField(max_length=30, choices=TYPE_CHOICES)
    title     = models.CharField(max_length=200)
    message   = models.TextField()
    is_read   = models.BooleanField(default=False)
    group     = models.ForeignKey(Group, on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']


class Expense(models.Model):
    SPLIT_MODES = [
        ('equal_all', 'Equal among all'),
        ('equal_subset', 'Equal among subset'),
        ('custom', 'Custom amounts'),
        ('shares', 'By share weights'),
    ]
    group          = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='expenses')
    paid_by        = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='expenses_paid')
    paid_by_member = models.ForeignKey('GroupMember', on_delete=models.SET_NULL, null=True, blank=True, related_name='expenses_paid')  # ← add this
    description    = models.CharField(max_length=255)
    amount_paise   = models.IntegerField(default=0)
    currency       = models.CharField(max_length=10, default='INR')
    split_mode     = models.CharField(max_length=20, default='equal_all')
    date           = models.DateField()
    notes          = models.TextField(blank=True, default='')
    ai_parsed      = models.BooleanField(default=False)
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'expenses'
        ordering = ['-date', '-created_at']

    @property
    def amount_display(self):
        return str(Decimal(self.amount_paise) / 100)


class ExpenseShare(models.Model):
    expense      = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name='shares')
    user         = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    member       = models.ForeignKey('GroupMember', on_delete=models.SET_NULL, null=True, blank=True)  # ← add this
    amount_paise = models.IntegerField(default=0)
    share_weight = models.IntegerField(default=1)

    def get_display_name(self):
        if self.user:
            return self.user.name
        if self.member:
            return self.member.invited_name or self.member.invited_email or '?'
        return '?'

    class Meta:
        db_table = 'expense_shares'
        unique_together = ('expense', 'user')