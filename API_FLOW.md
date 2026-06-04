# EnergyPac ERP - Complete API & Flow Documentation

Base URL: `/api/`  
Authentication: JWT Bearer Token (8-hour expiry)  
Header: `Authorization: Bearer <access_token>`

---

## Complete Business Flow

```
┌────────────────────────────────────────────────────────────────────────────┐
│                         EnergyPac ERP Flow                                 │
│                                                                            │
│  ┌──────────────┐    ┌──────────────┐  ┌──────────────┐                  │
│  │  Client Query │───▶│    Sales     │───▶│  Requisition │                  │
│  │  (Lead Entry) │    │  Quotation   │    │(Items Needed)│                  │
│  └──────────────┘    └──────────────┘    └──────┬───────┘                  │
│                                                  │                         │
│                    ┌─────────────────────────────┼──────────────┐           │
│                    │                             │              │           │
│                    ▼                             ▼              ▼           │
│  ┌──────────────────────┐   ┌──────────────────────┐  ┌─────────────────┐  │
│  │ Vendor Assignment    │   │  Proforma Invoice     │  │  Purchase Order │  │
│  │ + Quotation          │   │  (Sell to Client)     │  │  (Buy from      │  │
│  │ + Price Comparison   │   │  PI = Items Total     │  │   Vendor)       │  │
│  └──────────┬───────────┘   │  No GST, No Discount  │  │  GST + Discount │  │
│             │               └──────────┬────────────┘  └────────┬────────┘  │
│             ▼                          │                        │           │
│  ┌─────────────────┐                  │                        │           │
│  │  PO Generation  │◀─── from ────────┤                        │           │
│  │  (from Vendor   │     comparison   │                        │           │
│  │   Quotations)   │                  │                        │           │
│  └─────────────────┘                  │                        │           │
│                                       ▼                        ▼           │
│                          ┌──────────────────┐      ┌──────────────────┐    │
│                          │     PI Bill      │      │    Transport     │    │
│                          │  (GST + Discount │      │  (PO or PI)     │    │
│                          │   applied here)  │      │  Landed Cost    │    │
│                          └────────┬─────────┘      └────────┬────────┘    │
│                                   │                         │             │
│                                   ▼                         ▼             │
│                          ┌──────────────────────────────────────────┐      │
│                          │              Finance Module              │      │
│                          │                                          │      │
│                          │  ▸ PO Payments (outgoing to vendors)    │      │
│                          │  ▸ PI Payments (incoming from clients)  │      │
│                          │  ▸ Advance Payments (against PI)        │      │
│                          │  ▸ PI Bill Payments (against bills)     │      │
│                          │  ▸ P&L Reports (all in INR)            │      │
│                          │  ▸ Due Date Tracking                    │      │
│                          │  ▸ Reconciliation                       │      │
│                          └──────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Concepts

| Concept | Detail |
|---------|--------|
| **PI (Proforma Invoice)** | Simple items total — NO GST, NO discount. Sent to client for acceptance. |
| **PI Bill** | Generated AFTER client accepts PI. GST + discount applied here. This is the actual billing document. |
| **Advance Payment** | Always against a PI. Currency & conversion_rate auto-inherited from PI. |
| **Multi-Currency** | Amounts in original currency + immutable conversion_rate. All P&L in INR. |

---

## Authentication

### Login
```
POST /api/auth/login
```
```json
{
  "email": "user@company.com",
  "password": "your-password"
}
```
Returns: `access` (8hr), `refresh` tokens, user profile.

### Refresh Token
```
POST /api/auth/refresh
```
```json
{ "refresh": "refresh-token" }
```

### Profile
```
GET /api/auth/profile
```

### Forgot / Reset Password
```
POST /api/auth/forgot-password     → { "email": "..." }
POST /api/auth/verify-otp          → { "email": "...", "otp": "123456" }
POST /api/auth/reset-password      → { "email": "...", "otp": "...", "new_password": "..." }
```

---

## Step 1: Client Query (Lead Entry)

```
POST /api/client-queries
```
```json
{
  "client_name": "ABC International",
  "client_email": "abc@client.com",
  "client_phone": "+91-9876543210",
  "client_address": "Dubai, UAE",
  "query_date": "2026-05-20",
  "requirements": "Need steel rods and copper wire",
  "priority": "HIGH"
}
```

```
GET /api/client-queries                    → List all queries
GET /api/client-queries/{id}               → Query detail
PATCH /api/client-queries/{id}             → Update
```

---

## Step 2: Sales Quotation

```
POST /api/quotations
```
```json
{
  "client_query": "query-uuid",
  "quotation_date": "2026-05-21",
  "currency": "USD",
  "conversion_rate": 84.50,
  "validity_days": 30,
  "remarks": "As per your inquiry"
}
```

### Add Items to Quotation
```
POST /api/quotation-items
```
```json
{
  "sales_quotation": "quotation-uuid",
  "product": "product-uuid",
  "quantity": 100,
  "unit_price": 250.00
}
```

```
GET /api/quotations                        → List quotations
GET /api/quotations/{id}                   → Detail
PATCH /api/quotations/{id}                 → Update
GET /api/quotation-items?sales_quotation=uuid → Items for a quotation
```

---

## Step 3: Create Requisition (Purchase Request)

A requisition is the central entity linking procurement and sales.

```
POST /api/requisitions
```
```json
{
  "requisition_number": "EEL/2026/001",
  "requisition_date": "2026-05-22",
  "remarks": "Urgent requirement for project X",
  "items": [
    {
      "product": "product-uuid",
      "quantity": 100,
      "remarks": "Need high quality"
    }
  ]
}
```
- `requisition_number` is optional — auto-generates as `EEL/YEAR/NUMBER` if not provided
- Each product used gets `requisition_number` saved in the Item Master

```
GET /api/requisitions                      → List (filter: ?is_assigned=true&search=EEL)
GET /api/requisitions/{id}                 → Detail
GET /api/requisitions/{id}/items           → Requisition items
GET /api/requisitions/{id}/flow            → Complete flow (Requisition → Assignments → Quotations)
```

---

## Step 4: Assign Vendors to Requisition

```
POST /api/vendor-assignments
```
```json
{
  "requisition": "requisition-uuid",
  "vendor": "vendor-uuid",
  "remarks": "Request quotation for all items",
  "items": [
    {
      "requisition_item": "requisition-item-uuid",
      "quantity": 100
    }
  ]
}
```
- One vendor per requisition (unique constraint)

```
GET /api/requisitions/{id}/assignments             → Assignments for requisition
GET /api/vendor-assignments/{id}/items_for_quotation → Items for quotation entry
```

---

## Step 5: Enter Vendor Quotation

```
POST /api/vendor-quotations
```
```json
{
  "requisition": "requisition-uuid",
  "vendor": "vendor-uuid",
  "currency": "INR",
  "reference_number": "VENDOR-REF-123",
  "validity_date": "2026-06-22",
  "payment_terms": "30 days",
  "delivery_terms": "Ex-works",
  "items": [
    {
      "vendor_item": "vendor-requisition-item-uuid",
      "quoted_rate": 250.50
    }
  ]
}
```

```
GET /api/vendor-quotations                          → List all
GET /api/vendor-quotations/by_vendor?vendor=uuid     → By vendor
GET /api/vendor-quotations/by_requisition?requisition=uuid → By requisition
GET /api/vendor-quotations/by_requisition_vendor?requisition=uuid&vendor=uuid
```

---

## Step 6: Price Comparison

```
GET /api/requisitions/{id}/comparison
```
Returns all vendors with their quotations side-by-side. Each vendor entry has its `currency`. Cross-currency visible — frontend groups by currency.

---

## Step 7: Select Vendor

```
POST /api/vendor-quotations/{id}/select
```
Marks this quotation as selected (deselects others for the same requisition).

---

## Step 8: Generate Purchase Order

```
POST /api/purchase-orders/generate_from_comparison
```
```json
{
  "requisition": "requisition-uuid",
  "po_date": "2026-05-22",
  "subject": "Steel materials for Phase 2",
  "project_name": "Kolkata Metro Phase 2",
  "bill_to": "EnergyPac Engineering Ltd, 12 Park Street, Kolkata",
  "ship_to": "Site Office, Kolkata Metro Phase 2, Salt Lake",
  "terms_and_conditions": [
    "Delivery within 30 days from PO date",
    "Payment: 50% advance, 50% on delivery",
    {"type": "warranty", "value": "12 months from delivery"}
  ],
  "selections": [
    "quotation-item-uuid-1",
    "quotation-item-uuid-2"
  ],
  "discount_amount": 20.00,
  "cgst_percentage": 9.00,
  "sgst_percentage": 9.00,
  "igst_percentage": 0.00,
  "conversion_rate": 83.50
}
```
- System groups items by vendor → creates one PO per vendor
- PO Number: `EEL/IND/<VENDOR_PREFIX>/<NUMBER>` (starts from 100)
- GST calculated on `items_total`. Total = `items_total + GST - discount`
- Currency inherited from vendor's quotation
- `conversion_rate` = INR rate at PO creation (immutable)

---

## Step 9: Edit PO (Full Edit with Lock & Revision)

### Acquire Lock
```
POST /api/purchase-orders/{id}/lock
```
30-minute lock. Returns 409 if locked by another user.

### Edit PO
```
PATCH /api/purchase-orders/{id}
```
```json
{
  "po_date": "2026-05-25",
  "discount_amount": 500.00,
  "cgst_percentage": 12.00,
  "sgst_percentage": 12.00,
  "items": [
    { "id": "existing-item-uuid", "product": "uuid", "quantity": 150, "rate": 275.00 },
    { "product": "new-product-uuid", "quantity": 50, "rate": 300.00 }
  ]
}
```

**Editable:** `po_date`, `subject`, `project_name`, `bill_to`, `ship_to`, `terms_and_conditions`, `remarks`, `discount_amount`, GST percentages, `items`.

**Rules:**
- Send `id` → update existing item. Omit `id` → add new. Missing items → deleted.
- Items marked as "received" cannot be edited/removed.
- First edit: PO number gets "R" suffix. `revision_number` increments each edit.
- Audit log created on every update.

### Release Lock
```
POST /api/purchase-orders/{id}/unlock
```

---

## Step 10: Update GST on PO

```
POST /api/purchase-orders/{id}/update_gst
```
```json
{
  "cgst_percentage": 9.00,
  "sgst_percentage": 9.00,
  "igst_percentage": 0.00
}
```





---

## Step 11: Mark Items as Purchased (Received)

```
POST /api/purchase-orders/{id}/mark_item_purchased
```
```json
{ "item_id": "po-item-uuid" }
```
Updates inventory stock. PO status: PENDING → PARTIALLY_RECEIVED → COMPLETED.

```
POST /api/purchase-orders/{id}/mark_all_purchased    → Mark all items
```

---

## Step 12: Cancel PO (Password Protected)

```
POST /api/purchase-orders/{id}/cancel
```
```json
{
  "confirm_password": "your-password",
  "reason": "Vendor could not supply on time"
}
```
If items were received, stock is reversed.

---

## Step 13: Create Proforma Invoice (PI)


PI is a simple items total — **NO GST, NO discount** on PI. Those are applied later on the PI Bill.

### Check Requisition Items Purchase Status
```
GET /api/proforma-invoices/requisition_items?requisition=uuid
```
Shows which items are COMPLETED / PO_CREATED / PENDING.

### Create PI
```
POST /api/proforma-invoices
```
```json
{
  "requisition": "requisition-uuid",
  "pi_date": "2026-05-25",
  "currency": "USD",
  "conversion_rate": 84.5000,
  "payment_due_date": "2026-06-25",
  "lc_number": "LC-2026-001",
  "exporter_beneficiary": "EnergyPac Engineering Ltd",
  "consignee": "ABC Corp, Dubai",
  "applicant_importer": "ABC Trading LLC, UAE",
  "port_of_loading": "Kolkata Port",
  "port_of_discharge": "Jebel Ali",
  "terms_of_delivery": "FOB Kolkata",
  "terms_of_payment": "Irrevocable L/C at sight",
  "items": [
    {
      "product": "product-uuid-1",
      "hsn_code": "254125",
      "quantity": 100,
      "unit_price": 250.00
    }
  ],
  "terms_and_conditions": ["Shipment within 45 days", "Inspection certificate required"],
  "notes": "Priority handling"
}
```

- PI Number: `EEL/IND/PI/{YEAR}/{NUMBER}` (e.g., `EEL/IND/PI/2026/0001`)
- `grand_total` = sum of all items (quantity × unit_price). **No GST, no discount.**
- `conversion_rate` is immutable after creation
- All header fields are optional. Only `requisition`, `pi_date`, `currency`, `items` are required.

```
GET /api/proforma-invoices                 → List (filter: ?requisition=uuid&status=DRAFT&currency=USD)
GET /api/proforma-invoices/{id}            → Detail
```

### Edit PI (Lock + Revision)
```
POST /api/proforma-invoices/{id}/lock      → Acquire lock
PATCH /api/proforma-invoices/{id}          → Edit (same rules as PO edit)
POST /api/proforma-invoices/{id}/unlock    → Release lock
```
First edit appends "R" to PI number. `revision_number` increments.

### PI Status Flow

```
DRAFT → SENT → ACCEPTED
  |       |        |
  └───────┴────────┴──→ CANCELLED (password required)
