# Investigación: Integración de IA y Voz

Este documento analiza la viabilidad de integrar capacidades avanzadas de IA y voz en el sistema de contabilidad.

## 1. Interacción por Voz (VUI)
- **Tecnología**: `Web Speech API` (Nativa del navegador).
- **Alcance**:
    - **Dictado**: Transcribir notas o descripciones de servicios.
    - **Comandos**: Ejecutar acciones simples (ej: "Ver facturas vencidas").
    - **Conversación**: Feedback por voz del sistema (Text-to-Speech).

## 2. Integración con IA (Anthropic o Google)
- **Modelos**: Claude (Anthropic) o Gemini (Google).
- **Método**: Conexión vía API REST con llaves proveídas por el usuario.
- **Flujos de Valor**:
    - **Extracción de Entidades**: Convertir lenguaje natural en objetos JSON (Facturas, Clientes).
    - **Análisis de Datos**: Preguntas complejas sobre la salud financiera del negocio.
    - **Generación de Contenido**: Redacción de correos de cobro y recordatorios.

## 3. Retos y Consideraciones
- **Privacidad**: Los datos deben viajar a la API de Anthropic para ser procesados, lo cual debe ser transparente para el usuario.
- **Costo**: El uso de la API tiene un costo por token (consumo).
- **Conectividad**: A diferencia del resto del sistema que es "local-first", estas funciones requieren internet.

## 5. Model Context Protocol (MCP) Readiness
- **Core Idea**: Transform the accounting system into an MCP Server.
- **Benefit**: This allows external AI assistants (like Claude Desktop or custom agents) to "connect" to your local data.
- **Implementation Strategy**:
    - Centralize data logic in a `DBService`.
    - Create a set of "Tools" (functions) that an MCP server can expose (e.g., `create_invoice`, `get_tax_summary`).
    - This turns the app from a simple tool into a platform for your own AI agent.
