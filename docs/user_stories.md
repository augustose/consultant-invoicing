# User Stories & Criterios de Aceptación

Este documento define el comportamiento esperado del sistema. Cada historia sigue el formato tradicional y detalla las condiciones técnicas necesarias para su implementación exitosa.

---

## 🟢 Épica: Gestión de Clientes (CRM)

### US-01: Registro de Clientes
**Historia**: Como consultor, quiero poder registrar y gestionar la información de mis clientes para no tener que introducir sus datos en cada factura.
**Criterios de Aceptación:**
- [ ] El sistema debe permitir capturar: Nombre legal, Email, Dirección física y Moneda (USD/CAD).
- [ ] Los datos deben persistir en la tabla `customers` de SQLite.
- [ ] No se permiten clientes con el mismo email o nombre legal duplicado.
- [ ] Debe existir una vista de listado con capacidad de edición y borrado.

---

## 🔵 Épica: Facturación Core (Invoicing)

### US-02: Creación de Factura Manual
**Historia**: Como consultor, quiero crear facturas profesionales para cobrar por mis servicios prestados.
**Criterios de Aceptación:**
- [ ] Debe permitir seleccionar un cliente existente de un menú desplegable.
- [ ] Debe permitir añadir múltiples líneas de detalle (servicio, cantidad, precio unitario).
- [ ] **Lógica**: Subtotal, Impuestos (configurables) y Total deben calcularse en tiempo real.
- [ ] Al guardar, se debe generar un número de factura correlativo (ej: INV-1001).
- [ ] El estado inicial debe ser "Borrador" (Draft).

### US-03: Visualización y Exportación
**Historia**: Como consultor, quiero previsualizar la factura en un formato profesional para asegurar que no hay errores antes de enviarla.
**Criterios de Aceptación:**
- [ ] La previsualización debe seguir la estética de "Wave Apps" vista en los assets.
- [ ] Opción de exportar/imprimir a PDF manteniendo el diseño premium.
- [ ] El PDF debe incluir el logo del consultor (placeholder por ahora) y los datos bancarios para transferencia.

---

## 🕒 Épica: Automatización (Recurring Invoicing)

### US-04: Gestión de Perfiles Recurrentes (Retainers)
**Historia**: Como consultor con clientes bajo contrato mensual, quiero un sistema de facturación recurrente "set-and-forget" que sea extremadamente fácil de configurar y gestionar.
**Criterios de Aceptación:**
- [ ] **Creación Fluida**: Posibilidad de convertir cualquier factura manual existente en una "Plantilla Recurrente" con un solo clic.
- [ ] **Flexibilidad de Frecuencia**: Opciones predefinidas (Semanal, Quincenal, Mensual, Trimestral) y opción de intervalo personalizado (ej: cada X meses).
- [ ] **Modos de Operación**:
    - *Modo Revisión*: El sistema crea la factura en "Borrador" el día programado y notifica para aprobación final.
    - *Modo Piloto Automático*: El sistema crea y marca como "Enviada" automáticamente (ideal para fees fijos).
- [ ] **Visibilidad**: Tablero dedicado donde se vea claramente: Próxima fecha de emisión, monto total recurrente mensual (MRR) y cliente asociado.
- [ ] **Comandos Simples**: Acciones rápidas para: Pausar recurrencia, Omitir el próximo mes, o Emitir ahora mismo (fuera de ciclo).
- [ ] **Historial**: Cada perfil recurrente debe mostrar la lista de facturas que ha generado históricamente.

---

## 💰 Épica: Gestión de Cobros y Pagos

### US-05: Registro de Pagos Recibidos
**Historia**: Como consultor, quiero registrar los pagos recibidos para saber exactamente qué facturas siguen pendientes de cobro.
**Criterios de Aceptación:**
- [ ] Opción de "Registrar Pago" en cualquier factura "Enviada".
- [ ] Soporte para pagos parciales: si el pago es menor al total, la factura cambia a estado "Parcialmente Pagada".
- [ ] El historial de pagos de cada factura debe ser visible.

---

## 📊 Épica: Inteligencia de Negocio

### US-06: Dashboard de Salud Financiera
**Historia**: Como consultor, quiero ver un resumen visual de mi negocio para tomar decisiones financieras rápidas.
**Criterios de Aceptación:**
- [ ] Visualización clara de: Total por cobrar (Overdue + Pending), Cobrado este mes, y Próximos vencimientos.
- [ ] Gráfico simple de ingresos de los últimos 6 meses.
- [ ] Los datos deben extraerse directamente mediante queries SQL a la base de datos SQLite.

---

## 🗺️ Épica: Localización y Cumplimiento (Compliance)

