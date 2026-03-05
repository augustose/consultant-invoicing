# Research: AI & Voice Integration

This document analyses the feasibility of integrating advanced AI and voice capabilities into the accounting system.

---

## 1. Voice User Interface (VUI)
- **Technology**: `Web Speech API` (native browser API).
- **Scope**:
    - **Dictation**: Transcribe notes or service descriptions.
    - **Commands**: Execute simple actions (e.g. "Show unpaid invoices").
    - **Feedback**: System voice responses via Text-to-Speech.

## 2. AI Integration (Anthropic or Google)
- **Models**: Claude (Anthropic) or Gemini (Google).
- **Method**: REST API connection using user-provided API keys.
- **Value Flows**:
    - **Entity Extraction**: Convert natural language into structured JSON objects (invoices, clients).
    - **Data Analysis**: Answer complex questions about business financial health.
    - **Content Generation**: Draft collection emails and payment reminders.

## 3. Challenges & Considerations
- **Privacy**: Data must travel to the Anthropic/Google API for processing — this must be transparent to the user.
- **Cost**: API usage has a per-token cost.
- **Connectivity**: Unlike the rest of the system which is "local-first", these features require an internet connection.

## 4. Model Context Protocol (MCP) Readiness
- **Core Idea**: Transform the accounting system into an MCP Server.
- **Benefit**: This allows external AI assistants (like Claude Desktop or custom agents) to connect to your local data.
- **Implementation Strategy**:
    - Centralize data logic in a `DBService` layer.
    - Create a set of "Tools" (functions) that an MCP server can expose (e.g. `create_invoice`, `get_tax_summary`).
    - This turns the app from a simple tool into a platform for your own AI agent.
