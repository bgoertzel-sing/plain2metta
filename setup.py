from setuptools import find_packages, setup


setup(
    name="plain2metta",
    version="0.1.0",
    description="Conservative source-preserving Plain-like specification compiler",
    package_dir={"": "src"},
    packages=find_packages("src"),
    package_data={"specatom_hs": ["evaluation_profiles.json", "vertical_acceptance.json"]},
    entry_points={"console_scripts": ["plain2metta=specatom_hs.cli:main"]},
)
