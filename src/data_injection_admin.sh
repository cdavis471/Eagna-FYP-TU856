#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f "venv/bin/activate" ]; then
  source venv/bin/activate
elif [ -f "../venv/bin/activate" ]; then
  source ../venv/bin/activate
fi

python manage.py migrate

echo "Creating admin user..."

python manage.py shell <<'PY'
from apps.accounts.models import User

USERNAME = "cdavis471@outlook.com"
PASSWORD = "DevPass123!"
FIRST_NAME = "Conor"
LAST_NAME = "Davis"

existing = User.objects.filter(username__iexact=USERNAME).first()

if existing:
    existing.email = USERNAME
    existing.first_name = FIRST_NAME
    existing.last_name = LAST_NAME
    existing.role = User.Role.ADMIN
    existing.is_staff = True
    existing.is_superuser = True
    existing.is_active = True
    existing.set_password(PASSWORD)
    existing.save()
    print(f"Updated existing admin user: {USERNAME}")
    
else:
    User.objects.create_superuser(
        username=USERNAME,
        email=USERNAME,
        password=PASSWORD,
        first_name=FIRST_NAME,
        last_name=LAST_NAME,
        role=User.Role.ADMIN,
    )
    print(f"Created admin user: {USERNAME}")
PY

echo "Admin seed complete."
