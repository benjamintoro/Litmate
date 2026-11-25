"""Reutiliza tablas personales de core sólo en el almacén privado.

El catálogo no se copia. libro_id se conserva como referencia externa opcional,
sin una FK física entre SQLite y MySQL; las FK de propietarios sí se conservan.
También admite almacenes preparados antes de ampliar el router.
"""
from django.db import migrations


def private_tables(apps, schema_editor):
    if schema_editor.connection.alias != 'accounts':
        return
    names = set(schema_editor.connection.introspection.table_names())
    for name in ('ListaLectura', 'ElementoListaLectura', 'LibroFavorito'):
        model = apps.get_model('core', name)
        field = model._meta.get_field('libro') if name == 'LibroFavorito' else None
        previous = field.db_constraint if field else None
        try:
            if model._meta.db_table not in names:
                if field:
                    field.db_constraint = False
                schema_editor.create_model(model)
            elif field:
                replacement = field.clone()
                replacement.set_attributes_from_name('libro')
                replacement.model = model
                replacement.remote_field.model = field.remote_field.model
                replacement.db_constraint = False
                schema_editor.alter_field(model, field, replacement)
        finally:
            if field:
                field.db_constraint = previous


class Migration(migrations.Migration):
    dependencies = [('reader_accounts', '0001_initial'), ('core', '0008_bibliographic_repository')]
    operations = [migrations.RunPython(private_tables)]