```

**Allowed Transitions:**
| Current Status | Can Move To |
|----------------|-------------|
| DRAFT | SENT, CANCELLED |
| SENT | ACCEPTED, CANCELLED |
| ACCEPTED | CANCELLED |
| CANCELLED | _(dead end)_ |

#### Send PI to Client
```
POST /api/proforma-invoices/{id}/send
```
Moves status from `DRAFT` → `SENT`. No body required.

#### Client Accepts PI
```
POST /api/proforma-invoices/{id}/accept
```
Moves status from `SENT` → `ACCEPTED`. No body required.

#### Cancel PI (Password Protected)
```
POST /api/proforma-invoices/{id}/cancel
```
```json
{
  "confirm_password": "your-password"
}
```
Can cancel from any status (DRAFT / SENT / ACCEPTED). Cannot cancel an already cancelled PI.

All status changes are logged in Audit Log automatically.

---

## Step 14: Generate PI Bill (GST + Discount applied here)

PI Bill is generated when client accepts the PI. This is where GST and discount get applied.

### Create PI Bill
```
POST /api/pi-bills
```
```json
{
  "proforma_invoice": "pi-uuid",
  "bill_date": "2026-05-26",
  "bill_type": "INTERNATIONAL",
  "client_name": "ABC International, Dubai",
  "contact_person": "Mr. Ahmed",
  "phone": "+971-555-1234",
  "email": "ahmed@abc.com",
  "address": "Dubai, UAE",
  "cgst_percentage": 0,
  "sgst_percentage": 0,
  "igst_percentage": 18,
  "discount_amount": 500.00,
  "remarks": "Against PI EEL/IND/PI/2026/0001",
  "items": [
    {
      "pi_item": "pi-item-uuid",
      "item_name": "Steel Rod 10mm",
      "hsn_code": "7214",
      "unit": "KG",
      "quantity": 100,
      "rate": 250.00
    },
    {
      "product": "product-uuid",
      "item_name": "Copper Wire 5mm",
      "hsn_code": "7408",
      "unit": "MTR",
      "quantity": 200,
      "rate": 150.00
    }
  ]
}
```

**Auto behavior:**
- Bill Number: `PIB/{YEAR}/{NUMBER}` (e.g., `PIB/2026/0001`)
- `currency` and `conversion_rate` auto-inherited from PI
- `subtotal` = sum of items (quantity × rate)
- GST calculated on subtotal
- `total_amount = subtotal + GST - discount`
- `net_payable = total_amount`
- `balance = net_payable - amount_paid`

**Item linking:**
- `pi_item` = link to specific PI item (optional). If provided, product is auto-resolved.
- `product` = link to product directly (if pi_item not provided)
- Both are optional — but at least one is recommended for traceability

**Response:**
```json
{
  "id": "uuid",
  "bill_number": "PIB/2026/0001",
  "bill_type": "INTERNATIONAL",
  "proforma_invoice": "pi-uuid",
  "pi_number": "EEL/IND/PI/2026/0001",
  "bill_date": "2026-05-26",
  "client_name": "ABC International, Dubai",
  "currency": "USD",
  "conversion_rate": 84.5000,
  "subtotal": 55000.00,
  "cgst_percentage": 0,
  "sgst_percentage": 0,
  "igst_percentage": 18,
  "cgst_amount": 0,
  "sgst_amount": 0,
  "igst_amount": 9900.00,
  "total_gst": 9900.00,
  "discount_amount": 500.00,
  "total_amount": 64400.00,
  "net_payable": 64400.00,
  "amount_paid": 0,
  "balance": 64400.00,
  "status": "GENERATED",
  "items": [...]
}
```

### List PI Bills
```
GET /api/pi-bills
```
Query params: `?status=GENERATED&proforma_invoice=uuid&bill_type=DOMESTIC&search=PIB`

### Get PI Bill Detail
```
GET /api/pi-bills/{id}
```

### Bills by PI
```
GET /api/pi-bills/by_pi?proforma_invoice=pi-uuid
```

### Pending Payment Bills
```
GET /api/pi-bills/pending_payment
```

### Record Payment on PI Bill (Password Protected)
```
POST /api/pi-bills/{id}/mark_paid
```
```json
{
  "confirm_password": "your-password",
  "amount_paid": 30000.00,
  "payment_date": "2026-05-28",
  "payment_mode": "NEFT",
  "reference_number": "UTR123456",
  "remarks": "First installment"
}
```
Payment modes: `CASH`, `CHEQUE`, `NEFT`, `RTGS`, `IMPS`, `UPI`, `LC`, `TT`, `OTHER`

Each payment creates a `PIBillPayment` record with running totals. When `balance = 0`, status auto-set to `PAID`.

### PI Bill Payment History
```
GET /api/pi-bills/{id}/payment_history
```
Returns all payment records for the bill with running totals.

**Response:**
```json
{
  "bill_number": "PIB/2026/0001",
  "net_payable": 64400.00,
  "total_paid": 30000.00,
  "balance": 34400.00,
  "status": "GENERATED",
  "total_payments": 1,
  "payments": [
    {
      "payment_number": 1,
      "amount": 30000.00,
      "payment_date": "2026-05-28",
      "payment_mode": "NEFT",
      "payment_mode_display": "NEFT",
      "reference_number": "UTR123456",
      "remarks": "First installment",
      "total_paid_after": 30000.00,
      "balance_after": 34400.00,
      "recorded_by_name": "Admin User"
    }
  ]
}
```

### Cancel PI Bill (Password Protected)
```
POST /api/pi-bills/{id}/cancel
```
```json
{
  "confirm_password": "your-password"
}
```
Cannot cancel a paid bill.

### PI Bill Status Flow
```
GENERATED → PAID
    |
    v
