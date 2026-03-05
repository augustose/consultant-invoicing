# Strategic Action Plan

This plan focuses on design validation before technical execution.

---

## Phase 0: Definition & Design — COMPLETED
- [x] Define the full feature scope (see `docs/funcionalidades.md`).
- [x] Validate user stories (see `docs/user_stories.md`).
- [x] Confirm data flow and technical architecture (see `docs/decisiones.md`).
- [x] Organize directory structure (docs, app, assets, examples, data).

## Phase 1: Technical Foundation — COMPLETED
- [x] Create interactive management script (`manage.sh`).
- [x] Configure **Python + uv** environment and **NiceGUI**.
- [x] Implement database schema with **SQLModel** (SQLite).
- [x] Define the standard **Chart of Accounts** for Québec.

## Phase 2: Core Invoicing & CRM — COMPLETED
- [x] Customer CRUD with inline editing.
- [x] Services CRUD with inline editing and usage guards.
- [x] Accounts CRUD with system account protection.
- [x] Dynamic invoice creation with line items.
- [x] Automatic Québec tax calculation (TPS/TVQ).
- [x] Invoice workflow: Draft → Sent → Paid → Cancelled.
- [x] HTML invoice template (Jinja2) with browser print-to-PDF.

## Phase 3: Recurring Invoices & Automation — COMPLETED
- [x] Recurring profile database model.
- [x] Subscriptions & retainers management view.
- [x] Background invoicing engine (auto-drafts).
- [x] Dashboard with real-time metrics and monthly revenue chart (Plotly).

## Phase 4: Reports & Polish — IN PROGRESS
- [x] Sales report with preset and custom date ranges.
- [x] Tax report (TPS/TVQ breakdown per invoice).
- [ ] Data import/export module (CSV/JSON for accountant).
- [ ] Multi-language i18n completion (EN/ES).
- [ ] Smooth animations and transitions.

## Phase 5: AI & Voice — PLANNED
- [ ] LLM integration (Anthropic Claude or Google Gemini).
- [ ] Voice command processing for invoice creation.
- [ ] Natural language queries over accounting data.
- [ ] MCP server integration.

---

### Current Status
Phases 0–3 complete. Phase 4 reports are done. Remaining Phase 4 work: data export and i18n polish.
