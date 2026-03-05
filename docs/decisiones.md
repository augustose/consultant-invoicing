# Decision Log

This document records the architectural and design decisions made during development of the Accounting & Invoicing System for Independent Consultants.

---

## 2026-03-04: Initial Stack & Architecture Decisions

### 1. Technology & Language Standards
**Decision**: Use **Python 3.11+** with **NiceGUI**, managed by **uv**. All code, comments, variable names, and technical documentation will be in **English**.
**Reason**: Python is the user's preference and provides the most robust path for AI integration (Anthropic/Google/MCP). **uv** ensures extremely fast and reproducible environment management. NiceGUI allows for modern, premium web-based UI while keeping the backend logic in pure Python.

### 2. Data Storage & ORM
**Decision**: Use **SQLite 3** with **SQLModel**.
**Reason**: SQLModel simplifies database interactions by treating tables as Python classes. It provides auto-completion and type-safety, which is crucial for financial data integrity. It's the most robust way to manage a complex Chart of Accounts.

### 3. Visual Design & Aesthetics
**Decision**: Inspired by **Wave Apps** with touches of glassmorphism and micro-animations.
**Reason**: The reference images show Wave Apps. We want to surpass that aesthetic with a more modern, clean, and "premium" design using a sophisticated colour palette (deep blue, slate, emerald accents).

### 4. Iconography & Animations
**Decision**: Use **Material Icons** (via NiceGUI/Quasar) for icons and CSS transitions for animations.
**Reason**: Material Icons provide a clean, modern look that integrates natively with NiceGUI. CSS transitions are lightweight and performant without additional dependencies.

### 5. Dev Management Script
**Decision**: Interactive `manage.sh` script in ZSH.
**Reason**: Simplifies the developer/user experience for common tasks (Start, Backup, Logs, Docs) with a single keypress, keeping the environment clean and well-organized.

### 6. Data Model & Accounting Engine
**Decision**: Core entities: `Invoice`, `Customer`, `Service`, `Account` (Chart of Accounts), `RecurringProfile`, and `CompanySettings`.
**Reason**: Based on Wave Apps functionality (seen in the reference images), the system must allow transaction categorization for professional accounting reports readable by accountants.

### 7. Extensibility & Path to AI (MCP)
**Decision**: Architecture follows a "Local-First" approach with a clear separation between the Data Layer (SQLite) and the UI.
**Reason**: This prepares the system for a future **MCP (Model Context Protocol) Server** integration. By having a clean SQLite schema, an AI agent will be able to interface with the database directly or through a well-defined API in the future.

### 8. Data Portability
**Decision**: Import/Export feature using JSON and/or SQLite file sharing.
**Reason**: To allow data exchange with accountants and ensure the user owns their data.

---

## 2026-03-05: Data Privacy, DB Auto-Init & Bug Fixes

### 9. Data Privacy — Exclude All User Data from Git
**Decision**: The entire `data/` directory is excluded from version control via `.gitignore` (`data/*`), with only a `data/.gitkeep` file tracked to preserve the directory structure.
**Reason**: The `data/` folder contains the SQLite database (`accounting.db`), exported files, and custom invoice templates — all of which are **private user data** that must never be pushed to a public repository. The `.gitkeep` ensures the directory exists after a fresh clone.

**Affected files**:
- `.gitignore` — changed from individual patterns to a blanket `data/*` with `!data/.gitkeep` exception.
- `data/.gitkeep` — created as an empty placeholder.

### 10. Idempotent Database Auto-Initialization on Startup
**Decision**: `main.py` calls `create_db_and_tables()` and `seed_initial_data()` on every application startup.
**Reason**: Previously, the database was only initialized when running `database.py` directly. A fresh clone would crash on startup because no database existed. The auto-init is **idempotent** — safe to run on every startup:
- `os.makedirs("data", exist_ok=True)` → creates the folder only if missing.
- `create_db_and_tables()` → SQLModel's `create_all` skips tables that already exist.
- `seed_initial_data()` → checks if records exist before inserting defaults.

**Result**: Existing data is never overwritten. The init is a no-op on normal runs but acts as a safety net if the DB is missing.

### 11. Bug Fix — PDF Generation Removed
**Decision**: Removed ReportLab PDF generation entirely. PDF export now uses browser native print-to-PDF via the `/preview/{id}` HTML route.
**Reason**: ReportLab added complexity and a heavy dependency for functionality the browser already provides natively. The Jinja2 HTML template approach is more flexible and produces better-looking output.

### 12. Invoice Workflow Simplification
**Decision**: Invoice statuses are **Draft → Sent → Paid → Cancelled**. Removed "Overdue" as a status.
**Reason**: "Overdue" was a derived state (date-based), not a user-driven action. The simplified workflow maps directly to consultant actions: create a draft, send it, mark it paid, or cancel it.