CANCELLED
```

---

## Item Master (Products)

```
POST /api/products                         → Create item
GET /api/products                          → List (filter: ?is_active=true&unit=KG&search=steel)
GET /api/products/{id}                     → Detail
PATCH /api/products/{id}                   → Update
GET /api/products/by_requisition?requisition_number=EEL/2026/001 → By requisition
GET /api/products/low_stock                → Low stock items
POST /api/products/bulk-upload             → Bulk upload (Excel)
GET /api/products/bulk-upload-template     → Download template
```

```json
{
  "item_name": "Steel Rod 10mm",
  "description": "High tensile steel rod",
  "hsn_code": "7214",
  "unit": "KG",
  "rate": 250.00,
  "requisition_number": "EEL/2026/001"
}
```
`item_code` auto-generated (e.g., `ITEM/0001`).

---

## Vendor Master

```
POST /api/vendors                          → Create vendor
GET /api/vendors                           → List
GET /api/vendors/{id}                      → Detail
PATCH /api/vendors/{id}                    → Update
```

---

## Transport Module (PO + PI Support)

Track transport/logistics costs. Calculates landed cost per item.

### Create Transport Entry
```
POST /api/transport
```
```json
{
  "purchase_order": "po-uuid",
  "transporter_name": "Blue Dart Logistics",
  "transporter_contact": "9876543210",
  "vehicle_number": "MH12AB1234",
  "driver_name": "Raju",
  "driver_contact": "9876543211",
  "dispatch_date": "2026-05-22",
  "expected_delivery_date": "2026-05-25",
  "dispatch_from": "Mumbai",
  "dispatch_to": "Pune",
  "cost_items": [
    { "cost_type": "FREIGHT", "description": "Mumbai to Pune", "amount": 3500.00 },
    { "cost_type": "LOADING", "amount": 500.00 },
    { "cost_type": "INSURANCE", "description": "Transit insurance", "amount": 800.00 }
  ]
}
```
- Use `purchase_order` for PO transport, `proforma_invoice` for PI transport
- Transport number auto-generated: `TRN/YEAR/NUMBER`
- Cost types: `FREIGHT`, `LOADING`, `UNLOADING`, `INSURANCE`, `CUSTOMS`, `OCTROI`, `HANDLING`, `PACKAGING`, `TOLL`, `OTHER`

```
GET /api/transport                                → List
PATCH /api/transport/{id}                         → Update
POST /api/transport/{id}/mark_delivered           → Mark delivered
GET /api/transport/by_po?purchase_order=uuid      → By PO
GET /api/transport/by_pi?proforma_invoice=uuid    → By PI
GET /api/transport/landed_cost?purchase_order=uuid → Landed cost (PO)
GET /api/transport/landed_cost_pi?proforma_invoice=uuid → Landed cost (PI)
```

### Transport Reports
```
GET /api/reports/transport/by-po           → Transport cost by PO
GET /api/reports/transport/by-vendor       → Transport cost by vendor
GET /api/reports/transport/cost-breakdown  → By cost type
GET /api/reports/transport/landed-cost     → Item-wise landed cost
GET /api/dashboard/transport               → Transport dashboard
```

---

## Finance Module

### Record Payment to Vendor (against PO)
```
POST /api/finance/purchase-orders/{id}/record_payment
```
```json
{
  "confirm_password": "your-password",
  "amount": 15000.00,
  "payment_date": "2026-05-22",
  "payment_mode": "NEFT",
  "reference_number": "UTR123456",
  "remarks": "First installment"
}
```
Payment modes: `CASH`, `CHEQUE`, `NEFT`, `RTGS`, `IMPS`, `UPI`, `OTHER`

### Record Payment from Client (against PI)
```
POST /api/finance/proforma-invoices/{id}/record_payment
```
```json
{
  "confirm_password": "your-password",
  "amount": 5000.00,
  "payment_date": "2026-05-25",
  "payment_mode": "TT",
  "reference_number": "SWIFT-REF-123",
  "remarks": "Advance payment"
}
```
Payment modes: `CASH`, `CHEQUE`, `NEFT`, `RTGS`, `IMPS`, `UPI`, `LC`, `TT`, `OTHER`

When `amount_received == grand_total`, PI status auto-set to `ACCEPTED`.

### Advance Payment (Always against PI)

Client advance is always against a specific PI. Currency and conversion_rate are **auto-inherited from the linked PI** — you don't send them.

**Create Advance Payment:**
```
POST /api/finance/advance-payments
```
```json
{
  "proforma_invoice": "pi-uuid",
  "client_name": "ABC International",
  "amount": 100000.00,
  "payment_date": "2026-05-25",
  "payment_mode": "TT",
  "reference_number": "TT-REF-001",
  "remarks": "30% advance as per PI terms"
}
```

**Auto-populated from PI:**
- `currency` — inherited from PI's currency
- `conversion_rate` — inherited from PI's conversion_rate

**Auto-calculated:**
- `amount_inr` = amount × conversion_rate (or just amount if INR)
- `remaining` = amount - amount_used
- `advance_number` = `ADV/2026/0001` (auto)

**Response:**
```json
{
  "id": "uuid",
  "advance_number": "ADV/2026/0001",
  "proforma_invoice": "pi-uuid",
  "pi_number": "EEL/IND/PI/2026/0001",
  "client_name": "ABC International",
  "amount": 100000.00,
  "currency": "USD",
  "conversion_rate": 84.5000,
  "amount_inr": 8450000.00,
  "amount_used": 0,
  "remaining": 100000.00,
  "payment_date": "2026-05-25",
  "payment_mode": "TT",
  "status": "ACTIVE"
}
```

**List Advance Payments:**
```
GET /api/finance/advance-payments
GET /api/finance/advance-payments?status=ACTIVE&proforma_invoice=uuid&currency=USD
```

**Adjust (Use) Advance:**
```
POST /api/finance/advance-payments/{id}/adjust
```
```json
{
  "amount": 50000.00
}
```
Deducts from remaining. When remaining = 0, status = `FULLY_USED`.

**Note:** Advance payments cannot be deleted.

---

### PO Finance Views
```
GET /api/finance/purchase-orders                   → List POs with finance summary
GET /api/finance/purchase-orders/{id}              → PO finance detail
GET /api/finance/purchase-orders/{id}/record_payment   → Pay vendor
GET /api/finance/purchase-orders/{id}/payment_history  → PO payment history
GET /api/finance/purchase-orders/{id}/purchased_items  → Items received
GET /api/finance/purchase-orders/pending_payments      → POs with outstanding
GET /api/finance/purchase-orders/overdue               → POs past due date
```

### PI Finance Views
```
GET /api/finance/proforma-invoices                 → List PIs with finance summary
GET /api/finance/proforma-invoices/{id}            → PI finance detail
POST /api/finance/proforma-invoices/{id}/record_payment → Record client payment
GET /api/finance/proforma-invoices/{id}/payment_history → PI payment history
GET /api/finance/proforma-invoices/pending_payments    → PIs with outstanding
GET /api/finance/proforma-invoices/overdue             → PIs past due date
```

### Flat Payment Lists
```
GET /api/finance/all-purchase-payments             → All vendor payments
GET /api/finance/all-pi-payments                   → All PI payments
```

### Profit & Loss (INR)
```
GET /api/finance/profit-loss                       → P&L per requisition
GET /api/finance/profit-loss?requisition=uuid       → P&L for specific requisition
GET /api/finance/profit-loss/items?requisition=uuid → P&L per item (with transport allocation)
POST /api/finance/profit-preview                    → Real-time profit check during PI creation
```

**Conversion Logic:**
- PO cost → INR = `po.total_amount × po.conversion_rate`
- PI revenue → INR = `pi.grand_total × pi.conversion_rate`
- True Cost = Purchase Cost (INR) + Transport (allocated by value %)
- Alerts: `LOSS` if profit < 0, `LOW_MARGIN` if margin < 10%

### Item Analytics
```
GET /api/finance/items/analytics                   → Per-item purchase/sale stats
GET /api/finance/items/insights                    → Most/least sold, most profitable
GET /api/finance/items/aging?threshold_days=90     → Slow-moving & dead stock
```

### Due Dates & Tracking
```
GET /api/finance/due-dates?upcoming_days=7         → Upcoming & overdue payments (vendor + client)
```

### Reconciliation & Validation
```
GET /api/finance/reconciliation                    → Detect overpayment, duplicates, missing transport
GET /api/finance/validation                        → Purchased-unpaid, paid-not-purchased, anomalies
```

### Finance Dashboard
```
GET /api/finance/dashboard
```
Returns: outgoing (vendor) totals, incoming (client) totals, transport costs, P&L summary, cash flow, advance status, purchase item stats, recent transactions.

---

## Currency Master

```
GET /api/currencies                                → List all (any authenticated user)
POST /api/currencies                               → Create (admin only)
PATCH /api/currencies/{id}                         → Update (admin only)
DELETE /api/currencies/{id}                         → Delete (admin only)
```
```json
{ "code": "EUR", "name": "Euro", "symbol": "€", "is_active": true }
```

### Exchange Rates
```
GET /api/exchange-rate                             → Current rates
GET /api/admin/exchange-rates                      → Admin: list rates
POST /api/admin/exchange-rates                     → Admin: create rate
PATCH /api/admin/exchange-rates/{id}               → Admin: update rate
```

---

## Audit Logs

Single API for all modules.

```
GET /api/audit-logs                                → List all logs
GET /api/audit-logs?model_name=PurchaseOrder       → Filter by module
GET /api/audit-logs?model_name=PurchaseOrder&action=UPDATE&user=uuid → Combined filters
GET /api/audit-logs/{model_name}/{object_id}       → History for specific object
```

**Logged automatically:** PO create/update/cancel, PI create/update, Transport create/update/deliver, Bill create/update.

---

## Reports

### Requisition Reports
```
GET /api/reports/requisitions                      → Requisition report
GET /api/reports/requisitions/{id}/detailed         → Detailed report
```

### Vendor Reports
```
GET /api/reports/vendors/performance               → Vendor performance
GET /api/reports/vendors/quotation-comparison       → Quotation comparison
```

### Purchase Order Reports
```
GET /api/reports/purchase-orders                   → PO report
```

### Inventory Reports
```
GET /api/reports/inventory/stock                   → Stock report
GET /api/reports/inventory/movement                → Movement report
```

### Financial Reports
```
GET /api/reports/financial/spending                → Spending analysis
```

### Sales Reports
```
GET /api/reports/sales/client-queries              → Client query report
GET /api/reports/sales/client-queries/{id}/detailed
GET /api/reports/sales/quotations                  → Quotation report
GET /api/reports/sales/quotation-items             → Quotation items
GET /api/reports/sales/analytics                   → Sales analytics
GET /api/reports/sales/performance                 → Sales performance
GET /api/reports/sales/products                    → Product sales analysis
```

### Dashboards
```
GET /api/dashboard/stats                           → Main dashboard
GET /api/dashboard/sales/stats                     → Sales dashboard
GET /api/dashboard/transport                       → Transport dashboard
GET /api/finance/dashboard                         → Finance dashboard
```

---

## Admin

```
GET /api/admin/users                               → List users
POST /api/admin/users                              → Create user
PATCH /api/admin/users/{id}                        → Update user
```

---

## Key Business Rules

| Rule | Description |
|------|-------------|
| **PI = Items Only** | PI has no GST, no discount. Only `grand_total` = sum of items. |
| **PI Bill = GST + Discount** | PI Bill is where GST and discount are applied. Generated after PI acceptance. |
| **Advance = Always PI** | Advance payments are always against a PI. Currency/conversion_rate auto-inherited from PI. |
| **Multi-Currency** | All amounts in original currency + immutable conversion_rate. P&L always in INR. |
| **PO Number** | `EEL/IND/<VENDOR_PREFIX>/<NUMBER>` starting from 100 |
| **PI Number** | `EEL/IND/PI/{YEAR}/{NUMBER}` starting from 0001 |
| **PI Bill Number** | `PIB/{YEAR}/{NUMBER}` starting from 0001 |
| **Advance Number** | `ADV/{YEAR}/{NUMBER}` starting from 0001 |
| **Revision** | First edit appends "R" to number. `revision_number` increments. |
| **Edit Lock** | 30-minute timeout. Must lock before editing PO/PI. |
| **Password** | Cancel PO, Cancel PI, Cancel PI Bill, Record PO Payment, Mark PI Bill Paid — all require `confirm_password`. |
| **GST** | CGST + SGST (intra-state) OR IGST (inter-state). Applied on items_total/subtotal. |
| **Stock** | Auto-updated when PO item marked as purchased. Reversed on PO cancel. |
| **Transport** | Multiple shipments per PO/PI. Cost allocated proportionally by item value. |
| **Deletion** | Requisitions, Assignments, Quotations, POs, PI Bills, Advance Payments cannot be deleted. |

---

## Status Flows

### Purchase Order
```
PENDING → PARTIALLY_RECEIVED → COMPLETED
    |
    └──→ CANCELLED (stock reversed)
