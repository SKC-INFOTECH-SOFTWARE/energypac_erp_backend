# EnergyPac ERP — Complete API Documentation

> **Base URL:** `http://localhost:8000`
> **Auth:** All endpoints require `Authorization: Bearer <token>` header unless noted.
> **⚠ icon** = requires `confirm_password` in body

---

## 1. AUTH (`/api/auth/`)

### 1.1 Login (No auth required)
```
POST /api/auth/login
```
**Payload:**
```json
{
    "employee_code": "EMP001",
    "password": "your_password"
}
```
**Response (200):**
```json
{
    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOi...",
    "access": "eyJ0eXAiOiJKV1QiLCJhbGciOi...",
    "user": {
        "id": "a1b2c3d4-...",
        "username": "admin",
        "employee_code": "EMP001",
        "email": "admin@example.com",
        "first_name": "John",
        "last_name": "Doe",
        "full_name": "John Doe",
        "phone": "9876543210",
        "department": "Procurement",
        "created_at": "2026-01-01T00:00:00Z"
    }
}
```

### 1.2 Refresh Token
```
POST /api/auth/refresh
```
**Payload:**
```json
{ "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOi..." }
```
**Response (200):**
```json
{
    "access": "eyJ0eXAiOiJKV1QiLCJhbGciOi...",
    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOi..."
}
```

### 1.3 Get Profile
```
GET /api/auth/profile
```
**Response (200):**
```json
{
    "id": "a1b2c3d4-...",
    "username": "admin",
    "employee_code": "EMP001",
    "email": "admin@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "full_name": "John Doe",
    "phone": "9876543210",
    "department": "Procurement",
    "created_at": "2026-01-01T00:00:00Z"
}
```

---

## 2. INVENTORY (`/api/products`)

### 2.1 List Products
```
GET /api/products
```
**Filters:** `?is_active=true&unit=PCS&search=steel&ordering=-current_stock`
**Response (200):**
```json
{
    "count": 50,
    "next": "http://localhost:8000/api/products?page=2",
    "previous": null,
    "results": [
        {
            "id": "uuid-...",
            "item_code": "ITEM/0001",
            "item_name": "Steel Rod 12mm",
            "description": "High quality steel rod",
            "hsn_code": "7214",
            "unit": "KG",
            "current_stock": 500.00,
            "reorder_level": 100.00,
            "rate": 85.00,
            "is_active": true,
            "created_at": "2026-01-15T10:00:00Z",
            "updated_at": "2026-03-01T14:30:00Z"
        }
    ]
}
```

### 2.2 Create Product
```
POST /api/products
```
**Payload:**
```json
{
    "item_name": "Copper Wire 2.5mm",
    "description": "Electrical grade copper wire",
    "hsn_code": "7408",
    "unit": "MTR",
    "current_stock": 1000.00,
    "reorder_level": 200.00,
    "rate": 45.50,
    "is_active": true
}
```
**Response (201):** Same as single product object with auto-generated `item_code`.

### 2.3 Retrieve / Update / Delete
```
GET    /api/products/{id}
PUT    /api/products/{id}     — full update (same payload as create)
PATCH  /api/products/{id}     — partial update (any subset of fields)
DELETE /api/products/{id}  ⚠  — { "confirm_password": "your_password" }
```

### 2.4 Low Stock Products
```
GET /api/products/low_stock
```
**Response (200):** Array of products where `current_stock <= reorder_level`

### 2.5 Active Products
```
GET /api/products/active
```
**Response (200):** Array of active products only

---

## 3. VENDORS (`/api/vendors`)

### 3.1 List / Create / Retrieve / Update / Delete
```
GET    /api/vendors                — list (filters: ?is_active=true&search=abc)
POST   /api/vendors               — create
GET    /api/vendors/{id}           — retrieve
PUT    /api/vendors/{id}           — full update
PATCH  /api/vendors/{id}           — partial update
DELETE /api/vendors/{id}  ⚠        — requires confirm_password
```

