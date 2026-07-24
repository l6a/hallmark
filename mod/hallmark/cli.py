# Copyright 2025 the Hallmark Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""Hallmark CLI entrypoint and command wiring."""


import click
import requests
import yaml
from click import ClickException
from git.exc import GitError
from pathlib import Path

from .downloader import DownloadError, download_remote_data
from .error import CloneError, DestinationExistsError, CheckoutError
from .eht_repo_builder import build_repo

from . import Repo  # from "__init__.py"


@click.group()
@click.version_option()
@click.pass_context
def hallmark(ctx):
    """Reproducibility is the hallmark of the scientific method.

    Hallmark is a lightweight package designed to version control and
    manage data products in a complex workflow.
    """
    if ctx.invoked_subcommand in [None, "init", "clone", "build"]:
        return  # do nothing

    try:
        ctx.obj = Repo(".")
    except GitError as e:
        raise ClickException(
            f"Failed to open hallmark repository: {e}")


@hallmark.command(short_help="Initialize a hallmark repository.")
@click.argument("path")
def init(path):
    """Initialize a hallmark repository at PATH.

    If PATH ends with `.hm`, a bare repository is created.
    Otherwise, a `.hm` directory is created inside PATH.
    """
    try:
        Repo.init(path)
    except GitError as e:
        raise ClickException(
            f'Failed to initialize hallmark repository at "{path}": {e}')


@hallmark.command(short_help="Show information of the current directory.")
@click.pass_obj
def info(repo):
    """Show hallmark repository information of the current directory.

    Display local `.hm` and worktree locations for the current
    directory.
    """
    click.echo(f'dot-hallmark repo: "{repo.dothm.path}"')
    click.echo(f'hallmark worktree: "{repo.worktree}"')


@hallmark.command(short_help="Show worktree and staged hallmark state.")
@click.pass_obj
def status(repo):
    """Show hallmark status for the current branch and worktree."""
    snapshot = repo.status()

    click.echo(f'On branch {snapshot["branch"]}')

    staged = snapshot["staged"]
    worktree = snapshot["worktree"]
    untracked = snapshot["untracked"]

    def emit_section(title, entries, fg):
        if not entries:
            return
        click.echo("")
        click.secho(title, fg=fg)
        for label, paths in entries:
            for path in paths:
                click.echo("  " + click.style(f"{label}:   {path}", fg=fg))

    emit_section(
        "Changes to be committed:",
        [
            ("state", staged["state"]),
            ("new file", staged["added"]),
            ("modified", staged["modified"]),
            ("deleted", staged["deleted"]),
        ],
        "green",
    )
    emit_section(
        "Changes not staged for commit:",
        [
            ("modified", worktree["modified"]),
            ("deleted", worktree["deleted"]),
        ],
        "red",
    )
    if untracked:
        click.echo("")
        click.secho("Untracked files:", fg="red")
        for path in untracked:
            click.echo("  " + click.style(path, fg="red"))

    if not any([staged["state"], staged["added"], staged["modified"], staged["deleted"],
                worktree["modified"], worktree["deleted"], untracked]):
        click.echo("")
        click.echo("nothing to commit, working tree clean")


@hallmark.command(short_help="Add files to hallmark index.")
@click.option(
    "--regex",
    "encoding",
    is_flag=True,
    default=False,
    show_default=True,
    help="Enable regex-based encoding rules from config.yml.")
@click.argument("inputs", nargs=-1, required=True)
@click.pass_obj
def add(repo, encoding, inputs):
    """Add files to the hallmark index.

    `hallmark add [--regex] FORMAT` uses the branch format string workflow.
    `hallmark add "."` rebuilds the manifest from current files that match
    the branch `fmt` in `config.yml`.
    Explicit path inputs such as shell-expanded `*` are not supported yet
    with the parameter-based manifest format.
    """
    try:
        if len(inputs) == 1:
            pf = repo.add(inputs[0], encoding)
        else:
            pf = repo.add_paths(list(inputs))
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        raise ClickException(str(e))

    if pf.empty:
        click.echo("No files matched the format string.")
    else:
        click.echo("Changes to be committed")
        click.echo(pf.path.to_string(index=False, header=False))