```

### Proforma Invoice
```
DRAFT → SENT → ACCEPTED
  |       |        |
  └───────┴────────┴──→ CANCELLED (password required)
```

### PI Bill
```
GENERATED → PAID
    |
    └──→ CANCELLED
```

### Advance Payment
```
ACTIVE → FULLY_USED
    |
    └──→ REFUNDED
```

---

## All API Endpoints — Module-wise

### 1. AUTH MODULE
> Login, token management, password recovery

| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/auth/login` | POST | User login — returns JWT access (8hr) + refresh token |
| 2 | `/api/auth/refresh` | POST | Refresh expired access token using refresh token |
| 3 | `/api/auth/profile` | GET | Get current logged-in user profile |
| 4 | `/api/auth/forgot-password` | POST | Send OTP to email for password reset |
| 5 | `/api/auth/verify-otp` | POST | Verify OTP received on email |
| 6 | `/api/auth/reset-password` | POST | Reset password using verified OTP |

---

### 2. ADMIN MODULE
> User management, exchange rates (Admin role only)

| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/admin/users` | GET | List all users with their module permissions |
| 2 | `/api/admin/users` | POST | Create new user — auto-sends credentials email |
| 3 | `/api/admin/users/{id}` | PATCH | Update user details, role, permissions |
| 4 | `/api/admin/exchange-rates` | GET | List all exchange rates |
| 5 | `/api/admin/exchange-rates` | POST | Create new exchange rate |
| 6 | `/api/admin/exchange-rates/{id}` | PATCH | Update exchange rate |

**Permission Modules:** `MASTER`, `PURCHASE`, `SALES`, `FINANCE`, `TRANSPORT` — each with `can_read` / `can_write`

---

### 3. MASTER MODULE (Inventory + Vendors + Currency)
> Item master, vendor master, currency master

#### 3a. Products (Item Master)
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/products` | POST | Create new product — `item_code` auto-generated |
| 2 | `/api/products` | GET | List products — filter: `?is_active=true&unit=KG&search=steel` |
| 3 | `/api/products/{id}` | GET | Product detail |
| 4 | `/api/products/{id}` | PATCH | Update product |
| 5 | `/api/products/by_requisition` | GET | Products by requisition number — `?requisition_number=EEL/2026/001` |
| 6 | `/api/products/low_stock` | GET | Low stock items alert |
| 7 | `/api/products/bulk-upload` | POST | Bulk upload products via Excel file |
| 8 | `/api/products/bulk-upload-template` | GET | Download Excel template for bulk upload |