**Create Payload:**
```json
{
    "vendor_code": "VEN/0001",
    "vendor_name": "ABC Suppliers Pvt Ltd",
    "contact_person": "Rajesh Kumar",
    "phone": "9876543210",
    "email": "rajesh@abcsuppliers.com",
    "address": "123, Industrial Area, Mumbai",
    "gst_number": "27AABCU9603R1ZM",
    "pan_number": "AABCU9603R",
    "bank_name": "State Bank of India",
    "account_name": "ABC Suppliers Pvt Ltd",
    "bank_account_number": "123456789012",
    "ifsc_code": "SBIN0001234",
    "swift_code": "SBININBB",
    "is_active": true
}
```
**Response (201):**
```json
{
    "id": "uuid-...",
    "vendor_code": "VEN/0001",
    "vendor_name": "ABC Suppliers Pvt Ltd",
    "contact_person": "Rajesh Kumar",
    "phone": "9876543210",
    "email": "rajesh@abcsuppliers.com",
    "address": "123, Industrial Area, Mumbai",
    "gst_number": "27AABCU9603R1ZM",
    "pan_number": "AABCU9603R",
    "bank_name": "State Bank of India",
    "account_name": "ABC Suppliers Pvt Ltd",
    "bank_account_number": "123456789012",
    "ifsc_code": "SBIN0001234",
    "swift_code": "SBININBB",
    "is_active": true,
    "created_at": "2026-03-13T12:00:00Z",
    "updated_at": "2026-03-13T12:00:00Z"
}
```

### 3.2 Active Vendors
```
GET /api/vendors/active
```

---

## 4. REQUISITIONS (`/api/requisitions`)

### 4.1 List / Create / Retrieve / Update
```
GET   /api/requisitions              — list (filters: ?is_assigned=false&search=EEL)
POST  /api/requisitions              — create with items
GET   /api/requisitions/{id}         — retrieve
PATCH /api/requisitions/{id}         — update
```

**Create Payload:**
```json
{
    "requisition_date": "2026-03-13",
    "remarks": "Urgent requirement for project X",
    "items": [
        { "product": "product-uuid-1", "quantity": 100, "remarks": "For building A" },
        { "product": "product-uuid-2", "quantity": 50, "remarks": "" }
    ]
}
```
**Response (201):** Full requisition object with auto-generated `requisition_number` (e.g., `EEL/2026/001`)

### 4.2 Get Requisition Items
```
GET /api/requisitions/{id}/items
```
**Response (200):**
```json
{
    "requisition_number": "EEL/2026/001",
    "total_items": 2,
    "items": [
        {
            "id": "uuid-...",
            "product": "product-uuid",
            "product_name": "Steel Rod 12mm",
            "product_code": "ITEM/0001",
            "quantity": 100.00,
            "remarks": "For building A"
        }
    ]
}
```

### 4.3 Get Vendor Assignments
```
GET /api/requisitions/{id}/assignments
```

### 4.4 Full Flow (Requisition → Vendors → Quotations)
```
GET /api/requisitions/{id}/flow
```

### 4.5 Comparison (Compare All Vendor Quotations)
```
GET /api/requisitions/{id}/comparison
```
**Response (200):**
```json
{
    "requisition_number": "EEL/2026/001",
    "requisition_date": "2026-03-13",
    "vendors": [
        {
            "vendor_id": "uuid-...",
            "vendor_name": "ABC Suppliers",
            "vendor_code": "VEN/0001",
            "quotations": [
                {
                    "quotation_number": "VQ/2026/0001",
                    "quotation_date": "2026-03-14",
                    "total_amount": 125000.00,
                    "is_selected": false,
                    "items": [
                        {
                            "id": "quotation-item-uuid",
                            "product_code": "ITEM/0001",
                            "product_name": "Steel Rod 12mm",
                            "quantity": 100.00,
                            "unit": "KG",
                            "quoted_rate": 85.00,
                            "amount": 8500.00
                        }
                    ]
                }
            ]
        }
    ]
}
```

---

## 5. VENDOR ASSIGNMENTS (`/api/vendor-assignments`)

