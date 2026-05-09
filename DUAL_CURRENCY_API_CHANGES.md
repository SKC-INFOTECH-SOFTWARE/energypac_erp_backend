# Dual Currency Support — API Changes Documentation

## Overview

The system now supports **dual currency (INR + USD)**. All internal calculations and storage remain in **INR**. When a user selects USD, the system stores both the original USD amounts and the converted INR amounts.

- **Product prices** remain in INR only
- **Exchange rate** is managed by Admin via API or Django Admin Panel
- **Quotation comparison** always happens in INR (USD quotations auto-converted)
- Currency flows downstream automatically: `ClientQuery → SalesQuotation → WorkOrder → Bill` and `VendorQuotation → PurchaseOrder`

---

## 1. Exchange Rate Admin APIs (Admin Only)

### 1.1 Get Current Active Rate

```
GET /api/exchange-rate
Authorization: Bearer <token>
```

**Response (200):**
```json
{
  "currency_from": "USD",
  "currency_to": "INR",
  "rate": 83.5,
  "effective_date": "2026-05-08",
  "updated_at": "2026-05-08T10:30:00+05:30"
}
```

**Response (404) — No rate configured:**
```json
{
  "error": "No active USD to INR exchange rate configured. Please set one in Admin."
}
```

---

### 1.2 List All Exchange Rates (History)

```
GET /api/admin/exchange-rates
Authorization: Bearer <admin-token>
Permission: ADMIN role required
```

**Response (200):**
```json
{
  "count": 3,
  "results": [
    {
      "id": "uuid-here",
      "rate": 83.5000,
      "effective_date": "2026-05-08",
      "is_active": true,
      "remarks": "Updated as per RBI reference rate",
      "updated_by": "uuid",
      "updated_by_name": "Admin User",
      "created_at": "2026-05-08T10:30:00+05:30",
      "updated_at": "2026-05-08T10:30:00+05:30"
    },
    {
      "id": "uuid-here",
      "rate": 83.2500,
      "effective_date": "2026-05-01",
      "is_active": false,
      "remarks": "Previous rate",
      "updated_by": "uuid",
      "updated_by_name": "Admin User",
      "created_at": "2026-05-01T09:00:00+05:30",
      "updated_at": "2026-05-08T10:30:00+05:30"
    }
  ]
}
```

---

### 1.3 Create New Exchange Rate

```
POST /api/admin/exchange-rates
Authorization: Bearer <admin-token>
Content-Type: application/json
```

**Request Body:**
```json
{
  "rate": 84.2500,
  "effective_date": "2026-05-09",
  "is_active": true,
  "remarks": "Rate updated per market"
}
```

> **Note:** Setting `is_active: true` will automatically deactivate the previously active rate.

**Response (201):**
```json
{
  "id": "new-uuid",
  "rate": 84.2500,
  "effective_date": "2026-05-09",
  "is_active": true,
  "remarks": "Rate updated per market",
  "updated_by": "admin-uuid",
  "updated_by_name": "Admin User",
  "created_at": "2026-05-09T08:00:00+05:30",
  "updated_at": "2026-05-09T08:00:00+05:30"
}
```

---

### 1.4 Get Single Exchange Rate

```
GET /api/admin/exchange-rates/{id}
Authorization: Bearer <admin-token>
```

**Response (200):** Same as single item in list response.

---

### 1.5 Update Exchange Rate (Full)

```
PUT /api/admin/exchange-rates/{id}
Authorization: Bearer <admin-token>
Content-Type: application/json
```

**Request Body:**
```json
{
  "rate": 84.5000,
  "effective_date": "2026-05-09",
  "is_active": true,
  "remarks": "Corrected rate"
}
```

---

### 1.6 Update Exchange Rate (Partial)

```
PATCH /api/admin/exchange-rates/{id}
Authorization: Bearer <admin-token>
Content-Type: application/json
```

**Request Body (only fields to update):**
```json
{
  "rate": 85.0000
}
```

