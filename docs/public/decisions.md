# Decision Log

This document records public architecture and product decisions for Consultant Invoicing.

## 2026-03-04: Initial Stack and Architecture

### 1. Python, uv, and NiceGUI

**Decision:** Use Python 3.11+, uv, and NiceGUI.

**Reason:** Python keeps the local accounting logic, UI, reporting, and future AI integrations in one approachable stack. uv provides fast, reproducible dependency management.

### 2. SQLite and SQLModel

**Decision:** Use SQLite with SQLModel.

**Reason:** SQLite is local-first, easy to back up, and appropriate for an independent consultant. SQLModel provides typed models for financial records.

### 3. Local-First Data Ownership

**Decision:** User data lives locally in the `data/` directory.

**Reason:** The app should run without cloud infrastructure and should keep accounting records under the user's control.

### 4. HTML Invoice Templates

**Decision:** Render invoices from customizable Jinja2 HTML templates.

**Reason:** HTML templates are easy to inspect, customize, preview, print, and convert to PDF.

### 5. Simple Operational UI

**Decision:** Keep the main workflow in a small set of sidebar pages: Dashboard, Invoices, Subscription, Customers, Services, Accounts, Expenses, Reports, Settings, and Help.

**Reason:** The target user needs a quiet operational tool for repeated invoicing and bookkeeping tasks, not an enterprise accounting suite.

## 2026-03-05: Data Privacy and Startup Safety

### 6. Exclude User Data from Git

**Decision:** Ignore `data/*` and keep only `data/.gitkeep` tracked.

**Reason:** The database, exports, uploaded templates, and generated artifacts can contain private financial and customer data.

### 7. Idempotent Database Initialization

**Decision:** Create folders, tables, and seed data on app startup when missing.

**Reason:** A fresh clone should launch without manual database setup, while existing data must never be overwritten.

### 8. Browser/PDF Export Path

**Decision:** Keep invoice preview as rendered HTML and expose a PDF download route.

**Reason:** The template path remains flexible while still supporting accountant/customer-ready PDFs.

### 9. Invoice Status Rules

**Decision:** Store user-driven statuses and derive overdue display from dates.

**Reason:** Draft, Sent, Paid, Cancelled, and Written Off represent explicit accounting actions. Overdue is a date-based display state for sent invoices.

## 2026-06-04: Public and Private Documentation Split

### 10. Public Docs Stay Sanitized

**Decision:** Public documentation lives under `docs/public/`.

**Reason:** Public docs should explain the product and architecture without customer names, tax numbers, addresses, source invoice metadata, or local working notes.

### 11. Private Docs Stay Local

**Decision:** Local source material and implementation notes live under `docs/private/`, which is ignored by git.

**Reason:** Some useful local context should remain available in the workspace without risking accidental publication.
