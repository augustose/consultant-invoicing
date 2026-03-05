# Registro de Decisiones

Este documento registra las decisiones arquitectónicas y de diseño tomadas durante el desarrollo del Sistema de Contabilidad y Facturación para Consultores Independientes.

## 2026-03-04: Definición Inicial del Stack y Arquitectura

### 1. Technology & Language Standards
**Decision**: Use **Python 3.11+** with **NiceGUI**, managed by **uv**. All code, comments, variable names, and technical documentation will be in **English**.
**Reason**: Python is the user's preference and provides the most robust path for AI integration (Anthropic/Google/MCP). **uv** ensures extremely fast and reproducible environment management. NiceGUI allows for modern, premium web-based UI while keeping the backend logic in pure Python.

### 2. Data Storage & ORM
**Decision**: Use **SQLite 3** with **SQLModel**.
**Reason**: SQLModel simplifies database interactions by treating tables as Python classes. It provides auto-completion and type-safety, which is crucial for financial data integrity. It's the most robust way to manage a complex Chart of Accounts.

### 3. Estética y Diseño
**Decisión**: Inspirado en **Wave Apps** pero con toques de **Glassmorphism** y micro-animaciones.
**Razón**: Las imágenes de referencia muestran Wave Apps. Queremos superar esa estética con un diseño más moderno, limpio y "Premium" que use una paleta de colores sofisticada (Deep Blue, Slate, y acentos esmeralda).

### 4. Iconografía y Animaciones
**Decisión**: Usar **Lucide React** para iconos y **Framer Motion** para transiciones.
**Razón**: Lucide ofrece una estética de trazo fino que se siente muy moderna y "Premium". Framer Motion permite animaciones fluidas y naturales que mejoran la experiencia de usuario (UX).

### 5. Gestión y Mantenimiento
**Decisión**: Script interactivo `manage.sh` en ZSH.
**Razón**: Facilita la experiencia de usuario para tareas técnicas (Start, Backup, Docs) con un solo toque de tecla, manteniendo el ambiente de desarrollo ordenado.

### 6. Estructura de Datos y Motor Contable
**Decisión**: Entidades principales integradas: `Invoices`, `Payments`, `Customers`, `Products`, y un `Chart of Accounts` basado en categorías de Activos, Pasivos, Ingresos y Gastos.
**Razón**: Basado en las funcionalidades de Wave (vistas en las imágenes), el sistema debe permitir la categorización de transacciones para reportes contables legibles por profesionales.

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
**Reason**: The `data/` folder contains the SQLite database (`accounting.db`), generated PDFs, exported files, and custom invoice templates — all of which are **private user data** that must never be pushed to a public repository. The `.gitkeep` ensures the directory exists after a fresh clone.

**Affected files**:
- `.gitignore` — changed from individual patterns (`data/*.db`, `data/*.sqlite`, `data/exports/`) to a blanket `data/*` with `!data/.gitkeep` exception.
- `data/.gitkeep` — created as an empty placeholder.

### 10. Idempotent Database Auto-Initialization on Startup
**Decision**: `main.py` now calls `create_db_and_tables()` and `seed_initial_data()` on every application startup.
**Reason**: Previously, the database was only initialized when running `database.py` directly as a script. This meant a fresh clone would crash on startup because no database existed. The auto-init is **idempotent** — it's safe to run on every startup:
- `os.makedirs("data", exist_ok=True)` → creates the folder only if missing.
- `create_db_and_tables()` → SQLModel's `create_all` skips tables that already exist.
- `seed_initial_data()` → checks if records exist before inserting defaults (guard clause on line 122-124 of `database.py`).

**Result**: Existing data is never overwritten. The init is a no-op on normal runs but acts as a safety net if the DB is missing.

### 11. Bug Fix — SyntaxError in `template_utils.py`
**Decision**: Fixed indentation in `TemplateManager.render_invoice()`.
**Problem**: The code between `env.get_template()` (line 44) and `template.render()` (line 84) — including the `items_html` builder and `context` dictionary — was accidentally de-indented, breaking the `try/except` block structure. Python raised: `SyntaxError: expected 'except' or 'finally' block` at line 47.
**Fix**: Re-indented lines 46-83 to be properly inside the `try` block, restoring the intended error handling flow.

