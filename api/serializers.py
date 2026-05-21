from rest_framework import serializers
from decimal import Decimal
from .models import User, Group, GroupMember, Expense, ExpenseShare


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'name', 'email', 'avatar_color', 'created_at']


class GroupMemberSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    user_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), source='user', write_only=True
    )

    class Meta:
        model = GroupMember
        fields = ['id', 'user', 'user_id', 'joined_at']


class ExpenseShareSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    amount_rupees = serializers.SerializerMethodField()

    class Meta:
        model = ExpenseShare
        fields = ['id', 'user', 'amount_paise', 'amount_rupees', 'share_weight']

    def get_amount_rupees(self, obj):
        return str(Decimal(obj.amount_paise) / 100)


class ExpenseSerializer(serializers.ModelSerializer):
    paid_by = UserSerializer(read_only=True)
    paid_by_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), source='paid_by', write_only=True
    )
    shares = ExpenseShareSerializer(many=True, read_only=True)
    amount_rupees = serializers.CharField(source='amount_display', read_only=True)
    # Frontend sends rupees; we convert to paise server-side
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, write_only=True, required=False)
    split_members = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)
    custom_amounts = serializers.DictField(
        child=serializers.DecimalField(max_digits=12, decimal_places=2),
        write_only=True, required=False
    )
    share_weights = serializers.DictField(child=serializers.IntegerField(), write_only=True, required=False)

    class Meta:
        model = Expense
        fields = [
            'id', 'group', 'paid_by', 'paid_by_id', 'description',
            'amount_paise', 'amount', 'amount_rupees', 'currency',
            'split_mode', 'date', 'notes', 'ai_parsed', 'created_at', 'shares',
            'split_members', 'custom_amounts', 'share_weights',
        ]
        read_only_fields = ['amount_paise', 'created_at']

    def validate(self, data):
        amount = data.pop('amount', None)
        if amount is not None:
            # Integer paise — no floats
            data['amount_paise'] = int(amount * 100)

        split_mode = data.get('split_mode', 'equal_all')
        custom_amounts = data.get('custom_amounts', {})
        if split_mode == 'custom' and custom_amounts:
            total_custom = sum(Decimal(str(v)) for v in custom_amounts.values())
            expected = Decimal(data['amount_paise']) / 100
            if abs(total_custom - expected) > Decimal('0.01'):
                raise serializers.ValidationError(
                    f"Custom amounts ({total_custom}) do not sum to total ({expected})"
                )
        return data

    def create(self, validated_data):
        split_members = validated_data.pop('split_members', [])
        custom_amounts = validated_data.pop('custom_amounts', {})
        share_weights = validated_data.pop('share_weights', {})
        expense = Expense.objects.create(**validated_data)
        self._create_shares(expense, split_members, custom_amounts, share_weights)
        return expense

    def _create_shares(self, expense, split_members, custom_amounts, share_weights):
        all_member_ids = list(expense.group.members.values_list('user_id', flat=True))
        mode = expense.split_mode
        paise = expense.amount_paise

        if mode == 'equal_all':
            members = all_member_ids
        elif mode == 'equal_subset':
            members = split_members if split_members else all_member_ids
        else:
            members = []

        if mode in ('equal_all', 'equal_subset'):
            per = paise // len(members)
            rem = paise % len(members)
            for i, uid in enumerate(members):
                ExpenseShare.objects.create(
                    expense=expense, user_id=uid,
                    amount_paise=per + (1 if i < rem else 0)
                )
        elif mode == 'custom':
            for uid_str, amt in custom_amounts.items():
                ExpenseShare.objects.create(
                    expense=expense, user_id=int(uid_str),
                    amount_paise=int(Decimal(str(amt)) * 100)
                )
        elif mode == 'shares':
            target = split_members if split_members else all_member_ids
            weights = {str(uid): share_weights.get(str(uid), 1) for uid in target}
            total_w = sum(weights.values())
            allocated = 0
            items = list(weights.items())
            for i, (uid_str, w) in enumerate(items):
                if i == len(items) - 1:
                    share_paise = paise - allocated
                else:
                    share_paise = (paise * w) // total_w
                    allocated += share_paise
                ExpenseShare.objects.create(
                    expense=expense, user_id=int(uid_str),
                    amount_paise=share_paise, share_weight=w
                )


class GroupSerializer(serializers.ModelSerializer):
    members = GroupMemberSerializer(many=True, read_only=True)
    member_ids = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)
    created_by = UserSerializer(read_only=True)
    created_by_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), source='created_by', write_only=True, required=False
    )
    expense_count = serializers.SerializerMethodField()
    total_spent_paise = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = [
            'id', 'name', 'description', 'category', 'currency',
            'created_by', 'created_by_id', 'members', 'member_ids',
            'created_at', 'updated_at', 'expense_count', 'total_spent_paise',
        ]

    def get_expense_count(self, obj):
        return obj.expenses.count()

    def get_total_spent_paise(self, obj):
        from django.db.models import Sum
        return obj.expenses.aggregate(total=Sum('amount_paise'))['total'] or 0

    def create(self, validated_data):
        member_ids = validated_data.pop('member_ids', [])
        group = Group.objects.create(**validated_data)
        for uid in member_ids:
            GroupMember.objects.get_or_create(group=group, user_id=uid)
        return group