---

### 1.7 Delete Exchange Rate

```
DELETE /api/admin/exchange-rates/{id}
Authorization: Bearer <admin-token>
```

> **Restriction:** Cannot delete the active rate. Deactivate it first or set another rate as active.

**Response (204):** No content.

**Response (400) — If active:**
```json
{
  "error": "Cannot delete the active exchange rate. Deactivate it first or set another rate as active."
}
```

---

## 2. Client Query API Changes

### 2.1 Create Client Query

```
POST /api/client-queries
Authorization: Bearer <token>
Content-Type: multipart/form-data
```

**New field in request:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `currency` | string | `"INR"` | `"INR"` or `"USD"` — client ki preferred currency |

**Example:**
```json
{
  "client_name": "ABC International",
  "contact_person": "John",
  "phone": "9876543210",
  "email": "john@abc.com",
  "query_date": "2026-05-08",
  "currency": "USD",
  "remarks": "Need quotation in USD for export order"
}
```

---

### 2.2 Get Client Query Response

**New field:**

| Field | Type | Description |
|-------|------|-------------|
| `currency` | string | `"INR"` or `"USD"` |

**Example Response:**
```json
{
  "id": "uuid",
  "query_number": "CQ/2026/0001",
  "client_name": "ABC International",
  "currency": "USD",
  "status": "PENDING",
  ...
}
```

---

### 2.3 Currency Auto-Inherit

When creating a **Sales Quotation** from this client query:
- If `currency` is **not passed** in the quotation request → inherits from ClientQuery
- If `currency` **is passed** → uses the passed value (override)

```
ClientQuery (currency: "USD")
    ↓ auto-inherit
SalesQuotation (currency: "USD")  ← no need to pass currency again
    ↓ auto-inherit
WorkOrder (currency: "USD")
    ↓ auto-inherit
Bill (currency: "USD")
```

---

## 3. Vendor Quotation API Changes

### 2.1 Create Vendor Quotation

```
POST /api/vendor-quotations
```

**New field in request:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `currency` | string | `"INR"` | `"INR"` or `"USD"` |

**Example (USD quotation):**
```json
{
  "requisition": "req-uuid",
  "vendor": "vendor-uuid",
  "currency": "USD",
  "reference_number": "VQ-2026-001",
  "items": [
    {
      "vendor_item": "item-uuid",
      "quoted_rate": 120.00
    }
  ]
}
```

> When `currency: "USD"`, the system:
> 1. Fetches current active exchange rate
> 2. Stores `quoted_rate` as original USD rate
> 3. Converts to INR: `quoted_rate_inr = 120.00 × 83.50 = 10,020.00`
> 4. Stores both values

---

### 2.2 Get Vendor Quotation Response

**New fields in response:**

| Field | Type | Description |
|-------|------|-------------|
| `currency` | string | `"INR"` or `"USD"` |
| `exchange_rate` | decimal | USD to INR rate used (1.0 if INR) |
| `original_total_amount` | decimal | Total in original currency |
| `items[].original_quoted_rate` | decimal | Rate in original currency |
| `items[].original_amount` | decimal | Amount in original currency |

**Example Response:**
```json
{
  "id": "uuid",
  "quotation_number": "VQ/2026/0001",
  "currency": "USD",
  "exchange_rate": 83.5000,
  "total_amount": 100200.00,
  "original_total_amount": 1200.00,
  "items": [
    {
      "product_name": "Motor Unit",
      "quantity": 10.00,
      "quoted_rate": 10020.00,
      "amount": 100200.00,
      "original_quoted_rate": 120.00,
      "original_amount": 1200.00
    }
  ]
}
```

---

## 4. Sales Quotation API Changes

### 3.1 Create Sales Quotation

```
POST /api/quotations
```

**New field in request:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `currency` | string | `"INR"` | `"INR"` or `"USD"` |

