"""Renovaciones con reloj controlado, exclusivamente en un almacén sintético."""
import argparse
import json
from pathlib import Path
from django.utils.dateparse import parse_datetime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--at', required=True)
    parser.add_argument('--user', help='Nombre de una cuenta sintética del ensayo.')
    parser.add_argument('--scenario', choices=['approved', 'rejected', 'temporary'], default='approved')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    folder = args.folder.resolve()
    if not folder.is_relative_to(root/'.testtmp') or not (folder/'checkout-synthetic.json').is_file():
        parser.error('Se requiere el almacén sintético identificado del ensayo de checkout.')
    if json.loads((folder/'checkout-synthetic.json').read_text()) != {'synthetic_checkout': True}:
        parser.error('Marcador sintético inválido.')
    at = parse_datetime(args.at)
    if at is None or at.tzinfo is None:
        parser.error('Indica fecha ISO con zona horaria.')
    if not (folder/'accounts/users.sqlite3').is_file():
        parser.error('Falta el almacén sintético existente.')
    from scripts.accounts.community_test_settings import configure
    configure(folder)
    import os
    os.environ.update(LITMATE_SIMULATED_CHECKOUT_ENABLED='1', LITMATE_CHECKOUT_TEST_SCENARIOS='1')
    from reader_accounts.signing_key import load_key
    os.environ['SECRET_KEY'] = load_key(folder/'accounts/users.sqlite3')
    import django
    django.setup()
    from django.contrib.auth.models import User
    from reader_accounts.simulated_checkout import renew_due
    results = []
    users = User.objects.filter(suscripcion__fecha_fin__lte=at)
    if args.user:
        users = users.filter(username=args.user)
    for user in users:
        order = renew_due(user, at=at, scenario=args.scenario)
        if order:
            results.append({'order': str(order.pk), 'state': order.state, 'kind': order.kind})
    print(json.dumps({'synthetic_only': True, 'renewals': results}))


if __name__ == '__main__':
    main()
