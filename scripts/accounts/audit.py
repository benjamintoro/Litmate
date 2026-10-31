"""Inventario de cuentas y planes: sólo SELECT, sin datos personales ni secretos."""
import argparse
import getpass
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Conserva el informe previo y usa otro nombre.')
    from iniciar_mysql_local import local_database_environment
    with local_database_environment(getpass.getpass('Contraseña MySQL local (oculta): ')):
        os.environ['DJANGO_SETTINGS_MODULE'] = 'litmate_project.settings'
        import django
        django.setup()
        from django.db import connection
        from django.conf import settings
        with connection.cursor() as cursor:
            cursor.execute('SET SESSION TRANSACTION READ ONLY')
            cursor.execute('SELECT DATABASE(), @@session.transaction_read_only')
            database, readonly = cursor.fetchone()
            if database != 'litmate_db' or not readonly:
                raise ValueError('Se requiere MySQL local y sesión de sólo lectura.')
            from suscripciones.models import PlanSuscripcion
            fields = ['nombre', 'slug', 'descripcion', 'precio', 'moneda', 'periodo',
                      'limite_consultas_ia_diarias', 'limite_favoritos', 'acceso_ia_avanzada', 'activo', 'orden']
            plans = list(PlanSuscripcion.objects.using('default').values(*fields).order_by('orden', 'precio'))
            counts = {}
            for table in ['auth_user', 'core_perfilusuario', 'suscripciones_suscripcionusuario',
                          'suscripciones_historialpago', 'core_conversacionia', 'core_mensajeia']:
                cursor.execute('SELECT COUNT(*) FROM ' + connection.ops.quote_name(table))
                counts[table] = cursor.fetchone()[0]
        report = {'database': database, 'read_only': bool(readonly), 'plans': plans, 'counts': counts,
                  'timezone': settings.TIME_ZONE, 'existing_quotas_enabled': settings.LITMATE_USE_EXISTING_QUOTAS,
                  'payment_credentials_inspected_or_printed': False, 'writes': False}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, default=str, ensure_ascii=False, indent=2)
        print(json.dumps(report, default=str, ensure_ascii=True))


if __name__ == '__main__':
    main()
