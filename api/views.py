import re

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from decimal import Decimal

from .ai_parser import parse_bill_text, parse_expense_text
from .models import User, Group, GroupMember, Expense, Notification, Settlement, SettlementPayment
from .serializers import (
    RegisterSerializer, UserSerializer,
    GroupSerializer, GroupMemberSerializer,
    ExpenseSerializer, NotificationSerializer,
    SettlementSerializer,
)
from .settle import get_balance_summary


def valid_email(email):
    return re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email) is not None


# =========================
# AUTH VIEWS
# =========================

class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)

        if not serializer.is_valid():
            return Response(
                {"errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = serializer.save()
        refresh = RefreshToken.for_user(user)

        pending_count = Notification.objects.filter(
            user=user,
            is_read=False,
        ).count()

        return Response(
            {
                "user": UserSerializer(user).data,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "pending_groups": pending_count,
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(generics.GenericAPIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get("email", "").strip().lower()
        password = request.data.get("password", "")

        try:
            user = User.objects.get(email=email)

        except User.DoesNotExist:
            return Response(
                {"error": "Invalid email or password"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user.check_password(password):
            return Response(
                {"error": "Invalid email or password"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        refresh = RefreshToken.for_user(user)

        unread_notifications = Notification.objects.filter(
            user=user,
            is_read=False,
        ).count()

        return Response(
            {
                "user": UserSerializer(user).data,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "unread_notifications": unread_notifications,
            }
        )


class MeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


# =========================
# USER VIEWS
# =========================

class UserViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        my_group_ids = GroupMember.objects.filter(
        user=self.request.user
    ).values_list('group_id', flat=True)
        return Expense.objects.filter(
        group_id__in=my_group_ids
    ).select_related('paid_by', 'paid_by_member__user').prefetch_related(
        'shares__user', 'shares__member__user'   # ← add member
    )


# =========================
# NOTIFICATION VIEWS
# =========================

class NotificationViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request):
        notifications = Notification.objects.filter(
            user=request.user
        )[:30]

        serializer = NotificationSerializer(
            notifications,
            many=True,
        )

        return Response(serializer.data)

    @action(detail=False, methods=["post"], url_path="mark-read")
    def mark_read(self, request):
        Notification.objects.filter(
            user=request.user,
            is_read=False,
        ).update(is_read=True)

        return Response(
            {"message": "All notifications marked as read"}
        )

    @action(detail=True, methods=["post"], url_path="read")
    def mark_one_read(self, request, pk=None):
        notification = get_object_or_404(
            Notification,
            pk=pk,
            user=request.user,
        )

        notification.is_read = True
        notification.save()

        return Response(
            {"message": "Notification marked as read"}
        )
class SettlementViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def _get_group(self, group_id, user):
        group = get_object_or_404(Group, pk=group_id)
        if not GroupMember.objects.filter(group=group, user=user).exists():
            return None, Response({'error': 'Not a member'}, status=403)
        return group, None

    @action(detail=False, methods=['get'], url_path='group/(?P<group_id>[^/.]+)')
    def list_for_group(self, request, group_id=None):
        group, err = self._get_group(group_id, request.user)
        if err: return err
        # Sync settlements from current balances
        self._sync_settlements(group)
        settlements = list(
            Settlement.objects.filter(group=group)
            .prefetch_related(
                'payments',
                'payments__paid_by__user',
                'payments__paid_to__user',
                'from_member__user',
                'to_member__user',
            )
        )
        settlements.sort(key=lambda s: (s.status == 'completed', s.updated_at))
        return Response(SettlementSerializer(settlements, many=True).data)

    @action(detail=False, methods=['get'], url_path='detail/(?P<settlement_id>[^/.]+)')
    def detail_view(self, request, settlement_id=None):
        s = Settlement.objects.prefetch_related(
            'payments',
            'payments__paid_by__user',
            'payments__paid_to__user',
            'from_member__user',
            'to_member__user',
        ).filter(pk=settlement_id).first()
        if not s:
            return Response({'detail': 'Not found.'}, status=404)
        group, err = self._get_group(s.group_id, request.user)
        if err: return err
        return Response(SettlementSerializer(s).data)

    @action(detail=False, methods=['post'], url_path='(?P<settlement_id>[^/.]+)/pay')
    def pay(self, request, settlement_id=None):
        s = get_object_or_404(Settlement, pk=settlement_id)
        group, err = self._get_group(s.group_id, request.user)
        if err: return err
        if s.status == 'completed':
            return Response({'error': 'Already fully settled'}, status=400)

        amount = request.data.get('amount')
        note   = request.data.get('note', '').strip()
        try:
            amount_paise = int(Decimal(str(amount)) * 100)
        except Exception:
            return Response({'error': 'Invalid amount'}, status=400)

        if amount_paise <= 0:
            return Response({'error': 'Amount must be positive'}, status=400)
        if amount_paise > s.remaining_paise:
            return Response({
                'error': f'Amount exceeds remaining balance of ₹{s.remaining_paise/100:.2f}'
            }, status=400)

        payment_type = 'full' if amount_paise == s.remaining_paise else 'partial'
        payer_member = GroupMember.objects.filter(group=group, user=request.user).first()
        SettlementPayment.objects.create(
            settlement=s,
            amount_paise=amount_paise,
            note=note,
            paid_by=payer_member,
            paid_to=s.to_member,
            payment_type=payment_type,
        )

        s.paid_paise += amount_paise
        if s.paid_paise >= s.total_paise:
            s.paid_paise = s.total_paise
            s.status     = 'completed'
            s.completed_at = timezone.now()
        else:
            s.status = 'partial'
        s.save()

        payer    = s.payer
        receiver = s.receiver
        fmt      = lambda p: f"₹{p/100:,.2f}"

        if receiver.user:
            Notification.objects.create(
                user=receiver.user,
                type='expense_added',
                title=f'{payer.user.name if payer.user else payer.display_name} paid you {fmt(amount_paise)}',
                message=(
                    f'{payer.user.name if payer.user else payer.display_name} paid {fmt(amount_paise)} towards their debt of '
                    f'{fmt(s.total_paise)} in group "{group.name}".'
                    + (' Settlement completed! 🎉' if s.status == 'completed' else
                       f' Remaining: {fmt(s.remaining_paise)}')
                ),
                group=group,
            )

        if s.status == 'completed' and payer.user:
            Notification.objects.create(
                user=payer.user,
                type='expense_added',
                title=f'You fully settled with {receiver.user.name if receiver.user else receiver.display_name} 🎉',
                message=f'Your debt of {fmt(s.total_paise)} to {receiver.user.name if receiver.user else receiver.display_name} in "{group.name}" is fully cleared.',
                group=group,
            )

        return Response(SettlementSerializer(s).data)

    def _sync_settlements(self, group):
        """Recalculate debts from expenses and update Settlement records."""
        from .settle import compute_settlements
        transactions = compute_settlements(group)

        # Load all existing non-completed settlements
        existing = {
            (s.from_member_id, s.to_member_id): s
            for s in Settlement.objects.filter(group=group)
        }

        seen = set()
        for t in transactions:
            key = (t['from_member_id'], t['to_member_id'])
            seen.add(key)
            if key in existing:
                s = existing[key]
                # Do not modify s.total_paise here — payments are authoritative for progress.
                if s.remaining_paise == 0:
                    s.status = 'completed'
                elif s.paid_paise > 0:
                    s.status = 'partial'
                else:
                    s.status = 'pending'
                s.save()
            else:
                Settlement.objects.get_or_create(
                    group=group,
                    from_member_id=t['from_member_id'],
                    to_member_id=t['to_member_id'],
                    defaults={
                        'total_paise': t['amount_paise'],
                        'status': 'pending',
                    }
                )

    def _sync_settlements(self, group):
        """Recalculate debts from expenses and update Settlement records."""
        from .settle import compute_settlements
        transactions = compute_settlements(group)

        # Load all existing non-completed settlements
        existing = {
            (s.from_member_id, s.to_member_id): s
            for s in Settlement.objects.filter(group=group)
        }

        seen = set()
        for t in transactions:
            key = (t['from_member_id'], t['to_member_id'])
            seen.add(key)
            if key in existing:
                s = existing[key]
                if s.remaining_paise == 0:
                    s.status = 'completed'
                elif s.paid_paise > 0:
                    s.status = 'partial'
                else:
                    s.status = 'pending'
                s.save()
            else:
                Settlement.objects.get_or_create(
                    group=group,
                    from_member_id=t['from_member_id'],
                    to_member_id=t['to_member_id'],
                    defaults={
                        'total_paise': t['amount_paise'],
                        'status': 'pending',
                    }
                )

# =========================
# GROUP VIEWS
# =========================

class GroupViewSet(viewsets.ModelViewSet):
    serializer_class = GroupSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            Group.objects.filter(
                members__user=self.request.user
            )
            .prefetch_related("members__user")
            .distinct()
        )

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def destroy(self, request, *args, **kwargs):
        group = self.get_object()

        if group.created_by != request.user:
            return Response(
                {
                    "error": "Only the group creator can delete this group"
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        group.delete()

        return Response(
            {"message": "Group deleted successfully"}
        )

    # -------------------------
    # HELPER METHODS
    # -------------------------

    def _assert_member(self, group):
        if not group.members.filter(user=self.request.user).exists():
            return Response(
                {"error": "Not a member of this group"},
                status=status.HTTP_403_FORBIDDEN,
            )

        return None

    def _assert_admin(self, group):
        if group.created_by != self.request.user:
            return Response(
                {"error": "Only the group admin can perform this action"},
                status=status.HTTP_403_FORBIDDEN,
            )

        return None

    # -------------------------
    # GROUP MEMBERS
    # -------------------------

    @action(detail=True, methods=["get"], url_path="members")
    def list_members(self, request, pk=None):
        group = self.get_object()

        error = self._assert_member(group)

        if error:
            return error

        members = group.members.select_related(
            "user"
        ).order_by("is_pending", "joined_at")

        serializer = GroupMemberSerializer(
            members,
            many=True,
        )

        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="members/add")
    def add_member(self, request, pk=None):
        group = self.get_object()

        error = self._assert_admin(group)

        if error:
            return error

        email = request.data.get("email", "").strip().lower()
        name = request.data.get("name", "").strip()

        # Validation
        if not email:
            return Response(
                {"error": "Email is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not valid_email(email):
            return Response(
                {"error": "Invalid email format"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not name:
            return Response(
                {"error": "Name is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Duplicate check
        existing_member = GroupMember.objects.filter(
            group=group,
            user__email__iexact=email,
        ).exists()

        existing_pending = GroupMember.objects.filter(
            group=group,
            invited_email__iexact=email,
            is_pending=True,
        ).exists()

        if existing_member or existing_pending:
            return Response(
                {
                    "error": f"{email} is already a member or has a pending invite"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Existing user
        try:
            user = User.objects.get(email__iexact=email)

            GroupMember.objects.create(
                group=group,
                user=user,
                invited_email=email,
                invited_name=name,
                is_pending=False,
            )

            Notification.objects.create(
                user=user,
                type="group_invite",
                title=f'You were added to "{group.name}"',
                message=(
                    f'{request.user.name} added you to the group "{group.name}".'
                ),
                group=group,
            )

            return Response(
                {
                    "message": f"{name} added to group successfully",
                    "status": "joined",
                }
            )

        except User.DoesNotExist:

            # Pending invite
            GroupMember.objects.create(
                group=group,
                user=None,
                invited_email=email,
                invited_name=name,
                is_pending=True,
            )

            return Response(
                {
                    "message": (
                        f"{name} ({email}) added as pending member. "
                        "They will get access after signup."
                    ),
                    "status": "pending",
                }
            )

    @action(
        detail=True,
        methods=["delete"],
        url_path=r"members/remove/(?P<member_id>[^/.]+)",
    )
    def remove_member(self, request, pk=None, member_id=None):
        group = self.get_object()

        error = self._assert_admin(group)

        if error:
            return error

        member = get_object_or_404(
            GroupMember,
            pk=member_id,
            group=group,
        )

        if member.user == group.created_by:
            return Response(
                {"error": "Cannot remove the group creator"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        member.delete()

        return Response(
            {"message": "Member removed successfully"}
        )

    # -------------------------
    # GROUP BALANCES
    # -------------------------

    @action(detail=True, methods=["get"], url_path="balances")
    def balances(self, request, pk=None):
        group = self.get_object()

        error = self._assert_member(group)

        if error:
            return error

        return Response(get_balance_summary(group))

    # -------------------------
    # GROUP EXPENSES
    # -------------------------

    @action(detail=True, methods=["get"], url_path="expenses")
    def expenses(self, request, pk=None):
        group = self.get_object()

        error = self._assert_member(group)

        if error:
            return error

        queryset = group.expenses.select_related(
            "paid_by",
            "paid_by_member__user",
        ).prefetch_related(
            "shares__user",
            "shares__member__user",
        )

        payer_id = request.query_params.get("payer_id")
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        search = request.query_params.get("search")

        if payer_id:
            queryset = queryset.filter(
                paid_by_id=payer_id
            )

        if date_from:
            queryset = queryset.filter(
                date__gte=date_from
            )

        if date_to:
            queryset = queryset.filter(
                date__lte=date_to
            )

        if search:
            queryset = queryset.filter(
                description__icontains=search
            )

        serializer = ExpenseSerializer(
            queryset,
            many=True,
        )

        return Response(serializer.data)

    # -------------------------
    # JOIN GROUP BY TOKEN
    # -------------------------

    @action(
        detail=False,
        methods=["get"],
        url_path=r"join/(?P<token>[^/.]+)",
    )
    def join_by_token(self, request, token=None):

        group = get_object_or_404(
            Group,
            invite_token=token,
        )

        member, created = GroupMember.objects.get_or_create(
            group=group,
            user=request.user,
            defaults={
                "invited_email": request.user.email,
                "invited_name": request.user.name,
            },
        )

        if created and group.created_by:

            Notification.objects.create(
                user=group.created_by,
                type="group_joined",
                title=f'{request.user.name} joined "{group.name}"',
                message=(
                    f"{request.user.name} joined your group via invite link."
                ),
                group=group,
            )

        serializer = self.get_serializer(group)

        return Response(
            {
                "group": serializer.data,
                "joined": created,
                "message": (
                    "Joined group successfully"
                    if created
                    else "Already a member"
                ),
            }
        )


# =========================
# EXPENSE VIEWS
# =========================

class ExpenseViewSet(viewsets.ModelViewSet):
    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        my_group_ids = GroupMember.objects.filter(
            user=self.request.user
        ).values_list("group_id", flat=True)

        return (
            Expense.objects.filter(
                group_id__in=my_group_ids
            )
            .select_related("paid_by", "group")
            .prefetch_related("shares__user")
        )
    def create(self, request, *args, **kwargs):
        group_id = request.data.get('group')
        data = request.data.copy()
        if not data.get('paid_by_member') and data.get('paid_by_member_id'):
            data['paid_by_member'] = data.get('paid_by_member_id')
        if group_id:
            if not GroupMember.objects.filter(group_id=group_id, user=request.user).exists():
                return Response({'error': 'Not a member of this group'}, status=403)
            paid_by_member_id = data.get('paid_by_member') or data.get('paid_by_member_id')
            if paid_by_member_id and group_id:
                if not GroupMember.objects.filter(id=paid_by_member_id, group_id=group_id).exists():
                    return Response({'error': 'Payer is not a member of this group'}, status=400)
        s = self.get_serializer(data=data)
        if not s.is_valid():
            return Response({'errors': s.errors}, status=400)
        self.perform_create(s)
        return Response(s.data, status=201)
    def update(self, request, *args, **kwargs):
        expense = self.get_object()

        is_member = GroupMember.objects.filter(
            group=expense.group,
            user=request.user,
        ).exists()

        if not is_member:
            return Response(
                {"error": "Not a member"},
                status=status.HTTP_403_FORBIDDEN,
            )

        data = request.data.copy()
        if not data.get('paid_by_member') and data.get('paid_by_member_id'):
            data['paid_by_member'] = data.get('paid_by_member_id')
        serializer = self.get_serializer(
            expense,
            data=data,
            partial=kwargs.get("partial", False),
        )

        if not serializer.is_valid():
            return Response(
                {"errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        self.perform_update(serializer)

        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        expense = self.get_object()

        is_member = GroupMember.objects.filter(
            group=expense.group,
            user=request.user,
        ).exists()

        if not is_member:
            return Response(
                {"error": "Not a member"},
                status=status.HTTP_403_FORBIDDEN,
            )

        expense.delete()

        return Response(
            {"message": "Expense deleted successfully"}
        )

    # -------------------------
    # AI TEXT PARSER
    # -------------------------

    @action(detail=False, methods=["post"], url_path="parse-text")
    def parse_text(self, request):

        text = request.data.get("text", "").strip()
        group_id = request.data.get("group_id")

        if not text:
            return Response(
                {"error": "Text is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        group = get_object_or_404(Group, pk=group_id)

        is_member = GroupMember.objects.filter(
            group=group,
            user=request.user,
        ).exists()

        if not is_member:
            return Response(
                {"error": "Not a member"},
                status=status.HTTP_403_FORBIDDEN,
            )

        members = [
            {
                "id": member.user.id,
                "name": member.user.name,
            }
            for member in group.members.select_related("user").filter(
                is_pending=False,
                user__isnull=False,
            )
        ]

        parsed_data = parse_expense_text(
            text,
            members,
        )

        return Response(parsed_data)

    # -------------------------
    # BILL PARSER
    # -------------------------

    @action(detail=False, methods=["post"], url_path="parse-bill")
    def parse_bill(self, request):

        text = request.data.get("text", "").strip()

        if not text:
            return Response(
                {"error": "Text is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        parsed_bill = parse_bill_text(text)

        return Response(parsed_bill)