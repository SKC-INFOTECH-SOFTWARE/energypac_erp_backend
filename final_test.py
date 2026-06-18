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

endpoints = ["/api/pi-bills/", "/api/products/", "/api/vendors/", "/api/notifications/"]
print("Testing endpoints after fix:\n")
for endpoint in endpoints:
    resp = client.get(endpoint, **headers)
    status = "OK" if resp.status_code in [200, 403] else "FAIL"
    icon = "OK" if status == "OK" else "X"
    sys.stdout.buffer.write(f"[{icon}] {endpoint}: HTTP {resp.status_code}\n".encode())
