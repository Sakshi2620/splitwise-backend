from django.contrib import admin

from .models import (
    User,
    Group,
    GroupMember,
    Expense,
    ExpenseShare
)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'name',
        'email',
        'avatar_color',
        'created_at',
    )

    search_fields = (
        'name',
        'email',
    )

    list_filter = (
        'created_at',
    )

    ordering = (
        '-created_at',
    )


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'name',
        'category',
        'created_by',
        'currency',
        'created_at',
        'updated_at',
    )

    search_fields = (
        'name',
        'description',
    )

    list_filter = (
        'category',
        'currency',
        'created_at',
    )

    ordering = (
        '-created_at',
    )


@admin.register(GroupMember)
class GroupMemberAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'group',
        'user',
        'joined_at',
    )

    search_fields = (
        'group__name',
        'user__name',
        'user__email',
    )

    list_filter = (
        'joined_at',
    )

    ordering = (
        '-joined_at',
    )


class ExpenseShareInline(admin.TabularInline):
    model = ExpenseShare
    extra = 1


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'description',
        'group',
        'paid_by',
        'amount_display',
        'currency',
        'split_mode',
        'date',
        'ai_parsed',
        'created_at',
    )

    search_fields = (
        'description',
        'group__name',
        'paid_by__name',
    )

    list_filter = (
        'split_mode',
        'currency',
        'ai_parsed',
        'date',
        'created_at',
    )

    ordering = (
        '-date',
        '-created_at',
    )

    inlines = [ExpenseShareInline]


@admin.register(ExpenseShare)
class ExpenseShareAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'expense',
        'user',
        'amount_paise',
        'share_weight',
    )

    search_fields = (
        'expense__description',
        'user__name',
        'user__email',
    )

    list_filter = (
        'share_weight',
    )