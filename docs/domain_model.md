# PaymentPulse — Domain Model

**Execution environment:** Local  
**Version:** 1.0 (Tier 1)

---

## Entity Relationship Diagram

```
┌──────────────────────────────────────┐
│               CUSTOMERS              │
│──────────────────────────────────────│
│ PK  customer_id    VARCHAR (UUID)    │
│     name           VARCHAR           │
│     email          VARCHAR           │
│     segment        VARCHAR           │
│     country        CHAR(2)           │
│     customer_since DATE              │
└──────────────────┬───────────────────┘
                   │ 1
                   │
                   │ N
┌──────────────────▼───────────────────┐       ┌────────────────────────────────┐
│            TRANSACTIONS              │       │           MERCHANTS            │
│──────────────────────────────────────│       │────────────────────────────────│
│ PK  transaction_id VARCHAR (UUID)    │  N    │ PK  merchant_id  VARCHAR (UUID)│
│ FK  customer_id    VARCHAR ──────────────────►     name         VARCHAR       │
│ FK  merchant_id    VARCHAR ──────────────────►     category     VARCHAR       │
│     payment_method VARCHAR           │  1    │     country      CHAR(2)       │
│     timestamp      TIMESTAMP         │       │     risk_category VARCHAR      │
│     amount         DOUBLE            │       └────────────────────────────────┘
│     currency       CHAR(3)           │
│     country        CHAR(2)           │
│     channel        VARCHAR           │
│     device_type    VARCHAR           │
│     status         VARCHAR           │
│     batch_id       VARCHAR           │
└──────────────────────────────────────┘
```

---

## Payment Lifecycle

Every transaction begins as `INITIATED` and transitions to a terminal state.

```
                    INITIATED
                        │
           ┌────────────┼──────────────┐
           │            │              │
           ▼            ▼              ▼
        SUCCESS       FAILED        PENDING
                                       │
                                       ▼
                                    SUCCESS
           │
           ▼
        REVERSED   ← can follow a SUCCESS
```

### Status Definitions

| Status | Description | Terminal? |
|---|---|---|
| `INITIATED` | Payment request created; awaiting processing | No |
| `SUCCESS` | Payment authorised and settled | Yes |
| `FAILED` | Payment declined or errored | Yes |
| `PENDING` | Awaiting bank confirmation (e.g. 3DS, open banking) | No |
| `REVERSED` | Previously settled payment reversed (chargeback/refund) | Yes |

### Typical failure reasons (not stored in synthetic data, documented for context)

- Insufficient funds
- Card expired or blocked
- Fraud rule triggered
- Network timeout
- Invalid card number
- 3D Secure authentication failure
- Merchant account suspended

---

## Entity Descriptions

### Customers

Represents a bank customer who initiates payment transactions.

| Field | Type | Description |
|---|---|---|
| `customer_id` | VARCHAR (UUID) | Unique customer identifier |
| `name` | VARCHAR | Customer full name (synthetic — Faker) |
| `email` | VARCHAR | Customer email (synthetic — Faker) |
| `segment` | VARCHAR | One of: retail, premium, business, student, private_banking |
| `country` | CHAR(2) | ISO 3166-1 alpha-2 country code of residence |
| `customer_since` | DATE | Account opening date |

**Behavioural assumptions (in generator):**
- Premium customers transact in higher average amounts
- Business customers use bank_transfer and faster_payments more frequently
- Student customers transact less frequently and in smaller amounts

---

### Merchants

Represents a payment recipient (retailer, service provider, etc.).

| Field | Type | Description |
|---|---|---|
| `merchant_id` | VARCHAR (UUID) | Unique merchant identifier |
| `name` | VARCHAR | Merchant business name (synthetic — Faker) |
| `category` | VARCHAR | Merchant category (retail, travel, healthcare, etc.) |
| `country` | CHAR(2) | ISO 3166-1 alpha-2 merchant country |
| `risk_category` | VARCHAR | One of: low, medium, high |

