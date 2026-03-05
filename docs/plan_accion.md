# Plan de Acción Estratégico - Accounting AI

Este plan se centra en la definición y validación antes de la ejecución técnica.

## Fase 0: Definición y Diseño %completed: 100%
- [x] Definir el alcance total de las funcionalidades (ver `docs/funcionalidades.md`).
- [x] Validar las User Stories con el usuario (ver `docs/user_stories.md`).
- [x] Confirmar el flujo de datos y arquitectura técnica (ver `docs/decisiones.md`).
- [x] Organizar estructura de directorios (docs, app, assets, examples, data).

## Fase 1: Cimentación Técnica %completed: 100%
- [x] Crear script de mantenimiento interactivo (`manage.sh`).
- [x] Configurar entorno **Python + uv** y **NiceGUI**.
- [x] Implementar esquema de base de datos con **SQLModel** (SQLite).
- [x] Definir el **Plan de Cuentas Estándar** para Québec.

## Phase 2: Core Invoicing & CRM (COMPLETED)
- [x] CRUD Customers (NiceGUI Modals)
- [x] CRUD Services/Products
- [x] Dynamic Invoice Creation (Line Items)
- [x] Automatic Quebec Tax calculation (TPS/TVQ)
- [x] Dynamic Dashboard with real metrics

## Phase 3: Recurring Invoices & Automation (COMPLETED)
- [x] Recurring Profile Database Model
- [x] Subscriptions & Retainers management view
- [x] Background Invoicing Engine (Auto-drafts)
- [x] "Mark as Paid" and real-time dashboard updates

## Fase 4: Pulido Premium & Portabilidad
- [ ] Soporte Multi-idioma (i18n English/Spanish).
- [ ] Módulo de Importación/Exportación de datos.
- [ ] Animaciones y transiciones fluidas.
- [ ] Dashboard analítico y reportes.

## Fase 5: Inteligencia y Voz (Segunda Etapa)
- [ ] Integración con LLM (Anthropic Claude o Google Gemini).
- [ ] Procesamiento de comandos de voz para creación de facturas.
- [ ] Consultas en lenguaje natural sobre datos contables.

---
### Estado Actual:
Estamos en la **Fase 2**. Hemos inicializado la base de datos con el Plan de Cuentas y ya tenemos la gestión de Clientes y Servicios funcionando. El siguiente paso es el motor de facturación.
