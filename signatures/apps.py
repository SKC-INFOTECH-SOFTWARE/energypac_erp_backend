from django.apps import AppConfig


class SignaturesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'signatures'
    verbose_name = 'Signatures & Verification'

    def ready(self):
        """Register signal handlers"""
        import signatures.signals  # noqa

