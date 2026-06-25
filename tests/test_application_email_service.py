import unittest

from app.services.application_email_service import ApplicationEmailService


class ApplicationEmailServiceTest(unittest.TestCase):
    def test_candidate_values_are_escaped(self):
        service = ApplicationEmailService()
        html = service._confirmation_html(
            {
                "firstName": "<script>",
                "lastName": "Test",
                "email": "test@example.com",
                "companyName": "Acme",
                "sector": "Tech",
                "productName": "Produit",
            }
        )

        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()
