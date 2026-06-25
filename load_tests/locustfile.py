"""Non-destructive load scenarios for the public backend."""

import uuid

from locust import HttpUser, between, task


class PublicReadUser(HttpUser):
    wait_time = between(0.2, 1.0)

    def on_start(self):
        self.load_test_email = (
            f"load-{uuid.uuid4().hex}@example.invalid"
        )

    @task(5)
    def health(self):
        with self.client.get(
            "/health",
            name="GET /health",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(
                    f"Statut inattendu: {response.status_code}"
                )
            elif response.json().get("status") != "healthy":
                response.failure("Réponse health invalide")

    @task(3)
    def upcoming_events(self):
        self.client.get(
            "/api/events/upcoming",
            name="GET /api/events/upcoming",
        )

    @task(2)
    def public_events(self):
        self.client.get(
            "/api/events/",
            name="GET /api/events",
        )

    @task(1)
    def startup_email_availability(self):
        self.client.get(
            "/api/startup/check-email",
            params={"email": self.load_test_email},
            name="GET /api/startup/check-email",
        )
