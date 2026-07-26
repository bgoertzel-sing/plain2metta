import unittest

from specatom_hs.backends.petta import has_padded_object_subtarget
from specatom_hs.identities import is_canonical_object_subtarget


class CanonicalIdentityTests(unittest.TestCase):
    def test_shared_object_subtarget_policy_matches_backend_admission(self):
        ground_truth = {
            "fact:0": True,
            "café": True,
            "": False,
            " fact:0": False,
            "fact:0 ": False,
            "fact:\u200b0": False,
            "fact:\a0": False,
            "fact:\ud8000": False,
            "fact:\ufdd00": False,
            "fact:\ue0000": False,
            "fact:\u03780": False,
            "cafe\u0301": False,
            "\uff46act:0": False,
            "fact:\ufe0f0": False,
        }
        declared_ids = {"object:child"}

        for subtarget, expected in ground_truth.items():
            with self.subTest(subtarget=ascii(subtarget)):
                self.assertEqual(
                    is_canonical_object_subtarget(subtarget),
                    expected,
                )
                self.assertEqual(
                    not has_padded_object_subtarget(
                        f"object:child:{subtarget}", declared_ids
                    ),
                    expected,
                )


if __name__ == "__main__":
    unittest.main()