### 5.1 Create Assignment
```
POST /api/vendor-assignments
```
**Payload:**
```json
{
    "requisition": "requisition-uuid",
    "vendor": "vendor-uuid",
    "remarks": "Primary supplier for steel",
    "items": [
        { "requisition_item": "req-item-uuid-1", "product": "product-uuid-1", "quantity": 100 },
        { "requisition_item": "req-item-uuid-2", "product": "product-uuid-2", "quantity": 50 }
    ]
}
```

### 5.2 Get Items for Quotation Entry
```
GET /api/vendor-assignments/{id}/items_for_quotation
```

---

## 6. VENDOR QUOTATIONS (`/api/vendor-quotations`)

### 6.1 Create Quotation
```
POST /api/vendor-quotations
```
**Payload:**
```json
{
    "assignment": "assignment-uuid",
    "reference_number": "VQ-REF-2026-001",
    "validity_date": "2026-04-15",
    "payment_terms": "30 days net",
    "delivery_terms": "Ex-works",
    "remarks": "",
    "items": [
        { "vendor_item": "vendor-item-uuid", "product": "product-uuid", "quantity": 100, "quoted_rate": 85.00 }
    ]
}
```

### 6.2 Select Quotation
```
POST /api/vendor-quotations/{id}/select
```
**Response (200):** Updated quotation with `is_selected: true`

### 6.3 Filter by Vendor / Requisition
```
GET /api/vendor-quotations/by_vendor?vendor={vendor_id}
GET /api/vendor-quotations/by_requisition?requisition={req_id}
GET /api/vendor-quotations/by_requisition_vendor?requisition={req_id}&vendor={vendor_id}
```

---

## 7. PURCHASE ORDERS (`/api/purchase-orders`)

### 7.1 Generate PO from Comparison
```
POST /api/purchase-orders/generate_from_comparison
```
**Payload:**
```json
{
    "requisition": "requisition-uuid",
    "po_date": "2026-03-15",
    "selections": ["quotation-item-uuid-1", "quotation-item-uuid-2"],
    "remarks": "As per comparison approval"
}
```
**Response (201):**
```json
{
    "message": "1 Purchase Order(s) created",
    "purchase_orders": [
        {
            "id": "uuid-...",
            "po_number": "PO/2026/0001",
            "requisition": "req-uuid",
            "requisition_number": "EEL/2026/001",
            "vendor": "vendor-uuid",
            "vendor_name": "ABC Suppliers",
            "po_date": "2026-03-15",
            "items_total": 8500.00,
            "freight_cost": 0.00,
            "total_amount": 8500.00,
            "amount_paid": 0.00,
            "balance": 8500.00,
            "status": "PENDING",
            "items": [
                {
                    "id": "item-uuid",
                    "product": "product-uuid",
                    "product_name": "Steel Rod 12mm",
                    "product_code": "ITEM/0001",
                    "hsn_code": "7214",
                    "unit": "KG",
                    "quantity": 100.00,
                    "rate": 85.00,
                    "amount": 8500.00,
                    "is_received": false
                }
            ]
        }
    ]
}
```

### 7.2 Mark Single Item Purchased
```
POST /api/purchase-orders/{id}/mark_item_purchased
```
**Payload:**
```json
{ "item_id": "po-item-uuid" }
```
**Response (200):**
```json
{
    "message": "Item marked as received",
    "product": "Steel Rod 12mm",
    "quantity": 100.00,
    "new_stock": 600.00,
    "po_status": "COMPLETED"
}
```

### 7.3 Mark All Purchased
```
POST /api/purchase-orders/{id}/mark_all_purchased
```
**Response (200):**
```json
{ "message": "All items marked as received", "po_status": "COMPLETED" }
```

### 7.4 Cancel PO ⚠
```
POST /api/purchase-orders/{id}/cancel
```
**Payload:**
```json
{ "confirm_password": "your_password", "reason": "Vendor could not supply" }
```
**Response (200):**
```json
{
    "message": "Purchase order cancelled successfully",
    "po_number": "PO/2026/0001",
    "status": "CANCELLED",
    "cancelled_by": "John Doe",
    "cancelled_at": "2026-03-13T12:00:00Z",
    "reason": "Vendor could not supply",
    "stock_reversed": [
        { "item_id": "uuid", "product_code": "ITEM/0001", "product_name": "Steel Rod 12mm", "quantity": 100.0 }
    ],
    "purchase_order": { "...full PO object..." }
}
```

