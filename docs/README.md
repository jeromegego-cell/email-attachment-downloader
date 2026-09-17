# Production Documentation Suite

Welcome to the documentation suite for the Enterprise Email Ingestion Gateway. Below is an organized, categorized index of all system architecture guides, operational manuals, and project specifications.

---

## 📚 Core Operational & Developer Guides

| Document | Description | Target Audience |
| :--- | :--- | :--- |
| [**System Architecture Guide**](./architecture_guide.md) | High-level system topology, module breakdown, multi-layer defensive pipeline, and Content-Addressable Storage (CAS). | Architects & Developers |
| [**Configuration Reference**](./configuration_reference.md) | Full reference manual for `config.yaml`, Pydantic models, nested environment variables (`APP_*`), and connector credentials. | DevOps & System Administrators |
| [**Developer Onboarding Guide**](./developer_onboarding_guide.md) | Quickstart guide for setting up the development environment, running test suites, adding custom plugins, and creating connectors. | Software Engineers |
| [**Security Operations Manual**](./security_operations_manual.md) | Quarantine vault management, threat classification, zero-byte/LNK/macro isolation, and incident triage procedures. | Security & Operations Teams |

---

## 📋 Architectural Specifications & Decision Records

| Document | Description | Category |
| :--- | :--- | :--- |
| [**Master Plan & Specification**](./Enterprise_Email_Ingestion_Gateway_Master_Plan.md) | Complete end-to-end master plan, requirement mapping, and production implementation roadmap. | Master Specification |
| [**System Specification & Architecture**](./system_specification_and_architecture.md) | Detailed component contracts, database schemas, and message envelope data models. | Specifications |
| [**Decision Log & Milestones**](./master_project_specification_and_decision_log.md) | Architecture Decision Records (ADRs), trade-off evaluations, and milestone changelogs. | Decision Records |
| [**Production Architecture Report**](./production_architecture_report.md) | Deep analysis of high-throughput ingestion, backpressure, failure recovery, and ACID consistency. | Architecture Report |
| [**Folder Remote Control Architecture**](./folder_remote_control_specification_report.md) | Specification of the Zero-UI mailbox folder remote control, one-time pass semantic, and trade-off analysis. | Architecture Report |
| [**Industrial Research & Refinement**](./industrial_research_and_refinement_report.md) | Open-source ecosystem analysis, library selection rationale (`pathvalidate`, `rapidfuzz`, `tenacity`). | Research & Evaluation |
| [**Executive Briefing for Leadership**](./executive_report_for_leadership.md) | Executive briefing memo, business ROI, Zero-UI one-time pass analysis, and pilot proposal ready to email to leadership. | Executive Briefing |
| [**Session Handover Summary**](./session_handover_summary.md) | Consolidated project milestones, implemented fixes, and operational state summary. | Handover & Status |
