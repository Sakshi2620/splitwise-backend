from django.contrib import admin
from .models import (
    User,
    Group,
    GroupMember,
    Notification,
    Expense,
    ExpenseShare,
    Settlement,
    SettlementPayment,
)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'email',
        'username',
        'first_name',
        'last_name',
        'avatar_color',
        'created_at',
    )
    search_fields = ('email', 'username', 'first_name', 'last_name')
    list_filter = ('created_at',)
    ordering = ('-created_at',)


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'name',
        'category',
        'created_by',
        'currency',
        'created_at',
    )
    search_fields = ('name', 'description')
    list_filter = ('category', 'currency', 'created_at')
    ordering = ('-created_at',)


@admin.register(GroupMember)
class GroupMemberAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'group',
        'display_name',
        'display_email',
        'is_admin',
        'is_pending',
        'joined_at',
    )
    search_fields = (
        'group__name',
        'user__email',
        'user__username',
        'invited_email',
        'invited_name',
    )
    list_filter = ('is_admin', 'is_pending', 'joined_at')
    ordering = ('-joined_at',)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'type',
        'title',
        'is_read',
        'group',
        'created_at',
    )
    search_fields = (
        'user__email',
        'title',
        'message',
        'group__name',
    )
    list_filter = ('type', 'is_read', 'created_at')
    ordering = ('-created_at',)


class ExpenseShareInline(admin.TabularInline):
    model = ExpenseShare
    extra = 0


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'group',
        'description',
        'paid_by',
        'paid_by_member',
        'amount_display',
        'currency',
        'split_mode',
        'date',
        'ai_parsed',
    )
    search_fields = (
        'description',
        'group__name',
        'paid_by__email',
        'paid_by_member__invited_email',
    )
    list_filter = (
        'split_mode',
        'currency',
        'ai_parsed',
        'date',
    )
    ordering = ('-date', '-created_at')
    inlines = [ExpenseShareInline]


@admin.register(ExpenseShare)
class ExpenseShareAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'expense',
        'get_display_name',
        'amount_paise',
        'share_weight',
    )
    search_fields = (
        'expense__description',
        'user__email',
        'member__invited_email',
        'member__invited_name',
    )


class SettlementPaymentInline(admin.TabularInline):
    model = SettlementPayment
    extra = 0


@admin.register(Settlement)
class SettlementAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'group',
        'from_member',
        'to_member',
        'total_paise',
        'paid_paise',
        'remaining_paise',
        'status',
        'created_at',
    )
    search_fields = (
        'group__name',
        'from_member__invited_email',
        'to_member__invited_email',
    )
    list_filter = ('status', 'created_at')
    ordering = ('-created_at',)
    inlines = [SettlementPaymentInline]


@admin.register(SettlementPayment)
class SettlementPaymentAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'settlement',
        'amount_paise',
        'paid_at',
    )
    search_fields = (
        'settlement__group__name',
    )
    ordering = ('-paid_at',)