**Risk category distribution (in generator):**
- 70% low risk
- 20% medium risk
- 10% high risk

High-risk merchants have elevated failure rates (32% vs 12% baseline).

---

### Transactions

Central entity. One row per payment event.

| Field | Type | Description |
|---|---|---|
| `transaction_id` | VARCHAR (UUID) | Unique transaction identifier |
| `customer_id` | VARCHAR (UUID) | FK → customers |
| `merchant_id` | VARCHAR (UUID) | FK → merchants |
| `payment_method` | VARCHAR | One of 8 payment methods |
| `timestamp` | TIMESTAMP | UTC timestamp of transaction initiation |
| `amount` | DOUBLE | Transaction amount in originating currency |
| `currency` | CHAR(3) | ISO 4217 currency code |
| `country` | CHAR(2) | Country where transaction occurred |
| `channel` | VARCHAR | One of: online, mobile, branch, atm, pos |
| `device_type` | VARCHAR | One of: desktop, mobile, tablet, unknown |
| `status` | VARCHAR | Payment lifecycle status |
| `batch_id` | VARCHAR (UUID) | Ingestion batch this record belongs to |

---

## Payment Methods

| Payment Method | Method Group | Typical Use | Avg Amount (GBP) |
|---|---|---|---|
| `credit_card` | card | Retail purchases | £120 |
| `debit_card` | card | Everyday spending | £65 |
| `bank_transfer` | account | High-value B2B | £2,500 |
| `digital_wallet` | digital | Mobile/contactless | £40 |
| `buy_now_pay_later` | digital | Deferred retail | £250 |
| `direct_debit` | account | Recurring bills | £150 |
| `standing_order` | account | Regular transfers | £500 |
| `faster_payments` | account | Urgent transfers | £1,000 |

---

## Merchant Categories

| Category | Description |
|---|---|
| `retail` | Physical and online retail |
| `food_and_beverage` | Restaurants, cafes, takeaways |
| `travel` | Airlines, hotels, car hire |
| `healthcare` | Pharmacies, private clinics |
| `utilities` | Energy, broadband, water |
| `entertainment` | Streaming, events, gaming |
| `financial_services` | Insurance, wealth management |
| `ecommerce` | Pure-play online retail |
| `education` | Universities, training providers |
| `real_estate` | Property agents, rentals |

---

## Gold Dimensional Model

The Gold layer implements a star schema for analytical queries.

```
                         dim_date
                            │
              dim_customer   │   dim_merchant
                   │         │         │
                   └────┬────┘         │
                        ▼              │
              fact_transactions ◄──────┘
                        │
                        ▼
                dim_payment_method
```

### Fact table: `gold.fact_transactions`

Central fact table. Grain = one row per transaction.

| Column | Type | Description |
|---|---|---|
| `transaction_id` | VARCHAR PK | Unique transaction ID |
| `customer_sk` | INTEGER FK | Surrogate key → dim_customer |
| `merchant_sk` | INTEGER FK | Surrogate key → dim_merchant |
| `payment_method_sk` | INTEGER FK | Surrogate key → dim_payment_method |
| `date_sk` | INTEGER FK | Surrogate key → dim_date (YYYYMMDD) |
| `ts` | TIMESTAMP | Transaction timestamp |
| `amount` | DOUBLE | Transaction amount |
| `currency` | CHAR(3) | Currency code |
| `country` | CHAR(2) | Transaction country |
| `channel` | VARCHAR | Transaction channel |
| `device_type` | VARCHAR | Device type |
| `status` | VARCHAR | Payment status |
| `is_success` | BOOLEAN | Derived: status = 'SUCCESS' |
| `is_failed` | BOOLEAN | Derived: status = 'FAILED' |
| `is_reversed` | BOOLEAN | Derived: status = 'REVERSED' |
| `batch_id` | VARCHAR | Source batch |
