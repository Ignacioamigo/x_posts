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


# 1. Clone the repository
cd predictive_analytics_bot/

# 2. Set up an isolated virtual environment
python -m venv venv
source venv/bin/activate        # Linux/Mac
# venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables (.env)
cp .env.example .env
# You must inject your real credentials into the .env file



# Start the orchestrator
python scheduler.py
