# Consultant Invoicing

A local-first invoicing and accounting app for independent consultants, built with Python and NiceGUI. Runs entirely on your machine — no cloud, no subscriptions.

![Python](https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python)
![NiceGUI](https://img.shields.io/badge/NiceGUI-latest-indigo?style=flat-square)
![SQLite](https://img.shields.io/badge/SQLite-local--first-green?style=flat-square&logo=sqlite)
![License](https://img.shields.io/badge/License-MIT-slate?style=flat-square)

---

## Features

- **Invoicing** — Create, send, and track invoices through a clean workflow: Draft → Sent → Paid → Cancelled
- **Recurring billing** — Set up recurring invoice profiles that auto-generate on schedule
- **CRM** — Manage clients, contacts, and billing addresses
- **Services catalog** — Define your services with unit prices; auto-fill line items when creating invoices
- **Chart of accounts** — Full double-entry account structure (Assets, Liabilities, Income, Expenses, Equity)
- **Reports** — Sales and tax reports (TPS/TVQ) for any custom date range or preset period
- **HTML invoice templates** — Customizable Jinja2 templates; print to PDF directly from the browser
- **Dashboard** — Monthly revenue chart, outstanding amounts, and recent invoice activity

## Tech Stack

| Layer | Technology |
|---|---|
| UI | [NiceGUI](https://nicegui.io) (Python-native web UI) |
| Database | SQLite via [SQLModel](https://sqlmodel.tiangolo.com) |
| Templates | Jinja2 HTML → browser print-to-PDF |
| Charts | Plotly |
| Package manager | [uv](https://docs.astral.sh/uv/) |
| Logging | Loguru |

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — fast Python package manager

## Getting Started

```bash
# 1. Clone the repo
git clone https://github.com/augustose/consultant-invoicing.git
cd consultant-invoicing

# 2. Install dependencies
uv sync

# 3. Run the app
uv run python app/main.py
```

Then open your browser at **http://localhost:8081**

## Project Structure

```
consultant-invoicing/
├── app/
│   ├── main.py              # All pages and routes (NiceGUI)
│   ├── database.py          # SQLModel models + DB init
│   ├── template_utils.py    # Jinja2 invoice template rendering
│   ├── log_config.py        # Loguru logging setup
│   ├── style.css            # Premium UI styles
│   └── templates/
│       └── invoice_default.html   # Default invoice HTML template
├── data/                    # SQLite DB + user data (gitignored)
├── docs/                    # Architecture decisions, plans
├── manage.sh                # Dev management script (start/stop/logs)
├── pyproject.toml
└── uv.lock
```

## Invoice Workflow

```
Draft → Sent → Paid
              ↘ Cancelled (from Draft or Sent)
```

## Tax Configuration

Pre-configured for **Québec, Canada**:
- TPS (GST): 5%
- TVQ (QST): 9.975%
- Combined: 14.975%

The tax report separates TPS and TVQ per invoice for easy filing.

## Custom Invoice Templates

The app ships with a default single-page HTML invoice template. To customize:

1. Go to **Settings → Invoice Template**
2. Export the default template as a starting point
3. Edit the HTML/CSS and upload your custom version
4. Preview any invoice at `/preview/{id}` — use browser Print → Save as PDF

Jinja2 variables available in templates: `vendor_entity`, `vendor_address`, `client_entity`, `client_address`, `line_items`, `subtotal`, `gst`, `qst`, `total`, `balance_due`, `notes`, and more.

## Development

```bash
# Start with live reload
uv run python app/main.py

# Or use the management script
./manage.sh
```

Logs are written to `logs/app.log` and `logs/errors.log`.

## Roadmap

- [x] Core invoicing (create, send, pay, cancel)
- [x] Recurring invoice profiles
- [x] Client/Service/Account management
- [x] Custom HTML invoice templates
- [x] Sales & tax reports with date ranges
- [x] Dashboard with revenue chart
- [ ] Data export (CSV/JSON) for accountant
- [ ] Multi-language UI (EN/ES)
- [ ] LLM integration for voice/natural language invoice creation

## License

MIT