**Example (USD):**
```json
{
  "client_query": "query-uuid",
  "quotation_date": "2026-05-08",
  "currency": "USD",
  "cgst_percentage": 0,
  "sgst_percentage": 0,
  "igst_percentage": 0,
  "items": [
    {
      "product": "product-uuid",
      "quantity": 5,
      "rate": 200.00
    }
  ]
}
```

> `rate: 200.00` is in USD. System converts to INR internally.

---

### 3.2 Update Sales Quotation

```
PUT /PATCH /api/quotations/{id}
```

Currency can be changed during update. When changed from INR to USD (or vice versa), the exchange rate is automatically fetched.

```json
{
  "currency": "USD"
}
```

---

### 3.3 Get Sales Quotation Response

**New fields:**

| Field | Type | Description |
|-------|------|-------------|
| `currency` | string | `"INR"` or `"USD"` |
| `exchange_rate` | decimal | Rate used at creation time |
| `original_subtotal` | decimal | Subtotal in original currency |
| `original_cgst_amount` | decimal | CGST in original currency |
| `original_sgst_amount` | decimal | SGST in original currency |
| `original_igst_amount` | decimal | IGST in original currency |
| `original_total_amount` | decimal | Total in original currency |
| `items[].original_rate` | decimal | Item rate in original currency |
| `items[].original_amount` | decimal | Item amount in original currency |

---

## 5. Purchase Order API Changes

### 4.1 Generate PO

```
POST /api/purchase-orders/generate-po
```

**No change in request.** Currency is automatically inherited from the vendor quotation.

---

### 4.2 Get PO Response

**New fields:**

| Field | Type | Description |
|-------|------|-------------|
| `currency` | string | Inherited from vendor quotation |
| `exchange_rate` | decimal | Rate used |
| `original_items_total` | decimal | Items total in original currency |
| `original_freight_cost` | decimal | Freight in original currency |
| `original_total_amount` | decimal | Total in original currency |
| `items[].original_rate` | decimal | Item rate in original currency |
| `items[].original_amount` | decimal | Item amount in original currency |

---

## 6. Work Order API Changes

### 5.1 Create Work Order

```
POST /api/work-orders
```

**No change in request.** Currency is automatically inherited from the sales quotation.

---

### 5.2 Get Work Order Response

**New fields:**

| Field | Type | Description |
|-------|------|-------------|
| `currency` | string | Inherited from sales quotation |
| `exchange_rate` | decimal | Rate used |
| `original_subtotal` | decimal | Subtotal in original currency |
| `original_cgst_amount` | decimal | CGST in original currency |
| `original_sgst_amount` | decimal | SGST in original currency |
| `original_igst_amount` | decimal | IGST in original currency |
| `original_total_amount` | decimal | Total in original currency |
| `items[].original_rate` | decimal | Item rate in original currency |
| `items[].original_amount` | decimal | Item amount in original currency |

---

## 7. Bill / Invoice API Changes

### 6.1 Create Bill

```
POST /api/bills
```

**No change in request.** Currency is automatically inherited from the work order.

---

### 6.2 Get Bill Response

**New fields:**

| Field | Type | Description |
|-------|------|-------------|
| `currency` | string | Inherited from work order |
| `exchange_rate` | decimal | Rate used |
| `original_subtotal` | decimal | Subtotal in original currency |
| `original_cgst_amount` | decimal | CGST in original currency |
| `original_sgst_amount` | decimal | SGST in original currency |
| `original_igst_amount` | decimal | IGST in original currency |
| `original_total_amount` | decimal | Total in original currency |
| `original_freight_cost` | decimal | Freight in original currency |
| `original_net_payable` | decimal | Net payable in original currency |
| `items[].original_rate` | decimal | Item rate in original currency |
| `items[].original_amount` | decimal | Item amount in original currency |

---

## 8. Finance API Changes

### 7.1 Finance PO Summary

```
GET /api/finance/purchase-orders
```