@hallmark.command("set-config", short_help="Update hallmark branch config.")
@click.option("--fmt")
@click.option("--remote-name")
@click.option("--remote-url")
@click.option("--encoding", "encodings", multiple=True)
@click.pass_obj
def set_config(repo, fmt, remote_name, remote_url, encodings):
    """Update the current branch config.yml."""
    if not any([fmt, remote_name, remote_url, encodings]):
        raise ClickException("No config changes requested.")

    encoding_updates = {}
    for item in encodings:
        if "=" not in item:
            raise ClickException('encoding values must use FIELD=REGEX')
        field, regex = item.split("=", 1)
        if not field:
            raise ClickException('encoding values must use FIELD=REGEX')
        encoding_updates[field] = regex

    try:
        repo.set_config(
            fmt=fmt,
            remote_name=remote_name,
            remote_url=remote_url,
            encoding_updates=encoding_updates or None,
        )
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        raise ClickException(str(e))

    click.echo("Updated hallmark config.")


@hallmark.command(short_help="Commit changes to the repository.")
@click.option("-m", "message", required=True)
@click.pass_obj
def commit(repo, message):
    """Commit changes in the index to the hallmark repository.

    This is analogous to `git commit -m MESSAGE`.
    """
    if repo.commit(message):
        click.echo("Committed staged state changes.")
    else:
        click.echo("No changes added to commit.")


@hallmark.command(short_help="Show hallmark commit history.")
@click.pass_obj
def log(repo):
    """Show commit history for the hallmark state repository."""
    history = repo.log()
    if history:
        click.echo(history)


@hallmark.command(short_help="List hallmark branches.")
@click.pass_obj
def branch(repo):
    """List local hallmark branches."""
    snapshot = repo.branches()
    current = snapshot["current"]
    for name in snapshot["names"]:
        prefix = "*" if name == current else " "
        click.echo(f"{prefix} {name}")


@hallmark.command(short_help="Switch to another branch.")
@click.argument("target_branch")
@click.pass_obj
def checkout(repo, target_branch):
    """Switch branches and rewrite tracked files from branch state.

    This is analogous to `git checkout BRANCH`.
    If the branch does not exist, it is created from the current branch.
    Only hallmark-tracked files are rewritten; unrelated files are left
    alone unless they block restoration of a tracked path.
    """
    try:
        if repo.checkout(target_branch):
            click.echo(f'Switched to branch "{target_branch}".')
    except (GitError, RuntimeError, ValueError, FileNotFoundError, CheckoutError) as e:
        raise ClickException(str(e))


@hallmark.command(short_help="Clone a hallmark repository from a remote URL.")
@click.argument("url")
@click.argument("path")
@click.option(
    "--no-fetch-data",
    is_flag=True,
    help="Skip downloading remote data files after clone.")
@click.option(
    "--max-workers",
    type=int,
    default=4,
    show_default=True,
    help="Number of concurrent downloads.")
def clone(url, path, no_fetch_data, max_workers):
    """Clone a hallmark repository from URL to PATH.

    By default, also downloads data files from the configured remote URL.
    Use --no-fetch-data to skip this step.

    Supports concurrent downloads for efficient retrieval of large datasets.
    """
    try:
        repo = Repo.clone(url, path, fetch_data=False)
        click.echo(f'Successfully cloned to "{path}"')

        if not no_fetch_data:
            _, worktree_path = Repo.lwpaths(path)
            if worktree_path is None:
                click.echo("Bare repository clone; skipping data download.")
                return

            click.echo("Downloading remote data files...")
            results = download_remote_data(
                repo,
                worktree_path,
                max_workers=max_workers,
                show_progress=True,
            )

            if results["failed"] == 0:
                mb_total = results["total_bytes"] / (1024 * 1024)
                click.echo(
                    f"Successfully downloaded {results['succeeded']} files "
                    f"({mb_total:.1f} MB)"
                )
            else:
                click.echo(
                    "Download completed with errors: "
                    f"{results['succeeded']} succeeded, "
                    f"{results['failed']} failed"
                )
                for error in results["errors"]:
                    click.echo(f"  - {error}", err=True)

                if results["failed"] == len(results["errors"]):
                    raise ClickException(
                        f"Failed to download {results['failed']} file(s)"
                    )

    except DestinationExistsError as e:
        click.echo(str(e), err=True)
    except CloneError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    except DownloadError as e:
        raise ClickException(str(e))
    except GitError as e:
        raise ClickException(str(e))
    
    
