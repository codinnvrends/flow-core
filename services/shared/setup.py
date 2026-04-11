from setuptools import setup, find_packages

setup(
    name="flowcore-shared",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "pydantic>=2.7",
        "pydantic-settings>=2.3",
        "asyncpg>=0.29",
        "neo4j>=5.20",
        "confluent-kafka>=2.4",
    ],
)
