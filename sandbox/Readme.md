# 🛠️ Sandbox Directory Guide

This directory serves as an isolated "sandbox" environment to test our approaches and see the big picture before integrating anything into the main Fanoos Lantern Project environment.

## 🎯 What is this folder used for?
We are using this directory as a laboratory. The following items should be pushed here:
* **Web Scraping Codes:** Testing various data extraction tools and storing sample outputs.
* **LLM Configurations:** Testing free API keys, and configuring language models for coding or supervisor agents.
* **Data Processing Pipelines:** Testing Pydantic scripts, key extraction, and data validation before database integration.
* **Database Tests:** Connection scripts and test queries for Qdrant (Vector DB) and PostgreSQL.

## ⚠ Sandbox Rules
1. **No Production Code:** Do not push final, production-ready code directly here. This space is strictly for Trial & Error and Proof of Concept (PoC) scripts.
2. **Use Your Designated Folders:** Do not leave your test scripts scattered in the root of the sandbox directory. Place your files inside the dedicated sub-directory created for your specific task.
3. **Document Your Code:** Inside your specific folder, either include a short text file or use clear code comments to explain exactly what the test does and which task it belongs to.

If you have any questions about how to push your files to this directory, don't hesitate to contact the technical leads.