#### 3b. Vendors
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/vendors` | POST | Create new vendor |
| 2 | `/api/vendors` | GET | List all vendors |
| 3 | `/api/vendors/{id}` | GET | Vendor detail |
| 4 | `/api/vendors/{id}` | PATCH | Update vendor |

#### 3c. Currency
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/currencies` | GET | List all currencies (any authenticated user) |
| 2 | `/api/currencies` | POST | Create currency (admin only) |
| 3 | `/api/currencies/{id}` | PATCH | Update currency (admin only) |
| 4 | `/api/currencies/{id}` | DELETE | Delete currency (admin only) |
| 5 | `/api/exchange-rate` | GET | Get current exchange rates |

---

### 4. SALES MODULE (Client Query + Quotation + PI)
> Client queries, sales quotations, proforma invoices

#### 4a. Client Queries (Lead Entry)
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/client-queries` | POST | Create new client query (lead) — supports PDF upload |
| 2 | `/api/client-queries` | GET | List queries — filter: `?status=NEW&search=ABC` |
| 3 | `/api/client-queries/{id}` | GET | Query detail |
| 4 | `/api/client-queries/{id}` | PATCH | Update query |
| 5 | `/api/client-queries/{id}/update_status` | POST | Change query status |
| 6 | `/api/client-queries/{id}/quotations` | GET | All quotations for this query |
| 7 | `/api/client-queries/{id}/download_pdf` | GET | Download uploaded PDF |

#### 4b. Sales Quotations
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/quotations` | POST | Create quotation linked to client query |
| 2 | `/api/quotations` | GET | List quotations — filter: `?client_query=uuid&status=DRAFT` |
| 3 | `/api/quotations/{id}` | GET | Quotation detail |
| 4 | `/api/quotations/{id}` | PUT/PATCH | Update quotation (header + items in one call) |
| 5 | `/api/quotations/{id}/recalculate` | POST | Recalculate totals |
| 6 | `/api/quotations/{id}/update_gst` | POST | Update GST percentages only |
| 7 | `/api/quotations/{id}/update_status` | POST | Change quotation status |
| 8 | `/api/quotations/{id}/items` | GET | List items in quotation |
| 9 | `/api/quotations/{id}/summary` | GET | Full formatted summary with tax breakdown |
| 10 | `/api/quotations/by_status` | GET | Filter by status — `?status=ACCEPTED` |

