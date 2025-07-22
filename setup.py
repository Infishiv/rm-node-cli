"""
Setup configuration for RM-Node CLI.
"""
from setuptools import setup, find_packages
import os

def read_requirements():
    """Read requirements from requirements.txt"""
    if os.path.exists('requirements.txt'):
        with open('requirements.txt', 'r') as f:
            return [line.strip() for line in f if line.strip() and not line.startswith('#')]
    return []

def read_readme():
    """Read README file"""
    if os.path.exists('README.md'):
        with open('README.md', 'r', encoding='utf-8') as f:
            return f.read()
    return "RM-Node CLI - Efficient MQTT Node Management"

setup(
    name="rm-node-cli",
    version="1.0.0",
    author="ESP Team",
    author_email="esp-support@example.com",
    description="RM-Node CLI - Efficient MQTT Node Management for ESP RainMaker",
    long_description=read_readme(),
    long_description_content_type="text/markdown",
    url="https://github.com/espressif/rm-node-cli",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        'rm_node_cli': ['configs/*.json'],
    },
    install_requires=read_requirements(),
    entry_points={
        'console_scripts': [
            'rm-node=rm_node_cli.rmnode_cli:main',
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Software Development :: Embedded Systems",
        "Topic :: System :: Networking",
        "Topic :: Communications",
    ],
    python_requires=">=3.7",
    keywords="mqtt iot esp32 rainmaker cli embedded",
    project_urls={
        "Bug Reports": "https://github.com/espressif/rm-node-cli/issues",
        "Source": "https://github.com/espressif/rm-node-cli",
        "Documentation": "https://docs.espressif.com/projects/esp-rainmaker/",
    },
)
