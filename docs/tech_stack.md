# Technology Stack & Architecture

This document defines the final technology stack chosen for the **Consultant Invoicing** system, ensuring a premium, robust, and AI-ready application for independent consultants.

---

## Core — Python Ecosystem
- **Language**: **Python 3.11+**
  - *Rationale*: Preferred for its robustness, ease of use for financial calculations, and native support for AI integration.
- **Package Manager**: **uv**
  - *Rationale*: Extremely fast, modern replacement for pip/poetry. Manages virtual environments and dependencies seamlessly.
- **Frontend/UI Framework**: **NiceGUI** (built on Vue.js and Quasar)
  - *Rationale*: Allows building premium web-based interfaces directly in Python. Eliminates the complexity of maintaining a separate frontend/backend.

## Persistence — Data Layer
- **Database**: **SQLite 3**
  - *Rationale*: Local-first, professional-grade relational database. Data lives in a single file (`data/accounting.db`), making backups trivial.
- **ORM**: **SQLModel** (Pydantic + SQLAlchemy)
  - *Rationale*: Modern data modelling. Guarantees type safety and data integrity, which is critical for accounting. Simplifies complex queries for future AI analysis.

## Utilities
- **Logging**: **Loguru**
  - *Rationale*: Colourful, detailed logs for easy debugging and system health monitoring.
- **Charts**: **Plotly**
  - *Rationale*: Interactive, publication-quality charts for the revenue dashboard.
- **Templates**: **Jinja2**
  - *Rationale*: HTML invoice templates with full CSS control; rendered server-side and printed to PDF via the browser.

## Future-Ready Features
- **AI Integration**: Prepared for **Anthropic (Claude)** or **Google (Gemini)** via REST APIs.
- **MCP Readiness**: Architected to become an **MCP (Model Context Protocol)** server, allowing external AI agents to interact with local accounting data.
- **i18n**: UI strings externalized in a translation dictionary. Default: English. Secondary: Spanish.

## Directory Structure
```text
consultant-invoicing/
├── app/                # Python source code
│   ├── main.py         # All NiceGUI pages and routes
│   ├── database.py     # SQLModel models + DB init
│   ├── template_utils.py
│   └── templates/      # Jinja2 HTML invoice templates
├── docs/               # Architecture decisions and plans
├── data/               # SQLite database (gitignored)
├── manage.sh           # Interactive ZSH management script
└── pyproject.toml      # uv project configuration
```

---
*Last updated: 2026-03-05*