**New fields in response:** `currency`, `exchange_rate`, `original_items_total`, `original_freight_cost`, `original_total_amount`

---

### 7.2 Finance Bill Summary

```
GET /api/finance/bills
```

**New fields in response:** `currency`, `exchange_rate`, `original_subtotal`, `original_cgst_amount`, `original_sgst_amount`, `original_igst_amount`, `original_total_amount`, `original_freight_cost`, `original_net_payable`

---

## 9. Reports — Quotation Comparison

### 8.1 Vendor Quotation Comparison

```
GET /api/reports/vendors/quotation-comparison?requisition={id}
```

**Changes:**
- All comparisons happen in **INR** (USD quotations are auto-converted)
- New field: `comparison_currency: "INR"`
- Renamed fields for clarity

**Response:**
```json
{
  "report_type": "Vendor Quotation Comparison",
  "comparison_currency": "INR",
  "requisition_number": "EEL/2026/001",
  "quotations": [
    {
      "vendor_name": "ABC International",
      "vendor_code": "VEN/0001",
      "quotation_number": "VQ/2026/0001",
      "currency": "USD",
      "exchange_rate": 83.50,
      "total_amount_inr": 100200.00,
      "original_total_amount": 1200.00,
      "is_selected": false,
      "items": [
        {
          "product_code": "ITEM/0001",
          "product_name": "Motor Unit",
          "quantity": 10.0,
          "quoted_rate_inr": 10020.00,
          "amount_inr": 100200.00,
          "original_quoted_rate": 120.00,
          "original_amount": 1200.00
        }
      ]
    },
    {
      "vendor_name": "XYZ Domestic",
      "vendor_code": "VEN/0002",
      "quotation_number": "VQ/2026/0002",
      "currency": "INR",
      "exchange_rate": 1.0,
      "total_amount_inr": 95000.00,
      "original_total_amount": 95000.00,
      "is_selected": true,
      "items": [
        {
          "product_code": "ITEM/0001",
          "product_name": "Motor Unit",
          "quantity": 10.0,
          "quoted_rate_inr": 9500.00,
          "amount_inr": 95000.00,
          "original_quoted_rate": 9500.00,
          "original_amount": 95000.00
        }
      ]
    }
  ],
  "analysis": {
    "lowest_quote": { "vendor_name": "XYZ Domestic", "total_amount_inr": 95000.00 },
    "highest_quote": { "vendor_name": "ABC International", "total_amount_inr": 100200.00 },
    "selected_quote": { "vendor_name": "XYZ Domestic", "total_amount_inr": 95000.00 },
    "savings_achieved_inr": 5200.00,
    "savings_percentage": 5.19
  }
}
```

---

## 10. Currency Flow Diagram

```
                    USER SELECTS CURRENCY
                           |
          +----------------+----------------+
          |                                 |
   Sales Quotation                  Vendor Quotation
   (currency: USD/INR)              (currency: USD/INR)
          |                                 |
          | auto-inherit                    | auto-inherit
          v                                 v
     Work Order                       Purchase Order
   (currency from SQ)              (currency from VQ)
          |
          | auto-inherit
          v
        Bill
   (currency from WO)
```

---

## 10. Important Notes

1. **Payments are always in INR** — BillPayment, PurchasePayment, IncomingPayment amounts are always INR.

2. **Exchange rate is a snapshot** — The rate at the time of document creation is stored. If the admin changes the rate later, existing documents are NOT affected.

3. **Backward compatible** — All existing data works as-is. Default values: `currency = "INR"`, `exchange_rate = 1.0000`, `original_* = same as INR amounts`.

4. **Admin must set a rate before using USD** — If no active exchange rate exists and user tries to create a USD document, the API returns an error.

5. **Rate validation** — Rate must be greater than 0. Only one rate can be active at a time.

6. **Existing fields unchanged** — All existing amount fields (`subtotal`, `total_amount`, `balance`, etc.) remain in INR. New `original_*` fields hold the original currency values.
