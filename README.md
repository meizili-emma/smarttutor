# SmartTutor

A modular LLM pipeline for **academic question answering under ambiguous and adversarial inputs**.

---

## 🎯 What is this?

SmartTutor is not a standard chatbot.

It is a structured system that separates:
- intention identification  
- decision making  
- task formalisation  
- question answering  
- user-facing explanation  

to improve:
- reliability  
- transparency  
- failure handling  

---
## 🧪 Adversarial Test Cases


---
## 🧩 Module Design

### 1. Interpret
- Identifies the intention of the input  
- Detects structure (e.g., conditions, tasks, context)

### 2. Policy
- Decides how each part of the input should be handled  
- Possible actions:
  - accept
  - transform
  - abstract
  - reject
  - clarify  

### 3. Normalize
- Converts the input into a clean academic problem  
- Removes:
  - invalid constraints  
  - unsupported conditions  
  - external dependencies  

### 4. Solver
- Solves only the normalized task  
- Enforces:
  - no external knowledge injection  
  - symbolic reasoning when information is missing  

### 5. Assemble
- Explains adjustments (if any)  
- Restates the task clearly  
- Presents the final answer in a readable way  

---

##  Design Principles

SmartTutor enforces the following principles:

- **Task ≠ Purpose**  
  User intent does not override academic correctness  

- **Recover academic tasks whenever possible**  

- **No hidden constants**  
  Do not inject external knowledge  

- **Symbolic reasoning for missing information**  

- **Conditions must be evaluable to be used**  

- **Transparency**  
  Explain transformations and decisions when needed  

## 🧠 Memory Design

SmartTutor maintains a lightweight memory mechanism to support basic conversational continuity and future extensions.

### Current Design

The memory system stores:

- **Recent turns**  
  A short window of recent user–assistant interactions for local context.

- **Session summary**  
  A compressed summary of the conversation to retain high-level information.

- **Taught topics**  
  Extracted topics that have been covered during the session.

---

### Design Goals

The memory mechanism is designed to:

- Maintain **context across turns**  
- Avoid unbounded context growth  
- Support **topic tracking and summarization**  
- Provide a foundation for more advanced memory systems  

---

### Key Principles

- **Selective storage**  
  Only meaningful and valid responses are stored.

- **Summarization over raw logging**  
  The system prefers storing compressed summaries instead of full transcripts.

- **Separation from reasoning**  
  Memory is used for context, not as a source of truth for solving tasks.

---
## 🚀 Quick Start

```bash
# 1. Create environment
conda env create -f environment.yaml
conda activate smarttutor

# 2. Configure environment variables
cp .env.example .env

# Edit .env and add your API key:
# OPENAI_API_KEY=your_api_key_here
# OPENAI_MODEL=gpt-4o-mini

# 3. Run the application
streamlit run app.py

```
In the UI, you can:
- select the model to use
- toggle debug mode to inspect intermediate pipeline outputs. 


## ⚠️ Limitations

- **Prompt-based control**  
  The system relies on LLM prompts for all modules (policy, normalization, etc.), so behavior may vary across runs.

- **No formal guarantees**  
  Constraints (e.g., no external knowledge injection) are enforced heuristically and are not formally verified.

- **Limited domain scope**  
  Currently supports math, history, and conversation summarization only.

- **Heuristic decision-making**  
  The policy module is rule- and prompt-based rather than learned, which may lead to edge-case misclassification.

- **No quantitative evaluation yet**  
  Evaluation is based on curated examples rather than standardized benchmarks or metrics.

- **Not a full tutoring system**  
  The system focuses on robustness and reasoning control, not pedagogy (e.g., no personalization or adaptive teaching).

- **Memory is **not deeply integrated** into reasoning yet  
- **Topic extraction is **heuristic and approximate**  
- **No long-term retrieval or semantic search  