#### 4c. Quotation Items (Standalone CRUD)
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/quotation-items` | POST | Add item to quotation — auto-recalculates totals |
| 2 | `/api/quotation-items` | GET | List items — filter: `?quotation=uuid` |
| 3 | `/api/quotation-items/{id}` | PATCH | Update item — auto-recalculates totals |
| 4 | `/api/quotation-items/{id}` | DELETE | Remove item — auto-recalculates totals |

#### 4d. Proforma Invoices (PI)
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/proforma-invoices` | POST | Create PI — `grand_total` = items sum, NO GST/discount |
| 2 | `/api/proforma-invoices` | GET | List PIs — filter: `?requisition=uuid&status=DRAFT&currency=USD` |
| 3 | `/api/proforma-invoices/{id}` | GET | PI detail |
| 4 | `/api/proforma-invoices/{id}` | PATCH | Edit PI (requires lock, creates revision) |
| 5 | `/api/proforma-invoices/{id}/lock` | POST | Acquire 30-min edit lock |
| 6 | `/api/proforma-invoices/{id}/unlock` | POST | Release edit lock |
| 7 | `/api/proforma-invoices/{id}/send` | POST | Status: DRAFT → SENT |
| 8 | `/api/proforma-invoices/{id}/accept` | POST | Status: SENT → ACCEPTED |
| 9 | `/api/proforma-invoices/{id}/cancel` | POST | Cancel PI from any status (password required) |
| 10 | `/api/proforma-invoices/requisition_items` | GET | Check purchase status of requisition items — `?requisition=uuid` |

