# Strategic Action Plan

This plan tracks the public product roadmap for Consultant Invoicing.

## Phase 0: Definition and Design - Complete

- [x] Define feature scope in [features.md](features.md).
- [x] Validate user stories in [user-stories.md](user-stories.md).
- [x] Capture architecture decisions in [decisions.md](decisions.md).
- [x] Separate public documentation from private/local source material.

## Phase 1: Technical Foundation - Complete

- [x] Configure Python, uv, NiceGUI, and SQLModel.
- [x] Implement local SQLite persistence.
- [x] Add idempotent database initialization on startup.
- [x] Create a default Quebec-friendly chart of accounts.
- [x] Add management scripts for start, stop, logs, backups, and docs.

## Phase 2: Core Invoicing and CRM - Complete

- [x] Customer management.
- [x] Service catalog management.
- [x] Account management with system account protection.
- [x] Invoice creation with line items.
- [x] Sequential numeric invoice numbering.
- [x] Quebec TPS/TVQ calculation.
- [x] Invoice preview and PDF download.
- [x] Custom HTML invoice templates.

## Phase 3: Operations - Complete

- [x] Dashboard with invoice totals, client count, recent invoices, and revenue chart.
- [x] Recurring profile model and background recurring invoice generation.
- [x] Subscription page for recurring profile visibility.
- [x] Expense tracking linked to the chart of accounts.
- [x] Expense CSV export.

## Phase 4: Reporting and Polish - In Progress

- [x] Sales summary report.
- [x] Monthly revenue trend report.
- [x] TPS/TVQ collected report.
- [x] Income by customer report.
- [x] Aged receivables report.
- [x] In-app Help page explaining sidebar options and invoice workflow.
- [ ] Full CSV export coverage for accountant handoff.
- [ ] Import/restore workflow from exported data.
- [ ] Broader Spanish translation coverage.

## Phase 5: AI and Voice - Planned

- [ ] Voice command processing.
- [ ] Natural-language invoice creation.
- [ ] Natural-language questions over accounting data.
- [ ] Optional MCP server integration.

## Current Status

The app is usable for local invoicing, customer/service/account maintenance, expense tracking, invoice templates, and core reports. The next practical product work is broader import/export support and recurring profile management UI.
