def presentation(request):
    from django.conf import settings
    production=hasattr(settings,'PRODUCTION')
    return {'reader_accounts_enabled':True, 'simulated_checkout_enabled':getattr(settings, 'LITMATE_SIMULATED_CHECKOUT_ENABLED', False), 'production_mode':production,
            'community_enabled': settings.LITMATE_COMMUNITY_ENABLED,
            'social_login_enabled':not production}
