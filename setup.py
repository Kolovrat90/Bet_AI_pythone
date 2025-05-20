
from setuptools import setup, find_packages

setup(
    name="betai",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        # сюда все ваши зависимости, например:
        "requests",
        "sqlitedict",
        "pydantic",
        "python-dotenv",
        "streamlit",
        "pytz",
    ],
)
