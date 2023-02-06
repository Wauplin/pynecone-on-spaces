import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="huggingface-pynecone",
    version="0.0.1",
    author="Wauplin",
    description="Simple tool to deploy Pynecone apps on Huggingface Spaces.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://huggingface.co/spaces/Wauplin/pynecone-on-spaces-template",
    license="MIT",
    packages=["src"],
    install_requires=[
        "fire",
        "huggingface_hub",
    ],
    entry_points={
        "console_scripts": [
            "huggingface-pynecone=src.deploy:cli_run",
        ]
    },
)
