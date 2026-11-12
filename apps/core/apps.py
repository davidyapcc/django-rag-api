from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"

    def ready(self) -> None:
        from . import errors, tracing

        tracing.configure()
        errors.configure()
