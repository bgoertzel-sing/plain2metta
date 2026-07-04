import unittest

from specatom_hs.backends.petta import emit_reified_atoms
from specatom_hs.passes import compile_source
from specatom_hs.schema import CheckStatus, Role


class SecurityPrivacyValidationTests(unittest.TestCase):
    def test_secret_pii_access_and_delete_mentions_become_blocking_questions(self):
        doc = compile_source(
            "***functional specifications***\n"
            "- Store API token and password for the integration.\n"
            "- Collect user email address and phone number for support.\n"
            "- Admin users can access account records.\n"
            "- Delete records from the database on request.\n",
            "security-privacy-gaps.plain",
        )

        review = next(obj for obj in doc.objects if ("SecurityPrivacyReview", obj.id) in obj.facts)
        for property_name in {
            "security-secrets-handling-reviewed",
            "security-secret-log-exposure-reviewed",
            "privacy-pii-handling-reviewed",
            "privacy-data-classification-declared",
            "security-access-boundary-declared",
            "security-privilege-escalation-reviewed",
            "security-destructive-action-safety-reviewed",
        }:
            check = next(c for c in doc.checks if c.property == property_name and c.target_id == review.id)
            self.assertEqual(check.status, CheckStatus.UNKNOWN, property_name)
            self.assertTrue(
                any(
                    ("MissingSecurityPrivacyEvidence", obj.id, property_name) in obj.facts
                    and any(fact == ("Blocks", obj.id, check.obligation_id) for fact in obj.facts)
                    for obj in doc.objects
                    if obj.role == Role.QUESTION_OBJECT
                ),
                property_name,
            )

        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn(f"(SecurityPrivacyReview {review.id})", atoms)
        self.assertTrue(any(atom.startswith("(MissingSecurityPrivacyEvidence") for atom in atoms))
        self.assertFalse(any("MissingSecurityPrivacyEvidence" in refusal.reason for refusal in refusals))

    def test_explicit_security_privacy_controls_pass_keyword_review(self):
        doc = compile_source(
            "***functional specifications***\n"
            "- Store API tokens in a secret manager; tokens are redacted from logs and not hard-coded.\n"
            "- Collect user email address classified as restricted data with consent, data minimization, retention limits, and encryption.\n"
            "- Use RBAC least privilege access control for admin-only account records.\n"
            "- Delete records only after confirmation with audit log and rollback backup.\n",
            "security-privacy-pass.plain",
        )

        for property_name in {
            "security-secrets-handling-reviewed",
            "security-secret-log-exposure-reviewed",
            "privacy-pii-handling-reviewed",
            "privacy-data-classification-declared",
            "security-access-boundary-declared",
            "security-privilege-escalation-reviewed",
            "security-destructive-action-safety-reviewed",
        }:
            self.assertTrue(any(c.property == property_name and c.status == CheckStatus.PASS for c in doc.checks), property_name)


if __name__ == "__main__":
    unittest.main()
