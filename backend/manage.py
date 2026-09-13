import os
import sys


def main():
    # `manage.py test` uses a dedicated settings module: the default one reads
    # DATABASE_URL from .env, which points at the hosted database.
    default_settings = 'config.settings_test' if 'test' in sys.argv else 'config.settings'
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', default_settings)

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            'Не удалось импортировать Django. Активирован ли virtualenv и '
            'установлены ли зависимости (pip install -r requirements.txt)?'
        ) from exc

    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