---

## 8. SALES

### 8.1 Client Queries (`/api/client-queries`)
```
GET    /api/client-queries               — list (filters: ?status=PENDING&search=client)
POST   /api/client-queries               — create (supports multipart with PDF)
GET    /api/client-queries/{id}
PATCH  /api/client-queries/{id}
```
**Create Payload (multipart/form-data):**
```
client_name: "XYZ Corp"
contact_person: "Anil"
phone: "9876543210"
email: "anil@xyz.com"
address: "456, Tech Park"
query_date: "2026-03-10"
remarks: "Need 500 transformers"
pdf_file: <file upload>
```
**Custom Actions:**
```
GET  /api/client-queries/{id}/download_pdf
GET  /api/client-queries/{id}/quotations
POST /api/client-queries/{id}/update_status   — { "status": "QUOTATION_SENT" }
```

### 8.2 Sales Quotations (`/api/quotations`)
```
GET    /api/quotations               — list
POST   /api/quotations               — create
GET    /api/quotations/{id}
PUT    /api/quotations/{id}          — full update with items
PATCH  /api/quotations/{id}          — partial update
```
**Create Payload:**
```json
{
    "client_query": "query-uuid",
    "quotation_date": "2026-03-11",
    "validity_date": "2026-04-11",
    "payment_terms": "50% advance, 50% on delivery",
    "delivery_terms": "FOB Mumbai",
    "cgst_percentage": 9.00,
    "sgst_percentage": 9.00,
    "igst_percentage": 0.00,
    "remarks": "",
    "items": [
        {
            "product": "product-uuid",
            "quantity": 100,
            "rate": 1500.00,
            "remarks": ""
        },
        {
            "item_code": "CUSTOM01",
            "item_name": "Custom Transformer",
            "hsn_code": "8504",
            "unit": "PCS",
            "quantity": 5,
            "rate": 25000.00
        }
    ]
}
```
**Response (201):**
```json
{
    "id": "uuid-...",
    "quotation_number": "SQ/2026/0001",
    "client_query": "query-uuid",
    "quotation_date": "2026-03-11",
    "subtotal": 275000.00,
    "cgst_percentage": 9.00,
    "sgst_percentage": 9.00,
    "cgst_amount": 24750.00,
    "sgst_amount": 24750.00,
    "igst_amount": 0.00,
    "total_amount": 324500.00,
    "status": "DRAFT",
    "items": ["..."]
}
```
**Custom Actions:**
```
POST /api/quotations/{id}/recalculate
POST /api/quotations/{id}/update_gst     — { "cgst_percentage": 9, "sgst_percentage": 9 }
POST /api/quotations/{id}/update_status  — { "status": "SENT" }
GET  /api/quotations/{id}/items
GET  /api/quotations/{id}/summary
GET  /api/quotations/by_status?status=DRAFT
```

---

## 9. WORK ORDERS (`/api/work-orders`)

### 9.1 Create Work Order
```
POST /api/work-orders
```
**Payload:**
```json
{
    "sales_quotation": "quotation-uuid",
    "wo_date": "2026-03-12",
    "wo_number": "",
    "advance_amount": 50000.00,
    "remarks": "Priority order",
    "items": [
        {
            "quotation_item": "sq-item-uuid",
            "ordered_quantity": 100,
            "rate": 1500.00,
            "remarks": ""
        }
    ]
}
```
**Custom Actions:**
```
GET  /api/work-orders/{id}/items_for_billing
GET  /api/work-orders/{id}/stock_availability
GET  /api/work-orders/{id}/financial_summary
GET  /api/work-orders/{id}/delivery_summary
POST /api/work-orders/{id}/update_advance    — { "advance_amount": 75000 }
GET  /api/work-orders/by_quotation?quotation={sq_id}
GET  /api/work-orders/active
```

