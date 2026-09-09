# PaymentPulse — Data Dictionary

**Version:** 1.0 (Tier 1)  
**Storage Engine:** DuckDB (`data/paymentpulse.duckdb`)  
**Architecture:** Medallion (Bronze → Silver → Gold)

---

## 1. Bronze Layer (Raw Ingestion)

All fields are stored as unparsed `VARCHAR` (strings) with audit metadata.

### `bronze.raw_transactions`
| Field Name | Type | Nullable | Description | Source | Quality Rules |
|---|---|---|---|---|---|
| `transaction_id` | VARCHAR | Yes | Primary unique identifier for raw transaction | Raw CSV feed | Mandatory in Silver |
| `customer_id` | VARCHAR | Yes | Initiating customer UUID | Raw CSV feed | Checked for orphan IDs in Silver |
| `merchant_id` | VARCHAR | Yes | Recipient merchant UUID | Raw CSV feed | Checked for orphan IDs in Silver |
| `payment_method` | VARCHAR | Yes | Method of payment | Raw CSV feed | Must match allowed payment methods |
| `timestamp` | VARCHAR | Yes | Raw string timestamp of payment initiation | Raw CSV feed | Must parse to valid ISO timestamp |
| `amount` | VARCHAR | Yes | Raw transaction amount string | Raw CSV feed | Must parse to positive float |
| `currency` | VARCHAR | Yes | Currency code string | Raw CSV feed | Must match ISO 4217 standard codes |
| `country` | VARCHAR | Yes | Two-letter ISO country code | Raw CSV feed | Cleaned and validated |
| `channel` | VARCHAR | Yes | Transaction channel | Raw CSV feed | e.g., online, mobile, branch, pos |
| `device_type` | VARCHAR | Yes | Device used for initiation | Raw CSV feed | e.g., desktop, mobile, tablet |
| `status` | VARCHAR | Yes | Payment lifecycle state | Raw CSV feed | INITIATED, SUCCESS, FAILED, PENDING, REVERSED |
| `batch_id` | VARCHAR | No | Ingestion batch identifier UUID | Ingestion pipeline | Idempotency key |
| `_ingested_at` | TIMESTAMP | No | System timestamp when row landed in Bronze | DuckDB system | `CURRENT_TIMESTAMP` |

### `bronze.raw_customers`
| Field Name | Type | Nullable | Description | Source |
|---|---|---|---|---|
| `customer_id` | VARCHAR | Yes | Customer unique identifier | Reference feed |
| `name` | VARCHAR | Yes | Customer full name | Reference feed |
| `email` | VARCHAR | Yes | Customer contact email | Reference feed |
| `segment` | VARCHAR | Yes | Customer segment (retail, premium, etc.) | Reference feed |
| `country` | VARCHAR | Yes | Primary country of residence | Reference feed |
| `customer_since` | VARCHAR | Yes | Date customer account opened | Reference feed |
| `batch_id` | VARCHAR | No | Ingestion batch identifier UUID | Ingestion pipeline |
| `_ingested_at` | TIMESTAMP | No | System ingestion timestamp | DuckDB system |

### `bronze.raw_merchants`
| Field Name | Type | Nullable | Description | Source |
|---|---|---|---|---|
| `merchant_id` | VARCHAR | Yes | Merchant unique identifier | Reference feed |
| `name` | VARCHAR | Yes | Registered merchant business name | Reference feed |
| `category` | VARCHAR | Yes | Merchant business category | Reference feed |
| `country` | VARCHAR | Yes | Registered business country | Reference feed |
| `risk_category` | VARCHAR | Yes | Risk classification (low, medium, high) | Reference feed |
| `batch_id` | VARCHAR | No | Ingestion batch identifier UUID | Ingestion pipeline |
| `_ingested_at` | TIMESTAMP | No | System ingestion timestamp | DuckDB system |

### `bronze.ingestion_audit`
| Field Name | Type | Nullable | Description |
|---|---|---|---|
| `audit_id` | VARCHAR (PK) | No | Unique audit record identifier UUID |
| `batch_id` | VARCHAR | No | Batch identifier UUID |
| `source_file` | VARCHAR | Yes | File path ingested |
| `table_name` | VARCHAR | Yes | Target bronze table |
| `schema_version` | VARCHAR | Yes | Schema version contract |
| `ingestion_timestamp`| TIMESTAMP | Yes | Ingestion start timestamp |
| `record_count` | BIGINT | Yes | Total records read from file |
| `success_count` | BIGINT | Yes | Records successfully landed |
| `failure_count` | BIGINT | Yes | Records failing schema check |
| `status` | VARCHAR | Yes | SUCCESS / SCHEMA_ERROR / READ_ERROR |
| `error_detail` | VARCHAR | Yes | Stacktrace or missing column details |

---

## 2. Silver Layer (Cleaned, Typed, Validated & Quarantined)

