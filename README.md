# Consultant Invoicing

A local-first invoicing and accounting app for independent consultants, built with Python and NiceGUI. Runs entirely on your machine — no cloud, no subscriptions.

![Python](https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python)
![NiceGUI](https://img.shields.io/badge/NiceGUI-latest-indigo?style=flat-square)
![SQLite](https://img.shields.io/badge/SQLite-local--first-green?style=flat-square&logo=sqlite)
![License](https://img.shields.io/badge/License-MIT-slate?style=flat-square)

---

## Features

- **Invoicing** — Create, send, and track invoices through a clean workflow: Draft → Sent → Paid, with cancellation for drafts and write-off handling for uncollectible invoices
- **Recurring billing** — Set up recurring invoice profiles that auto-generate on schedule
- **CRM** — Manage clients, contacts, and billing addresses
- **Services catalog** — Define your services with unit prices; auto-fill line items when creating invoices
- **Chart of accounts** — Full double-entry account structure (Assets, Liabilities, Income, Expenses, Equity)
- **Expense tracking** — Record business expenses by account, optional TPS/TVQ, period filters, and CSV export
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

### macOS / Linux

```bash
# 1. Clone the repo
git clone https://github.com/augustose/consultant-invoicing.git
cd consultant-invoicing

# 2. Install dependencies
uv sync

# 3. Launch with the management script (recommended)
./manage.sh
```

### Windows

```powershell
# 1. Install uv (if not already installed)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. Clone the repo
git clone https://github.com/augustose/consultant-invoicing.git
cd consultant-invoicing

# 3. Install dependencies
uv sync

# 4. Launch with the management script (recommended)
manage.bat
```

### Management Script

Both `manage.sh` (macOS/Linux) and `manage.bat` (Windows) provide the same interactive menu:

| Key | Action |
|-----|--------|
| `W` | Start app and open browser automatically |
| `S` | Start app (terminal only) |
| `K` | Stop the running app |
| `L` | View live logs |
| `B` | Create a backup |
| `D` | Open docs folder |
| `X` | Exit |

Or run directly without the script:

```bash
uv run python app/main.py
```

Then open **http://localhost:8081** in your browser.

## Using the App

The left sidebar is the main navigation for the local accounting workflow:

| Option | Use it for | Main actions |
|---|---|---|
| **Dashboard** | Monitor the current state of the business. | Review paid, awaiting payment, draft totals, client count, monthly revenue, and recent invoices. |
| **Invoices** | Create and manage customer invoices. | Add invoices from customers and services, preview them, download PDFs, mark sent, mark paid, write off, or cancel drafts. |
| **Subscription** | Review recurring billing profiles. | See recurring customers and amounts; active profiles can generate draft recurring invoices when due. |
| **Customers** | Maintain the client list used by invoices. | Add or edit customer names, emails, phone numbers, contact people, and addresses; delete customers only when they are not tied to invoices. |
| **Services** | Manage the catalog of billable work. | Add services, set default descriptions and unit prices, edit existing services, toggle active status, and delete unused services. |
| **Accounts** | Maintain the chart of accounts. | Add accounts, edit account names and descriptions, activate or deactivate non-system accounts, delete custom accounts, and export JSON data. |
| **Expenses** | Track business spending against expense accounts. | Record date, description, account, amount, optional TPS/TVQ, and notes; filter by period and export expenses to CSV. |
| **Reports** | Analyze invoices, taxes, customers, and receivables. | Use period presets or custom dates for sales summary, revenue trend, TPS/TVQ report, income by customer, and aged receivables. |
| **Settings** | Configure company identity and invoice templates. | Update legal name, address, phone, email, GST/QST numbers, download the default template, upload custom HTML, or reset to default. |
| **Help** | Find workflow explanations and status rules. | Review what each sidebar option does and how invoice states should be handled. |

The sidebar footer also includes a language selector for English/Spanish labels and a dark mode toggle for the current browser session.

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
├── docs/
│   ├── public/              # Sanitized docs safe for a public repository
│   └── private/             # Local/private source material (gitignored)
├── manage.sh                # Dev management script (start/stop/logs)
├── pyproject.toml
└── uv.lock
```

## Invoice Workflow

```
Draft → Sent → Paid
  └── Cancelled
Sent/Overdue → Written Off
```

Only Draft invoices can be cancelled. Sent invoices can be marked Paid or Written Off. Overdue is displayed for Sent invoices after their due date.

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
- [x] Expense tracking with CSV export
- [x] Public/private documentation split
- [ ] Full data import/export workflow for accountant handoff
- [ ] Expanded multi-language UI coverage (EN/ES)
- [ ] LLM integration for voice/natural language invoice creation

## License

MIT
