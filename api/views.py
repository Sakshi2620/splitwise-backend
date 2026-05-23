import re
from decimal import Decimal

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from .ai_parser import parse_bill_text, parse_expense_text
from .models import (
    User, Group, GroupMember, Expense,
    Notification, Settlement, SettlementPayment,
)
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
    serializer_class   = RegisterSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response({'errors': serializer.errors}, status=400)
        user    = serializer.save()
        refresh = RefreshToken.for_user(user)
        pending_count = Notification.objects.filter(user=user, is_read=False).count()
        return Response({
            'user':           UserSerializer(user).data,
            'access':         str(refresh.access_token),
            'refresh':        str(refresh),
            'pending_groups': pending_count,
        }, status=201)


class LoginView(generics.GenericAPIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email    = request.data.get('email', '').strip().lower()
        password = request.data.get('password', '')
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({'error': 'Invalid email or password'}, status=401)
        if not user.check_password(password):
            return Response({'error': 'Invalid email or password'}, status=401)
        refresh = RefreshToken.for_user(user)
        unread  = Notification.objects.filter(user=user, is_read=False).count()
        return Response({
            'user':                   UserSerializer(user).data,
            'access':                 str(refresh.access_token),
            'refresh':                str(refresh),
            'unread_notifications':   unread,
        })


class MeView(generics.RetrieveAPIView):
    serializer_class   = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


# =========================
# USER VIEWS
# =========================

class UserViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class   = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Return User peers — people in the same groups as the current user
        my_group_ids = GroupMember.objects.filter(
            user=self.request.user
        ).values_list('group_id', flat=True)
        peer_ids = GroupMember.objects.filter(
            group_id__in=my_group_ids
        ).values_list('user_id', flat=True)
        return User.objects.filter(
            id__in=peer_ids
        ).exclude(id=None).distinct().order_by('first_name')


# =========================
# NOTIFICATION VIEWS
# =========================

class NotificationViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request):
        notifications = Notification.objects.filter(user=request.user)[:30]
        return Response(NotificationSerializer(notifications, many=True).data)

    @action(detail=False, methods=['post'], url_path='mark-read')
    def mark_read(self, request):
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return Response({'message': 'All notifications marked as read'})

    @action(detail=True, methods=['post'], url_path='read')
    def mark_one_read(self, request, pk=None):
        notification = get_object_or_404(Notification, pk=pk, user=request.user)
        notification.is_read = True
        notification.save()
        return Response({'message': 'Notification marked as read'})


# =========================
# SETTLEMENT VIEWS
# =========================

class SettlementViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def _get_group(self, group_id, user):
        group = get_object_or_404(Group, pk=group_id)
        if not GroupMember.objects.filter(group=group, user=user).exists():
            return None, Response({'error': 'Not a member'}, status=403)
        return group, None

    def _sync_settlements(self, group):
        """Recalculate debts from expenses and update Settlement records."""
        from .settle import compute_settlements
        transactions = compute_settlements(group)

        existing = {
            (s.from_member_id, s.to_member_id): s
            for s in Settlement.objects.filter(group=group)
        }

        for t in transactions:
            key = (t['from_member_id'], t['to_member_id'])
            if key in existing:
                s = existing[key]
                # Update total to reflect current debt + already paid
                new_total = t['amount_paise'] + s.paid_paise
                if s.total_paise != new_total:
                    s.total_paise = new_total
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
                        'status':      'pending',
                    }
                )

    def list_for_group(self, request, group_id=None):
        group, err = self._get_group(group_id, request.user)
        if err: return err
        self._sync_settlements(group)
        settlements = list(
            Settlement.objects.filter(group=group)
            .prefetch_related('payments', 'from_member__user', 'to_member__user')
        )
        settlements.sort(key=lambda s: (s.status == 'completed', s.updated_at))
        return Response(SettlementSerializer(settlements, many=True).data)

    def detail_view(self, request, settlement_id=None):
        s = Settlement.objects.prefetch_related(
            'payments', 'from_member__user', 'to_member__user'
        ).filter(pk=settlement_id).first()
        if not s:
            return Response({'detail': 'Not found.'}, status=404)
        group, err = self._get_group(s.group_id, request.user)
        if err: return err
        return Response(SettlementSerializer(s).data)

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

        # Create payment record — only fields that exist on the model
        SettlementPayment.objects.create(
            settlement=s,
            amount_paise=amount_paise,
            note=note,
        )

        s.paid_paise += amount_paise
        if s.paid_paise >= s.total_paise:
            s.paid_paise   = s.total_paise
            s.status       = 'completed'
            s.completed_at = timezone.now()
        else:
            s.status = 'partial'
        s.save()

        # Notifications
        payer    = s.from_member
        receiver = s.to_member
        fmt      = lambda p: f"₹{p/100:,.2f}"

        if receiver and receiver.user:
            payer_name = payer.user.name if payer and payer.user else (payer.invited_name if payer else '?')
            Notification.objects.create(
                user=receiver.user,
                type='expense_added',
                title=f'{payer_name} paid you {fmt(amount_paise)}',
                message=(
                    f'{payer_name} paid {fmt(amount_paise)} in group "{group.name}".'
                    + (' Settlement completed! 🎉' if s.status == 'completed'
                       else f' Remaining: {fmt(s.remaining_paise)}')
                ),
                group=group,
            )

        if s.status == 'completed' and payer and payer.user:
            receiver_name = receiver.user.name if receiver and receiver.user else (receiver.invited_name if receiver else '?')
            Notification.objects.create(
                user=payer.user,
                type='expense_added',
                title=f'You fully settled with {receiver_name} 🎉',
                message=f'Your debt of {fmt(s.total_paise)} to {receiver_name} in "{group.name}" is fully cleared.',
                group=group,
            )

        return Response(SettlementSerializer(s).data)