**Financial Summary Response (200):**
```json
{
    "total_amount": 324500.00,
    "advance_amount": 50000.00,
    "advance_deducted": 10000.00,
    "advance_remaining": 40000.00,
    "total_delivered_value": 150000.00,
    "total_pending_value": 174500.00
}
```

**Delivery Summary Response (200):**
```json
{
    "total_items": 5,
    "fully_delivered_items": 2,
    "partially_delivered_items": 1,
    "pending_items": 2,
    "completion_percentage": 45.50
}
```

---

## 10. BILLING (`/api/bills`)

### 10.1 Create Bill
```
POST /api/bills
```
**Payload:**
```json
{
    "work_order": "wo-uuid",
    "bill_date": "2026-03-13",
    "bill_type": "DOMESTIC",
    "freight_cost": 2500.00,
    "remarks": "First delivery",
    "items": [
        {
            "work_order_item": "wo-item-uuid",
            "delivered_quantity": 50,
            "remarks": ""
        }
    ]
}
```
**Response (201):**
```json
{
    "id": "uuid-...",
    "bill_number": "BILL/2026/0001",
    "bill_type": "DOMESTIC",
    "wo_number": "WO/2026/0001",
    "bill_date": "2026-03-13",
    "client_name": "XYZ Corp",
    "subtotal": 75000.00,
    "cgst_percentage": 9.00,
    "sgst_percentage": 9.00,
    "cgst_amount": 6750.00,
    "sgst_amount": 6750.00,
    "igst_amount": 0.00,
    "total_amount": 88500.00,
    "freight_cost": 2500.00,
    "advance_deducted": 40000.00,
    "net_payable": 51000.00,
    "amount_paid": 0.00,
    "balance": 51000.00,
    "status": "GENERATED",
    "items": ["..."],
    "payments": []
}
```

### 10.2 Mark Paid ⚠ (legacy — use finance endpoint instead)
```
POST /api/bills/{id}/mark_paid
```
**Payload:**
```json
{
    "confirm_password": "your_password",
    "amount_paid": 25000.00,
    "payment_date": "2026-03-15",
    "payment_mode": "NEFT",
    "reference_number": "UTR123456",
    "remarks": "First instalment"
}
```

### 10.3 Other Bill Endpoints
```
GET  /api/bills/{id}/payment_history
GET  /api/bills/{id}/detailed_summary
POST /api/bills/{id}/cancel  ⚠     — { "confirm_password": "pwd", "reason": "Duplicate" }
GET  /api/bills/by_work_order?work_order={wo_id}
GET  /api/bills/pending_payment
POST /api/bills/validate_stock     — { "work_order": "uuid", "items": [...] }
```

---

## 11. FINANCE (`/api/finance/`) — NEW

### 11.1 List Purchase Orders (Finance View)
```
GET /api/finance/purchase-orders
```
**Filters:** `?vendor={id}&status=PENDING&search=PO/2026&ordering=-balance`
**Response (200):**
```json
{
    "count": 10,
    "results": [
        {
            "id": "uuid-...",
            "po_number": "PO/2026/0001",
            "vendor_name": "ABC Suppliers",
            "vendor_phone": "9876543210",
            "vendor_email": "info@abc.com",
            "vendor_gst": "27AABCU9603R1ZM",
            "po_date": "2026-03-15",
            "items_total": 85000.00,
            "freight_cost": 2000.00,
            "total_amount": 87000.00,
            "amount_paid": 30000.00,
            "balance": 57000.00,
            "purchased_items_total": 85000.00,
            "purchased_items_count": 3,
            "total_items_count": 3,
            "status": "COMPLETED",
            "payment_count": 1,
            "items": [
                {
                    "id": "item-uuid",
                    "product_name": "Steel Rod 12mm",
                    "product_code": "ITEM/0001",
                    "hsn_code": "7214",
                    "unit": "KG",
                    "quantity": 100.00,
                    "rate": 85.00,
                    "amount": 8500.00,
                    "is_received": true
                }
            ]
        }
    ]
}
```

