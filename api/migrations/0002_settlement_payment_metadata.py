from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='settlement',
            name='completed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='settlementpayment',
            name='paid_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='settlement_payments_made',
                to='api.groupmember',
            ),
        ),
        migrations.AddField(
            model_name='settlementpayment',
            name='paid_to',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='settlement_payments_received',
                to='api.groupmember',
            ),
        ),
        migrations.AddField(
            model_name='settlementpayment',
            name='payment_type',
            field=models.CharField(choices=[('partial', 'Partial'), ('full', 'Full')], default='partial', max_length=10),
        ),
        migrations.AddField(
            model_name='settlementpayment',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
    ]