# =========================
# GROUP VIEWS
# =========================

class GroupViewSet(viewsets.ModelViewSet):
    serializer_class   = GroupSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            Group.objects.filter(members__user=self.request.user)
            .prefetch_related('members__user')
            .distinct()
        )

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def destroy(self, request, *args, **kwargs):
        group = self.get_object()
        if group.created_by != request.user:
            return Response(
                {'error': 'Only the group creator can delete this group'},
                status=403,
            )
        group.delete()
        return Response({'message': 'Group deleted successfully'})

    def _assert_member(self, group):
        if not group.members.filter(user=self.request.user).exists():
            return Response({'error': 'Not a member of this group'}, status=403)
        return None

    def _assert_admin(self, group):
        if group.created_by != self.request.user:
            return Response({'error': 'Only the group admin can perform this action'}, status=403)
        return None

    @action(detail=True, methods=['get'], url_path='members')
    def list_members(self, request, pk=None):
        group = self.get_object()
        err   = self._assert_member(group)
        if err: return err
        members = group.members.select_related('user').order_by('is_pending', 'joined_at')
        return Response(GroupMemberSerializer(members, many=True).data)

    @action(detail=True, methods=['post'], url_path='members/add')
    def add_member(self, request, pk=None):
        group = self.get_object()
        err   = self._assert_admin(group)
        if err: return err

        email = request.data.get('email', '').strip().lower()
        name  = request.data.get('name', '').strip()

        if not email:
            return Response({'error': 'Email is required'}, status=400)
        if not valid_email(email):
            return Response({'error': 'Invalid email format'}, status=400)
        if not name:
            return Response({'error': 'Name is required'}, status=400)

        existing_member  = GroupMember.objects.filter(group=group, user__email__iexact=email).exists()
        existing_pending = GroupMember.objects.filter(group=group, invited_email__iexact=email, is_pending=True).exists()
        if existing_member or existing_pending:
            return Response({'error': f'{email} is already a member or has a pending invite'}, status=400)

        try:
            user = User.objects.get(email__iexact=email)
            GroupMember.objects.create(
                group=group, user=user,
                invited_email=email, invited_name=name, is_pending=False,
            )
            Notification.objects.create(
                user=user, type='group_invite',
                title=f'You were added to "{group.name}"',
                message=f'{request.user.name} added you to the group "{group.name}".',
                group=group,
            )
            return Response({'message': f'{name} added to group successfully', 'status': 'joined'})
        except User.DoesNotExist:
            GroupMember.objects.create(
                group=group, user=None,
                invited_email=email, invited_name=name, is_pending=True,
            )
            return Response({
                'message': f'{name} ({email}) added as pending member. They will get access after signup.',
                'status': 'pending',
            })

    @action(detail=True, methods=['delete'], url_path=r'members/remove/(?P<member_id>[^/.]+)')
    def remove_member(self, request, pk=None, member_id=None):
        group  = self.get_object()
        err    = self._assert_admin(group)
        if err: return err
        member = get_object_or_404(GroupMember, pk=member_id, group=group)
        if member.user == group.created_by:
            return Response({'error': 'Cannot remove the group creator'}, status=400)
        member.delete()
        return Response({'message': 'Member removed successfully'})

    @action(detail=True, methods=['get'], url_path='balances')
    def balances(self, request, pk=None):
        group = self.get_object()
        err   = self._assert_member(group)
        if err: return err
        return Response(get_balance_summary(group))

    @action(detail=True, methods=['get'], url_path='expenses')
    def expenses(self, request, pk=None):
        group = self.get_object()
        err   = self._assert_member(group)
        if err: return err

        queryset = group.expenses.select_related(
            'paid_by', 'paid_by_member__user',
        ).prefetch_related(
            'shares__user', 'shares__member__user',
        )

        if pid := request.query_params.get('payer_id'):
            queryset = queryset.filter(paid_by_id=pid)
        if df := request.query_params.get('date_from'):
            queryset = queryset.filter(date__gte=df)
        if dt := request.query_params.get('date_to'):
            queryset = queryset.filter(date__lte=dt)
        if s := request.query_params.get('search'):
            queryset = queryset.filter(description__icontains=s)

        return Response(ExpenseSerializer(queryset, many=True).data)

    @action(detail=False, methods=['get'], url_path=r'join/(?P<token>[^/.]+)')
    def join_by_token(self, request, token=None):
        group = get_object_or_404(Group, invite_token=token)
        member, created = GroupMember.objects.get_or_create(
            group=group, user=request.user,
            defaults={'invited_email': request.user.email, 'invited_name': request.user.name},
        )
        if created and group.created_by:
            Notification.objects.create(
                user=group.created_by, type='group_joined',
                title=f'{request.user.name} joined "{group.name}"',
                message=f'{request.user.name} joined your group via invite link.',
                group=group,
            )
        return Response({
            'group':   self.get_serializer(group).data,
            'joined':  created,
            'message': 'Joined group successfully' if created else 'Already a member',
        })


