from setuptools import setup, find_packages

# Root package is current directory, subpackages are inside it
setup(
    name="agent_bootstrap",
    version="2.1.119",
    description="Autonomous AI Infrastructure: key recognition, resilience, self-configuration",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    packages=['agent_bootstrap'] + [f'agent_bootstrap.{p}' for p in find_packages()],
    package_dir={'agent_bootstrap': '.'},
    python_requires=">=3.8",
    install_requires=[
        "httpx",
        "PyYAML",
        "beautifulsoup4",
        "lxml",
    ],
    extras_require={
        "dev": ["pytest", "pytest-cov"],
    },
    url="https://github.com/chenyuan35/agent-bootstrap",
)
