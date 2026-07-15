import unittest

from specatom_hs.backends.petta import emit_reified_atoms, refuse_executable_skeleton
from specatom_hs.passes import compile_source
from specatom_hs.schema import CheckStatus, Role, SemanticLevel, SpecDocument, SpecObject
from specatom_hs.validators import add_check, add_validation_obligation


def obj(level):
    return SpecObject("obj-1", Role.REQUIREMENT_OBJECT, level, "span-1")


class PettaProfileGateTests(unittest.TestCase):
    def test_quotes_ascii_control_characters_in_fact_text(self):
        requirement = SpecObject(
            "requirement",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
            "span-1",
            facts=[("RequirementText", "requirement", "alpha\x00beta\x07gamma")],
        )

        atoms, refusals = emit_reified_atoms(SpecDocument(objects=[requirement]))

        self.assertIn(
            '(RequirementText requirement "alpha\\u0000beta\\u0007gamma")',
            atoms,
        )
        self.assertFalse(any("RequirementText" in refusal.reason for refusal in refusals))
        self.assertFalse(any("\x00" in atom or "\x07" in atom for atom in atoms))

    def test_quotes_semicolons_in_source_and_fact_text(self):
        doc = compile_source(
            "***functional specifications***\n"
            "- Requirement: preserve alpha; do not treat beta as a comment.\n",
            "semicolon.plain",
        )

        atoms, refusals = emit_reified_atoms(doc)
        rendered = "\n".join(atoms)

        self.assertIn(
            '"Requirement: preserve alpha; do not treat beta as a comment."',
            rendered,
        )
        self.assertNotIn(
            "Requirement: preserve alpha; do not treat beta as a comment.)",
            rendered,
        )
        self.assertFalse(
            any("RequirementText" in refusal.reason for refusal in refusals)
        )

    def test_refuses_executable_skeleton_from_raw_text_only(self):
        refusals = refuse_executable_skeleton([obj(SemanticLevel.RAW_TEXT_ONLY)])
        self.assertEqual(len(refusals), 1)
        self.assertEqual(refusals[0].reason, "raw-text-only-skeleton-forbidden")

    def test_semantic_level_refusal_precedes_missing_provenance(self):
        objects = [
            SpecObject("raw", Role.REQUIREMENT_OBJECT, SemanticLevel.RAW_TEXT_ONLY, ""),
            SpecObject("parsed", Role.REQUIREMENT_OBJECT, SemanticLevel.TEMPLATE_PARSED, ""),
        ]
        refusals = refuse_executable_skeleton(objects)
        self.assertEqual(
            [(r.object_id, r.reason, r.semantic_level) for r in refusals],
            [
                ("raw", "raw-text-only-skeleton-forbidden", "RawTextOnly"),
                ("parsed", "unsupported-semantic-level-for-executable-skeleton", "TemplateParsed"),
            ],
        )

    def test_refuses_executable_skeleton_from_unsupported_semantic_levels(self):
        refusals = refuse_executable_skeleton([obj(SemanticLevel.TEMPLATE_PARSED)])
        self.assertEqual(len(refusals), 1)
        self.assertEqual(refusals[0].reason, "unsupported-semantic-level-for-executable-skeleton")

    def test_refuses_executable_skeleton_without_object_id(self):
        unidentified = SpecObject(
            "",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("Requirement", "")],
        )
        refusals = refuse_executable_skeleton([unidentified])
        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [("", "missing-object-id-for-executable-skeleton")],
        )

    def test_refuses_executable_skeleton_with_empty_object_reference(self):
        unidentified = SpecObject(
            "",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("Requirement", "")],
        )
        coverage = SpecObject(
            "coverage",
            Role.VALIDATION_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-2",
            facts=[("Covers", "coverage", "")],
        )
        refusals = refuse_executable_skeleton([unidentified, coverage])
        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [
                ("", "missing-object-id-for-executable-skeleton"),
                ("coverage", "unsafe-profile-fact:empty-object-reference:Covers"),
            ],
        )

    def test_refuses_transitive_reference_to_empty_object_identity(self):
        unidentified = SpecObject(
            "",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("Requirement", "")],
        )
        requirement = SpecObject(
            "requirement",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-2",
            facts=[("GeneratedFrom", "requirement", "")],
        )
        coverage = SpecObject(
            "coverage",
            Role.VALIDATION_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-3",
            facts=[("Covers", "coverage", "requirement")],
        )
        refusals = refuse_executable_skeleton([unidentified, requirement, coverage])
        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [
                ("", "missing-object-id-for-executable-skeleton"),
                ("requirement", "unsafe-profile-fact:empty-object-reference:GeneratedFrom"),
                (
                    "coverage",
                    "unsafe-profile-fact:unsafe-object-reference-deep-semantic-level:"
                    "Covers:requirement->:MissingObjectId",
                ),
            ],
        )

    def test_refuses_whitespace_only_object_identity_across_reference_depths(self):
        unidentified = SpecObject(
            "   ",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("Requirement", "   ")],
        )
        requirement = SpecObject(
            "requirement",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-2",
            facts=[("GeneratedFrom", "requirement", "   ")],
        )
        coverage = SpecObject(
            "coverage",
            Role.VALIDATION_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-3",
            facts=[("Covers", "coverage", "requirement")],
        )

        refusals = refuse_executable_skeleton([unidentified, requirement, coverage])

        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [
                ("   ", "missing-object-id-for-executable-skeleton"),
                ("requirement", "unsafe-profile-fact:empty-object-reference:GeneratedFrom"),
                (
                    "coverage",
                    "unsafe-profile-fact:unsafe-object-reference-deep-semantic-level:"
                    "Covers:requirement->   :MissingObjectId",
                ),
            ],
        )

    def test_refuses_executable_skeleton_when_lowered_object_has_unsafe_facts(self):
        objects = [
            SpecObject("unknown", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-1", facts=[("InventedExecutable", "unknown", "run")]),
            SpecObject("malformed", Role.VALIDATION_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-1", facts=[("Covers", "malformed")]),
            SpecObject("wrong-owner", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-1", facts=[("RequirementText", "other", "text")]),
        ]
        refusals = refuse_executable_skeleton(objects)
        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [
                ("unknown", "unsafe-profile-fact:unsupported-fact-predicate:InventedExecutable"),
                ("malformed", "unsafe-profile-fact:unsupported-fact-arity:Covers:expected-3:got-2"),
                ("wrong-owner", "unsafe-profile-fact:fact-subject-mismatch:RequirementText:expected-wrong-owner:got-other"),
            ],
        )

    def test_refuses_blank_scalar_fact_argument_for_reified_and_executable_profiles(self):
        obj = SpecObject(
            "obj-blank-value",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-blank-value",
            facts=[("RequirementLabel", "obj-blank-value", " \t ")],
        )

        atoms, reified_refusals = emit_reified_atoms(SpecDocument(objects=[obj]))
        executable_refusals = refuse_executable_skeleton([obj])

        self.assertNotIn("(RequirementLabel ", "\n".join(atoms))
        self.assertTrue(any(r.reason == "empty-fact-argument:RequirementLabel:position-2" for r in reified_refusals))
        self.assertTrue(any(r.reason == "unsafe-profile-fact:empty-fact-argument:RequirementLabel:position-2" for r in executable_refusals))

    def test_refuses_none_scalar_fact_argument_for_reified_and_executable_profiles(self):
        missing_value = SpecObject(
            "obj-none-value",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("RequirementLabel", "obj-none-value", None)],
        )

        atoms, reified_refusals = emit_reified_atoms(SpecDocument(objects=[missing_value]))
        executable_refusals = refuse_executable_skeleton([missing_value])

        self.assertNotIn("(RequirementLabel ", "\n".join(atoms))
        self.assertTrue(any(r.reason == "empty-fact-argument:RequirementLabel:position-2" for r in reified_refusals))
        self.assertTrue(any(r.reason == "unsafe-profile-fact:empty-fact-argument:RequirementLabel:position-2" for r in executable_refusals))

    def test_refuses_non_finite_scalar_fact_arguments_for_reified_and_executable_profiles(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                candidate = SpecObject(
                    "obj-non-finite-value",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-non-finite-value",
                    facts=[("RequirementLabel", "obj-non-finite-value", value)],
                )

                atoms, reified_refusals = emit_reified_atoms(SpecDocument(objects=[candidate]))
                executable_refusals = refuse_executable_skeleton([candidate])

                self.assertNotIn("(RequirementLabel ", "\n".join(atoms))
                self.assertTrue(any(r.reason == "non-finite-fact-argument:RequirementLabel:position-2" for r in reified_refusals))
                self.assertTrue(any(r.reason == "unsafe-profile-fact:non-finite-fact-argument:RequirementLabel:position-2" for r in executable_refusals))

    def test_refuses_non_string_fact_subject_despite_apparent_matching_id(self):
        for object_id, subject in (("1", 1), ("1.5", 1.5), ("True", True)):
            with self.subTest(object_id=object_id, subject=subject):
                candidate = SpecObject(
                    object_id,
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-subject",
                    facts=[("RequirementLabel", subject, "label")],
                )

                atoms, reified_refusals = emit_reified_atoms(
                    SpecDocument(objects=[candidate])
                )
                executable_refusals = refuse_executable_skeleton([candidate])
                reason = (
                    "unsupported-fact-subject-type:RequirementLabel:position-1:"
                    f"{type(subject).__name__}"
                )

                self.assertFalse(
                    any(atom.startswith("(RequirementLabel ") for atom in atoms)
                )
                self.assertTrue(any(r.reason == reason for r in reified_refusals))
                self.assertTrue(
                    any(
                        r.reason == f"unsafe-profile-fact:{reason}"
                        for r in executable_refusals
                    )
                )

    def test_refuses_non_string_object_ids_without_aliasing_or_crashing(self):
        for object_id in (1, 1.5, True):
            with self.subTest(object_id=object_id):
                candidate = SpecObject(
                    object_id,
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-object-id",
                    facts=[("Requirement", object_id)],
                )

                atoms, reified_refusals = emit_reified_atoms(
                    SpecDocument(objects=[candidate])
                )
                executable_refusals = refuse_executable_skeleton([candidate])
                type_name = type(object_id).__name__

                self.assertFalse(any(atom.startswith("(spec-object ") for atom in atoms))
                self.assertFalse(any(atom.startswith("(Requirement ") for atom in atoms))
                self.assertTrue(
                    any(
                        refusal.reason
                        == f"unsupported-object-id-type-for-reified-emission:{type_name}"
                        for refusal in reified_refusals
                    )
                )
                self.assertEqual(
                    [refusal.reason for refusal in executable_refusals],
                    [
                        "unsupported-object-id-type-for-executable-skeleton:"
                        f"{type_name}"
                    ],
                )

    def test_refuses_non_enum_object_roles_without_emitting_facts(self):
        for role in ("RequirementObject", None, 7):
            with self.subTest(role=role):
                candidate = SpecObject(
                    "obj-invalid-role",
                    role,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-invalid-role",
                    facts=[("Requirement", "obj-invalid-role")],
                )

                atoms, reified_refusals = emit_reified_atoms(
                    SpecDocument(objects=[candidate])
                )
                executable_refusals = refuse_executable_skeleton([candidate])
                type_name = type(role).__name__

                self.assertFalse(any(atom.startswith("(spec-object ") for atom in atoms))
                self.assertFalse(any(atom.startswith("(Requirement ") for atom in atoms))
                self.assertEqual(
                    [refusal.reason for refusal in reified_refusals],
                    [
                        "unsupported-object-role-type-for-reified-emission:"
                        f"{type_name}"
                    ],
                )
                self.assertEqual(
                    [refusal.reason for refusal in executable_refusals],
                    [
                        "unsupported-object-role-type-for-executable-skeleton:"
                        f"{type_name}"
                    ],
                )

    def test_refuses_structured_fact_arguments_for_reified_and_executable_profiles(self):
        for value in (["nested"], {"nested": "value"}):
            with self.subTest(value=value):
                unsafe = SpecObject(
                    "obj-structured-value",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-structured-value",
                    facts=[("RequirementLabel", "obj-structured-value", value)],
                )
                atoms, reified_refusals = emit_reified_atoms(SpecDocument(objects=[unsafe]))
                executable_refusals = refuse_executable_skeleton([unsafe])
                reason = f"unsupported-fact-argument-type:RequirementLabel:position-2:{type(value).__name__}"
                self.assertNotIn(f"(RequirementLabel obj-structured-value {value})", atoms)
                self.assertTrue(any(r.reason == reason for r in reified_refusals))
                self.assertTrue(any(r.reason == f"unsafe-profile-fact:{reason}" for r in executable_refusals))

    def test_refuses_structured_object_references_before_id_resolution(self):
        for value in (["requirement-1"], {"id": "requirement-1"}):
            with self.subTest(value=value):
                coverage = SpecObject(
                    "coverage-structured-reference",
                    Role.VALIDATION_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-structured-reference",
                    facts=[("Covers", "coverage-structured-reference", value)],
                )
                requirement = SpecObject(
                    "requirement-1",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-requirement-1",
                    facts=[("Requirement", "requirement-1")],
                )

                atoms, reified_refusals = emit_reified_atoms(
                    SpecDocument(objects=[coverage, requirement])
                )
                executable_refusals = refuse_executable_skeleton(
                    [coverage, requirement]
                )
                reason = (
                    "unsupported-fact-argument-type:Covers:position-2:"
                    f"{type(value).__name__}"
                )

                self.assertFalse(any(atom.startswith("(Covers ") for atom in atoms))
                self.assertTrue(any(r.reason == reason for r in reified_refusals))
                self.assertTrue(
                    any(
                        r.reason == f"unsafe-profile-fact:{reason}"
                        for r in executable_refusals
                    )
                )

    def test_refuses_none_object_reference_for_reified_and_executable_profiles(self):
        requirement = SpecObject(
            "requirement-1",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("GeneratedFrom", "requirement-1", None)],
        )
        atoms, reified_refusals = emit_reified_atoms(SpecDocument(objects=[requirement]))
        executable_refusals = refuse_executable_skeleton([requirement])

        self.assertFalse(any("GeneratedFrom" in atom for atom in atoms))
        self.assertTrue(any(r.reason == "empty-object-reference:GeneratedFrom:position-2" for r in reified_refusals))
        self.assertTrue(any(r.reason == "unsafe-profile-fact:empty-object-reference:GeneratedFrom" for r in executable_refusals))

    def test_refuses_non_string_object_references_before_id_resolution(self):
        for value in (1, 1.5, True):
            with self.subTest(value=value):
                coverage = SpecObject(
                    "coverage-non-string-reference",
                    Role.VALIDATION_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-non-string-reference",
                    facts=[("Covers", "coverage-non-string-reference", value)],
                )
                apparent_target = SpecObject(
                    str(value),
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-apparent-target",
                    facts=[("Requirement", str(value))],
                )

                atoms, reified_refusals = emit_reified_atoms(
                    SpecDocument(objects=[coverage, apparent_target])
                )
                executable_refusals = refuse_executable_skeleton(
                    [coverage, apparent_target]
                )
                reason = (
                    "unsupported-object-reference-type:Covers:position-2:"
                    f"{type(value).__name__}"
                )

                self.assertFalse(any(atom.startswith("(Covers ") for atom in atoms))
                self.assertTrue(any(r.reason == reason for r in reified_refusals))
                self.assertTrue(
                    any(
                        r.reason == f"unsafe-profile-fact:{reason}"
                        for r in executable_refusals
                    )
                )

    def test_refuses_executable_skeleton_with_dangling_object_reference(self):
        lowered = SpecObject(
            "coverage",
            Role.VALIDATION_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("Covers", "coverage", "missing-requirement")],
        )
        refusals = refuse_executable_skeleton([lowered])
        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [("coverage", "unsafe-profile-fact:dangling-object-reference:Covers:missing-requirement")],
        )

    def test_refuses_executable_skeleton_reference_to_raw_text_object(self):
        requirement = SpecObject("requirement", Role.REQUIREMENT_OBJECT, SemanticLevel.RAW_TEXT_ONLY, "span-1", facts=[("Requirement", "requirement")])
        coverage = SpecObject("coverage", Role.VALIDATION_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-2", facts=[("Covers", "coverage", "requirement")])
        refusals = refuse_executable_skeleton([requirement, coverage])
        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [
                ("requirement", "raw-text-only-skeleton-forbidden"),
                ("coverage", "unsafe-profile-fact:unsafe-object-reference-semantic-level:Covers:requirement:RawTextOnly"),
            ],
        )

    def test_allows_executable_skeleton_reference_to_declared_safe_object(self):
        requirement = SpecObject("requirement", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-1", facts=[("Requirement", "requirement")])
        coverage = SpecObject("coverage", Role.VALIDATION_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-2", facts=[("Covers", "coverage", "requirement")])
        self.assertEqual(refuse_executable_skeleton(iter([requirement, coverage])), [])

    def test_allows_profile_safe_diamond_reference_graph(self):
        shared = SpecObject(
            "shared-source",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.VERIFIED,
            "span-1",
            facts=[("Requirement", "shared-source")],
        )
        left = SpecObject(
            "left-artifact",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-2",
            facts=[("GeneratedFrom", "left-artifact", "shared-source")],
        )
        right = SpecObject(
            "right-artifact",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-3",
            facts=[("GeneratedFrom", "right-artifact", "shared-source")],
        )
        requirement = SpecObject(
            "requirement",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-4",
            facts=[
                ("GeneratedFrom", "requirement", "left-artifact"),
                ("GeneratedFrom", "requirement", "right-artifact"),
            ],
        )
        coverage = SpecObject(
            "coverage",
            Role.VALIDATION_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-5",
            facts=[("Covers", "coverage", "requirement")],
        )

        self.assertEqual(
            refuse_executable_skeleton([coverage, requirement, right, left, shared]),
            [],
        )

    def test_refuses_executable_skeleton_references_to_profile_unsafe_objects(self):
        unprovenanced = SpecObject("unprovenanced", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "", facts=[("Requirement", "unprovenanced")])
        empty = SpecObject("empty", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-2")
        malformed = SpecObject("malformed", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-3", facts=[("RequirementText", "other", "text")])
        coverage = SpecObject(
            "coverage",
            Role.VALIDATION_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-4",
            facts=[
                ("Covers", "coverage", "unprovenanced"),
                ("Covers", "coverage", "empty"),
                ("Covers", "coverage", "malformed"),
            ],
        )
        refusals = refuse_executable_skeleton([unprovenanced, empty, malformed, coverage])
        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [
                ("unprovenanced", "missing-source-provenance-for-executable-skeleton"),
                ("empty", "missing-profile-facts-for-executable-skeleton"),
                ("malformed", "unsafe-profile-fact:fact-subject-mismatch:RequirementText:expected-malformed:got-other"),
                ("coverage", "unsafe-profile-fact:unsafe-object-reference-missing-profile-facts:Covers:empty"),
                ("coverage", "unsafe-profile-fact:unsafe-object-reference-profile:Covers:malformed:fact-subject-mismatch:RequirementText:expected-malformed:got-other"),
                ("coverage", "unsafe-profile-fact:unsafe-object-reference-missing-source-provenance:Covers:unprovenanced"),
            ],
        )

    def test_refuses_reference_to_object_with_transitive_dangling_reference(self):
        requirement = SpecObject(
            "requirement",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("GeneratedFrom", "requirement", "missing-source-object")],
        )
        coverage = SpecObject("coverage", Role.VALIDATION_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-2", facts=[("Covers", "coverage", "requirement")])
        refusals = refuse_executable_skeleton([requirement, coverage])
        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [
                ("requirement", "unsafe-profile-fact:dangling-object-reference:GeneratedFrom:missing-source-object"),
                ("coverage", "unsafe-profile-fact:unsafe-object-reference-transitive-dangling:Covers:requirement:GeneratedFrom:missing-source-object"),
            ],
        )

    def test_refuses_reference_to_object_with_transitive_raw_text_reference(self):
        raw_source = SpecObject("raw-source", Role.REQUIREMENT_OBJECT, SemanticLevel.RAW_TEXT_ONLY, "span-1", facts=[("Requirement", "raw-source")])
        requirement = SpecObject(
            "requirement",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-2",
            facts=[("GeneratedFrom", "requirement", "raw-source")],
        )
        coverage = SpecObject("coverage", Role.VALIDATION_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-3", facts=[("Covers", "coverage", "requirement")])
        refusals = refuse_executable_skeleton([raw_source, requirement, coverage])
        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [
                ("raw-source", "raw-text-only-skeleton-forbidden"),
                ("requirement", "unsafe-profile-fact:unsafe-object-reference-semantic-level:GeneratedFrom:raw-source:RawTextOnly"),
                ("coverage", "unsafe-profile-fact:unsafe-object-reference-transitive-semantic-level:Covers:requirement:GeneratedFrom:raw-source:RawTextOnly"),
            ],
        )

    def test_transitive_refusal_is_stable_across_fact_order(self):
        raw_targets = [
            SpecObject("alpha-source", Role.REQUIREMENT_OBJECT, SemanticLevel.RAW_TEXT_ONLY, "span-1", facts=[("Requirement", "alpha-source")]),
            SpecObject("zeta-source", Role.REQUIREMENT_OBJECT, SemanticLevel.RAW_TEXT_ONLY, "span-2", facts=[("Requirement", "zeta-source")]),
        ]
        expected = "unsafe-profile-fact:unsafe-object-reference-transitive-semantic-level:Covers:requirement:GeneratedFrom:alpha-source:RawTextOnly"
        for target_order in (raw_targets, list(reversed(raw_targets))):
            with self.subTest(order=[target.id for target in target_order]):
                requirement = SpecObject(
                    "requirement",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-3",
                    facts=[("GeneratedFrom", "requirement", target.id) for target in target_order],
                )
                coverage = SpecObject(
                    "coverage",
                    Role.VALIDATION_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-4",
                    facts=[("Covers", "coverage", "requirement")],
                )
                coverage_reasons = [
                    refusal.reason
                    for refusal in refuse_executable_skeleton([*raw_targets, requirement, coverage])
                    if refusal.object_id == "coverage"
                ]
                self.assertEqual(coverage_reasons, [expected])

    def test_originating_refusal_order_is_stable_across_fact_order(self):
        referenced = [
            SpecObject("alpha-target", Role.REQUIREMENT_OBJECT, SemanticLevel.RAW_TEXT_ONLY, "span-1", facts=[("Requirement", "alpha-target")]),
            SpecObject("zeta-target", Role.REQUIREMENT_OBJECT, SemanticLevel.RAW_TEXT_ONLY, "span-2", facts=[("Requirement", "zeta-target")]),
        ]
        expected = [
            "unsafe-profile-fact:unsafe-object-reference-semantic-level:GeneratedFrom:alpha-target:RawTextOnly",
            "unsafe-profile-fact:unsafe-object-reference-semantic-level:GeneratedFrom:zeta-target:RawTextOnly",
        ]
        facts = [
            ("GeneratedFrom", "origin", "zeta-target"),
            ("GeneratedFrom", "origin", "alpha-target"),
        ]
        for fact_order in (facts, list(reversed(facts))):
            with self.subTest(order=[fact[2] for fact in fact_order]):
                origin = SpecObject(
                    "origin",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-3",
                    facts=fact_order,
                )
                origin_reasons = [
                    refusal.reason
                    for refusal in refuse_executable_skeleton([*referenced, origin])
                    if refusal.object_id == "origin"
                ]
                self.assertEqual(origin_reasons, expected)

    def test_deep_refusal_is_stable_across_fact_order(self):
        raw_targets = [
            SpecObject("alpha-source", Role.REQUIREMENT_OBJECT, SemanticLevel.RAW_TEXT_ONLY, "span-1", facts=[("Requirement", "alpha-source")]),
            SpecObject("zeta-source", Role.REQUIREMENT_OBJECT, SemanticLevel.RAW_TEXT_ONLY, "span-2", facts=[("Requirement", "zeta-source")]),
        ]
        expected = "unsafe-profile-fact:unsafe-object-reference-deep-semantic-level:Covers:requirement->alpha-artifact->alpha-source:RawTextOnly"
        for target_order in (raw_targets, list(reversed(raw_targets))):
            with self.subTest(order=[target.id for target in target_order]):
                artifacts = [
                    SpecObject(
                        target.id.replace("source", "artifact"),
                        Role.REQUIREMENT_OBJECT,
                        SemanticLevel.BACKEND_LOWERED,
                        f"span-{index + 3}",
                        facts=[("GeneratedFrom", target.id.replace("source", "artifact"), target.id)],
                    )
                    for index, target in enumerate(target_order)
                ]
                requirement = SpecObject(
                    "requirement",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-5",
                    facts=[("GeneratedFrom", "requirement", artifact.id) for artifact in artifacts],
                )
                coverage = SpecObject(
                    "coverage",
                    Role.VALIDATION_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-6",
                    facts=[("Covers", "coverage", "requirement")],
                )
                coverage_reasons = [
                    refusal.reason
                    for refusal in refuse_executable_skeleton([*raw_targets, *artifacts, requirement, coverage])
                    if refusal.object_id == "coverage"
                ]
                self.assertEqual(coverage_reasons, [expected])

    def test_deep_refusal_uses_canonical_path_across_mixed_depths(self):
        alpha_leaf = SpecObject(
            "alpha-leaf",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("GeneratedFrom", "alpha-leaf", "alpha-raw")],
        )
        alpha_raw = SpecObject("alpha-raw", Role.REQUIREMENT_OBJECT, SemanticLevel.RAW_TEXT_ONLY, "span-2", facts=[("Requirement", "alpha-raw")])
        zeta_raw = SpecObject("zeta-raw", Role.REQUIREMENT_OBJECT, SemanticLevel.RAW_TEXT_ONLY, "span-3", facts=[("Requirement", "zeta-raw")])
        artifact = SpecObject(
            "artifact",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-4",
            facts=[
                ("GeneratedFrom", "artifact", "zeta-raw"),
                ("GeneratedFrom", "artifact", "alpha-leaf"),
            ],
        )
        requirement = SpecObject(
            "requirement",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-5",
            facts=[("GeneratedFrom", "requirement", "artifact")],
        )
        coverage = SpecObject(
            "coverage",
            Role.VALIDATION_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-6",
            facts=[("Covers", "coverage", "requirement")],
        )

        coverage_reasons = [
            refusal.reason
            for refusal in refuse_executable_skeleton([alpha_leaf, alpha_raw, zeta_raw, artifact, requirement, coverage])
            if refusal.object_id == "coverage"
        ]
        self.assertEqual(
            coverage_reasons,
            [
                "unsafe-profile-fact:unsafe-object-reference-deep-semantic-level:"
                "Covers:requirement->artifact->alpha-leaf->alpha-raw:RawTextOnly"
            ],
        )

    def test_refuses_reference_with_deep_raw_text_dependency(self):
        raw_source = SpecObject("raw-source", Role.REQUIREMENT_OBJECT, SemanticLevel.RAW_TEXT_ONLY, "span-1", facts=[("Requirement", "raw-source")])
        artifact = SpecObject(
            "artifact",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-2",
            facts=[("GeneratedFrom", "artifact", "raw-source")],
        )
        requirement = SpecObject(
            "requirement",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-3",
            facts=[("GeneratedFrom", "requirement", "artifact")],
        )
        coverage = SpecObject("coverage", Role.VALIDATION_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-4", facts=[("Covers", "coverage", "requirement")])
        refusals = refuse_executable_skeleton([raw_source, artifact, requirement, coverage])
        self.assertIn(
            (
                "coverage",
                "unsafe-profile-fact:unsafe-object-reference-deep-semantic-level:Covers:requirement->artifact->raw-source:RawTextOnly",
            ),
            [(r.object_id, r.reason) for r in refusals],
        )

    def test_semantic_level_refusal_precedes_missing_provenance_through_reference_depths(self):
        for depth in (1, 2, 3):
            with self.subTest(depth=depth):
                parsed = SpecObject(
                    "parsed",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.TEMPLATE_PARSED,
                    "",
                    facts=[("Requirement", "parsed")],
                )
                objects = [parsed]
                target_id = parsed.id
                for hop in range(depth - 1):
                    artifact = SpecObject(
                        f"artifact-{hop}",
                        Role.REQUIREMENT_OBJECT,
                        SemanticLevel.BACKEND_LOWERED,
                        f"span-{hop + 1}",
                        facts=[("GeneratedFrom", f"artifact-{hop}", target_id)],
                    )
                    objects.append(artifact)
                    target_id = artifact.id
                coverage = SpecObject(
                    "coverage",
                    Role.VALIDATION_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-coverage",
                    facts=[("Covers", "coverage", target_id)],
                )
                refusals = refuse_executable_skeleton([*objects, coverage])
                coverage_reasons = [r.reason for r in refusals if r.object_id == "coverage"]
                self.assertEqual(len(coverage_reasons), 1)
                self.assertIn("TemplateParsed", coverage_reasons[0])
                self.assertNotIn("MissingSourceProvenance", coverage_reasons[0])

    def test_refuses_reference_with_deep_dangling_dependency(self):
        artifact = SpecObject(
            "artifact",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("GeneratedFrom", "artifact", "missing-source")],
        )
        requirement = SpecObject(
            "requirement",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-2",
            facts=[("GeneratedFrom", "requirement", "artifact")],
        )
        coverage = SpecObject("coverage", Role.VALIDATION_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-3", facts=[("Covers", "coverage", "requirement")])
        refusals = refuse_executable_skeleton([artifact, requirement, coverage])
        self.assertIn(
            (
                "coverage",
                "unsafe-profile-fact:unsafe-object-reference-deep-semantic-level:Covers:requirement->artifact->missing-source:DanglingReference",
            ),
            [(r.object_id, r.reason) for r in refusals],
        )

    def test_refuses_reference_with_deep_profile_unsafe_dependencies(self):
        unsafe_targets = [
            (
                SpecObject("unprovenanced", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "", facts=[("Requirement", "unprovenanced")]),
                "MissingSourceProvenance",
            ),
            (
                SpecObject("empty", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-1"),
                "MissingProfileFacts",
            ),
            (
                SpecObject("malformed", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-2", facts=[("RequirementText", "other", "text")]),
                "UnsafeProfile:fact-subject-mismatch:RequirementText:expected-malformed:got-other",
            ),
        ]
        for unsafe_target, expected_reason in unsafe_targets:
            with self.subTest(target=unsafe_target.id):
                artifact = SpecObject(
                    "artifact",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-3",
                    facts=[("GeneratedFrom", "artifact", unsafe_target.id)],
                )
                requirement = SpecObject(
                    "requirement",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-4",
                    facts=[("GeneratedFrom", "requirement", "artifact")],
                )
                coverage = SpecObject(
                    "coverage",
                    Role.VALIDATION_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-5",
                    facts=[("Covers", "coverage", "requirement")],
                )
                refusals = refuse_executable_skeleton([unsafe_target, artifact, requirement, coverage])
                self.assertIn(
                    (
                        "coverage",
                        f"unsafe-profile-fact:unsafe-object-reference-deep-semantic-level:Covers:requirement->artifact->{unsafe_target.id}:{expected_reason}",
                    ),
                    [(r.object_id, r.reason) for r in refusals],
                )

    def test_refuses_reference_with_one_hop_transitive_unsafe_dependencies(self):
        unsafe_targets = [
            (
                [SpecObject("source", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "", facts=[("Requirement", "source")])],
                "MissingSourceProvenance",
            ),
            (
                [SpecObject("source", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-1")],
                "MissingProfileFacts",
            ),
            (
                [SpecObject("source", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-2", facts=[("RequirementText", "other", "text")])],
                "UnsafeProfile:fact-subject-mismatch:RequirementText:expected-source:got-other",
            ),
            (
                [
                    SpecObject("source", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-3", facts=[("Requirement", "source")]),
                    SpecObject("source", Role.REQUIREMENT_OBJECT, SemanticLevel.VERIFIED, "span-4", facts=[("Requirement", "source")]),
                ],
                "AmbiguousReference",
            ),
        ]
        for targets, expected_reason in unsafe_targets:
            with self.subTest(reason=expected_reason):
                requirement = SpecObject(
                    "requirement",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-5",
                    facts=[("GeneratedFrom", "requirement", "source")],
                )
                coverage = SpecObject(
                    "coverage",
                    Role.VALIDATION_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-6",
                    facts=[("Covers", "coverage", "requirement")],
                )
                refusals = refuse_executable_skeleton([*targets, requirement, coverage])
                self.assertIn(
                    (
                        "coverage",
                        f"unsafe-profile-fact:unsafe-object-reference-deep-semantic-level:Covers:requirement->source:{expected_reason}",
                    ),
                    [(r.object_id, r.reason) for r in refusals],
                )

    def test_refuses_reference_with_deep_reference_cycle(self):
        artifact = SpecObject(
            "artifact",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("GeneratedFrom", "artifact", "requirement")],
        )
        requirement = SpecObject(
            "requirement",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-2",
            facts=[("GeneratedFrom", "requirement", "artifact")],
        )
        coverage = SpecObject("coverage", Role.VALIDATION_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-3", facts=[("Covers", "coverage", "requirement")])
        refusals = refuse_executable_skeleton([artifact, requirement, coverage])
        self.assertIn(
            (
                "coverage",
                "unsafe-profile-fact:unsafe-object-reference-deep-semantic-level:Covers:requirement->artifact->requirement:ReferenceCycle",
            ),
            [(r.object_id, r.reason) for r in refusals],
        )

    def test_refuses_reference_with_deep_ambiguous_dependency(self):
        duplicate_a = SpecObject(
            "source",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("Requirement", "source")],
        )
        duplicate_b = SpecObject(
            "source",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.VERIFIED,
            "span-2",
            facts=[("Requirement", "source")],
        )
        artifact = SpecObject(
            "artifact",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-3",
            facts=[("GeneratedFrom", "artifact", "source")],
        )
        requirement = SpecObject(
            "requirement",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-4",
            facts=[("GeneratedFrom", "requirement", "artifact")],
        )
        coverage = SpecObject(
            "coverage",
            Role.VALIDATION_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-5",
            facts=[("Covers", "coverage", "requirement")],
        )
        refusals = refuse_executable_skeleton([duplicate_a, duplicate_b, artifact, requirement, coverage])
        self.assertIn(
            (
                "coverage",
                "unsafe-profile-fact:unsafe-object-reference-deep-semantic-level:Covers:requirement->artifact->source:AmbiguousReference",
            ),
            [(r.object_id, r.reason) for r in refusals],
        )

    def test_refuses_duplicate_object_ids_and_ambiguous_references(self):
        requirement_a = SpecObject("requirement", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-1", facts=[("Requirement", "requirement")])
        requirement_b = SpecObject("requirement", Role.REQUIREMENT_OBJECT, SemanticLevel.VERIFIED, "span-2", facts=[("Requirement", "requirement")])
        coverage = SpecObject("coverage", Role.VALIDATION_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-3", facts=[("Covers", "coverage", "requirement")])
        refusals = refuse_executable_skeleton([requirement_a, requirement_b, coverage])
        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [
                ("requirement", "duplicate-object-id-for-executable-skeleton"),
                ("requirement", "duplicate-object-id-for-executable-skeleton"),
                ("coverage", "unsafe-profile-fact:ambiguous-object-reference:Covers:requirement"),
            ],
        )

    def test_refuses_executable_skeleton_without_source_provenance(self):
        lowered = SpecObject("unprovenanced", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "", facts=[("Requirement", "unprovenanced")])
        refusals = refuse_executable_skeleton([lowered])
        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [("unprovenanced", "missing-source-provenance-for-executable-skeleton")],
        )

    def test_refuses_whitespace_only_source_provenance_directly_and_transitively(self):
        unprovenanced = SpecObject(
            "unprovenanced",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            " \t ",
            facts=[("Requirement", "unprovenanced")],
        )
        requirement = SpecObject(
            "requirement",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("GeneratedFrom", "requirement", "unprovenanced")],
        )
        coverage = SpecObject(
            "coverage",
            Role.VALIDATION_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-2",
            facts=[("Covers", "coverage", "requirement")],
        )

        refusals = refuse_executable_skeleton([unprovenanced, requirement, coverage])
        refusal_pairs = [(refusal.object_id, refusal.reason) for refusal in refusals]
        self.assertIn(
            ("unprovenanced", "missing-source-provenance-for-executable-skeleton"),
            refusal_pairs,
        )
        self.assertIn(
            (
                "requirement",
                "unsafe-profile-fact:unsafe-object-reference-missing-source-provenance:GeneratedFrom:unprovenanced",
            ),
            refusal_pairs,
        )
        self.assertIn(
            (
                "coverage",
                "unsafe-profile-fact:unsafe-object-reference-deep-semantic-level:Covers:requirement->unprovenanced:MissingSourceProvenance",
            ),
            refusal_pairs,
        )

    def test_refuses_executable_skeleton_without_profile_facts(self):
        lowered = SpecObject("empty", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-1")
        refusals = refuse_executable_skeleton([lowered])
        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [("empty", "missing-profile-facts-for-executable-skeleton")],
        )

    def test_allows_executable_skeleton_gate_for_profile_safe_lowered_object(self):
        lowered = SpecObject("safe", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-1", facts=[("Requirement", "safe")])
        self.assertEqual(refuse_executable_skeleton([lowered]), [])

    def test_basic_reified_atom_emission_stub_when_safe(self):
        doc = SpecDocument(objects=[obj(SemanticLevel.TEMPLATE_PARSED)])
        atoms, refusals = emit_reified_atoms(doc)
        self.assertFalse(refusals)
        self.assertIn("(target-profile petta_reified_v0)", atoms)
        self.assertIn("(spec-object obj-1 RequirementObject TemplateParsed)", atoms)

    def test_reified_atom_refuses_raw_text_only(self):
        doc = SpecDocument(objects=[obj(SemanticLevel.RAW_TEXT_ONLY)])
        atoms, refusals = emit_reified_atoms(doc)
        self.assertEqual(atoms, ["(target-profile petta_reified_v0)", "(document-validation-summary document 0 0 0 0)", "(information-flow-graph-summary document 0 0 0 0 0 0 0 0 0)"])
        self.assertEqual(len(refusals), 1)
        self.assertEqual(refusals[0].reason, "unsupported-semantic-level-for-reified-emission")

    def test_reified_profile_filters_unknown_malformed_and_wrong_subject_facts(self):
        good = SpecObject("obj-good", Role.REQUIREMENT_OBJECT, SemanticLevel.TEMPLATE_PARSED, "span-1", facts=[("Requirement", "obj-good")])
        unknown = SpecObject("obj-unknown", Role.REQUIREMENT_OBJECT, SemanticLevel.TEMPLATE_PARSED, "span-1", facts=[("InventedExecutable", "obj-unknown", "run")])
        malformed = SpecObject("obj-bad", Role.VALIDATION_OBJECT, SemanticLevel.TEMPLATE_PARSED, "span-1", facts=[("Covers", "obj-bad")])
        wrong_subject = SpecObject("obj-owner", Role.REQUIREMENT_OBJECT, SemanticLevel.TEMPLATE_PARSED, "span-1", facts=[("RequirementText", "obj-other", "text")])
        atoms, refusals = emit_reified_atoms(SpecDocument(objects=[good, unknown, malformed, wrong_subject]))
        self.assertIn("(Requirement obj-good)", atoms)
        self.assertNotIn("(InventedExecutable obj-unknown run)", atoms)
        self.assertNotIn("(Covers obj-bad)", atoms)
        self.assertNotIn("(RequirementText obj-other text)", atoms)
        self.assertTrue(any(r.reason == "unsupported-fact-predicate:InventedExecutable" for r in refusals))
        self.assertTrue(any(r.reason == "unsupported-fact-arity:Covers:expected-3:got-2" for r in refusals))
        self.assertTrue(any(r.reason == "fact-subject-mismatch:RequirementText:expected-obj-owner:got-obj-other" for r in refusals))

    def test_reified_validation_records_preserve_rationale_and_check_evidence(self):
        doc = compile_source("***definitions***\n- :Task: is work.\n", "validation.plain")
        obligation = add_validation_obligation(doc, "manual-question", doc.items[0].id, "Need Ben to confirm the intended scope.", doc.items[0].span.id)
        check = add_check(doc, obligation, CheckStatus.UNKNOWN, "not enough source evidence")
        atoms, refusals = emit_reified_atoms(doc)
        self.assertTrue(any(atom == f'(validation-rationale {obligation.id} "Need Ben to confirm the intended scope.")' for atom in atoms))
        self.assertTrue(any(atom == f'(check-obligation {check.id} {obligation.id})' for atom in atoms))
        self.assertTrue(any(atom == f'(check-evidence {check.id} "not enough source evidence")' for atom in atoms))

    def test_reified_projection_includes_source_provenance_manifest(self):
        doc = compile_source("***definitions***\n- Task: tracked work.\n", "source_manifest.plain")
        atoms, refusals = emit_reified_atoms(doc)

        plain_file = doc.files[0]
        section = doc.sections[0]
        item = doc.items[0]
        span = item.span
        expected_manifest_atoms = {
            f"(plain-file {plain_file.id} source_manifest.plain {plain_file.digest})",
            f"(section {section.id} {plain_file.id} Definitions 1)",
            f"(derived-from {section.id} {section.span.id})",
            f'(plain-item {item.id} {section.id} none 1 "Task: tracked work.")',
            f"(derived-from {item.id} {span.id})",
            f"(source-span {span.id} {plain_file.id} {span.start_byte} {span.end_byte} {span.start_line} {span.end_line})",
        }
        self.assertTrue(expected_manifest_atoms.issubset(set(atoms)))
        self.assertFalse(any(r.reason.startswith("unsupported-fact") for r in refusals))


if __name__ == "__main__":
    unittest.main()