# =========================
# EXPENSE VIEWS
# =========================

class ExpenseViewSet(viewsets.ModelViewSet):
    serializer_class   = ExpenseSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        my_group_ids = GroupMember.objects.filter(
            user=self.request.user
        ).values_list('group_id', flat=True)
        return Expense.objects.filter(
            group_id__in=my_group_ids
        ).select_related(
            'paid_by', 'paid_by_member__user',
        ).prefetch_related(
            'shares__user', 'shares__member__user',
        )

    def create(self, request, *args, **kwargs):
        group_id = request.data.get('group')
        data     = request.data.copy()
        # Frontend sends paid_by_member_id → map to paid_by_member for serializer
        if not data.get('paid_by_member') and data.get('paid_by_member_id'):
            data['paid_by_member'] = data['paid_by_member_id']
        if group_id:
            if not GroupMember.objects.filter(group_id=group_id, user=request.user).exists():
                return Response({'error': 'Not a member of this group'}, status=403)
            paid_by_member_id = data.get('paid_by_member')
            if paid_by_member_id:
                if not GroupMember.objects.filter(id=paid_by_member_id, group_id=group_id).exists():
                    return Response({'error': 'Payer is not a member of this group'}, status=400)
        s = self.get_serializer(data=data)
        if not s.is_valid():
            return Response({'errors': s.errors}, status=400)
        self.perform_create(s)
        return Response(s.data, status=201)

    def update(self, request, *args, **kwargs):
        expense = self.get_object()
        if not GroupMember.objects.filter(group=expense.group, user=request.user).exists():
            return Response({'error': 'Not a member'}, status=403)
        data = request.data.copy()
        if not data.get('paid_by_member') and data.get('paid_by_member_id'):
            data['paid_by_member'] = data['paid_by_member_id']
        s = self.get_serializer(expense, data=data, partial=kwargs.get('partial', False))
        if not s.is_valid():
            return Response({'errors': s.errors}, status=400)
        self.perform_update(s)
        return Response(s.data)

    def destroy(self, request, *args, **kwargs):
        expense = self.get_object()
        if not GroupMember.objects.filter(group=expense.group, user=request.user).exists():
            return Response({'error': 'Not a member'}, status=403)
        expense.delete()
        return Response({'message': 'Expense deleted successfully'})

    @action(detail=False, methods=['post'], url_path='parse-text')
    def parse_text(self, request):
        text     = request.data.get('text', '').strip()
        group_id = request.data.get('group_id')
        if not text:
            return Response({'error': 'Text is required'}, status=400)
        group = get_object_or_404(Group, pk=group_id)
        if not GroupMember.objects.filter(group=group, user=request.user).exists():
            return Response({'error': 'Not a member'}, status=403)
        members = [
            {'id': m.user.id, 'name': m.user.name}
            for m in group.members.select_related('user').filter(
                is_pending=False, user__isnull=False,
            )
        ]
        return Response(parse_expense_text(text, members))

    @action(detail=False, methods=['post'], url_path='parse-bill')
    def parse_bill(self, request):
        text = request.data.get('text', '').strip()
        if not text:
            return Response({'error': 'Text is required'}, status=400)
        return Response(parse_bill_text(text))