from django.conf import settings

def analytics_processor(request):
    return {
        'GOOGLE_ANALYTICS_ID': getattr(settings, 'GOOGLE_ANALYTICS_ID', '')
    }