### US-07: Configuración Regional Dinámica
**Historia**: Como consultor, quiero poder configurar mis reglas de impuestos y moneda según mi ubicación (inicialmente Québec, Canadá) para que el sistema se adapte a mi legislación local o a cualquier otra en el futuro.
**Criterios de Aceptación:**
- [ ] **Módulo de Configuración**: Panel para definir Moneda base (CAD, USD, etc.) y Símbolo.
- [ ] **Gestión de Impuestos (Multi-Tax)**: 
    - Posibilidad de activar/desactivar impuestos (ej: TPS y TVQ para Québec).
    - Definición de porcentajes (ej: 5% TPS, 9.975% TVQ).
    - Opción de impuestos "Compuestos" o "Simples".
- [ ] **Identificadores Legales**: Campos para ingresar el NEQ (Numéro d'entreprise du Québec) y números de registro de impuestos (TPS/TVQ) para que aparezcan legalmente en las facturas.

### US-08: Reporte de Impuestos Recaudados
**Historia**: Como consultor en Québec, necesito un reporte que sume exactamente cuánto he recaudado de TPS y TVQ para facilitar mi declaración trimestral o anual al gobierno.
**Criterios de Aceptación:**
- [ ] **Selector de Periodo**: Filtrar por año fiscal o trimestre (Q1, Q2, Q3, Q4).
- [ ] **Desglose de Totales**: Mostrar Base Imponible total, Total TPS recaudado y Total TVQ recaudado por separado.
- [ ] **Exportación Simple**: Botón para copiar estos valores o exportar un resumen en CSV para el contador.

---

## 🏛️ Épica: Contabilidad Profesional (Accounting Core)

### US-09: Plan de Cuentas Estándar (Chart of Accounts)
**Historia**: Como consultor, quiero que el sistema maneje un Plan de Cuentas flexible pero basado en estándares de mercado (como se ve en las imágenes de Wave) para que mi contador pueda entender y auditar mis finanzas.
**Criterios de Aceptación:**
- [ ] **Jerarquía Estándar**: El sistema debe venir pre-configurado con las categorías principales:
    - **Activos (Assets)**: Caja, Cuentas por Cobrar, Cuenta Bancaria (ej: RBC).
    - **Pasivos (Liabilities)**: Impuestos por Pagar (TPS/TVQ), Cuentas por Pagar.
    - **Ingresos (Income)**: Servicios de Consultoría, Ventas de Productos.
    - **Gastos (Expenses)**: Software, Oficina, Viajes, etc.
- [ ] **Flexibilidad**: Permitir al usuario crear sub-cuentas personalizadas dentro de estas categorías.
- [ ] **Asignación Automática**: Al crear una factura, el sistema debe saber automáticamente que el ingreso va a "Consultoría" y el impuesto a "TPS/TVQ Payable".
- [ ] **Conciliación**: Vista de transacciones donde se pueda elegir la "Cuenta" (de dónde sale/entra el dinero) y la "Categoría" (qué tipo de gasto/ingreso es).

---

## 🌐 Épica: Sistema Global (Internationalization & Portability)

### US-10: Multi-language UI Support (i18n)
**Story**: As a consultant, I want the interface to be available in multiple languages (English/Spanish) so I can work in my preferred language while keeping the system globally compatible.
**Acceptance Criteria:**
- [ ] Implement an i18n framework (like `i18next` or a custom lightweight hook).
- [ ] All UI strings (buttons, labels, messages) must be externalized in JSON files.
- [ ] User can switch between English and Spanish from the Settings panel.
- [ ] Default system language should be English.

### US-11: Data Portability (Backup & Accountant Exchange)
**Story**: As a consultant, I want to export my financial data to send to my accountant and import it back if needed.
**Acceptance Criteria:**
- [ ] **Export to JSON/CSV**: Generate a downloadable file with all transactions and chart of accounts.
- [ ] **Database Backup**: Allow downloading the raw `.sqlite` file from the browser's OPFS.
- [ ] **Import Procedure**: Allow loading a previously exported file to restore the system state.
- [ ] **Accountant View**: A simplified export format specifically designed for tax filing.

---

## 🤖 Future-Proofing (AI & MCP Readiness)
- The system will be designed with a clean API/Service layer to eventually act as an **MCP (Model Context Protocol)** server provider. 
- This will allow AI agents to "read and write" invoices directly with the user's permission.

---

## 🛠️ Technical Requirements (For AI Coding Agent)
- **Language**: All code and comments MUST be in English.
- **Persistence**: Synchronize with `sqlite_wasm` in the browser's OPFS.
- **UI/UX**: Premium "Wave Apps" inspiration, Vanilla CSS, and Framer Motion.
