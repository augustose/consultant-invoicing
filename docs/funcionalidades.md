# Requerimientos Funcionales Detallados

Este documento detalla todas las funcionalidades propuestas para el sistema, divididas por módulos. Por favor revisa y comenta para realizar ajustes antes de iniciar cualquier desarrollo.

## 1. Módulo de Clientes (CRM Simple)
- **Gestión de Perfiles**: Nombre, Email de contacto, Dirección de facturación, Moneda predeterminada.
- **Historial de Facturación**: Lista de todas las facturas enviadas a este cliente con su estado.
- **Preferencias**: Idioma de la factura, términos de pago predeterminados (Net 15, Net 30).

## 2. Módulo de Servicios/Productos
- **Catálogo**: Nombre del servicio, descripción predeterminada, precio unitario.
- **Impuestos por Item**: Poder definir qué impuestos aplican a cada servicio (GST, QST, etc.).

## 3. Módulo de Facturación (Invoicing)
- **Generador de Facturas**:
    - Selección de cliente (autocompletado).
    - Agregado dinámico de líneas de detalle.
    - Cálculo automático de subtotal e impuestos.
    - Personalización de notas y términos por factura.
- **Gestión de Estados**: Borrador -> Enviada -> Pagada / Vencida.
- **Exportación**: Generación de PDF profesional para enviar al cliente.

## 4. Facturación Recurrente
- **Configuración de Perfiles Recurrentes**: 
    - Frecuencia (Semanal, Mensual, Trimestral).
    - Fecha de inicio y fin.
    - Generación automática de borrador o envío automático (a decidir).

## 5. Seguimiento de Pagos
- **Registro de Pagos**: Fecha de pago, método (Transferencia, Efectivo, etc.), monto recibido.
- **Pagos Parciales**: Soporte para que una factura reciba múltiples abonos.

## 6. Dashboard e Informes
- **Dashboard Visual**: Gráficos de ingresos mensuales, monto total por cobrar (Accounts Receivable).
- **Reportes**: Resumen para declaración de impuestos (ingresos totales vs impuestos recaudados).

## 7. Futuro (Segunda Etapa: Inteligencia Artificial)
- **Asistente Virtual**: Integración con Anthropic/Google para dictado y creación de facturas mediante lenguaje natural.
- **Análisis Predictivo de Flujo de Caja**.

---
*¿Alguna funcionalidad que falte o que debamos ajustar?*
