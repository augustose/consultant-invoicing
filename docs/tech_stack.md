# Technology Stack & Architecture

This document defines the final technological stack chosen for the **Accounting AI** system, ensuring a premium, robust, and AI-ready application for independent consultants.

## 核心 (Core) - Python Ecosystem
- **Language**: **Python 3.11+**
  - *Rationale*: Preferred for its robustness, ease of use for financial calculations, and native support for AI integration.
- **Package Manager**: **uv**
  - *Rationale*: Extremely fast, modern replacement for pip/poetry. Manages virtual environments and dependencies seamlessly.
- **Frontend/UI Framework**: **NiceGUI** (built on Vue.js and Tailwind CSS)
  - *Rationale*: Allows building "Premium" web-based interfaces directly in Python. Eliminates the complexity of separating frontend/backend.

## 持久化 (Persistence) - Data Layer
- **Database**: **SQLite 3**
  - *Rationale*: Local-first, professional-grade relational database. Data lives in a single file (`data/accounting.db`), making backups easy.
- **ORM**: **SQLModel** (Pydantic + SQLAlchemy)
  - *Rationale*: Modern data modeling. Guarantees type safety and data integrity, which is critical for accounting. It simplifies complex queries for future AI analysis.

## 辅助工具 (Utilities)
- **Logging**: **Loguru**
  - *Rationale*: Provides colorful, detailed logs for easier debugging and system health monitoring.
- **Data Analysis**: **Pandas**
  - *Rationale*: The industry standard for financial reporting and tax summary calculations.
- **Visuals**: **Lucide Icons** & **Framer Motion** (via NiceGUI/Quasar)
  - *Rationale*: To achieve the sleek, micro-animated aesthetic inspired by Wave Apps.

## 未来规划 (Future-Ready Features)
- **AI Integration**: Prepared for **Anthropic (Claude)** or **Google (Gemini)** via REST APIs.
- **Extensibility**: Architected to be **MCP (Model Context Protocol)** compatible, allowing external AI agents to interact with the local database.
- **i18n**: Fully translatable UI strings stored in external configurations (Default: English, Secondary: Spanish).

## Structure Summary
```text
/
├── app/            # Source code (Python)
├── docs/           # Documentation and Decisions
├── assets/         # Reference images and logos
├── data/           # SQLite database file
├── examples/       # Sample PDFs and exports
├── manage.sh       # Interactive ZSH management script
└── pyproject.toml  # UV project configuration
```

---
*Last Updated: 2026-03-04*
