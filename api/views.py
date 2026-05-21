from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import User, Group, GroupMember, Expense
from .serializers import UserSerializer, GroupSerializer, ExpenseSerializer
from .settle import get_balance_summary
from .ai_parser import parse_expense_text, parse_bill_text


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by('name')
    serializer_class = UserSerializer


class GroupViewSet(viewsets.ModelViewSet):
    queryset = Group.objects.prefetch_related('members__user').all()
    serializer_class = GroupSerializer

    @action(detail=True, methods=['post'], url_path='add-member')
    def add_member(self, request, pk=None):
        group = self.get_object()
        uid = request.data.get('user_id')
        if not uid:
            return Response({'error': 'user_id required'}, status=400)
        try:
            user = User.objects.get(pk=uid)
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=404)
        _, created = GroupMember.objects.get_or_create(group=group, user=user)
        return Response({'message': 'Member added' if created else 'Already a member'})

    @action(detail=True, methods=['delete'], url_path='remove-member/(?P<user_id>[^/.]+)')
    def remove_member(self, request, pk=None, user_id=None):
        group = self.get_object()
        GroupMember.objects.filter(group=group, user_id=user_id).delete()
        return Response({'message': 'Member removed'})

    @action(detail=True, methods=['get'], url_path='balances')
    def balances(self, request, pk=None):
        return Response(get_balance_summary(self.get_object()))

    @action(detail=True, methods=['get'], url_path='expenses')
    def expenses(self, request, pk=None):
        qs = self.get_object().expenses.select_related('paid_by').prefetch_related('shares__user')
        if pid := request.query_params.get('payer_id'):
            qs = qs.filter(paid_by_id=pid)
        if df := request.query_params.get('date_from'):
            qs = qs.filter(date__gte=df)
        if dt := request.query_params.get('date_to'):
            qs = qs.filter(date__lte=dt)
        if s := request.query_params.get('search'):
            qs = qs.filter(description__icontains=s)
        return Response(ExpenseSerializer(qs, many=True).data)


class ExpenseViewSet(viewsets.ModelViewSet):
    queryset = Expense.objects.select_related('paid_by', 'group').prefetch_related('shares__user')
    serializer_class = ExpenseSerializer

    def create(self, request, *args, **kwargs):
        s = self.get_serializer(data=request.data)
        if not s.is_valid():
            return Response({'errors': s.errors}, status=400)
        self.perform_create(s)
        return Response(s.data, status=201)

    @action(detail=False, methods=['post'], url_path='parse-text')
    def parse_text(self, request):
        text = request.data.get('text', '').strip()
        group_id = request.data.get('group_id')
        if not text:
            return Response({'error': 'text required'}, status=400)
        if not group_id:
            return Response({'error': 'group_id required'}, status=400)
        try:
            group = Group.objects.get(pk=group_id)
        except Group.DoesNotExist:
            return Response({'error': 'Group not found'}, status=404)
        members = [{'id': m['user__id'], 'name': m['user__name']}
                   for m in group.members.values('user__id', 'user__name')]
        return Response(parse_expense_text(text, members))

    @action(detail=False, methods=['post'], url_path='parse-bill')
    def parse_bill(self, request):
        text = request.data.get('text', '').strip()
        if not text:
            return Response({'error': 'text required'}, status=400)
        return Response(parse_bill_text(text))