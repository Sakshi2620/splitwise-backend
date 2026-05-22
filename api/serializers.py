from rest_framework import serializers
from decimal import Decimal
import re
from .models import User, Group, GroupMember, Expense, ExpenseShare, Notification

AVATAR_COLORS = [
    '#6366f1','#ec4899','#10b981','#f59e0b',
    '#3b82f6','#8b5cf6','#ef4444','#14b8a6',
]

PENDING_COLOR = '#94a3b8'


def valid_email(email):
    return re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email) is not None


def member_display(m):
    """Return a user-like dict from a GroupMember (real or pending)."""
    if m is None:
        return None
    if m.user:
        return {
            'id':           m.user.id,
            'member_id':    m.id,
            'name':         m.user.name,
            'avatar_color': m.user.avatar_color,
        }
    idx = sum(ord(c) for c in (m.invited_email or '')) % len(AVATAR_COLORS)
    return {
        'id':           None,
        'member_id':    m.id,
        'name':         m.invited_name or m.invited_email or '?',
        'avatar_color': AVATAR_COLORS[idx],
    }


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    name     = serializers.CharField(write_only=True)

    class Meta:
        model  = User
        fields = ['name', 'email', 'password']

    def create(self, validated_data):
        name  = validated_data.pop('name')
        parts = name.strip().split(' ', 1)
        first = parts[0]
        last  = parts[1] if len(parts) > 1 else ''
        import random
        color = random.choice(AVATAR_COLORS)
        user  = User.objects.create_user(
            username=validated_data['email'],
            email=validated_data['email'],
            password=validated_data['password'],
            first_name=first,
            last_name=last,
            avatar_color=color,
        )
        pending = GroupMember.objects.filter(
            invited_email__iexact=user.email, is_pending=True
        )
        for pm in pending:
            exists = GroupMember.objects.filter(group=pm.group, user=user).exists()
            if not exists:
                pm.user       = user
                pm.is_pending = False
                pm.save()
                Notification.objects.create(
                    user=user,
                    type='group_invite',
                    title=f'You were added to "{pm.group.name}"',
                    message=f'You have been added to the group "{pm.group.name}".',
                    group=pm.group,
                )
        return user


class UserSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()

    class Meta:
        model  = User
        fields = ['id', 'name', 'email', 'avatar_color', 'created_at']

    def get_name(self, obj):
        return obj.name


class GroupMemberSerializer(serializers.ModelSerializer):
    user          = UserSerializer(read_only=True)
    display_name  = serializers.SerializerMethodField()
    display_email = serializers.SerializerMethodField()
    avatar_color  = serializers.SerializerMethodField()

    class Meta:
        model  = GroupMember
        fields = [
            'id', 'user', 'display_name', 'display_email',
            'avatar_color', 'joined_at', 'is_admin', 'is_pending',
        ]

    def get_display_name(self, obj):
        return obj.display_name

    def get_display_email(self, obj):
        return obj.display_email

    def get_avatar_color(self, obj):
        if obj.user:
            return obj.user.avatar_color
        idx = sum(ord(c) for c in (obj.invited_email or '')) % len(AVATAR_COLORS)
        return AVATAR_COLORS[idx]


class NotificationSerializer(serializers.ModelSerializer):
    group_name = serializers.SerializerMethodField()

    class Meta:
        model  = Notification
        fields = ['id', 'type', 'title', 'message', 'is_read', 'group', 'group_name', 'created_at']

    def get_group_name(self, obj):
        return obj.group.name if obj.group else None


class ExpenseShareSerializer(serializers.ModelSerializer):
    user          = serializers.SerializerMethodField()
    member_id     = serializers.SerializerMethodField()
    amount_rupees = serializers.SerializerMethodField()

    class Meta:
        model  = ExpenseShare
        fields = ['id', 'user', 'member_id', 'amount_paise', 'amount_rupees', 'share_weight']

    def get_member_id(self, obj):
        return obj.member_id

    def get_user(self, obj):
        if obj.user:
            return {
                'id':           obj.user.id,
                'name':         obj.user.name,
                'avatar_color': obj.user.avatar_color,
            }
        if obj.member:
            return member_display(obj.member)
        return None

    def get_amount_rupees(self, obj):
        return str(Decimal(obj.amount_paise) / 100)


