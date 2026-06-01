# 📊 Automated Sports Analytics & Prediction Pipeline

An automated system for data ingestion, AI-driven probabilistic modeling, and alert distribution. Currently configured to analyze professional **PDC Darts** and **Table Tennis** leagues.

This project demonstrates the implementation of an end-to-end ETL (Extract, Transform, Load) pipeline: it extracts real-time sports statistics, leverages the Gemini API (LLM) to estimate event probabilities, detects market inefficiencies by comparing them against consensus odds, and asynchronously distributes alerts via third-party API integrations (**Telegram** and **X/Twitter**).

---

## 🏗️ System Architecture (Data Pipeline)

The data flow is designed to be modular, separating ingestion, analysis, and distribution:

```text
[Raw Data Sources]
flashscore.com          dartsdata.co.uk
      │                 tabletennis.guide
      │                        │
      ▼                        ▼
 scraper.py             scraper.py
 (Data Ingestion)       (Data Ingestion)
      │                        │
      └──────────┬─────────────┘
                 │
           analyzer.py ◄── Gemini API (NLP Processing & Probability Estimation)
                 │
           odds_scraper.py ◄── oddsportal.com (Market Consensus)
                 │
           detect_value() ◄── Mathematical Rules Engine (Expected Value > 4%)
                 │
           publisher.py (Automated Alerts)
           ├── Telegram API (Webhooks / Direct Messaging)
           └── X/Twitter API (Rate-limiting handling & Message Queuing)
```

**Key Design Principle:** The LLM acts solely as a statistical inference engine. Final decisions are executed by a deterministic `detect_value()` algorithm based on transparent mathematical rules, ensuring strict control over AI hallucinations.

---

## 🚀 Core Technologies & Skills

* **Python 3.11+**: Primary language for the pipeline.
* **Web Scraping & DOM Parsing**: Dynamic data extraction bypassing anti-bot mechanisms.
* **LLM Integration**: Prompt engineering and JSON response parsing with Google AI Studio (Gemini).
* **Automation & Cron Jobs**: Periodic task orchestration (`scheduler.py`).
* **REST API Integration**: Secure communication with Telegram and X/Twitter.

---

## 🛠️ Local Installation & Deployment

```bash
# 1. Clone the repository
cd predictive_analytics_bot/

# 2. Set up an isolated virtual environment
python -m venv venv
source venv/bin/activate
```