### 11.2 Purchased Items Detail
```
GET /api/finance/purchase-orders/{id}/purchased_items
```
**Response (200):**
```json
{
    "po_number": "PO/2026/0001",
    "vendor_name": "ABC Suppliers",
    "po_date": "2026-03-15",
    "po_status": "COMPLETED",
    "items_total": 85000.00,
    "freight_cost": 2000.00,
    "total_amount": 87000.00,
    "purchased_items_total": 85000.00,
    "purchased_items_count": 3,
    "pending_items_count": 0,
    "amount_paid": 30000.00,
    "balance": 57000.00,
    "purchased_items": [
        {
            "item_id": "uuid-...",
            "product_code": "ITEM/0001",
            "product_name": "Steel Rod 12mm",
            "hsn_code": "7214",
            "unit": "KG",
            "quantity": 100.00,
            "rate": 85.00,
            "amount": 8500.00
        }
    ],
    "pending_items": []
}
```

### 11.3 Record Outgoing Payment ⚠
```
POST /api/finance/purchase-orders/{id}/record_payment
```
**Payload:**
```json
{
    "confirm_password": "your_password",
    "amount": 50000.00,
    "payment_date": "2026-03-15",
    "payment_mode": "NEFT",
    "reference_number": "UTR9876543210",
    "remarks": "First instalment to vendor"
}
```
**Payment modes:** `CASH` | `CHEQUE` | `NEFT` | `RTGS` | `IMPS` | `UPI` | `OTHER`

**Response (200):**
```json
{
    "message": "Payment recorded successfully",
    "payment_number": 1,
    "payment_this_transaction": 50000.00,
    "total_paid": 50000.00,
    "total_amount": 87000.00,
    "balance": 37000.00,
    "payment": {
        "id": "payment-uuid",
        "purchase_order": "po-uuid",
        "po_number": "PO/2026/0001",
        "vendor_name": "ABC Suppliers",
        "payment_number": 1,
        "amount": 50000.00,
        "payment_date": "2026-03-15",
        "payment_mode": "NEFT",
        "payment_mode_display": "NEFT",
        "reference_number": "UTR9876543210",
        "remarks": "First instalment to vendor",
        "payment_status": "COMPLETED",
        "total_paid_after": 50000.00,
        "balance_after": 37000.00,
        "recorded_by": "user-uuid",
        "recorded_by_name": "John Doe",
        "created_at": "2026-03-15T10:30:00Z"
    },
    "purchase_order": { "...full PO finance summary..." }
}
```

### 11.4 PO Payment History
```
GET /api/finance/purchase-orders/{id}/payment_history
```
**Response (200):**
```json
{
    "po_number": "PO/2026/0001",
    "vendor_name": "ABC Suppliers",
    "po_date": "2026-03-15",
    "total_amount": 87000.00,
    "total_paid": 80000.00,
    "balance": 7000.00,
    "status": "COMPLETED",
    "payment_count": 2,
    "payments": [
        {
            "id": "uuid-1",
            "po_number": "PO/2026/0001",
            "vendor_name": "ABC Suppliers",
            "payment_number": 1,
            "amount": 50000.00,
            "payment_date": "2026-03-15",
            "payment_mode": "NEFT",
            "payment_mode_display": "NEFT",
            "reference_number": "UTR9876543210",
            "total_paid_after": 50000.00,
            "balance_after": 37000.00,
            "recorded_by_name": "John Doe",
            "created_at": "2026-03-15T10:30:00Z"
        },
        {
            "id": "uuid-2",
            "payment_number": 2,
            "amount": 30000.00,
            "payment_date": "2026-03-20",
            "payment_mode": "RTGS",
            "reference_number": "RTG5551234",
            "total_paid_after": 80000.00,
            "balance_after": 7000.00,
            "recorded_by_name": "John Doe",
            "created_at": "2026-03-20T11:00:00Z"
        }
    ]
}
```

### 11.5 POs with Pending Payments
```
GET /api/finance/purchase-orders/pending_payments
```
**Response (200):**
```json
{
    "total_pending_pos": 5,
    "total_outstanding": 350000.00,
    "purchase_orders": [ "...array of PO finance summaries..." ]
}
```