class ExpenseSerializer(serializers.ModelSerializer):
    paid_by           = serializers.SerializerMethodField()
    paid_by_member_id = serializers.SerializerMethodField()
    # write field — accepts GroupMember.id from frontend
    paid_by_member    = serializers.PrimaryKeyRelatedField(
        queryset=GroupMember.objects.all(), write_only=True, required=False
    )
    shares            = ExpenseShareSerializer(many=True, read_only=True)
    amount_rupees     = serializers.CharField(source='amount_display', read_only=True)
    amount            = serializers.DecimalField(
        max_digits=12, decimal_places=2, write_only=True, required=False
    )
    split_members     = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )
    custom_amounts    = serializers.DictField(
        child=serializers.DecimalField(max_digits=12, decimal_places=2),
        write_only=True, required=False
    )
    share_weights     = serializers.DictField(
        child=serializers.IntegerField(), write_only=True, required=False
    )

    class Meta:
        model  = Expense
        fields = [
            'id', 'group', 'paid_by', 'paid_by_member_id', 'paid_by_member',
            'description', 'amount_paise', 'amount', 'amount_rupees', 'currency',
            'split_mode', 'date', 'notes', 'ai_parsed', 'created_at', 'shares',
            'split_members', 'custom_amounts', 'share_weights',
        ]
        read_only_fields = ['amount_paise', 'created_at']

    def get_paid_by_member_id(self, obj):
        return obj.paid_by_member_id

    def get_paid_by(self, obj):
        if obj.paid_by_member:
            return member_display(obj.paid_by_member)
        # fallback for old expenses that only have paid_by (User FK)
        if obj.paid_by:
            return {
                'id':           obj.paid_by.id,
                'member_id':    None,
                'name':         obj.paid_by.name,
                'avatar_color': obj.paid_by.avatar_color,
            }
        return None

    def validate(self, data):
        amount = data.pop('amount', None)
        if amount is not None:
            data['amount_paise'] = int(amount * 100)
        split_mode     = data.get('split_mode', 'equal_all')
        custom_amounts = data.get('custom_amounts', {})
        if split_mode == 'custom' and custom_amounts:
            total_custom = sum(Decimal(str(v)) for v in custom_amounts.values())
            expected     = Decimal(data.get('amount_paise', 0)) / 100
            if abs(total_custom - expected) > Decimal('0.01'):
                raise serializers.ValidationError(
                    f"Custom amounts ({total_custom}) do not sum to total ({expected})"
                )
        return data

    def create(self, validated_data):
        split_members  = validated_data.pop('split_members', [])
        custom_amounts = validated_data.pop('custom_amounts', {})
        share_weights  = validated_data.pop('share_weights', {})
        # sync paid_by (User) from paid_by_member for backwards compat
        member = validated_data.get('paid_by_member')
        if member and member.user:
            validated_data['paid_by'] = member.user
        expense = Expense.objects.create(**validated_data)
        self._create_shares(expense, split_members, custom_amounts, share_weights)
        return expense

    def update(self, instance, validated_data):
        split_members  = validated_data.pop('split_members', [])
        custom_amounts = validated_data.pop('custom_amounts', {})
        share_weights  = validated_data.pop('share_weights', {})
        member = validated_data.get('paid_by_member')
        if member and member.user:
            validated_data['paid_by'] = member.user
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        instance.shares.all().delete()
        self._create_shares(instance, split_members, custom_amounts, share_weights)
        return instance

    def _create_shares(self, expense, split_members, custom_amounts, share_weights):
        all_members = list(expense.group.members.select_related('user').all())

        def make_share(member, amount_paise, weight=1):
            ExpenseShare.objects.create(
                expense=expense,
                user=member.user if not member.is_pending else None,
                member=member,
                amount_paise=amount_paise,
                share_weight=weight,
            )

        mode  = expense.split_mode
        paise = expense.amount_paise

        if mode == 'equal_all':
            targets = all_members
        elif mode == 'equal_subset':
            targets = (
                [m for m in all_members if m.id in split_members]
                if split_members else all_members
            )
        else:
            targets = []

        if mode in ('equal_all', 'equal_subset'):
            if not targets:
                return
            per = paise // len(targets)
            rem = paise % len(targets)
            for i, member in enumerate(targets):
                make_share(member, per + (1 if i < rem else 0))

        elif mode == 'custom':
            mid_to_member = {m.id: m for m in all_members}
            for mid_str, amt in custom_amounts.items():
                member = mid_to_member.get(int(mid_str))
                if member:
                    make_share(member, int(Decimal(str(amt)) * 100))

        elif mode == 'shares':
            target_ids    = split_members if split_members else [m.id for m in all_members]
            mid_to_member = {m.id: m for m in all_members}
            weights       = {mid: share_weights.get(str(mid), 1) for mid in target_ids}
            total_w       = sum(weights.values())
            if not total_w:
                return
            allocated = 0
            items     = list(weights.items())
            for i, (mid, w) in enumerate(items):
                member = mid_to_member.get(mid)
                if not member:
                    continue
                if i == len(items) - 1:
                    share_paise = paise - allocated
                else:
                    share_paise  = (paise * w) // total_w
                    allocated   += share_paise
                make_share(member, share_paise, w)


class GroupSerializer(serializers.ModelSerializer):
    members           = GroupMemberSerializer(many=True, read_only=True)
    member_ids        = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )
    created_by        = UserSerializer(read_only=True)
    expense_count     = serializers.SerializerMethodField()
    total_spent_paise = serializers.SerializerMethodField()
    invite_link       = serializers.SerializerMethodField()
    pending_count     = serializers.SerializerMethodField()

    class Meta:
        model  = Group
        fields = [
            'id', 'name', 'description', 'category', 'currency',
            'created_by', 'members', 'member_ids',
            'created_at', 'updated_at', 'expense_count',
            'total_spent_paise', 'invite_link', 'pending_count',
        ]

    def get_expense_count(self, obj):
        return obj.expenses.count()

    def get_total_spent_paise(self, obj):
        from django.db.models import Sum
        return obj.expenses.aggregate(total=Sum('amount_paise'))['total'] or 0

    def get_invite_link(self, obj):
        return str(obj.invite_token)

    def get_pending_count(self, obj):
        return obj.members.filter(is_pending=True).count()

    def create(self, validated_data):
        member_ids = validated_data.pop('member_ids', [])
        group      = Group.objects.create(**validated_data)
        creator    = self.context['request'].user
        GroupMember.objects.get_or_create(
            group=group, user=creator, defaults={'is_admin': True}
        )
        for uid in member_ids:
            if uid != creator.id:
                GroupMember.objects.get_or_create(group=group, user_id=uid)
        return group