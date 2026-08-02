from setuptools import setup, find_packages

setup(
    name="glucolens",
    version="1.0.0",
    description="Glooko diabetes data analysis and Omnipod pump settings recommendations",
    author="Ravi",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.9",
    install_requires=[
        "pandas>=1.5.0",
        "numpy>=1.23.0",
        "scipy>=1.9.0",
        "pydantic>=1.10.0",
        "python-dateutil>=2.8.2",
        "streamlit>=1.30.0",
        "pypdf>=4.0.0",
    ],
)