### 11.6 List Bills (Finance View)
```
GET /api/finance/bills
```
**Filters:** `?status=GENERATED&bill_type=DOMESTIC&search=BILL/2026&ordering=-balance`

### 11.7 Record Incoming Payment ⚠
```
POST /api/finance/bills/{id}/record_payment
```
**Payload:**
```json
{
    "confirm_password": "your_password",
    "amount": 25000.00,
    "payment_date": "2026-03-16",
    "payment_mode": "NEFT",
    "reference_number": "UTR1111222233",
    "remarks": "March instalment from client"
}
```
**Response (200):**
```json
{
    "message": "Payment recorded successfully",
    "payment_number": 1,
    "payment_this_transaction": 25000.00,
    "total_paid": 25000.00,
    "net_payable": 51000.00,
    "balance": 26000.00,
    "status": "GENERATED",
    "payment": {
        "id": "payment-uuid",
        "bill": "bill-uuid",
        "bill_number": "BILL/2026/0001",
        "client_name": "XYZ Corp",
        "wo_number": "WO/2026/0001",
        "payment_number": 1,
        "amount": 25000.00,
        "payment_date": "2026-03-16",
        "payment_mode": "NEFT",
        "payment_mode_display": "NEFT",
        "reference_number": "UTR1111222233",
        "payment_status": "COMPLETED",
        "total_paid_after": 25000.00,
        "balance_after": 26000.00,
        "recorded_by_name": "John Doe",
        "created_at": "2026-03-16T14:00:00Z"
    },
    "bill": { "...full bill finance summary..." }
}
```

### 11.8 Bill Payment History
```
GET /api/finance/bills/{id}/payment_history
```
**Response (200):**
```json
{
    "bill_number": "BILL/2026/0001",
    "bill_type": "DOMESTIC",
    "client_name": "XYZ Corp",
    "wo_number": "WO/2026/0001",
    "bill_date": "2026-03-13",
    "net_payable": 51000.00,
    "total_paid": 51000.00,
    "balance": 0.00,
    "status": "PAID",
    "payment_count": 2,
    "payments": [ "...array of incoming payment objects..." ]
}
```

### 11.9 Bill Detailed Summary
```
GET /api/finance/bills/{id}/detailed_summary
```
**Response (200):**
```json
{
    "bill_number": "BILL/2026/0001",
    "bill_date": "2026-03-13",
    "bill_type": "DOMESTIC",
    "wo_number": "WO/2026/0001",
    "client_details": {
        "name": "XYZ Corp",
        "contact_person": "Anil",
        "phone": "9876543210",
        "email": "anil@xyz.com",
        "address": "456, Tech Park"
    },
    "items": [
        {
            "item_code": "ITEM/0001",
            "item_name": "Steel Rod 12mm",
            "hsn_code": "7214",
            "ordered_quantity": 100.00,
            "previously_delivered": 0.00,
            "delivered_now": 50.00,
            "pending_after": 50.00,
            "unit": "KG",
            "rate": 1500.00,
            "amount": 75000.00
        }
    ],
    "financial": {
        "subtotal": 75000.00,
        "cgst": { "percentage": 9.00, "amount": 6750.00 },
        "sgst": { "percentage": 9.00, "amount": 6750.00 },
        "igst": { "percentage": 0.00, "amount": 0.00 },
        "total_gst": 13500.00,
        "total_amount": 88500.00,
        "freight_cost": 2500.00,
        "advance_deducted": 40000.00,
        "net_payable": 51000.00,
        "amount_paid": 51000.00,
        "balance": 0.00
    },
    "payment_summary": {
        "payment_count": 2,
        "total_paid": 51000.00,
        "balance": 0.00,
        "status": "PAID"
    },
    "payment_history": [ "...array of payment objects..." ],
    "status": "PAID",
    "remarks": "First delivery"
}
```

### 11.10 Bills with Pending Payments
```
GET /api/finance/bills/pending_payments
```
**Response (200):**
```json
{
    "total_pending_bills": 3,
    "total_outstanding": 180000.00,
    "bills": [ "...array of bill finance summaries..." ]
}
```

