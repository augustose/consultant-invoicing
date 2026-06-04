# Technology Stack and Architecture

This document summarizes the public architecture for Consultant Invoicing.

## Core Stack

- **Language:** Python 3.11+
- **Package manager:** uv
- **UI framework:** NiceGUI, built on Vue and Quasar
- **Database:** SQLite
- **ORM:** SQLModel
- **Templates:** Jinja2 HTML invoice templates
- **Charts:** Plotly
- **Logging:** Loguru

## Architecture

The app is local-first. User data lives in `data/accounting.db`, and that directory is ignored by git except for `data/.gitkeep`.

The application is intentionally small:

- `app/database.py` defines the SQLModel tables and seed data.
- `app/main.py` defines the NiceGUI pages and local routes.
- `app/template_utils.py` renders invoice templates.
- `app/pdf_utils.py` builds downloadable invoice PDFs.
- `app/style.css` contains shared UI styling.

## Data Model

Core tables:

- `Account`
- `CompanySettings`
- `TaxRate`
- `Customer`
- `Service`
- `Invoice`
- `InvoiceItem`
- `RecurringProfile`
- `Expense`

## Documentation Layout

```text
docs/
├── public/       # Sanitized docs that can be committed
└── private/      # Local source material and private notes; ignored by git
```

Private documentation can include source invoice notes, local implementation plans, screenshots, customer details, tax numbers, and other material that should not be published.

## Future-Ready Features

- Optional AI integrations can be added behind explicit user configuration.
- The local SQLite schema keeps the app suitable for a future MCP server or local automation layer.
- The current interface has basic English/Spanish label support through an in-app language selector.

---

Last updated: 2026-06-04