### `silver.transactions`
| Field Name | Type | Nullable | Description | Quality Rules & Controls |
|---|---|---|---|---|
| `transaction_id` | VARCHAR (PK) | No | Unique transaction identifier | Uniqueness enforced; duplicates quarantined |
| `customer_id` | VARCHAR (FK) | No | Valid customer reference | Referential integrity verified against `silver.customers` |
| `merchant_id` | VARCHAR (FK) | No | Valid merchant reference | Referential integrity verified against `silver.merchants` |
| `payment_method` | VARCHAR | No | Validated payment method | Must belong to allowed set |
| `ts` | TIMESTAMP | No | Normalized UTC timestamp | Parsed; future timestamps quarantined |
| `amount` | DOUBLE | No | Validated transaction amount in GBP equivalent | Amount > 0 and <= £1,000,000 |
| `currency` | VARCHAR | No | Standard ISO-4217 currency code | Must belong to allowed set |
| `country` | VARCHAR | No | ISO country code | Cleaned string |
| `channel` | VARCHAR | No | Ingestion channel | Cleaned string |
| `device_type` | VARCHAR | No | User device type | Cleaned string |
| `status` | VARCHAR | No | Validated lifecycle status | INITIATED, SUCCESS, FAILED, PENDING, REVERSED |
| `batch_id` | VARCHAR | No | Batch identifier UUID | Preserved from Bronze |
| `_loaded_at` | TIMESTAMP | No | Load timestamp into Silver | System timestamp |

### `silver.quarantine`
| Field Name | Type | Nullable | Description |
|---|---|---|---|
| `transaction_id` | VARCHAR | Yes | Transaction ID (if present in raw record) |
| `raw_record` | VARCHAR | No | Complete raw row serialised as JSON string |
| `rejection_reason` | VARCHAR | No | Semicolon-delimited list of failing DQ checks |
| `batch_id` | VARCHAR | No | Source batch identifier |
| `_quarantined_at` | TIMESTAMP | No | System quarantine timestamp |

---

## 3. Gold Layer (Dimensional Star Schema)

### `gold.fact_transactions`
| Column Name | Type | Key | Nullable | Description |
|---|---|---|---|---|
| `transaction_id` | VARCHAR | PK | No | Unique business transaction key |
| `customer_sk` | INTEGER | FK | No | Surrogate key referencing `gold.dim_customer` |
| `merchant_sk` | INTEGER | FK | No | Surrogate key referencing `gold.dim_merchant` |
| `payment_method_sk`| INTEGER | FK | No | Surrogate key referencing `gold.dim_payment_method` |
| `date_sk` | INTEGER | FK | No | Surrogate key referencing `gold.dim_date` (format: YYYYMMDD) |
| `ts` | TIMESTAMP | | No | Transaction event timestamp |
| `amount` | DOUBLE | | No | Cleaned transaction amount |
| `currency` | VARCHAR | | No | ISO-4217 currency code |
| `country` | VARCHAR | | No | Transaction country |
| `channel` | VARCHAR | | No | Transaction channel |
| `device_type` | VARCHAR | | No | Initiation device |
| `status` | VARCHAR | | No | Transaction terminal status |
| `is_success` | BOOLEAN | | No | Derived flag: `status = 'SUCCESS'` |
| `is_failed` | BOOLEAN | | No | Derived flag: `status = 'FAILED'` |
| `is_reversed` | BOOLEAN | | No | Derived flag: `status = 'REVERSED'` |
| `batch_id` | VARCHAR | | No | Ingestion batch identifier |

### `gold.dim_customer`
| Column Name | Type | Key | Description |
|---|---|---|---|
| `customer_sk` | INTEGER | PK | Integer surrogate key |
| `customer_id` | VARCHAR | Natural Key | UUID customer key |
| `name` | VARCHAR | | Customer name |
| `email` | VARCHAR | | Customer contact email |
| `segment` | VARCHAR | | Behavioral segment |
| `country` | VARCHAR | | Country of residence |
| `customer_since` | DATE | | Account open date |

### `gold.dim_merchant`
| Column Name | Type | Key | Description |
|---|---|---|---|
| `merchant_sk` | INTEGER | PK | Integer surrogate key |
| `merchant_id` | VARCHAR | Natural Key | UUID merchant key |
| `name` | VARCHAR | | Registered merchant name |
| `category` | VARCHAR | | Industry category |
| `country` | VARCHAR | | Registered country |
| `risk_category` | VARCHAR | | Risk tier (low, medium, high) |

### `gold.dim_payment_method`
| Column Name | Type | Key | Description |
|---|---|---|---|
| `payment_method_sk`| INTEGER | PK | Integer surrogate key |
| `payment_method` | VARCHAR | Natural Key | Specific method name |
| `method_group` | VARCHAR | | Classification group (`card`, `account`, `digital`, `other`) |

### `gold.dim_date`
| Column Name | Type | Key | Description |
|---|---|---|---|
| `date_sk` | INTEGER | PK | Date key in YYYYMMDD integer format |
| `full_date` | DATE | | Full calendar date |
| `year` | INTEGER | | Calendar year |
| `quarter` | INTEGER | | Fiscal/calendar quarter (1-4) |
| `month` | INTEGER | | Calendar month (1-12) |
| `month_name` | VARCHAR | | Full month name (e.g. January) |
| `week_of_year` | INTEGER | | ISO week number |
| `day_of_month` | INTEGER | | Day of the month (1-31) |
| `day_of_week` | INTEGER | | Day of week (0-6) |
| `day_name` | VARCHAR | | Name of day (e.g. Monday) |
| `is_weekend` | BOOLEAN | | True if Saturday or Sunday |
