# -*- coding: utf-8 -*-
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "erp_energypac.settings")
import django
django.setup()

from django.test import Client
from rest_framework_simplejwt.tokens import AccessToken
from django.contrib.auth import get_user_model
import json

User = get_user_model()
user = User.objects.first()
token = AccessToken.for_user(user)

client = Client()
headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

# Test GET endpoint
print("1. Testing GET /api/vendor-quotations:")
resp = client.get("/api/vendor-quotations", **headers)
print(f"   Status: HTTP {resp.status_code}")

# Test POST endpoint
print("\n2. Testing POST /api/vendor-quotations:")
payload = {
    "requisition": "test-id",
    "vendor": "test-id",
    "currency": "INR",
    "items": []
}
resp = client.post("/api/vendor-quotations", data=json.dumps(payload), 
                   content_type="application/json", **headers)
print(f"   Status: HTTP {resp.status_code}")
if resp.status_code != 200:
    print(f"   Response: {resp.content.decode()[:200]}")

# Test custom action endpoint
print("\n3. Testing GET /api/vendor-quotations/by_requisition_vendor:")
resp = client.get("/api/vendor-quotations/by_requisition_vendor?requisition=test&vendor=test", **headers)
print(f"   Status: HTTP {resp.status_code}")
if resp.status_code != 200:
    print(f"   Error: {resp.content.decode()[:150]}")
