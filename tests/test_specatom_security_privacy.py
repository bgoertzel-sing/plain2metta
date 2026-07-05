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
            "- Admin users login and can access account records.\n"
            "- Delete records from the database on request.\n",
            "security-privacy-gaps.plain",
        )

        review = next(obj for obj in doc.objects if ("SecurityPrivacyReview", obj.id) in obj.facts)
        for property_name in {
            "security-secrets-handling-reviewed",
            "security-secret-log-exposure-reviewed",
            "security-credential-rotation-reviewed",
            "privacy-pii-handling-reviewed",
            "privacy-data-classification-declared",
            "privacy-encryption-scope-reviewed",
            "privacy-lawful-basis-reviewed",
            "privacy-retention-deletion-reviewed",
            "privacy-purpose-limitation-reviewed",
            "privacy-data-subject-rights-reviewed",
            "privacy-pii-access-audit-reviewed",
            "privacy-incident-response-reviewed",
            "security-access-boundary-declared",
            "security-privilege-escalation-reviewed",
            "security-session-management-reviewed",
            "security-auth-abuse-protection-reviewed",
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

    def test_secret_without_rotation_or_revocation_stays_unknown(self):
        doc = compile_source(
            "***functional specifications***\n"
            "- Store API token in a secret manager; token is redacted from logs and not hard-coded.\n",
            "secret-rotation-gap.plain",
        )

        check = next(c for c in doc.checks if c.property == "security-credential-rotation-reviewed")
        self.assertEqual(check.status, CheckStatus.UNKNOWN)
        self.assertTrue(
            any(
                ("MissingSecurityPrivacyEvidence", obj.id, "security-credential-rotation-reviewed") in obj.facts
                and ("Blocks", obj.id, check.obligation_id) in obj.facts
                for obj in doc.objects
                if obj.role == Role.QUESTION_OBJECT
            )
        )

    def test_pii_encryption_without_retention_or_deletion_stays_unknown(self):
        doc = compile_source(
            "***functional specifications***\n"
            "- Collect user email address classified as restricted data with consent and encryption.\n",
            "privacy-retention-gap.plain",
        )

        check = next(c for c in doc.checks if c.property == "privacy-retention-deletion-reviewed")
        self.assertEqual(check.status, CheckStatus.UNKNOWN)
        self.assertTrue(
            any(
                ("MissingSecurityPrivacyEvidence", obj.id, "privacy-retention-deletion-reviewed") in obj.facts
                and ("Blocks", obj.id, check.obligation_id) in obj.facts
                for obj in doc.objects
                if obj.role == Role.QUESTION_OBJECT
            )
        )

    def test_pii_encryption_without_lawful_basis_stays_unknown(self):
        doc = compile_source(
            "***functional specifications***\n"
            "- Collect user email address classified as restricted data with retention limits and encryption at rest.\n",
            "privacy-lawful-basis-gap.plain",
        )

        check = next(c for c in doc.checks if c.property == "privacy-lawful-basis-reviewed")
        self.assertEqual(check.status, CheckStatus.UNKNOWN)
        self.assertTrue(
            any(
                ("MissingSecurityPrivacyEvidence", obj.id, "privacy-lawful-basis-reviewed") in obj.facts
                and ("Blocks", obj.id, check.obligation_id) in obj.facts
                for obj in doc.objects
                if obj.role == Role.QUESTION_OBJECT
            )
        )

    def test_pii_generic_encryption_without_scope_stays_unknown(self):
        doc = compile_source(
            "***functional specifications***\n"
            "- Collect user email address classified as restricted data with consent, retention limits, purpose limitation, privacy rights, incident response, and encryption.\n",
            "privacy-encryption-scope-gap.plain",
        )

        check = next(c for c in doc.checks if c.property == "privacy-encryption-scope-reviewed")
        self.assertEqual(check.status, CheckStatus.UNKNOWN)
        self.assertTrue(
            any(
                ("MissingSecurityPrivacyEvidence", obj.id, "privacy-encryption-scope-reviewed") in obj.facts
                and ("Blocks", obj.id, check.obligation_id) in obj.facts
                for obj in doc.objects
                if obj.role == Role.QUESTION_OBJECT
            )
        )

    def test_pii_without_purpose_limitation_stays_unknown(self):
        doc = compile_source(
            "***functional specifications***\n"
            "- Collect user email address classified as restricted data with consent, retention limits, and encryption.\n",
            "privacy-purpose-gap.plain",
        )

        check = next(c for c in doc.checks if c.property == "privacy-purpose-limitation-reviewed")
        self.assertEqual(check.status, CheckStatus.UNKNOWN)
        self.assertTrue(
            any(
                ("MissingSecurityPrivacyEvidence", obj.id, "privacy-purpose-limitation-reviewed") in obj.facts
                and ("Blocks", obj.id, check.obligation_id) in obj.facts
                for obj in doc.objects
                if obj.role == Role.QUESTION_OBJECT
            )
        )

    def test_pii_without_data_subject_rights_stays_unknown(self):
        doc = compile_source(
            "***functional specifications***\n"
            "- Collect user email address classified as restricted data with consent, retention limits, purpose limitation, and encryption.\n",
            "privacy-rights-gap.plain",
        )

        check = next(c for c in doc.checks if c.property == "privacy-data-subject-rights-reviewed")
        self.assertEqual(check.status, CheckStatus.UNKNOWN)
        self.assertTrue(
            any(
                ("MissingSecurityPrivacyEvidence", obj.id, "privacy-data-subject-rights-reviewed") in obj.facts
                and ("Blocks", obj.id, check.obligation_id) in obj.facts
                for obj in doc.objects
                if obj.role == Role.QUESTION_OBJECT
            )
        )

    def test_pii_rights_request_without_identity_verification_stays_unknown(self):
        doc = compile_source(
            "***functional specifications***\n"
            "- Collect user email address classified as restricted data with consent, retention limits, purpose limitation, privacy rights access requests, and encryption.\n",
            "privacy-rights-auth-gap.plain",
        )

        check = next(c for c in doc.checks if c.property == "privacy-rights-request-authentication-reviewed")
        self.assertEqual(check.status, CheckStatus.UNKNOWN)
        self.assertTrue(
            any(
                ("MissingSecurityPrivacyEvidence", obj.id, "privacy-rights-request-authentication-reviewed") in obj.facts
                and ("Blocks", obj.id, check.obligation_id) in obj.facts
                for obj in doc.objects
                if obj.role == Role.QUESTION_OBJECT
            )
        )

    def test_authentication_without_session_management_stays_unknown(self):
        doc = compile_source(
            "***functional specifications***\n"
            "- Users login with role-based access control and least privilege for account records.\n",
            "auth-session-management-gap.plain",
        )

        check = next(c for c in doc.checks if c.property == "security-session-management-reviewed")
        self.assertEqual(check.status, CheckStatus.UNKNOWN)
        self.assertTrue(
            any(
                ("MissingSecurityPrivacyEvidence", obj.id, "security-session-management-reviewed") in obj.facts
                and ("Blocks", obj.id, check.obligation_id) in obj.facts
                for obj in doc.objects
                if obj.role == Role.QUESTION_OBJECT
            )
        )

    def test_auth_api_without_abuse_protection_stays_unknown(self):
        doc = compile_source(
            "***functional specifications***\n"
            "- Users login to the API endpoint with RBAC, least privilege, MFA, and session timeout.\n",
            "auth-abuse-protection-gap.plain",
        )

        check = next(c for c in doc.checks if c.property == "security-auth-abuse-protection-reviewed")
        self.assertEqual(check.status, CheckStatus.UNKNOWN)
        self.assertTrue(
            any(
                ("MissingSecurityPrivacyEvidence", obj.id, "security-auth-abuse-protection-reviewed") in obj.facts
                and ("Blocks", obj.id, check.obligation_id) in obj.facts
                for obj in doc.objects
                if obj.role == Role.QUESTION_OBJECT
            )
        )

    def test_pii_access_without_audit_stays_unknown(self):
        doc = compile_source(
            "***functional specifications***\n"
            "- Admin users can access user email address classified as restricted data with consent, retention limits, purpose limitation, privacy rights, identity verification, and encryption.\n",
            "privacy-access-audit-gap.plain",
        )

        check = next(c for c in doc.checks if c.property == "privacy-pii-access-audit-reviewed")
        self.assertEqual(check.status, CheckStatus.UNKNOWN)
        self.assertTrue(
            any(
                ("MissingSecurityPrivacyEvidence", obj.id, "privacy-pii-access-audit-reviewed") in obj.facts
                and ("Blocks", obj.id, check.obligation_id) in obj.facts
                for obj in doc.objects
                if obj.role == Role.QUESTION_OBJECT
            )
        )

    def test_pii_without_incident_response_stays_unknown(self):
        doc = compile_source(
            "***functional specifications***\n"
            "- Collect user email address classified as restricted data with consent, retention limits, purpose limitation, privacy rights, identity verification, access audit logs, and encryption.\n",
            "privacy-incident-gap.plain",
        )

        check = next(c for c in doc.checks if c.property == "privacy-incident-response-reviewed")
        self.assertEqual(check.status, CheckStatus.UNKNOWN)
        self.assertTrue(
            any(
                ("MissingSecurityPrivacyEvidence", obj.id, "privacy-incident-response-reviewed") in obj.facts
                and ("Blocks", obj.id, check.obligation_id) in obj.facts
                for obj in doc.objects
                if obj.role == Role.QUESTION_OBJECT
            )
        )

    def test_pii_region_without_residency_policy_stays_unknown(self):
        doc = compile_source(
            "***functional specifications***\n"
            "- Collect user email address classified as restricted data with consent, retention limits, and encryption for EU region users.\n",
            "privacy-residency-gap.plain",
        )

        check = next(c for c in doc.checks if c.property == "privacy-data-residency-reviewed")
        self.assertEqual(check.status, CheckStatus.UNKNOWN)
        self.assertTrue(
            any(
                ("MissingSecurityPrivacyEvidence", obj.id, "privacy-data-residency-reviewed") in obj.facts
                and ("Blocks", obj.id, check.obligation_id) in obj.facts
                for obj in doc.objects
                if obj.role == Role.QUESTION_OBJECT
            )
        )

    def test_pii_third_party_sharing_without_processor_policy_stays_unknown(self):
        doc = compile_source(
            "***functional specifications***\n"
            "- Share user email address classified as restricted data with consent, retention limits, and encryption to a vendor analytics service.\n",
            "privacy-third-party-gap.plain",
        )

        check = next(c for c in doc.checks if c.property == "privacy-third-party-sharing-reviewed")
        self.assertEqual(check.status, CheckStatus.UNKNOWN)
        self.assertTrue(
            any(
                ("MissingSecurityPrivacyEvidence", obj.id, "privacy-third-party-sharing-reviewed") in obj.facts
                and ("Blocks", obj.id, check.obligation_id) in obj.facts
                for obj in doc.objects
                if obj.role == Role.QUESTION_OBJECT
            )
        )

    def test_explicit_security_privacy_controls_pass_keyword_review(self):
        doc = compile_source(
            "***functional specifications***\n"
            "- Store API tokens in a secret manager; tokens are redacted from logs and not hard-coded.\n"
            "- Collect user email address classified as restricted data with consent, data minimization, retention limits, encryption at rest, TLS transport encryption, key rotation, EU data residency, purpose limitation, privacy rights access requests with identity verification, vendor review under a DPA, access audit logs, and breach notification incident response.\n"
            "- Use RBAC least privilege access control for admin-only account records with MFA, session timeout, logout, token expiry, rate limits, and brute-force lockout.\n"
            "- Delete records only after confirmation with audit log and rollback backup.\n",
            "security-privacy-pass.plain",
        )

        for property_name in {
            "security-secrets-handling-reviewed",
            "security-secret-log-exposure-reviewed",
            "security-credential-rotation-reviewed",
            "privacy-pii-handling-reviewed",
            "privacy-data-classification-declared",
            "privacy-encryption-scope-reviewed",
            "privacy-lawful-basis-reviewed",
            "privacy-retention-deletion-reviewed",
            "privacy-purpose-limitation-reviewed",
            "privacy-data-subject-rights-reviewed",
            "privacy-rights-request-authentication-reviewed",
            "privacy-data-residency-reviewed",
            "privacy-third-party-sharing-reviewed",
            "privacy-pii-access-audit-reviewed",
            "privacy-incident-response-reviewed",
            "security-access-boundary-declared",
            "security-privilege-escalation-reviewed",
            "security-session-management-reviewed",
            "security-auth-abuse-protection-reviewed",
            "security-destructive-action-safety-reviewed",
        }:
            self.assertTrue(any(c.property == property_name and c.status == CheckStatus.PASS for c in doc.checks), property_name)


if __name__ == "__main__":
    unittest.main()
