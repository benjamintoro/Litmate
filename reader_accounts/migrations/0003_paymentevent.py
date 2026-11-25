from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('reader_accounts', '0002_personal_library'), ('suscripciones', '0001_initial')]
    operations = [migrations.CreateModel(
        name='PaymentEvent',
        fields=[('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('provider', models.CharField(max_length=50)),
                ('event_id', models.CharField(max_length=100)),
                ('digest', models.CharField(max_length=64)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('payment', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='suscripciones.historialpago'))],
        options={'constraints': [models.UniqueConstraint(fields=('provider', 'event_id'), name='reader_provider_event')]},
    )]
