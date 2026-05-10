"""
Load testing with Locust — simulates 100-1000 concurrent users.

Usage:
    locust -f tests/locustfile.py --host=http://localhost:8000 --users=500 --spawn-rate=50
    Open: http://localhost:8089
"""

from locust import HttpUser, task, between, events
import json
import random


class DashboardUser(HttpUser):
    """Simulates a user browsing the dashboard."""
    wait_time = between(1, 5)

    def on_start(self):
        """Login on user start."""
        resp = self.client.post("/api/login", json={
            "username": "loadtest",
            "password": "loadtest123"
        })
        if resp.status_code == 200:
            self.token = resp.json().get("token", "")
            self.client.headers["X-Session-Token"] = self.token
        else:
            self.token = ""

    @task(10)
    def view_messages(self):
        """Most common action — view announcement feed."""
        page = random.randint(1, 10)
        self.client.get(f"/api/messages?page={page}&per_page=20")

    @task(5)
    def view_message_stats(self):
        self.client.get("/api/messages/stats")

    @task(8)
    def view_pe_analysis(self):
        """View PE analysis with random filters."""
        params = {"page": random.randint(1, 5), "per_page": 20}
        if random.random() > 0.5:
            params["year"] = random.choice(["2025", "2026"])
        if random.random() > 0.5:
            params["quarter"] = random.choice(["Q1", "Q2", "Q3", "Q4"])
        self.client.get("/api/pe_analysis", params=params)

    @task(3)
    def view_pe_filters(self):
        self.client.get("/api/pe_analysis/filters")

    @task(4)
    def view_report_summary(self):
        self.client.get("/api/pe_analysis/report_summary")

    @task(3)
    def view_stocks(self):
        self.client.get("/api/stocks")

    @task(2)
    def view_stock_detail(self):
        symbols = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]
        self.client.get(f"/api/stocks/{random.choice(symbols)}")

    @task(1)
    def view_config(self):
        self.client.get("/api/config/scheduled_fetch")

    @task(1)
    def health_check(self):
        self.client.get("/health")


class WebSocketUser(HttpUser):
    """Simulates WebSocket connections (uses polling fallback for Locust)."""
    wait_time = between(5, 15)

    @task
    def poll_messages(self):
        """Simulate real-time polling (Locust doesn't support WS natively)."""
        self.client.get("/api/messages?page=1&per_page=5")


class HeavyUser(HttpUser):
    """Simulates power users triggering jobs and AI analysis."""
    wait_time = between(10, 30)
    weight = 1  # Much fewer heavy users

    @task(3)
    def trigger_job(self):
        job_types = ["fetch_nse", "fetch_bse", "fetch_quotes"]
        self.client.post(f"/api/jobs/{random.choice(job_types)}/start")

    @task(1)
    def trigger_ai_analysis(self):
        symbols = ["RELIANCE", "TCS", "INFY"]
        self.client.post("/api/jobs/ai_analysis/start", json={
            "symbol": random.choice(symbols)
        })