### 11.11 All Purchase Payments (Flat List)
```
GET /api/finance/all-purchase-payments
```
**Filters:** `?payment_mode=NEFT&payment_status=COMPLETED&purchase_order={po_id}&search=UTR&ordering=-payment_date`
**Response (200):**
```json
{
    "count": 25,
    "results": [
        {
            "id": "uuid-...",
            "purchase_order": "po-uuid",
            "po_number": "PO/2026/0001",
            "vendor_name": "ABC Suppliers",
            "payment_number": 1,
            "amount": 50000.00,
            "payment_date": "2026-03-15",
            "payment_mode": "NEFT",
            "payment_mode_display": "NEFT",
            "reference_number": "UTR9876543210",
            "remarks": "First instalment",
            "payment_status": "COMPLETED",
            "total_paid_after": 50000.00,
            "balance_after": 37000.00,
            "recorded_by": "user-uuid",
            "recorded_by_name": "John Doe",
            "created_at": "2026-03-15T10:30:00Z"
        }
    ]
}
```

### 11.12 All Incoming Payments (Flat List)
```
GET /api/finance/all-incoming-payments
```
**Filters:** `?payment_mode=CASH&bill={bill_id}&search=BILL&ordering=-amount`
**Response (200):** Same structure as above but with [bill](file:///e:/energypac_dev/work_orders/views.py#57-98), `bill_number`, `client_name`, `wo_number` fields.

### 11.13 Finance Dashboard
```
GET /api/finance/dashboard
```
**Response (200):**
```json
{
    "outgoing": {
        "label": "Payments to Vendors",
        "total_value": 500000.00,
        "total_paid": 200000.00,
        "outstanding": 300000.00,
        "pending_count": 5
    },
    "incoming": {
        "label": "Payments from Clients",
        "total_value": 800000.00,
        "total_received": 600000.00,
        "outstanding": 200000.00,
        "pending_count": 3
    },
    "cash_flow": {
        "total_inflow": 600000.00,
        "total_outflow": 200000.00,
        "net_flow": 400000.00
    },
    "purchase_items": {
        "total_items": 25,
        "purchased_items": 18,
        "pending_items": 7,
        "purchased_value": 350000.00
    },
    "recent_outgoing": [ "...last 10 outgoing payment objects..." ],
    "recent_incoming": [ "...last 10 incoming payment objects..." ]
}
```

---

## 12. DASHBOARD & REPORTS

### 12.1 Main Dashboard
```
GET /api/dashboard/stats
```

### 12.2 Sales Dashboard
```
GET /api/dashboard/sales/stats
```

### 12.3 Billing Dashboard
```
GET /api/dashboard/billing/stats
```

### 12.4 Reports
```
GET /api/reports/requisitions
GET /api/reports/requisitions/{id}/detailed
GET /api/reports/vendors/performance
GET /api/reports/vendors/quotation-comparison
GET /api/reports/purchase-orders
GET /api/reports/inventory/stock
GET /api/reports/inventory/movement
GET /api/reports/financial/spending
GET /api/reports/sales/client-queries
GET /api/reports/sales/client-queries/{id}/detailed
GET /api/reports/sales/quotations
GET /api/reports/sales/quotation-items
GET /api/reports/sales/analytics
GET /api/reports/sales/performance
GET /api/reports/sales/products
GET /api/reports/billing/bills
GET /api/reports/billing/bills/{id}/detailed
GET /api/reports/billing/analytics
GET /api/reports/billing/outstanding
GET /api/reports/work-orders
GET /api/reports/work-orders/{id}/detailed
GET /api/reports/work-orders/delivery-analysis
```

---

## Error Responses

All endpoints return errors in this format:
```json
{ "error": "Description of what went wrong" }
```

**Common HTTP status codes:**
| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 400 | Bad Request (validation error) |
| 401 | Unauthorized (missing/invalid token) |
| 403 | Forbidden (e.g., trying to delete) |
| 404 | Not Found |