@hallmark.command(short_help="Build a hallmark repository from a remote dataset.")
@click.argument("directory")
@click.argument("dataset_name")
@click.option(
    "--remote", "remotes", multiple=True,
    help="Remote to record, as NAME=URL or just NAME. May be repeated "
         "for multiple remotes.")
@click.option(
    "--config-file", "config_file",
    type=click.Path(exists=True, dir_okay=False),
    help="Load fmt entries (and remotes, unless --remote is also given) "
         "from an existing config.yml, skipping the prompt entirely.")
@click.option(
    "--fmt", "fmts", multiple=True,
    help="A fmt entry to use directly, as FMT=DB (e.g. "
         "'a{a}_i{i}.h5=data.tsv'). May be repeated for multiple fmts; "
         "skips the prompt entirely.")
def build(directory, dataset_name, remotes, config_file, fmts):
    """
    Build a hallmark repository at DIRECTORY for the remote dataset DATASET_NAME.

    The dataset is fetched from the remote index and stored in a new hallmark 
    repository at DIRECTORY. The remotes can be specified with
    --remote NAME=URL or --remote NAME. 
    if no remotes are specified, the default remote from the dataset index will be used.
    --config-file: Optional path to an existing config.yml to load fmts and remotes
    --fmt: Optional fmt entries to use directly, specified as FMT=DB. May be repeated 
    for multiple fmts.

    Arguments:

        DIRECTORY: The file system path where the hallmark repository will be created.
        DATASET_NAME: The name of the remote dataset to fetch.
        --remote: Optional remote(s) to record, specified as NAME=URL or just NAME. 
        May be repeated for multiple remotes.
        --config-file: Optional path to an existing config.yml to load fmts and remotes.
        --fmt: Optional fmt entries to use directly, specified as FMT=DB.

    Raises:
        ClickException: If there is an error during the build process, such as
        a network error, Git error, or invalid dataset name.

    """
    if config_file and fmts:
        raise ClickException("Use only one of --config-file or --fmt, not both.")
    
    repo_path = Path(directory) / f"{dataset_name}.hm"
    parsed_remotes = []
    for entry in remotes:
        if "=" in entry:
            name, url = entry.split("=", 1)
            parsed_remotes.append({"name": name, "url": url})
        else:
            parsed_remotes.append({"name": entry})

    fmt_entries = None
    if config_file:
        loaded_config = yaml.safe_load(Path(config_file).read_text()) or {}
        fmt_entries = [
            entry for entry in loaded_config.get("data", []) if "fmt" in entry]
        if not fmt_entries:
            raise ClickException(f"No fmt entries found in {config_file!r}.")
        # If no remotes were specified on the command line, use these remotes
        if not parsed_remotes and loaded_config.get("remote"):
            parsed_remotes = loaded_config["remote"]
    elif fmts:
        fmt_entries = []
        for entry in fmts:
            if "=" not in entry:
                raise ClickException(
                    f"--fmt values must use FMT=DB, got {entry!r}.")
            fmt, db = entry.split("=", 1)
            # ensure the db filename ends with .tsv for consistency
            if not db.endswith(".tsv"):
                db += ".tsv"
            fmt_entries.append({"fmt": fmt, "db": db})

    try:
        build_repo(
            repo_path=repo_path,
            dataset_name=dataset_name,
            fmt_entries=fmt_entries,
            remotes=parsed_remotes or None,)
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        raise ClickException(str(e))
    except GitError as e:
        raise ClickException(str(e))
    except requests.exceptions.RequestException as e:
        raise ClickException(f"Failed to reach dataset {dataset_name!r}: {e}")

    click.echo(f'Successfully built hallmark repository at "{repo_path}".')