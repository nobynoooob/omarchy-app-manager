from setuptools import setup, find_packages

setup(
    name="omarchy-app-manager",
    version="1.0.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=[
        "PyQt6>=6.0.0",
    ],
    entry_points={
        "console_scripts": [
            "omarchy-app-manager = omarchy_app_manager.__main__:main",
        ],
    },
)