---

### 5. PURCHASE MODULE (Requisitions + Vendor Assignments + POs)
> Requisitions, vendor assignments, vendor quotations, purchase orders

#### 5a. Requisitions
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/requisitions` | POST | Create requisition with items — number auto-generated |
| 2 | `/api/requisitions` | GET | List — filter: `?is_assigned=true&search=EEL` |
| 3 | `/api/requisitions/{id}` | GET | Requisition detail |
| 4 | `/api/requisitions/{id}/items` | GET | Requisition items list |
| 5 | `/api/requisitions/{id}/flow` | GET | Complete flow (Requisition → Assignments → Quotations) |
| 6 | `/api/requisitions/{id}/comparison` | GET | Side-by-side vendor price comparison |
| 7 | `/api/requisitions/{id}/assignments` | GET | Vendor assignments for requisition |

#### 5b. Vendor Assignments
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/vendor-assignments` | POST | Assign vendor to requisition (unique per vendor) |
| 2 | `/api/vendor-assignments` | GET | List assignments |
| 3 | `/api/vendor-assignments/{id}/items_for_quotation` | GET | Items ready for quotation entry |

#### 5c. Vendor Quotations
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/vendor-quotations` | POST | Enter vendor quotation with item rates |
| 2 | `/api/vendor-quotations` | GET | List all quotations |
| 3 | `/api/vendor-quotations/{id}/select` | POST | Select this quotation (deselects others) |
| 4 | `/api/vendor-quotations/by_vendor` | GET | Filter by vendor — `?vendor=uuid` |
| 5 | `/api/vendor-quotations/by_requisition` | GET | Filter by requisition — `?requisition=uuid` |
| 6 | `/api/vendor-quotations/by_requisition_vendor` | GET | Filter by both — `?requisition=uuid&vendor=uuid` |

#### 5d. Purchase Orders
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/purchase-orders/generate_from_comparison` | POST | Generate PO from selected vendor quotations |
| 2 | `/api/purchase-orders` | GET | List POs |
| 3 | `/api/purchase-orders/{id}` | GET | PO detail |
| 4 | `/api/purchase-orders/{id}` | PATCH | Edit PO (requires lock, creates revision) |
| 5 | `/api/purchase-orders/{id}/lock` | POST | Acquire 30-min edit lock |
| 6 | `/api/purchase-orders/{id}/unlock` | POST | Release edit lock |
| 7 | `/api/purchase-orders/{id}/update_gst` | POST | Update GST percentages and recalculate |
| 8 | `/api/purchase-orders/{id}/mark_item_purchased` | POST | Mark single item as received — updates stock |
| 9 | `/api/purchase-orders/{id}/mark_all_purchased` | POST | Mark all items as received — updates stock |
| 10 | `/api/purchase-orders/{id}/cancel` | POST | Cancel PO — reverses stock (password required) |

---

### 6. BILLING MODULE (PI Bills)
> Bill generation from PI, GST + discount, partial payments

| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/pi-bills` | POST | Create PI Bill — GST & discount applied, currency from PI |
| 2 | `/api/pi-bills` | GET | List bills — filter: `?status=GENERATED&bill_type=DOMESTIC&search=PIB` |
| 3 | `/api/pi-bills/{id}` | GET | Bill detail with items |
| 4 | `/api/pi-bills/{id}` | PATCH | Update bill |
| 5 | `/api/pi-bills/{id}/mark_paid` | POST | Record partial/full payment (password required) |
| 6 | `/api/pi-bills/{id}/payment_history` | GET | All payment records with running totals |
| 7 | `/api/pi-bills/{id}/cancel` | POST | Cancel bill (password required, cannot cancel PAID) |
| 8 | `/api/pi-bills/by_pi` | GET | Bills by PI — `?proforma_invoice=uuid` |
| 9 | `/api/pi-bills/pending_payment` | GET | All bills with outstanding balance |

---

### 7. FINANCE MODULE
> Vendor payments, client payments, advance payments, P&L, analytics

#### 7a. PO Finance (Outgoing — Payments to Vendors)
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/finance/purchase-orders` | GET | List POs with finance summary (paid, balance) |
| 2 | `/api/finance/purchase-orders/{id}` | GET | PO finance detail — purchased vs pending items |
| 3 | `/api/finance/purchase-orders/{id}/record_payment` | POST | Record vendor payment (password required) |
| 4 | `/api/finance/purchase-orders/{id}/payment_history` | GET | PO payment history — all installments |
| 5 | `/api/finance/purchase-orders/{id}/purchased_items` | GET | Items received for this PO |
| 6 | `/api/finance/purchase-orders/pending_payments` | GET | POs with outstanding balance |
| 7 | `/api/finance/purchase-orders/overdue` | GET | POs past payment due date |

