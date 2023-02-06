import re
import warnings
from pathlib import Path
from typing import List, Union

import fire
import requests
from huggingface_hub import (
    CommitOperationAdd,
    CommitOperationDelete,
    create_commit,
    hf_hub_download,
    whoami,
)
from huggingface_hub.repocard import RepoCard
from huggingface_hub.utils import HfHubHTTPError, build_hf_headers, hf_raise_for_status


def deploy(
    pcconfig_path: Union[str, Path] = "pcconfig.py",
    private: bool = False,
    token: Union[str, None] = None,
) -> None:
    # Check correct path + get app name
    pcconfig_path = Path(pcconfig_path).resolve()
    if not pcconfig_path.is_file():
        raise ValueError(f"Could not find pcconfig file at {pcconfig_path}")
    match = re.search(
        r"app_name=[\"'](?P<app_name>.+)[\"'],", pcconfig_path.read_text()
    )
    if match is None:
        raise ValueError(f"Could not find app_name in {pcconfig_path}")
    app_name = match.groupdict()["app_name"]

    # Check app path exists
    app_path = pcconfig_path.parent / app_name
    if not app_path.is_dir():
        raise ValueError(f"Could not find app folder at {app_path}")

    # Check app path exists
    assets_path = pcconfig_path.parent / "assets"
    if not assets_path.is_dir():
        raise ValueError(f"Could not find assets folder at {assets_path}")

    # Must be logged in!
    username = whoami(token=token)["name"]

    # "curate" app name to avoid conflicts in repo_id
    # => keep only alphanumeric chars + no consecutive "-" + no "-" at beginning or end
    curated_app_name = re.sub(r"-+", "-", re.sub(r"\W", "-", app_name)).strip("-")
    repo_id = f"{username}/{curated_app_name}"
    print(f"Repo ID: {repo_id}")

    # Pre-compute urls
    space_url = f"https://huggingface.co/spaces/{repo_id}"
    space_url_embed = f"https://{username}-{curated_app_name}.hf.space"

    # Duplicate template repo
    response = requests.post(
        "https://huggingface.co/api/spaces/Wauplin/pynecone-on-spaces-template/duplicate",
        headers=build_hf_headers(token=token),
        json={"repository": repo_id, "private": private},
    )

    try:
        hf_raise_for_status(response)
        is_new = True
        print(f"New Space created: {space_url}")
    except HfHubHTTPError as error:
        if response.status_code == 409:
            is_new = False
            print(f"Space already exist: {space_url}")

    # Prepare commit to push pynecone app

    # Delete existing assets and app folders
    # Quite harsh way to sync with the Hub but it works fine for now
    operations: List[Union[CommitOperationAdd, CommitOperationDelete]] = []

    if is_new:
        # Update readme file
        duplicated_repo_card = RepoCard.load(
            repo_id_or_path=repo_id, repo_type="space", token=token
        )
        duplicated_repo_card.data.title = " ".join(
            item.capitalize() for item in curated_app_name.split("-")
        )
        if Path("README.md").is_file():
            # if current folder already contains a README file, upload it
            print("  README.md file found locally. Adding it to the Space.")
            duplicated_repo_card.text = RepoCard.load("README.md").text
        else:
            # otherwise, write a basic README
            print(
                "  README.md file not found locally. Adapting the existing remote one."
            )
            duplicated_repo_card.text = (
                "## 🤗 Spaces x Pynecone"
                "\n\nThis "
                f" {' '.join(part.capitalize() for part in app_name.split('_|-'))}"
                " Space has been duplicated from the [Pynecone on Spaces"
                " template](https://huggingface.co/spaces/Wauplin/pynecone-on-spaces-template)."
                "\n\nTo host and deploy your own Pynecone app on 🤗 Spaces, check out [the"
                " instructions](https://huggingface.co/spaces/Wauplin/pynecone-on-spaces-template/blob/main/README.md)."
            )
        operations.append(
            CommitOperationAdd("README.md", duplicated_repo_card.content.encode())
        )

        # Setup pcconfig.py
        print("  Setup pcconfig.py")
        pcconfig_content = (
            Path(
                hf_hub_download(
                    repo_id=repo_id,
                    repo_type="space",
                    filename="pcconfig_docker.py",
                    token=token,
                )
            )
            .read_text()
            .replace("default_app", app_name)
            .replace(
                "https://wauplin-pynecone-on-spaces-template.hf.space/pynecone-backend",
                f"{space_url_embed}/pynecone-backend",
            )
        )
        operations.append(
            CommitOperationAdd("pcconfig_docker.py", pcconfig_content.encode())
        )

        # Setup Dockerfile
        print("  Setup Dockerfile")
        dockerfile_content = (
            Path(
                hf_hub_download(
                    repo_id=repo_id,
                    repo_type="space",
                    filename="Dockerfile",
                    token=token,
                )
            )
            .read_text()
            .replace("default_app", app_name)
        )
        operations.append(CommitOperationAdd("Dockerfile", dockerfile_content.encode()))
    else:
        print(
            "  Space already configured. Do not update README.md, Dockerfile and pcconfig.py"
        )

    # Add requirements.txt if any
    requirements_path = app_path.parent / "requirements.txt"
    if requirements_path.is_file():
        print("  Sync requirements.txt")
        operations.append(CommitOperationDelete("requirements.txt"))
        operations.append(CommitOperationAdd("requirements.txt", requirements_path))
    else:
        print("  requirements.txt not found")

    # Sync assets/
    # Quite harsh way to sync (delete + upload) but "it works" for now
    print("  Sync assets/ folder")
    operations.append(CommitOperationDelete("assets", is_folder=True))
    for path in assets_path.glob("**/*"):
        if path.is_file():
            operations.append(
                CommitOperationAdd(
                    str(path.relative_to(assets_path.parent)), path_or_fileobj=path
                )
            )

    # Sync app folder
    # Quite harsh way to sync (delete + upload) but "it works" for now
    print("  Sync app folder")
    operations.append(
        CommitOperationDelete("default_app" if is_new else app_name, is_folder=True)
    )
    for path in app_path.glob(f"**/*"):
        if path.is_file() and "__pycache__" not in str(path):
            operations.append(
                CommitOperationAdd(
                    str(path.relative_to(app_path.parent)), path_or_fileobj=path
                )
            )

    # Deploy the app!
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        create_commit(
            repo_id=repo_id,
            repo_type="space",
            commit_message=f"Deploy {app_name}!" if is_new else f"Update {app_name}",
            operations=operations,
            token=token,
        )

    print("Your app has been successfully deployed!")
    print(f"Check it out: {space_url_embed}")


def cli_run():
    fire.Fire({"deploy": deploy})


if __name__ == "__main__":
    deploy()
