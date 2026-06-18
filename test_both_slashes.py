# -*- coding: utf-8 -*-
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "erp_energypac.settings")
import django
django.setup()

from django.test import Client
from rest_framework_simplejwt.tokens import AccessToken
from django.contrib.auth import get_user_model

User = get_user_model()
user = User.objects.first()
token = AccessToken.for_user(user)

client = Client()
headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

# Test URLs with AND without trailing slashes
test_cases = [
    ("/api/vendor-quotations", "no slash"),
    ("/api/vendor-quotations/", "with slash"),
    ("/api/vendors", "no slash"),
    ("/api/vendors/", "with slash"),
]

print("Testing URLs:\n")
for url, desc in test_cases:
    resp = client.get(url, **headers)
    status = "OK" if resp.status_code in [200, 403] else "FAIL"
    print(f"[{status}] {url:30} ({desc}): HTTP {resp.status_code}")