#### 7b. PI Finance (Incoming — Payments from Clients)
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/finance/proforma-invoices` | GET | List PIs with finance summary |
| 2 | `/api/finance/proforma-invoices/{id}` | GET | PI finance detail |
| 3 | `/api/finance/proforma-invoices/{id}/record_payment` | POST | Record client payment (password required) |
| 4 | `/api/finance/proforma-invoices/{id}/payment_history` | GET | PI payment history — all installments |
| 5 | `/api/finance/proforma-invoices/pending_payments` | GET | PIs with outstanding balance |
| 6 | `/api/finance/proforma-invoices/overdue` | GET | PIs past payment due date |

#### 7c. Advance Payments (Client Advances against PI)
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/finance/advance-payments` | POST | Create advance — currency/rate auto-inherited from PI |
| 2 | `/api/finance/advance-payments` | GET | List — filter: `?status=ACTIVE&proforma_invoice=uuid&currency=USD` |
| 3 | `/api/finance/advance-payments/{id}` | GET | Advance detail |
| 4 | `/api/finance/advance-payments/{id}` | PATCH | Update advance |
| 5 | `/api/finance/advance-payments/{id}/adjust` | POST | Use (deduct) advance amount against PI |

#### 7d. Payment Lists (Flat views across all POs/PIs)
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/finance/all-purchase-payments` | GET | All vendor payments across all POs |
| 2 | `/api/finance/all-pi-payments` | GET | All client payments across all PIs |

#### 7e. Profit & Loss (All in INR)
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/finance/profit-loss` | GET | P&L per requisition — `?requisition=uuid` |
| 2 | `/api/finance/profit-loss/items` | GET | P&L per item with transport allocation |
| 3 | `/api/finance/profit-preview` | POST | Real-time profit check during PI creation |

#### 7f. Item Analytics
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/finance/items/analytics` | GET | Per-item purchase/sale stats |
| 2 | `/api/finance/items/insights` | GET | Most/least sold, most profitable items |
| 3 | `/api/finance/items/aging` | GET | Slow-moving & dead stock — `?threshold_days=90` |

#### 7g. Due Dates, Reconciliation & Validation
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/finance/due-dates` | GET | Upcoming & overdue payments — `?upcoming_days=7` |
| 2 | `/api/finance/reconciliation` | GET | Detect overpayment, duplicates, missing transport |
| 3 | `/api/finance/validation` | GET | Purchased-unpaid, paid-not-purchased, anomalies |

#### 7h. Finance Dashboard
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/finance/dashboard` | GET | Outgoing/incoming totals, P&L, cash flow, advances, recent transactions |

---

### 8. TRANSPORT MODULE
> Shipment tracking, cost items, landed cost calculation

| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/transport` | POST | Create transport entry with cost items |
| 2 | `/api/transport` | GET | List entries — filter: `?purchase_order=uuid&status=IN_TRANSIT` |
| 3 | `/api/transport/{id}` | GET | Transport detail with cost breakdown |
| 4 | `/api/transport/{id}` | PATCH | Update transport entry |
| 5 | `/api/transport/{id}/mark_delivered` | POST | Mark as delivered — sets actual delivery date |
| 6 | `/api/transport/by_po` | GET | Entries by PO — `?purchase_order=uuid` |
| 7 | `/api/transport/by_pi` | GET | Entries by PI — `?proforma_invoice=uuid` |
| 8 | `/api/transport/landed_cost` | GET | Landed cost per item (PO) — `?purchase_order=uuid` |
| 9 | `/api/transport/landed_cost_pi` | GET | Landed cost per item (PI) — `?proforma_invoice=uuid` |

---

### 9. REPORTS MODULE
> All reports across modules (read-only, any authenticated user)

#### 9a. Requisition Reports
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/reports/requisitions` | GET | Requisition summary report |
| 2 | `/api/reports/requisitions/{id}/detailed` | GET | Detailed requisition report |

#### 9b. Vendor Reports
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/reports/vendors/performance` | GET | Vendor performance metrics |
| 2 | `/api/reports/vendors/quotation-comparison` | GET | Cross-vendor quotation comparison |

#### 9c. Purchase Order Reports
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/reports/purchase-orders` | GET | PO summary report |

#### 9d. Inventory Reports
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/reports/inventory/stock` | GET | Current stock report |
| 2 | `/api/reports/inventory/movement` | GET | Stock movement report |

#### 9e. Financial Reports
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/reports/financial/spending` | GET | Spending analysis report |

#### 9f. Sales Reports
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/reports/sales/client-queries` | GET | Client query report |
| 2 | `/api/reports/sales/client-queries/{id}/detailed` | GET | Detailed client query report |
| 3 | `/api/reports/sales/quotations` | GET | Quotation report |
| 4 | `/api/reports/sales/quotation-items` | GET | Quotation items report |
| 5 | `/api/reports/sales/analytics` | GET | Sales analytics |
| 6 | `/api/reports/sales/performance` | GET | Sales performance |
| 7 | `/api/reports/sales/products` | GET | Product sales analysis |

#### 9g. Transport Reports
| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/reports/transport/by-po` | GET | Transport cost by PO |
| 2 | `/api/reports/transport/by-vendor` | GET | Transport cost by vendor |
| 3 | `/api/reports/transport/cost-breakdown` | GET | Cost breakdown by type |
| 4 | `/api/reports/transport/landed-cost` | GET | Item-wise landed cost |

---

### 10. DASHBOARDS
> Overview stats for each module

| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/dashboard/stats` | GET | Main dashboard — requisitions, POs, inventory overview |
| 2 | `/api/dashboard/sales/stats` | GET | Sales dashboard — queries, quotations, PI stats |
| 3 | `/api/dashboard/transport` | GET | Transport dashboard — shipment stats, cost breakdown |
| 4 | `/api/finance/dashboard` | GET | Finance dashboard — cash flow, P&L, due dates |

---

### 11. AUDIT LOGS
> Activity tracking across all modules

| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/audit-logs` | GET | List all logs — filter: `?model_name=PurchaseOrder&action=CREATE&user=uuid` |
| 2 | `/api/audit-logs/{model_name}/{object_id}` | GET | History for a specific object |

**Logged actions:** CREATE, UPDATE, DELETE, STATUS_CHANGE
**Covered modules:** PO, PI, PI Bill, Transport, PO Payment, PI Payment, Advance Payment

---

### 12. API DOCS
> Auto-generated API documentation

| # | Endpoint | Method | Functionality |
|---|----------|--------|---------------|
| 1 | `/api/docs` | GET | Swagger UI — interactive API explorer |
| 2 | `/api/playground` | GET | Redoc — formatted API reference |
| 3 | `/api/schema/` | GET | OpenAPI 3.0 JSON schema |



