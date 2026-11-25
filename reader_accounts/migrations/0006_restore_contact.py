from django.db import migrations


def restore_contact_table(apps, schema_editor):
    model = apps.get_model('core', 'MensajeContacto')
    if model._meta.db_table not in schema_editor.connection.introspection.table_names():
        schema_editor.create_model(model)


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0008_bibliographic_repository'),
        ('reader_accounts', '0005_simulated_checkout'),
    ]
    # La tabla original no se creó en accounts cuando el router la excluía.
    # Conservar mensajes al revertir el código o el marcador de migración.
    operations = [migrations.RunPython(restore_contact_table, migrations.RunPython.noop)]
